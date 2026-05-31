/*
 * Iter36u — Cash & Billing unified page.
 *
 * Tabs:
 *   - Caisse        → list + create receipts
 *   - Facturation   → list + create invoices/proformas, lifecycle actions
 *   - Catalogue     → CRUD products
 *   - Clients en compte → CRUD business_clients
 *   - Modes de paiement → CRUD payment_methods (admin-only)
 *
 * Permission gate: user must have role admin/superviseur OR can_cash=true.
 */
import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import {
  Banknote, Receipt, ShoppingBag, Building2, CreditCard, Plus, Search, X,
  Printer, MessageCircle, Edit2, Trash2, FileText, CheckCircle2, XCircle,
  Loader2, ArrowRight, AlertTriangle, Download, FileSpreadsheet, Bell,
  TrendingUp, TrendingDown, Clock, AlertOctagon, Tag, RefreshCw, Users, Building, Copy, RotateCcw,
  Upload, Image as ImageIcon, Sparkles, Send, Eye,
} from "lucide-react";
import { Link } from "react-router-dom";
import ExpensesTab from "./ExpensesTab";

const FCFA = (n) => Number(n || 0).toLocaleString("fr-FR", { maximumFractionDigits: 0 });
const BACKEND = process.env.REACT_APP_BACKEND_URL || "";
const fmtDt = (iso) => {
  if (!iso) return null;
  try { return new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); }
  catch { return String(iso).slice(0, 16); }
};

// Iter36w — Trigger a file download from a protected API endpoint (axios w/ auth).
async function downloadExport(apiPath, fallbackName) {
  try {
    const resp = await apiClient.get(apiPath, { responseType: "blob" });
    const blob = new Blob([resp.data], { type: resp.headers["content-type"] || "application/octet-stream" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    // Extract filename from Content-Disposition if present
    const cd = resp.headers["content-disposition"] || "";
    const m = cd.match(/filename="?([^";]+)"?/i);
    a.download = (m && m[1]) || fallbackName;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    return true;
  } catch (err) {
    toast.error(err?.response?.data?.detail || "Erreur de téléchargement");
    return false;
  }
}

function Empty({ label }) {
  return (
    <div className="text-center py-12 text-slate-400 text-sm italic">{label}</div>
  );
}

// =====================================================================
// Iter38m — WhatsApp Preview & Resend modal (P1.3)
// Shows the current WA delivery status, template used, recipient and last
// error, plus a "Renvoyer" button that re-fires the send endpoint.
// =====================================================================
function WaPreviewModal({ doc, kind, onClose, onSent }) {
  const [resending, setResending] = useState(false);
  if (!doc) return null;
  const endpoint = kind === "receipt" ? `/cashier/receipts/${doc.id}/send-whatsapp` : `/cashier/invoices/${doc.id}/send-whatsapp`;
  const number = doc.number || doc.id;
  const lastStatus = doc.whatsapp_last_status || (doc.whatsapp_sent_at ? "ok" : null);
  const lastSentAt = doc.whatsapp_sent_at || doc.whatsapp_last_attempt_at;
  const lastTo = doc.whatsapp_to || doc.whatsapp_last_to;
  const lastError = doc.whatsapp_last_error;
  const tplName = doc.whatsapp_template_name;
  const pdfUrl = doc.whatsapp_pdf_url;
  const moduleUsed = tplName ? `Meta WhatsApp Cloud API (template "${tplName}")` : (lastSentAt ? "Meta WhatsApp Cloud API (texte libre)" : "Aucun envoi enregistré");

  const resend = async () => {
    setResending(true);
    try {
      const r = await apiClient.post(endpoint, {});
      if (r.data && r.data.ok) {
        toast.success(`✓ Renvoyé à ${r.data.to}`);
      } else {
        toast.error(`KO — ${r.data?.error || "Échec WhatsApp"}`);
      }
      onSent && onSent();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur d'envoi");
    } finally { setResending(false); }
  };

  return (
    <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" data-testid="wa-preview-modal">
      <div className="bg-white rounded-2xl max-w-xl w-full shadow-2xl">
        <div className="flex items-center justify-between p-5 border-b border-slate-100">
          <h3 className="text-lg font-semibold text-slate-900 flex items-center gap-2">
            <MessageCircle className="text-emerald-600" size={20} />
            Aperçu envoi WhatsApp — {kind === "receipt" ? "Reçu" : "Facture"} {number}
          </h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600" data-testid="wa-preview-close"><X size={20} /></button>
        </div>
        <div className="p-5 space-y-3 text-sm">
          {/* Status banner */}
          {lastStatus === "ok" ? (
            <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-lg p-3 flex items-start gap-2" data-testid="wa-preview-status-ok">
              <CheckCircle2 size={16} className="flex-shrink-0 mt-0.5" />
              <div>
                <div className="font-semibold">Dernier envoi : OK</div>
                <div className="text-xs">Envoyé le {fmtDt(lastSentAt)}</div>
              </div>
            </div>
          ) : lastStatus === "ko" ? (
            <div className="bg-rose-50 border border-rose-200 text-rose-800 rounded-lg p-3 flex items-start gap-2" data-testid="wa-preview-status-ko">
              <AlertTriangle size={16} className="flex-shrink-0 mt-0.5" />
              <div>
                <div className="font-semibold">Dernier envoi : ÉCHEC</div>
                {lastError && <div className="text-xs mt-1">{lastError}</div>}
                <div className="text-xs">Tenté le {fmtDt(lastSentAt)}</div>
              </div>
            </div>
          ) : (
            <div className="bg-slate-50 border border-slate-200 text-slate-700 rounded-lg p-3 flex items-start gap-2" data-testid="wa-preview-status-none">
              <Clock size={16} className="flex-shrink-0 mt-0.5" />
              <span>Aucun envoi WhatsApp enregistré pour ce document.</span>
            </div>
          )}

          {/* Details */}
          <div className="bg-slate-50 rounded-lg p-3 space-y-1">
            <div className="flex justify-between gap-3">
              <span className="text-slate-500">Module utilisé</span>
              <span className="font-medium text-right">{moduleUsed}</span>
            </div>
            <div className="flex justify-between gap-3">
              <span className="text-slate-500">Destinataire</span>
              <span className="font-mono text-right">{lastTo || "—"}</span>
            </div>
            {tplName && (
              <div className="flex justify-between gap-3">
                <span className="text-slate-500">Nom du template</span>
                <span className="font-mono text-xs text-right">{tplName}</span>
              </div>
            )}
            {pdfUrl && (
              <div className="flex justify-between gap-3">
                <span className="text-slate-500">PDF joint</span>
                <a href={pdfUrl} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline text-xs truncate max-w-xs">{pdfUrl}</a>
              </div>
            )}
          </div>

          {/* Preview body */}
          <div>
            <p className="text-xs font-semibold text-slate-600 mb-1">Aperçu du contenu :</p>
            <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-3 text-xs whitespace-pre-line font-mono text-slate-700" data-testid="wa-preview-body">
              {kind === "receipt"
                ? `📄 Reçu *${number}*\nBénéficiaire : ${(doc.business_client_snapshot?.name) || doc.beneficiary_name || "—"}\nMontant : ${FCFA(doc.amount)} FCFA\nMotif : ${doc.motif || "—"}${pdfUrl ? `\nPDF : ${pdfUrl}` : ""}`
                : `📄 ${doc.kind === "proforma" ? "Proforma" : "Facture"} *${number}*\nClient : ${(doc.business_client_snapshot?.name) || "—"}\nMontant : ${FCFA(doc.net_to_pay ?? doc.total_ttc)} FCFA${pdfUrl ? `\nPDF : ${pdfUrl}` : ""}`}
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-2 p-5 border-t border-slate-100">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-600" data-testid="wa-preview-cancel">Fermer</button>
          <button onClick={resend} disabled={resending} data-testid="wa-preview-resend-btn"
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm rounded-lg flex items-center gap-2 disabled:opacity-60">
            {resending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
            {lastStatus === "ok" ? "Renvoyer le message" : "Envoyer maintenant"}
          </button>
        </div>
      </div>
    </div>
  );
}

// =====================================================================
// Receipts tab
// =====================================================================
function ReceiptsTab({ businessClients, paymentMethods, refreshClients }) {
  const { user } = useAuth();
  const canDelete = user && (user.role === "admin" || user.role === "superviseur");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    business_client_id: "", beneficiary_name: "", amount: "",
    motif: "", payment_method_id: "", payment_reference: "",
  });
  const [submitting, setSubmitting] = useState(false);
  // Iter37h.A — Recycle bin toggle
  const [showTrash, setShowTrash] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/cashier/receipts", { params: { limit: 100, include_deleted: showTrash } });
      setItems(r.data || []);
    } catch { setItems([]); } finally { setLoading(false); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [showTrash]);

  // Iter37h.A — Soft delete (trash), Restore, Purge — admin/superviseur only.
  const trashReceipt = async (rid, number) => {
    if (!window.confirm(`Mettre le reçu ${number || rid} à la corbeille ?`)) return;
    try { await apiClient.delete(`/cashier/receipts/${rid}`); toast.success(`Reçu ${number || rid} mis à la corbeille`); load(); }
    catch (err) { toast.error(err?.response?.data?.detail || "Échec"); }
  };
  const restoreReceipt = async (rid, number) => {
    try { await apiClient.post(`/cashier/receipts/${rid}/restore`); toast.success(`Reçu ${number || rid} restauré`); load(); }
    catch (err) { toast.error(err?.response?.data?.detail || "Échec"); }
  };
  const purgeReceipt = async (rid, number) => {
    if (!window.confirm(`⚠️ SUPPRESSION DÉFINITIVE du reçu ${number || rid} ?\nIrréversible.`)) return;
    try { await apiClient.delete(`/cashier/receipts/${rid}`, { params: { purge: true } }); toast.success("Supprimé définitivement"); load(); }
    catch (err) { toast.error(err?.response?.data?.detail || "Échec"); }
  };

  // Iter38m — WA preview/resend modal
  const [waPreview, setWaPreview] = useState(null);

  const submit = async () => {
    if (!form.business_client_id) { toast.error("Sélectionnez un client en compte"); return; }
    if (!form.amount || Number(form.amount) <= 0) { toast.error("Montant invalide"); return; }
    if (!form.motif.trim()) { toast.error("Motif requis"); return; }
    if (!form.payment_method_id) { toast.error("Mode de paiement requis"); return; }
    setSubmitting(true);
    try {
      const r = await apiClient.post("/cashier/receipts", {
        ...form, amount: Number(form.amount),
      });
      toast.success(`Reçu ${r.data.number} créé`);
      setShowForm(false);
      setForm({ business_client_id: "", beneficiary_name: "", amount: "", motif: "", payment_method_id: "", payment_reference: "" });
      await load();
      window.open(`/portal/cash/receipt/${r.data.id}`, "_blank");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSubmitting(false); }
  };

  return (
    <div className="space-y-4" data-testid="cashier-receipts-tab">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
          <Banknote className="h-5 w-5 text-emerald-600" /> Reçus d'encaissement
        </h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => downloadExport("/cashier/exports/receipts.csv", "recus.csv")}
            className="inline-flex items-center gap-1.5 rounded-lg bg-white ring-1 ring-slate-300 hover:bg-slate-50 text-slate-700 px-3 py-1.5 text-sm font-medium"
            data-testid="cashier-receipts-export-csv"
            title="Exporter en CSV (Excel)"
          >
            <FileSpreadsheet className="h-4 w-4 text-emerald-600" /> CSV
          </button>
          <button
            onClick={() => downloadExport("/cashier/exports/receipts.pdf", "recus.pdf")}
            className="inline-flex items-center gap-1.5 rounded-lg bg-white ring-1 ring-slate-300 hover:bg-slate-50 text-slate-700 px-3 py-1.5 text-sm font-medium"
            data-testid="cashier-receipts-export-pdf"
            title="Exporter en PDF"
          >
            <Download className="h-4 w-4 text-rose-600" /> PDF
          </button>
          {/* Iter37h.A — Recycle bin toggle */}
          {canDelete && (
            <button
              onClick={() => setShowTrash((v) => !v)}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium ${showTrash ? "bg-rose-600 text-white hover:bg-rose-700" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}
              data-testid="receipts-trash-toggle"
              title="Afficher/masquer la corbeille"
            >
              <Trash2 className="h-4 w-4" /> {showTrash ? "Sortir de la corbeille" : "Corbeille"}
            </button>
          )}
          <button
            onClick={() => setShowForm((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1.5 text-sm font-medium"
            data-testid="cashier-new-receipt-btn"
          >
            <Plus className="h-4 w-4" /> Nouveau reçu
          </button>
        </div>
      </div>

      {showForm && (
        <div className="rounded-2xl bg-white shadow ring-1 ring-slate-200 p-4 space-y-3" data-testid="cashier-receipt-form">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-xs font-medium text-slate-700">Client en compte *</label>
                <button type="button" onClick={refreshClients} className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-100" data-testid="receipt-refresh-clients" title="Actualiser la liste">
                  <RefreshCw className="h-3 w-3" /> Actualiser
                </button>
              </div>
              <select value={form.business_client_id} onChange={(e) => setForm({ ...form, business_client_id: e.target.value })}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="receipt-form-business-client">
                <option value="">— Choisir —</option>
                {businessClients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">Bénéficiaire (optionnel)</label>
              <input value={form.beneficiary_name} onChange={(e) => setForm({ ...form, beneficiary_name: e.target.value })}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                placeholder="(par défaut: nom du client)" />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">Montant (FCFA) *</label>
              <input type="number" min="0" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
                data-testid="receipt-form-amount" />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">Mode de paiement *</label>
              <select value={form.payment_method_id} onChange={(e) => setForm({ ...form, payment_method_id: e.target.value })}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="receipt-form-pm">
                <option value="">— Choisir —</option>
                {paymentMethods.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
              </select>
            </div>
            <div className="sm:col-span-2">
              <label className="block text-xs font-medium text-slate-700 mb-1">Motif *</label>
              <input value={form.motif} onChange={(e) => setForm({ ...form, motif: e.target.value })}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                placeholder="Ex: Acompte sur prestation X" data-testid="receipt-form-motif" />
            </div>
            <div className="sm:col-span-2">
              <label className="block text-xs font-medium text-slate-700 mb-1">Référence du paiement</label>
              <input value={form.payment_reference} onChange={(e) => setForm({ ...form, payment_reference: e.target.value })}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                placeholder="N° de chèque, ID transaction, etc." />
            </div>
          </div>
          <div className="flex items-center justify-end gap-2 pt-2">
            <button onClick={() => setShowForm(false)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">Annuler</button>
            <button onClick={submit} disabled={submitting}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1.5 text-sm font-medium disabled:opacity-50"
              data-testid="receipt-form-submit">
              {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Encaisser & imprimer
            </button>
          </div>
        </div>
      )}

      <div className="rounded-2xl bg-white shadow ring-1 ring-slate-200 overflow-hidden">
        {loading ? <Empty label="Chargement…" /> : items.length === 0 ? <Empty label="Aucun reçu pour le moment" /> : (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs text-slate-600">
              <tr>
                <th className="text-left px-3 py-2">N°</th>
                <th className="text-left px-3 py-2">Date</th>
                <th className="text-left px-3 py-2">Client en compte</th>
                <th className="text-right px-3 py-2">Montant</th>
                <th className="text-left px-3 py-2">Paiement</th>
                <th className="text-left px-3 py-2">Caissier</th>
                <th className="text-left px-3 py-2">WhatsApp</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((r) => (
                <tr key={r.id} className="hover:bg-slate-50">
                  <td className="px-3 py-2 font-mono font-semibold text-slate-800">{r.number}</td>
                  <td className="px-3 py-2 text-slate-600 text-xs">{new Date(r.issued_at).toLocaleString("fr-FR")}</td>
                  <td className="px-3 py-2 text-slate-700">{(r.business_client_snapshot || {}).name}</td>
                  <td className="px-3 py-2 text-right font-mono font-bold text-emerald-700">{FCFA(r.amount)} FCFA</td>
                  <td className="px-3 py-2 text-slate-600 text-xs">{r.payment_method_label}</td>
                  <td className="px-3 py-2 text-slate-500 text-xs">{r.cashier_name}</td>
                  <td className="px-3 py-2 text-xs" data-testid={`receipt-wa-status-${r.id}`}>
                    {r.whatsapp_sent_at ? (
                      <button
                        onClick={() => setWaPreview(r)}
                        className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 px-1.5 py-0.5 hover:bg-emerald-100"
                        title={`Cliquer pour voir l'aperçu / renvoyer · Envoyé à ${r.whatsapp_to || ""}`}
                        data-testid={`receipt-wa-preview-${r.id}`}
                      >
                        <CheckCircle2 className="h-3 w-3" /> {fmtDt(r.whatsapp_sent_at)}
                      </button>
                    ) : r.whatsapp_last_status === "ko" ? (
                      <button
                        onClick={() => setWaPreview(r)}
                        className="inline-flex items-center gap-1 rounded-full bg-rose-50 text-rose-700 ring-1 ring-rose-200 px-1.5 py-0.5 hover:bg-rose-100"
                        title={r.whatsapp_last_error || "Envoi WhatsApp échoué — cliquer pour réessayer"}
                        data-testid={`receipt-wa-preview-${r.id}`}
                      >
                        <AlertTriangle className="h-3 w-3" /> KO
                      </button>
                    ) : (
                      <button
                        onClick={() => setWaPreview(r)}
                        className="inline-flex items-center gap-1 text-slate-500 hover:text-emerald-600 underline-offset-2 hover:underline text-xs"
                        title="Aperçu et envoi WhatsApp"
                        data-testid={`receipt-wa-preview-${r.id}`}
                      >
                        <Eye className="h-3 w-3" /> Aperçu
                      </button>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {/* Iter37h.A — Trashed receipts: only Imprimer (no WA/edit) */}
                    {r.deleted_at ? (
                      <div className="inline-flex items-center gap-2">
                        <span className="text-[10px] uppercase font-bold text-rose-600 bg-rose-50 px-1.5 py-0.5 rounded ring-1 ring-rose-200">Corbeille</span>
                        <Link to={`/portal/cash/receipt/${r.id}`} target="_blank" className="inline-flex items-center gap-1 text-sawali-blue hover:underline text-xs">
                          <Printer className="h-3.5 w-3.5" />
                        </Link>
                        {canDelete && (
                          <>
                            <button onClick={() => restoreReceipt(r.id, r.number)} className="text-xs text-emerald-600 hover:underline" title="Restaurer" data-testid={`receipt-restore-${r.id}`}>
                              <RotateCcw className="h-3.5 w-3.5 inline" />
                            </button>
                            <button onClick={() => purgeReceipt(r.id, r.number)} className="text-xs text-rose-700 hover:underline" title="Supprimer définitivement" data-testid={`receipt-purge-${r.id}`}>
                              <Trash2 className="h-3.5 w-3.5 inline" />
                            </button>
                          </>
                        )}
                      </div>
                    ) : (
                      <>
                        <Link to={`/portal/cash/receipt/${r.id}`} target="_blank" className="inline-flex items-center gap-1 text-sawali-blue hover:underline text-xs"
                          data-testid={`receipt-print-${r.id}`}>
                          <Printer className="h-3.5 w-3.5" /> Imprimer
                        </Link>
                        {canDelete && (
                          <button
                            onClick={() => trashReceipt(r.id, r.number)}
                            className="ml-3 inline-flex items-center gap-1 text-rose-600 hover:underline text-xs"
                            title="Mettre à la corbeille (admin/superviseur)"
                            data-testid={`receipt-delete-${r.id}`}
                          >
                            <Trash2 className="h-3.5 w-3.5" /> Corbeille
                          </button>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {waPreview && (
        <WaPreviewModal
          doc={waPreview}
          kind="receipt"
          onClose={() => setWaPreview(null)}
          onSent={() => { setWaPreview(null); load(); }}
        />
      )}
    </div>
  );
}

// =====================================================================
// Invoices tab
// =====================================================================
// =====================================================================
// Iter36z — Mini KPI panel for Facturation header (cashflow cockpit)
// =====================================================================
function InvoiceKpiPanel() {
  const [kpis, setKpis] = useState(null);
  const [loading, setLoading] = useState(true);
  const load = async () => {
    try {
      const r = await apiClient.get("/cashier/kpis");
      setKpis(r.data);
    } catch { /* noop */ } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  if (loading) {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="rounded-2xl bg-white ring-1 ring-slate-200 p-4 animate-pulse h-24" />
        ))}
      </div>
    );
  }
  if (!kpis) return null;

  const paid = kpis.encaisse_this_month || {};
  const due = kpis.restant_a_encaisser || {};
  const delay = kpis.delai_moyen_jours;
  const tops = kpis.top_bad_payers || [];
  const monthLabel = new Date().toLocaleDateString("fr-FR", { month: "long", year: "numeric" });

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-4" data-testid="invoice-kpi-panel">
      {/* Card 1 — Encaissé ce mois */}
      <div className="rounded-2xl bg-gradient-to-br from-emerald-500 to-emerald-600 text-white p-4 shadow-md ring-1 ring-emerald-700/20" data-testid="kpi-card-paid">
        <div className="flex items-center justify-between">
          <span className="text-xs uppercase tracking-wider opacity-90 font-medium">Encaissé · {monthLabel}</span>
          <TrendingUp className="h-4 w-4 opacity-80" />
        </div>
        <div className="mt-2 text-2xl font-display font-bold tabular-nums">{FCFA(paid.amount)} <span className="text-sm font-normal opacity-90">FCFA</span></div>
        <div className="text-xs opacity-90 mt-1">{paid.count || 0} facture(s) réglée(s)</div>
      </div>

      {/* Card 2 — Restant à encaisser */}
      <div className="rounded-2xl bg-gradient-to-br from-amber-500 to-orange-500 text-white p-4 shadow-md ring-1 ring-orange-700/20" data-testid="kpi-card-due">
        <div className="flex items-center justify-between">
          <span className="text-xs uppercase tracking-wider opacity-90 font-medium">Restant à encaisser</span>
          <AlertOctagon className="h-4 w-4 opacity-80" />
        </div>
        <div className="mt-2 text-2xl font-display font-bold tabular-nums">{FCFA(due.amount)} <span className="text-sm font-normal opacity-90">FCFA</span></div>
        <div className="text-xs opacity-90 mt-1">{due.count || 0} facture(s) en attente</div>
      </div>

      {/* Card 3 — Délai moyen */}
      <div className="rounded-2xl bg-gradient-to-br from-sky-500 to-blue-600 text-white p-4 shadow-md ring-1 ring-blue-700/20" data-testid="kpi-card-delay">
        <div className="flex items-center justify-between">
          <span className="text-xs uppercase tracking-wider opacity-90 font-medium">Délai moyen de paiement</span>
          <Clock className="h-4 w-4 opacity-80" />
        </div>
        <div className="mt-2 text-2xl font-display font-bold tabular-nums">
          {delay !== null && delay !== undefined ? <>{delay} <span className="text-sm font-normal opacity-90">jour{delay > 1 ? "s" : ""}</span></> : <span className="text-base opacity-80">—</span>}
        </div>
        <div className="text-xs opacity-90 mt-1">{kpis.delai_moyen_sample_size || 0} facture(s) · 90 derniers jours</div>
      </div>

      {/* Card 4 — Top mauvais payeurs */}
      <div className="rounded-2xl bg-gradient-to-br from-rose-500 to-pink-600 text-white p-4 shadow-md ring-1 ring-rose-700/20" data-testid="kpi-card-bad-payers">
        <div className="flex items-center justify-between">
          <span className="text-xs uppercase tracking-wider opacity-90 font-medium">Top 3 mauvais payeurs</span>
          <TrendingDown className="h-4 w-4 opacity-80" />
        </div>
        {tops.length === 0 ? (
          <div className="mt-2 text-sm opacity-90 italic">Aucun impayé 🎉</div>
        ) : (
          <ol className="mt-2 space-y-1">
            {tops.map((t, idx) => (
              <li key={t.business_client_id || idx} className="flex items-center justify-between gap-2 text-sm" data-testid={`kpi-bad-payer-${idx}`}>
                <span className="truncate font-medium">
                  <span className="opacity-70 mr-1">{idx + 1}.</span>{t.name}
                  {t.oldest_overdue_days != null && t.oldest_overdue_days > 0 && (
                    <span className="ml-1 text-xs opacity-80">({t.oldest_overdue_days}j)</span>
                  )}
                </span>
                <span className="font-mono text-xs whitespace-nowrap">{FCFA(t.unpaid_amount)}</span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}


function InvoicesTab({ businessClients, products, paymentMethods, refreshClients }) {
  const { user } = useAuth();
  const canDelete = user && (user.role === "admin" || user.role === "superviseur");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [showTrash, setShowTrash] = useState(false);
  const [filter, setFilter] = useState({ kind: "", status: "" });
  const [overdueCount, setOverdueCount] = useState(0);
  const [relancing, setRelancing] = useState(false);
  const [form, setForm] = useState({
    kind: "proforma",
    business_client_id: "",
    items: [{ label: "", quantity: 1, unit_price_ht: 0, tva_pct: 18, unit: "pièce" }],
    discount_kind: "none",
    discount_value: 0,
    notes: "",
  });
  const [submitting, setSubmitting] = useState(false);
  // Iter38m — WA preview/resend modal
  const [waPreview, setWaPreview] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/cashier/invoices", { params: { limit: 100, include_deleted: showTrash, ...filter } });
      setItems(r.data || []);
    } catch { setItems([]); } finally { setLoading(false); }
  };
  const refreshOverdue = async () => {
    try {
      const r = await apiClient.get("/cashier/overdue/count", { params: { grace_days: 30 } });
      setOverdueCount(r.data?.count || 0);
    } catch { /* noop */ }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [filter.kind, filter.status, showTrash]);
  useEffect(() => { refreshOverdue(); }, []);

  // Iter38d — Trash actions (restore + permanent delete + duplicate)
  const restoreInvoice = async (id, number) => {
    if (!canDelete) return;
    try {
      await apiClient.post(`/cashier/invoices/${id}/restore`);
      toast.success(`Facture ${number || id} restaurée`);
      load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };
  const purgeInvoice = async (id, number) => {
    if (!canDelete) return;
    if (!window.confirm(`Supprimer DÉFINITIVEMENT la facture ${number || id} ? Cette action est irréversible.`)) return;
    try {
      await apiClient.delete(`/cashier/invoices/${id}/permanent`);
      toast.success("Suppression définitive");
      load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const relanceOverdue = async () => {
    if (overdueCount === 0 || relancing) return;
    if (!window.confirm(`Envoyer un rappel WhatsApp à ${overdueCount} facture(s) impayée(s) (échéance > 30 j) ?`)) return;
    setRelancing(true);
    try {
      const r = await apiClient.post("/cashier/overdue/relance", { grace_days: 30 });
      const { sent_ok = 0, sent_ko = 0, skipped_no_phone = 0, total = 0 } = r.data || {};
      const detail = [];
      if (sent_ok) detail.push(`${sent_ok} envoyée(s) ✓`);
      if (sent_ko) detail.push(`${sent_ko} échec(s)`);
      if (skipped_no_phone) detail.push(`${skipped_no_phone} sans n°`);
      if (sent_ok > 0 && sent_ko === 0) {
        toast.success(`Relance terminée — ${total} facture(s) — ${detail.join(" · ")}`);
      } else if (sent_ok > 0) {
        toast.warning(`Relance partielle — ${detail.join(" · ")}`);
      } else {
        toast.error(`Relance échouée — ${detail.join(" · ") || "aucun envoi"}`);
      }
      await Promise.all([load(), refreshOverdue()]);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur lors de la relance");
    } finally { setRelancing(false); }
  };

  const totals = useMemo(() => {
    let ht = 0, tva = 0;
    form.items.forEach((it) => {
      const lineHT = (Number(it.quantity) || 0) * (Number(it.unit_price_ht) || 0);
      const lineTVA = lineHT * (Number(it.tva_pct) || 0) / 100;
      ht += lineHT; tva += lineTVA;
    });
    const ttc = ht + tva;
    let disc = 0;
    if (form.discount_kind === "value") disc = Math.min(Number(form.discount_value) || 0, ttc);
    else if (form.discount_kind === "percent") disc = ttc * Math.min(Number(form.discount_value) || 0, 100) / 100;
    return { ht, tva, ttc, disc, net: ttc - disc };
  }, [form.items, form.discount_kind, form.discount_value]);

  const addItem = () => setForm({ ...form, items: [...form.items, { label: "", quantity: 1, unit_price_ht: 0, tva_pct: 18, unit: "pièce" }] });
  const removeItem = (i) => setForm({ ...form, items: form.items.filter((_, idx) => idx !== i) });
  const updateItem = (i, patch) => setForm({ ...form, items: form.items.map((it, idx) => idx === i ? { ...it, ...patch } : it) });
  const fillFromProduct = (i, pid) => {
    const p = products.find((x) => x.id === pid);
    if (!p) return;
    updateItem(i, {
      product_id: p.id, label: p.name, unit_price_ht: p.unit_price_ht,
      tva_pct: p.tva_pct, unit: p.unit,
    });
  };

  const submit = async () => {
    if (!form.business_client_id) { toast.error("Sélectionnez un client en compte"); return; }
    if (!form.items.every((it) => it.label && it.quantity > 0 && it.unit_price_ht >= 0)) {
      toast.error("Veuillez compléter toutes les lignes"); return;
    }
    setSubmitting(true);
    try {
      const r = await apiClient.post("/cashier/invoices", form);
      toast.success(`${form.kind === "proforma" ? "Proforma" : "Facture"} ${r.data.number} créée`);
      setShowForm(false);
      setForm({
        kind: "proforma", business_client_id: "",
        items: [{ label: "", quantity: 1, unit_price_ht: 0, tva_pct: 18, unit: "pièce" }],
        discount_kind: "none", discount_value: 0, notes: "",
      });
      await load();
      window.open(`/portal/billing/invoice/${r.data.id}`, "_blank");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSubmitting(false); }
  };

  const convertToInvoice = async (iid) => {
    try {
      const r = await apiClient.patch(`/cashier/invoices/${iid}`, { kind: "invoice" });
      toast.success(`Convertie en ${r.data.invoice.number}`);
      load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const markPaid = async (iid) => {
    const pmId = window.prompt("Mode de paiement ID (collez ici)\n" +
      paymentMethods.map((p) => `${p.id} → ${p.label}`).join("\n"));
    if (!pmId) return;
    try {
      const r = await apiClient.patch(`/cashier/invoices/${iid}`, {
        status: "paid", payment_method_id: pmId,
      });
      toast.success(`Réglée — reçu ${r.data.generated_receipt?.number} généré`);
      load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const cancel = async (iid) => {
    if (!window.confirm("Annuler ce document ?")) return;
    try {
      await apiClient.patch(`/cashier/invoices/${iid}`, { status: "cancelled" });
      toast.success("Annulé");
      load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  // Iter37h — Hard delete (admin/superviseur only)
  const deleteInvoice = async (iid, number, kind) => {
    const label = kind === "proforma" ? "proforma" : "facture";
    if (!window.confirm(`Supprimer définitivement ${label} ${number || iid} ?\nCette action est irréversible.`)) return;
    try {
      await apiClient.delete(`/cashier/invoices/${iid}`);
      toast.success(`${label} ${number || iid} supprimé(e)`);
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de la suppression");
    }
  };

  // Iter37h — Duplicate an invoice/proforma (items only, no client) → open the
  // creation modal with pre-filled lines via a draft fetched from backend.
  const duplicateInvoice = async (iid, number) => {
    try {
      const r = await apiClient.post(`/cashier/invoices/${iid}/duplicate`);
      const draft = r.data?.draft;
      if (!draft) { toast.error("Échec de la duplication"); return; }
      setForm((prev) => ({
        ...prev,
        kind: draft.kind || "invoice",
        business_client_id: "",       // Forced empty per user spec
        items: (draft.items || []).map((it) => ({
          label: it.label || "",
          description: it.description || "",
          quantity: Number(it.quantity || 1),
          unit_price_ht: Number(it.unit_price_ht || 0),
          tva_pct: Number(it.tva_pct || 0),
        })),
        discount_kind: draft.discount_kind || "none",
        discount_value: Number(draft.discount_value || 0),
        notes: draft.notes || "",
        due_date: "",
        billing_address: "",
        shipping_address: "",
      }));
      setShowForm(true);
      toast.success(`Dupliqué depuis ${number || iid} — choisissez un client puis enregistrez`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de la duplication");
    }
  };

  return (
    <div className="space-y-4" data-testid="cashier-invoices-tab">
      <InvoiceKpiPanel />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
          <Receipt className="h-5 w-5 text-sawali-blue" /> Factures & Proformas
        </h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowTrash((v) => !v)}
            data-testid="invoices-trash-toggle"
            title={showTrash ? "Revenir aux factures actives" : "Voir la corbeille"}
            className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium ${showTrash ? "bg-rose-600 text-white hover:bg-rose-700" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}
          >
            <Trash2 className="h-4 w-4" /> {showTrash ? "Sortir de la corbeille" : "Corbeille"}
          </button>
          <select value={filter.kind} onChange={(e) => setFilter({ ...filter, kind: e.target.value })}
            className="rounded-md border border-slate-300 px-2 py-1 text-xs">
            <option value="">Tous types</option>
            <option value="proforma">Proformas</option>
            <option value="invoice">Factures</option>
          </select>
          <select value={filter.status} onChange={(e) => setFilter({ ...filter, status: e.target.value })}
            className="rounded-md border border-slate-300 px-2 py-1 text-xs">
            <option value="">Tous statuts</option>
            <option value="issued">Émis</option>
            <option value="paid">Réglé</option>
            <option value="cancelled">Annulé</option>
          </select>
          {overdueCount > 0 && (
            <button
              onClick={relanceOverdue}
              disabled={relancing}
              className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500 hover:bg-amber-600 disabled:opacity-60 text-white px-3 py-1.5 text-sm font-medium shadow-sm ring-1 ring-amber-600/30 animate-pulse"
              data-testid="cashier-relance-overdue-btn"
              title="Envoyer un rappel WhatsApp aux clients dont la facture est échue depuis plus de 30 jours"
            >
              {relancing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Bell className="h-4 w-4" />}
              Relancer {overdueCount} impayée{overdueCount > 1 ? "s" : ""}
            </button>
          )}
          <button
            onClick={() => downloadExport(`/cashier/exports/invoices.csv${(filter.kind || filter.status) ? `?${new URLSearchParams(Object.fromEntries(Object.entries(filter).filter(([_, v]) => v)))}` : ""}`, "factures.csv")}
            className="inline-flex items-center gap-1.5 rounded-lg bg-white ring-1 ring-slate-300 hover:bg-slate-50 text-slate-700 px-3 py-1.5 text-sm font-medium"
            data-testid="cashier-invoices-export-csv"
            title="Exporter en CSV (Excel)"
          >
            <FileSpreadsheet className="h-4 w-4 text-emerald-600" /> CSV
          </button>
          <button
            onClick={() => downloadExport(`/cashier/exports/invoices.pdf${(filter.kind || filter.status) ? `?${new URLSearchParams(Object.fromEntries(Object.entries(filter).filter(([_, v]) => v)))}` : ""}`, "factures.pdf")}
            className="inline-flex items-center gap-1.5 rounded-lg bg-white ring-1 ring-slate-300 hover:bg-slate-50 text-slate-700 px-3 py-1.5 text-sm font-medium"
            data-testid="cashier-invoices-export-pdf"
            title="Exporter en PDF"
          >
            <Download className="h-4 w-4 text-rose-600" /> PDF
          </button>
          <button onClick={() => setShowForm((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-sawali-blue hover:bg-sawali-blue-light text-white px-3 py-1.5 text-sm font-medium"
            data-testid="invoice-new-btn">
            <Plus className="h-4 w-4" /> Nouvelle
          </button>
        </div>
      </div>

      {showForm && (
        <div className="rounded-2xl bg-white shadow ring-1 ring-slate-200 p-4 space-y-3" data-testid="invoice-form">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">Type *</label>
              <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                <option value="proforma">Proforma</option>
                <option value="invoice">Facture</option>
              </select>
            </div>
            <div className="sm:col-span-2">
              <div className="flex items-center justify-between mb-1">
                <label className="block text-xs font-medium text-slate-700">Client en compte *</label>
                <button type="button" onClick={refreshClients} className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-100" data-testid="invoice-refresh-clients" title="Actualiser la liste des clients en compte">
                  <RefreshCw className="h-3 w-3" /> Actualiser
                </button>
              </div>
              <select value={form.business_client_id} onChange={(e) => setForm({ ...form, business_client_id: e.target.value })}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                <option value="">— Choisir —</option>
                {businessClients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
          </div>

          <div className="rounded-lg ring-1 ring-slate-200 overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="text-left px-2 py-1.5">Produit (optionnel)</th>
                  <th className="text-left px-2 py-1.5">Désignation</th>
                  <th className="text-right px-2 py-1.5">Qté</th>
                  <th className="text-right px-2 py-1.5">P.U. HT</th>
                  <th className="text-right px-2 py-1.5">TVA %</th>
                  <th className="text-right px-2 py-1.5">Total HT</th>
                  <th></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {form.items.map((it, i) => (
                  <tr key={i}>
                    <td className="px-2 py-1">
                      <select value={it.product_id || ""} onChange={(e) => fillFromProduct(i, e.target.value)}
                        className="w-full text-xs border border-slate-200 rounded px-1 py-0.5">
                        <option value="">—</option>
                        {products.map((p) => <option key={p.id} value={p.id}>{p.sku} · {p.name}</option>)}
                      </select>
                    </td>
                    <td className="px-2 py-1">
                      <input value={it.label} onChange={(e) => updateItem(i, { label: e.target.value })}
                        className="w-full text-xs border border-slate-200 rounded px-1 py-0.5" placeholder="Désignation" />
                    </td>
                    <td className="px-2 py-1">
                      <input type="number" min="0" step="0.01" value={it.quantity} onChange={(e) => updateItem(i, { quantity: Number(e.target.value) })}
                        className="w-20 text-right text-xs border border-slate-200 rounded px-1 py-0.5 font-mono" />
                    </td>
                    <td className="px-2 py-1">
                      <input type="number" min="0" value={it.unit_price_ht} onChange={(e) => updateItem(i, { unit_price_ht: Number(e.target.value) })}
                        className="w-24 text-right text-xs border border-slate-200 rounded px-1 py-0.5 font-mono" />
                    </td>
                    <td className="px-2 py-1">
                      <input type="number" min="0" max="100" step="0.01" value={it.tva_pct} onChange={(e) => updateItem(i, { tva_pct: Number(e.target.value) })}
                        className="w-16 text-right text-xs border border-slate-200 rounded px-1 py-0.5 font-mono" />
                    </td>
                    <td className="px-2 py-1 text-right font-mono">{FCFA((it.quantity || 0) * (it.unit_price_ht || 0))}</td>
                    <td className="px-2 py-1 text-right">
                      <button onClick={() => removeItem(i)} className="text-rose-500 hover:text-rose-700">
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="px-2 py-1 bg-slate-50 border-t">
              <button onClick={addItem} className="text-xs text-sawali-blue hover:underline">+ Ajouter une ligne</button>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="flex items-center gap-2">
              <label className="text-xs font-medium text-slate-700">Remise</label>
              <select value={form.discount_kind} onChange={(e) => setForm({ ...form, discount_kind: e.target.value })}
                className="rounded border border-slate-300 px-2 py-1 text-xs">
                <option value="none">Aucune</option>
                <option value="value">En valeur</option>
                <option value="percent">En %</option>
              </select>
              {form.discount_kind !== "none" && (
                <input type="number" min="0" value={form.discount_value} onChange={(e) => setForm({ ...form, discount_value: Number(e.target.value) })}
                  className="w-24 text-right text-xs border border-slate-300 rounded px-2 py-1 font-mono" />
              )}
            </div>
            <div className="text-right text-xs space-y-0.5 font-mono">
              <div>Sous-total HT : <strong className="text-slate-800">{FCFA(totals.ht)} FCFA</strong></div>
              <div>TVA : <strong className="text-slate-800">{FCFA(totals.tva)} FCFA</strong></div>
              <div>Total TTC : <strong className="text-slate-800">{FCFA(totals.ttc)} FCFA</strong></div>
              {totals.disc > 0 && <div className="text-rose-600">Remise : -{FCFA(totals.disc)} FCFA</div>}
              <div className="text-base text-sawali-blue">Net à payer : <strong>{FCFA(totals.net)} FCFA</strong></div>
            </div>
          </div>

          <div className="flex items-center justify-end gap-2 pt-2">
            <button onClick={() => setShowForm(false)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">Annuler</button>
            <button onClick={submit} disabled={submitting}
              className="inline-flex items-center gap-1.5 rounded-lg bg-sawali-blue hover:bg-sawali-blue-light text-white px-3 py-1.5 text-sm font-medium disabled:opacity-50"
              data-testid="invoice-form-submit">
              {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Créer & imprimer
            </button>
          </div>
        </div>
      )}

      <div className="rounded-2xl bg-white shadow ring-1 ring-slate-200 overflow-hidden">
        {loading ? <Empty label="Chargement…" /> : items.length === 0 ? <Empty label="Aucun document" /> : (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs text-slate-600">
              <tr>
                <th className="text-left px-3 py-2">N°</th>
                <th className="text-left px-3 py-2">Type</th>
                <th className="text-left px-3 py-2">Client</th>
                <th className="text-right px-3 py-2">Net</th>
                <th className="text-left px-3 py-2">Statut</th>
                <th className="text-left px-3 py-2">Date</th>
                <th className="text-left px-3 py-2">WhatsApp</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((i) => (
                <tr key={i.id} className="hover:bg-slate-50">
                  <td className="px-3 py-2 font-mono font-semibold text-slate-800">{i.number}</td>
                  <td className="px-3 py-2 text-xs">
                    {i.kind === "proforma"
                      ? <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 text-amber-700 ring-1 ring-amber-200 px-1.5 py-0.5">Proforma</span>
                      : <span className="inline-flex items-center gap-1 rounded-full bg-sky-50 text-sawali-blue ring-1 ring-sky-200 px-1.5 py-0.5">Facture</span>}
                  </td>
                  <td className="px-3 py-2 text-slate-700 text-sm">{(i.business_client_snapshot || {}).name}</td>
                  <td className="px-3 py-2 text-right font-mono font-bold">{FCFA(i.net_to_pay)} FCFA</td>
                  <td className="px-3 py-2 text-xs">
                    {i.status === "paid" && <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 px-1.5 py-0.5"><CheckCircle2 className="h-3 w-3" /> Réglée</span>}
                    {i.status === "issued" && <span className="inline-flex items-center gap-1 rounded-full bg-slate-50 text-slate-600 ring-1 ring-slate-200 px-1.5 py-0.5">Émis</span>}
                    {i.status === "cancelled" && <span className="inline-flex items-center gap-1 rounded-full bg-rose-50 text-rose-700 ring-1 ring-rose-200 px-1.5 py-0.5"><XCircle className="h-3 w-3" /> Annulée</span>}
                  </td>
                  <td className="px-3 py-2 text-slate-500 text-xs">{new Date(i.created_at).toLocaleDateString("fr-FR")}</td>
                  <td className="px-3 py-2 text-xs" data-testid={`invoice-wa-status-${i.id}`}>
                    {i.whatsapp_sent_at ? (
                      <button
                        onClick={() => setWaPreview(i)}
                        className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 px-1.5 py-0.5 hover:bg-emerald-100"
                        title={`Cliquer pour voir l'aperçu / renvoyer · Envoyé à ${i.whatsapp_to || ""}`}
                        data-testid={`invoice-wa-preview-${i.id}`}
                      >
                        <CheckCircle2 className="h-3 w-3" /> {fmtDt(i.whatsapp_sent_at)}
                      </button>
                    ) : i.whatsapp_last_status === "ko" ? (
                      <button
                        onClick={() => setWaPreview(i)}
                        className="inline-flex items-center gap-1 rounded-full bg-rose-50 text-rose-700 ring-1 ring-rose-200 px-1.5 py-0.5 hover:bg-rose-100"
                        title={i.whatsapp_last_error || "Envoi WhatsApp échoué — cliquer pour réessayer"}
                        data-testid={`invoice-wa-preview-${i.id}`}
                      >
                        <AlertTriangle className="h-3 w-3" /> KO
                      </button>
                    ) : (
                      <button
                        onClick={() => setWaPreview(i)}
                        className="inline-flex items-center gap-1 text-slate-500 hover:text-emerald-600 underline-offset-2 hover:underline text-xs"
                        title="Aperçu et envoi WhatsApp"
                        data-testid={`invoice-wa-preview-${i.id}`}
                      >
                        <Eye className="h-3 w-3" /> Aperçu
                      </button>
                    )}
                    {i.last_reminder_at && (
                      <span className="ml-1 inline-flex items-center gap-0.5 rounded-full bg-amber-50 text-amber-700 ring-1 ring-amber-200 px-1.5 py-0.5"
                        title={`${i.reminders_count || 1} rappel(s) — dernier le ${fmtDt(i.last_reminder_at)}`}>
                        <Bell className="h-3 w-3" /> {i.reminders_count || 1}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right space-x-1">
                    <Link to={`/portal/billing/invoice/${i.id}`} target="_blank" className="inline-flex items-center gap-0.5 text-sawali-blue hover:underline text-xs">
                      <Printer className="h-3.5 w-3.5" />
                    </Link>
                    {/* Iter37h — Duplicate invoice/proforma (no client, only lines) */}
                    <button
                      onClick={() => duplicateInvoice(i.id, i.number)}
                      className="text-xs text-violet-600 hover:underline"
                      title="Dupliquer (sans client, juste les lignes)"
                      data-testid={`invoice-duplicate-${i.id}`}
                    >
                      <Copy className="h-3.5 w-3.5 inline" />
                    </button>
                    {/* Iter38d — Trash mode: restore + permanent delete; otherwise standard actions */}
                    {i.deleted_at ? (
                      <>
                        {canDelete && (
                          <>
                            <button
                              onClick={() => restoreInvoice(i.id, i.number)}
                              className="text-xs text-emerald-600 hover:underline"
                              title="Restaurer cette facture"
                              data-testid={`invoice-restore-${i.id}`}
                            >
                              <RotateCcw className="h-3.5 w-3.5 inline" />
                            </button>
                            <button
                              onClick={() => purgeInvoice(i.id, i.number)}
                              className="text-xs text-rose-700 hover:underline"
                              title="Supprimer définitivement (irréversible)"
                              data-testid={`invoice-purge-${i.id}`}
                            >
                              <Trash2 className="h-3.5 w-3.5 inline" />
                            </button>
                          </>
                        )}
                      </>
                    ) : (
                      <>
                        {i.kind === "proforma" && i.status === "issued" && (
                          <button onClick={() => convertToInvoice(i.id)} className="text-xs text-emerald-600 hover:underline" title="Convertir en facture">
                            <ArrowRight className="h-3.5 w-3.5 inline" />
                          </button>
                        )}
                        {i.kind === "invoice" && i.status === "issued" && (
                          <button onClick={() => markPaid(i.id)} className="text-xs text-emerald-600 hover:underline" title="Marquer réglée">
                            <CheckCircle2 className="h-3.5 w-3.5 inline" />
                          </button>
                        )}
                        {i.status === "issued" && (
                          <button onClick={() => cancel(i.id)} className="text-xs text-amber-600 hover:underline" title="Annuler (statut)">
                            <XCircle className="h-3.5 w-3.5 inline" />
                          </button>
                        )}
                        {canDelete && (
                          <button
                            onClick={() => deleteInvoice(i.id, i.number, i.kind)}
                            className="text-xs text-rose-600 hover:underline"
                            title="Mettre à la corbeille (admin/superviseur)"
                            data-testid={`invoice-delete-${i.id}`}
                          >
                            <Trash2 className="h-3.5 w-3.5 inline" />
                          </button>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {waPreview && (
        <WaPreviewModal
          doc={waPreview}
          kind="invoice"
          onClose={() => setWaPreview(null)}
          onSent={() => { setWaPreview(null); load(); }}
        />
      )}
    </div>
  );
}

// =====================================================================
// Generic CRUD tab (clients en compte, products, payment methods)
// =====================================================================
// =====================================================================
// Iter37b — CSV import button (modal with file picker + tooltip on hover)
// =====================================================================
function CsvImportButton({ resourceKind, onSuccess }) {
  // resourceKind: 'business-clients' | 'products'
  const [open, setOpen] = useState(false);
  const [fields, setFields] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [file, setFile] = useState(null);

  const fetchFields = async () => {
    try {
      const r = await apiClient.get(`/cashier/import/${resourceKind}/fields`);
      setFields(r.data);
    } catch { setFields(null); }
  };

  const upload = async () => {
    if (!file) { toast.error("Sélectionnez un fichier CSV"); return; }
    const text = await file.text();
    setUploading(true);
    try {
      const r = await apiClient.post(`/cashier/import/${resourceKind}`, { csv: text });
      const { created = 0, skipped_duplicates = 0, errors = [], total_lines = 0 } = r.data || {};
      const detail = [];
      detail.push(`${created} créé(s)`);
      if (skipped_duplicates) detail.push(`${skipped_duplicates} doublons ignorés`);
      if (errors.length) detail.push(`${errors.length} erreurs`);
      if (errors.length === 0 && created > 0) {
        toast.success(`Import OK — ${detail.join(" · ")} (${total_lines} lignes)`);
      } else if (created > 0) {
        toast.warning(`Import partiel — ${detail.join(" · ")}`);
      } else {
        toast.error(`Aucun import — ${detail.join(" · ") || "fichier vide"}`);
      }
      setOpen(false);
      setFile(null);
      onSuccess && onSuccess();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur d'import");
    } finally { setUploading(false); }
  };

  const tooltip = fields?.sample ? `Ordre des champs (séparateur ';'):\n${fields.sample}\n\n${fields.note || ""}` : "Charger le format attendu";

  return (
    <>
      <button
        type="button"
        onMouseEnter={fetchFields}
        onClick={() => { fetchFields(); setOpen(true); }}
        title={tooltip}
        className="inline-flex items-center gap-1.5 rounded-lg bg-white ring-1 ring-slate-300 hover:bg-slate-50 text-slate-700 px-3 py-1.5 text-sm font-medium"
        data-testid={`csv-import-btn-${resourceKind}`}
      >
        <FileSpreadsheet className="h-4 w-4 text-emerald-600" /> Importer CSV
      </button>
      {open && (
        <div className="fixed inset-0 bg-slate-900/50 z-50 flex items-center justify-center p-4" onClick={() => setOpen(false)}>
          <div className="bg-white rounded-2xl shadow-xl max-w-lg w-full p-5 space-y-4" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h3 className="text-base font-display font-bold inline-flex items-center gap-2"><FileSpreadsheet className="h-4 w-4 text-emerald-600" /> Import CSV</h3>
              <button onClick={() => setOpen(false)}><X className="h-5 w-5" /></button>
            </div>
            {fields && (
              <div className="rounded-lg bg-slate-50 ring-1 ring-slate-200 p-3 text-xs text-slate-700 space-y-1">
                <p className="font-medium text-slate-900">Ordre des colonnes (séparateur <code>;</code>) :</p>
                <p className="font-mono text-[11px] break-all">{fields.sample}</p>
                <p className="text-slate-500 italic">{fields.note}</p>
              </div>
            )}
            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">Fichier CSV (UTF-8)</label>
              <input type="file" accept=".csv,text/csv"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="w-full text-sm" data-testid="csv-import-file-input" />
              {file && <p className="text-xs text-slate-500 mt-1">📄 {file.name} ({Math.round(file.size / 1024)} Ko)</p>}
            </div>
            <div className="flex items-center justify-end gap-2 pt-2">
              <button onClick={() => setOpen(false)} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">Annuler</button>
              <button onClick={upload} disabled={uploading || !file}
                className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1.5 text-sm font-medium disabled:opacity-50"
                data-testid="csv-import-submit">
                {uploading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Importer
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}


// =====================================================================
// Iter38e (B.3) — Image upload field for product icons / catalog images.
// Uploads to /me/upload (supervisor-allowed), then stores returned `url`.
// Includes an "AI" generate button (Gemini Nano Banana, server-side route
// `/admin/ai/generate-icon`) — degrades gracefully when not configured.
// =====================================================================
function ImageUploadField({ value, onChange, testId }) {
  const [uploading, setUploading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [aiPrompt, setAiPrompt] = useState("");
  const inputRef = React.useRef(null);
  const backend = process.env.REACT_APP_BACKEND_URL || "";

  const onPickFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      toast.error("Image trop volumineuse (max 5 Mo)");
      return;
    }
    const form = new FormData();
    form.append("file", file);
    setUploading(true);
    try {
      const r = await apiClient.post("/me/upload", form, { headers: { "Content-Type": "multipart/form-data" } });
      const url = r.data?.public_url || r.data?.url || "";
      if (url) {
        onChange(url);
        toast.success("Image téléversée");
      } else {
        toast.error("Réponse upload invalide");
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec du téléversement");
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const onGenerateAi = async () => {
    if (!aiPrompt.trim()) {
      toast.warning("Décrivez l'icône souhaitée");
      return;
    }
    setGenerating(true);
    try {
      const r = await apiClient.post("/cashier/products/generate-icon", { prompt: aiPrompt.trim() });
      const url = r.data?.public_url || r.data?.url || "";
      if (url) {
        onChange(url);
        toast.success("Icône générée par IA");
      } else {
        toast.error("Génération IA indisponible");
      }
    } catch (err) {
      const msg = err?.response?.data?.detail || "IA non configurée";
      toast.warning(msg);
    } finally { setGenerating(false); }
  };

  const fullSrc = value
    ? (value.startsWith("http") ? value : `${backend}${value.startsWith("/") ? "" : "/"}${value}`)
    : null;

  return (
    <div className="space-y-2" data-testid={testId}>
      <div className="flex items-start gap-3">
        <div className="w-16 h-16 rounded-lg ring-1 ring-slate-200 bg-slate-50 flex items-center justify-center overflow-hidden flex-shrink-0">
          {fullSrc ? (
            <img src={fullSrc} alt="Icône" className="w-full h-full object-cover" onError={(e) => { e.target.style.display = "none"; }} />
          ) : (
            <ImageIcon className="h-6 w-6 text-slate-300" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <input
            type="text"
            value={value || ""}
            onChange={(e) => onChange(e.target.value)}
            placeholder="https://… ou /api/files/…"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-mono"
          />
          <div className="flex items-center gap-2 mt-1.5 flex-wrap">
            <input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp" onChange={onPickFile} className="hidden" data-testid={`${testId}-input`} />
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              disabled={uploading}
              className="inline-flex items-center gap-1.5 rounded bg-violet-600 hover:bg-violet-700 disabled:opacity-60 text-white px-2.5 py-1 text-xs font-medium"
              data-testid={`${testId}-btn`}
            >
              {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
              {uploading ? "Téléversement…" : "Téléverser PNG/JPG"}
            </button>
            {value && (
              <button
                type="button"
                onClick={() => onChange("")}
                className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-rose-600"
              >
                <X className="h-3 w-3" /> Retirer
              </button>
            )}
          </div>
        </div>
      </div>
      {/* AI generation row */}
      <div className="flex items-center gap-2 pl-[76px]">
        <input
          type="text"
          value={aiPrompt}
          onChange={(e) => setAiPrompt(e.target.value)}
          placeholder="Décrire pour génération IA (ex: ordinateur portable bleu pictogramme)"
          className="flex-1 rounded border border-slate-200 px-2 py-1 text-xs"
          data-testid={`${testId}-ai-prompt`}
        />
        <button
          type="button"
          onClick={onGenerateAi}
          disabled={generating}
          className="inline-flex items-center gap-1 rounded bg-amber-500 hover:bg-amber-600 disabled:opacity-60 text-white px-2 py-1 text-xs font-medium"
          data-testid={`${testId}-ai-btn`}
        >
          {generating ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
          {generating ? "Génération…" : "Générer IA"}
        </button>
      </div>
    </div>
  );
}



function CrudTab({ title, icon: Icon, color, listPath, createPath, deletePath, fields, formInitial, transformBeforeSubmit, dataTestId, extraHeaderButton }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(formInitial);
  const [submitting, setSubmitting] = useState(false);
  const [remoteOptions, setRemoteOptions] = useState({});  // { fieldKey: [{value, label}] }

  // Iter37a — Prefetch remoteSelect options once
  useEffect(() => {
    const remotes = (fields || []).filter((f) => f.type === "remoteSelect" && f.sourcePath);
    if (!remotes.length) return;
    Promise.all(remotes.map((f) =>
      apiClient.get(f.sourcePath).then((r) => ({
        key: f.key,
        options: (r.data || []).map((row) => ({ value: row[f.optionValue || "label"], label: row[f.optionLabel || "label"] })),
      })).catch(() => ({ key: f.key, options: [] }))
    )).then((arr) => {
      const next = {};
      arr.forEach((x) => { next[x.key] = x.options; });
      setRemoteOptions(next);
    });
  }, [fields]);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get(listPath);
      setItems(r.data || []);
    } catch { setItems([]); } finally { setLoading(false); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  const submit = async () => {
    const payload = transformBeforeSubmit ? transformBeforeSubmit(form) : form;
    setSubmitting(true);
    try {
      if (editing) {
        await apiClient.patch(`${createPath}/${editing.id}`, payload);
        toast.success("Modifié");
      } else {
        await apiClient.post(createPath, payload);
        toast.success("Créé");
      }
      setShowForm(false);
      setEditing(null);
      setForm(formInitial);
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSubmitting(false); }
  };

  const startEdit = (item) => {
    setEditing(item);
    const f = { ...formInitial };
    fields.forEach((fld) => { f[fld.key] = item[fld.key] ?? formInitial[fld.key]; });
    setForm(f);
    setShowForm(true);
  };

  const remove = async (id) => {
    if (!window.confirm("Supprimer cet élément ?")) return;
    try {
      await apiClient.delete(`${deletePath}/${id}`);
      toast.success("Supprimé");
      load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  return (
    <div className="space-y-4" data-testid={dataTestId}>
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
          <Icon className={`h-5 w-5 ${color}`} /> {title}
        </h2>
        <div className="flex items-center gap-2">
          {typeof extraHeaderButton === "function" ? extraHeaderButton({ onRefresh: load }) : extraHeaderButton}
          <button onClick={() => { setEditing(null); setForm(formInitial); setShowForm((v) => !v); }}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800 hover:bg-slate-900 text-white px-3 py-1.5 text-sm">
            <Plus className="h-4 w-4" /> Nouveau
          </button>
        </div>
      </div>
      {showForm && (
        <div className="rounded-2xl bg-white shadow ring-1 ring-slate-200 p-4 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {fields.map((fld) => (
              <div key={fld.key} className={fld.full ? "sm:col-span-2" : ""}>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  {fld.label}{fld.required && " *"}
                </label>
                {fld.type === "select" ? (
                  <select value={form[fld.key] || ""} onChange={(e) => setForm({ ...form, [fld.key]: e.target.value })}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                    <option value="">— Choisir —</option>
                    {(fld.options || []).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                ) : fld.type === "remoteSelect" ? (
                  <select value={form[fld.key] || ""} onChange={(e) => setForm({ ...form, [fld.key]: e.target.value })}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                    <option value="">— Choisir —</option>
                    {(remoteOptions[fld.key] || []).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                ) : fld.type === "readonly" ? (
                  <input type="text" value={form[fld.key] ?? "(auto-généré à la création)"} readOnly disabled
                    className="w-full rounded-lg border border-slate-200 bg-slate-100 text-slate-500 px-3 py-2 text-sm font-mono cursor-not-allowed" />
                ) : fld.type === "textarea" ? (
                  <textarea value={form[fld.key] || ""} onChange={(e) => setForm({ ...form, [fld.key]: e.target.value })}
                    rows={2} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                ) : fld.type === "checkbox" ? (
                  <label className="inline-flex items-center gap-2 text-sm pt-2">
                    <input type="checkbox" checked={!!form[fld.key]} onChange={(e) => setForm({ ...form, [fld.key]: e.target.checked })} />
                    {fld.checkboxLabel || fld.label}
                  </label>
                ) : fld.type === "imageUpload" ? (
                  /* Iter38e (B.3) — Upload PNG/JPG icon via /me/upload then prefill URL */
                  <ImageUploadField
                    value={form[fld.key] || ""}
                    onChange={(url) => setForm({ ...form, [fld.key]: url })}
                    testId={`${fld.key}-upload`}
                  />
                ) : (
                  <input type={fld.type || "text"} value={form[fld.key] ?? ""} onChange={(e) => {
                    let v = fld.type === "number" ? Number(e.target.value) : e.target.value;
                    if (fld.uppercase && typeof v === "string") v = v.toUpperCase();
                    setForm({ ...form, [fld.key]: v });
                  }} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                )}
              </div>
            ))}
          </div>
          <div className="flex items-center justify-end gap-2 pt-2">
            <button onClick={() => { setShowForm(false); setEditing(null); }} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">Annuler</button>
            <button onClick={submit} disabled={submitting}
              className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800 hover:bg-slate-900 text-white px-3 py-1.5 text-sm font-medium disabled:opacity-50">
              {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {editing ? "Modifier" : "Créer"}
            </button>
          </div>
        </div>
      )}
      <div className="rounded-2xl bg-white shadow ring-1 ring-slate-200 overflow-hidden">
        {loading ? <Empty label="Chargement…" /> : items.length === 0 ? <Empty label="Aucun élément" /> : (
          <ul className="divide-y divide-slate-100">
            {items.map((it) => (
              <li key={it.id} className="px-3 py-2 flex items-center gap-3 hover:bg-slate-50">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-slate-800 truncate">
                    {it.name || it.label || it.sku}
                  </p>
                  <p className="text-xs text-slate-500 truncate">
                    {it.sku && <span className="font-mono mr-2">{it.sku}</span>}
                    {it.unit_price_ht !== undefined && <span>{FCFA(it.unit_price_ht)} FCFA / {it.unit}</span>}
                    {it.phone && <span>{it.phone}</span>}
                    {it.kind && <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-slate-100 text-slate-600 px-1.5 py-0.5">{it.kind}</span>}
                    {/* Iter38e (B.2) — Dernière utilisation sur une facture (jamais sur proforma) */}
                    {it.last_used_at && (
                      <span
                        className="ml-2 inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 px-1.5 py-0.5"
                        title={`Dernière facturation: ${new Date(it.last_used_at).toLocaleString("fr-FR")}`}
                        data-testid={`product-last-used-${it.id}`}
                      >
                        🕒 {new Date(it.last_used_at).toLocaleDateString("fr-FR")}
                      </span>
                    )}
                  </p>
                </div>
                <button onClick={() => startEdit(it)} className="text-slate-500 hover:text-slate-900"><Edit2 className="h-3.5 w-3.5" /></button>
                <button onClick={() => remove(it.id)} className="text-rose-500 hover:text-rose-700"><Trash2 className="h-3.5 w-3.5" /></button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}


// =====================================================================
// Iter36y — Auto-relance admin settings panel (master toggle, schedule, history)
// =====================================================================
function AutoRelanceTab() {
  const [settings, setSettings] = useState({
    auto_relance_enabled: false,
    auto_relance_day_of_week: 0,
    auto_relance_grace_days: 30,
    auto_relance_email_report_to: "",
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [history, setHistory] = useState([]);
  const DAYS = [
    { v: 0, label: "Lundi" }, { v: 1, label: "Mardi" }, { v: 2, label: "Mercredi" },
    { v: 3, label: "Jeudi" }, { v: 4, label: "Vendredi" }, { v: 5, label: "Samedi" }, { v: 6, label: "Dimanche" },
  ];

  const load = async () => {
    setLoading(true);
    try {
      const [s, h] = await Promise.all([
        apiClient.get("/cashier/auto-relance/settings"),
        apiClient.get("/cashier/overdue/relance-history", { params: { limit: 20 } }),
      ]);
      setSettings({
        auto_relance_enabled: !!s.data?.auto_relance_enabled,
        auto_relance_day_of_week: Number(s.data?.auto_relance_day_of_week ?? 0),
        auto_relance_grace_days: Number(s.data?.auto_relance_grace_days ?? 30),
        auto_relance_email_report_to: s.data?.auto_relance_email_report_to || "",
      });
      setHistory(h.data || []);
    } catch { /* noop */ } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true);
    try {
      await apiClient.put("/cashier/auto-relance/settings", settings);
      toast.success("Paramètres enregistrés");
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSaving(false); }
  };

  const triggerNow = async () => {
    if (running) return;
    if (!window.confirm("Lancer la relance automatique maintenant (sur tous les clients en compte ayant la relance activée) ?")) return;
    setRunning(true);
    try {
      const r = await apiClient.post("/cashier/overdue/relance-auto-run");
      const { sent_ok = 0, sent_ko = 0, skipped_no_phone = 0, total = 0, business_clients_count = 0, skipped, reason } = r.data || {};
      if (skipped) {
        toast.warning(`Relance non exécutée — ${reason || "skipped"}`);
      } else {
        toast.success(`Relance terminée — ${business_clients_count} client(s) ciblé(s) · ${total} facture(s) · ✓${sent_ok} ✗${sent_ko} ⊝${skipped_no_phone}`);
      }
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setRunning(false); }
  };

  return (
    <div className="space-y-4" data-testid="cashier-auto-relance-tab">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
          <Bell className="h-5 w-5 text-amber-500" /> Relance automatique des impayés
        </h2>
        <button
          onClick={triggerNow}
          disabled={running}
          className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500 hover:bg-amber-600 disabled:opacity-60 text-white px-3 py-1.5 text-sm font-medium"
          data-testid="auto-relance-trigger-now"
        >
          {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Bell className="h-4 w-4" />}
          Tester maintenant
        </button>
      </div>

      <div className="rounded-2xl bg-white shadow ring-1 ring-slate-200 p-4 space-y-4">
        <p className="text-xs text-slate-600">
          Quand activée, la relance s'exécute automatiquement <b>chaque {DAYS[settings.auto_relance_day_of_week]?.label || "Lundi"} à 09:00 (Africa/Abidjan)</b>.
          Seuls les <b>Clients en compte</b> dont la case « 🔔 Relance automatique » est cochée sont ciblés.
          Une facture est considérée impayée si elle est <code>status=issued</code> et que sa date d'échéance est dépassée
          (ou créée il y a plus de N jours si aucune échéance).
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label className="flex items-center gap-2 rounded-lg ring-1 ring-slate-200 px-3 py-2">
            <input type="checkbox" checked={settings.auto_relance_enabled}
              onChange={(e) => setSettings({ ...settings, auto_relance_enabled: e.target.checked })}
              data-testid="auto-relance-master-toggle" />
            <span className="text-sm font-medium">Activer la relance automatique (master)</span>
          </label>
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">Jour de la semaine</label>
            <select value={settings.auto_relance_day_of_week}
              onChange={(e) => setSettings({ ...settings, auto_relance_day_of_week: Number(e.target.value) })}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              data-testid="auto-relance-day-of-week">
              {DAYS.map((d) => <option key={d.v} value={d.v}>{d.label}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">Délai de grâce (jours sans paiement)</label>
            <input type="number" min="0" max="365" value={settings.auto_relance_grace_days}
              onChange={(e) => setSettings({ ...settings, auto_relance_grace_days: Number(e.target.value) })}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">Email destinataire du rapport</label>
            <input type="email" value={settings.auto_relance_email_report_to}
              onChange={(e) => setSettings({ ...settings, auto_relance_email_report_to: e.target.value })}
              placeholder="admin@sawalismartsystems.com"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </div>
        </div>

        <div>
          <button onClick={save} disabled={saving}
            className="inline-flex items-center gap-1.5 rounded-lg bg-sawali-blue hover:bg-sawali-blue-light disabled:opacity-60 text-white px-4 py-2 text-sm font-medium"
            data-testid="auto-relance-save-btn">
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            Enregistrer
          </button>
        </div>
      </div>

      <div className="rounded-2xl bg-white shadow ring-1 ring-slate-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
          <h3 className="text-sm font-display font-semibold">Historique des exécutions</h3>
          <span className="text-xs text-slate-500">{history.length} entrée(s)</span>
        </div>
        {loading ? <Empty label="Chargement…" /> : history.length === 0 ? <Empty label="Aucune exécution pour le moment" /> : (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs text-slate-600">
              <tr>
                <th className="text-left px-3 py-2">Date</th>
                <th className="text-left px-3 py-2">Déclenchement</th>
                <th className="text-right px-3 py-2">Clients</th>
                <th className="text-right px-3 py-2">Factures</th>
                <th className="text-right px-3 py-2">✓ OK</th>
                <th className="text-right px-3 py-2">✗ KO</th>
                <th className="text-right px-3 py-2">⊝ Sans n°</th>
                <th className="text-left px-3 py-2">Email</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {history.map((h) => (
                <tr key={h.id} className="hover:bg-slate-50">
                  <td className="px-3 py-2 text-xs">{fmtDt(h.started_at)}</td>
                  <td className="px-3 py-2 text-xs text-slate-600">{h.triggered_by}</td>
                  <td className="px-3 py-2 text-right font-mono text-xs">{h.business_clients_count || 0}</td>
                  <td className="px-3 py-2 text-right font-mono text-xs">{h.total || 0}</td>
                  <td className="px-3 py-2 text-right font-mono text-xs text-emerald-700">{h.sent_ok || 0}</td>
                  <td className="px-3 py-2 text-right font-mono text-xs text-rose-600">{h.sent_ko || 0}</td>
                  <td className="px-3 py-2 text-right font-mono text-xs text-slate-500">{h.skipped_no_phone || 0}</td>
                  <td className="px-3 py-2 text-xs">
                    {h.email_report?.sent
                      ? <span className="text-emerald-600">✓ {h.email_report.to}</span>
                      : (h.skipped ? <span className="text-slate-400 italic">{h.reason}</span> : <span className="text-slate-400">—</span>)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}


// =====================================================================
// Main page
// =====================================================================
export default function CashBilling({ defaultTab = "receipts" }) {
  const { user } = useAuth();
  const [tab, setTab] = useState(defaultTab);
  const [businessClients, setBusinessClients] = useState([]);
  const [products, setProducts] = useState([]);
  const [paymentMethods, setPaymentMethods] = useState([]);
  // Iter37f — Tenant info badge
  const [tenantInfo, setTenantInfo] = useState(null);

  const refresh = async () => {
    try {
      const [bc, pr, pm] = await Promise.all([
        apiClient.get("/admin/business-clients"),
        apiClient.get("/admin/products"),
        apiClient.get("/payment-methods"),
      ]);
      setBusinessClients(bc.data || []);
      setProducts(pr.data || []);
      setPaymentMethods(pm.data || []);
    } catch { /* noop */ }
  };
  useEffect(() => { refresh(); }, []);
  // Iter37f — Load tenant info once
  useEffect(() => {
    apiClient.get("/cashier/tenant-info")
      .then((r) => setTenantInfo(r.data))
      .catch(() => setTenantInfo(null));
  }, []);

  const canAccess = ["admin", "superviseur"].includes(user?.role) || user?.can_cash;
  if (!canAccess) {
    return (
      <div className="rounded-2xl bg-amber-50 ring-1 ring-amber-200 p-6 text-center">
        <AlertTriangle className="h-8 w-8 text-amber-500 mx-auto mb-2" />
        <p className="text-sm text-amber-800">
          Vous n'avez pas les permissions pour accéder à la caisse.
          Un administrateur doit activer la fonction caissier sur votre compte.
        </p>
      </div>
    );
  }

  const isAdmin = ["admin", "superviseur"].includes(user?.role);
  const isComptable = (user?.tracked_role || "") === "Comptable";
  const canExpense = isAdmin || !!user?.can_cash || isComptable;
  // Iter38r-fix9o — "Payer (Mobile Money)" deeplink visible only when the
  // user is Cashier AND (Admin OR Superviseur). Replaces the sidebar link.
  const trackedRole = (user?.tracked_role || "").toLowerCase();
  const isCashier = !!user?.can_cash || trackedRole === "caissier";
  const isAdminOrSup = isAdmin || trackedRole === "admin" || trackedRole === "superviseur";
  const canPayout = isCashier && isAdminOrSup;

  const tabs = [
    { key: "receipts", label: "Caisse", icon: Banknote, color: "text-emerald-600" },
    { key: "invoices", label: "Facturation", icon: Receipt, color: "text-sawali-blue" },
    ...(canExpense ? [
      { key: "expenses", label: "Dépenses", icon: CreditCard, color: "text-rose-700" },
    ] : []),
    ...(isAdmin ? [
      { key: "catalog", label: "Catalogue", icon: ShoppingBag, color: "text-violet-600" },
      { key: "business", label: "Clients en compte", icon: Building2, color: "text-amber-600" },
      { key: "payment", label: "Modes de paiement", icon: CreditCard, color: "text-rose-600" },
      { key: "legal_forms", label: "Formes juridiques", icon: FileText, color: "text-slate-600" },
      { key: "categories", label: "Catégories produits", icon: Tag, color: "text-violet-500" },
      { key: "auto_relance", label: "Relance auto", icon: Bell, color: "text-amber-500" },
    ] : []),
  ];

  return (
    <div className="space-y-4">
      {/* Iter37f — Tenant info badge: shows which company/users share this Caisse space */}
      {tenantInfo && (
        <div
          className="flex flex-wrap items-center gap-3 rounded-2xl bg-gradient-to-r from-sky-50 via-emerald-50 to-fuchsia-50 ring-1 ring-sky-200 px-4 py-2.5 text-xs"
          data-testid="cashier-tenant-badge"
          title={`Tenant ID : ${tenantInfo.tenant_id}`}
        >
          <span className="inline-flex items-center gap-1.5 font-semibold text-sawali-blue">
            <Building className="h-4 w-4" />
            {tenantInfo.tenant_name || "—"}
          </span>
          <span className="text-slate-300">·</span>
          <span className="inline-flex items-center gap-1.5 text-emerald-700">
            <Users className="h-3.5 w-3.5" />
            <strong className="font-bold tabular-nums">{tenantInfo.member_count}</strong>
            utilisateur{tenantInfo.member_count > 1 ? "s" : ""} partage{tenantInfo.member_count > 1 ? "nt" : ""} cette caisse
          </span>
          <span className="text-slate-300">·</span>
          <span className="inline-flex items-center gap-1.5 text-amber-700">
            <Building2 className="h-3.5 w-3.5" />
            <strong className="font-bold tabular-nums">{tenantInfo.business_client_count}</strong>
            client{tenantInfo.business_client_count > 1 ? "s" : ""} en compte
          </span>
          <span className="text-slate-300">·</span>
          <span className="inline-flex items-center gap-1.5 text-violet-700">
            <ShoppingBag className="h-3.5 w-3.5" />
            <strong className="font-bold tabular-nums">{tenantInfo.product_count}</strong>
            produit{tenantInfo.product_count > 1 ? "s" : ""} au catalogue
          </span>
          {tenantInfo.is_super_admin && (
            <>
              <span className="text-slate-300">·</span>
              <span className="inline-flex items-center gap-1 rounded-full bg-fuchsia-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-fuchsia-700 ring-1 ring-fuchsia-300">
                Super-admin · vue globale
              </span>
            </>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-1 border-b border-slate-200">
        {tabs.map((t) => {
          const Icon = t.icon;
          const active = tab === t.key;
          return (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ${
                active ? "border-sawali-blue text-sawali-blue" : "border-transparent text-slate-500 hover:text-slate-900"
              }`}
              data-testid={`cashier-tab-${t.key}`}>
              <Icon className={`h-4 w-4 ${active ? t.color : ""}`} />
              {t.label}
            </button>
          );
        })}
        {/* Iter38r-fix9o — Mobile Money payout shortcut for cashiers who are
            also Admin or Superviseur. Replaces the sidebar entry. */}
        {canPayout && (
          <Link
            to="/portal/payouts"
            className="ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white shadow-sm transition self-center"
            data-testid="cash-payout-link"
            title="Décaisser un salaire ou une avance via Mobile Money"
          >
            <Banknote className="h-3.5 w-3.5" />
            Payer (Mobile Money)
          </Link>
        )}
      </div>

      {tab === "receipts" && <ReceiptsTab businessClients={businessClients} paymentMethods={paymentMethods} refreshClients={refresh} />}
      {tab === "invoices" && <InvoicesTab businessClients={businessClients} products={products} paymentMethods={paymentMethods} refreshClients={refresh} />}
      {tab === "expenses" && <ExpensesTab isAdmin={isAdmin} />}
      {tab === "catalog" && (
        <CrudTab title="Catalogue produits/services" icon={ShoppingBag} color="text-violet-600"
          listPath="/admin/products" createPath="/admin/products" deletePath="/admin/products"
          dataTestId="cashier-products-tab"
          extraHeaderButton={({ onRefresh }) => <CsvImportButton resourceKind="products" onSuccess={onRefresh} />}
          formInitial={{ sku: "", name: "", description: "", category: "", unit: "pièce", unit_price_ht: 0, tva_pct: 18, stock: null, image_url: "", active: true, is_public: false }}
          fields={[
            { key: "sku", label: "Référence (SKU) — auto-générée", type: "readonly" },
            { key: "name", label: "Nom (MAJUSCULES auto)", required: true, uppercase: true, full: true },
            { key: "category", label: "Catégorie", type: "remoteSelect", sourcePath: "/cashier/product-categories" },
            { key: "unit", label: "Unité", type: "select", options: [
              { value: "pièce", label: "Pièce" }, { value: "heure", label: "Heure" }, { value: "jour", label: "Jour" }, { value: "forfait", label: "Forfait" },
            ]},
            { key: "unit_price_ht", label: "Prix unitaire HT", type: "number", required: true },
            { key: "tva_pct", label: "TVA %", type: "number" },
            { key: "stock", label: "Stock (optionnel)", type: "number" },
            { key: "image_url", label: "Icône / Image produit", type: "imageUpload", full: true },
            { key: "description", label: "Description", type: "textarea", full: true },
            { key: "active", label: "Actif", type: "checkbox" },
            { key: "is_public", label: "Exporter au catalogue public", type: "checkbox", checkboxLabel: "Visible dans le futur catalogue e-commerce" },
          ]} />
      )}
      {tab === "business" && (
        <CrudTab title="Clients en compte" icon={Building2} color="text-amber-600"
          listPath="/admin/business-clients" createPath="/admin/business-clients" deletePath="/admin/business-clients"
          dataTestId="cashier-bc-tab"
          extraHeaderButton={({ onRefresh }) => <CsvImportButton resourceKind="business-clients" onSuccess={onRefresh} />}
          formInitial={{ name: "", legal_form: "", nif: "", ifu: "", rccm: "", phone: "", whatsapp: "", email: "", billing_address: "", shipping_address: "", notes: "", auto_relance_enabled: false, relance_channel: "whatsapp" }}
          fields={[
            { key: "name", label: "Raison sociale / Nom", required: true, full: true },
            { key: "legal_form", label: "Forme juridique", type: "remoteSelect", sourcePath: "/cashier/legal-forms" },
            { key: "nif", label: "NIF" },
            { key: "ifu", label: "IFU" },
            { key: "rccm", label: "RCCM" },
            { key: "phone", label: "Téléphone (voix/SMS)" },
            { key: "whatsapp", label: "WhatsApp (si différent du téléphone)" },
            { key: "email", label: "Email" },
            { key: "billing_address", label: "Adresse de facturation", type: "textarea", full: true },
            { key: "shipping_address", label: "Adresse de livraison", type: "textarea", full: true },
            { key: "notes", label: "Notes", type: "textarea", full: true },
            { key: "auto_relance_enabled", label: "🔔 Relance automatique des impayés", type: "checkbox", full: true },
          ]} />
      )}
      {tab === "payment" && (
        <CrudTab title="Modes de paiement" icon={CreditCard} color="text-rose-600"
          listPath="/payment-methods" createPath="/admin/payment-methods" deletePath="/admin/payment-methods"
          dataTestId="cashier-pm-tab"
          formInitial={{ label: "", kind: "electronic", active: true, sort_order: 0 }}
          fields={[
            { key: "label", label: "Libellé", required: true, full: true },
            { key: "kind", label: "Catégorie", type: "select", options: [
              { value: "cash", label: "Espèces" }, { value: "check", label: "Chèque" }, { value: "electronic", label: "Monnaie électronique" },
            ]},
            { key: "sort_order", label: "Ordre d'affichage", type: "number" },
            { key: "active", label: "Actif", type: "checkbox" },
          ]} />
      )}
      {tab === "legal_forms" && (
        <CrudTab title="Formes juridiques" icon={FileText} color="text-slate-600"
          listPath="/cashier/legal-forms" createPath="/admin/legal-forms" deletePath="/admin/legal-forms"
          dataTestId="cashier-legal-forms-tab"
          formInitial={{ label: "" }}
          fields={[
            { key: "label", label: "Libellé (ex: SARL, SA, SAS, EI, ASSO…)", required: true, full: true },
          ]} />
      )}
      {tab === "categories" && (
        <CrudTab title="Catégories de produits" icon={Tag} color="text-violet-500"
          listPath="/cashier/product-categories" createPath="/admin/product-categories" deletePath="/admin/product-categories"
          dataTestId="cashier-categories-tab"
          formInitial={{ label: "" }}
          fields={[
            { key: "label", label: "Libellé (ex: Logiciel, Service, Matériel, Formation…)", required: true, full: true },
          ]} />
      )}
      {tab === "auto_relance" && <AutoRelanceTab />}
    </div>
  );
}
