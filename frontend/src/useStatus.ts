import { useEffect, useRef, useState } from "react";

import { Status, wsUrl } from "./api";

// Live status pushed by the server over /api/v1/ws/events. Reconnects with a
// growing delay. Calls onSessionEnded when the server closes with 4401.
export function useStatus(onSessionEnded: () => void): { status: Status | null; connected: boolean } {
  const [status, setStatus] = useState<Status | null>(null);
  const [connected, setConnected] = useState(false);
  const ended = useRef(onSessionEnded);
  ended.current = onSessionEnded;

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retry = 1000;
    let timer: number | undefined;
    let stopped = false;

    const connect = () => {
      socket = new WebSocket(wsUrl("ws/events"));
      socket.onopen = () => {
        setConnected(true);
        retry = 1000;
      };
      socket.onmessage = (event) => {
        const msg = JSON.parse(event.data as string) as { type: string; data: Status };
        if (msg.type === "status") setStatus(msg.data);
      };
      socket.onclose = (event) => {
        setConnected(false);
        if (stopped) return;
        if (event.code === 4401) {
          ended.current();
          return;
        }
        timer = window.setTimeout(connect, retry);
        retry = Math.min(retry * 2, 30000);
      };
    };
    connect();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      socket?.close();
    };
  }, []);

  return { status, connected };
}
