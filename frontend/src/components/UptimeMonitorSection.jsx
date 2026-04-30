import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { RefreshCw, Loader2, ShieldCheck, ShieldAlert, Globe, Database, Activity, AlertCircle } from "lucide-react";

const PROBE_ICONS = {
  db_ping: Database,
  api_health: Activity,
  api_company_info: Globe,
  api_visits_count: Activity,
  auth_login_endpoint: ShieldCheck,
};

export default function UptimeMonitorSection() {
  const [data, setData] = useState(null);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [windowH, setWindowH] = useState(168);

  const load = async (w = windowH) => {
    setLoading(true);
    try {
      const r = await apiClient.get(`/admin/health/uptime/stats?window_hours=${w}`);
      setData(r.data);
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur uptime"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  const runNow = async () => {
    setRunning(true);
    try {
      const r = await apiClient.post("/admin/health/uptime/run-now");
      toast.success(r.data.ok ? `Toutes les sondes OK (${r.data.total_duration_ms} ms)` : `${r.data.probes.filter(p => !p.ok).length} sonde(s) en échec`);
      await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setRunning(false); }
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5" data-testid="uptime-monitor-section">
      <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
        <div>
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <Globe className="h-4 w-4 text-sawali-blue" /> Uptime Monitor
          </h3>
          <p className="text-xs text-slate-500 mt-1">
            Disponibilité des services clés — sonde horaire automatique. Une page de statut publique est disponible sur <a href="/uptime" target="_blank" rel="noreferrer" className="text-sawali-blue underline">/uptime</a>.
          </p>
        </div>
        <div className="flex gap-2">
          <select
            value={windowH}
            onChange={(e) => { const w = parseInt(e.target.value, 10); setWindowH(w); load(w); }}
            className="rounded-lg border border-slate-300 px-3 py-2 text-xs"
            data-testid="uptime-window-select"
          >
            <option value={24}>24 h</option>
            <option value={72}>3 j</option>
            <option value={168}>7 j</option>
            <option value={720}>30 j</option>
          </select>
          <button
            onClick={runNow}
            disabled={running}
            className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-3.5 py-2 text-xs hover:bg-sawali-blue-light disabled:opacity-50"
            data-testid="uptime-run-now"
          >
            {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Exécuter maintenant
          </button>
        </div>
      </div>

      {loading && !data ? (
        <div className="text-center text-slate-400 py-8 text-sm">Chargement…</div>
      ) : !data?.probes?.length ? (
        <div className="text-center text-slate-400 py-8 text-sm">Aucune sonde configurée.</div>
      ) : (
        <>
          <div className="flex items-center justify-between mb-4 pb-3 border-b border-slate-100">
            <span className="text-xs uppercase tracking-[0.2em] text-slate-500">Disponibilité globale</span>
            <span className={`text-3xl font-display font-bold tabular-nums ${data.overall_uptime_pct >= 99 ? "text-emerald-600" : data.overall_uptime_pct >= 95 ? "text-amber-600" : "text-rose-600"}`} data-testid="uptime-overall-pct">
              {data.overall_uptime_pct} %
            </span>
          </div>
          <div className="space-y-3">
            {data.probes.map((p) => {
              const Icon = PROBE_ICONS[p.key] || Activity;
              const lastOk = p.timeline.length ? p.timeline[p.timeline.length - 1].ok : null;
              return (
                <div key={p.key} className="flex items-center gap-3 py-2" data-testid={`uptime-probe-${p.key}`}>
                  <div className={`h-9 w-9 rounded-lg flex items-center justify-center flex-shrink-0 ${lastOk === false ? "bg-rose-100" : lastOk === true ? "bg-emerald-100" : "bg-slate-100"}`}>
                    <Icon className={`h-4 w-4 ${lastOk === false ? "text-rose-600" : lastOk === true ? "text-emerald-600" : "text-slate-400"}`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <span className="text-sm font-medium text-slate-800 truncate">{p.label}</span>
                      <span className={`text-xs font-mono tabular-nums ${p.uptime_pct >= 99 ? "text-emerald-600" : p.uptime_pct >= 95 ? "text-amber-600" : "text-rose-600"}`}>
                        {p.uptime_pct} % · {p.avg_duration_ms} ms
                      </span>
                    </div>
                    <SparklineBar timeline={p.timeline} />
                  </div>
                </div>
              );
            })}
          </div>
          <p className="text-[10px] text-slate-400 mt-4">Fenêtre : {data.window_hours} h · {data.samples} relevé(s) · généré {new Date(data.generated_at).toLocaleString("fr-FR")}</p>
        </>
      )}
    </div>
  );
}

// Sparkline-style horizontal strip: each cell = 1 hourly probe result.
const SparklineBar = ({ timeline }) => {
  if (!timeline?.length) {
    return <div className="text-[11px] text-slate-400 italic">Aucun relevé sur la fenêtre.</div>;
  }
  return (
    <div className="flex gap-[2px] h-5" data-testid="uptime-sparkline">
      {timeline.map((t, i) => (
        <span
          key={i}
          className={`flex-1 rounded-sm ${t.ok ? "bg-emerald-500" : "bg-rose-500"}`}
          title={`${new Date(t.ts).toLocaleString("fr-FR")} — ${t.ok ? "OK" : "FAIL"} (${t.duration_ms} ms)`}
          style={{ minWidth: 3 }}
        />
      ))}
    </div>
  );
};

export { UptimeMonitorSection };
