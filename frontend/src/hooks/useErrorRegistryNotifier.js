/*
  Iter43-fix2 (2026-03) — Polls /me/notifications/counts every 20s and detects
  new errors in the Registre des Erreurs. Plays a DEDICATED alarm sound
  (3-tone urgent descending pattern, distinct from tickets / WhatsApp blips)
  and shows a toast with severity color when errors_high or errors_critical
  GROW since last poll.

  Storage flags (shared with WA hook for consistency) :
    sawali_wa_notif_sound   "off" → mute audio
    sawali_wa_notif_desktop "off" → mute desktop notifications
*/
import { useEffect, useRef } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";

const POLL_MS = 20000;
const STORAGE_KEY_SOUND = "sawali_wa_notif_sound";
const STORAGE_KEY_DESKTOP = "sawali_wa_notif_desktop";

// Iter43-fix2 — Alarme dédiée erreurs : 3 tons descendants saccadés (urgent
// & reconnaissable, très différent du "blip" tickets et du "ping" WhatsApp).
function playErrorAlarm(severity = "high") {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const isCritical = severity === "critical";
    const gain = ctx.createGain();
    gain.connect(ctx.destination);
    const vol = isCritical ? 0.55 : 0.40;
    // Critical = 4 tons (plus long et plus aigu), High = 3 tons (plus court)
    const tones = isCritical
      ? [880, 660, 440, 880]   // SOS-like
      : [780, 580, 420];        // alarm descendante
    const tDur = 0.16;
    const tGap = 0.04;
    let now = ctx.currentTime;
    tones.forEach((freq) => {
      const osc = ctx.createOscillator();
      osc.type = "square";
      osc.frequency.setValueAtTime(freq, now);
      osc.connect(gain);
      gain.gain.setValueAtTime(vol, now);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + tDur);
      osc.start(now);
      osc.stop(now + tDur);
      now += tDur + tGap;
    });
    setTimeout(() => { try { ctx.close(); } catch { /* noop */ } }, (tones.length * (tDur + tGap) + 0.1) * 1000);
  } catch {
    /* sound is best effort */
  }
}

function notifyDesktop(title, body) {
  try {
    if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
    new Notification(title, { body, tag: "sawali-error", silent: true });
  } catch { /* noop */ }
}

export function useErrorRegistryNotifier(enabled = true) {
  const lastCriticalRef = useRef(null);
  const lastHighRef = useRef(null);

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;

    const isOn = (key) => localStorage.getItem(key) !== "off";

    const poll = async () => {
      try {
        const r = await apiClient.get("/me/notifications/counts").catch(() => null);
        if (cancelled) return;
        const c = r?.data?.counts || {};
        const critical = Number(c.errors_critical ?? c.errors_fatale ?? 0) || 0;
        const high = Number(c.errors_high ?? c.errors_exception ?? 0) || 0;

        // First run : seed refs without triggering anything
        if (lastCriticalRef.current === null && lastHighRef.current === null) {
          lastCriticalRef.current = critical;
          lastHighRef.current = high;
          return;
        }

        const deltaC = critical - (lastCriticalRef.current ?? 0);
        const deltaH = high - (lastHighRef.current ?? 0);

        if (deltaC > 0) {
          toast.error(`🔴 ${deltaC} nouvelle(s) erreur(s) Critical`, {
            duration: 10000,
            id: `err-critical-${critical}`,
            action: {
              label: "Voir",
              onClick: () => { window.location.href = "/portal/error-registry"; },
            },
          });
          if (isOn(STORAGE_KEY_SOUND)) playErrorAlarm("critical");
          if (isOn(STORAGE_KEY_DESKTOP)) notifyDesktop("Erreurs critiques", `${deltaC} nouvelle(s) — Registre des Erreurs`);
        } else if (deltaH > 0) {
          toast.warning(`🟠 ${deltaH} nouvelle(s) erreur(s) High`, {
            duration: 8000,
            id: `err-high-${high}`,
            action: {
              label: "Voir",
              onClick: () => { window.location.href = "/portal/error-registry"; },
            },
          });
          if (isOn(STORAGE_KEY_SOUND)) playErrorAlarm("high");
          if (isOn(STORAGE_KEY_DESKTOP)) notifyDesktop("Nouvelles erreurs", `${deltaH} High — Registre des Erreurs`);
        }
        lastCriticalRef.current = critical;
        lastHighRef.current = high;
      } catch {
        /* silent */
      }
    };

    poll();
    const id = setInterval(poll, POLL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, [enabled]);
}
