import { useEffect, useRef, useState } from "react";

import { ApiError, openSocket, Status } from "./api";

// What a page shows beyond the basics. The server runs the Asterisk commands
// for a topic only while an open page asks for it.
export type StatusTopic = "registrations";

// Live status pushed by the server over /api/v1/ws/events. Reconnects with a
// growing delay. Calls onSessionEnded when the server closes with 4401.
// While the browser tab is hidden the socket is closed, so a page left open
// in the background does not keep Asterisk busy; the last status is kept and
// a fresh one arrives when the tab is shown again.
export function useStatus(
  onSessionEnded: () => void,
  topics: StatusTopic[] = [],
): { status: Status | null; connected: boolean } {
  const [status, setStatus] = useState<Status | null>(null);
  const [connected, setConnected] = useState(false);
  const ended = useRef(onSessionEnded);
  ended.current = onSessionEnded;
  const wanted = [...topics].sort().join(",");
  const wantedRef = useRef(wanted);
  wantedRef.current = wanted;
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retry = 1000;
    let timer: number | undefined;
    let stopped = false; // unmounted
    let hidden = document.visibilityState === "hidden";
    let connecting = false;

    const retryLater = () => {
      timer = window.setTimeout(connect, retry);
      retry = Math.min(retry * 2, 30000);
    };

    const connect = async () => {
      if (stopped || hidden || socket || connecting) return;
      connecting = true;
      let s: WebSocket;
      try {
        s = await openSocket("ws/events", wantedRef.current ? { topics: wantedRef.current } : {});
      } catch (err) {
        connecting = false;
        if (stopped) return;
        if (err instanceof ApiError && err.status === 401) ended.current();
        else retryLater();
        return;
      }
      connecting = false;
      if (stopped || hidden) {
        s.close();
        return;
      }
      socket = s;
      socketRef.current = s;
      const sent = wantedRef.current;
      s.onopen = () => {
        setConnected(true);
        retry = 1000;
        // The page may have changed while the socket was opening.
        if (wantedRef.current !== sent) subscribe(s, wantedRef.current);
      };
      s.onmessage = (event) => {
        const msg = JSON.parse(event.data as string) as { type: string; data: Status };
        if (msg.type === "status") setStatus(msg.data);
      };
      s.onclose = (event) => {
        if (socket === s) {
          socket = null;
          socketRef.current = null;
        }
        setConnected(false);
        if (stopped || hidden) return;
        if (event.code === 4401) {
          ended.current();
          return;
        }
        retryLater();
      };
    };

    const onVisibility = () => {
      hidden = document.visibilityState === "hidden";
      if (hidden) {
        window.clearTimeout(timer);
        socket?.close();
      } else {
        retry = 1000;
        void connect();
      }
    };

    document.addEventListener("visibilitychange", onVisibility);
    void connect();
    return () => {
      stopped = true;
      document.removeEventListener("visibilitychange", onVisibility);
      window.clearTimeout(timer);
      socket?.close();
    };
  }, []);

  useEffect(() => {
    const s = socketRef.current;
    if (s && s.readyState === WebSocket.OPEN) subscribe(s, wanted);
  }, [wanted]);

  return { status, connected };
}

function subscribe(socket: WebSocket, topics: string) {
  socket.send(JSON.stringify({ type: "subscribe", topics: topics ? topics.split(",") : [] }));
}
