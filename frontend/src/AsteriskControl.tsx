import { ReactNode, useCallback, useState } from "react";
import { Alert, Button, Modal, ModalBody, ModalFooter, ModalHeader } from "@patternfly/react-core";

import { ApiError, message } from "./api";
import { asteriskAction } from "./nodesApi";
import { useReauth } from "./Reauth";
import { go } from "./useRoute";

type Action = "restart" | "start" | "stop";
type FirstError = { file: string; line: number | null; message: string } | null;

const VERB: Record<Action, string> = { restart: "Restart", start: "Start", stop: "Stop" };
const DOING: Record<Action, string> = { restart: "Restarting", start: "Starting", stop: "Stopping" };

// Start, stop or restart Asterisk. Starting or restarting while rpt.conf has
// errors asks first (app_rpt would start no node); stopping asks for the
// password again.
export function useAsteriskControl(): [ReactNode, (action: Action) => Promise<boolean>] {
  const [reauthElement, withReauth] = useReauth();
  const [blocked, setBlocked] = useState<{ action: Action; error: FirstError; resolve: (run: boolean) => void } | null>(
    null,
  );
  const [busy, setBusy] = useState<Action | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const act = useCallback(
    async (action: Action): Promise<boolean> => {
      setFailure(null);
      setBusy(action);
      try {
        try {
          await withReauth(() => asteriskAction(action));
        } catch (err) {
          if (!(err instanceof ApiError && err.code === "rpt_errors")) throw err;
          setBusy(null);
          const run = await new Promise<boolean>((resolve) =>
            setBlocked({ action, error: (err.data.first_error as FirstError) ?? null, resolve }),
          );
          setBlocked(null);
          if (!run) return false;
          setBusy(action);
          await asteriskAction(action, true);
        }
        return true;
      } catch (err) {
        setFailure(message(err));
        return false;
      } finally {
        setBusy(null);
      }
    },
    [withReauth],
  );

  const element = (
    <>
      {reauthElement}
      <Modal isOpen={busy !== null} variant="small" aria-label="Working" disableFocusTrap>
        <ModalBody>{busy ? `${DOING[busy]} Asterisk…` : ""}</ModalBody>
      </Modal>
      <Modal isOpen={failure !== null} onClose={() => setFailure(null)} variant="small" aria-labelledby="ctl-fail">
        <ModalHeader title="That did not work" titleIconVariant="danger" labelId="ctl-fail" />
        <ModalBody>{failure}</ModalBody>
        <ModalFooter>
          <Button onClick={() => setFailure(null)}>Close</Button>
        </ModalFooter>
      </Modal>
      <Modal isOpen={blocked !== null} onClose={() => blocked?.resolve(false)} variant="small" aria-labelledby="ctl-rpt">
        <ModalHeader title="rpt.conf has errors" titleIconVariant="danger" labelId="ctl-rpt" />
        <ModalBody>
          <p>With rpt.conf as it is, app_rpt starts no node: your nodes would be off the air.</p>
          {blocked?.error && (
            <Alert variant="danger" isInline isPlain className="asl-gap" title={
              `${blocked.error.file}${blocked.error.line ? ` line ${blocked.error.line}` : ""}: ${blocked.error.message}`
            } />
          )}
        </ModalBody>
        <ModalFooter>
          <Button
            onClick={() => {
              blocked?.resolve(false);
              go(`config/${encodeURIComponent(blocked?.error?.file ?? "rpt.conf")}`);
            }}
          >
            Fix in editor
          </Button>
          <Button variant="danger" onClick={() => blocked?.resolve(true)}>
            {blocked ? `${VERB[blocked.action]} anyway` : ""}
          </Button>
          <Button variant="link" onClick={() => blocked?.resolve(false)}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>
    </>
  );
  return [element, act];
}
