import { ReactNode, useCallback, useState } from "react";
import {
  Alert,
  Button,
  Content,
  ExpandableSection,
  List,
  ListItem,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
} from "@patternfly/react-core";

import { ApiError, message } from "./api";
import { fixOwnership } from "./backupsApi";
import { useAsteriskControl } from "./AsteriskControl";
import { DiffView } from "./DiffView";
import { Applied, applyChange, ChangePlan, planChange } from "./nodesApi";
import { useReauth } from "./Reauth";

function FileDiffs({ plan }: { plan: ChangePlan }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  return (
    <div className="asl-stack">
      {plan.files.map((f, i) => (
        <ExpandableSection
          key={f.name}
          toggleText={f.name.startsWith("/") ? f.name : `/etc/asterisk/${f.name}`}
          isExpanded={open[f.name] ?? i === 0}
          onToggle={(_e, v) => setOpen((o) => ({ ...o, [f.name]: v }))}
        >
          <DiffView diff={f.diff} />
        </ExpandableSection>
      ))}
    </div>
  );
}

type Review = { plan: ChangePlan; resolve: (result: Applied | null) => void };

// Plans a change, shows exactly what it does to which files, and applies it
// when confirmed. Afterwards offers to restart Asterisk when needed.
// propose() rejects with the planning error (so forms can show it by the
// field) and resolves to null when cancelled or when nothing changes.
export function useChange(): [
  ReactNode,
  (op: string, params: Record<string, unknown>) => Promise<Applied | null>,
  (ops: Record<string, unknown>[]) => Promise<Applied | null>,
] {
  const [review, setReview] = useState<Review | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{ applied: Applied; tune: boolean } | null>(null);
  const [nothing, setNothing] = useState(false);
  const [reauthElement, withReauth] = useReauth();
  const [controlElement, control] = useAsteriskControl();

  const [fix, setFix] = useState<{ files: string[]; resolve: (ok: boolean) => void } | null>(null);
  const [fixError, setFixError] = useState<string | null>(null);

  const run = useCallback(async (body: Record<string, unknown>) => {
    let plan;
    try {
      plan = await planChange(body);
    } catch (err) {
      // Root-owned files (edited with sudo): offer to give them back, then plan again.
      if (!(err instanceof ApiError && err.code === "not_writable")) throw err;
      const files = (err.data.files as string[]) ?? [];
      const ok = await new Promise<boolean>((resolve) => setFix({ files, resolve }));
      setFix(null);
      if (!ok) return null;
      plan = await planChange(body);
    }
    if ("unchanged" in plan) {
      setNothing(true);
      return null;
    }
    setError(null);
    return await new Promise<Applied | null>((resolve) => setReview({ plan, resolve }));
  }, []);
  const propose = useCallback((op: string, params: Record<string, unknown>) => run({ op, ...params }), [run]);
  const proposeOps = useCallback((ops: Record<string, unknown>[]) => run({ ops }), [run]);

  const apply = async () => {
    if (!review) return;
    setBusy(true);
    setError(null);
    try {
      const applied = await withReauth(() => applyChange(review.plan.id, review.plan.errors.length > 0));
      if (!applied) return;
      review.resolve(applied);
      if (applied.restart || applied.warnings.length) setDone({ applied, tune: review.plan.tune });
      setReview(null);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };

  const cancel = () => {
    review?.resolve(null);
    setReview(null);
  };

  const doFix = async () => {
    if (!fix) return;
    setFixError(null);
    try {
      const res = await withReauth(() => fixOwnership(fix.files));
      if (res) fix.resolve(true);
    } catch (err) {
      setFixError(message(err));
    }
  };

  const plan = review?.plan;
  const element = (
    <>
      {reauthElement}
      {controlElement}
      <Modal isOpen={fix !== null} onClose={() => fix?.resolve(false)} variant="small" aria-labelledby="fix-title">
        <ModalHeader title="Some files belong to another user" labelId="fix-title" titleIconVariant="warning" />
        <ModalBody>
          <div className="asl-stack">
            <p>
              The web interface cannot change these files, usually because they were edited with sudo. Give them back
              to the asterisk user?
            </p>
            <List>{fix?.files.map((f) => <ListItem key={f}><code>{f}</code></ListItem>)}</List>
            {fixError && <Alert variant="danger" isInline isPlain title={fixError} />}
          </div>
        </ModalBody>
        <ModalFooter>
          <Button onClick={doFix}>Fix permissions</Button>
          <Button variant="link" onClick={() => fix?.resolve(false)}>Cancel</Button>
        </ModalFooter>
      </Modal>
      <Modal isOpen={plan !== undefined} onClose={cancel} variant="large" aria-labelledby="change-title">
        <ModalHeader
          title={plan ? `Review: ${plan.action}` : ""}
          labelId="change-title"
          titleIconVariant={plan?.errors.length ? "danger" : undefined}
        />
        <ModalBody>
          {plan && (
            <div className="asl-stack">
              {error && <Alert variant="danger" isInline title={error} />}
              {plan.errors.length > 0 && (
                <Alert variant="danger" isInline title="This change would leave a file that Asterisk rejects">
                  <ul>
                    {plan.errors.map((f, i) => (
                      <li key={i}>
                        {f.file}
                        {f.line ? ` line ${f.line}` : ""}: {f.message}
                      </li>
                    ))}
                  </ul>
                </Alert>
              )}
              {plan.notes.map((n, i) => (
                <Alert key={i} variant={n.severity === "warning" ? "warning" : "info"} isInline isPlain title={n.text} />
              ))}
              {plan.allmon3.length > 0 && (
                <Alert variant="warning" isInline title="Allmon3 needs the same change">
                  <p>The web interface could not read Allmon3's settings. Do this by hand:</p>
                  <List>
                    {plan.allmon3.map((t) => (
                      <ListItem key={t}>{t}</ListItem>
                    ))}
                  </List>
                </Alert>
              )}
              <Content component="p">
                {plan.files.length === 1 ? "One file changes" : `${plan.files.length} files change`}. A snapshot of
                each is kept before it is written.
              </Content>
              <FileDiffs plan={plan} />
              {plan.restart && (
                <Content component="p" className="asl-sub">
                  Asterisk must restart before the change takes effect.
                </Content>
              )}
            </div>
          )}
        </ModalBody>
        <ModalFooter>
          <Button
            variant={plan?.errors.length || plan?.reauth ? "danger" : "primary"}
            onClick={apply}
            isLoading={busy}
            isDisabled={busy}
          >
            {plan?.errors.length ? "Apply anyway" : "Apply"}
          </Button>
          <Button variant="link" onClick={cancel}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>
      <Modal isOpen={nothing} onClose={() => setNothing(false)} variant="small" aria-labelledby="nothing-title">
        <ModalHeader title="Nothing to change" labelId="nothing-title" />
        <ModalBody>The configuration already has these settings.</ModalBody>
        <ModalFooter>
          <Button onClick={() => setNothing(false)}>Close</Button>
        </ModalFooter>
      </Modal>
      <Modal isOpen={done !== null} onClose={() => setDone(null)} variant="small" aria-labelledby="done-title">
        <ModalHeader title="Saved" labelId="done-title" titleIconVariant="success" />
        <ModalBody>
          <div className="asl-stack">
            {done?.applied.warnings.map((w) => <Alert key={w} variant="warning" isInline isPlain title={w} />)}
            {done?.applied.restart && (
              <p>
                Asterisk must restart for the change to take effect.
                {done.tune && " Afterwards, tune the radio interface."}
              </p>
            )}
          </div>
        </ModalBody>
        <ModalFooter>
          {done?.applied.restart && (
            <Button
              onClick={async () => {
                setDone(null);
                await control("restart");
              }}
            >
              Restart Asterisk now
            </Button>
          )}
          <Button variant="link" onClick={() => setDone(null)}>
            {done?.applied.restart ? "Later" : "Close"}
          </Button>
        </ModalFooter>
      </Modal>
    </>
  );
  return [element, propose, proposeOps];
}
