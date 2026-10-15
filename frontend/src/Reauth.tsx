import { FormEvent, ReactNode, useCallback, useRef, useState } from "react";
import { Alert, Button, Form, FormGroup, Modal, ModalBody, ModalFooter, ModalHeader, TextInput } from "@patternfly/react-core";

import { ApiError, LoginStep, message, post } from "./api";

// Asks for the password again (the same PAM conversation as logging in, so a
// verification code works too) before a destructive action.
function ReauthModal({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const [step, setStep] = useState<LoginStep | null>(null);
  const [answer, setAnswer] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const started = useRef(false);

  const handle = (next: LoginStep) => {
    if (next.state === "success") onDone();
    else if (next.state === "failure") {
      setError(next.message ?? "That did not work. Try again.");
      setStep(null);
      started.current = false;
    } else setStep(next);
    setAnswer("");
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      let current = step;
      if (!current) {
        current = await post<LoginStep>("auth/reauth", {});
        started.current = true;
        if (current.state !== "prompt") return handle(current);
      }
      handle(await post<LoginStep>(`auth/reauth/${current.id}`, { answer }));
    } catch (err) {
      setError(message(err));
      setStep(null);
    } finally {
      setBusy(false);
    }
  };

  const label = step?.prompt?.text.replace(/:\s*$/, "") || "Password";
  return (
    <Modal isOpen onClose={onCancel} variant="small" aria-labelledby="reauth-title">
      <ModalHeader title="Confirm it's you" labelId="reauth-title" />
      <ModalBody>
        <Form id="reauth-form" onSubmit={submit}>
          <p>This action needs your password again.</p>
          {error && <Alert variant="danger" isInline title={error} />}
          {step?.messages.map((m, i) => <Alert key={i} variant="info" isInline isPlain title={m.text} />)}
          <FormGroup label={label} fieldId="reauth-answer">
            <TextInput
              id="reauth-answer"
              type={step?.prompt?.echo ? "text" : "password"}
              autoComplete={step ? "one-time-code" : "current-password"}
              value={answer}
              onChange={(_e, v) => setAnswer(v)}
              autoFocus
            />
          </FormGroup>
        </Form>
      </ModalBody>
      <ModalFooter>
        <Button type="submit" form="reauth-form" isLoading={busy} isDisabled={busy || !answer}>
          Continue
        </Button>
        <Button variant="link" onClick={onCancel}>
          Cancel
        </Button>
      </ModalFooter>
    </Modal>
  );
}

// Runs an action; if the server asks for the password again, shows the
// dialog and runs the action once more after a successful entry.
export function useReauth(): [ReactNode, <T>(action: () => Promise<T>) => Promise<T | undefined>] {
  const [pending, setPending] = useState<{ resolve: (ok: boolean) => void } | null>(null);

  const run = useCallback(async <T,>(action: () => Promise<T>): Promise<T | undefined> => {
    try {
      return await action();
    } catch (err) {
      if (!(err instanceof ApiError && err.code === "reauth_required")) throw err;
      const ok = await new Promise<boolean>((resolve) => setPending({ resolve }));
      setPending(null);
      if (!ok) return undefined;
      return await action();
    }
  }, []);

  const element = pending ? (
    <ReauthModal onDone={() => pending.resolve(true)} onCancel={() => pending.resolve(false)} />
  ) : null;
  return [element, run];
}
