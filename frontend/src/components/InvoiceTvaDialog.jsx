/*
  InvoiceTvaDialog — lot 27 : création de la facture (ou proforma) d'un bilan
  « Formulaires & Sondages ». Le Superviseur (ou l'admin) décide, POUR CETTE
  FACTURE, s'il applique la TVA : les montants HT, TVA et TTC sont affichés
  pour les deux cas avant de valider.

  Props : report {id, client_name, total_ht, total_tva, tva_pct}, kind ("invoice" | "proforma"),
          onClose(), onDone(résultat du serveur)
*/
import React, { useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Receipt, X, Loader2 } from "lucide-react";

const money = (v) => `${Math.round(v || 0).toLocaleString("fr-FR")} FCFA`;

export default function InvoiceTvaDialog({ report, kind = "invoice", onClose, onDone }) {
  const rate = Number(report.tva_pct || 18);
  const [applyTva, setApplyTva] = useState(rate > 0);
  const [busy, setBusy] = useState(false);
  const ht = report.total_ht || 0;
  const tva = applyTva ? Math.round(ht * rate) / 100 : 0;

  const create = async () => {
    setBusy(true);
    try {
      const r = await apiClient.post(`/admin/portfolio-reports/${report.id}/invoice`, { kind, apply_tva: applyTva });
      toast.success(`${kind === "invoice" ? "Facture" : "Proforma"} ${r.data.invoice.number} créée ${applyTva ? "avec" : "sans"} TVA — ${money(r.data.invoice.net_to_pay)}`);
      onDone?.(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Facture impossible");
    } finally {
      setBusy(false);
    }
  };

  const choice = (active) => `flex-1 rounded-xl ring-1 px-4 py-3 text-left transition ${active ? "ring-2 ring-emerald-500 bg-emerald-50" : "ring-slate-200 hover:ring-slate-300"}`;
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/40" onClick={(e) => e.target === e.currentTarget && onClose?.()}>
      <div className="w-full max-w-md rounded-2xl bg-white p-5 shadow-2xl space-y-4" data-testid="invoice-tva-dialog">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-xs uppercase tracking-wider text-slate-500">{kind === "invoice" ? "Nouvelle facture" : "Nouvelle proforma"}</p>
            <h3 className="font-semibold text-slate-900">{report.client_name}</h3>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-slate-100" aria-label="Fermer"><X className="h-5 w-5" /></button>
        </div>
        <p className="text-sm font-medium text-slate-800">Appliquer la TVA sur cette facture ?</p>
        <div className="flex gap-2">
          <button onClick={() => setApplyTva(true)} className={choice(applyTva)} data-testid="tva-yes">
            <p className="font-semibold text-sm">Oui, TVA {rate || 18} %</p>
            <p className="text-[11px] text-slate-500">{money(ht + Math.round(ht * (rate || 18)) / 100)} TTC</p>
          </button>
          <button onClick={() => setApplyTva(false)} className={choice(!applyTva)} data-testid="tva-no">
            <p className="font-semibold text-sm">Non, sans TVA</p>
            <p className="text-[11px] text-slate-500">{money(ht)} net</p>
          </button>
        </div>
        <table className="w-full text-sm">
          <tbody>
            <tr><td className="text-slate-600">Total HT</td><td className="text-right tabular-nums">{money(ht)}</td></tr>
            <tr><td className="text-slate-600">TVA {applyTva ? `${rate || 18} %` : "(non appliquée)"}</td><td className="text-right tabular-nums">{money(tva)}</td></tr>
            <tr className="font-bold border-t border-slate-200"><td className="pt-1">Net à payer</td><td className="pt-1 text-right tabular-nums">{money(ht + tva)}</td></tr>
          </tbody>
        </table>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100">Annuler</button>
          <button onClick={create} disabled={busy} data-testid="tva-confirm"
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 text-white px-4 py-2 text-sm font-semibold hover:bg-emerald-700 disabled:opacity-50">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Receipt className="h-4 w-4" />} Créer {kind === "invoice" ? "la facture" : "la proforma"}
          </button>
        </div>
      </div>
    </div>
  );
}
