import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { CreditCard, Plus, RefreshCw, X, CheckCircle2, Clock, AlertCircle, Wallet } from "lucide-react";

/*
  Portal → My Payments
  Lets the user initiate a PawaPay deposit and track the status.
  Available MNOs come from /me/features (inherited from the parent client).
*/
const MNO_LABELS = {
  ORANGE: { label: "Orange Money", color: "#FF7900" },
  MOOV: { label: "Moov Money", color: "#0076BB" },
  TELECEL: { label: "Telecel Cash", color: "#E2241A" },
};

const STATUS_BADGE = {
  pending: { cls: "bg-amber-100 text-amber-800", icon: Clock, label: "En attente" },
  completed: { cls: "bg-emerald-100 text-emerald-800", icon: CheckCircle2, label: "Complété" },
  failed: { cls: "bg-rose-100 text-rose-800", icon: AlertCircle, label: "Échec" },
};

export default function MyPayments() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [features, setFeatures] = useState({});
  const [mnos, setMnos] = useState([]);
  const [showModal, setShowModal] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/payments");
      setItems(r.data || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    apiClient.get("/me/features").then((r) => {
      setFeatures(r.data?.features || {});
      setMnos(r.data?.pawapay_mnos || []);
    }).catch(() => {});
  }, []);

  const refreshOne = async (deposit_id) => {
    try {
      const r = await apiClient.get(`/me/payments/${deposit_id}`);
      setItems((prev) => prev.map((p) => (p.deposit_id === deposit_id ? r.data : p)));
    } catch { /* noop */ }
  };

  return (
    <div className="space-y-6 p-6 max-w-5xl" data-testid="my-payments-page">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-display font-bold inline-flex items-center gap-2">
            <Wallet className="h-6 w-6 text-amber-600" /> Mes paiements
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Encaissements via Mobile Money (PawaPay).
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={load} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50" data-testid="payments-refresh">
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Actualiser
          </button>
          <button
            onClick={() => features.payments && mnos.length > 0 ? setShowModal(true) : toast.error(features.payments ? "Aucun opérateur autorisé" : "Paiements non activés pour votre compte")}
            disabled={!features.payments || mnos.length === 0}
            className="inline-flex items-center gap-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white px-4 py-2 text-sm disabled:opacity-40 disabled:cursor-not-allowed"
            data-testid="payments-new-btn"
          >
            <Plus className="h-4 w-4" /> Nouveau paiement
          </button>
        </div>
      </div>

      {!features.payments && (
        <div className="rounded-lg ring-1 ring-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          La fonctionnalité Paiements n'est pas activée pour votre compte. Contactez votre administrateur.
        </div>
      )}

      <div className="rounded-xl ring-1 ring-slate-200 bg-white overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500 uppercase text-[10px]">
              <tr>
                <th className="text-left px-3 py-2">Date</th>
                <th className="text-left px-3 py-2">Référence</th>
                <th className="text-left px-3 py-2">Opérateur</th>
                <th className="text-left px-3 py-2">Numéro</th>
                <th className="text-right px-3 py-2">Montant</th>
                <th className="text-left px-3 py-2">Statut</th>
                <th className="text-right px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {loading && items.length === 0 && (
                <tr><td colSpan={7} className="px-3 py-6 text-center text-slate-400 italic">Chargement…</td></tr>
              )}
              {!loading && items.length === 0 && (
                <tr><td colSpan={7} className="px-3 py-6 text-center text-slate-400 italic">Aucun paiement pour l'instant.</td></tr>
              )}
              {items.map((p) => {
                const sb = STATUS_BADGE[p.status] || STATUS_BADGE.pending;
                const Icon = sb.icon;
                const mno = MNO_LABELS[p.mno] || { label: p.mno, color: "#64748b" };
                return (
                  <tr key={p.deposit_id} className="border-t border-slate-100 hover:bg-slate-50" data-testid={`payment-row-${p.deposit_id}`}>
                    <td className="px-3 py-2 text-slate-600 whitespace-nowrap">{p.created_at ? new Date(p.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—"}</td>
                    <td className="px-3 py-2 font-mono text-[10px] text-slate-700">{p.deposit_id?.slice(0, 8)}…</td>
                    <td className="px-3 py-2"><span className="text-[11px] font-semibold" style={{ color: mno.color }}>{mno.label}</span></td>
                    <td className="px-3 py-2 font-mono text-xs text-slate-700">{p.msisdn}</td>
                    <td className="px-3 py-2 text-right font-mono">{p.amount?.toLocaleString("fr-FR")} <span className="text-[10px] text-slate-400">{p.currency}</span></td>
                    <td className="px-3 py-2">
                      <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded ${sb.cls}`}>
                        <Icon className="h-3 w-3" /> {sb.label}
                      </span>
                      {p.api_message && <span className="block text-[10px] text-slate-500 mt-0.5">{p.api_message}</span>}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {p.status === "pending" && (
                        <button onClick={() => refreshOne(p.deposit_id)} className="text-xs text-sawali-blue hover:underline" data-testid={`payment-refresh-${p.deposit_id}`}>
                          Vérifier
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {showModal && (
        <NewPaymentModal mnos={mnos} onClose={() => setShowModal(false)} onCreated={load} />
      )}
    </div>
  );
}

function NewPaymentModal({ mnos, onClose, onCreated }) {
  const [amount, setAmount] = useState("");
  const [msisdn, setMsisdn] = useState("226");
  const [mno, setMno] = useState(mnos[0] || "ORANGE");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    const amt = parseFloat(amount);
    if (!amt || amt <= 0) { toast.error("Montant invalide"); return; }
    if (!msisdn || msisdn.replace(/\D/g, "").length < 11) {
      toast.error("Numéro mobile invalide (format international, ex: 22670000000)");
      return;
    }
    if (!mnos.includes(mno)) { toast.error("Opérateur non autorisé"); return; }
    setSubmitting(true);
    try {
      const r = await apiClient.post("/me/payments/pawapay/deposit", {
        amount: amt,
        msisdn: msisdn.replace(/\D/g, ""),
        mno,
        description: description || undefined,
      });
      if (r.data?.ok) {
        toast.success("Demande envoyée — vous allez recevoir une notification mobile pour confirmer le paiement.");
        onCreated && onCreated();
        onClose();
      } else {
        toast.error(r.data?.reason || "Demande rejetée");
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      data-testid="payment-new-modal"
    >
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 bg-amber-50">
          <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
            <CreditCard className="h-5 w-5 text-amber-600" /> Nouveau paiement
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-3">
          <div>
            <label className="text-xs font-semibold block mb-1">Montant (XOF)</label>
            <input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="5000"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
              data-testid="payment-amount"
            />
          </div>
          <div>
            <label className="text-xs font-semibold block mb-1">Opérateur Mobile Money</label>
            <div className="grid grid-cols-3 gap-2">
              {mnos.map((m) => {
                const meta = MNO_LABELS[m] || { label: m, color: "#64748b" };
                const active = mno === m;
                return (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setMno(m)}
                    className={`rounded-lg px-2 py-2 text-xs font-semibold ring-1 ${active ? "ring-2 text-white" : "ring-slate-200 text-slate-600 bg-white hover:bg-slate-50"}`}
                    style={active ? { backgroundColor: meta.color, ringColor: meta.color } : {}}
                    data-testid={`payment-mno-${m}`}
                  >
                    {meta.label}
                  </button>
                );
              })}
            </div>
          </div>
          <div>
            <label className="text-xs font-semibold block mb-1">Numéro Mobile Money (format international)</label>
            <input
              value={msisdn}
              onChange={(e) => setMsisdn(e.target.value)}
              placeholder="22670XXXXXX"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
              data-testid="payment-msisdn"
            />
            <p className="text-[10px] text-slate-400 mt-0.5">Sans le « + ». Exemple Burkina : 22670000000.</p>
          </div>
          <div>
            <label className="text-xs font-semibold block mb-1">Description (facultatif, max 22 car.)</label>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value.slice(0, 22))}
              maxLength={22}
              placeholder="Facture #1234"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              data-testid="payment-description"
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 px-5 py-3 border-t border-slate-200 bg-slate-50">
          <button onClick={onClose} className="text-sm rounded-lg bg-white ring-1 ring-slate-300 hover:bg-slate-100 px-4 py-2">Annuler</button>
          <button
            onClick={submit}
            disabled={submitting}
            className="inline-flex items-center gap-1.5 text-sm rounded-lg bg-amber-600 hover:bg-amber-700 text-white px-4 py-2 disabled:opacity-50"
            data-testid="payment-submit-btn"
          >
            <CreditCard className="h-4 w-4" /> {submitting ? "Envoi…" : "Lancer le paiement"}
          </button>
        </div>
      </div>
    </div>
  );
}
