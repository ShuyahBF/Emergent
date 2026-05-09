/*
  Polls /me/whatsapp/unread every 15s and:
    1. Fires a Web Notification API toast when the unread count grows.
    2. Plays a short blip sound (Web Audio API, no asset needed).
    3. Updates the favicon with a red dot so even an inactive tab signals activity.

  No server-side push — keeps things simple and avoids websockets.
  Permission is requested on the first interaction (after login).
  Sound + notification opt-in are persisted in localStorage so the user keeps
  control. A small bell button in the layout exposes the toggle.
*/
import { useEffect, useRef, useState, useCallback } from "react";
import { apiClient } from "@/lib/api";

const POLL_MS = 15000;
const STORAGE_KEY_SOUND = "sawali_wa_notif_sound";
const STORAGE_KEY_DESKTOP = "sawali_wa_notif_desktop";

// Tiny "bling" generated programmatically via Web Audio — no external file.
function playBlip(volume = 0.4) {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = "sine";
    osc.frequency.setValueAtTime(880, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(1320, ctx.currentTime + 0.18);
    gain.gain.setValueAtTime(volume, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.4);
    osc.start();
    osc.stop(ctx.currentTime + 0.42);
    osc.onended = () => ctx.close();
  } catch {
    /* swallow — sound is best effort */
  }
}

let originalFavicon = null;
function setFaviconBadge(show) {
  try {
    const link = document.querySelector("link[rel~='icon']");
    if (!link) return;
    if (!originalFavicon) originalFavicon = link.href;
    if (!show) {
      link.href = originalFavicon;
      return;
    }
    const canvas = document.createElement("canvas");
    canvas.width = 64;
    canvas.height = 64;
    const ctx = canvas.getContext("2d");
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      ctx.drawImage(img, 0, 0, 64, 64);
      ctx.beginPath();
      ctx.arc(50, 14, 14, 0, 2 * Math.PI);
      ctx.fillStyle = "#ef4444";
      ctx.fill();
      ctx.lineWidth = 4;
      ctx.strokeStyle = "#fff";
      ctx.stroke();
      link.href = canvas.toDataURL("image/png");
    };
    img.onerror = () => { /* no badge if origin blocks */ };
    img.src = originalFavicon;
  } catch { /* noop */ }
}

export function useWhatsAppNotifier() {
  const [unread, setUnread] = useState(0);
  const [permission, setPermission] = useState(typeof Notification !== "undefined" ? Notification.permission : "default");
  const [soundOn, setSoundOn] = useState(() => localStorage.getItem(STORAGE_KEY_SOUND) !== "off");
  const [desktopOn, setDesktopOn] = useState(() => localStorage.getItem(STORAGE_KEY_DESKTOP) !== "off");
  // Client-level kill switch: when the admin disables `wa_sound_alerts` on the
  // parent client, the user's localStorage preference is overridden and the
  // sound never plays. Defaults to true (allowed) until /me/features answers.
  const [soundAllowedByAdmin, setSoundAllowedByAdmin] = useState(true);
  const lastSeenRef = useRef(null);
  const intervalRef = useRef(null);

  // Resolve the per-client feature flag once on mount. Privileged roles get
  // every flag = true, so the kill switch is a no-op for them.
  useEffect(() => {
    let cancelled = false;
    apiClient.get("/me/features")
      .then((r) => {
        if (cancelled) return;
        const allowed = r.data?.features?.wa_sound_alerts;
        // Treat undefined as allowed (backward-compat with older payloads).
        setSoundAllowedByAdmin(allowed !== false);
      })
      .catch(() => { /* keep default = allowed */ });
    return () => { cancelled = true; };
  }, []);

  const persist = useCallback((sound, desktop) => {
    localStorage.setItem(STORAGE_KEY_SOUND, sound ? "on" : "off");
    localStorage.setItem(STORAGE_KEY_DESKTOP, desktop ? "on" : "off");
  }, []);

  const requestPermission = useCallback(async () => {
    if (typeof Notification === "undefined") return "denied";
    if (Notification.permission === "granted" || Notification.permission === "denied") {
      return Notification.permission;
    }
    const r = await Notification.requestPermission();
    setPermission(r);
    return r;
  }, []);

  const tick = useCallback(async () => {
    try {
      const r = await apiClient.get("/me/whatsapp/unread");
      const total = r.data?.total || 0;
      setUnread(total);
      setFaviconBadge(total > 0);
      // First poll → just bookmark the current count (don't notify retro-actively)
      if (lastSeenRef.current == null) {
        lastSeenRef.current = total;
        return;
      }
      if (total > lastSeenRef.current) {
        const delta = total - lastSeenRef.current;
        if (soundOn && soundAllowedByAdmin) playBlip();
        if (desktopOn && typeof Notification !== "undefined" && Notification.permission === "granted" && document.visibilityState !== "visible") {
          try {
            const n = new Notification(`SAWALI — ${delta} nouveau(x) message WhatsApp`, {
              body: "Cliquez pour voir la conversation.",
              tag: "sawali-wa",
              renotify: true,
              icon: "/favicon.ico",
            });
            n.onclick = () => {
              window.focus();
              window.location.href = "/portal/contacts";
              n.close();
            };
          } catch { /* swallow */ }
        }
      }
      lastSeenRef.current = total;
    } catch { /* poll silently */ }
  }, [soundOn, desktopOn, soundAllowedByAdmin]);

  useEffect(() => {
    tick();
    intervalRef.current = setInterval(tick, POLL_MS);
    return () => {
      clearInterval(intervalRef.current);
      setFaviconBadge(false);
    };
  }, [tick]);

  return {
    unread,
    permission,
    soundOn,
    soundAllowedByAdmin,
    desktopOn,
    requestPermission,
    toggleSound: () => setSoundOn((s) => { const v = !s; persist(v, desktopOn); return v; }),
    toggleDesktop: () => setDesktopOn(async (d) => {
      const v = !d;
      if (v && typeof Notification !== "undefined" && Notification.permission === "default") {
        const r = await Notification.requestPermission();
        setPermission(r);
      }
      persist(soundOn, v);
      return v;
    }),
  };
}
