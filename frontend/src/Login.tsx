import { FormEvent, useState } from "react";
import {
  ActionGroup,
  Alert,
  Button,
  Checkbox,
  Form,
  FormGroup,
  Content,
  TextInput,
  Title,
} from "@patternfly/react-core";

import { ApiError, LoginStep, post, Session } from "./api";
import { Brand } from "./Brand";

type Props = { onLogin: (session: Session) => void; insecure: boolean };

// The login page. The common case (a password prompt) is answered from the
// password field directly; any further PAM prompt, such as a verification
// code, appears as an extra step.
export function Login({ onLogin, insecure }: Props) {
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [keep, setKeep] = useState(false);
  const [step, setStep] = useState<LoginStep | null>(null);
  const [answer, setAnswer] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<LoginStep["messages"]>([]);
  const [busy, setBusy] = useState(false);

  const handle = async (next: LoginStep, firstPrompt: boolean) => {
    setNotes((n) => [...n, ...next.messages]);
    if (next.state === "success" && next.session) {
      onLogin(next.session);
    } else if (next.state === "failure") {
      setError(next.message ?? "Login failed.");
      setStep(null);
      setPassword("");
    } else if (next.state === "prompt") {
      // Answer the first hidden prompt with the password already typed.
      if (firstPrompt && next.prompt && !next.prompt.echo && password) {
        await handle(await post<LoginStep>(`auth/login/${next.id}`, { answer: password }), false);
        return;
      }
      setAnswer("");
      setStep(next);
    }
  };

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The server could not be reached.");
      setStep(null);
    } finally {
      setBusy(false);
    }
  };

  const start = (e: FormEvent) => {
    e.preventDefault();
    setNotes([]);
    void run(async () => handle(await post<LoginStep>("auth/login", { user, keep }), true));
  };

  const reply = (e: FormEvent) => {
    e.preventDefault();
    if (!step?.id) return;
    void run(async () => handle(await post<LoginStep>(`auth/login/${step.id}`, { answer }), false));
  };

  return (
    <div className="asl-login">
      <div className="asl-login-card">
        <Brand subtitle="ASL Web UI" />
        {insecure ? (
          <Alert variant="danger" isInline title="This connection is not secure">
            <p>asl-web-ui only accepts logins over HTTPS, so your password is never sent unencrypted.</p>
            <p>Set up HTTPS in your web server, then open this page with https://.</p>
          </Alert>
        ) : step ? (
          <Form onSubmit={reply}>
            <Content component="p">
              Signed in as <b>{user}</b>. One more step:
            </Content>
            {notes.map((n, i) => (
              <Alert key={i} variant={n.kind === "error" ? "warning" : "info"} isInline isPlain title={n.text} />
            ))}
            <FormGroup label={step.prompt?.text.replace(/:\s*$/, "") || "Answer"} fieldId="login-answer">
              <TextInput
                id="login-answer"
                type={step.prompt?.echo ? "text" : "password"}
                autoComplete="one-time-code"
                value={answer}
                onChange={(_e, v) => setAnswer(v)}
                autoFocus
              />
            </FormGroup>
            <ActionGroup>
              <Button type="submit" isBlock isLoading={busy} isDisabled={busy}>
                Continue
              </Button>
            </ActionGroup>
            <Button variant="link" isInline onClick={() => setStep(null)}>
              Start over
            </Button>
          </Form>
        ) : (
          <Form onSubmit={start}>
            {error && <Alert variant="danger" isInline title={error} />}
            {notes.map((n, i) => (
              <Alert key={i} variant={n.kind === "error" ? "warning" : "info"} isInline isPlain title={n.text} />
            ))}
            <FormGroup label="User name" fieldId="login-user">
              <TextInput id="login-user" autoComplete="username" value={user} onChange={(_e, v) => setUser(v)} autoFocus />
            </FormGroup>
            <FormGroup label="Password" fieldId="login-password">
              <TextInput
                id="login-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(_e, v) => setPassword(v)}
              />
            </FormGroup>
            <Checkbox
              id="login-keep"
              label="Keep me signed in"
              description="Stay signed in on this browser for up to 30 days. Leave unchecked on shared computers."
              isChecked={keep}
              onChange={(_e, v) => setKeep(v)}
            />
            <ActionGroup>
              <Button type="submit" isBlock isLoading={busy} isDisabled={busy || !user}>
                Log in
              </Button>
            </ActionGroup>
          </Form>
        )}
      </div>
      <Title headingLevel="h2" className="pf-v6-screen-reader">
        Login
      </Title>
      <p className="asl-login-foot">
        Log in with your Linux account on this server. Your account must be in the <code>asl-web-ui</code> group.
      </p>
    </div>
  );
}
