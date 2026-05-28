/*
 * Iter38r — PawaPay Payment Page return handler.
 *
 * The customer is redirected here by PawaPay after they either pay or abandon
 * on the hosted page. We poll the deposit status every 3 s until we get a
 * final state (completed / failed) or until we hit 25 attempts (~75 s).
 */
import React, { useEffect, useState, useCallback } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { CheckCircle2, XCircle, Loader2, Clock, ArrowLeft } from "lucide-react";

const POLL_INTERVAL_MS = 3000;
const MAX_ATTEMPTS = 25;

export default function PaymentReturn() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const depositId = params.get("depositId") || params.get("deposit_id") || "";
  const [payment, setPayment] = useState(null);
  const [attempts, setAttempts] = useState(0);
  const [done, setDone] = useState(false);

  const refresh = useCallback(async () => {
    if (!depositId) return;
    try {
      const r = await apiClient.get(`/me/payments/${depositId}`);
      setPayment(r.data);
      if (["completed", "failed"].includes(r.data?.status)) setDone(true);
    } catch (err) {
      // 404 = unknown deposit, 403 = not yours → stop polling
      if ([403, 404].includes(err?.response?.status)) setDone(true);
    }
  }, [depositId]);

  useEffect(() => {
    if (!depositId || done) return;
    refresh();
    const t = setInterval(() => {
      setAttempts((a) => {
        if (a + 1 >= MAX_ATTEMPTS) { setDone(true); return a + 1; }
        refresh();
        return a + 1;
      });
    }, POLL_INTERVAL_MS);
    return () => clearInterval(t);
  }, [depositId, done, refresh]);

  const status = payment?.status || "pending";
  const apiStatus = payment?.api_status;
  const apiMessage = payment?.api_message;

  if (!depositId) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6">
        <div className="bg-white rounded-xl border border-slate-200 p-8 text-center max-w-md" data-testid="payment-return-missing">
          <XCircle className="w-12 h-12 text-rose-500 mx-auto mb-3" />
          <p className="text-slate-700">Identifiant de paiement manquant.</p>
          <button onClick={() => navigate("/portal")} className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm flex items-center gap-2 mx-auto">
            <ArrowLeft size={14} /> Retour au portail
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-6" data-testid="payment-return-page">
      <div className="bg-white rounded-2xl border border-slate-200 p-8 max-w-lg w-full shadow-lg">
        <div className="text-center mb-4">
          {status === "completed" ? (
            <CheckCircle2 className="w-16 h-16 text-emerald-500 mx-auto mb-2" data-testid="payment-status-icon" />
          ) : status === "failed" ? (
            <XCircle className="w-16 h-16 text-rose-500 mx-auto mb-2" data-testid="payment-status-icon" />
          ) : (
            <Loader2 className="w-16 h-16 text-blue-500 mx-auto mb-2 animate-spin" data-testid="payment-status-icon" />
          )}
          <h1 className="text-2xl font-bold text-slate-900">
            {status === "completed" ? "Paiement confirmé" :
             status === "failed" ? "Paiement échoué" :
             "Confirmation en cours…"}
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            {status === "completed" ? "Votre paiement a été reçu avec succès." :
             status === "failed" ? (apiMessage || "Le paiement n'a pas pu être finalisé.") :
             "Veuillez patienter le temps que PawaPay confirme la transaction côté opérateur mobile."}
          </p>
        </div>

        <div className="bg-slate-50 rounded-lg p-4 space-y-2 text-sm" data-testid="payment-return-summary">
          <div className="flex justify-between"><span className="text-slate-500">N° de transaction</span><span className="font-mono text-xs">{depositId}</span></div>
          {payment?.amount && <div className="flex justify-between"><span className="text-slate-500">Montant</span><span className="font-semibold">{Number(payment.amount).toLocaleString("fr-FR")} {payment.currency || "XOF"}</span></div>}
          {payment?.mno && <div className="flex justify-between"><span className="text-slate-500">Opérateur</span><span>{payment.mno}</span></div>}
          {payment?.msisdn && <div className="flex justify-between"><span className="text-slate-500">Numéro</span><span className="font-mono">{payment.msisdn}</span></div>}
          {apiStatus && status !== "completed" && (
            <div className="flex justify-between text-xs text-slate-500"><span>Statut PawaPay</span><span>{apiStatus}</span></div>
          )}
          {status === "pending" && (
            <div className="flex items-center gap-2 text-xs text-blue-700 pt-2">
              <Clock size={12} /> Tentative {attempts}/{MAX_ATTEMPTS}…
            </div>
          )}
        </div>

        <div className="flex gap-2 mt-6">
          <button onClick={() => navigate("/portal/my-payments")} data-testid="payment-return-back"
            className="flex-1 px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-sm">
            Voir mes paiements
          </button>
          {status === "pending" && (
            <button onClick={refresh} data-testid="payment-return-refresh"
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm flex items-center gap-2">
              <Loader2 size={14} /> Actualiser
            </button>
          )}
        </div>
        {status === "pending" && attempts >= MAX_ATTEMPTS && (
          <p className="text-xs text-amber-700 text-center mt-3">
            Délai dépassé. Le webhook PawaPay mettra à jour le statut automatiquement dans les minutes qui suivent.
          </p>
        )}
      </div>
    </div>
  );
}
