/*
 * Iter36u — Printable receipt page (HTML, ready for window.print()).
 *
 * Renders a single receipt with:
 *   - SAWALI logo header
 *   - Business client info
 *   - Amount (figures + spelled-out French)
 *   - Payment method & reference
 *   - Cashier name
 *   - QR code (top-right) for public verification
 *   - Repeated watermark "SAWALI SMART SYSTEMS"
 */
import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { Printer, MessageCircle, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { LOGO_URL } from "@/lib/brand";
import WaStatusBadge from "@/components/WaStatusBadge";

const FCFA = (n) => Number(n || 0).toLocaleString("fr-FR", { maximumFractionDigits: 0 });
const BACKEND = process.env.REACT_APP_BACKEND_URL || "";

export default function ReceiptPrint() {
  const { id } = useParams();
  const [r, setR] = useState(null);
  const [qrBlob, setQrBlob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const resp = await apiClient.get(`/cashier/receipts/${id}`);
        setR(resp.data);
        const qr = await apiClient.get(`/cashier/receipts/${id}/qr.png`, { responseType: "blob" });
        setQrBlob(URL.createObjectURL(qr.data));
      } catch { /* noop */ } finally { setLoading(false); }
    })();
    return () => { if (qrBlob) URL.revokeObjectURL(qrBlob); /* eslint-disable-next-line */ };
  }, [id]);

  const print = () => window.print();

  // Iter36v — Envoi direct WhatsApp (Cloud API) avec fallback wa.me
  const sendWhatsApp = async () => {
    if (!r || sending) return;
    setSending(true);
    try {
      const resp = await apiClient.post(`/cashier/receipts/${r.id}/send-whatsapp`, {});
      if (resp.data?.ok) {
        toast.success(`Reçu envoyé sur WhatsApp à ${resp.data.to}`);
      } else {
        // Backend returned 200 with ok=false + fallback link (Meta refused)
        toast.warning(resp.data?.error || "Envoi WhatsApp impossible — ouverture du lien de secours");
        if (resp.data?.fallback_wa_link) window.open(resp.data.fallback_wa_link, "_blank");
      }
      // Iter38e (B.1) — Refresh receipt to update the status badge
      try {
        const refreshed = await apiClient.get(`/cashier/receipts/${r.id}`);
        setR(refreshed.data);
      } catch { /* noop */ }
    } catch (err) {
      const detail = err?.response?.data?.detail || "Erreur d'envoi WhatsApp";
      toast.error(typeof detail === "string" ? detail : "Erreur d'envoi");
      // Last-chance fallback: open generic wa.me link
      const msg = `Reçu ${r.number} — ${FCFA(r.amount)} FCFA — ${r.qr_url}`;
      window.open(`https://wa.me/?text=${encodeURIComponent(msg)}`, "_blank");
    } finally { setSending(false); }
  };

  if (loading) return <div className="p-8 text-center"><Loader2 className="h-6 w-6 animate-spin mx-auto" /></div>;
  if (!r) return <div className="p-8 text-center text-rose-500">Reçu introuvable</div>;

  return (
    <div className="min-h-screen bg-slate-100 print:bg-white p-4 print:p-0">
      {/* Action bar (hidden when printing) */}
      <div className="max-w-3xl mx-auto mb-4 flex items-center justify-end gap-2 print:hidden">
        {/* Iter38e (B.1) — Last WhatsApp send status badge */}
        <WaStatusBadge doc={r} />
        <button onClick={sendWhatsApp} disabled={sending} className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 text-white px-3 py-1.5 text-sm font-medium" data-testid="receipt-send-wa-btn">
          {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <MessageCircle className="h-4 w-4" />}
          {sending ? "Envoi…" : "Envoyer par WhatsApp"}
        </button>
        <button onClick={print} className="inline-flex items-center gap-1.5 rounded-lg bg-sawali-blue hover:bg-sawali-blue-light text-white px-3 py-1.5 text-sm font-medium" data-testid="receipt-print-btn">
          <Printer className="h-4 w-4" /> Imprimer / PDF
        </button>
      </div>

      {/* A4-like sheet */}
      <div className="relative max-w-3xl mx-auto bg-white shadow-lg print:shadow-none ring-1 ring-slate-200 print:ring-0 p-8 overflow-hidden" id="receipt-sheet">
        {/* Watermark */}
        <div aria-hidden className="absolute inset-0 pointer-events-none flex items-center justify-center" style={{ opacity: 0.05 }}>
          <span className="text-[120px] font-display font-bold text-slate-900 rotate-[-25deg] whitespace-nowrap">SAWALI SMART SYSTEMS</span>
        </div>

        <div className="relative">
          {/* Header — Iter37b: use tenant_snapshot (Client Lié) when available */}
          <div className="flex items-start justify-between gap-4 pb-4 border-b-2 border-slate-900">
            <div className="flex items-center gap-3">
              <img src={(r.tenant_snapshot && r.tenant_snapshot.logo_url) || LOGO_URL} alt={(r.tenant_snapshot && r.tenant_snapshot.name) || "SAWALI"} className="h-14 w-auto" />
              <div>
                <p className="font-display font-bold text-lg text-slate-900">{(r.tenant_snapshot && r.tenant_snapshot.name) || "SAWALI SMART SYSTEMS"}</p>
                <p className="text-xs text-slate-600">{(r.tenant_snapshot && r.tenant_snapshot.billing_address) || "Société d'ingénierie logicielle"}</p>
                {(r.tenant_snapshot && r.tenant_snapshot.phone) && <p className="text-[11px] text-slate-500">📞 {r.tenant_snapshot.phone}</p>}
              </div>
            </div>
            <div className="text-right">
              <p className="text-[10px] uppercase tracking-wider text-slate-500">Reçu d'encaissement</p>
              <p className="text-2xl font-display font-bold text-slate-900 font-mono">{r.number}</p>
              {qrBlob && <img src={qrBlob} alt="QR" className="w-20 h-20 ml-auto mt-1 ring-1 ring-slate-200" />}
            </div>
          </div>

          {/* Client + Date */}
          <div className="grid grid-cols-2 gap-4 mt-6">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Reçu de</p>
              <p className="font-bold text-slate-900">{r.business_client_snapshot?.name}</p>
              {r.business_client_snapshot?.billing_address && (
                <p className="text-xs text-slate-600 whitespace-pre-line mt-0.5">{r.business_client_snapshot.billing_address}</p>
              )}
              {r.business_client_snapshot?.nif && <p className="text-xs text-slate-500 mt-0.5">NIF : {r.business_client_snapshot.nif}</p>}
            </div>
            <div className="text-right">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Date</p>
              <p className="text-sm font-medium text-slate-800">{new Date(r.issued_at).toLocaleString("fr-FR")}</p>
            </div>
          </div>

          {/* Amount block */}
          <div className="mt-6 p-5 bg-emerald-50 ring-1 ring-emerald-200 rounded-lg">
            <p className="text-[10px] uppercase tracking-wider text-emerald-700 mb-1">Montant encaissé</p>
            <p className="text-4xl font-display font-bold text-emerald-900 font-mono">{FCFA(r.amount)} FCFA</p>
            <p className="text-sm text-slate-700 italic mt-1">
              ({r.amount_in_words})
            </p>
          </div>

          {/* Details grid */}
          <div className="grid grid-cols-2 gap-x-6 gap-y-3 mt-6 text-sm">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-500">Motif</p>
              <p className="text-slate-800">{r.motif}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-500">Mode de paiement</p>
              <p className="text-slate-800">{r.payment_method_label}</p>
            </div>
            {r.payment_reference && (
              <div className="col-span-2">
                <p className="text-[10px] uppercase tracking-wider text-slate-500">Référence</p>
                <p className="text-slate-800 font-mono">{r.payment_reference}</p>
              </div>
            )}
            {r.beneficiary_name && r.beneficiary_name !== r.business_client_snapshot?.name && (
              <div>
                <p className="text-[10px] uppercase tracking-wider text-slate-500">Bénéficiaire</p>
                <p className="text-slate-800">{r.beneficiary_name}</p>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="mt-12 pt-4 border-t border-slate-200 flex items-end justify-between">
            <div className="text-xs text-slate-500">
              <p>Vérifiez l'authenticité de ce reçu en scannant le QR code.</p>
              <p className="mt-1 text-[10px]">Délivré par : <span className="font-medium text-slate-700">{r.cashier_name}</span></p>
            </div>
            <div className="text-right">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Signature & cachet</p>
              <div className="w-40 h-12 border-b border-slate-400" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
