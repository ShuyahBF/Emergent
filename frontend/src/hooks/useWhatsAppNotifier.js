/*
  Polls /me/whatsapp/unread every 15s and:
    1. Fires a Web Notification API toast when the unread count grows.
    2. Plays a configurable sound (5 built-in presets or a custom MP3 chosen
       by the admin — see /app/backend/routes/wa_notification_sound.py).
    3. Updates the favicon with a red dot so even an inactive tab signals activity.

  No server-side push — keeps things simple and avoids websockets.
  Permission is requested on the first interaction (after login).
  Sound + notification opt-in are persisted in localStorage so the user keeps
  control. A small bell button in the layout exposes the toggle. Individual
  users may also override the preset/volume locally via /portal/account.
*/
import { useEffect, useRef, useState, useCallback } from "react";
import { apiClient } from "@/lib/api";
import { getEffectiveConfig, playSound } from "@/lib/notificationSounds";

const POLL_MS = 15000;
const STORAGE_KEY_SOUND = "sawali_wa_notif_sound";
const STORAGE_KEY_DESKTOP = "sawali_wa_notif_desktop";

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

export function useWhatsAppNotifier({ enabled = true } = {}) {
  const [unread, setUnread] = useState(0);
  const [permission, setPermission] = useState(typeof Notification !== "undefined" ? Notification.permission : "default");
  const [soundOn, setSoundOn] = useState(() => localStorage.getItem(STORAGE_KEY_SOUND) !== "off");
  const [desktopOn, setDesktopOn] = useState(() => localStorage.getItem(STORAGE_KEY_DESKTOP) !== "off");
  // Client-level kill switch: when the admin disables `wa_sound_alerts` on the
  // parent client, the user's localStorage preference is overridden and the
  // sound never plays. Defaults to true (allowed) until /me/features answers.
  const [soundAllowedByAdmin, setSoundAllowedByAdmin] = useState(true);
  // Effective sound config resolved from tenant defaults + user localStorage
  // overrides. Refreshed alongside the feature flags on mount.
  const [soundConfig, setSoundConfig] = useState({ preset: "bip", url: null, volume: 0.4 });
  // Raw tenant defaults (no user override applied) so the "Reset to admin"
  // action in <WaSoundPreferences /> knows what to reset to.
  const [soundAdminDefaults, setSoundAdminDefaults] = useState({ preset: "bip", url: null, volume: 0.4 });
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
        const raw = {
          preset: r.data?.wa_notification_sound || "bip",
          url: r.data?.wa_notification_sound_url || null,
          volume: typeof r.data?.wa_notification_volume === "number" ? r.data.wa_notification_volume : 0.4,
        };
        setSoundAdminDefaults(raw);
        setSoundConfig(getEffectiveConfig(raw));
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
        if (soundOn && soundAllowedByAdmin) {
          playSound(soundConfig.preset, soundConfig.url, soundConfig.volume);
        }
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
  }, [soundOn, desktopOn, soundAllowedByAdmin, soundConfig]);

  useEffect(() => {
    if (!enabled) {
      // 2026-02 fork (P4) — Admin toggle "show_messaging_notifs=false" cuts
      // the poll + resets the badge silently.
      setUnread(0);
      setFaviconBadge(false);
      return () => {};
    }
    tick();
    intervalRef.current = setInterval(tick, POLL_MS);
    return () => {
      clearInterval(intervalRef.current);
      setFaviconBadge(false);
    };
  }, [tick, enabled]);

  return {
    unread,
    permission,
    soundOn,
    soundAllowedByAdmin,
    soundConfig,
    soundAdminDefaults,
    desktopOn,
    requestPermission,
    // Testing helper: preview the current effective sound (used by the popover)
    previewSound: () => playSound(soundConfig.preset, soundConfig.url, soundConfig.volume),
    // Called after the user updates their local sound preference so the hook
    // picks it up without a page refresh.
    refreshSoundConfig: () => {
      // Re-resolve the effective config from the raw admin defaults + the
      // freshly updated localStorage overrides. No network needed.
      setSoundConfig(getEffectiveConfig(soundAdminDefaults));
    },
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
