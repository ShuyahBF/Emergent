/*
 * Iter34x — Activity feed polling hook.
 *
 * Polls /api/me/recent-activity every 8 seconds (configurable) and surfaces
 * Sonner toasts for events created by OTHER users of the same client scope.
 * Events created by the current viewer are silently ignored (so the user
 * doesn't get notified about their own actions).
 *
 * Persists the last seen cursor in sessionStorage so brief page navigations
 * don't re-replay the same events; resets on hard refresh / re-login.
 */
import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const POLL_MS = 8000;
const STORAGE_KEY = "sawali_activity_since";

const KIND_LABELS = {
  contact: "Contact",
  rapport: "Rapport",
  suivi: "Suivi",
  sms: "SMS",
  whatsapp: "WhatsApp",
  intervention: "Intervention",
  appointment: "Rendez-vous",
  payment: "Paiement",
  ticket: "Ticket",
};

const ACTION_LABELS = {
  created: "créé",
  updated: "modifié",
  deleted: "supprimé",
  sent: "envoyé",
  received: "reçu",
  assigned: "affecté",
  closed: "clôturé",
  reopened: "rouvert",
};

export function useActivityFeedNotifier(enabled = true) {
  const sinceRef = useRef(sessionStorage.getItem(STORAGE_KEY) || null);

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    let timer = null;

    const tick = async () => {
      try {
        const params = sinceRef.current ? { since: sinceRef.current } : {};
        const r = await apiClient.get("/me/recent-activity", { params });
        if (cancelled) return;
        const { events = [], server_now, viewer_id } = r.data || {};
        if (events.length > 0) {
          events.forEach((ev) => {
            // Suppress own actions
            if (ev.actor_id === viewer_id) return;
            const kindLabel = KIND_LABELS[ev.kind] || ev.kind;
            const actionLabel = ACTION_LABELS[ev.action] || ev.action;
            const body = `${ev.actor_label} a ${actionLabel} ${kindLabel.toLowerCase()} : ${ev.label}`;
            const opts = { duration: 6500, id: `activity-${ev.id}` };
            // Use distinct toast types per action for visual cue
            if (ev.action === "deleted") toast.error(body, opts);
            else if (ev.action === "received") toast.info(body, opts);
            else if (ev.action === "sent") toast.success(body, opts);
            else if (ev.action === "created") toast.success(body, opts);
            else toast(body, opts);
          });
        }
        if (server_now) {
          sinceRef.current = server_now;
          sessionStorage.setItem(STORAGE_KEY, server_now);
        }
      } catch {
        // silent — network blip is fine, next tick will retry
      } finally {
        if (!cancelled) {
          timer = setTimeout(tick, POLL_MS);
        }
      }
    };
    // initial run after 2s to let the page settle
    timer = setTimeout(tick, 2000);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [enabled]);
}
