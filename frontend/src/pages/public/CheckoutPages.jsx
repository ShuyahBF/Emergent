// Iter38r-fix9n — Checkout success/cancel landing pages
// Iter38r-fix9o — Polling removed: the Stripe webhook is now the primary
// confirmation channel (server-side, signed). One lightweight fetch is
// enough to display the order status.
import React, { useEffect, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { CheckCircle2, XCircle, Loader2, ArrowLeft } from "lucide-react";
import { apiClient } from "@/lib/api";

export function CheckoutSuccess() {
  const [params] = useSearchParams();
  const orderId = params.get("order_id");
  const [order, setOrder] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!orderId) { setLoading(false); return; }
    apiClient.get(`/public/orders/${orderId}`)
      .then((r) => setOrder(r.data))
      .catch(() => setOrder(null))
      .finally(() => setLoading(false));
  }, [orderId]);


  return (
    <section className="min-h-screen bg-sawali-navy flex items-center justify-center p-6" data-testid="checkout-success-page">
      <div className="max-w-md w-full bg-sawali-navy-dark ring-1 ring-emerald-400/30 rounded-2xl p-8 text-center">
        {loading ? (
          <>
            <Loader2 className="h-16 w-16 mx-auto text-sawali-blue-light animate-spin" />
            <h1 className="font-display font-bold text-white text-xl mt-4">Confirmation en cours…</h1>
            <p className="text-slate-400 text-sm mt-2">Patientez quelques secondes.</p>
          </>
        ) : order?.status === "paid" ? (
          <>
            <CheckCircle2 className="h-16 w-16 mx-auto text-emerald-400" />
            <h1 className="font-display font-bold text-white text-2xl mt-4">Paiement confirmé !</h1>
            <p className="text-slate-300 text-sm mt-2">Votre commande <code className="text-emerald-300">{order.id.slice(0, 8)}</code> a bien été enregistrée.</p>
            <div className="mt-4 rounded-lg bg-white/5 p-3 text-left text-sm">
              <div className="flex justify-between text-slate-300"><span>Produit</span><strong className="text-white">{order.product_name} × {order.quantity}</strong></div>
              <div className="flex justify-between text-slate-300 mt-1"><span>Montant</span><strong className="text-white">{order.amount_xof?.toLocaleString("fr-FR")} XOF</strong></div>
            </div>
            <p className="text-xs text-slate-500 mt-4">Un email de confirmation a été envoyé à <strong className="text-slate-300">{order.customer_email || "votre adresse"}</strong>.</p>
          </>
        ) : (
          <>
            <Loader2 className="h-16 w-16 mx-auto text-amber-400" />
            <h1 className="font-display font-bold text-white text-xl mt-4">Paiement en attente</h1>
            <p className="text-slate-400 text-sm mt-2">Stripe traite votre paiement. Vous recevrez l'email de confirmation sous peu.</p>
          </>
        )}
        <Link to="/catalogue" className="inline-flex items-center gap-2 mt-6 text-sawali-blue-light hover:text-white text-sm">
          <ArrowLeft className="h-4 w-4" /> Retour au catalogue
        </Link>
      </div>
    </section>
  );
}

export function CheckoutCancel() {
  return (
    <section className="min-h-screen bg-sawali-navy flex items-center justify-center p-6" data-testid="checkout-cancel-page">
      <div className="max-w-md w-full bg-sawali-navy-dark ring-1 ring-rose-400/30 rounded-2xl p-8 text-center">
        <XCircle className="h-16 w-16 mx-auto text-rose-400" />
        <h1 className="font-display font-bold text-white text-2xl mt-4">Paiement annulé</h1>
        <p className="text-slate-400 text-sm mt-2">Aucun montant n'a été débité. Vous pouvez réessayer.</p>
        <Link to="/catalogue" className="inline-flex items-center gap-2 mt-6 text-sawali-blue-light hover:text-white text-sm">
          <ArrowLeft className="h-4 w-4" /> Retour au catalogue
        </Link>
      </div>
    </section>
  );
}
