import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Ticket, RefreshCw, X, Check, Clock, AlertCircle, PauseCircle, Ban,
  ArrowRight, Search, MessageCircle, ChevronDown, ChevronRight,
  UserPlus, RotateCw, Plus, Trash2, ClipboardList, FileSpreadsheet, FileText,
  AlertTriangle,
} from "lucide-react";

/*
  Iter35o — Tickets d'intervention.
  Listing + filtres + actions (changer statut, clôturer). Création d'un
  nouveau ticket se fait depuis la fenêtre de chat WhatsApp d'un contact
  (Contacts.jsx → ConversationModal).
*/

const STATUS_META = {
  open: { label: "En attente", Icon: Clock, ring: "ring-amber-300", chip: "bg-amber-50 text-amber-700 ring-amber-200" },
  in_progress: { label: "En cours", Icon: ArrowRight, ring: "ring-sky-300", chip: "bg-sky-50 text-sky-700 ring-sky-200" },
  suspended: { label: "Suspendu", Icon: PauseCircle, ring: "ring-slate-300", chip: "bg-slate-100 text-slate-700 ring-slate-200" },
  done: { label: "Terminé", Icon: Check, ring: "ring-emerald-300", chip: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  cancelled: { label: "Annulé", Icon: Ban, ring: "ring-rose-300", chip: "bg-rose-50 text-rose-700 ring-rose-200" },
};

const fmtDateTime = (iso) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }); }
  catch { return iso; }
};

// Iter35r — formate une durée en secondes en chaîne courte FR (1h 30min / 3j / 45s)
const fmtSeconds = (s) => {
  if (s == null || s < 0) return "—";
  if (s < 60) return `${Math.round(s)} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  if (s < 86400) {
    const h = Math.floor(s / 3600);
    const m = Math.round((s % 3600) / 60);
    return m ? `${h}h ${m}min` : `${h}h`;
  }
  const d = Math.floor(s / 86400);
  const h = Math.round((s % 86400) / 3600);
  return h ? `${d}j ${h}h` : `${d}j`;
};

const StatusChip = ({ status }) => {
  const meta = STATUS_META[status] || STATUS_META.open;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${meta.chip}`} data-testid={`ticket-chip-${status}`}>
      <meta.Icon className="h-3 w-3" /> {meta.label}
    </span>
  );
};

export default function Tickets() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState("open_all");
  const [search, setSearch] = useState("");
  // Iter35p
  const [targets, setTargets] = useState([]);
  const [motifTemplates, setMotifTemplates] = useState([]);
  const [showTemplatesMgr, setShowTemplatesMgr] = useState(false);
  // Iter37d — Monthly cost aggregate (elevated viewers only)
  const [costSummary, setCostSummary] = useState(null);
  const [monthsBack, setMonthsBack] = useState(0);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/tickets", { params: filterStatus ? { status: filterStatus } : {} });
      setItems(r.data || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [filterStatus]);
  // Load targets + motif templates once
  useEffect(() => {
    apiClient.get("/me/notes-targets").then((r) => setTargets(r.data?.items || [])).catch(() => {});
    apiClient.get("/me/ticket-motif-templates").then((r) => setMotifTemplates(r.data || [])).catch(() => {});
  }, []);
  // Iter37d — Load cost summary (admin/sup only — endpoint returns 403 otherwise)
  useEffect(() => {
    apiClient.get("/me/tickets/cost-summary", { params: { months_back: monthsBack } })
      .then((r) => setCostSummary(r.data))
      .catch(() => setCostSummary(null));
  }, [monthsBack]);
  const reloadTemplates = () => apiClient.get("/me/ticket-motif-templates").then((r) => setMotifTemplates(r.data || [])).catch(() => {});

  // Iter37e — Download cost-summary as CSV or PDF (admin/sup only).
  const downloadCostExport = async (fmt) => {
    try {
      const r = await apiClient.get(`/me/tickets/cost-summary.${fmt}`, {
        params: { months_back: monthsBack },
        responseType: "blob",
      });
      const cd = r.headers["content-disposition"] || "";
      const m = cd.match(/filename="([^"]+)"/);
      const filename = m ? m[1] : `cout-interventions.${fmt}`;
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success(`Export ${fmt.toUpperCase()} téléchargé`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || `Échec export ${fmt.toUpperCase()}`);
    }
  };

  const filtered = useMemo(() => {
    if (!search.trim()) return items;
    const q = search.toLowerCase();
    return items.filter((t) =>
      (t.number || "").toLowerCase().includes(q)
      || (t.motif || "").toLowerCase().includes(q)
      || (t.contact_name || "").toLowerCase().includes(q)
    );
  }, [items, search]);

  // Iter38d — If the user is searching by ticket number and no result is found,
  // suggest switching to "Tous" because a status filter may be hiding it.
  const noResultsButFiltering = !loading && filtered.length === 0 && search.trim() && filterStatus !== "";

  return (
    <div className="space-y-6" data-testid="tickets-page">
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Support</p>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            <Ticket className="h-5 w-5 text-sawali-blue" /> Tickets d'intervention
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Numérotation automatique <code className="bg-slate-100 px-1 rounded">{"{CLIENT}-"}{new Date().getFullYear()}{"-NNNN"}</code> par Client Lié.
            Créez un ticket depuis la fenêtre de chat WhatsApp d'un contact.
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 px-3 py-2 text-sm disabled:opacity-60"
          data-testid="tickets-refresh"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Actualiser
        </button>
        <button
          onClick={() => setShowTemplatesMgr(true)}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 px-3 py-2 text-sm"
          data-testid="tickets-templates-btn"
          title="Gérer les motifs réutilisables"
        >
          <ClipboardList className="h-4 w-4" /> Modèles de motif ({motifTemplates.length})
        </button>
      </header>

      {/* Iter37d — Monthly cost aggregate (admin/sup only). Endpoint returns 403 for regulars so costSummary stays null. */}
      {costSummary && (
        <div className="rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-600 text-white p-4 shadow-md ring-1 ring-indigo-700/20" data-testid="tickets-cost-panel">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div>
              <p className="text-xs uppercase tracking-wider opacity-90 font-medium">Coût des interventions · {costSummary.month}</p>
              <p className="mt-1 text-2xl font-display font-bold tabular-nums">
                {Number(costSummary.grand_total || 0).toLocaleString("fr-FR")} <span className="text-sm font-normal opacity-90">XOF</span>
              </p>
              <p className="text-xs opacity-90 mt-0.5">
                {costSummary.grand_count} ticket(s) clôturé(s) · {costSummary.grand_hours}h
              </p>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <select value={monthsBack} onChange={(e) => setMonthsBack(Number(e.target.value))}
                className="rounded-lg bg-white/15 text-white px-2 py-1 text-xs ring-1 ring-white/30"
                data-testid="tickets-cost-month-select">
                {[0, 1, 2, 3, 6, 12].map((m) => (
                  <option key={m} value={m} className="text-slate-900">{m === 0 ? "Mois en cours" : `Il y a ${m} mois`}</option>
                ))}
              </select>
              {/* Iter37e — Exports CSV / PDF */}
              <button
                onClick={() => downloadCostExport("csv")}
                className="inline-flex items-center gap-1.5 rounded-lg bg-white/15 hover:bg-white/25 transition px-2.5 py-1 text-xs ring-1 ring-white/30 font-medium"
                title="Télécharger CSV (Excel)"
                data-testid="tickets-cost-export-csv"
              >
                <FileSpreadsheet className="h-3.5 w-3.5" /> CSV
              </button>
              <button
                onClick={() => downloadCostExport("pdf")}
                className="inline-flex items-center gap-1.5 rounded-lg bg-white/15 hover:bg-white/25 transition px-2.5 py-1 text-xs ring-1 ring-white/30 font-medium"
                title="Télécharger PDF (A4 paysage)"
                data-testid="tickets-cost-export-pdf"
              >
                <FileText className="h-3.5 w-3.5" /> PDF
              </button>
            </div>
          </div>
          {Array.isArray(costSummary.by_client) && costSummary.by_client.length > 0 && (
            <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-1 text-xs">
              {costSummary.by_client.slice(0, 6).map((row) => (
                <div key={row.client_id} className="flex items-center justify-between bg-white/10 rounded-md px-2 py-1" data-testid={`tickets-cost-row-${row.client_id}`}>
                  <span className="truncate">{row.client_name}</span>
                  <span className="font-mono whitespace-nowrap">{Number(row.total_cost || 0).toLocaleString("fr-FR")} XOF <span className="opacity-70">·{row.count}</span></span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="flex gap-2 items-center flex-wrap">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Rechercher par n°, motif, contact…"
            className="w-full rounded-lg border border-slate-300 pl-8 pr-3 py-2 text-sm"
            data-testid="tickets-search"
          />
        </div>
        <div className="inline-flex rounded-lg ring-1 ring-slate-300 bg-slate-50 p-0.5" data-testid="tickets-filter">
          {[
            { v: "open_all", label: "Ouverts" },
            { v: "open", label: "En attente" },
            { v: "in_progress", label: "En cours" },
            { v: "suspended", label: "Suspendus" },
            { v: "done", label: "Terminés" },
            { v: "cancelled", label: "Annulés" },
            { v: "", label: "Tous" },
          ].map((f) => (
            <button
              key={f.v || "all"}
              onClick={() => setFilterStatus(f.v)}
              className={`text-xs px-2.5 py-1 rounded-md transition ${filterStatus === f.v ? "bg-sawali-blue text-white shadow-sm" : "text-slate-600 hover:bg-white"}`}
              data-testid={`tickets-filter-${f.v || "all"}`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <span className="text-xs text-slate-500" data-testid="tickets-count">{filtered.length} ticket(s)</span>
      </div>

      {loading ? (
        <div className="text-center text-slate-500 py-10">Chargement…</div>
      ) : filtered.length === 0 ? (
        <div className="text-center text-slate-500 py-10" data-testid="tickets-empty">
          {search.trim() ? (
            <>
              <p>Aucun ticket dans cette liste.</p>
              {noResultsButFiltering && (
                <div className="mt-3 inline-flex items-center gap-2 rounded-lg bg-amber-50 ring-1 ring-amber-200 text-amber-900 px-3 py-2 text-xs" data-testid="tickets-search-hint">
                  <AlertTriangle className="h-4 w-4" />
                  <span>
                    Aucun ticket trouvé avec ce numéro <strong>parmi les "{filterStatus === "open_all" ? "Ouverts" : filterStatus}"</strong>.
                  </span>
                  <button
                    onClick={() => setFilterStatus("")}
                    data-testid="tickets-search-switch-all"
                    className="ml-1 underline font-semibold hover:text-amber-700"
                  >
                    Chercher dans tous les statuts (y compris terminés/annulés) →
                  </button>
                </div>
              )}
            </>
          ) : (
            <div className="rounded-xl border border-dashed border-slate-300 p-12 text-center">
              <Ticket className="h-10 w-10 text-slate-300 mx-auto mb-2" />
              <p className="text-slate-500 text-sm">Aucun ticket. Créez-en un depuis la fenêtre de chat WhatsApp d'un contact.</p>
              <Link to="/portal/contacts" className="inline-flex items-center gap-1 mt-2 text-sm text-sawali-blue hover:underline">
                <MessageCircle className="h-4 w-4" /> Ouvrir les contacts
              </Link>
            </div>
          )}
        </div>
      ) : (
        <ul className="space-y-2">
          {filtered.map((t) => <TicketRow key={t.id} t={t} reload={load} targets={targets} />)}
        </ul>
      )}
      {showTemplatesMgr && (
        <MotifTemplatesModal
          templates={motifTemplates}
          onClose={() => setShowTemplatesMgr(false)}
          onChange={reloadTemplates}
        />
      )}
    </div>
  );
}

function TicketRow({ t, reload, targets }) {
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [resolutionNote, setResolutionNote] = useState("");
  const isClosed = t.status === "done" || t.status === "cancelled";

  const changeStatus = async (newStatus) => {
    setBusy(true);
    try {
      await apiClient.patch(`/me/tickets/${t.id}`, { status: newStatus });
      toast.success("Statut mis à jour");
      await reload();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setBusy(false); }
  };

  const assignTo = async (userId) => {
    setBusy(true);
    try {
      await apiClient.post(`/me/tickets/${t.id}/assign`, { user_id: userId || "" });
      toast.success(userId ? "Ticket affecté" : "Affectation retirée");
      await reload();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setBusy(false); }
  };

  const reopen = async () => {
    const motif = window.prompt("Motif de la réouverture (laisser vide pour réutiliser le motif initial) :", "");
    if (motif === null) return;
    setBusy(true);
    try {
      const r = await apiClient.post(`/me/tickets/${t.id}/reopen`, { motif: motif || null });
      if (r.data?.ok) {
        toast.success(`Ticket rouvert : ${r.data.ticket.number}`);
        await reload();
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setBusy(false); }
  };

  const close = async (outcome) => {
    if (!window.confirm(outcome === "done" ? "Clôturer comme TERMINÉ ?" : "ANNULER ce ticket ?")) return;
    setBusy(true);
    try {
      const r = await apiClient.post(`/me/tickets/${t.id}/close`, { outcome, resolution_note: resolutionNote || null });
      toast.success("Ticket clôturé");
      if (r.data?.notification?.sent) toast.info("Notification WhatsApp envoyée au contact");
      else if (r.data?.notification?.error) toast.warning(`Notification non envoyée : ${r.data.notification.error}`);
      await reload();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setBusy(false); }
  };

  return (
    <li className="rounded-xl border border-slate-200 bg-white hover:shadow-sm transition" data-testid={`ticket-row-${t.id}`}>
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left flex-wrap"
        data-testid={`ticket-toggle-${t.id}`}
      >
        {expanded ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />}
        <code className="font-mono text-xs bg-slate-100 px-2 py-0.5 rounded text-slate-800">{t.number}</code>
        {t.root_number && t.root_number !== t.number && (
          <span className="text-[9px] uppercase tracking-wider text-fuchsia-700 bg-fuchsia-50 ring-1 ring-fuchsia-200 rounded px-1" title={`Réouverture de ${t.root_number}`}>
            REOPEN
          </span>
        )}
        <StatusChip status={t.status} />
        <span className="flex-1 truncate text-sm text-slate-800 min-w-[120px]">{t.motif}</span>
        {/* Iter35r — Client lié + Entreprise */}
        {(t.client_label || t.company_label) && (
          <span className="text-[10px] text-indigo-700 bg-indigo-50 ring-1 ring-indigo-200 rounded-full px-2 py-0.5 inline-flex items-center gap-1" title="Client lié / Entreprise">
            🏢 {[t.company_label, t.client_label].filter(Boolean).join(" · ")}
          </span>
        )}
        {t.assigned_to_label && (
          <span className="text-[10px] text-sky-700 bg-sky-50 ring-1 ring-sky-200 rounded-full px-2 py-0.5 inline-flex items-center gap-1" title={`Affecté à ${t.assigned_to_label}`}>
            <UserPlus className="h-3 w-3" /> {t.assigned_to_label}
          </span>
        )}
        {/* Iter35r — Durées : ouverture & pause */}
        {!isClosed && t.age_seconds != null && (
          <span
            className={`text-[10px] rounded-full px-2 py-0.5 ring-1 inline-flex items-center gap-1 tabular-nums ${
              t.age_seconds > 7 * 86400 ? "bg-rose-50 text-rose-700 ring-rose-300" :
              t.age_seconds > 3 * 86400 ? "bg-amber-50 text-amber-700 ring-amber-300" :
              "bg-slate-50 text-slate-600 ring-slate-200"
            }`}
            title="Durée depuis l'ouverture"
            data-testid={`ticket-age-${t.id}`}
          >
            <Clock className="h-3 w-3" /> {fmtSeconds(t.age_seconds)}
          </span>
        )}
        {t.pause_seconds > 0 && (
          <span
            className="text-[10px] bg-purple-50 text-purple-700 ring-1 ring-purple-200 rounded-full px-2 py-0.5 inline-flex items-center gap-1 tabular-nums"
            title="Temps cumulé en pause (suspendu)"
            data-testid={`ticket-pause-${t.id}`}
          >
            <PauseCircle className="h-3 w-3" /> {fmtSeconds(t.pause_seconds)}
          </span>
        )}
        <span className="text-[11px] text-slate-500 shrink-0">{t.contact_name || "—"}</span>
        <span className="text-[11px] text-slate-400 shrink-0 tabular-nums">{fmtDateTime(t.opened_at)}</span>
      </button>
      {expanded && (
        <div className="border-t border-slate-200 p-4 space-y-3 bg-slate-50/50" data-testid={`ticket-detail-${t.id}`}>
          <div className="grid sm:grid-cols-2 gap-3 text-xs">
            <Field label="Ouvert par" value={t.opened_by_label} />
            <Field label="Ouvert le" value={fmtDateTime(t.opened_at)} />
            <Field label="Contact" value={t.contact_name} />
            <Field label="Téléphone" value={t.contact_phone || "—"} />
            {t.assigned_to_label && <Field label="Affecté à" value={t.assigned_to_label} />}
            {t.parent_ticket_id && <Field label="Réouverture de" value={t.root_number} />}
            {t.closed_at && <Field label="Clôturé le" value={fmtDateTime(t.closed_at)} />}
            {t.closed_by_label && <Field label="Clôturé par" value={t.closed_by_label} />}
            {/* Iter37c — Cost (visible only when backend exposes it, i.e. elevated viewer) */}
            {t.cost_amount != null && (
              <Field label="💰 Coût" value={`${Number(t.cost_amount).toLocaleString("fr-FR")} XOF ${t.cost_mode === "flat" ? "(forfait)" : t.active_hours != null ? `(${t.active_hours}h × ${Number(t.cost_hourly_rate || 0).toLocaleString("fr-FR")})` : ""}`} />
            )}
          </div>
          {!isClosed && targets && targets.length > 0 && (
            <div className="flex items-center gap-2 text-xs">
              <label className="text-slate-500 font-semibold">Affecter à :</label>
              <select
                value={t.assigned_to_id || ""}
                onChange={(e) => assignTo(e.target.value)}
                disabled={busy}
                className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs"
                data-testid={`ticket-${t.id}-assign`}
              >
                <option value="">— Personne —</option>
                {targets.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.is_self ? "Moi-même" : u.full_name}{u.role && !u.is_self ? ` (${u.role})` : ""}
                  </option>
                ))}
              </select>
            </div>
          )}
          {t.resolution_note && (
            <div className="rounded-lg bg-white ring-1 ring-slate-200 p-2.5">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Note de résolution</p>
              <p className="text-xs text-slate-800 whitespace-pre-wrap">{t.resolution_note}</p>
            </div>
          )}
          {!isClosed && (
            <div className="space-y-2">
              <div className="flex flex-wrap gap-2">
                {t.status !== "in_progress" && (
                  <button onClick={() => changeStatus("in_progress")} disabled={busy} className="rounded-md bg-sky-50 text-sky-700 ring-1 ring-sky-200 hover:bg-sky-100 px-2.5 py-1 text-xs disabled:opacity-50" data-testid={`ticket-${t.id}-set-in-progress`}>
                    → En cours
                  </button>
                )}
                {t.status !== "suspended" && (
                  <button onClick={() => changeStatus("suspended")} disabled={busy} className="rounded-md bg-slate-100 text-slate-700 ring-1 ring-slate-200 hover:bg-slate-200 px-2.5 py-1 text-xs disabled:opacity-50" data-testid={`ticket-${t.id}-set-suspended`}>
                    ⏸ Suspendre
                  </button>
                )}
                {t.status !== "open" && (
                  <button onClick={() => changeStatus("open")} disabled={busy} className="rounded-md bg-amber-50 text-amber-700 ring-1 ring-amber-200 hover:bg-amber-100 px-2.5 py-1 text-xs disabled:opacity-50" data-testid={`ticket-${t.id}-set-open`}>
                    → En attente
                  </button>
                )}
              </div>
              <textarea
                value={resolutionNote}
                onChange={(e) => setResolutionNote(e.target.value)}
                rows={2}
                placeholder="Note de résolution (optionnelle, transmise dans le ticket)"
                className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-xs resize-none"
                data-testid={`ticket-${t.id}-resolution`}
              />
              <div className="flex gap-2">
                <button onClick={() => close("done")} disabled={busy} className="inline-flex items-center gap-1 rounded-md bg-emerald-600 text-white hover:bg-emerald-700 px-3 py-1.5 text-xs disabled:opacity-50" data-testid={`ticket-${t.id}-close-done`}>
                  <Check className="h-3.5 w-3.5" /> Clôturer (Terminé)
                </button>
                <button onClick={() => close("cancelled")} disabled={busy} className="inline-flex items-center gap-1 rounded-md bg-rose-600 text-white hover:bg-rose-700 px-3 py-1.5 text-xs disabled:opacity-50" data-testid={`ticket-${t.id}-close-cancelled`}>
                  <Ban className="h-3.5 w-3.5" /> Annuler
                </button>
              </div>
            </div>
          )}
          {/* Iter35p — Reopen button on closed tickets */}
          {isClosed && (
            <div className="flex">
              <button
                onClick={reopen}
                disabled={busy}
                className="inline-flex items-center gap-1 rounded-md bg-fuchsia-600 text-white hover:bg-fuchsia-700 px-3 py-1.5 text-xs disabled:opacity-50"
                data-testid={`ticket-${t.id}-reopen`}
                title="Créer un nouveau ticket lié (TKT-...-R1) pour ce contact"
              >
                <RotateCw className="h-3.5 w-3.5" /> Rouvrir (créer un ticket lié)
              </button>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

// Iter35p — Modale de gestion des modèles de motif (admin/superviseur)
function MotifTemplatesModal({ templates, onClose, onChange }) {
  const [label, setLabel] = useState("");
  const [motif, setMotif] = useState("");
  const [busy, setBusy] = useState(false);

  const create = async () => {
    if (!label.trim() || !motif.trim()) {
      toast.error("Label et motif sont obligatoires");
      return;
    }
    setBusy(true);
    try {
      await apiClient.post("/me/ticket-motif-templates", { label: label.trim(), motif: motif.trim() });
      toast.success("Modèle ajouté");
      setLabel("");
      setMotif("");
      onChange();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setBusy(false); }
  };
  const remove = async (id) => {
    if (!window.confirm("Supprimer ce modèle ?")) return;
    setBusy(true);
    try {
      await apiClient.delete(`/me/ticket-motif-templates/${id}`);
      toast.success("Modèle supprimé");
      onChange();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setBusy(false); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={(e) => e.target === e.currentTarget && onClose()} data-testid="motif-templates-modal">
      <div className="w-full max-w-xl rounded-2xl bg-white shadow-2xl flex flex-col max-h-[80vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
          <h2 className="font-display font-bold text-lg flex items-center gap-2"><ClipboardList className="h-4 w-4 text-sawali-blue" /> Modèles de motif</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-3 overflow-y-auto">
          <p className="text-xs text-slate-500">
            Ajoutez des motifs réutilisables (ex. <code>Panne onduleur</code>, <code>Demande de maintenance</code>) pour gagner du temps à la création des tickets.
          </p>
          <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 space-y-2">
            <p className="text-[11px] uppercase tracking-wider font-semibold text-slate-600">Nouveau modèle</p>
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Étiquette courte (60 chars max)"
              maxLength={60}
              className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              data-testid="motif-tpl-new-label"
            />
            <textarea
              value={motif}
              onChange={(e) => setMotif(e.target.value)}
              placeholder="Texte du motif injecté (200 chars max)"
              rows={2}
              maxLength={200}
              className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm resize-none"
              data-testid="motif-tpl-new-motif"
            />
            <button
              onClick={create}
              disabled={busy}
              className="inline-flex items-center gap-1 rounded-md bg-sawali-blue text-white hover:opacity-90 px-3 py-1.5 text-xs disabled:opacity-50"
              data-testid="motif-tpl-new-add"
            >
              <Plus className="h-3.5 w-3.5" /> Ajouter
            </button>
          </div>
          {templates.length === 0 ? (
            <p className="text-xs italic text-slate-400">Aucun modèle enregistré.</p>
          ) : (
            <ul className="space-y-1.5">
              {templates.map((tpl) => (
                <li key={tpl.id} className="flex items-start gap-2 rounded-md bg-white ring-1 ring-slate-200 p-2.5" data-testid={`motif-tpl-${tpl.id}`}>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-slate-800">{tpl.label}</p>
                    <p className="text-xs text-slate-600 truncate" title={tpl.motif}>{tpl.motif}</p>
                  </div>
                  <button onClick={() => remove(tpl.id)} disabled={busy} className="text-rose-500 hover:text-rose-700 disabled:opacity-50" data-testid={`motif-tpl-${tpl.id}-delete`}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

const Field = ({ label, value }) => (
  <div>
    <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">{label}</p>
    <p className="text-xs text-slate-800">{value || "—"}</p>
  </div>
);
