// 2026-02 fork iter102 — Suggestions History (statuses + dates + filters).
// Backed by GET /api/admin/suggestions-history.
import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { History, Loader2, RefreshCw, Search, X } from "lucide-react";

const STATUS_META = {
  implemented: { emoji: "🟢", label: "IMPLÉMENTÉE", color: "emerald", key: "implemented" },
  accepted:    { emoji: "🟡", label: "ACCEPTÉE",    color: "amber",   key: "accepted" },
  proposed:    { emoji: "🔵", label: "PROPOSÉE",    color: "sky",     key: "proposed" },
  deferred:    { emoji: "⚪", label: "DIFFÉRÉE",    color: "slate",   key: "deferred" },
  refused:     { emoji: "🔴", label: "REFUSÉE",     color: "rose",    key: "refused" },
  unknown:     { emoji: "⚫", label: "Sans statut", color: "zinc",    key: "unknown" },
};

const STATUS_ORDER = ["implemented", "accepted", "proposed", "deferred", "refused", "unknown"];

const chipClass = (color, active) => {
  const map = {
    emerald: active
      ? "bg-emerald-600 text-white border-emerald-600"
      : "bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100",
    amber: active
      ? "bg-amber-600 text-white border-amber-600"
      : "bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100",
    sky: active
      ? "bg-sky-600 text-white border-sky-600"
      : "bg-sky-50 text-sky-700 border-sky-200 hover:bg-sky-100",
    slate: active
      ? "bg-slate-600 text-white border-slate-600"
      : "bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100",
    rose: active
      ? "bg-rose-600 text-white border-rose-600"
      : "bg-rose-50 text-rose-700 border-rose-200 hover:bg-rose-100",
    zinc: active
      ? "bg-zinc-600 text-white border-zinc-600"
      : "bg-zinc-50 text-zinc-700 border-zinc-200 hover:bg-zinc-100",
  };
  return map[color] || map.zinc;
};

const badgeClass = (color) => {
  const map = {
    emerald: "bg-emerald-100 text-emerald-800 border-emerald-200",
    amber: "bg-amber-100 text-amber-800 border-amber-200",
    sky: "bg-sky-100 text-sky-800 border-sky-200",
    slate: "bg-slate-100 text-slate-700 border-slate-200",
    rose: "bg-rose-100 text-rose-800 border-rose-200",
    zinc: "bg-zinc-100 text-zinc-700 border-zinc-200",
  };
  return map[color] || map.zinc;
};

export default function AdminSuggestionsHistory() {
  const [items, setItems] = useState([]);
  const [counts, setCounts] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState("all");
  const [q, setQ] = useState("");
  const [updatedAt, setUpdatedAt] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await apiClient.get("/admin/suggestions-history");
      setItems(r.data?.items || []);
      setCounts(r.data?.counts || {});
      setUpdatedAt(new Date().toISOString());
    } catch (err) {
      const detail = err?.response?.data?.detail || err?.message || "Erreur";
      setError(String(detail));
      toast.error(String(detail));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase();
    return items.filter((it) => {
      if (filter !== "all" && it.status !== filter) return false;
      if (!query) return true;
      const hay = `${it.id} ${it.title} ${it.summary}`.toLowerCase();
      return hay.includes(query);
    });
  }, [items, filter, q]);

  return (
    <div className="max-w-6xl space-y-5" data-testid="admin-suggestions-history-page">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <History className="h-6 w-6 text-indigo-600" />
            Historique des suggestions
          </h1>
          <p className="text-sm text-slate-600 mt-1">
            Liste parsée depuis <code className="text-xs bg-slate-100 px-1 py-0.5 rounded">/app/memory/SUGGESTIONS.md</code>{" "}
            avec statut ({items.length} suggestions).
          </p>
        </div>
        <button
          onClick={load}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50"
          data-testid="suggestions-history-refresh-btn"
          disabled={loading}
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          Actualiser
        </button>
      </div>

      {/* Status chips */}
      <div className="flex gap-2 flex-wrap" data-testid="suggestions-history-filters">
        <button
          onClick={() => setFilter("all")}
          className={`px-3 py-1.5 rounded-full text-xs font-medium border transition ${chipClass("zinc", filter === "all")}`}
          data-testid="suggestions-history-filter-all"
        >
          Toutes · {items.length}
        </button>
        {STATUS_ORDER.map((key) => {
          const meta = STATUS_META[key];
          const count = counts[key] || 0;
          if (count === 0 && filter !== key) return null;
          return (
            <button
              key={key}
              onClick={() => setFilter(key)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium border transition ${chipClass(meta.color, filter === key)}`}
              data-testid={`suggestions-history-filter-${key}`}
            >
              {meta.emoji} {meta.label} · {count}
            </button>
          );
        })}
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
        <input
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Rechercher un ID, titre ou mot-clé…"
          className="w-full rounded-lg border border-slate-300 bg-white pl-9 pr-9 py-2 text-sm"
          data-testid="suggestions-history-search-input"
        />
        {q && (
          <button
            onClick={() => setQ("")}
            className="absolute right-3 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-slate-700"
            data-testid="suggestions-history-search-clear"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Errors */}
      {error && (
        <div className="rounded-lg border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-800" data-testid="suggestions-history-error">
          {error}
        </div>
      )}

      {/* Table */}
      <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="px-4 py-2 w-24">ID</th>
              <th className="px-4 py-2">Titre</th>
              <th className="px-4 py-2 w-40">Statut</th>
              <th className="px-4 py-2 w-32">Date</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading && items.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-slate-500">
                  <Loader2 className="inline h-4 w-4 animate-spin mr-2" />
                  Chargement…
                </td>
              </tr>
            )}
            {!loading && filtered.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-slate-500" data-testid="suggestions-history-empty">
                  Aucune suggestion ne correspond aux filtres.
                </td>
              </tr>
            )}
            {filtered.map((it) => {
              const meta = STATUS_META[it.status] || STATUS_META.unknown;
              return (
                <tr
                  key={it.id}
                  className="hover:bg-slate-50 transition"
                  data-testid={`suggestions-history-row-${it.id}`}
                >
                  <td className="px-4 py-2 font-mono text-xs font-semibold text-indigo-700">{it.id}</td>
                  <td className="px-4 py-2">
                    <div className="font-medium text-slate-900">{it.title}</div>
                    {it.summary && (
                      <div className="text-xs text-slate-500 mt-0.5 line-clamp-2">
                        {it.summary}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border ${badgeClass(meta.color)}`}
                      data-testid={`suggestions-history-status-${it.id}`}
                    >
                      <span>{meta.emoji}</span>
                      <span>{meta.label}</span>
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-500 font-mono">
                    {it.date_iso || "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {updatedAt && (
        <div className="text-xs text-slate-400" data-testid="suggestions-history-updated-at">
          Dernière actualisation : {new Date(updatedAt).toLocaleString("fr-FR")}
        </div>
      )}
    </div>
  );
}
