// Iter38r-fix9z10 — Suggestion S009 — Auto-logout on inactivity hook.
//
// Watches for user activity (mouse, keyboard, scroll, touch). When idle
// for `idleMinutes` minutes, fires `onWarn` 30 s before the timeout and
// `onLogout` at the timeout. Returns the remaining warning seconds while
// in the warning window so the UI can show a countdown.
//
// idleMinutes = 0 disables the timer entirely.
import { useEffect, useRef, useState, useCallback } from "react";

const EVENTS = ["mousemove", "mousedown", "keydown", "scroll", "touchstart", "click"];

export function useIdleTimer({ idleMinutes, warningSeconds = 30, onWarn, onLogout, enabled = true }) {
  const [warningCountdown, setWarningCountdown] = useState(null);
  const lastActivityRef = useRef(Date.now());
  const warnTimerRef = useRef(null);
  const logoutTimerRef = useRef(null);
  const countdownIntervalRef = useRef(null);
  const onWarnRef = useRef(onWarn);
  const onLogoutRef = useRef(onLogout);

  useEffect(() => { onWarnRef.current = onWarn; }, [onWarn]);
  useEffect(() => { onLogoutRef.current = onLogout; }, [onLogout]);

  const clearAll = useCallback(() => {
    if (warnTimerRef.current) { clearTimeout(warnTimerRef.current); warnTimerRef.current = null; }
    if (logoutTimerRef.current) { clearTimeout(logoutTimerRef.current); logoutTimerRef.current = null; }
    if (countdownIntervalRef.current) { clearInterval(countdownIntervalRef.current); countdownIntervalRef.current = null; }
    setWarningCountdown(null);
  }, []);

  const reset = useCallback(() => {
    if (!enabled || !idleMinutes || idleMinutes <= 0) return;
    lastActivityRef.current = Date.now();
    clearAll();
    const idleMs = idleMinutes * 60 * 1000;
    const warnMs = Math.max(idleMs - warningSeconds * 1000, 1000);
    // Schedule the warning
    warnTimerRef.current = setTimeout(() => {
      setWarningCountdown(warningSeconds);
      try { onWarnRef.current && onWarnRef.current(); } catch { /* swallow */ }
      // Start countdown UI tick
      countdownIntervalRef.current = setInterval(() => {
        setWarningCountdown((c) => (c === null ? null : Math.max(c - 1, 0)));
      }, 1000);
    }, warnMs);
    // Schedule the actual logout
    logoutTimerRef.current = setTimeout(() => {
      clearAll();
      try { onLogoutRef.current && onLogoutRef.current(); } catch { /* swallow */ }
    }, idleMs);
  }, [enabled, idleMinutes, warningSeconds, clearAll]);

  // Wire events
  useEffect(() => {
    if (!enabled || !idleMinutes || idleMinutes <= 0) {
      clearAll();
      return;
    }
    const handler = () => reset();
    EVENTS.forEach((ev) => window.addEventListener(ev, handler, { passive: true }));
    reset(); // arm initial timers
    return () => {
      EVENTS.forEach((ev) => window.removeEventListener(ev, handler));
      clearAll();
    };
  }, [enabled, idleMinutes, warningSeconds, reset, clearAll]);

  // Manual "stay connected" action — called from the warning modal
  const stayConnected = useCallback(() => {
    reset();
  }, [reset]);

  return { warningCountdown, stayConnected };
}
