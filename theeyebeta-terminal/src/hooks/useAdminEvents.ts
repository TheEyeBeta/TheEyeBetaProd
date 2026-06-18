import { useEffect, useMemo, useRef, useState } from "react";
import { apiConfig } from "../api/http";
import type { WsEvent } from "../api/types";

type WsState = "offline" | "connecting" | "connected" | "reconnecting";

export function useAdminEvents(token: string | null) {
  const [state, setState] = useState<WsState>("offline");
  const [events, setEvents] = useState<WsEvent[]>([]);
  const attemptRef = useRef(0);

  useEffect(() => {
    if (!token) {
      setState("offline");
      setEvents([]);
      return;
    }

    let socket: WebSocket | null = null;
    let stopped = false;
    let timer: number | undefined;

    const connect = () => {
      setState(attemptRef.current === 0 ? "connecting" : "reconnecting");
      socket = new WebSocket(apiConfig.adminWs);

      socket.onopen = () => {
        socket?.send(JSON.stringify({ type: "auth", token }));
        attemptRef.current = 0;
        setState("connected");
      };

      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(String(message.data)) as WsEvent;
          if (event.type !== "ping") {
            setEvents((current) => [event, ...current].slice(0, 200));
          }
        } catch {
          setEvents((current) =>
            [
              {
                type: "client.parse_error",
                severity: "warn",
                ts: new Date().toISOString(),
                payload: message.data
              },
              ...current
            ].slice(0, 200)
          );
        }
      };

      socket.onclose = () => {
        if (stopped) return;
        attemptRef.current += 1;
        const delay = Math.min(30000, 1000 * 2 ** attemptRef.current);
        timer = window.setTimeout(connect, delay);
      };

      socket.onerror = () => {
        socket?.close();
      };
    };

    connect();

    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
      socket?.close();
    };
  }, [token]);

  return useMemo(() => ({ state, events }), [events, state]);
}
