/*
 * Iter36k — Internal chat WebSocket hook.
 *
 * Connects to /api/ws/chat?token=<JWT> with auto-reconnect, exposes:
 *   - connected (bool)
 *   - messageStream: latest server event ({type, ...})
 *   - sendTyping(client_id, recipient_id?)
 *   - ping every 30s to keep proxy from closing the socket
 *
 * REST endpoints are called directly from the panel component for
 * thread listing / history / send / mark-read; the socket is only used
 * for push notifications of new events.
 */
import { useEffect, useRef, useState, useCallback } from "react";

const BACKEND = process.env.REACT_APP_BACKEND_URL || "";

function buildWsUrl(token) {
  if (!BACKEND) return null;
  // BACKEND is https://...  → wss://.../api/ws/chat
  const proto = BACKEND.startsWith("https") ? "wss" : "ws";
  const host = BACKEND.replace(/^https?:\/\//, "");
  return `${proto}://${host}/api/ws/chat?token=${encodeURIComponent(token)}`;
}

export function useInternalChat({ token, enabled }) {
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState(null);
  const wsRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const reconnectAttemptsRef = useRef(0);
  const pingTimerRef = useRef(null);

  const closeSocket = useCallback(() => {
    if (pingTimerRef.current) { clearInterval(pingTimerRef.current); pingTimerRef.current = null; }
    if (reconnectTimerRef.current) { clearTimeout(reconnectTimerRef.current); reconnectTimerRef.current = null; }
    if (wsRef.current) {
      try { wsRef.current.close(); } catch { /* noop */ }
      wsRef.current = null;
    }
    setConnected(false);
  }, []);

  const connect = useCallback(() => {
    if (!token || !enabled) return;
    const url = buildWsUrl(token);
    if (!url) return;
    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;
      ws.onopen = () => {
        setConnected(true);
        reconnectAttemptsRef.current = 0;
        // Keep-alive ping every 30s
        pingTimerRef.current = setInterval(() => {
          try { ws.send(JSON.stringify({ type: "ping" })); } catch { /* noop */ }
        }, 30000);
      };
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          setLastEvent({ ...data, _rxAt: Date.now() });
        } catch { /* ignore */ }
      };
      ws.onerror = () => { /* triggers onclose */ };
      ws.onclose = () => {
        setConnected(false);
        if (pingTimerRef.current) { clearInterval(pingTimerRef.current); pingTimerRef.current = null; }
        // Exponential back-off, capped at 30s
        if (!enabled) return;
        reconnectAttemptsRef.current += 1;
        const delay = Math.min(30000, 1000 * Math.pow(2, reconnectAttemptsRef.current));
        reconnectTimerRef.current = setTimeout(connect, delay);
      };
    } catch { /* noop */ }
  }, [token, enabled]);

  useEffect(() => {
    if (enabled && token) connect();
    return closeSocket;
  }, [enabled, token, connect, closeSocket]);

  const sendTyping = useCallback((clientId, recipientId) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    try {
      ws.send(JSON.stringify({
        type: "typing",
        client_id: clientId,
        recipient_id: recipientId || null,
      }));
    } catch { /* noop */ }
  }, []);

  return { connected, lastEvent, sendTyping };
}
