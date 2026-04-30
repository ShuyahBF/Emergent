import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { Database, Search, Download, RefreshCw, Eye, ChevronUp, ChevronDown } from "lucide-react";
import { toast } from "sonner";

export default function AdminDbExplorer() {
  const [collections, setCollections] = useState([]);
  const [collection, setCollection] = useState("api_traces");
  const [filters, setFilters] = useState([{ key: "", op: "eq", value: "" }]);
  const [limit, setLimit] = useState(200);
  const [sortBy, setSortBy] = useState("created_at");
  const [sortDir, setSortDir] = useState(-1);
  const [data, setData] = useState({ items: [], total_matched: 0, returned: 0 });
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(null);
  const [delimiter, setDelimiter] = useState(",");

  useEffect(() => {
    apiClient.get("/admin/db").then((r) => setCollections(r.data)).catch(() => {});
  }, []);

  const buildParams = () => {
    const p = { limit, sort_by: sortBy || undefined, sort_dir: sortDir };
    for (const f of filters) {
      if (!f.key.trim()) continue;
      const k = f.op === "eq" ? f.key : `${f.key}__${f.op}`;
      p[k] = f.value;
    }
    return p;
  };

  const load = async () => {
    if (!collection) return;
    setLoading(true);
    try {
      const r = await apiClient.get(`/admin/db/${collection}`, { params: buildParams() });
      setData(r.data);
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setLoading(false); }
  };

  useEffect(() => { load().catch(() => {}); /* eslint-disable-next-line */ }, [collection]);

  // Compute columns from the first ~10 items (most-frequent keys first)
  const columns = useMemo(() => {
    const counts = new Map();
    for (const it of data.items.slice(0, 30)) {
      for (const k of Object.keys(it)) counts.set(k, (counts.get(k) || 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([k]) => k).slice(0, 8);
  }, [data]);

  const exportFile = (asJson = false) => {
    if (!data.items.length) { toast.error("Aucune donnée à exporter"); return; }
    let blob, filename;
    if (asJson) {
      blob = new Blob([JSON.stringify(data.items, null, 2)], { type: "application/json" });
      filename = `${collection}-${new Date().toISOString().slice(0, 10)}.json`;
    } else {
      const sep = delimiter === ":" ? ":" : ",";
      // Use ALL keys union as columns (richer than the 8-shown columns)
      const allKeys = [...new Set(data.items.flatMap((it) => Object.keys(it)))];
      const escape = (v) => {
        if (v === null || v === undefined) return "";
        const s = typeof v === "string" ? v : JSON.stringify(v);
        const needsQuote = s.includes(sep) || s.includes('"') || s.includes("\n");
        return needsQuote ? `"${s.replace(/"/g, '""')}"` : s;
      };
      const lines = [allKeys.join(sep), ...data.items.map((it) => allKeys.map((k) => escape(it[k])).join(sep))];
      blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
      filename = `${collection}-${new Date().toISOString().slice(0, 10)}.${sep === ":" ? "csv" : "csv"}`;
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6" data-testid="admin-db-explorer-page">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2"><Database className="h-5 w-5 text-sawali-blue" /> Explorateur de base</h1>
          <p className="text-sm text-slate-500">Interroge n'importe quelle collection MongoDB whitelistée. Champs sensibles automatiquement masqués. Réservé au superviseur principal.</p>
        </div>
        <div className="flex gap-2 items-center">
          <select value={delimiter} onChange={(e) => setDelimiter(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-2 text-sm" title="Délimiteur d'export">
            <option value=",">Séparateur ,</option>
            <option value=":">Séparateur :</option>
          </select>
          <button onClick={() => exportFile(false)} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-3.5 py-2 text-sm hover:bg-sawali-blue-light" data-testid="db-export-csv"><Download className="h-4 w-4" /> Export CSV</button>
          <button onClick={() => exportFile(true)} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3.5 py-2 text-sm hover:border-sawali-blue hover:text-sawali-blue" data-testid="db-export-json">JSON</button>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <div>
            <label className="block text-xs font-semibold mb-1">Collection</label>
            <select value={collection} onChange={(e) => setCollection(e.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="db-collection-select">
              {collections.map((c) => <option key={c.name} value={c.name}>{c.name} ({c.count ?? "?"})</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">Trier par</label>
            <input value={sortBy} onChange={(e) => setSortBy(e.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" placeholder="created_at" />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">Direction</label>
            <select value={sortDir} onChange={(e) => setSortDir(parseInt(e.target.value, 10))} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
              <option value={-1}>Décroissant</option>
              <option value={1}>Croissant</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">Limite</label>
            <input type="number" value={limit} onChange={(e) => setLimit(parseInt(e.target.value, 10) || 200)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </div>
          <div className="flex items-end">
            <button onClick={load} disabled={loading} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light disabled:opacity-50 w-full justify-center" data-testid="db-run">
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Exécuter
            </button>
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="block text-xs font-semibold">Filtres</label>
            <button type="button" onClick={() => setFilters([...filters, { key: "", op: "eq", value: "" }])} className="text-xs text-sawali-blue hover:underline" data-testid="db-add-filter">+ ajouter</button>
          </div>
          {filters.map((f, i) => (
            <div key={i} className="grid grid-cols-1 sm:grid-cols-[1fr,auto,1fr,auto] gap-2 items-center">
              <input value={f.key} onChange={(e) => { const u = [...filters]; u[i] = { ...f, key: e.target.value }; setFilters(u); }} placeholder="champ (ex: status)" className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" data-testid={`db-filter-key-${i}`} />
              <select value={f.op} onChange={(e) => { const u = [...filters]; u[i] = { ...f, op: e.target.value }; setFilters(u); }} className="rounded-lg border border-slate-300 px-2 py-2 text-sm">
                <option value="eq">=</option>
                <option value="ne">≠</option>
                <option value="gte">≥</option>
                <option value="lte">≤</option>
                <option value="gt">&gt;</option>
                <option value="lt">&lt;</option>
                <option value="regex">regex</option>
              </select>
              <input value={f.value} onChange={(e) => { const u = [...filters]; u[i] = { ...f, value: e.target.value }; setFilters(u); }} placeholder="valeur" className="rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid={`db-filter-val-${i}`} />
              <button type="button" onClick={() => setFilters(filters.filter((_, idx) => idx !== i))} className="text-slate-400 hover:text-rose-600 px-2">×</button>
            </div>
          ))}
        </div>
      </div>

      <div className="text-xs text-slate-500">
        <strong>{data.returned}</strong> / {data.total_matched} document(s) — collection <code>{collection}</code>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[900px]">
          <thead className="bg-slate-50 text-xs uppercase tracking-widest text-slate-600">
            <tr>
              <th className="text-left px-3 py-2 w-8"></th>
              {columns.map((c) => (
                <th key={c} className="text-left px-3 py-2">
                  <button onClick={() => { if (sortBy === c) setSortDir(-sortDir); else setSortBy(c); load(); }} className="inline-flex items-center gap-1 hover:text-sawali-blue">
                    {c} {sortBy === c && (sortDir === 1 ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />)}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.items.length === 0 && <tr><td colSpan={columns.length + 1} className="px-3 py-12 text-center text-slate-500">Aucun document.</td></tr>}
            {data.items.map((it, i) => (
              <tr key={it.id || i} className="border-t border-slate-100 hover:bg-slate-50" data-testid={`db-row-${i}`}>
                <td className="px-3 py-2"><button onClick={() => setActive(it)} className="text-slate-500 hover:text-sawali-blue" title="Voir le JSON"><Eye className="h-4 w-4" /></button></td>
                {columns.map((c) => (
                  <td key={c} className="px-3 py-2 text-xs text-slate-700 truncate max-w-[280px] font-mono">{renderCell(it[c])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {active && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={() => setActive(null)}>
          <div className="bg-white rounded-xl w-full max-w-3xl max-h-[92vh] overflow-auto" onClick={(e) => e.stopPropagation()} data-testid="db-detail-modal">
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="font-display font-semibold">Document <code className="text-xs">{active.id || "(sans id)"}</code></h3>
              <button onClick={() => setActive(null)} className="text-slate-500 hover:text-rose-600">✕</button>
            </div>
            <pre className="text-[12px] bg-slate-900 text-emerald-200 p-4 font-mono whitespace-pre-wrap overflow-auto">{JSON.stringify(active, null, 2)}</pre>
          </div>
        </div>
      )}
    </div>
  );
}

function renderCell(v) {
  if (v === null || v === undefined) return <span className="text-slate-300">—</span>;
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "object") {
    try { return JSON.stringify(v).slice(0, 60); } catch { return String(v); }
  }
  const s = String(v);
  return s.length > 80 ? s.slice(0, 80) + "…" : s;
}
