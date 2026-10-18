import { ReactNode, useCallback, useState } from "react";
import { Alert, Button, Modal, ModalBody, ModalFooter, ModalHeader, Spinner } from "@patternfly/react-core";

import { ApiError, message } from "./api";
import { JobState, jobState, Started } from "./backupsApi";

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

// Some jobs reload the web server the UI is reached through (the HTTPS
// certificate job does, several times), which can drop a request. The job
// keeps running, so polls that do not reach the server are retried this long.
const UNREACHABLE_FOR = 30000;

// Runs a server-side job and shows its progress until it finishes.
// run() resolves to the final state (or null if it could not start).
export function useJob(): [ReactNode, (title: string, start: () => Promise<Started | undefined>) => Promise<JobState | null>] {
  const [state, setState] = useState<{ title: string; lines: string[]; done: boolean; error: string | null } | null>(null);
  const [closer, setCloser] = useState<(() => void) | null>(null);

  const run = useCallback(async (title: string, start: () => Promise<Started | undefined>) => {
    setState({ title, lines: [], done: false, error: null });
    let started: Started | undefined;
    try {
      started = await start();
    } catch (err) {
      setState({ title, lines: [], done: true, error: message(err) });
      await new Promise<void>((resolve) => setCloser(() => resolve));
      setState(null);
      return null;
    }
    if (!started) {
      setState(null);
      return null;
    }
    let from = 0;
    let lines: string[] = [];
    let last: JobState | null = null;
    let unreachable: number | null = null;
    for (;;) {
      try {
        last = await jobState(started.job, from);
        unreachable = null;
      } catch (err) {
        if (!(err instanceof ApiError)) {
          unreachable ??= Date.now();
          if (Date.now() - unreachable < UNREACHABLE_FOR) {
            await wait(700);
            continue;
          }
        }
        setState({ title, lines, done: true, error: message(err) });
        break;
      }
      lines = [...lines, ...last.lines];
      from = last.next;
      setState({ title, lines, done: last.done, error: last.error });
      if (last.done) break;
      await wait(700);
    }
    await new Promise<void>((resolve) => setCloser(() => resolve));
    setState(null);
    return last;
  }, []);

  const element = (
    <Modal isOpen={state !== null} variant="medium" aria-labelledby="job-title"
           onClose={state?.done ? () => closer?.() : undefined}>
      <ModalHeader title={state?.title ?? ""} labelId="job-title"
                   titleIconVariant={state?.done ? (state.error ? "danger" : "success") : undefined} />
      <ModalBody>
        <div className="asl-stack">
          {!state?.done && <Spinner size="lg" aria-label="Working" />}
          {state && state.lines.length > 0 && <pre className="asl-job-log">{state.lines.join("\n")}</pre>}
          {state?.error && <Alert variant="danger" isInline title={state.error} />}
        </div>
      </ModalBody>
      <ModalFooter>
        <Button onClick={() => state?.done && closer?.()} isAriaDisabled={!state?.done}>
          {state?.done ? "Close" : "Working…"}
        </Button>
      </ModalFooter>
    </Modal>
  );
  return [element, run];
}
