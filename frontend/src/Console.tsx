import "@xterm/xterm/css/xterm.css";

import { useEffect, useRef, useState } from "react";
import { Alert, Button } from "@patternfly/react-core";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";

import { wsUrl } from "./api";

// The Asterisk CLI (asterisk -rvvv on the server) in a terminal.
export function Console() {
  const host = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"connecting" | "open" | "closed">("connecting");
  const [attempt, setAttempt] = useState(0);

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
    const input = term.onData((data) => {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "input", data }));
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
      <p className="asl-sub">
        Equivalent to <code>asterisk -r</code>, running as the asterisk user. There is no system shell in the web UI.
      </p>
    </div>
  );
}
