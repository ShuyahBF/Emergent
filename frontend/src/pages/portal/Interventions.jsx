import React, { useEffect, useMemo, useRef, useState } from "react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Plus, X, RefreshCw, Trash2, Wrench, Mic, MicOff, Square, Play, Pause, Building2, FileText, Printer, Pencil, ReceiptText, Download, Unlock, Lock, AlertTriangle, ChevronDown, ChevronUp, CalendarClock, CheckCircle2, Banknote } from "lucide-react";
import { toast } from "sonner";

const ELEVATED = new Set(["Moderation", "Administrateur", "Superviseur"]);
const ADMIN_LEVEL = new Set(["Administrateur", "Superviseur"]);
function isElevated(user) {
  if (!user) return false;
  if (user.role === "admin" || user.role === "superviseur") return true;
  return ELEVATED.has(user.tracked_role);
}
function canDelete(user) {
  if (!user) return false;
  if (user.role === "admin" || user.role === "superviseur") return true;
  return ADMIN_LEVEL.has(user.tracked_role);
}

const STATUSES = [
  { value: "planned", label: "Planifiée", color: "bg-sky-100 text-sky-700" },
  { value: "in_progress", label: "En cours", color: "bg-amber-100 text-amber-700" },
  { value: "completed", label: "Terminée", color: "bg-emerald-100 text-emerald-700" },
  { value: "cancelled", label: "Annulée", color: "bg-slate-100 text-slate-600" },
];

export default function ClientInterventions() {
  const { user } = useAuth();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [clients, setClients] = useState([]);
  // Iter34y — Filtre par client lié (en-tête de colonne)
  const [clientFilter, setClientFilter] = useState("all");
  // Iter43-fix — Filtre temporel + taux horaire + bouton Imprimer
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [hourlyRate, setHourlyRate] = useState(15000);
  const [printing, setPrinting] = useState(false);
  // Iter43-fix4 — Facturation des interventions
  const [selected, setSelected] = useState(() => new Set());
  const [generating, setGenerating] = useState(false);
  const [editing, setEditing] = useState(null);
  const [unlockBusy, setUnlockBusy] = useState(null);
  // Iter43-fix6 — Liste des factures émises + suivi paiement
  const [invoices, setInvoices] = useState([]);
  const [showInvoices, setShowInvoices] = useState(false);
  const [invoicesLoading, setInvoicesLoading] = useState(false);
  const [editingInvoice, setEditingInvoice] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const [r, rRate] = await Promise.all([
        apiClient.get("/me/interventions"),
        apiClient.get("/me/interventions/hourly-rate").catch(() => ({ data: { hourly_rate_xof: 15000 } })),
      ]);
      setItems(r.data || []);
      setHourlyRate(rRate.data?.hourly_rate_xof || 15000);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally { setLoading(false); }
  };
  const loadClients = async () => {
    try {
      const r = await apiClient.get("/me/clients");
      setClients(r.data || []);
    } catch { /* noop */ }
  };
  // Iter43-fix6 — Charge les factures émises (admin/sup voient tout, tenant voit les siennes)
  const loadInvoices = async () => {
    setInvoicesLoading(true);
    try {
      const r = await apiClient.get("/me/invoices/from-interventions", { params: { limit: 500 } });
      setInvoices(r.data || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur chargement factures");
    } finally { setInvoicesLoading(false); }
  };
  useEffect(() => { load(); loadClients(); }, []);

  const clientLabel = (cid) => {
    const c = clients.find((x) => x.id === cid);
    return c ? (c.company || c.full_name || c.id?.slice(0, 8)) : "—";
  };

  const filtered = useMemo(() => {
    return items.filter((i) => {
      // Filtre client
      if (clientFilter !== "all" && i.client_id !== clientFilter) return false;
      // Filtre statut
      if (statusFilter !== "all" && i.status !== statusFilter) return false;
      // Filtre dates
      const d = (i.intervention_date || "").slice(0, 10);
      if (fromDate && d < fromDate) return false;
      if (toDate && d > toDate) return false;
      return true;
    });
  }, [items, clientFilter, statusFilter, fromDate, toDate]);

  // Iter43-fix — Totaux affichés pour le set filtré
  const totals = useMemo(() => {
    const dur = filtered.reduce((acc, i) => acc + (Number(i.duration_hours) || 0), 0);
    return { hours: dur, cost: Math.round(dur * (Number(hourlyRate) || 0)) };
  }, [filtered, hourlyRate]);

  const formatXof = (n) => (Number(n) || 0).toLocaleString("fr-FR").replaceAll(",", " ");

  // Iter43-fix — Admin/Sup uniquement : voient les coûts + peuvent imprimer
  // Iter43-fix4 — Admin/Sup uniquement : voient les coûts + peuvent imprimer
  // Iter43-fix8 — Élargi aux tracked-users ayant le rôle "Administrateur" ou
  // "Superviseur" côté tenant (canDelete couvre ce cas) afin qu'ils puissent
  // également éditer/facturer les interventions de leur organisation.
  const isAdminOrSup = user?.role === "admin" || user?.role === "superviseur" || ADMIN_LEVEL.has(user?.tracked_role);

  const printPdf = async () => {
    setPrinting(true);
    try {
      const params = {};
      if (fromDate) params.from = fromDate;
      if (toDate) params.to = toDate;
      if (clientFilter !== "all") params.client_id = clientFilter;
      if (statusFilter !== "all") params.status = statusFilter;
      const r = await apiClient.get("/me/interventions/pdf", { params, responseType: "blob" });
      const blobUrl = URL.createObjectURL(r.data);
      const w = window.open(blobUrl, "_blank", "noopener");
      if (w) setTimeout(() => URL.revokeObjectURL(blobUrl), 8000);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Impossible d'imprimer");
    } finally { setPrinting(false); }
  };

  // Iter43-fix4 — Sélection multi + génération facture(s) groupées par tenant
  const toggleSelect = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const selectableIds = useMemo(() => filtered.filter((i) => !i.invoiced).map((i) => i.id), [filtered]);
  const allSelected = selectableIds.length > 0 && selectableIds.every((id) => selected.has(id));
  const toggleSelectAll = () => {
    setSelected((prev) => {
      if (allSelected) return new Set();
      return new Set(selectableIds);
    });
  };
  const selectedCount = selected.size;

  const downloadInvoicePdf = async (invoice) => {
    try {
      const r = await apiClient.get(`/me/invoices/from-interventions/${invoice.id}/pdf`, { responseType: "blob" });
      const blobUrl = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = `${invoice.invoice_number || "facture"}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(blobUrl), 8000);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Impossible de télécharger la facture");
    }
  };

  const downloadInvoiceByIdNumber = async (intervention) => {
    if (!intervention?.invoice_id) return;
    await downloadInvoicePdf({ id: intervention.invoice_id, invoice_number: intervention.invoice_number });
  };

  const generateInvoices = async () => {
    if (selected.size === 0) { toast.error("Sélectionnez au moins une intervention"); return; }
    const ids = Array.from(selected);
    if (!window.confirm(`Générer la/les facture(s) pour ${ids.length} intervention(s) ?\n\nLes interventions seront verrouillées (grisées) et regroupées par client.`)) return;
    setGenerating(true);
    try {
      const r = await apiClient.post("/me/invoices/from-interventions", { intervention_ids: ids });
      const newInvoices = r.data?.invoices || [];
      toast.success(`${newInvoices.length} facture(s) générée(s) — téléchargement…`);
      // Télécharge automatiquement chaque facture
      for (const inv of newInvoices) {
        await downloadInvoicePdf(inv);
      }
      setSelected(new Set());
      await load();
      await loadInvoices();
      setShowInvoices(true);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur génération facture");
    } finally { setGenerating(false); }
  };

  const unlockIntervention = async (i) => {
    if (!window.confirm(`Déverrouiller l'intervention « ${i.title} » ?\n\nNB : la facture ${i.invoice_number || ""} reste valide ; déverrouillez uniquement pour corriger une erreur.`)) return;
    setUnlockBusy(i.id);
    try {
      await apiClient.post(`/admin/interventions/${i.id}/unlock-invoice`);
      toast.success("Intervention déverrouillée");
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur déverrouillage");
    } finally { setUnlockBusy(null); }
  };

  const distinctClientIds = useMemo(() => {
    const set = new Set();
    items.forEach((i) => i.client_id && set.add(i.client_id));
    return Array.from(set);
  }, [items]);

  const del = async (id) => {
    if (!window.confirm("Supprimer cette intervention ?")) return;
    try {
      await apiClient.delete(`/me/interventions/${id}`);
      toast.success("Intervention supprimée");
      await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const elevated = isElevated(user);
  const deletable = canDelete(user);

  return (
    <div className="space-y-6" data-testid="client-interventions-page">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-display font-bold">Historique de nos interventions</h1>
          <p className="text-sm text-slate-500">Détail de toutes les interventions réalisées — filtrez par client, statut ou période.</p>
          {isAdminOrSup && (
            <p className="text-[11px] text-slate-500 mt-1">
              Taux horaire appliqué : <strong className="text-slate-700">{formatXof(hourlyRate)} XOF/h</strong>
            </p>
          )}
        </div>
        <div className="flex gap-2 flex-wrap">
          <button onClick={load} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 px-3 py-2 text-sm disabled:opacity-60" data-testid="interventions-refresh">
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Actualiser
          </button>
          {isAdminOrSup && (
            <button onClick={printPdf} disabled={printing || loading}
                    className="inline-flex items-center gap-2 rounded-lg bg-slate-800 hover:bg-slate-900 text-white px-3 py-2 text-sm disabled:opacity-60"
                    data-testid="interventions-print-btn"
                    title="Génère un PDF avec colonne Coût et total cumulé">
              <Printer className={`h-4 w-4 ${printing ? "animate-pulse" : ""}`} />
              {printing ? "Génération…" : "Imprimer (PDF)"}
            </button>
          )}
          {isAdminOrSup && (
            <button onClick={generateInvoices} disabled={generating || selectedCount === 0}
                    className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-2 text-sm disabled:opacity-50"
                    data-testid="interventions-invoice-btn"
                    title="Génère une facture par client à partir des interventions sélectionnées">
              <ReceiptText className={`h-4 w-4 ${generating ? "animate-pulse" : ""}`} />
              {generating ? "Génération…" : `Générer facture(s)${selectedCount > 0 ? ` (${selectedCount})` : ""}`}
            </button>
          )}
          {elevated && (
            <button onClick={() => setShowCreate(true)} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light" data-testid="interventions-create-btn">
              <Plus className="h-4 w-4" /> Nouvelle intervention
            </button>
          )}
        </div>
      </div>

      {/* Iter43-fix — Filtres période + statut */}
      <div className="flex items-end flex-wrap gap-3 rounded-xl bg-slate-50 ring-1 ring-slate-200 p-3" data-testid="interventions-filters">
        <label className="text-xs">
          <span className="block text-slate-600 mb-1">Du</span>
          <input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)}
                 className="rounded border border-slate-300 px-2 py-1.5 text-sm bg-white"
                 data-testid="interventions-filter-from" />
        </label>
        <label className="text-xs">
          <span className="block text-slate-600 mb-1">Au</span>
          <input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)}
                 className="rounded border border-slate-300 px-2 py-1.5 text-sm bg-white"
                 data-testid="interventions-filter-to" />
        </label>
        <label className="text-xs">
          <span className="block text-slate-600 mb-1">Statut</span>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
                  className="rounded border border-slate-300 px-2 py-1.5 text-sm bg-white"
                  data-testid="interventions-filter-status">
            <option value="all">Tous</option>
            {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </label>
        {(fromDate || toDate || statusFilter !== "all" || clientFilter !== "all") && (
          <button onClick={() => { setFromDate(""); setToDate(""); setStatusFilter("all"); setClientFilter("all"); }}
                  className="text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 bg-white hover:bg-slate-100"
                  data-testid="interventions-filter-reset">
            Réinitialiser
          </button>
        )}
        <div className="ml-auto text-xs text-slate-700">
          <span className="text-slate-500">Total affiché :</span>{" "}
          <strong className="text-slate-900" data-testid="interventions-total-count">{filtered.length}</strong> intervention(s) ·{" "}
          <strong className="text-slate-900" data-testid="interventions-total-hours">{totals.hours.toFixed(2)} h</strong>
          {isAdminOrSup && (
            <> · <strong className="text-emerald-700" data-testid="interventions-total-cost">{formatXof(totals.cost)} XOF</strong></>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[960px]">
          <thead className="bg-slate-50 text-xs uppercase text-slate-600">
            <tr>
              {isAdminOrSup && (
                <th className="px-3 py-3 w-10">
                  <input type="checkbox" checked={allSelected} onChange={toggleSelectAll}
                         className="h-4 w-4 rounded border-slate-300 cursor-pointer"
                         data-testid="interventions-select-all"
                         title={allSelected ? "Tout désélectionner" : "Tout sélectionner (non-facturées)"} />
                </th>
              )}
              <th className="text-left px-4 py-3">Référence</th>
              <th className="text-left px-4 py-3">Titre</th>
              <th className="text-left px-4 py-3">
                <div className="flex items-center gap-2">
                  <Building2 className="h-3 w-3" />
                  <span>Client lié</span>
                  <select
                    value={clientFilter}
                    onChange={(e) => setClientFilter(e.target.value)}
                    className="rounded border border-slate-300 px-1.5 py-0.5 text-[10px] font-normal normal-case bg-white"
                    data-testid="interventions-filter-client"
                    title="Filtrer par Client lié"
                  >
                    <option value="all">Tous ({items.length})</option>
                    {distinctClientIds.map((cid) => (
                      <option key={cid} value={cid}>{clientLabel(cid)} ({items.filter((i) => i.client_id === cid).length})</option>
                    ))}
                  </select>
                </div>
              </th>
              <th className="text-left px-4 py-3">Date</th>
              <th className="text-left px-4 py-3">Technicien</th>
              <th className="text-right px-4 py-3" data-testid="interventions-col-duration">Durée (h)</th>
              <th className="text-left px-4 py-3">Statut</th>
              <th className="text-left px-4 py-3">N° Facture</th>
              <th className="text-left px-4 py-3">Note vocale</th>
              {(deletable || isAdminOrSup) && <th className="text-right px-4 py-3">Actions</th>}
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={11} className="px-4 py-10 text-center text-slate-500">Chargement…</td></tr>}
            {!loading && filtered.length === 0 && (
              <tr><td colSpan={11} className="px-4 py-10 text-center text-slate-500">{clientFilter === "all" && !fromDate && !toDate && statusFilter === "all" ? "Aucune intervention enregistrée." : "Aucune intervention pour ces critères."}</td></tr>
            )}
            {filtered.map((i) => {
              const status = STATUSES.find((s) => s.value === i.status) || { label: i.status, color: "bg-slate-100 text-slate-700" };
              const dh = Number(i.duration_hours) || 0;
              const invoiced = !!i.invoiced;
              const isChecked = selected.has(i.id);
              return (
                <tr key={i.id}
                    className={`border-t border-slate-100 ${invoiced ? "bg-slate-50 text-slate-400" : "hover:bg-sky-50/60"}`}
                    data-testid={`intervention-row-${i.id}`}>
                  {isAdminOrSup && (
                    <td className="px-3 py-3 w-10">
                      <input type="checkbox" checked={isChecked} onChange={() => toggleSelect(i.id)}
                             disabled={invoiced}
                             className="h-4 w-4 rounded border-slate-300 cursor-pointer disabled:cursor-not-allowed"
                             data-testid={`intervention-select-${i.id}`}
                             title={invoiced ? "Déjà facturée — déverrouillez d'abord" : "Sélectionner"} />
                    </td>
                  )}
                  <td className="px-4 py-3 text-xs font-mono text-slate-500">{i.intervention_number || "—"}</td>
                  <td className={`px-4 py-3 font-medium ${invoiced ? "" : "text-slate-800"}`}>
                    {i.title}
                    {i.description && <p className="text-xs text-slate-500 font-normal mt-0.5 line-clamp-1">{i.description}</p>}
                  </td>
                  <td className="px-4 py-3 text-xs">
                    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 ring-1 ${invoiced ? "bg-slate-100 text-slate-500 ring-slate-200" : "bg-emerald-50 text-emerald-700 ring-emerald-200"}`}
                          data-testid={`intervention-client-${i.id}`}>
                      <Building2 className="h-3 w-3" /> {clientLabel(i.client_id)}
                    </span>
                  </td>
                  <td className="px-4 py-3">{i.intervention_date && new Date(i.intervention_date).toLocaleDateString("fr-FR")}</td>
                  <td className="px-4 py-3">{i.technician || "-"}</td>
                  <td className="px-4 py-3 text-right font-mono text-xs" data-testid={`intervention-duration-${i.id}`}>
                    {dh > 0 ? dh.toFixed(2) : "—"}
                  </td>
                  <td className="px-4 py-3"><span className={`text-xs px-2 py-1 rounded ${status.color}`}>{status.label}</span></td>
                  <td className="px-4 py-3">
                    {invoiced ? (
                      <button type="button" onClick={() => downloadInvoiceByIdNumber(i)}
                              className="inline-flex items-center gap-1 text-[11px] font-mono px-2 py-1 rounded ring-1 ring-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                              data-testid={`intervention-invoice-link-${i.id}`}
                              title="Télécharger la facture (PDF)">
                        <Lock className="h-3 w-3" />
                        {i.invoice_number || "—"}
                        <Download className="h-3 w-3" />
                      </button>
                    ) : (
                      <span className="text-[10px] text-slate-400">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {i.voice_note_url ? (
                      <div className="space-y-1">
                        <audio controls src={i.voice_note_url} className="h-8 max-w-[180px]" data-testid={`intervention-audio-${i.id}`} />
                        {i.voice_note_transcript && (
                          <p className="text-[10px] text-slate-600 italic line-clamp-2 max-w-[220px]" title={i.voice_note_transcript} data-testid={`intervention-transcript-${i.id}`}>
                            « {i.voice_note_transcript} »
                          </p>
                        )}
                      </div>
                    ) : <span className="text-[10px] text-slate-400">—</span>}
                  </td>
                  {(deletable || isAdminOrSup) && (
                    <td className="px-4 py-3 text-right">
                      <div className="inline-flex items-center gap-2 justify-end flex-wrap">
                        {isAdminOrSup && !invoiced && (
                          <button onClick={() => setEditing(i)}
                                  className="inline-flex items-center gap-1 text-xs text-sky-700 hover:underline"
                                  data-testid={`intervention-edit-${i.id}`}
                                  title="Modifier (tenant / durée / etc.)">
                            <Pencil className="h-3.5 w-3.5" /> Modifier
                          </button>
                        )}
                        {isAdminOrSup && invoiced && (
                          <button onClick={() => unlockIntervention(i)}
                                  disabled={unlockBusy === i.id}
                                  className="inline-flex items-center gap-1 text-xs text-amber-700 hover:underline disabled:opacity-50"
                                  data-testid={`intervention-unlock-${i.id}`}
                                  title="Déverrouille l'intervention (la facture reste valide)">
                            <Unlock className="h-3.5 w-3.5" /> {unlockBusy === i.id ? "…" : "Déverrouiller"}
                          </button>
                        )}
                        {deletable && !invoiced && (
                          <button onClick={() => del(i.id)} className="inline-flex items-center gap-1 text-xs text-rose-600 hover:underline" data-testid={`intervention-delete-${i.id}`}>
                            <Trash2 className="h-3.5 w-3.5" /> Supprimer
                          </button>
                        )}
                      </div>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {showCreate && (
        <CreateInterventionModal
          user={user}
          clients={clients}
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); load(); }}
        />
      )}

      {/* Iter43-fix6 — Section repliable : Factures émises + suivi paiement */}
      {isAdminOrSup && (
        <InvoicesPanel
          open={showInvoices}
          onToggle={() => {
            const next = !showInvoices;
            setShowInvoices(next);
            if (next && invoices.length === 0) loadInvoices();
          }}
          invoices={invoices}
          loading={invoicesLoading}
          onRefresh={loadInvoices}
          onEdit={(inv) => setEditingInvoice(inv)}
          onDownload={downloadInvoicePdf}
        />
      )}

      {editingInvoice && (
        <EditInvoicePaymentModal
          invoice={editingInvoice}
          onClose={() => setEditingInvoice(null)}
          onSaved={() => { setEditingInvoice(null); loadInvoices(); }}
        />
      )}

      {editing && (
        <EditInterventionModal
          intervention={editing}
          clients={clients}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
        />
      )}
    </div>
  );
}

// ============================================================
// Iter34y — Create intervention modal with Client picker + voice note
// ============================================================
const CreateInterventionModal = ({ user, clients, onClose, onCreated }) => {
  const [form, setForm] = useState({
    title: "",
    description: "",
    intervention_date: new Date().toISOString().slice(0, 10),
    technician: "",
    status: "completed",
    duration_hours: "",
    client_id: user?.client_id || user?.parent_client_id || user?.id || "",
    voice_note_url: "",
    voice_note_transcript: "",
  });
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!form.client_id) { toast.error("Client lié requis"); return; }
    if (!form.title.trim()) { toast.error("Le titre est requis"); return; }
    if (!form.intervention_date) { toast.error("Date requise"); return; }
    setSaving(true);
    try {
      const payload = {
        client_id: form.client_id,
        title: form.title.trim(),
        description: form.description || null,
        status: form.status,
        intervention_date: new Date(form.intervention_date).toISOString(),
        technician: form.technician || null,
        duration_hours: form.duration_hours ? Number(form.duration_hours) : null,
        attachments: [],
        voice_note_url: form.voice_note_url || null,
        voice_note_transcript: form.voice_note_transcript || null,
      };
      await apiClient.post("/me/interventions", payload);
      toast.success("Intervention créée");
      onCreated();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur lors de la création");
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={(e) => e.target === e.currentTarget && onClose()} data-testid="intervention-create-modal">
      <div className="w-full max-w-lg rounded-2xl bg-white shadow-2xl p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
            <Wrench className="h-5 w-5 text-sawali-blue" /> Nouvelle intervention
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900" data-testid="intervention-create-close"><X className="h-4 w-4" /></button>
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1 inline-flex items-center gap-1">
            <Building2 className="h-3 w-3 text-sawali-blue" /> Client lié *
          </label>
          <select
            value={form.client_id}
            onChange={(e) => setForm({ ...form, client_id: e.target.value })}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            data-testid="intervention-field-client"
          >
            <option value="">— Sélectionnez un client —</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>{c.company || c.full_name}{c.client_code ? ` · ${c.client_code}` : ""}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Titre *</label>
          <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Mise à jour du logiciel comptable" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="intervention-field-title" />
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Description</label>
          <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={3} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="intervention-field-description" />
        </div>
        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold mb-1">Date *</label>
            <input type="date" value={form.intervention_date} onChange={(e) => setForm({ ...form, intervention_date: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="intervention-field-date" />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">Statut</label>
            <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="intervention-field-status">
              {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">Technicien</label>
            <input value={form.technician} onChange={(e) => setForm({ ...form, technician: e.target.value })} placeholder="Nom du technicien" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="intervention-field-technician" />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">Durée (heures)</label>
            <input type="number" step="0.25" value={form.duration_hours} onChange={(e) => setForm({ ...form, duration_hours: e.target.value })} placeholder="2.5" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="intervention-field-duration" />
          </div>
        </div>

        <VoiceNoteRecorder
          value={form.voice_note_url}
          transcript={form.voice_note_transcript}
          onChange={(url) => setForm({ ...form, voice_note_url: url })}
          onTranscriptChange={(t) => setForm({ ...form, voice_note_transcript: t })}
        />

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="text-sm rounded-lg bg-slate-100 hover:bg-slate-200 px-4 py-2">Annuler</button>
          <button onClick={submit} disabled={saving} className="text-sm rounded-lg bg-sawali-blue hover:bg-sawali-blue-light text-white px-4 py-2 disabled:opacity-50" data-testid="intervention-create-save">
            {saving ? "Création…" : "Créer"}
          </button>
        </div>
      </div>
    </div>
  );
};

// ============================================================
// Iter34y — Voice note recorder (MediaRecorder → /me/upload-audio)
// Returns the absolute URL of the stored audio in onChange.
// Iter34z — Adds optional automatic transcription via /transcribe so the
// user sees the spoken text right under the audio player. The transcript
// is stored in the parent form state via onTranscriptChange.
// ============================================================
function VoiceNoteRecorder({ value, transcript, onChange, onTranscriptChange }) {
  const [recording, setRecording] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const mediaRef = useRef(null);
  const chunksRef = useRef([]);
  const lastBlobRef = useRef(null);

  const transcribe = async (blob) => {
    if (!blob) return;
    setTranscribing(true);
    try {
      const fd = new FormData();
      const mime = (blob.type || "audio/webm").split(";")[0];
      const ext = mime.split("/")[1] || "webm";
      fd.append("file", blob, `intervention-${Date.now()}.${ext}`);
      fd.append("language", "fr");
      const r = await apiClient.post("/transcribe", fd, { headers: { "Content-Type": "multipart/form-data" } });
      if (r.data?.text) {
        onTranscriptChange?.(r.data.text);
        toast.success("Transcription terminée");
      } else {
        toast.warning("Transcription vide");
      }
    } catch (err) {
      const detail = err?.response?.data?.detail;
      if (err?.response?.status === 503) {
        toast.info("Transcription non configurée (clé OpenAI manquante). La note vocale est sauvegardée sans texte.");
      } else {
        toast.error(detail || "Transcription échouée");
      }
    } finally { setTranscribing(false); }
  };

  const start = async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof window.MediaRecorder === "undefined") {
      toast.error("Votre navigateur ne supporte pas l'enregistrement audio.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
      const mime = candidates.find((m) => window.MediaRecorder.isTypeSupported && window.MediaRecorder.isTypeSupported(m)) || "";
      const rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      chunksRef.current = [];
      rec.ondataavailable = (e) => e.data && e.data.size && chunksRef.current.push(e.data);
      rec.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
        stream.getTracks().forEach((t) => t.stop());
        lastBlobRef.current = blob;
        setUploading(true);
        try {
          const fd = new FormData();
          const ext = (rec.mimeType || "audio/webm").split(";")[0].split("/")[1] || "webm";
          fd.append("file", blob, `intervention-${Date.now()}.${ext}`);
          const r = await apiClient.post("/me/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
          if (r.data?.public_url || r.data?.url) {
            onChange(r.data.public_url || r.data.url);
            toast.success("Note vocale enregistrée");
            // Fire-and-forget transcription
            transcribe(blob);
          } else {
            toast.error("Upload échoué");
          }
        } catch (err) {
          toast.error(err?.response?.data?.detail || "Erreur upload audio");
        } finally { setUploading(false); }
      };
      rec.start();
      mediaRef.current = rec;
      setRecording(true);
    } catch (err) {
      toast.error("Accès au micro refusé");
    }
  };
  const stop = () => {
    if (mediaRef.current && mediaRef.current.state !== "inactive") {
      mediaRef.current.stop();
      mediaRef.current = null;
    }
    setRecording(false);
  };

  const retranscribe = () => {
    if (lastBlobRef.current) transcribe(lastBlobRef.current);
    else toast.info("Aucun audio à retranscrire (réenregistrez la note vocale)");
  };

  return (
    <div className="rounded-lg ring-1 ring-amber-200 bg-amber-50/50 p-3 space-y-2" data-testid="intervention-voice-note">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <label className="text-xs font-semibold inline-flex items-center gap-1 text-amber-900">
          <Mic className="h-3.5 w-3.5" /> Note vocale (facultative)
        </label>
        {!recording && !uploading && (
          <button type="button" onClick={start} className="inline-flex items-center gap-1.5 rounded-lg bg-amber-600 text-white text-xs px-3 py-1.5 hover:bg-amber-700" data-testid="intervention-voice-start">
            <Mic className="h-3 w-3" /> Démarrer
          </button>
        )}
        {recording && (
          <button type="button" onClick={stop} className="inline-flex items-center gap-1.5 rounded-lg bg-rose-600 text-white text-xs px-3 py-1.5 hover:bg-rose-700 animate-pulse" data-testid="intervention-voice-stop">
            <Square className="h-3 w-3" /> Arrêter
          </button>
        )}
        {uploading && (
          <span className="inline-flex items-center gap-1.5 text-xs text-amber-700"><RefreshCw className="h-3 w-3 animate-spin" /> Upload en cours…</span>
        )}
      </div>
      {value && (
        <div className="flex items-center gap-2">
          <audio controls src={value} className="flex-1 h-8" data-testid="intervention-voice-preview" />
          <button type="button" onClick={() => { onChange(""); onTranscriptChange?.(""); lastBlobRef.current = null; }} className="text-xs text-rose-600 hover:underline inline-flex items-center gap-1" data-testid="intervention-voice-remove">
            <MicOff className="h-3 w-3" /> Supprimer
          </button>
        </div>
      )}
      {/* Iter34z — Transcription preview + editable area */}
      {(value || transcribing || (transcript || "")) && (
        <div className="rounded-md bg-white ring-1 ring-amber-100 p-2 space-y-1">
          <div className="flex items-center justify-between gap-2">
            <label className="text-[10px] uppercase tracking-wider text-amber-800 font-semibold flex items-center gap-1">
              <FileText className="h-2.5 w-2.5" /> Transcription
              {transcribing && <RefreshCw className="h-2.5 w-2.5 animate-spin" />}
            </label>
            {lastBlobRef.current && !transcribing && (
              <button type="button" onClick={retranscribe} className="text-[10px] text-amber-700 hover:underline" data-testid="intervention-voice-retranscribe">Re-transcrire</button>
            )}
          </div>
          <textarea
            value={transcript || ""}
            onChange={(e) => onTranscriptChange?.(e.target.value)}
            rows={2}
            placeholder={transcribing ? "Transcription en cours…" : "La transcription apparaîtra ici. Vous pouvez l'éditer librement."}
            disabled={transcribing}
            className="w-full text-xs rounded border border-amber-100 px-2 py-1 resize-y bg-amber-50/30"
            data-testid="intervention-voice-transcript"
          />
        </div>
      )}
    </div>
  );
}


// ============================================================
// Iter43-fix4 — Modale d'édition Admin/Superviseur d'une intervention
// Permet de corriger : client (tenant), titre, statut, date, technicien,
// durée. Les interventions facturées sont rejetées par le backend (409)
// et le bouton « Modifier » est masqué côté UI dans ce cas.
// ============================================================
const EditInterventionModal = ({ intervention, clients, onClose, onSaved }) => {
  const [form, setForm] = useState({
    client_id: intervention.client_id || "",
    title: intervention.title || "",
    description: intervention.description || "",
    status: intervention.status || "completed",
    intervention_date: (intervention.intervention_date || "").slice(0, 10),
    technician: intervention.technician || "",
    duration_hours: intervention.duration_hours ?? "",
  });
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!form.client_id) { toast.error("Client lié requis"); return; }
    if (!form.title.trim()) { toast.error("Titre requis"); return; }
    setSaving(true);
    try {
      const payload = {
        client_id: form.client_id,
        title: form.title.trim(),
        description: form.description || null,
        status: form.status,
        intervention_date: form.intervention_date ? new Date(form.intervention_date).toISOString() : null,
        technician: form.technician || null,
        duration_hours: form.duration_hours === "" || form.duration_hours === null
          ? null
          : Number(form.duration_hours),
      };
      await apiClient.put(`/admin/interventions/${intervention.id}`, payload);
      toast.success("Intervention mise à jour");
      onSaved();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur lors de la mise à jour");
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
         onClick={(e) => e.target === e.currentTarget && onClose()}
         data-testid="intervention-edit-modal">
      <div className="w-full max-w-lg rounded-2xl bg-white shadow-2xl p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
            <Pencil className="h-5 w-5 text-sawali-blue" /> Modifier intervention
            {intervention.intervention_number && (
              <span className="text-xs font-mono text-slate-500">· {intervention.intervention_number}</span>
            )}
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900" data-testid="intervention-edit-close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div>
          <label className="block text-xs font-semibold mb-1 inline-flex items-center gap-1">
            <Building2 className="h-3 w-3 text-sawali-blue" /> Client lié *
          </label>
          <select value={form.client_id}
                  onChange={(e) => setForm({ ...form, client_id: e.target.value })}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  data-testid="intervention-edit-field-client">
            <option value="">— Sélectionnez un client —</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>{c.company || c.full_name}{c.client_code ? ` · ${c.client_code}` : ""}</option>
            ))}
          </select>
          <p className="text-[10px] text-slate-500 mt-1">Le tenant détermine le taux horaire appliqué lors de la facturation.</p>
        </div>

        <div>
          <label className="block text-xs font-semibold mb-1">Titre *</label>
          <input value={form.title}
                 onChange={(e) => setForm({ ...form, title: e.target.value })}
                 className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                 data-testid="intervention-edit-field-title" />
        </div>

        <div>
          <label className="block text-xs font-semibold mb-1">Description</label>
          <textarea value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                    rows={3}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    data-testid="intervention-edit-field-description" />
        </div>

        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold mb-1">Date</label>
            <input type="date" value={form.intervention_date}
                   onChange={(e) => setForm({ ...form, intervention_date: e.target.value })}
                   className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                   data-testid="intervention-edit-field-date" />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">Statut</label>
            <select value={form.status}
                    onChange={(e) => setForm({ ...form, status: e.target.value })}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    data-testid="intervention-edit-field-status">
              {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">Technicien</label>
            <input value={form.technician}
                   onChange={(e) => setForm({ ...form, technician: e.target.value })}
                   className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                   data-testid="intervention-edit-field-technician" />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">Durée (heures)</label>
            <input type="number" step="0.25" min="0"
                   value={form.duration_hours}
                   onChange={(e) => setForm({ ...form, duration_hours: e.target.value })}
                   placeholder="2.5"
                   className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                   data-testid="intervention-edit-field-duration" />
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="text-sm rounded-lg bg-slate-100 hover:bg-slate-200 px-4 py-2">
            Annuler
          </button>
          <button onClick={submit} disabled={saving}
                  className="text-sm rounded-lg bg-sawali-blue hover:bg-sawali-blue-light text-white px-4 py-2 disabled:opacity-50"
                  data-testid="intervention-edit-save">
            {saving ? "Enregistrement…" : "Enregistrer"}
          </button>
        </div>
      </div>
    </div>
  );
};

// ============================================================
// Iter43-fix6 — Panneau "Factures émises" + édition dépôt/paiement
// ============================================================
const fmtXof = (n) => (Number(n) || 0).toLocaleString("fr-FR").replaceAll(",", " ");
const fmtIsoDateTime = (iso) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }); }
  catch { return iso; }
};

const InvoicesPanel = ({ open, onToggle, invoices, loading, onRefresh, onEdit, onDownload }) => {
  const overdueCount = invoices.filter((i) => (i.days_overdue ?? 0) > 0).length;
  const paidCount = invoices.filter((i) => i.payment_status === "paid").length;
  const unpaidCount = invoices.filter((i) => i.payment_status === "unpaid").length;
  return (
    <div className="rounded-xl border border-slate-200 bg-white" data-testid="invoices-panel">
      <button type="button"
              onClick={onToggle}
              className="w-full flex items-center justify-between gap-3 px-4 py-3 hover:bg-slate-50"
              data-testid="invoices-panel-toggle">
        <div className="flex items-center gap-2">
          <ReceiptText className="h-4 w-4 text-sawali-blue" />
          <span className="font-semibold text-slate-800">Factures émises</span>
          <span className="text-xs text-slate-500">({invoices.length})</span>
          {overdueCount > 0 && (
            <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-rose-100 text-rose-700 ring-1 ring-rose-300 font-semibold"
                  data-testid="invoices-overdue-badge">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-rose-500" />
              {overdueCount} en retard
            </span>
          )}
          {paidCount > 0 && (
            <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200">
              {paidCount} payée(s)
            </span>
          )}
          {unpaidCount > 0 && (
            <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-50 text-amber-800 ring-1 ring-amber-200">
              {unpaidCount} en attente
            </span>
          )}
        </div>
        {open ? <ChevronUp className="h-4 w-4 text-slate-500" /> : <ChevronDown className="h-4 w-4 text-slate-500" />}
      </button>
      {open && (
        <div className="border-t border-slate-100 p-3">
          <div className="flex justify-end mb-2">
            <button onClick={onRefresh} disabled={loading}
                    className="inline-flex items-center gap-2 text-xs rounded-lg border border-slate-300 bg-white hover:bg-slate-50 px-3 py-1.5 disabled:opacity-60"
                    data-testid="invoices-refresh">
              <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} /> Actualiser
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[820px]">
              <thead className="bg-slate-50 text-xs uppercase text-slate-600">
                <tr>
                  <th className="text-left px-3 py-2">N° Facture</th>
                  <th className="text-left px-3 py-2">Tenant</th>
                  <th className="text-right px-3 py-2">Total (XOF)</th>
                  <th className="text-left px-3 py-2">Dépôt</th>
                  <th className="text-left px-3 py-2">Échéance</th>
                  <th className="text-left px-3 py-2">Paiement</th>
                  <th className="text-left px-3 py-2">Retard</th>
                  <th className="text-right px-3 py-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan={8} className="text-center py-6 text-slate-400">Chargement…</td></tr>
                )}
                {!loading && invoices.length === 0 && (
                  <tr><td colSpan={8} className="text-center py-6 text-slate-400 italic">Aucune facture émise.</td></tr>
                )}
                {!loading && invoices.map((inv) => {
                  const od = inv.days_overdue;
                  const paid = inv.payment_status === "paid";
                  const isOverdue = (od ?? 0) > 0 && !paid;
                  return (
                    <tr key={inv.id}
                        className={`border-t border-slate-100 ${isOverdue ? "bg-rose-50/40" : ""} ${paid ? "text-slate-500" : ""}`}
                        data-testid={`invoice-row-${inv.id}`}>
                      <td className="px-3 py-2 font-mono text-xs">
                        <button type="button" onClick={() => onDownload(inv)}
                                className="inline-flex items-center gap-1 text-emerald-700 hover:underline"
                                data-testid={`invoice-download-${inv.id}`}
                                title="Télécharger PDF">
                          {inv.invoice_number}
                          <Download className="h-3 w-3" />
                        </button>
                      </td>
                      <td className="px-3 py-2 text-xs">{inv.tenant_name || "—"}</td>
                      <td className="px-3 py-2 text-right font-mono text-xs">{fmtXof(inv.total_xof)}</td>
                      <td className="px-3 py-2 text-xs whitespace-nowrap">
                        {inv.deposited_at ? (
                          <span className="inline-flex items-center gap-1 text-slate-700">
                            <CalendarClock className="h-3 w-3" /> {fmtIsoDateTime(inv.deposited_at)}
                          </span>
                        ) : <span className="italic text-amber-600" title="Renseigner pour activer le suivi du délai de paiement">non renseigné</span>}
                      </td>
                      <td className="px-3 py-2 text-xs">{inv.due_days ?? 30} j</td>
                      <td className="px-3 py-2 text-xs whitespace-nowrap">
                        {paid ? (
                          <span className="inline-flex items-center gap-1 text-emerald-700 font-medium">
                            <CheckCircle2 className="h-3 w-3" /> {fmtIsoDateTime(inv.paid_at)}
                          </span>
                        ) : <span className="italic text-slate-400">non payée</span>}
                      </td>
                      <td className="px-3 py-2 text-xs">
                        {paid ? (
                          <span className="text-emerald-600">—</span>
                        ) : od === null || od === undefined ? (
                          <span className="text-slate-400">—</span>
                        ) : od > 0 ? (
                          <span className="inline-flex items-center gap-1 text-rose-700 font-semibold" data-testid={`invoice-overdue-${inv.id}`}>
                            <span className="inline-block h-1.5 w-1.5 rounded-full bg-rose-500 animate-pulse" />
                            {od} j de retard
                          </span>
                        ) : (
                          <span className="text-slate-500">En cours</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button onClick={() => onEdit(inv)}
                                className="inline-flex items-center gap-1 text-xs text-sawali-blue hover:underline"
                                data-testid={`invoice-edit-${inv.id}`}>
                          <Pencil className="h-3 w-3" /> Saisir / Modifier
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

// ISO datetime helpers — converts between <input type="datetime-local"> and ISO UTC.
const isoToLocalInput = (iso) => {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    const off = d.getTimezoneOffset() * 60_000;
    return new Date(d.getTime() - off).toISOString().slice(0, 16);
  } catch { return ""; }
};
const localInputToIso = (local) => {
  if (!local) return null;
  try {
    const d = new Date(local);
    if (isNaN(d.getTime())) return null;
    return d.toISOString();
  } catch { return null; }
};

const EditInvoicePaymentModal = ({ invoice, onClose, onSaved }) => {
  const [deposited, setDeposited] = useState(isoToLocalInput(invoice.deposited_at));
  const [paid, setPaid] = useState(isoToLocalInput(invoice.paid_at));
  const [dueDays, setDueDays] = useState(invoice.due_days ?? 30);
  const [saving, setSaving] = useState(false);

  const setDepositedNow = () => setDeposited(isoToLocalInput(new Date().toISOString()));
  const setPaidNow = () => setPaid(isoToLocalInput(new Date().toISOString()));

  const submit = async () => {
    setSaving(true);
    try {
      const payload = {
        due_days: Number(dueDays) || 30,
      };
      if (deposited) payload.deposited_at = localInputToIso(deposited);
      else payload.clear_deposited_at = true;
      if (paid) payload.paid_at = localInputToIso(paid);
      else payload.clear_paid_at = true;
      await apiClient.put(`/admin/invoices/from-interventions/${invoice.id}`, payload);
      toast.success("Facture mise à jour");
      onSaved();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
         onClick={(e) => e.target === e.currentTarget && onClose()}
         data-testid="invoice-edit-modal">
      <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
            <Banknote className="h-5 w-5 text-sawali-blue" />
            <span>Facture {invoice.invoice_number}</span>
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900" data-testid="invoice-edit-close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="rounded-lg bg-slate-50 p-3 text-xs space-y-1">
          <p><span className="text-slate-500">Tenant :</span> <strong>{invoice.tenant_name || "—"}</strong></p>
          <p><span className="text-slate-500">Total :</span> <strong>{fmtXof(invoice.total_xof)} XOF</strong></p>
        </div>

        <div>
          <label className="block text-xs font-semibold mb-1 inline-flex items-center gap-1">
            <CalendarClock className="h-3 w-3 text-amber-600" /> Date / heure de dépôt
          </label>
          <div className="flex items-center gap-2">
            <input type="datetime-local"
                   value={deposited}
                   onChange={(e) => setDeposited(e.target.value)}
                   className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
                   data-testid="invoice-edit-deposited-at" />
            <button type="button" onClick={setDepositedNow}
                    className="text-xs px-2 py-2 rounded ring-1 ring-slate-300 bg-white hover:bg-slate-100"
                    data-testid="invoice-edit-deposited-now"
                    title="Renseigner la date actuelle">
              Maintenant
            </button>
          </div>
          <p className="text-[10px] text-slate-500 mt-1">Le retard de paiement se calcule à partir de cette date + l'échéance.</p>
        </div>

        <div>
          <label className="block text-xs font-semibold mb-1">Échéance (jours après dépôt)</label>
          <input type="number" min="0" max="365"
                 value={dueDays}
                 onChange={(e) => setDueDays(e.target.value)}
                 className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                 data-testid="invoice-edit-due-days" />
        </div>

        <div>
          <label className="block text-xs font-semibold mb-1 inline-flex items-center gap-1">
            <CheckCircle2 className="h-3 w-3 text-emerald-600" /> Date / heure de paiement
          </label>
          <div className="flex items-center gap-2">
            <input type="datetime-local"
                   value={paid}
                   onChange={(e) => setPaid(e.target.value)}
                   className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
                   data-testid="invoice-edit-paid-at" />
            <button type="button" onClick={setPaidNow}
                    className="text-xs px-2 py-2 rounded ring-1 ring-emerald-300 bg-emerald-50 hover:bg-emerald-100 text-emerald-700"
                    data-testid="invoice-edit-paid-now"
                    title="Marquer comme payée maintenant">
              Marquer payée
            </button>
          </div>
          <p className="text-[10px] text-slate-500 mt-1">Laisser vide tant que la facture n'a pas été réglée.</p>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="text-sm rounded-lg bg-slate-100 hover:bg-slate-200 px-4 py-2">Annuler</button>
          <button onClick={submit} disabled={saving}
                  className="text-sm rounded-lg bg-sawali-blue hover:bg-sawali-blue-light text-white px-4 py-2 disabled:opacity-50"
                  data-testid="invoice-edit-save">
            {saving ? "Enregistrement…" : "Enregistrer"}
          </button>
        </div>
      </div>
    </div>
  );
};

