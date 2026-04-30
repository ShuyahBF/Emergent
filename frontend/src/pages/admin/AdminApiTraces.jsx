import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { Search, Download, RefreshCw, Trash2, AlertTriangle } from "lucide-react";
import { toast } from "sonner";

export default function AdminApiTraces() {
  const [items, setItems] = useState([]);
  const [q, setQ] = useState("");
  const [onlyErrors, setOnlyErrors] = useState(false);
  const [method, setMethod] = useState("");
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/api-traces", {
        params: {
          q: q || undefined,
          only_errors: onlyErrors || undefined,
          method: method || undefined,
          limit: 1000,
        },
      });
      setItems(r.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setLoading(false); }
  };

  useEffect(() => { load().catch(() => {}); /* eslint-disable-next-line */ }, []);

  const exportCsv = async () => {
    try {
      const r = await apiClient.get("/admin/api-traces/export.csv", {
        params: { only_errors: onlyErrors || undefined, method: method || undefined },
      });
      const blob = new Blob([r.data?.csv || ""], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `api-traces-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur export"); }
  };

  const clearAll = async () => {
    if (!window.confirm("Effacer toutes les traces API enregistrées ?")) return;
    try { const r = await apiClient.delete("/admin/api-traces"); toast.success(`${r.data.deleted} traces effacées`); await load(); }
    catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const stats = useMemo(() => {
    const total = items.length;
    const errors = items.filter((i) => i.status >= 400).length;
    const users = new Set(items.map((i) => i.user_email)).size;
    const avgMs = total ? Math.round(items.reduce((a, b) => a + (b.duration_ms || 0), 0) / total) : 0;
    return { total, errors, users, avgMs };
  }, [items]);

  return (
    <div className="space-y-6" data-testid="admin-api-traces-page">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2"><AlertTriangle className="h-5 w-5 text-amber-500" /> Traces API (Debug)</h1>
          <p className="text-sm text-slate-500">Journal de toutes les requêtes mutantes (POST/PUT/PATCH/DELETE) déclenchées par les utilisateurs. Réservé au superviseur principal.</p>
        </div>
        <div className="flex gap-2">
          <button onClick={load} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3.5 py-2 text-sm hover:border-sawali-blue hover:text-sawali-blue disabled:opacity-50" data-testid="traces-refresh">
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Actualiser
          </button>
          <button onClick={exportCsv} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-3.5 py-2 text-sm hover:bg-sawali-blue-light" data-testid="traces-export">
            <Download className="h-4 w-4" /> Export CSV
          </button>
          <button onClick={clearAll} className="inline-flex items-center gap-2 rounded-lg border border-rose-300 bg-rose-50 text-rose-700 px-3.5 py-2 text-sm hover:bg-rose-100" data-testid="traces-clear">
            <Trash2 className="h-4 w-4" /> Effacer
          </button>
        </div>
      </div>

      <div className="grid sm:grid-cols-4 gap-4">
        <Stat label="Événements" value={stats.total} testid="traces-stat-total" />
        <Stat label="Erreurs (≥400)" value={stats.errors} accent={stats.errors > 0 ? "text-rose-600" : ""} testid="traces-stat-errors" />
        <Stat label="Utilisateurs" value={stats.users} testid="traces-stat-users" />
        <Stat label="Durée moy." value={`${stats.avgMs} ms`} testid="traces-stat-duration" />
      </div>

      <form onSubmit={(e) => { e.preventDefault(); load(); }} className="flex items-center gap-2 flex-wrap">
        <div className="flex-1 relative min-w-[240px]">
          <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Rechercher email, URL, body…" className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-slate-300 focus:border-sawali-blue focus:outline-none" data-testid="traces-search" />
        </div>
        <select value={method} onChange={(e) => setMethod(e.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
          <option value="">Toutes méthodes</option>
          <option value="POST">POST</option>
          <option value="PUT">PUT</option>
          <option value="PATCH">PATCH</option>
          <option value="DELETE">DELETE</option>
        </select>
        <label className="inline-flex items-center gap-1 text-sm text-slate-700">
          <input type="checkbox" checked={onlyErrors} onChange={(e) => setOnlyErrors(e.target.checked)} /> erreurs uniquement
        </label>
        <button type="submit" className="rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light">Filtrer</button>
      </form>

      <div className="rounded-xl border border-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[1000px]">
          <thead className="bg-slate-50 text-xs uppercase tracking-widest text-slate-600">
            <tr>
              <th className="text-left px-3 py-2">Date</th>
              <th className="text-left px-3 py-2">Utilisateur</th>
              <th className="text-left px-3 py-2">Méthode</th>
              <th className="text-left px-3 py-2">URL</th>
              <th className="text-left px-3 py-2">HTTP</th>
              <th className="text-left px-3 py-2">Durée</th>
              <th className="text-left px-3 py-2">IP</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={7} className="px-3 py-12 text-center text-slate-500">Aucune trace.</td></tr>}
            {items.map((it) => (
              <tr key={it.id} className="border-t border-slate-100 hover:bg-slate-50 cursor-pointer" onClick={() => setActive(it)} data-testid={`trace-${it.id}`}>
                <td className="px-3 py-2 whitespace-nowrap text-slate-600">{new Date(it.created_at).toLocaleString("fr-FR")}</td>
                <td className="px-3 py-2"><div className="font-medium">{it.user_name || "—"}</div><div className="text-xs text-slate-500">{it.user_email}</div></td>
                <td className="px-3 py-2 font-mono text-xs"><span className="px-1.5 py-0.5 rounded bg-slate-100">{it.method}</span></td>
                <td className="px-3 py-2 font-mono text-xs text-slate-600 truncate max-w-[280px]">{it.url}</td>
                <td className="px-3 py-2 font-mono text-xs">
                  <span className={`px-1.5 py-0.5 rounded ${it.status >= 500 ? "bg-rose-100 text-rose-700" : it.status >= 400 ? "bg-amber-100 text-amber-700" : "bg-emerald-100 text-emerald-700"}`}>{it.status}</span>
                </td>
                <td className="px-3 py-2 tabular-nums text-xs">{it.duration_ms} ms</td>
                <td className="px-3 py-2 font-mono text-xs text-slate-500">{it.ip || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {active && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={() => setActive(null)}>
          <div className="bg-white rounded-xl w-full max-w-3xl max-h-[92vh] overflow-auto" onClick={(e) => e.stopPropagation()} data-testid="trace-detail-modal">
            <div className="flex items-center justify-between p-4 border-b">
              <div>
                <h3 className="font-display font-semibold flex items-center gap-2 flex-wrap">
                  <span className="px-1.5 py-0.5 rounded bg-slate-100 text-xs font-mono">{active.method}</span>
                  <span className="font-mono text-sm">{active.url}</span>
                  <span className={`px-1.5 py-0.5 rounded text-xs font-mono ${active.status >= 400 ? "bg-rose-100 text-rose-700" : "bg-emerald-100 text-emerald-700"}`}>{active.status}</span>
                </h3>
                <p className="text-xs text-slate-500 mt-1">{active.user_email} · {new Date(active.created_at).toLocaleString("fr-FR")} · {active.duration_ms} ms · IP {active.ip}</p>
              </div>
              <button onClick={() => setActive(null)} className="text-slate-500 hover:text-rose-600">✕</button>
            </div>
            <div className="p-4 space-y-3 text-sm">
              {active.module && <div className="text-xs"><span className="font-semibold">Page :</span> <code className="bg-slate-100 px-1 rounded">{active.module}</code></div>}
              {active.error && <div className="rounded bg-rose-50 border border-rose-200 text-rose-800 px-3 py-2"><strong>Erreur :</strong> {active.error}</div>}
              <div>
                <div className="text-xs font-semibold mb-1">Corps de la requête</div>
                <pre className="text-[12px] bg-slate-900 text-emerald-200 p-3 rounded overflow-auto max-h-72 font-mono whitespace-pre-wrap">{prettify(active.request_body)}</pre>
              </div>
              <div>
                <div className="text-xs font-semibold mb-1">Réponse</div>
                <pre className="text-[12px] bg-slate-900 text-sky-200 p-3 rounded overflow-auto max-h-72 font-mono whitespace-pre-wrap">{prettify(active.response_body)}</pre>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const Stat = ({ label, value, accent = "", testid }) => (
  <div className="rounded-xl border border-slate-200 bg-white p-5" data-testid={testid}>
    <p className="text-xs uppercase tracking-[0.2em] text-slate-500">{label}</p>
    <p className={`text-3xl font-display font-bold mt-1 tabular-nums ${accent || "text-slate-900"}`}>{value}</p>
  </div>
);

function prettify(value) {
  if (value === null || value === undefined) return "(vide)";
  if (typeof value !== "string") {
    try { return JSON.stringify(value, null, 2); } catch { return String(value); }
  }
  try { return JSON.stringify(JSON.parse(value), null, 2); } catch { return value; }
}
