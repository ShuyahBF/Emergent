import React, { useEffect, useState } from "react";
import axios from "axios";
import { Link } from "react-router-dom";
import { Activity, Globe, Database, ShieldCheck, ArrowLeft, RefreshCw } from "lucide-react";
import { LOGO_URL } from "@/lib/brand";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const PROBE_ICONS = {
  db_ping: Database,
  api_health: Activity,
  api_company_info: Globe,
  api_visits_count: Activity,
  auth_login_endpoint: ShieldCheck,
};

export default function StatusPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [windowH, setWindowH] = useState(168);

  const load = async (w = windowH) => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/public/status?window_hours=${w}`);
      setData(r.data);
    } catch { /* noop */ }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);
  // auto-refresh every 60s
  useEffect(() => {
    const t = setInterval(() => load(), 60000);
    return () => clearInterval(t);
    // eslint-disable-next-line
  }, [windowH]);

  const overallTone = !data?.stats ? "slate" : data.stats.overall_uptime_pct >= 99 ? "emerald" : data.stats.overall_uptime_pct >= 95 ? "amber" : "rose";
  const palette = {
    emerald: { ring: "ring-emerald-400", bg: "bg-emerald-500/10", text: "text-emerald-300", label: "Tous les services opérationnels" },
    amber: { ring: "ring-amber-400", bg: "bg-amber-500/10", text: "text-amber-300", label: "Performance dégradée" },
    rose: { ring: "ring-rose-400", bg: "bg-rose-500/10", text: "text-rose-300", label: "Incident en cours" },
    slate: { ring: "ring-slate-400", bg: "bg-slate-500/10", text: "text-slate-300", label: "État inconnu" },
  }[overallTone];

  return (
    <div className="min-h-screen bg-[#0E1F3D] text-white" data-testid="public-status-page">
      <header className="border-b border-white/10 bg-black/20 backdrop-blur-sm">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-3" data-testid="status-home-link">
            <img src={LOGO_URL} alt="SAWALI" className="h-9 w-9 rounded-md ring-1 ring-white/20" />
            <div>
              <p className="font-display font-bold text-sm">{data?.company || "SAWALI SMART SYSTEMS"}</p>
              <p className="text-[10px] uppercase tracking-[0.3em] text-sawali-blue-light">Page de statut</p>
            </div>
          </Link>
          <Link to="/" className="text-xs text-slate-300 hover:text-white inline-flex items-center gap-1.5">
            <ArrowLeft className="h-3.5 w-3.5" /> Retour au site
          </Link>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-10">
        {/* Overall banner */}
        <div className={`rounded-2xl ${palette.bg} ring-2 ${palette.ring} p-8 mb-8`} data-testid="status-overall-banner">
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-slate-300 mb-1">État global</p>
              <h1 className={`text-3xl sm:text-4xl font-display font-bold ${palette.text}`} data-testid="status-overall-label">
                {palette.label}
              </h1>
              {data?.stats && (
                <p className="text-sm text-slate-300 mt-2">
                  Disponibilité moyenne sur {data.stats.window_hours} h :
                  <span className={`ml-2 text-xl font-display font-bold ${palette.text} tabular-nums`} data-testid="status-overall-pct">
                    {data.stats.overall_uptime_pct} %
                  </span>
                </p>
              )}
            </div>
            <div className="flex flex-col items-end gap-2">
              <select
                value={windowH}
                onChange={(e) => { const w = parseInt(e.target.value, 10); setWindowH(w); load(w); }}
                className="rounded-lg bg-white/10 border border-white/20 text-white px-3 py-2 text-sm"
                data-testid="status-window-select"
              >
                <option value={24} className="text-slate-900">24 h</option>
                <option value={72} className="text-slate-900">3 jours</option>
                <option value={168} className="text-slate-900">7 jours</option>
                <option value={720} className="text-slate-900">30 jours</option>
              </select>
              <button
                onClick={() => load()}
                className="text-xs text-slate-300 hover:text-white inline-flex items-center gap-1.5"
                data-testid="status-refresh"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Actualiser
              </button>
            </div>
          </div>
        </div>

        {/* Per-probe list */}
        <div className="rounded-2xl bg-white/5 ring-1 ring-white/10 p-6">
          <h2 className="text-xs uppercase tracking-[0.3em] text-slate-400 mb-4">Services surveillés</h2>
          {!data?.stats?.probes?.length ? (
            <div className="text-center py-12 text-slate-400">Aucune donnée disponible.</div>
          ) : (
            <ul className="divide-y divide-white/10">
              {data.stats.probes.map((p) => {
                const Icon = PROBE_ICONS[p.key] || Activity;
                const last = p.timeline.length ? p.timeline[p.timeline.length - 1] : null;
                const tone = !last ? "slate" : last.ok ? "emerald" : "rose";
                const dotClass = { emerald: "bg-emerald-500", rose: "bg-rose-500", slate: "bg-slate-500" }[tone];
                return (
                  <li key={p.key} className="py-4 flex items-center gap-4" data-testid={`status-probe-${p.key}`}>
                    <Icon className="h-5 w-5 text-slate-400 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-3 mb-2">
                        <span className="text-sm font-medium">{p.label}</span>
                        <div className="flex items-center gap-2">
                          <span className={`h-2 w-2 rounded-full ${dotClass}`} />
                          <span className={`text-xs tabular-nums ${p.uptime_pct >= 99 ? "text-emerald-300" : p.uptime_pct >= 95 ? "text-amber-300" : "text-rose-300"}`}>
                            {p.uptime_pct} %
                          </span>
                        </div>
                      </div>
                      <Sparkline timeline={p.timeline} />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <p className="text-center text-[11px] text-slate-500 mt-8">
          Sondes exécutées chaque heure · {data?.stats?.samples || 0} relevé(s) · dernière mise à jour {data?.stats?.generated_at ? new Date(data.stats.generated_at).toLocaleString("fr-FR") : "—"}
        </p>
      </main>
    </div>
  );
}

const Sparkline = ({ timeline }) => {
  if (!timeline?.length) {
    return <div className="text-[11px] text-slate-500 italic">Pas encore de relevé sur la fenêtre.</div>;
  }
  return (
    <div className="flex gap-[2px] h-6" data-testid="status-sparkline">
      {timeline.map((t, i) => (
        <span
          key={i}
          className={`flex-1 rounded-sm ${t.ok ? "bg-emerald-500/80" : "bg-rose-500/80"}`}
          title={`${new Date(t.ts).toLocaleString("fr-FR")} — ${t.ok ? "OK" : "Échec"} (${t.duration_ms} ms)`}
          style={{ minWidth: 3 }}
        />
      ))}
    </div>
  );
};
