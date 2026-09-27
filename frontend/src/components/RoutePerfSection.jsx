/*
  RoutePerfSection — lot 29 (performances) : temps de réponse du serveur par
  route depuis son dernier démarrage (GET /api/admin/perf/routes).
  Sert à repérer les pages lentes et à mesurer le gain de chaque lot.
*/
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Gauge, RefreshCw } from "lucide-react";

const SORTS = [["total", "Temps cumulé"], ["avg", "Moyenne"], ["max", "Maximum"], ["count", "Nombre d'appels"]];

export default function RoutePerfSection() {
  const [data, setData] = useState(null);
  const [sort, setSort] = useState("total");
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");

  const load = async (s = sort) => {
    try {
      const r = await apiClient.get(`/admin/perf/routes?limit=80&sort=${s}`);
      setData(r.data); setError("");
    } catch (e) { setError(e?.response?.data?.detail || "Mesures indisponibles"); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  // couleur de la moyenne : vert < 300 ms, orange < 1 s, rouge au-delà
  const tone = (ms) => (ms < 300 ? "text-emerald-700" : ms < 1000 ? "text-amber-700" : "text-rose-700");
  const rows = (data?.routes || []).filter((r) => !filter || r.path.toLowerCase().includes(filter.toLowerCase()));

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 space-y-3" data-testid="route-perf">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="font-display font-bold text-lg flex items-center gap-2"><Gauge className="h-5 w-5 text-sawali-blue" /> Temps de réponse par route</h2>
        <span className="text-xs text-slate-500">
          depuis le dernier démarrage{data?.since ? ` (${new Date(data.since).toLocaleString("fr-FR")})` : ""}
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filtrer (ex. contacts)"
            className="h-8 rounded-lg border border-slate-300 px-2 text-sm" data-testid="route-perf-filter" />
          <select value={sort} onChange={(e) => { setSort(e.target.value); load(e.target.value); }}
            className="h-8 rounded-lg border border-slate-300 px-2 text-sm" data-testid="route-perf-sort">
            {SORTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
          <button type="button" onClick={() => load()} className="inline-flex items-center gap-1 h-8 rounded-lg border border-slate-300 px-2 text-sm hover:bg-slate-50">
            <RefreshCw className="h-3.5 w-3.5" /> Actualiser
          </button>
        </div>
      </div>
      {error && <p className="text-sm text-rose-700">{error}</p>}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500 border-b">
              <th className="py-2 pr-3">Route</th><th className="py-2 px-2 text-right">Appels</th>
              <th className="py-2 px-2 text-right">Moyenne</th><th className="py-2 px-2 text-right">Maximum</th>
              <th className="py-2 px-2 text-right">&gt; 1 s</th><th className="py-2 pl-2 text-right">Cumul</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.method + r.path} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="py-1.5 pr-3 font-mono text-xs"><span className="text-slate-400 mr-1">{r.method}</span>{r.path}</td>
                <td className="py-1.5 px-2 text-right tabular-nums">{r.count}</td>
                <td className={`py-1.5 px-2 text-right tabular-nums font-medium ${tone(r.avg_ms)}`}>{r.avg_ms} ms</td>
                <td className="py-1.5 px-2 text-right tabular-nums">{r.max_ms} ms</td>
                <td className="py-1.5 px-2 text-right tabular-nums">{r.over_1s || ""}</td>
                <td className="py-1.5 pl-2 text-right tabular-nums">{r.total_s} s</td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={6} className="py-4 text-center text-slate-500">Aucune mesure pour l'instant.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}
