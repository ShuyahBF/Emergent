// 2026-02 fork iter102/iter103 — Suggestions History (statuses + dates + vote).
// Backed by GET /api/admin/suggestions-history + PATCH/DELETE …/status.
import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { History, Loader2, RefreshCw, Search, X, Vote, RotateCcw } from "lucide-react";

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
      <div className="rounded-lg border border-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[900px]">
          <thead className="bg-slate-50">
            <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="px-4 py-2 w-24">ID</th>
              <th className="px-4 py-2">Titre</th>
              <th className="px-4 py-2 w-40">Statut</th>
              <th className="px-4 py-2 w-32">Date</th>
              <th className="px-4 py-2 w-56">Voter</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading && items.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-slate-500">
                  <Loader2 className="inline h-4 w-4 animate-spin mr-2" />
                  Chargement…
                </td>
              </tr>
            )}
            {!loading && filtered.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-slate-500" data-testid="suggestions-history-empty">
                  Aucune suggestion ne correspond aux filtres.
                </td>
              </tr>
            )}
            {filtered.map((it) => {
              const meta = STATUS_META[it.status] || STATUS_META.unknown;
              return (
                <tr
                  key={it.id}
                  className={`hover:bg-slate-50 transition ${it.overridden ? "bg-indigo-50/40" : ""}`}
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
                    {it.overridden && (
                      <span
                        className="ml-2 inline-block text-[10px] px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-700 border border-indigo-200"
                        title={`Statut modifié par ${it.override_by || "admin"}${it.override_reason ? ` — ${it.override_reason}` : ""}`}
                        data-testid={`suggestions-history-override-badge-${it.id}`}
                      >
                        modifié · {it.override_by || "admin"}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-500 font-mono">
                    {it.date_iso || "—"}
                  </td>
                  <td className="px-4 py-2">
                    <VoteControl item={it} onChanged={load} />
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


// ----------------------------------------------------------------------------
// 2026-02 fork iter103 — Vote control per row : select + submit + clear.
// Persists via PATCH /admin/suggestions-history/{id}/status (or DELETE to
// revert to the markdown-declared status).
// ----------------------------------------------------------------------------
function VoteControl({ item, onChanged }) {
  const [choice, setChoice] = useState(item.status);
  const [reason, setReason] = useState(item.override_reason || "");
  const [saving, setSaving] = useState(false);
  const [showReason, setShowReason] = useState(false);

  useEffect(() => {
    setChoice(item.status);
    setReason(item.override_reason || "");
  }, [item.status, item.override_reason]);

  const save = async () => {
    if (!choice || choice === "unknown") {
      toast.error("Choisir un statut valide");
      return;
    }
    setSaving(true);
    try {
      await apiClient.patch(`/admin/suggestions-history/${item.id}/status`, {
        status: choice,
        reason: reason.trim() || null,
      });
      toast.success(`${item.id} → ${STATUS_META[choice]?.label || choice}`);
      setShowReason(false);
      await onChanged?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setSaving(false);
    }
  };

  const clear = async () => {
    if (!window.confirm(`Retirer l'override et rétablir le statut du fichier pour ${item.id} ?`)) return;
    setSaving(true);
    try {
      await apiClient.delete(`/admin/suggestions-history/${item.id}/status`);
      toast.success(`${item.id} : override retiré`);
      setShowReason(false);
      await onChanged?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex items-center gap-1.5 flex-wrap" data-testid={`suggestions-vote-${item.id}`}>
      <select
        value={choice}
        onChange={(e) => setChoice(e.target.value)}
        className="text-[11px] rounded border border-slate-300 bg-white px-1.5 py-0.5"
        data-testid={`suggestions-vote-select-${item.id}`}
      >
        {STATUS_ORDER.filter((k) => k !== "unknown").map((k) => (
          <option key={k} value={k}>
            {STATUS_META[k].emoji} {STATUS_META[k].label}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={() => setShowReason((v) => !v)}
        className="text-[10px] px-1 py-0.5 rounded text-slate-500 hover:text-slate-700"
        title="Ajouter un motif"
      >
        …
      </button>
      <button
        type="button"
        onClick={save}
        disabled={saving || choice === item.status}
        className="inline-flex items-center gap-1 rounded bg-indigo-600 hover:bg-indigo-700 text-white text-[11px] px-2 py-0.5 disabled:opacity-50"
        data-testid={`suggestions-vote-save-${item.id}`}
      >
        {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Vote className="h-3 w-3" />}
        Voter
      </button>
      {item.overridden && (
        <button
          type="button"
          onClick={clear}
          disabled={saving}
          className="inline-flex items-center gap-1 rounded border border-slate-300 hover:bg-slate-100 text-slate-600 text-[11px] px-2 py-0.5"
          title="Retirer l'override"
          data-testid={`suggestions-vote-clear-${item.id}`}
        >
          <RotateCcw className="h-3 w-3" />
        </button>
      )}
      {showReason && (
        <input
          type="text"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Motif du vote (facultatif, ≤500)"
          maxLength={500}
          className="text-[11px] rounded border border-slate-300 bg-white px-2 py-0.5 flex-1 min-w-[180px]"
          data-testid={`suggestions-vote-reason-${item.id}`}
        />
      )}
    </div>
  );
}
