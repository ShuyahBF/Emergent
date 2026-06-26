// =====================================================================
// Iter43-fix24ay (2026-02-26) — Google Calendar Watch API admin panel.
// Renders inside the existing Google Calendar section in AdminSettings.
// Lets admin start/stop the push watch + force sync-now + see expiration.
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw, Trash2, Play, Bell, Copy } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const GoogleCalendarWatchPanel = () => {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [lastSync, setLastSync] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/google/calendar/watch");
      setStatus(r.data);
    } catch {
      setStatus(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const startWatch = async () => {
    if (!window.confirm("Démarrer la surveillance en temps réel ? Google enverra une notification à notre webhook à chaque changement (création / modification / suppression d'événement).")) return;
    setStarting(true);
    try {
      const r = await apiClient.post("/admin/google/calendar/watch", {});
      toast.success(`Watch active jusqu'au ${r.data.expiration ? new Date(r.data.expiration).toLocaleString("fr-FR") : "?"}`);
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur démarrage watch");
    } finally {
      setStarting(false);
    }
  };

  const stopWatch = async () => {
    if (!window.confirm("Arrêter la surveillance temps réel ?")) return;
    setStopping(true);
    try {
      await apiClient.delete("/admin/google/calendar/watch");
      toast.success("Watch arrêtée");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur arrêt watch");
    } finally {
      setStopping(false);
    }
  };

  const syncNow = async () => {
    setSyncing(true);
    try {
      const r = await apiClient.post("/admin/google/calendar/sync-now");
      const { created, updated, deleted, sync_token_expired } = r.data;
      setLastSync(r.data);
      if (sync_token_expired) {
        toast.warning("Sync token expiré — relancez la watch pour réinitialiser.");
      } else {
        toast.success(`Sync : ${created} créés, ${updated} mis à jour, ${deleted} supprimés`);
      }
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur sync");
    } finally {
      setSyncing(false);
    }
  };

  if (loading) {
    return (
      <div className="mt-3 p-3 text-xs text-slate-500 inline-flex items-center gap-2" data-testid="gcal-watch-loading">
        <Loader2 className="h-3 w-3 animate-spin" /> Chargement Watch API…
      </div>
    );
  }

  if (!status) return null;
  const expDate = status.expiration ? new Date(status.expiration) : null;
  const hoursLeft = expDate ? Math.round((expDate.getTime() - Date.now()) / 3600000) : null;

  return (
    <div className="mt-3 rounded-lg ring-1 ring-fuchsia-200 bg-fuchsia-50/30 p-3 space-y-2" data-testid="gcal-watch-panel">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <p className="text-xs font-semibold text-fuchsia-800 inline-flex items-center gap-1">
          <Bell className="h-3.5 w-3.5" /> Watch API — Synchronisation temps réel (Phase 2)
        </p>
        <span
          className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded ${status.active ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"}`}
          data-testid="gcal-watch-status-badge"
        >
          {status.active ? "✓ Active" : "○ Inactive"}
        </span>
      </div>

      <p className="text-[11px] text-slate-600 leading-relaxed">
        Quand cette surveillance est <strong>active</strong>, Google notifie SAWALI à chaque modification de votre calendrier en quelques secondes.
        Les événements sont automatiquement reflétés dans la collection <code>appointments</code>.
      </p>

      {status.active && (
        <div className="grid sm:grid-cols-2 gap-2 text-[11px]">
          <div>
            <span className="block text-slate-500">Channel ID</span>
            <p className="font-mono text-[10px] text-slate-700 break-all" data-testid="gcal-watch-channel-id">{status.channel_id}</p>
          </div>
          <div>
            <span className="block text-slate-500">Calendrier surveillé</span>
            <p className="font-mono text-[10px] text-slate-700">{status.calendar_id}</p>
          </div>
          <div>
            <span className="block text-slate-500">Expiration</span>
            <p className="text-slate-700">
              {expDate ? expDate.toLocaleString("fr-FR") : "—"}{" "}
              {hoursLeft !== null && (
                <span className={`text-[10px] ${hoursLeft < 24 ? "text-amber-700 font-bold" : "text-slate-500"}`}>
                  ({hoursLeft}h restantes)
                </span>
              )}
            </p>
          </div>
          <div>
            <span className="block text-slate-500">Dernière notif Google</span>
            <p className="text-slate-700">
              {status.last_notification_at ? new Date(status.last_notification_at).toLocaleString("fr-FR") : "—"}
            </p>
          </div>
          <div className="sm:col-span-2">
            <span className="block text-slate-500">Webhook URL (Google envoie ici)</span>
            <div className="flex gap-1">
              <code className="flex-1 bg-white px-2 py-1 rounded ring-1 ring-slate-200 text-[10px] font-mono break-all" data-testid="gcal-watch-webhook-url">{status.webhook_url}</code>
              <button
                onClick={() => { navigator.clipboard.writeText(status.webhook_url); toast.success("Copié"); }}
                className="text-[10px] px-2 rounded ring-1 ring-slate-300 hover:bg-slate-100"
              >
                <Copy className="h-3 w-3" />
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-2 pt-1">
        {!status.active ? (
          <button
            onClick={startWatch}
            disabled={starting}
            className="text-xs px-3 py-1.5 rounded bg-fuchsia-600 hover:bg-fuchsia-700 text-white inline-flex items-center gap-1 disabled:opacity-50"
            data-testid="gcal-watch-start-btn"
          >
            {starting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
            Démarrer la surveillance
          </button>
        ) : (
          <button
            onClick={stopWatch}
            disabled={stopping}
            className="text-xs px-3 py-1.5 rounded bg-rose-100 hover:bg-rose-200 text-rose-700 ring-1 ring-rose-200 inline-flex items-center gap-1 disabled:opacity-50"
            data-testid="gcal-watch-stop-btn"
          >
            {stopping ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
            Arrêter la surveillance
          </button>
        )}
        <button
          onClick={syncNow}
          disabled={syncing}
          className="text-xs px-3 py-1.5 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 ring-1 ring-slate-300 inline-flex items-center gap-1 disabled:opacity-50"
          data-testid="gcal-watch-sync-now-btn"
        >
          {syncing ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
          Forcer un sync maintenant
        </button>
      </div>

      {lastSync && (
        <div className="text-[10px] bg-emerald-50 ring-1 ring-emerald-200 rounded p-2" data-testid="gcal-watch-last-sync">
          ✅ Dernier sync : {lastSync.created} créés, {lastSync.updated} mis à jour, {lastSync.deleted} supprimés
        </div>
      )}

      <p className="text-[10px] text-slate-500 italic border-t border-fuchsia-200 pt-1">
        💡 Renouvellement automatique : la surveillance est valide 7 jours max. Un cron interne la renouvelle automatiquement toutes les 6h si l&apos;expiration approche.
      </p>
    </div>
  );
};

export default GoogleCalendarWatchPanel;
