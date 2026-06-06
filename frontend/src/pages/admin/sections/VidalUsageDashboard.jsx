// Iter41 Phase 4 (2026-02) — Widget Dashboard usage VIDAL + Officines
// Inséré dans la section S058 (VIDAL) en bas. Affiche : totaux 30j,
// série quotidienne (mini graphe SVG), top consommateurs et top produits.
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import {
  BarChart3, Users, Pill, AlertTriangle, ShieldCheck, RefreshCw, Loader2
} from "lucide-react";

function StatCard({ icon: Icon, label, value, hint, color = "fuchsia" }) {
  return (
    <div className={`ring-1 ring-${color}-200 bg-${color}-50/40 rounded-lg p-3 flex items-start gap-3`} data-testid={`stat-${label}`}>
      <div className={`h-10 w-10 rounded-lg bg-${color}-100 flex items-center justify-center shrink-0`}>
        <Icon className={`h-5 w-5 text-${color}-600`} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
        <div className="text-xl font-bold text-slate-800 leading-tight">{value}</div>
        {hint && <div className="text-[10px] text-slate-500 mt-1 truncate">{hint}</div>}
      </div>
    </div>
  );
}

function MiniLineChart({ data, color = "#a21caf" }) {
  if (!data?.length) return <div className="text-xs text-slate-400 italic">Aucune donnée</div>;
  const max = Math.max(...data.map((d) => d.total || 0), 1);
  const w = 600; const h = 80;
  const step = w / Math.max(data.length - 1, 1);
  const pts = data.map((d, i) => `${i * step},${h - ((d.total || 0) / max) * (h - 8) - 4}`).join(" ");
  return (
    <div className="ring-1 ring-slate-200 bg-white rounded-lg p-2">
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="w-full h-20">
        <polyline points={pts} fill="none" stroke={color} strokeWidth="2" />
        {data.map((d, i) => (
          <circle key={i} cx={i * step} cy={h - ((d.total || 0) / max) * (h - 8) - 4} r="2" fill={color} />
        ))}
      </svg>
      <div className="flex justify-between text-[9px] text-slate-400 mt-1 font-mono">
        <span>{data[0]?.day}</span>
        <span>{data[data.length - 1]?.day}</span>
      </div>
    </div>
  );
}

export default function VidalUsageDashboard() {
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);
  const [vidal, setVidal] = useState(null);
  const [off, setOff] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const run = async () => {
      setLoading(true);
      try {
        const [v, o] = await Promise.all([
          apiClient.get(`/admin/vidal/usage?days=${days}`),
          apiClient.get(`/admin/officines/usage?days=${days}`),
        ]);
        setVidal(v.data);
        setOff(o.data);
      } catch (e) {
        console.warn("Dashboard load failed", e);
      }
      setLoading(false);
    };
    run();
  }, [days, reloadKey]);

  const reload = () => setReloadKey((k) => k + 1);

  return (
    <div className="space-y-4" data-testid="vidal-usage-dashboard">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-slate-700 inline-flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-fuchsia-600" />
          Tableau de bord d&apos;utilisation
        </h3>
        <div className="flex items-center gap-2">
          <select value={days} onChange={(e) => setDays(parseInt(e.target.value))}
                  className="text-xs px-2 py-1 rounded ring-1 ring-slate-300"
                  data-testid="dashboard-days-select">
            <option value="7">7 jours</option>
            <option value="30">30 jours</option>
            <option value="90">90 jours</option>
          </select>
          <button onClick={reload} disabled={loading}
                  className="text-xs px-2 py-1 rounded ring-1 ring-slate-300 hover:bg-slate-50 inline-flex items-center gap-1"
                  data-testid="dashboard-reload-btn">
            {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
          </button>
        </div>
      </div>

      {loading && !vidal && (
        <div className="text-xs text-slate-500 flex items-center gap-2 py-2">
          <Loader2 className="h-3 w-3 animate-spin" /> Chargement des statistiques…
        </div>
      )}

      {vidal && (
        <>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <StatCard icon={Pill} label="Appels VIDAL" value={vidal.totals.vidal_calls.toLocaleString("fr-FR")} hint={`sur ${days}j`} color="fuchsia" />
            <StatCard icon={Users} label="Utilisateurs uniques" value={vidal.totals.unique_users} color="violet" />
            <StatCard icon={AlertTriangle} label="Analyses Rx" value={vidal.totals.prescription_alerts} hint="prescriptions analysées" color="rose" />
            <StatCard icon={ShieldCheck} label="Entrées en cache" value={vidal.totals.cache_entries} color="emerald" />
          </div>

          <div>
            <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Activité quotidienne VIDAL</div>
            <MiniLineChart data={vidal.daily_series} color="#a21caf" />
          </div>

          <div className="grid lg:grid-cols-2 gap-3">
            <div className="ring-1 ring-slate-200 bg-white rounded-lg p-3">
              <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">🏆 Top consommateurs VIDAL</div>
              {vidal.top_consumers?.length ? (
                <ol className="space-y-1 text-xs">
                  {vidal.top_consumers.slice(0, 5).map((c, i) => (
                    <li key={i} className="flex justify-between border-b border-slate-50 last:border-0 pb-1" data-testid={`top-consumer-${i}`}>
                      <span className="truncate flex-1">{c.full_name || c.email} <span className="text-slate-400 text-[10px]">({c.role})</span></span>
                      <span className="font-mono text-slate-700">{c.total}</span>
                    </li>
                  ))}
                </ol>
              ) : <p className="text-[11px] text-slate-400 italic">Aucune activité</p>}
            </div>
            <div className="ring-1 ring-slate-200 bg-white rounded-lg p-3">
              <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">🎯 Mode VIDAL utilisé</div>
              <div className="space-y-1">
                {Object.entries(vidal.by_mode || {}).length ? (
                  Object.entries(vidal.by_mode).map(([mode, count]) => (
                    <div key={mode} className="flex items-center justify-between text-xs">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${mode === "production" ? "bg-rose-100 text-rose-700" : "bg-emerald-100 text-emerald-700"}`}>
                        {mode === "production" ? "🚀 PROD" : "🧪 TEST"}
                      </span>
                      <span className="font-mono">{count}</span>
                    </div>
                  ))
                ) : <p className="text-[11px] text-slate-400 italic">Aucune analyse Rx</p>}
              </div>
            </div>
          </div>
        </>
      )}

      {off && (
        <div className="ring-1 ring-emerald-200 bg-emerald-50/30 rounded-lg p-3 space-y-2">
          <div className="text-[10px] uppercase tracking-wider text-emerald-700 font-semibold">🏪 Activité Officines</div>
          <div className="grid sm:grid-cols-3 gap-2 text-xs">
            <div><span className="text-slate-500">Lookups portail :</span> <strong>{off.totals.portal_lookups}</strong></div>
            <div><span className="text-slate-500">!aizenta WA :</span> <strong>{off.totals.wa_aizenta_calls}</strong></div>
            <div><span className="text-slate-500">Officines enrôlées :</span> <strong>{off.totals.registered_officines_products}</strong></div>
          </div>
          {off.top_products?.length > 0 && (
            <div className="mt-2">
              <div className="text-[10px] text-emerald-700 mb-1">Top produits recherchés :</div>
              <ol className="space-y-0.5 text-xs">
                {off.top_products.slice(0, 5).map((p, i) => (
                  <li key={i} className="flex justify-between" data-testid={`top-product-${i}`}>
                    <span className="truncate flex-1">{p.product}</span>
                    <span className="font-mono text-slate-700">{p.count}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
