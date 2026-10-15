"""The root auth helper's protocol, with PAM replaced by a fake."""

import io
import json

from asl_web_ui_auth import helper, pam


class Script:
    """Feeds client messages to the helper and records what it sends."""

    def __init__(self, *client_msgs):
        self.rfile = io.BytesIO(b"".join(json.dumps(m).encode() + b"\n" for m in client_msgs))
        self.wfile = io.BytesIO()

    @property
    def sent(self):
        return [json.loads(line) for line in self.wfile.getvalue().splitlines()]


def fake_pam(password="secret", code=pam.PAM_SUCCESS, stage="account", messages=()):
    def authenticate(service, user, rhost, respond):
        assert service == "asl-web-ui"
        for text in messages:
            respond(pam.Message(pam.PAM_TEXT_INFO, text))
        answer = respond(pam.Message(pam.PAM_PROMPT_ECHO_OFF, "Password: "))
        if answer != password:
            return pam.Outcome("authenticate", pam.PAM_AUTH_ERR, "Authentication failure")
        return pam.Outcome(stage, code, "detail")

    return authenticate


def run(script, authenticate, member=True, root=False, root_allowed=False):
    helper.converse(
        helper.Channel(script.rfile, script.wfile),
        authenticate=authenticate,
        is_member=lambda user: member,
        root_allowed=lambda: root_allowed,
        is_root_user=lambda user: root,
    )
    return script.sent


def test_successful_login():
    sent = run(Script({"op": "start", "user": "op", "rhost": "203.0.113.9"}, {"op": "answer", "value": "secret"}), fake_pam())
    assert sent == [
        {"op": "prompt", "echo": False, "text": "Password: "},
        {"op": "result", "ok": True, "user": "op"},
    ]


def test_wrong_password_is_denied():
    sent = run(Script({"op": "start", "user": "op", "rhost": "::1"}, {"op": "answer", "value": "nope"}), fake_pam())
    assert sent[-1] == {"op": "result", "ok": False, "reason": "denied"}


def test_correct_password_but_not_in_group():
    sent = run(Script({"op": "start", "user": "op"}, {"op": "answer", "value": "secret"}), fake_pam(), member=False)
    assert sent[-1] == {"op": "result", "ok": False, "reason": "not_permitted"}


def test_expired_password_reported_only_after_success():
    pam_expired = fake_pam(code=pam.PAM_NEW_AUTHTOK_REQD, stage="account")
    sent = run(Script({"op": "start", "user": "op"}, {"op": "answer", "value": "secret"}), pam_expired)
    assert sent[-1] == {"op": "result", "ok": False, "reason": "expired"}


def test_info_messages_are_relayed():
    sent = run(Script({"op": "start", "user": "op"}, {"op": "answer", "value": "secret"}), fake_pam(messages=["Hello"]))
    assert sent[0] == {"op": "info", "text": "Hello"}


def test_root_is_refused_without_running_pam():
    def must_not_run(*args):
        raise AssertionError("PAM must not run for root")

    sent = run(Script({"op": "start", "user": "root"}), must_not_run, root=True)
    assert sent == [{"op": "result", "ok": False, "reason": "denied"}]


def test_invalid_user_name_is_refused():
    sent = run(Script({"op": "start", "user": "../etc"}), fake_pam())
    assert sent == [{"op": "result", "ok": False, "reason": "denied"}]


def test_bad_answer_aborts_conversation():
    sent = run(Script({"op": "start", "user": "op"}, {"op": "answer", "value": 5}), fake_pam())
    assert sent[-1] == {"op": "result", "ok": False, "reason": "denied"}


def test_oversized_message_is_a_protocol_error():
    script = Script()
    script.rfile = io.BytesIO(b"x" * (helper.MAX_LINE + 10) + b"\n")
    try:
        run(script, fake_pam())
    except helper.ProtocolError as exc:
        assert "too long" in str(exc)
    else:
        raise AssertionError("expected ProtocolError")


def test_real_pam_binding_loads():
    # The ctypes binding must load libpam and expose the entry points.
    assert callable(pam.authenticate)
