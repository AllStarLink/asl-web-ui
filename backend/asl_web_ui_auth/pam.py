"""Minimal ctypes binding to Linux-PAM: authenticate and check the account.

Only what the helper needs: pam_start, pam_set_item(PAM_RHOST),
pam_authenticate, pam_acct_mgmt and pam_end, with a conversation callback
that lets the caller answer each prompt.
"""

import ctypes
import ctypes.util
from collections.abc import Callable
from dataclasses import dataclass

# Message styles (security/_pam_types.h)
PAM_PROMPT_ECHO_OFF = 1
PAM_PROMPT_ECHO_ON = 2
PAM_ERROR_MSG = 3
PAM_TEXT_INFO = 4

# Return codes
PAM_SUCCESS = 0
PAM_PERM_DENIED = 6
PAM_AUTH_ERR = 7
PAM_USER_UNKNOWN = 10
PAM_MAXTRIES = 11
PAM_NEW_AUTHTOK_REQD = 12
PAM_ACCT_EXPIRED = 13
PAM_CONV_ERR = 19
PAM_ABORT = 26

# Item types
PAM_RHOST = 4

# Flags
PAM_SILENT = 0x8000
PAM_DISALLOW_NULL_AUTHTOK = 0x0001


class _Message(ctypes.Structure):
    _fields_ = [("msg_style", ctypes.c_int), ("msg", ctypes.c_char_p)]


class _Response(ctypes.Structure):
    _fields_ = [("resp", ctypes.c_void_p), ("resp_retcode", ctypes.c_int)]


_CONV_FUNC = ctypes.CFUNCTYPE(
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(ctypes.POINTER(_Message)),
    ctypes.POINTER(ctypes.POINTER(_Response)),
    ctypes.c_void_p,
)


class _Conv(ctypes.Structure):
    _fields_ = [("conv", _CONV_FUNC), ("appdata_ptr", ctypes.c_void_p)]


_libpam = ctypes.CDLL(ctypes.util.find_library("pam") or "libpam.so.0")
_libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")

_libc.calloc.restype = ctypes.c_void_p
_libc.calloc.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
_libc.strdup.restype = ctypes.c_void_p
_libc.strdup.argtypes = [ctypes.c_char_p]
_libc.free.argtypes = [ctypes.c_void_p]

_pam_start = _libpam.pam_start
_pam_start.restype = ctypes.c_int
_pam_start.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(_Conv), ctypes.POINTER(ctypes.c_void_p)]
_pam_end = _libpam.pam_end
_pam_end.restype = ctypes.c_int
_pam_end.argtypes = [ctypes.c_void_p, ctypes.c_int]
_pam_set_item = _libpam.pam_set_item
_pam_set_item.restype = ctypes.c_int
_pam_set_item.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
_pam_authenticate = _libpam.pam_authenticate
_pam_authenticate.restype = ctypes.c_int
_pam_authenticate.argtypes = [ctypes.c_void_p, ctypes.c_int]
_pam_acct_mgmt = _libpam.pam_acct_mgmt
_pam_acct_mgmt.restype = ctypes.c_int
_pam_acct_mgmt.argtypes = [ctypes.c_void_p, ctypes.c_int]
_pam_strerror = _libpam.pam_strerror
_pam_strerror.restype = ctypes.c_char_p
_pam_strerror.argtypes = [ctypes.c_void_p, ctypes.c_int]


@dataclass(frozen=True)
class Message:
    style: int  # one of the PAM_* message styles
    text: str


# Called for each message. For prompts it returns the answer; for info and
# error messages the return value is ignored. Returning None for a prompt
# aborts the conversation.
Responder = Callable[[Message], str | None]


@dataclass(frozen=True)
class Outcome:
    stage: str  # "start", "authenticate" or "account"
    code: int
    detail: str

    @property
    def ok(self) -> bool:
        return self.code == PAM_SUCCESS


def _decode(raw: bytes | None) -> str:
    return (raw or b"").decode("utf-8", errors="replace")


def authenticate(service: str, user: str, rhost: str, respond: Responder) -> Outcome:
    """Run pam_authenticate then pam_acct_mgmt for user."""

    def conv(num_msg, msgs, resp_out, _appdata):
        responses = _libc.calloc(num_msg, ctypes.sizeof(_Response))
        if not responses:
            return PAM_CONV_ERR
        resp_array = ctypes.cast(responses, ctypes.POINTER(_Response))
        try:
            for i in range(num_msg):
                m = msgs[i].contents
                message = Message(m.msg_style, _decode(m.msg))
                answer = respond(message)
                if m.msg_style in (PAM_PROMPT_ECHO_OFF, PAM_PROMPT_ECHO_ON):
                    if answer is None:
                        raise _Aborted
                    resp_array[i].resp = _libc.strdup(answer.encode("utf-8"))
                    resp_array[i].resp_retcode = 0
        except _Aborted:
            for i in range(num_msg):
                if resp_array[i].resp:
                    _libc.free(resp_array[i].resp)
            _libc.free(responses)
            return PAM_CONV_ERR
        except Exception:  # never let an exception unwind through C
            _libc.free(responses)
            return PAM_CONV_ERR
        resp_out[0] = resp_array
        return PAM_SUCCESS

    callback = _CONV_FUNC(conv)  # kept referenced until pam_end
    conversation = _Conv(callback, None)
    handle = ctypes.c_void_p()
    rc = _pam_start(service.encode(), user.encode(), ctypes.byref(conversation), ctypes.byref(handle))
    if rc != PAM_SUCCESS:
        return Outcome("start", rc, f"pam_start failed ({rc})")

    rhost_buf = ctypes.create_string_buffer(rhost.encode())
    _pam_set_item(handle, PAM_RHOST, ctypes.cast(rhost_buf, ctypes.c_void_p))

    stage = "authenticate"
    rc = _pam_authenticate(handle, PAM_DISALLOW_NULL_AUTHTOK)
    if rc == PAM_SUCCESS:
        stage = "account"
        rc = _pam_acct_mgmt(handle, PAM_DISALLOW_NULL_AUTHTOK)
    detail = _decode(_pam_strerror(handle, rc))
    _pam_end(handle, rc)
    return Outcome(stage, rc, detail)


class _Aborted(Exception):
    pass
