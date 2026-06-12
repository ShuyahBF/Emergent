// Iter40 (2026-02) — Registre des erreurs (Modérateur/Admin/Superviseur).
// Tableau filtré + tri par date décroissante + recherche full-text sur
// Motif et SurNomWA. Superviseur peut purger.
import React, { useEffect, useMemo, useState, useCallback } from "react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import {
  AlertOctagon, Search, RefreshCw, Filter, Eye, Trash2, X, AlertTriangle, ShieldAlert, CheckCircle2,
} from "lucide-react";

const PAGE_SIZE = 50;

function fmtDateTime(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }); }
  catch { return iso; }
}

function statusBadge(s) {
  const sl = (s || "").toLowerCase();
  if (sl === "fatale" || sl === "fatal") {
    return { cls: "bg-rose-100 text-rose-800 ring-rose-300", icon: ShieldAlert, label: "Fatale" };
  }
  if (sl === "exception") {
    return { cls: "bg-amber-100 text-amber-800 ring-amber-300", icon: AlertTriangle, label: "Exception" };
  }
  return { cls: "bg-slate-100 text-slate-700 ring-slate-300", icon: AlertOctagon, label: s || "—" };
}

export default function ErrorRegistry() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState({});
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [codeClient, setCodeClient] = useState("");
  const [dateWindow, setDateWindow] = useState("");
  const [activeOnly, setActiveOnly] = useState(false);
  const [skip, setSkip] = useState(0);
  const [detail, setDetail] = useState(null);
  const [purgeOpen, setPurgeOpen] = useState(false);
  const [userRole, setUserRole] = useState("");
  // Iter43 — multi-sélection pour bulk delete
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [migrating, setMigrating] = useState(false);
  const { user: authUser } = useAuth();
  useEffect(() => {
    setUserRole(authUser?.role || "");
  }, [authUser]);

  const load = async () => {
    setLoading(true);
    try {
      const params = { limit: PAGE_SIZE, skip };
      if (search.trim()) params.search = search.trim();
      if (statusFilter) params.status = statusFilter;
      if (codeClient.trim()) params.code_client = codeClient.trim();
      if (dateWindow) params.date_window = dateWindow;
      if (activeOnly) params.active_only = true;
      const [r, sR] = await Promise.all([
        apiClient.get("/me/errors", { params }),
        apiClient.get("/me/errors/stats").catch(() => ({ data: {} })),
      ]);
      setItems(r.data?.items || []);
      setTotal(r.data?.total || 0);
      setStats(sR.data || {});
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const t = setTimeout(() => { load(); }, search ? 350 : 0);
    return () => clearTimeout(t);
  }, [skip, statusFilter, codeClient, dateWindow, activeOnly, search]); // eslint-disable-line react-hooks/exhaustive-deps

  const openDetail = useCallback(async (id) => {
    try {
      const r = await apiClient.get(`/me/errors/${id}`);
      setDetail(r.data);
      // Mark acknowledged on read
      apiClient.post(`/me/errors/${id}/acknowledge`).catch(() => {});
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
  }, []);

  const softDelete = async (id) => {
    if (!window.confirm("Supprimer (corbeille) cette erreur du registre ?")) return;
    try {
      await apiClient.delete(`/me/errors/${id}`);
      toast.success("Mise à la corbeille");
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
  };

  // Iter43 — multi-sélection + bulk delete + reset
  const isAdminOrSup = userRole === "admin" || userRole === "superviseur";
  const allSelected = items.length > 0 && items.every((it) => selectedIds.has(it.id));
  const someSelected = selectedIds.size > 0;

  const toggleSelect = (id) => {
    setSelectedIds((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const toggleSelectAll = () => {
    setSelectedIds((s) => {
      if (allSelected) {
        const next = new Set(s);
        items.forEach((it) => next.delete(it.id));
        return next;
      }
      const next = new Set(s);
      items.forEach((it) => next.add(it.id));
      return next;
    });
  };
  const clearSelection = () => setSelectedIds(new Set());

  const bulkDelete = async () => {
    if (selectedIds.size === 0) return;
    if (!window.confirm(`Supprimer DÉFINITIVEMENT ${selectedIds.size} erreur(s) sélectionnée(s) ?\n\nCette action est irréversible.`)) return;
    try {
      const r = await apiClient.post("/me/errors/bulk-delete", { ids: Array.from(selectedIds) });
      toast.success(`${r.data.deleted} erreur(s) supprimée(s)`);
      clearSelection();
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
  };

  const resetAll = async () => {
    const total = stats.total || 0;
    if (!window.confirm(`⚠️ Remise à ZÉRO du Registre des Erreurs\n\nCela supprime DÉFINITIVEMENT ${total} entrée(s).\n\nÊtes-vous absolument sûr ?`)) return;
    if (!window.confirm("Dernière confirmation : tout sera effacé.")) return;
    try {
      const r = await apiClient.post("/me/errors/reset");
      toast.success(`Registre remis à zéro (${r.data.deleted} entrée(s) supprimées)`);
      clearSelection();
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
  };

  const migrateFromTickets = async () => {
    if (!window.confirm("Rapatrier les erreurs envoyées par erreur sur le webhook Incidents (support_tickets) vers le Registre des Erreurs ?")) return;
    setMigrating(true);
    try {
      const r = await apiClient.post("/admin/error-registry/migrate-from-tickets");
      toast.success(`${r.data.migrated} migrées · ${r.data.skipped_already} déjà présentes`);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    } finally { setMigrating(false); }
  };

  const isSupervisor = userRole === "superviseur";

  return (
    <div className="space-y-4 p-4" data-testid="error-registry-page">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold flex items-center gap-2">
            <AlertOctagon className="h-6 w-6 text-rose-600" />
            Registre des erreurs
          </h1>
          <p className="text-sm text-slate-600 mt-1">
            Erreurs et exceptions remontées par les logiciels clients via le webhook
            <code className="bg-slate-100 px-1 mx-1 rounded text-[11px]">POST /api/errors/ingest</code>.
            Accepte les formats <em>plat</em> ou imbriqué (<code className="text-[10px]">{`{TicketDemnde:{...}}`}</code>, <code className="text-[10px]">{`{Erreur:{...}}`}</code> etc).
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button onClick={load} className="text-xs px-3 py-1.5 rounded ring-1 ring-slate-300 hover:bg-slate-50 inline-flex items-center gap-1" data-testid="err-refresh">
            <RefreshCw className="h-3 w-3" /> Rafraîchir
          </button>
          {isAdminOrSup && (
            <button onClick={migrateFromTickets} disabled={migrating}
                    className="text-xs px-3 py-1.5 rounded bg-sky-600 hover:bg-sky-700 text-white inline-flex items-center gap-1 disabled:opacity-50"
                    data-testid="err-migrate-btn">
              <RefreshCw className={`h-3 w-3 ${migrating ? "animate-spin" : ""}`} />
              {migrating ? "Migration…" : "Rapatrier depuis tickets"}
            </button>
          )}
          {isAdminOrSup && (
            <button onClick={resetAll}
                    className="text-xs px-3 py-1.5 rounded bg-rose-700 hover:bg-rose-800 text-white inline-flex items-center gap-1"
                    data-testid="err-reset-btn"
                    title="Supprime TOUTES les erreurs du registre">
              <Trash2 className="h-3 w-3" /> Remise à zéro
            </button>
          )}
          {isSupervisor && (
            <button onClick={() => setPurgeOpen(true)} className="text-xs px-3 py-1.5 rounded bg-rose-600 hover:bg-rose-700 text-white inline-flex items-center gap-1" data-testid="err-purge-btn">
              <Trash2 className="h-3 w-3" /> Purger par date
            </button>
          )}
        </div>
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Total" value={stats.total || 0} color="slate" />
        <KpiCard label="Non lues" value={stats.unacknowledged || 0} color="indigo" />
        <KpiCard label="Exceptions" value={stats.exception || 0} color="amber" icon={AlertTriangle} />
        <KpiCard label="Fatales" value={stats.fatale || 0} color="rose" icon={ShieldAlert} />
      </div>

      {/* Filters bar */}
      <div className="flex flex-wrap gap-2 items-center" data-testid="err-filters">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-2 top-2 h-3.5 w-3.5 text-slate-400" />
          <input value={search} onChange={(e) => setSearch(e.target.value)}
                 placeholder="Recherche (motif, SurnomWA)…"
                 className="w-full pl-7 pr-2 py-1.5 text-xs rounded ring-1 ring-slate-300"
                 data-testid="err-search" />
        </div>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
                className="text-xs px-2 py-1.5 rounded ring-1 ring-slate-300" data-testid="err-status-filter">
          <option value="">Tous statuts</option>
          <option value="exception">Exception</option>
          <option value="fatale">Fatale</option>
        </select>
        <input value={codeClient} onChange={(e) => setCodeClient(e.target.value)}
               placeholder="Code Client…"
               className="text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 w-32" data-testid="err-code-client" />
        <select value={dateWindow} onChange={(e) => setDateWindow(e.target.value)}
                className="text-xs px-2 py-1.5 rounded ring-1 ring-slate-300" data-testid="err-date-window">
          <option value="">Tout temps</option>
          <option value="today">Aujourd&apos;hui</option>
          <option value="7d">7 jours</option>
          <option value="30d">30 jours</option>
        </select>
        <label className="inline-flex items-center gap-1 text-xs text-slate-600">
          <input type="checkbox" checked={activeOnly} onChange={(e) => setActiveOnly(e.target.checked)} className="h-3.5 w-3.5" data-testid="err-active-only" />
          Actives seulement
        </label>
      </div>

      {/* Iter43 — Bulk action bar (visible quand sélection non vide) */}
      {isAdminOrSup && someSelected && (
        <div className="flex items-center justify-between gap-2 rounded-lg ring-1 ring-rose-300 bg-rose-50 px-3 py-2" data-testid="err-bulk-bar">
          <span className="text-xs text-rose-900 font-medium">
            {selectedIds.size} sélectionnée(s)
          </span>
          <div className="flex gap-2">
            <button onClick={clearSelection} className="text-xs px-2 py-1 rounded ring-1 ring-slate-300 bg-white hover:bg-slate-50" data-testid="err-bulk-clear">
              Annuler
            </button>
            <button onClick={bulkDelete} className="text-xs px-3 py-1 rounded bg-rose-600 hover:bg-rose-700 text-white inline-flex items-center gap-1" data-testid="err-bulk-delete">
              <Trash2 className="h-3 w-3" /> Supprimer la sélection
            </button>
          </div>
        </div>
      )}

      {/* Table */}
      <div className="overflow-x-auto ring-1 ring-slate-200 rounded-lg bg-white">
        <table className="min-w-full text-xs" data-testid="err-table">
          <thead className="bg-slate-50 text-slate-600 uppercase tracking-wider">
            <tr>
              {isAdminOrSup && (
                <th className="px-2 py-2 text-left w-8">
                  <input type="checkbox"
                         checked={allSelected}
                         onChange={toggleSelectAll}
                         className="h-3.5 w-3.5 cursor-pointer"
                         title={allSelected ? "Tout décocher" : "Tout cocher"}
                         data-testid="err-select-all" />
                </th>
              )}
              <th className="px-2 py-2 text-left">Date</th>
              <th className="px-2 py-2 text-left">Numéro</th>
              <th className="px-2 py-2 text-left">Statut</th>
              <th className="px-2 py-2 text-left">Code Client</th>
              <th className="px-2 py-2 text-left">CodeApp</th>
              <th className="px-2 py-2 text-left">Motif</th>
              <th className="px-2 py-2 text-left">SurNomWA</th>
              <th className="px-2 py-2 text-left">Actif</th>
              <th className="px-2 py-2 text-left"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading ? (
              <tr><td colSpan={isAdminOrSup ? 10 : 9} className="text-center text-slate-400 py-6">Chargement…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={isAdminOrSup ? 10 : 9} className="text-center text-slate-400 py-6 italic">Aucune erreur.</td></tr>
            ) : items.map((e) => {
              const b = statusBadge(e.StatutEnCours);
              const Icon = b.icon;
              const unack = !e.acknowledged;
              const isSel = selectedIds.has(e.id);
              return (
                <tr key={e.id} className={`hover:bg-slate-50 ${unack ? "bg-amber-50/30" : ""} ${isSel ? "bg-rose-50" : ""}`} data-testid={`err-row-${e.id}`}>
                  {isAdminOrSup && (
                    <td className="px-2 py-1.5">
                      <input type="checkbox"
                             checked={isSel}
                             onChange={() => toggleSelect(e.id)}
                             className="h-3.5 w-3.5 cursor-pointer"
                             data-testid={`err-select-${e.id}`} />
                    </td>
                  )}
                  <td className="px-2 py-1.5 whitespace-nowrap">{fmtDateTime(e.DateHeure_Création)}</td>
                  <td className="px-2 py-1.5 font-mono text-[10px]">{e.Numéro_Généré}</td>
                  <td className="px-2 py-1.5">
                    <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full ring-1 ${b.cls}`}>
                      <Icon className="h-2.5 w-2.5" /> {b.label}
                    </span>
                  </td>
                  <td className="px-2 py-1.5">{e.Code_Client || "—"}</td>
                  <td className="px-2 py-1.5"><code className="text-[10px]">{e.CodeApplicatif}</code></td>
                  <td className="px-2 py-1.5 max-w-md truncate" title={e.Motif}>{e.Motif}</td>
                  <td className="px-2 py-1.5">{e.SurNomWA || "—"}</td>
                  <td className="px-2 py-1.5">{e.estActif ? <CheckCircle2 className="h-3 w-3 text-emerald-600" /> : <X className="h-3 w-3 text-slate-400" />}</td>
                  <td className="px-2 py-1.5">
                    <div className="flex gap-1">
                      <button onClick={() => openDetail(e.id)} className="text-slate-500 hover:text-sawali-blue" title="Détails" data-testid={`err-view-${e.id}`}><Eye className="h-3.5 w-3.5" /></button>
                      <button onClick={() => softDelete(e.id)} className="text-slate-500 hover:text-rose-600" title="Supprimer" data-testid={`err-del-${e.id}`}><Trash2 className="h-3.5 w-3.5" /></button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between text-xs text-slate-500">
        <span>{total} erreur(s) au total · {Math.min(skip + PAGE_SIZE, total)} affichées</span>
        <div className="flex gap-1">
          <button disabled={skip === 0} onClick={() => setSkip(Math.max(0, skip - PAGE_SIZE))} className="px-2 py-1 ring-1 ring-slate-300 rounded disabled:opacity-50">←</button>
          <button disabled={skip + PAGE_SIZE >= total} onClick={() => setSkip(skip + PAGE_SIZE)} className="px-2 py-1 ring-1 ring-slate-300 rounded disabled:opacity-50">→</button>
        </div>
      </div>

      {/* Detail modal */}
      {detail && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setDetail(null)}>
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl p-5 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-semibold text-slate-800">Détails — {detail.Numéro_Généré}</h2>
              <button onClick={() => setDetail(null)} className="text-slate-400 hover:text-slate-700"><X className="h-4 w-4" /></button>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              {Object.entries(detail).filter(([k]) => !["_id", "deleted_at"].includes(k)).map(([k, v]) => (
                <div key={k} className="flex flex-col">
                  <span className="text-[10px] uppercase tracking-wider text-slate-500">{k}</span>
                  <span className="text-slate-800 break-words">
                    {typeof v === "boolean" ? (v ? "✓" : "✗") :
                     v === null || v === undefined ? "—" :
                     typeof v === "object" ? JSON.stringify(v) :
                     String(v).length > 200 ? `${String(v).slice(0, 200)}…` : String(v)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Purge modal — Supervisor only */}
      {purgeOpen && isSupervisor && (
        <PurgeModal onClose={() => setPurgeOpen(false)} onDone={() => { setPurgeOpen(false); load(); }} />
      )}
    </div>
  );
}

function KpiCard({ label, value, color, icon: Icon }) {
  const colorClass = {
    slate: "bg-slate-100 text-slate-700",
    indigo: "bg-indigo-100 text-indigo-700",
    amber: "bg-amber-100 text-amber-800",
    rose: "bg-rose-100 text-rose-800",
  }[color] || "bg-slate-100 text-slate-700";
  return (
    <div className={`rounded-lg ring-1 ring-slate-200 bg-white p-3`} data-testid={`err-kpi-${label.toLowerCase()}`}>
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">{label}</span>
        {Icon && <Icon className="h-3.5 w-3.5 text-slate-400" />}
      </div>
      <div className={`mt-1 text-2xl font-bold tabular-nums inline-block px-2 rounded ${colorClass}`}>{value}</div>
    </div>
  );
}

function PurgeModal({ onClose, onDone }) {
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [codeClient, setCodeClient] = useState("");
  const [running, setRunning] = useState(false);

  const purge = async () => {
    if (!fromDate && !toDate && !codeClient) {
      toast.error("Au moins un critère"); return;
    }
    if (!window.confirm(`Confirmer la PURGE DÉFINITIVE des erreurs sélectionnées ?\n\nDe : ${fromDate || "(début)"}\nÀ : ${toDate || "(maintenant)"}\nCode Client : ${codeClient || "(tous)"}\n\nCette action est IRRÉVERSIBLE.`)) return;
    setRunning(true);
    try {
      const r = await apiClient.post("/me/errors/purge", {
        from_date: fromDate || null, to_date: toDate || null, code_client: codeClient || null,
      });
      toast.success(`${r.data.deleted} erreur(s) purgée(s)`);
      onDone();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    } finally { setRunning(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-5 space-y-3" data-testid="err-purge-modal">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-slate-800 flex items-center gap-2">
            <Trash2 className="h-4 w-4 text-rose-600" /> Purger le registre
          </h2>
          <button onClick={onClose}><X className="h-4 w-4 text-slate-400 hover:text-slate-700" /></button>
        </div>
        <p className="text-[11px] text-rose-700 bg-rose-50 ring-1 ring-rose-200 rounded p-2">
          ⚠️ Cette opération supprime DÉFINITIVEMENT les erreurs. Réservée Superviseur.
        </p>
        <label className="block text-xs"><span className="block text-slate-600 mb-1">Du (YYYY-MM-DD)</span>
          <input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} className="w-full text-sm rounded ring-1 ring-slate-300 px-2 py-1" data-testid="err-purge-from" />
        </label>
        <label className="block text-xs"><span className="block text-slate-600 mb-1">Au (YYYY-MM-DD)</span>
          <input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} className="w-full text-sm rounded ring-1 ring-slate-300 px-2 py-1" data-testid="err-purge-to" />
        </label>
        <label className="block text-xs"><span className="block text-slate-600 mb-1">Code Client (facultatif)</span>
          <input value={codeClient} onChange={(e) => setCodeClient(e.target.value)} placeholder="ex: TENANT-xxx"
                 className="w-full text-sm rounded ring-1 ring-slate-300 px-2 py-1" data-testid="err-purge-code" />
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} disabled={running} className="text-xs px-3 py-1.5 rounded ring-1 ring-slate-300 hover:bg-slate-50">Annuler</button>
          <button onClick={purge} disabled={running} className="text-xs px-3 py-1.5 rounded bg-rose-600 hover:bg-rose-700 text-white inline-flex items-center gap-1" data-testid="err-purge-confirm">
            <Trash2 className="h-3 w-3" /> Confirmer la purge
          </button>
        </div>
      </div>
    </div>
  );
}
