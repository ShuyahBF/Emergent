/*
  Iter36b — Polls /me/tickets/pending-count every 30 s and detects:
    • newly opened tickets (count increases) → toast + sound + native notif
    • status changes on tickets we already saw (via /me/tickets list)

  We keep a snapshot of {ticketId → status} in a ref so we can diff between
  polls and surface "Ticket TKT-… : nouveau / suspendu / clôturé" toasts.

  Sound + desktop notification preferences are reused from the WhatsApp
  hook's localStorage keys (single user toggle for the whole app).
*/
import { useEffect, useRef } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";

const POLL_MS = 30000;
const STORAGE_KEY_SOUND = "sawali_wa_notif_sound";
const STORAGE_KEY_DESKTOP = "sawali_wa_notif_desktop";

const STATUS_LABELS = {
  open: "Ouvert",
  in_progress: "En cours",
  suspended: "Suspendu",
  closed: "Clôturé",
};
const STATUS_COLORS = {
  open: "warning",
  in_progress: "info",
  suspended: "warning",
  closed: "success",
};

function playTicketBlip(volume = 0.45) {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    // Two-tone ticket "bing-bong" (different from WA's "blip")
    osc.type = "triangle";
    osc.frequency.setValueAtTime(660, ctx.currentTime);
    osc.frequency.linearRampToValueAtTime(990, ctx.currentTime + 0.12);
    osc.frequency.linearRampToValueAtTime(540, ctx.currentTime + 0.28);
    gain.gain.setValueAtTime(volume, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.5);
    osc.start();
    osc.stop(ctx.currentTime + 0.52);
    osc.onended = () => ctx.close();
  } catch {
    /* sound is best effort */
  }
}

function notifyDesktop(title, body) {
  try {
    if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
    new Notification(title, { body, tag: "sawali-ticket", silent: true });
  } catch { /* noop */ }
}

export function useTicketNotifier(enabled = true) {
  const lastCountRef = useRef(null);
  const statusMapRef = useRef(null); // {ticketId: {status, number}}

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;

    const isOn = (key) => localStorage.getItem(key) !== "off";

    const poll = async () => {
      try {
        const [countR, listR] = await Promise.all([
          apiClient.get("/me/tickets/pending-count").catch(() => null),
          apiClient.get("/me/tickets?limit=50").catch(() => null),
        ]);
        if (cancelled) return;
        const newCount = countR?.data?.count ?? null;
        const items = Array.isArray(listR?.data?.items) ? listR.data.items
                    : Array.isArray(listR?.data) ? listR.data : [];

        // ---- 1) Detect newly opened tickets via count delta ----
        if (lastCountRef.current !== null && newCount !== null && newCount > lastCountRef.current) {
          const delta = newCount - lastCountRef.current;
          // Best-effort: find the newest item that wasn't in our previous snapshot
          const newest = (statusMapRef.current && items.length)
            ? items.find((t) => !statusMapRef.current[t.id])
            : items[0];
          const lbl = newest?.number ? `Ticket ${newest.number}` : `${delta} nouveau(x) ticket(s)`;
          const motif = newest?.motif || newest?.subject || "Nouvelle demande";
          toast.warning(`${lbl} : ${motif}`, {
            duration: 7000,
            id: `ticket-new-${newest?.id || newCount}`,
            action: {
              label: "Voir",
              onClick: () => { window.location.href = "/portal/tickets"; },
            },
          });
          if (isOn(STORAGE_KEY_SOUND)) playTicketBlip();
          if (isOn(STORAGE_KEY_DESKTOP)) notifyDesktop("Nouveau ticket", `${lbl} — ${motif}`);
        }
        lastCountRef.current = newCount;

        // ---- 2) Detect status changes on known tickets ----
        if (statusMapRef.current && items.length) {
          for (const t of items) {
            const prev = statusMapRef.current[t.id];
            if (prev && prev.status !== t.status) {
              const label = STATUS_LABELS[t.status] || t.status;
              const tone = STATUS_COLORS[t.status] || "info";
              const msg = `Ticket ${t.number || t.id.slice(0, 8)} → ${label}`;
              const fn = toast[tone] || toast.info;
              fn(msg, {
                duration: 6000,
                id: `ticket-status-${t.id}`,
                action: {
                  label: "Voir",
                  onClick: () => { window.location.href = "/portal/tickets"; },
                },
              });
              if (isOn(STORAGE_KEY_SOUND)) playTicketBlip(0.35);
              if (isOn(STORAGE_KEY_DESKTOP)) notifyDesktop("Statut ticket modifié", msg);
            }
          }
        }
        // Refresh snapshot
        statusMapRef.current = Object.fromEntries(items.map((t) => [t.id, { status: t.status, number: t.number }]));
      } catch {
        /* silent — best effort */
      }
    };

    // Initial poll to seed the snapshot (no toast on first run)
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, [enabled]);
}
