/*
 * Iter36u — Printable invoice / proforma page.
 */
import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { Printer, MessageCircle, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { LOGO_URL } from "@/lib/brand";
import WaStatusBadge from "@/components/WaStatusBadge";

const FCFA = (n) => Number(n || 0).toLocaleString("fr-FR", { maximumFractionDigits: 0 });

export default function InvoicePrint() {
  const { id } = useParams();
  const [i, setI] = useState(null);
  const [qrBlob, setQrBlob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const resp = await apiClient.get(`/cashier/invoices/${id}`);
        setI(resp.data);
        const qr = await apiClient.get(`/cashier/invoices/${id}/qr.png`, { responseType: "blob" });
        setQrBlob(URL.createObjectURL(qr.data));
      } catch { /* noop */ } finally { setLoading(false); }
    })();
    return () => { if (qrBlob) URL.revokeObjectURL(qrBlob); /* eslint-disable-next-line */ };
  }, [id]);

  if (loading) return <div className="p-8 text-center"><Loader2 className="h-6 w-6 animate-spin mx-auto" /></div>;
  if (!i) return <div className="p-8 text-center text-rose-500">Document introuvable</div>;

  const print = () => window.print();
  // Iter36v — Envoi direct WhatsApp (Cloud API) avec fallback wa.me
  const sendWhatsApp = async () => {
    if (!i || sending) return;
    setSending(true);
    try {
      const resp = await apiClient.post(`/cashier/invoices/${i.id}/send-whatsapp`, {});
      if (resp.data?.ok) {
        toast.success(`Document envoyé sur WhatsApp à ${resp.data.to}`);
      } else {
        toast.warning(resp.data?.error || "Envoi WhatsApp impossible — ouverture du lien de secours");
        if (resp.data?.fallback_wa_link) window.open(resp.data.fallback_wa_link, "_blank");
      }
      // Iter38e (B.1) — Refresh invoice to update the status badge
      try {
        const refreshed = await apiClient.get(`/cashier/invoices/${i.id}`);
        setI(refreshed.data);
      } catch { /* noop */ }
    } catch (err) {
      const detail = err?.response?.data?.detail || "Erreur d'envoi WhatsApp";
      toast.error(typeof detail === "string" ? detail : "Erreur d'envoi");
      const label = i.kind === "proforma" ? "Proforma" : "Facture";
      const msg = `${label} ${i.number} — ${FCFA(i.net_to_pay)} FCFA — ${i.qr_url}`;
      window.open(`https://wa.me/?text=${encodeURIComponent(msg)}`, "_blank");
    } finally { setSending(false); }
  };

  const kindLabel = i.kind === "proforma" ? "Facture proforma" : "Facture";
  const statusLabels = { issued: "ÉMISE", paid: "RÉGLÉE", cancelled: "ANNULÉE" };
  const statusColors = { issued: "text-slate-600", paid: "text-emerald-600", cancelled: "text-rose-600" };

  return (
    <div className="min-h-screen bg-slate-100 print:bg-white p-4 print:p-0">
      <div className="max-w-3xl mx-auto mb-4 flex items-center justify-end gap-2 print:hidden">
        {/* Iter38e (B.1) — Last WhatsApp send status badge */}
        <WaStatusBadge doc={i} />
        <button onClick={sendWhatsApp} disabled={sending} className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 text-white px-3 py-1.5 text-sm font-medium" data-testid="invoice-send-wa-btn">
          {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <MessageCircle className="h-4 w-4" />}
          {sending ? "Envoi…" : "Envoyer par WhatsApp"}
        </button>
        <button onClick={print} className="inline-flex items-center gap-1.5 rounded-lg bg-sawali-blue hover:bg-sawali-blue-light text-white px-3 py-1.5 text-sm font-medium" data-testid="invoice-print-btn">
          <Printer className="h-4 w-4" /> Imprimer / PDF
        </button>
      </div>

      <div className="relative max-w-3xl mx-auto bg-white shadow-lg print:shadow-none ring-1 ring-slate-200 print:ring-0 p-8 overflow-hidden">
        {/* Watermark */}
        <div aria-hidden className="absolute inset-0 pointer-events-none flex items-center justify-center" style={{ opacity: 0.04 }}>
          <span className="text-[140px] font-display font-bold text-slate-900 rotate-[-25deg] whitespace-nowrap">SAWALI SMART SYSTEMS</span>
        </div>

        <div className="relative">
          {/* Header — Iter37b: tenant_snapshot from user's Client Lié */}
          <div className="flex items-start justify-between gap-4 pb-4 border-b-2 border-slate-900">
            <div className="flex items-center gap-3">
              <img src={(i.tenant_snapshot && i.tenant_snapshot.logo_url) || LOGO_URL} alt={(i.tenant_snapshot && i.tenant_snapshot.name) || "SAWALI"} className="h-14 w-auto" />
              <div>
                <p className="font-display font-bold text-lg text-slate-900">{(i.tenant_snapshot && i.tenant_snapshot.name) || "SAWALI SMART SYSTEMS"}</p>
                <p className="text-xs text-slate-600">{(i.tenant_snapshot && i.tenant_snapshot.billing_address) || "Société d'ingénierie logicielle"}</p>
                {(i.tenant_snapshot && i.tenant_snapshot.phone) && <p className="text-[11px] text-slate-500">📞 {i.tenant_snapshot.phone}</p>}
              </div>
            </div>
            <div className="text-right">
              <p className="text-[10px] uppercase tracking-wider text-slate-500">{kindLabel}</p>
              <p className="text-2xl font-display font-bold text-slate-900 font-mono">{i.number}</p>
              <p className={`text-[10px] font-bold ${statusColors[i.status]}`}>{statusLabels[i.status]}</p>
              {qrBlob && <img src={qrBlob} alt="QR" className="w-20 h-20 ml-auto mt-1 ring-1 ring-slate-200" />}
            </div>
          </div>

          {/* Addresses */}
          <div className="grid grid-cols-2 gap-4 mt-4 text-sm">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Facturé à</p>
              <p className="font-bold text-slate-900">{i.business_client_snapshot?.name}</p>
              {i.business_client_snapshot?.billing_address && (
                <p className="text-xs text-slate-600 whitespace-pre-line">{i.business_client_snapshot.billing_address}</p>
              )}
              {i.business_client_snapshot?.nif && <p className="text-xs text-slate-500 mt-0.5">NIF : {i.business_client_snapshot.nif}</p>}
              {i.business_client_snapshot?.rccm && <p className="text-xs text-slate-500">RCCM : {i.business_client_snapshot.rccm}</p>}
            </div>
            <div className="text-right">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Date d'émission</p>
              <p className="text-sm font-medium text-slate-800">{new Date(i.created_at).toLocaleDateString("fr-FR")}</p>
              {i.due_date && <>
                <p className="text-[10px] uppercase tracking-wider text-slate-500 mt-2 mb-1">Échéance</p>
                <p className="text-sm">{i.due_date}</p>
              </>}
            </div>
          </div>
          {i.business_client_snapshot?.shipping_address && i.business_client_snapshot.shipping_address !== i.business_client_snapshot.billing_address && (
            <div className="mt-3 text-sm">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-0.5">Adresse de livraison</p>
              <p className="text-xs text-slate-600 whitespace-pre-line">{i.business_client_snapshot.shipping_address}</p>
            </div>
          )}

          {/* Items table */}
          <div className="mt-6 rounded ring-1 ring-slate-200 overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-slate-900 text-white">
                <tr>
                  <th className="text-left px-2 py-2">Désignation</th>
                  <th className="text-right px-2 py-2">Qté</th>
                  <th className="text-right px-2 py-2">Unité</th>
                  <th className="text-right px-2 py-2">P.U. HT</th>
                  <th className="text-right px-2 py-2">TVA</th>
                  <th className="text-right px-2 py-2">Total HT</th>
                </tr>
              </thead>
              <tbody>
                {(i.items || []).map((it, idx) => (
                  <tr key={idx} className="border-b border-slate-100">
                    <td className="px-2 py-1.5">{it.label}</td>
                    <td className="px-2 py-1.5 text-right font-mono">{it.quantity}</td>
                    <td className="px-2 py-1.5 text-right text-slate-500">{it.unit || ""}</td>
                    <td className="px-2 py-1.5 text-right font-mono">{FCFA(it.unit_price_ht)}</td>
                    <td className="px-2 py-1.5 text-right font-mono">{it.tva_pct}%</td>
                    <td className="px-2 py-1.5 text-right font-mono">{FCFA(it.line_total_ht)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Totals */}
          <div className="mt-3 grid grid-cols-2 gap-4">
            <div className="text-xs text-slate-600">
              {i.notes && (<>
                <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Notes</p>
                <p className="whitespace-pre-line">{i.notes}</p>
              </>)}
            </div>
            <div className="text-right text-sm font-mono space-y-1">
              <div className="flex justify-between"><span className="text-slate-500">Sous-total HT</span><span>{FCFA(i.subtotal_ht)} FCFA</span></div>
              <div className="flex justify-between"><span className="text-slate-500">TVA</span><span>{FCFA(i.total_tva)} FCFA</span></div>
              <div className="flex justify-between font-bold"><span>Total TTC</span><span>{FCFA(i.total_ttc)} FCFA</span></div>
              {i.discount_amount > 0 && (
                <div className="flex justify-between text-rose-600"><span>Remise</span><span>-{FCFA(i.discount_amount)} FCFA</span></div>
              )}
              <div className="flex justify-between text-lg font-bold text-sawali-blue border-t-2 border-slate-900 pt-2 mt-2">
                <span>Net à payer</span><span>{FCFA(i.net_to_pay)} FCFA</span>
              </div>
              <p className="text-xs italic text-slate-600 text-right">({i.amount_in_words})</p>
            </div>
          </div>

          {/* Footer */}
          <div className="mt-10 pt-4 border-t border-slate-200 text-xs text-slate-500 flex items-end justify-between">
            <div>
              <p>Vérifiez l'authenticité en scannant le QR code.</p>
              <p className="mt-1 text-[10px]">Émis par : <span className="font-medium text-slate-700">{i.created_by_name}</span></p>
            </div>
            <div className="text-right">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Signature</p>
              <div className="w-40 h-12 border-b border-slate-400" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
