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
} from "lucide-react";
import { Link } from "react-router-dom";

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
// Receipts tab
// =====================================================================
function ReceiptsTab({ businessClients, paymentMethods, refreshClients }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    business_client_id: "", beneficiary_name: "", amount: "",
    motif: "", payment_method_id: "", payment_reference: "",
  });
  const [submitting, setSubmitting] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/cashier/receipts", { params: { limit: 100 } });
      setItems(r.data || []);
    } catch { setItems([]); } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

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
              <label className="block text-xs font-medium text-slate-700 mb-1">Client en compte *</label>
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
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 px-1.5 py-0.5" title={`Envoyé à ${r.whatsapp_to || ""}`}>
                        <CheckCircle2 className="h-3 w-3" /> {fmtDt(r.whatsapp_sent_at)}
                      </span>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Link to={`/portal/cash/receipt/${r.id}`} target="_blank" className="inline-flex items-center gap-1 text-sawali-blue hover:underline text-xs"
                      data-testid={`receipt-print-${r.id}`}>
                      <Printer className="h-3.5 w-3.5" /> Imprimer
                    </Link>
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
// Invoices tab
// =====================================================================
function InvoicesTab({ businessClients, products, paymentMethods }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
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

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/cashier/invoices", { params: { limit: 100, ...filter } });
      setItems(r.data || []);
    } catch { setItems([]); } finally { setLoading(false); }
  };
  const refreshOverdue = async () => {
    try {
      const r = await apiClient.get("/cashier/overdue/count", { params: { grace_days: 30 } });
      setOverdueCount(r.data?.count || 0);
    } catch { /* noop */ }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [filter.kind, filter.status]);
  useEffect(() => { refreshOverdue(); }, []);

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

  return (
    <div className="space-y-4" data-testid="cashier-invoices-tab">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
          <Receipt className="h-5 w-5 text-sawali-blue" /> Factures & Proformas
        </h2>
        <div className="flex items-center gap-2">
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
              <label className="block text-xs font-medium text-slate-700 mb-1">Client en compte *</label>
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
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 px-1.5 py-0.5" title={`Envoyé à ${i.whatsapp_to || ""}`}>
                        <CheckCircle2 className="h-3 w-3" /> {fmtDt(i.whatsapp_sent_at)}
                      </span>
                    ) : (
                      <span className="text-slate-400">—</span>
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
                      <button onClick={() => cancel(i.id)} className="text-xs text-rose-500 hover:underline" title="Annuler">
                        <Trash2 className="h-3.5 w-3.5 inline" />
                      </button>
                    )}
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
// Generic CRUD tab (clients en compte, products, payment methods)
// =====================================================================
function CrudTab({ title, icon: Icon, color, listPath, createPath, deletePath, fields, formInitial, transformBeforeSubmit, dataTestId }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(formInitial);
  const [submitting, setSubmitting] = useState(false);

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
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
          <Icon className={`h-5 w-5 ${color}`} /> {title}
        </h2>
        <button onClick={() => { setEditing(null); setForm(formInitial); setShowForm((v) => !v); }}
          className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800 hover:bg-slate-900 text-white px-3 py-1.5 text-sm">
          <Plus className="h-4 w-4" /> Nouveau
        </button>
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
                ) : fld.type === "textarea" ? (
                  <textarea value={form[fld.key] || ""} onChange={(e) => setForm({ ...form, [fld.key]: e.target.value })}
                    rows={2} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                ) : fld.type === "checkbox" ? (
                  <label className="inline-flex items-center gap-2 text-sm pt-2">
                    <input type="checkbox" checked={!!form[fld.key]} onChange={(e) => setForm({ ...form, [fld.key]: e.target.checked })} />
                    {fld.checkboxLabel || fld.label}
                  </label>
                ) : (
                  <input type={fld.type || "text"} value={form[fld.key] ?? ""} onChange={(e) => {
                    const v = fld.type === "number" ? Number(e.target.value) : e.target.value;
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
// Main page
// =====================================================================
export default function CashBilling({ defaultTab = "receipts" }) {
  const { user } = useAuth();
  const [tab, setTab] = useState(defaultTab);
  const [businessClients, setBusinessClients] = useState([]);
  const [products, setProducts] = useState([]);
  const [paymentMethods, setPaymentMethods] = useState([]);

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

  const tabs = [
    { key: "receipts", label: "Caisse", icon: Banknote, color: "text-emerald-600" },
    { key: "invoices", label: "Facturation", icon: Receipt, color: "text-sawali-blue" },
    ...(isAdmin ? [
      { key: "catalog", label: "Catalogue", icon: ShoppingBag, color: "text-violet-600" },
      { key: "business", label: "Clients en compte", icon: Building2, color: "text-amber-600" },
      { key: "payment", label: "Modes de paiement", icon: CreditCard, color: "text-rose-600" },
    ] : []),
  ];

  return (
    <div className="space-y-4">
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
      </div>

      {tab === "receipts" && <ReceiptsTab businessClients={businessClients} paymentMethods={paymentMethods} refreshClients={refresh} />}
      {tab === "invoices" && <InvoicesTab businessClients={businessClients} products={products} paymentMethods={paymentMethods} />}
      {tab === "catalog" && (
        <CrudTab title="Catalogue produits/services" icon={ShoppingBag} color="text-violet-600"
          listPath="/admin/products" createPath="/admin/products" deletePath="/admin/products"
          dataTestId="cashier-products-tab"
          formInitial={{ sku: "", name: "", description: "", category: "", unit: "pièce", unit_price_ht: 0, tva_pct: 18, stock: null, image_url: "", active: true }}
          fields={[
            { key: "sku", label: "Référence (SKU)", required: true },
            { key: "name", label: "Nom", required: true },
            { key: "category", label: "Catégorie" },
            { key: "unit", label: "Unité", type: "select", options: [
              { value: "pièce", label: "Pièce" }, { value: "heure", label: "Heure" }, { value: "jour", label: "Jour" }, { value: "forfait", label: "Forfait" },
            ]},
            { key: "unit_price_ht", label: "Prix unitaire HT", type: "number", required: true },
            { key: "tva_pct", label: "TVA %", type: "number" },
            { key: "stock", label: "Stock (optionnel)", type: "number" },
            { key: "image_url", label: "URL image" },
            { key: "description", label: "Description", type: "textarea", full: true },
            { key: "active", label: "Actif", type: "checkbox" },
          ]} />
      )}
      {tab === "business" && (
        <CrudTab title="Clients en compte" icon={Building2} color="text-amber-600"
          listPath="/admin/business-clients" createPath="/admin/business-clients" deletePath="/admin/business-clients"
          dataTestId="cashier-bc-tab"
          formInitial={{ name: "", legal_form: "", nif: "", ifu: "", rccm: "", phone: "", email: "", billing_address: "", shipping_address: "", notes: "" }}
          fields={[
            { key: "name", label: "Raison sociale / Nom", required: true, full: true },
            { key: "legal_form", label: "Forme juridique (SARL, SA…)" },
            { key: "nif", label: "NIF" },
            { key: "ifu", label: "IFU" },
            { key: "rccm", label: "RCCM" },
            { key: "phone", label: "Téléphone" },
            { key: "email", label: "Email" },
            { key: "billing_address", label: "Adresse de facturation", type: "textarea", full: true },
            { key: "shipping_address", label: "Adresse de livraison", type: "textarea", full: true },
            { key: "notes", label: "Notes", type: "textarea", full: true },
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
    </div>
  );
}
