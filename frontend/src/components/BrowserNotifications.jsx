// S046 #2 (2026-02) — Browser notifications & title blinking.
//
// Two complementary user-feedback channels for when the SAWALI tab is in
// background / minimized :
//
//   1. The `document.title` flashes every 1.2s, e.g.
//      "(3) SAWALI Portal"   ←→   "🔔 New activity"
//      The count is the sum of unread badges (notifications, tickets,
//      contacts, …) returned by `/me/notifications/counts`.
//
//   2. Native Notification API : a Windows / macOS / Android system toast
//      is fired the first time the unread count GROWS while the tab is
//      hidden. Requires user permission (asked once on first sign-in).
//
// The component is mounted globally inside `PortalLayout` so every signed-in
// route gets this behaviour for free.
//
// 2026-02 fork iter108 — S164 (Emmy) — Respects the admin global switch
// `browser_notifications_enabled` (via /public/ui-flags) AND the per-user
// opt-out flag (user.browser_notifications_optout) so users who find the
// alerts intrusive can silence them from their profile settings.
import { useEffect, useRef } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { apiClient } from "@/lib/api";
import { useUIFlags } from "@/lib/useUIFlags";

const POLL_MS = 25_000;
const BLINK_MS = 1_200;
const BASE_TITLE = "SAWALI · Espace Loois";

export default function BrowserNotifications() {
  const { user } = useAuth();
  const flags = useUIFlags();
  // S164 — Admin global switch (default true when field missing).
  const globalEnabled = flags?.browser_notifications_enabled !== false;
  // S164 — Per-user opt-out stored in localStorage so users can silence
  // toasts they find intrusive without needing an admin round-trip.
  const userOptedOut = (() => {
    try { return localStorage.getItem("sawali_browser_notifs_optout") === "1"; }
    catch { return false; }
  })();
  const featureActive = globalEnabled && !userOptedOut;
  const baseTitleRef = useRef(BASE_TITLE);
  const totalRef = useRef(0);
  const lastShownRef = useRef(0);
  const blinkTimerRef = useRef(null);
  const blinkToggleRef = useRef(false);
  const permRequestedRef = useRef(false);

  // Capture the original document title once so we can restore it later.
  useEffect(() => {
    baseTitleRef.current = document.title || BASE_TITLE;
    return () => { document.title = baseTitleRef.current; };
  }, []);

  // Ask the user once (politely) for notification permission.
  useEffect(() => {
    if (!user || permRequestedRef.current) return;
    if (!featureActive) return;  // S164 — Respect admin/user toggle
    if (typeof window === "undefined" || !("Notification" in window)) return;
    if (Notification.permission === "default") {
      // Defer the request a bit so it doesn't compete with login redirects.
      const t = setTimeout(() => {
        try { Notification.requestPermission().catch(() => {}); }
        catch { /* noop */ }
      }, 5000);
      permRequestedRef.current = true;
      return () => clearTimeout(t);
    }
  }, [user, featureActive]);

  // Compute the total across all badge categories.
  const sumCounts = (countsObj) => {
    if (!countsObj || typeof countsObj !== "object") return 0;
    return Object.values(countsObj).reduce(
      (acc, v) => acc + (Number.isFinite(+v) ? +v : 0),
      0,
    );
  };

  // Start / stop the blinking title.
  const stopBlinking = () => {
    if (blinkTimerRef.current) {
      clearInterval(blinkTimerRef.current);
      blinkTimerRef.current = null;
    }
    document.title = baseTitleRef.current;
  };

  const startBlinking = (n) => {
    stopBlinking();
    const base = baseTitleRef.current;
    blinkToggleRef.current = false;
    blinkTimerRef.current = setInterval(() => {
      if (!document.hidden) { stopBlinking(); return; }
      blinkToggleRef.current = !blinkToggleRef.current;
      document.title = blinkToggleRef.current
        ? `🔔 Nouvelle activité · (${n})`
        : `(${n}) ${base}`;
    }, BLINK_MS);
  };

  // Resume normal title when user comes back to the tab.
  useEffect(() => {
    const onVisible = () => {
      if (!document.hidden) {
        stopBlinking();
        // Reset the "last shown" count so subsequent growth re-triggers notif.
        lastShownRef.current = totalRef.current;
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);

  // Poll the counts endpoint and react to deltas.
  useEffect(() => {
    if (!user) return undefined;
    if (!featureActive) {
      // S164 — Feature disabled globally or by user; stop blinking / no toast.
      stopBlinking();
      return undefined;
    }
    let cancelled = false;

    const tick = async () => {
      try {
        const r = await apiClient.get("/me/notifications/counts");
        const counts = r.data?.counts || {};
        // Also fetch tickets pending count (separate endpoint)
        let tickets = 0;
        try {
          const r2 = await apiClient.get("/me/tickets/pending-count");
          tickets = Number(r2.data?.count) || 0;
        } catch { /* noop */ }
        const total = sumCounts(counts) + tickets;
        if (cancelled) return;
        const previous = totalRef.current;
        totalRef.current = total;

        // Only act when the count GREW while the tab was hidden.
        if (total > previous && document.hidden) {
          startBlinking(total);
          // Fire a system notification at most once per growth event.
          if (
            "Notification" in window &&
            Notification.permission === "granted" &&
            total > lastShownRef.current
          ) {
            try {
              const n = new Notification(BASE_TITLE, {
                body: `${total} notification${total > 1 ? "s" : ""} en attente. Cliquez pour ouvrir.`,
                tag: "sawali-unread",
                renotify: true,
                silent: false,
              });
              n.onclick = () => { window.focus(); n.close(); };
              lastShownRef.current = total;
            } catch { /* noop */ }
          }
        } else if (total === 0) {
          stopBlinking();
          lastShownRef.current = 0;
        }
      } catch { /* noop */ }
    };

    tick();
    const timer = setInterval(tick, POLL_MS);
    return () => { cancelled = true; clearInterval(timer); stopBlinking(); };
  }, [user, featureActive]);

  return null;
}
