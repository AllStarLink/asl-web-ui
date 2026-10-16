import { ReactNode, useCallback, useState } from "react";
import { Alert, Button, Content, Modal, ModalBody, ModalFooter, ModalHeader } from "@patternfly/react-core";

import { message } from "./api";
import { Allmon3Applied, Allmon3Finding, Allmon3Plan, Allmon3Unchanged, applyAllmon3Plan } from "./allmon3Api";
import { DiffView } from "./DiffView";

export function Findings({ findings, errorsTitle = "Allmon3 would not load the file as it is" }:
  { findings: Allmon3Finding[]; errorsTitle?: string }) {
  const errors = findings.filter((f) => f.severity === "error");
  const warnings = findings.filter((f) => f.severity !== "error");
  const line = (f: Allmon3Finding) => `${f.line ? `Line ${f.line}: ` : ""}${f.message}`;
  return (
    <>
      {errors.length > 0 && (
        <Alert variant="danger" isInline title={errorsTitle}>
          <ul>{errors.map((f, i) => <li key={i}>{line(f)}</li>)}</ul>
        </Alert>
      )}
      {warnings.length > 0 && (
        <Alert variant="warning" isInline isPlain title="Check these">
          <ul>{warnings.map((f, i) => <li key={i}>{line(f)}</li>)}</ul>
        </Alert>
      )}
    </>
  );
}

type Review = { plan: Allmon3Plan; resolve: (applied: Allmon3Applied | null) => void };

// How a reviewed plan is saved: by default one of Allmon3's files (Allmon3
// is restarted to load it). The SA818 settings file passes its own.
export type ReviewTarget = {
  apply: (id: string, confirmErrors: boolean) => Promise<Allmon3Applied>;
  dir: string;
  note: string;
  errorsBlock?: boolean; // errors cannot be saved anyway
  errorsTitle?: string;
};

const ALLMON3: ReviewTarget = {
  apply: applyAllmon3Plan,
  dir: "/etc/allmon3",
  note: "Allmon3 is restarted to load the change; anyone logged in to Allmon3 has to log in again.",
};

// Shows a planned change to one of Allmon3's files, and saves it when
// confirmed. review() rejects with the planning error and resolves to null
// when cancelled or nothing changes.
export function useAllmon3Review(target: ReviewTarget = ALLMON3):
  [ReactNode, (planned: Promise<Allmon3Plan | Allmon3Unchanged>) => Promise<Allmon3Applied | null>] {
  const [review, setReview] = useState<Review | null>(null);
  const [nothing, setNothing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = useCallback(async (planned: Promise<Allmon3Plan | Allmon3Unchanged>) => {
    const plan = await planned;
    if ("unchanged" in plan) {
      setNothing(true);
      return null;
    }
    setError(null);
    return await new Promise<Allmon3Applied | null>((resolve) => setReview({ plan, resolve }));
  }, []);

  const save = async () => {
    if (!review) return;
    setBusy(true);
    setError(null);
    try {
      const errors = review.plan.findings.some((f) => f.severity === "error");
      const applied = await target.apply(review.plan.id, errors);
      review.resolve(applied);
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

  const plan = review?.plan;
  const errors = plan?.findings.some((f) => f.severity === "error");
  const element = (
    <>
      <Modal isOpen={plan !== undefined} onClose={cancel} variant="large" aria-labelledby="a3-review-title">
        <ModalHeader title={plan ? `Review: ${plan.action}` : ""} labelId="a3-review-title"
                     titleIconVariant={errors ? "danger" : undefined} />
        <ModalBody>
          {plan && (
            <div className="asl-stack">
              {error && <Alert variant="danger" isInline title={error} />}
              <Findings findings={plan.findings} errorsTitle={target.errorsTitle} />
              {plan.created && <Content component="p">Creates <code>{target.dir}/{plan.name}</code>.</Content>}
              <DiffView diff={plan.diff} />
              <Content component="p" className="asl-sub">{target.note}</Content>
            </div>
          )}
        </ModalBody>
        <ModalFooter>
          <Button variant={errors ? "danger" : "primary"} onClick={save} isLoading={busy}
                  isDisabled={busy || (errors && target.errorsBlock)}>
            {errors && !target.errorsBlock ? "Save anyway" : "Save"}
          </Button>
          <Button variant="link" onClick={cancel}>Cancel</Button>
        </ModalFooter>
      </Modal>
      <Modal isOpen={nothing} onClose={() => setNothing(false)} variant="small" aria-labelledby="a3-nothing-title">
        <ModalHeader title="Nothing to change" labelId="a3-nothing-title" />
        <ModalBody>The file already says this.</ModalBody>
        <ModalFooter>
          <Button onClick={() => setNothing(false)}>Close</Button>
        </ModalFooter>
      </Modal>
    </>
  );
  return [element, start];
}
