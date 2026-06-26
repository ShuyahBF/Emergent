// Iter43-fix24ap (2026-06-17) — Admin Settings section: integration health
// monitor (Google Calendar + Meta WA Webhook).
//
// - Shows current live status (green/red) for each integration.
// - Lets admin configure the alert WhatsApp number + enable/disable alerts.
// - Provides a "Run check now" button + persistent history view.
import React, { useCallback, useEffect, useState } from "react";
import { Activity, RefreshCcw, CheckCircle2, XCircle, AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const StatusBadge = ({ ok, label }) => (
  <span
    className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${
      ok ? "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-200" : "bg-rose-100 text-rose-700 ring-1 ring-rose-200"
    }`}
  >
    {ok ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />} {label}
  </span>
);

export default function IntegrationHealthSection() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [enabled, setEnabled] = useState(true);
  const [waPhone, setWaPhone] = useState("");
  const [saving, setSaving] = useState(false);

  const loadConfig = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/settings");
      setEnabled(r.data?.integration_health_alerts_enabled !== false);
      setWaPhone(r.data?.integration_health_alert_wa_phone || "");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur chargement config");
    }
  }, []);

  const loadHistory = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/integrations/health-history?limit=10");
      setHistory(r.data?.items || []);
    } catch {
      // silent
    }
  }, []);

  useEffect(() => {
    loadConfig();
    loadHistory();
  }, [loadConfig, loadHistory]);

  const runCheck = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/integrations/health-check");
      setResult(r.data);
      await loadHistory();
      if (r.data?.ok) {
        toast.success("Toutes les intégrations sont OK");
      } else if (r.data?.alert_sent) {
        toast.warning("Échec détecté — alerte WhatsApp envoyée");
      } else if (r.data?.alert_throttled) {
        toast.warning("Échec détecté — alerte throttlée (déjà envoyée < 12h)");
      } else {
        toast.warning("Échec détecté (aucune alerte envoyée — configurez le numéro)");
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur du check");
    } finally {
      setLoading(false);
    }
  };

  const saveConfig = async () => {
    setSaving(true);
    try {
      await apiClient.put("/admin/settings", {
        integration_health_alerts_enabled: enabled,
        integration_health_alert_wa_phone: waPhone || "",
      });
      toast.success("Configuration enregistrée");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de sauvegarde");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section
      className="rounded-2xl ring-1 ring-violet-200 bg-gradient-to-br from-violet-50/40 via-white to-fuchsia-50/30 p-5 space-y-4"
      data-testid="integration-health-section"
    >
      <header className="flex items-center gap-3">
        <div className="rounded-full bg-violet-100 ring-1 ring-violet-200 p-2">
          <Activity className="h-5 w-5 text-violet-700" />
        </div>
        <div className="flex-1">
          <h3 className="font-display font-bold text-slate-900">
            Monitoring des intégrations (Google Cal + Meta Webhook)
          </h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Vérification automatique toutes les <strong>4 heures</strong>. Notification WhatsApp
            envoyée à l&apos;admin en cas d&apos;échec (throttle 12h pour éviter le spam).
          </p>
        </div>
        <button
          type="button"
          onClick={runCheck}
          disabled={loading}
          className="text-sm inline-flex items-center gap-1.5 rounded-lg border border-violet-300 bg-violet-50 hover:bg-violet-100 text-violet-700 px-3 py-1.5 disabled:opacity-50 font-semibold"
          data-testid="integration-health-run"
        >
          <RefreshCcw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          {loading ? "Test en cours…" : "🩺 Lancer un check"}
        </button>
      </header>

      {/* Live result */}
      {result && (
        <div className="space-y-2" data-testid="integration-health-result">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge ok={!!result.google_calendar?.ok} label={`Google Calendar`} />
            <StatusBadge ok={!!result.meta_webhook?.ok} label={`Meta Webhook WA`} />
            {result.alert_sent && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 text-xs ring-1 ring-amber-200">
                <AlertTriangle className="h-3 w-3" /> Alerte WhatsApp envoyée
              </span>
            )}
            {result.alert_throttled && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-100 text-slate-700 text-xs ring-1 ring-slate-200">
                Alerte throttlée (déjà envoyée &lt; 12h)
              </span>
            )}
          </div>
          {!result.google_calendar?.ok && (
            <p className="text-xs text-rose-700 bg-rose-50 ring-1 ring-rose-200 rounded p-2" data-testid="health-google-error">
              🟥 <strong>Google Calendar</strong> : {result.google_calendar?.message || "?"}
              {result.google_calendar?.error_type && (
                <span className="block text-[10px] font-mono mt-0.5 text-rose-600">
                  type: {result.google_calendar.error_type}
                </span>
              )}
            </p>
          )}
          {!result.meta_webhook?.ok && (
            <p className="text-xs text-rose-700 bg-rose-50 ring-1 ring-rose-200 rounded p-2" data-testid="health-meta-error">
              🟥 <strong>Meta Webhook</strong> : {result.meta_webhook?.message || "?"}
            </p>
          )}
        </div>
      )}

      {/* Config */}
      <div className="rounded-lg bg-white ring-1 ring-slate-200 p-3 space-y-3">
        <p className="text-xs font-semibold text-slate-700">Configuration des alertes</p>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            data-testid="integration-health-enabled-toggle"
          />
          <span>Alertes WhatsApp activées</span>
        </label>
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">
            Numéro WhatsApp admin (format E.164, ex: +22670112233)
          </label>
          <input
            type="text"
            value={waPhone}
            onChange={(e) => setWaPhone(e.target.value)}
            placeholder="+22670112233"
            className="w-full sm:w-auto min-w-[240px] px-3 py-1.5 rounded ring-1 ring-slate-300 focus:ring-2 focus:ring-violet-400 outline-none text-sm font-mono"
            data-testid="integration-health-wa-phone"
          />
        </div>
        <button
          type="button"
          onClick={saveConfig}
          disabled={saving}
          className="text-sm px-3 py-1.5 rounded bg-violet-600 hover:bg-violet-700 text-white font-semibold disabled:opacity-50"
          data-testid="integration-health-save"
        >
          {saving ? "Enregistrement…" : "💾 Enregistrer"}
        </button>
      </div>

      {/* History */}
      {history.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer font-semibold text-slate-700">
            📜 Historique des 10 derniers contrôles ({history.length})
          </summary>
          <div className="mt-2 rounded ring-1 ring-slate-200 bg-white overflow-hidden">
            <table className="w-full text-[11px]">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="text-left px-2 py-1">Date</th>
                  <th className="text-left px-2 py-1">GCal</th>
                  <th className="text-left px-2 py-1">Meta</th>
                  <th className="text-left px-2 py-1">Source</th>
                  <th className="text-left px-2 py-1">Alerte</th>
                </tr>
              </thead>
              <tbody>
                {history.map((row) => (
                  <tr key={row.id} className="border-t border-slate-100">
                    <td className="px-2 py-1 font-mono">{(row.checked_at || "").slice(0, 19).replace("T", " ")}</td>
                    <td className="px-2 py-1">{row.google_calendar?.ok ? "✅" : "❌"}</td>
                    <td className="px-2 py-1">{row.meta_webhook?.ok ? "✅" : "❌"}</td>
                    <td className="px-2 py-1 text-slate-500">{row.triggered_by || ""}</td>
                    <td className="px-2 py-1">{row.alert_sent ? "📨" : row.alert_throttled ? "⏱" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </section>
  );
}
