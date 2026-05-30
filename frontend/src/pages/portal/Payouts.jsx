// =====================================================================
// Iter38r-fix9j — PawaPay Payouts UI : envoyer de l'argent à un Mobile Money
// =====================================================================
// Accessible : admin / superviseur / comptable (tracked_role)
// - Formulaire d'envoi (provider, numéro, montant, message)
// - Liste des derniers payouts avec KPI (terminés / échoués / en attente)
// - Bouton "Actualiser le statut" sur les payouts pending (force refresh API)

import React, { useCallback, useEffect, useState } from "react";
import { Banknote, Send, RefreshCw, CheckCircle2, XCircle, Clock, AlertTriangle, Phone, Wallet, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

const PROVIDERS = [
  { code: "ORANGE_BFA", label: "Orange Money (Burkina)" },
  { code: "MOOV_BFA", label: "Moov Money (Burkina)" },
  { code: "TELECEL_BFA", label: "Telecel Money (Burkina)" },
];

const STATUS_COLORS = {
  COMPLETED: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  ACCEPTED: "bg-sky-50 text-sky-700 ring-sky-200",
  ENQUEUED: "bg-sky-50 text-sky-700 ring-sky-200",
  PROCESSING: "bg-amber-50 text-amber-700 ring-amber-200",
  PENDING: "bg-amber-50 text-amber-700 ring-amber-200",
  FAILED: "bg-rose-50 text-rose-700 ring-rose-200",
};

const STATUS_ICON = {
  COMPLETED: CheckCircle2,
  FAILED: XCircle,
};

export default function PayoutsPage() {
  const { user } = useAuth() || {};
  const role = (user?.role || "").toLowerCase();
  const trackedRole = (user?.tracked_role || "").toLowerCase();
  const canPay = ["admin", "superviseur"].includes(role)
    || ["admin", "superviseur", "comptable"].includes(trackedRole);

  const [form, setForm] = useState({
    amount: "",
    msisdn: "",
    provider: "ORANGE_BFA",
    customer_message: "",
  });
  const [sending, setSending] = useState(false);
  const [items, setItems] = useState([]);
  const [kpis, setKpis] = useState({ total: 0, completed: 0, failed: 0, pending: 0, xof_completed: 0 });
  const [refreshing, setRefreshing] = useState(new Set());

  // Iter38r-fix9j — Pre-fill from URL params (e.g. when redirected from GRH paie)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const next = {};
    if (params.get("amount")) next.amount = params.get("amount");
    if (params.get("msisdn")) next.msisdn = params.get("msisdn");
    if (params.get("message")) next.customer_message = params.get("message");
    if (Object.keys(next).length > 0) {
      setForm((f) => ({ ...f, ...next }));
      toast.info("Formulaire pré-rempli depuis la paie — vérifiez et envoyez");
    }
  }, []);

  const load = useCallback(async () => {
    try {
      const r = await apiClient.get("/me/payments/pawapay/payouts?limit=100");
      setItems(r.data?.items || []);
      setKpis(r.data?.kpis || kpis);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { load(); }, [load]);

  const submit = async (e) => {
    e.preventDefault();
    if (!canPay) return;
    const amount = parseInt(form.amount, 10);
    if (!amount || amount <= 0) { toast.error("Montant invalide"); return; }
    if (!form.msisdn || form.msisdn.replace(/\D/g, "").length < 8) {
      toast.error("Numéro destinataire trop court"); return;
    }
    if (!window.confirm(`Confirmer l'envoi de ${amount.toLocaleString("fr-FR")} XOF à ${form.msisdn} (${form.provider}) ?`)) return;
    setSending(true);
    try {
      const r = await apiClient.post("/me/payments/pawapay/payout", {
        amount,
        msisdn: form.msisdn,
        provider: form.provider,
        customer_message: form.customer_message || undefined,
      });
      const st = r.data?.status || "PENDING";
      if (st === "FAILED") {
        toast.error(`Échec : ${r.data?.failure_message || r.data?.failure_code || "raison inconnue"}`);
      } else {
        toast.success(`Payout initié — statut ${st}`);
      }
      setForm({ ...form, amount: "", msisdn: "", customer_message: "" });
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setSending(false);
    }
  };

  const refreshOne = async (pid) => {
    setRefreshing((s) => new Set([...s, pid]));
    try {
      await apiClient.get(`/me/payments/pawapay/payout/${pid}?refresh=true`);
      toast.success("Statut actualisé");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setRefreshing((s) => { const n = new Set(s); n.delete(pid); return n; });
    }
  };

  const fmtAge = (iso) => {
    if (!iso) return "—";
    try {
      const d = (Date.now() - new Date(iso).getTime()) / 60000;
      if (d < 1) return "à l'instant";
      if (d < 60) return `il y a ${Math.floor(d)} min`;
      if (d < 1440) return `il y a ${Math.floor(d / 60)} h`;
      return new Date(iso).toLocaleDateString("fr-FR");
    } catch { return iso; }
  };

  return (
    <div className="space-y-4 p-4" data-testid="pawapay-payouts-page">
      {/* Header */}
      <div className="flex items-center gap-2">
        <div className="h-10 w-10 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center">
          <Banknote className="h-5 w-5 text-white" />
        </div>
        <div className="flex-1">
          <h1 className="font-display font-bold text-slate-900 text-xl inline-flex items-center gap-1">
            PawaPay Payouts <Sparkles className="h-4 w-4 text-emerald-500" />
          </h1>
          <p className="text-xs text-slate-500">Envoyer de l'argent depuis votre portefeuille SAWALI vers un compte Mobile Money (fournisseurs, salaires, remboursements).</p>
        </div>
      </div>

      {!canPay && (
        <div className="rounded-lg ring-1 ring-amber-200 bg-amber-50 p-3 flex items-start gap-2 text-amber-900" data-testid="payouts-no-access">
          <AlertTriangle className="h-4 w-4 mt-0.5" />
          <p className="text-sm">Lecture seule — réservé aux rôles administrateur / superviseur / comptable.</p>
        </div>
      )}

      {/* KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <div className="rounded-lg ring-1 ring-slate-200 bg-white p-3" data-testid="kpi-total">
          <div className="text-[10px] uppercase tracking-wider text-slate-500">Total</div>
          <div className="text-2xl font-display font-bold text-slate-900">{kpis.total}</div>
        </div>
        <div className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50/40 p-3" data-testid="kpi-completed">
          <div className="text-[10px] uppercase tracking-wider text-emerald-700">Terminés</div>
          <div className="text-2xl font-display font-bold text-emerald-700">{kpis.completed}</div>
          <div className="text-[10px] text-emerald-600 mt-0.5">{(kpis.xof_completed || 0).toLocaleString("fr-FR")} XOF</div>
        </div>
        <div className="rounded-lg ring-1 ring-amber-200 bg-amber-50/40 p-3" data-testid="kpi-pending">
          <div className="text-[10px] uppercase tracking-wider text-amber-700">En attente</div>
          <div className="text-2xl font-display font-bold text-amber-700">{kpis.pending}</div>
        </div>
        <div className="rounded-lg ring-1 ring-rose-200 bg-rose-50/40 p-3" data-testid="kpi-failed">
          <div className="text-[10px] uppercase tracking-wider text-rose-700">Échoués</div>
          <div className="text-2xl font-display font-bold text-rose-700">{kpis.failed}</div>
        </div>
      </div>

      {/* Form */}
      {canPay && (
        <form onSubmit={submit} className="rounded-xl ring-1 ring-emerald-200 bg-gradient-to-br from-emerald-50/40 to-white p-4 space-y-3" data-testid="payout-form">
          <div className="flex items-center gap-2 mb-1">
            <Send className="h-4 w-4 text-emerald-600" />
            <h2 className="font-display font-semibold text-slate-800 text-sm">Nouveau paiement Mobile Money</h2>
          </div>
          <div className="grid sm:grid-cols-3 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">Opérateur</label>
              <select
                value={form.provider}
                onChange={(e) => setForm({ ...form, provider: e.target.value })}
                className="w-full text-sm rounded-lg border border-slate-300 px-3 py-2 bg-white"
                data-testid="payout-provider"
              >
                {PROVIDERS.map((p) => (
                  <option key={p.code} value={p.code}>{p.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">Numéro destinataire</label>
              <div className="relative">
                <Phone className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
                <input
                  type="tel"
                  value={form.msisdn}
                  onChange={(e) => setForm({ ...form, msisdn: e.target.value })}
                  placeholder="22670000000"
                  className="w-full text-sm pl-8 pr-3 py-2 rounded-lg border border-slate-300 font-mono"
                  data-testid="payout-msisdn"
                />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">Montant (XOF)</label>
              <div className="relative">
                <Wallet className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={form.amount}
                  onChange={(e) => setForm({ ...form, amount: e.target.value })}
                  placeholder="5000"
                  className="w-full text-sm pl-8 pr-3 py-2 rounded-lg border border-slate-300 font-mono"
                  data-testid="payout-amount"
                />
              </div>
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">
              Message au destinataire <span className="text-slate-400">(facultatif, 22 car. max)</span>
            </label>
            <input
              type="text"
              maxLength={22}
              value={form.customer_message}
              onChange={(e) => setForm({ ...form, customer_message: e.target.value })}
              placeholder="Paiement SAWALI"
              className="w-full text-sm rounded-lg border border-slate-300 px-3 py-2"
              data-testid="payout-message"
            />
          </div>
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={sending}
              className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 text-sm font-medium disabled:opacity-50"
              data-testid="payout-submit"
            >
              <Send className="h-4 w-4" /> {sending ? "Envoi…" : "Envoyer le paiement"}
            </button>
          </div>
        </form>
      )}

      {/* List */}
      <div className="rounded-xl ring-1 ring-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[820px]" data-testid="payouts-table">
          <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-slate-600">
            <tr>
              <th className="px-3 py-2 text-left">Destinataire</th>
              <th className="px-2 py-2 text-left">Opérateur</th>
              <th className="px-2 py-2 text-right">Montant</th>
              <th className="px-2 py-2 text-center">Statut</th>
              <th className="px-2 py-2 text-left">Message</th>
              <th className="px-2 py-2 text-left">Créé</th>
              <th className="px-2 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr><td colSpan={7} className="px-3 py-8 text-center text-slate-400 italic">Aucun payout pour le moment.</td></tr>
            ) : items.map((it) => {
              const st = (it.status || "PENDING").toUpperCase();
              const Icon = STATUS_ICON[st] || Clock;
              const isPending = !["COMPLETED", "FAILED"].includes(st);
              return (
                <tr key={it.id} className="border-t border-slate-100 hover:bg-slate-50/60" data-testid={`payout-row-${it.id}`}>
                  <td className="px-3 py-2 font-mono text-xs text-slate-800">+{it.phone_digits}</td>
                  <td className="px-2 py-2 text-xs text-slate-600">{it.provider}</td>
                  <td className="px-2 py-2 text-right font-mono font-semibold text-slate-800">{Number(it.amount_xof || 0).toLocaleString("fr-FR")} XOF</td>
                  <td className="px-2 py-2 text-center">
                    <span className={`inline-flex items-center gap-1 text-[10px] rounded-full ring-1 px-1.5 py-0.5 ${STATUS_COLORS[st] || "bg-slate-50 text-slate-700 ring-slate-200"}`}>
                      <Icon className="h-2.5 w-2.5" /> {st}
                    </span>
                    {it.failure_code && (
                      <div className="text-[9px] text-rose-600 mt-1 truncate max-w-[200px]" title={it.failure_message || ""}>
                        {it.failure_code}
                      </div>
                    )}
                  </td>
                  <td className="px-2 py-2 text-[11px] text-slate-500 max-w-[180px] truncate" title={it.customer_message || ""}>{it.customer_message || "—"}</td>
                  <td className="px-2 py-2 text-[11px] text-slate-500 whitespace-nowrap">{fmtAge(it.created_at)}</td>
                  <td className="px-2 py-2 text-right">
                    {isPending && (
                      <button
                        type="button"
                        onClick={() => refreshOne(it.id)}
                        disabled={refreshing.has(it.id)}
                        className="text-[10px] inline-flex items-center gap-1 rounded ring-1 ring-slate-300 hover:bg-slate-50 px-2 py-1 text-slate-700 disabled:opacity-50"
                        data-testid={`payout-refresh-${it.id}`}
                      >
                        <RefreshCw className={`h-3 w-3 ${refreshing.has(it.id) ? "animate-spin" : ""}`} /> Actualiser
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
  );
}
