/*
  PortfolioInvoices — lot 27 : « Bilans à facturer » (admin et Superviseur).

  Tous les bilans « Formulaires & Sondages WhatsApp » des clients, générés par
  l'admin dans la page SMART Communications de chaque client :
    - onglets À facturer / Facturés / Tous ;
    - PDF du bilan, lien à transmettre au client ;
    - Créer la facture (ou une proforma) : le Superviseur choisit, pour chaque
      facture, d'appliquer ou non la TVA ; la facture arrive dans la Caisse/Facturation.
*/
import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Receipt, FileText, Link2, CheckCircle2 } from "lucide-react";
import InvoiceTvaDialog from "@/components/InvoiceTvaDialog";

const money = (v) => `${Math.round(v || 0).toLocaleString("fr-FR")} FCFA`;
const d = (iso) => (iso ? new Date(iso).toLocaleDateString("fr-FR") : "—");

export default function PortfolioInvoices() {
  const [status, setStatus] = useState("to_invoice");
  const [items, setItems] = useState(null);
  const [dialog, setDialog] = useState(null);        // {report, kind}

  const load = useCallback(async () => {
    try { setItems((await apiClient.get("/admin/portfolio-reports", { params: { status } })).data.items || []); }
    catch (e) { toast.error(e?.response?.data?.detail || "Chargement impossible"); setItems([]); }
  }, [status]);
  useEffect(() => { load(); }, [load]);

  const pdf = async (r) => {
    try { window.open(URL.createObjectURL((await apiClient.get(`/admin/portfolio-reports/${r.id}/pdf`, { responseType: "blob" })).data), "_blank"); }
    catch { toast.error("PDF indisponible"); }
  };
  const copyLink = async (r) => {
    const url = `${r.base_url || window.location.origin}/api/public/portfolio-report/${r.token}`;
    try { await navigator.clipboard.writeText(url); toast.success("Lien du bilan copié"); } catch { window.prompt("Lien du bilan :", url); }
  };

  return (
    <div className="max-w-6xl space-y-5" data-testid="portfolio-invoices-page">
      <div>
        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Facturation</p>
        <h1 className="text-2xl font-display font-bold flex items-center gap-2"><Receipt className="h-5 w-5 text-sawali-blue" /> Bilans à facturer</h1>
        <p className="text-sm text-slate-500 mt-1">Bilans Formulaires & Sondages WhatsApp des clients. Pour chaque facture, vous choisissez d'appliquer ou non la TVA.</p>
      </div>
      <div className="flex gap-2 border-b border-slate-200">
        {[["to_invoice", "À facturer"], ["invoiced", "Facturés"], ["", "Tous"]].map(([k, l]) => (
          <button key={k || "all"} onClick={() => setStatus(k)} data-testid={`pi-tab-${k || "all"}`}
            className={`px-3 py-2 text-sm border-b-2 ${status === k ? "border-sawali-blue text-sawali-blue font-semibold" : "border-transparent text-slate-500 hover:text-slate-900"}`}>{l}</button>
        ))}
      </div>
      {items === null ? <p className="text-sm text-slate-500">Chargement…</p> : !items.length ? (
        <p className="rounded-xl border-2 border-dashed border-slate-200 p-8 text-center text-sm text-slate-500">
          {status === "to_invoice" ? "Aucun bilan en attente de facturation." : "Aucun bilan."}
        </p>
      ) : (
        <div className="rounded-xl bg-white ring-1 ring-slate-200 overflow-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-[11px] uppercase text-slate-500">
              <tr><th className="px-3 py-2 text-left">Client</th><th className="text-left">Période</th><th className="text-right">Total HT</th>
                <th className="text-right">TTC (si TVA)</th><th className="text-left px-3">Facture</th><th className="px-3" /></tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id} className="border-t border-slate-100" data-testid={`pi-row-${r.id}`}>
                  <td className="px-3 py-2 font-medium text-slate-800">{r.client_name}</td>
                  <td className="text-xs text-slate-600">du {d(r.date_from)} au {d(r.date_to)}</td>
                  <td className="text-right tabular-nums">{money(r.total_ht)}</td>
                  <td className="text-right tabular-nums text-slate-500">{money(r.total_ttc)}</td>
                  <td className="px-3 text-xs">
                    {r.invoice_number ? (
                      <span className="inline-flex items-center gap-1 text-emerald-700"><CheckCircle2 className="h-3.5 w-3.5" />
                        {r.invoice_number} · {money(r.invoiced_amount)} {r.invoiced_with_tva === false ? "(sans TVA)" : r.invoiced_with_tva ? "(TVA incluse)" : ""}</span>
                    ) : <span className="text-amber-600">à facturer</span>}
                  </td>
                  <td className="px-3 whitespace-nowrap text-right space-x-1">
                    <button onClick={() => pdf(r)} className="inline-flex items-center gap-1 text-xs rounded ring-1 ring-slate-300 px-2 py-1 hover:bg-slate-50"><FileText className="h-3.5 w-3.5" /> PDF</button>
                    <button onClick={() => copyLink(r)} className="inline-flex items-center gap-1 text-xs rounded ring-1 ring-slate-300 px-2 py-1 hover:bg-slate-50"><Link2 className="h-3.5 w-3.5" /></button>
                    {!r.invoice_number && (
                      <button onClick={() => setDialog({ report: r, kind: "invoice" })} disabled={!r.total_ht} data-testid={`pi-invoice-${r.id}`}
                        className="inline-flex items-center gap-1 text-xs rounded bg-emerald-600 text-white px-2 py-1 hover:bg-emerald-700 disabled:opacity-40"><Receipt className="h-3.5 w-3.5" /> Facturer</button>
                    )}
                    <button onClick={() => setDialog({ report: r, kind: "proforma" })} disabled={!r.total_ht} className="text-xs text-slate-600 hover:underline disabled:opacity-40">Proforma</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-slate-500">Les factures créées apparaissent dans <Link to="/portal/billing" className="text-sawali-blue hover:underline">Caisse/Facturation</Link>.
        Les tarifs et le prompt de l'analyse IA se règlent par l'admin dans la page SMART Communications de chaque client.</p>
      {dialog && <InvoiceTvaDialog report={dialog.report} kind={dialog.kind} onClose={() => setDialog(null)} onDone={() => { setDialog(null); load(); }} />}
    </div>
  );
}
