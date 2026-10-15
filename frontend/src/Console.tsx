import "@xterm/xterm/css/xterm.css";

import { useEffect, useRef, useState } from "react";
import { Alert, Button, Modal, ModalBody, ModalFooter, ModalHeader } from "@patternfly/react-core";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";

import { Status, wsUrl } from "./api";
import { go } from "./useRoute";

// Commands that make app_rpt read rpt.conf again. app_rpt 3.10 disables every
// node when the file is invalid, yet still reports success.
const RELOADS = /^\s*(module\s+reload(\s+app_rpt(\.so)?)?|core\s+reload|rpt\s+restart|core\s+restart\s+(now|gracefully|when\s+convenient))\s*$/i;

// What has been typed on the current line, as far as we can tell. Becomes
// null after history recall, completion or cursor movement, when the line
// on the server is no longer known.
export class LineTracker {
  line: string | null = "";

  feed(data: string): void {
    if (data.startsWith("\x1b") || data === "\t") {
      this.line = null;
      return;
    }
    for (const ch of data) {
      if (ch === "\r" || ch === "\n" || ch === "\x03" || ch === "\x15") this.line = "";
      else if (ch === "\x7f" || ch === "\b") this.line = this.line === null ? null : this.line.slice(0, -1);
      else if (ch < " ") this.line = null;
      else if (this.line !== null) this.line += ch;
    }
  }
}

export function isReload(line: string | null): boolean {
  return line !== null && RELOADS.test(line);
}

// The Asterisk CLI (asterisk -rvvv on the server) in a terminal.
export function Console({ status }: { status: Status | null }) {
  const host = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"connecting" | "open" | "closed">("connecting");
  const [attempt, setAttempt] = useState(0);
  const errors = useRef(0);
  errors.current = status?.config?.rpt_errors ?? 0;
  const firstError = status?.config?.rpt_first_error ?? null;
  // Set while a reload command waits for confirmation; calling it with true sends Enter.
  const [held, setHeld] = useState<{ command: string; finish: (run: boolean) => void } | null>(null);

  useEffect(() => {
    if (!host.current) return;
    const term = new Terminal({
      cursorBlink: true,
      fontFamily: '"Red Hat Mono", "DejaVu Sans Mono", monospace',
      fontSize: 14,
      theme: { background: "#0f1214", foreground: "#d5dde3" },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(host.current);
    fit.fit();

    const socket = new WebSocket(wsUrl("ws/console"));
    socket.binaryType = "arraybuffer";
    const sendSize = () => {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
    };
    socket.onopen = () => {
      setState("open");
      sendSize();
      term.focus();
    };
    socket.onmessage = (event) => term.write(new Uint8Array(event.data as ArrayBuffer));
    socket.onclose = () => setState("closed");
    const send = (data: string) => {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "input", data }));
    };
    const tracker = new LineTracker();
    const input = term.onData((data) => {
      if (data === "\r" && errors.current > 0 && isReload(tracker.line)) {
        const command = (tracker.line ?? "").trim();
        setHeld({
          command,
          finish: (run) => {
            setHeld(null);
            tracker.feed(run ? "\r" : "\x15");
            send(run ? "\r" : "\x15");
            term.focus();
          },
        });
        return;
      }
      tracker.feed(data);
      send(data);
    });
    const observer = new ResizeObserver(() => {
      fit.fit();
      sendSize();
    });
    observer.observe(host.current);

    return () => {
      observer.disconnect();
      input.dispose();
      socket.close();
      term.dispose();
    };
  }, [attempt]);

  return (
    <div className="asl-console">
      {state === "closed" && (
        <Alert
          variant="info"
          isInline
          title="The console session ended"
          actionLinks={
            <Button variant="link" isInline onClick={() => { setState("connecting"); setAttempt((a) => a + 1); }}>
              Reconnect
            </Button>
          }
        />
      )}
      <div ref={host} className="asl-terminal" />
      <Modal isOpen={held !== null} onClose={() => held?.finish(false)} variant="small" aria-labelledby="reload-title">
        <ModalHeader title="rpt.conf has errors" titleIconVariant="danger" labelId="reload-title" />
        <ModalBody>
          <p>
            <code>{held?.command}</code> makes app_rpt read rpt.conf again. With the file as it is, every node goes off
            the air, even though the command reports success.
          </p>
          {firstError && (
            <p className="asl-gap">
              {firstError.file}
              {firstError.line ? ` line ${firstError.line}` : ""}: {firstError.message}
            </p>
          )}
        </ModalBody>
        <ModalFooter>
          <Button
            onClick={() => {
              held?.finish(false);
              go(`config/${encodeURIComponent(firstError?.file ?? "rpt.conf")}`);
            }}
          >
            Fix in editor
          </Button>
          <Button variant="danger" onClick={() => held?.finish(true)}>
            Run anyway
          </Button>
          <Button variant="link" onClick={() => held?.finish(false)}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>
      <p className="asl-sub">
        Equivalent to <code>asterisk -r</code>, running as the asterisk user. There is no system shell in the web UI.
      </p>
    </div>
  );
}
