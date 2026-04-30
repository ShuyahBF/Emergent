import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { Activity, AlertCircle, Clock, Mail, Send, RefreshCw, AlertTriangle } from "lucide-react";
import { toast } from "sonner";

export default function AdminHealthDashboard() {
  const [stats, setStats] = useState(null);
  const [windowH, setWindowH] = useState(24);
  const [loading, setLoading] = useState(false);

  const load = async (w = windowH) => {
    setLoading(true);
    try {
      const r = await apiClient.get(`/admin/health-stats?window_hours=${w}`);
      setStats(r.data);
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load().catch(() => {}); /* eslint-disable-next-line */ }, []);

  const testEmail = async () => {
    try { const r = await apiClient.post("/admin/health/test-email"); toast.success(`Test envoyé à ${r.data.recipient}`); }
    catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };
  const runWeekly = async () => {
    try { await apiClient.post("/admin/health/run-weekly-now"); toast.success("Rapport hebdomadaire déclenché"); }
    catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const peak = useMemo(() => Math.max(1, ...(stats?.hourly || []).map((h) => h.total)), [stats]);

  return (
    <div className="space-y-6" data-testid="admin-health-page">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2"><Activity className="h-5 w-5 text-emerald-500" /> Santé applicative</h1>
          <p className="text-sm text-slate-500">Vue d'ensemble des requêtes mutantes capturées dans <code>api_traces</code>. Réservé au superviseur principal.</p>
        </div>
        <div className="flex gap-2">
          <select value={windowH} onChange={(e) => { const w = parseInt(e.target.value, 10); setWindowH(w); load(w); }} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
            <option value={1}>1 h</option><option value={6}>6 h</option><option value={24}>24 h</option><option value={72}>3 j</option><option value={168}>7 j</option><option value={336}>14 j</option>
          </select>
          <button onClick={() => load()} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3.5 py-2 text-sm hover:border-sawali-blue hover:text-sawali-blue disabled:opacity-50" data-testid="health-refresh">
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Actualiser
          </button>
          <button onClick={testEmail} className="inline-flex items-center gap-2 rounded-lg bg-amber-500 text-white px-3.5 py-2 text-sm hover:bg-amber-600" data-testid="health-test-email">
            <Mail className="h-4 w-4" /> Test alerte
          </button>
          <button onClick={runWeekly} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-3.5 py-2 text-sm hover:bg-sawali-blue-light" data-testid="health-run-weekly">
            <Send className="h-4 w-4" /> Hebdo maintenant
          </button>
        </div>
      </div>

      {!stats ? (
        <div className="rounded-xl border border-dashed border-slate-300 p-12 text-center text-slate-500">Chargement…</div>
      ) : (
        <>
          <div className="grid sm:grid-cols-4 gap-4">
            <Stat label={`Actions (${stats.window_hours} h)`} value={stats.total} icon={<Activity className="h-4 w-4 text-sawali-blue" />} testid="health-stat-total" />
            <Stat label="Erreurs ≥ 400" value={stats.errors} icon={<AlertTriangle className="h-4 w-4 text-rose-500" />} accent={stats.errors > 0 ? "text-rose-600" : ""} testid="health-stat-errors" />
            <Stat label="Taux d'erreur" value={`${stats.error_rate} %`} icon={<AlertCircle className="h-4 w-4 text-amber-500" />} accent={stats.error_rate > 5 ? "text-rose-600" : ""} testid="health-stat-rate" />
            <Stat label="Durée moyenne" value={`${stats.avg_duration_ms} ms`} icon={<Clock className="h-4 w-4 text-emerald-500" />} testid="health-stat-duration" />
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <h3 className="text-sm font-semibold mb-3">Activité par heure</h3>
            <div className="flex items-end gap-1 h-24" data-testid="health-hourly">
              {(stats.hourly || []).map((h) => (
                <div key={h.hour} className="flex-1 flex flex-col-reverse" title={`${h.hour}: ${h.total} actions, ${h.errors} erreurs`}>
                  <div className="bg-sawali-blue/40 rounded-t" style={{ height: `${Math.round((h.total / peak) * 100)}%`, minHeight: 2 }} />
                  {h.errors > 0 && <div className="bg-rose-500 rounded-t" style={{ height: `${Math.round((h.errors / peak) * 100)}%`, minHeight: 2 }} />}
                </div>
              ))}
              {(stats.hourly || []).length === 0 && <p className="text-xs text-slate-400">Aucune activité sur la fenêtre.</p>}
            </div>
          </div>

          <div className="grid lg:grid-cols-2 gap-4">
            <Card title="Top endpoints en erreur">
              <table className="w-full text-sm" data-testid="health-top-errors">
                <thead className="text-xs uppercase tracking-widest text-slate-500"><tr><th className="text-left px-2 py-1.5">Méthode</th><th className="text-left px-2 py-1.5">URL</th><th className="text-right px-2 py-1.5">#</th></tr></thead>
                <tbody>
                  {(stats.top_errors || []).map((e) => (
                    <tr key={`${e.method}${e.url}`} className="border-t border-slate-100">
                      <td className="px-2 py-1.5 font-mono text-xs"><span className="px-1.5 py-0.5 rounded bg-slate-100">{e.method}</span></td>
                      <td className="px-2 py-1.5 font-mono text-xs text-slate-600 truncate max-w-[280px]">{e.url}</td>
                      <td className="px-2 py-1.5 text-right tabular-nums font-semibold text-rose-600">{e.count}</td>
                    </tr>
                  ))}
                  {!stats.top_errors?.length && <tr><td colSpan={3} className="px-2 py-6 text-center text-emerald-600">Aucune erreur sur la fenêtre — bravo !</td></tr>}
                </tbody>
              </table>
            </Card>
            <Card title="Top utilisateurs">
              <table className="w-full text-sm" data-testid="health-top-users">
                <thead className="text-xs uppercase tracking-widest text-slate-500"><tr><th className="text-left px-2 py-1.5">Email</th><th className="text-right px-2 py-1.5">Actions</th><th className="text-right px-2 py-1.5">Erreurs</th></tr></thead>
                <tbody>
                  {(stats.top_users || []).map((u) => (
                    <tr key={u.email} className="border-t border-slate-100">
                      <td className="px-2 py-1.5">{u.email}</td>
                      <td className="px-2 py-1.5 text-right tabular-nums">{u.total}</td>
                      <td className={`px-2 py-1.5 text-right tabular-nums ${u.errors ? "text-rose-600" : "text-slate-400"}`}>{u.errors}</td>
                    </tr>
                  ))}
                  {!stats.top_users?.length && <tr><td colSpan={3} className="px-2 py-6 text-center text-slate-400">Aucune activité.</td></tr>}
                </tbody>
              </table>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

const Stat = ({ label, value, icon, accent = "", testid }) => (
  <div className="rounded-xl border border-slate-200 bg-white p-5" data-testid={testid}>
    <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-slate-500">{icon} {label}</div>
    <p className={`text-3xl font-display font-bold mt-2 tabular-nums ${accent || "text-slate-900"}`}>{value}</p>
  </div>
);

const Card = ({ title, children }) => (
  <div className="rounded-xl border border-slate-200 bg-white p-5">
    <h3 className="text-sm font-semibold mb-3">{title}</h3>
    {children}
  </div>
);
