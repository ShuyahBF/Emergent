import React, { useEffect, useState, useCallback } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import {
  CreditCard, ShieldCheck, CheckCircle2, AlertCircle, Clock, Loader2, Lock,
} from "lucide-react";
import { LOGO_URL } from "@/lib/brand";

/*
  Public branded payment landing page.
  URL : /pay/{slug}
  Shows the merchant's branding + amount/MNO selector.
  Calls /api/public/pay/{slug}/deposit (no auth) then polls status.
*/
const BACKEND = process.env.REACT_APP_BACKEND_URL || "";
const MNO_LABELS = {
  ORANGE: { label: "Orange Money", color: "#FF7900", emoji: "🟧" },
  MOOV: { label: "Moov Money", color: "#0076BB", emoji: "🟦" },
  TELECEL: { label: "Telecel Cash", color: "#E2241A", emoji: "🟥" },
};

function absoluteUrl(u) {
  if (!u) return u;
  if (u.startsWith("http")) return u;
  return `${BACKEND}${u.startsWith("/") ? "" : "/"}${u}`;
}

const STATUS_LABELS = {
  pending: { cls: "text-amber-700 bg-amber-50 ring-amber-200", icon: Clock, label: "En attente de confirmation sur votre téléphone" },
  completed: { cls: "text-emerald-700 bg-emerald-50 ring-emerald-200", icon: CheckCircle2, label: "Paiement confirmé — merci !" },
  failed: { cls: "text-rose-700 bg-rose-50 ring-rose-200", icon: AlertCircle, label: "Paiement échoué" },
};

const STATE_LABEL = {
  active: "Actif",
  disabled: "Désactivé par l'émetteur",
  expired: "Lien expiré",
  exhausted: "Lien épuisé (nombre max d'utilisations atteint)",
};

export default function PayLink() {
  const { slug } = useParams();
  const [link, setLink] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Form state
  const [amount, setAmount] = useState("");
  const [msisdn, setMsisdn] = useState("226");
  const [mno, setMno] = useState(null);
  const [payerName, setPayerName] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // Result state
  const [result, setResult] = useState(null); // {deposit_id, status, api_message, amount, currency}

  const fetchLink = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${BACKEND}/api/public/pay/${slug}`);
      setLink(r.data);
      if (r.data?.amount != null) setAmount(String(r.data.amount));
      if (Array.isArray(r.data?.allowed_mnos) && r.data.allowed_mnos.length > 0) {
        setMno(r.data.allowed_mnos[0]);
      }
    } catch (err) {
      setError(err?.response?.data?.detail || "Lien introuvable");
    } finally {
      setLoading(false);
    }
  }, [slug]);

  useEffect(() => { fetchLink(); }, [fetchLink]);

  // Poll status when result.status === pending
  useEffect(() => {
    if (!result || result.status !== "pending") return;
    const t = setInterval(async () => {
      try {
        const r = await axios.get(`${BACKEND}/api/public/pay/${slug}/status/${result.deposit_id}`);
        setResult((prev) => prev ? { ...prev, ...r.data } : prev);
      } catch { /* noop */ }
    }, 5000);
    return () => clearInterval(t);
  }, [result, slug]);

  const submit = async () => {
    const isOpen = link?.amount == null;
    const amt = isOpen ? parseFloat(amount) : Number(link.amount);
    if (!amt || amt <= 0) { toast.error("Montant invalide"); return; }
    const cleanMsisdn = (msisdn || "").replace(/\D/g, "");
    if (cleanMsisdn.length < 11) { toast.error("Numéro mobile invalide (format international)"); return; }
    if (!mno || !(link.allowed_mnos || []).includes(mno)) { toast.error("Sélectionnez un opérateur"); return; }
    setSubmitting(true);
    try {
      const r = await axios.post(`${BACKEND}/api/public/pay/${slug}/deposit`, {
        amount: isOpen ? amt : undefined,
        msisdn: cleanMsisdn,
        mno,
        payer_name: payerName || undefined,
      });
      const reason = r.data?.reason;
      const reasonStr = reason && typeof reason === "object"
        ? (reason.failureMessage || reason.rejectionMessage || reason.message || JSON.stringify(reason))
        : reason;
      setResult({
        deposit_id: r.data.deposit_id,
        status: r.data.status,
        api_message: reasonStr || null,
        amount: amt,
        currency: link.currency || "XOF",
      });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      const msg = (typeof detail === "object" ? (detail?.failureMessage || detail?.rejectionMessage || detail?.message || JSON.stringify(detail)) : detail) || err?.message || "Erreur lors du paiement";
      toast.error(String(msg).slice(0, 200));
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <Centered>
        <Loader2 className="h-6 w-6 animate-spin text-amber-600" />
        <p className="text-sm text-slate-500">Chargement du lien…</p>
      </Centered>
    );
  }
  if (error || !link) {
    return (
      <Centered>
        <AlertCircle className="h-10 w-10 text-rose-600" />
        <h1 className="font-display text-xl font-bold">Lien introuvable</h1>
        <p className="text-sm text-slate-500 max-w-sm text-center">{error || "Ce lien n'existe pas ou a été supprimé."}</p>
      </Centered>
    );
  }

  const isOpen = link.amount == null;
  const company = link.branding?.company || "SAWALI SMART SYSTEMS";
  const logoUrl = link.branding?.logo_url ? absoluteUrl(link.branding.logo_url) : LOGO_URL;
  const inactive = link.status !== "active";

  // Result screen
  if (result) {
    const sb = STATUS_LABELS[result.status] || STATUS_LABELS.pending;
    const Icon = sb.icon;
    return (
      <Shell company={company} logoUrl={logoUrl}>
        <div className="rounded-2xl bg-white shadow-xl ring-1 ring-slate-200 p-8 text-center" data-testid="pay-result">
          <div className={`mx-auto mb-4 inline-flex items-center justify-center h-16 w-16 rounded-full ring-2 ${sb.cls}`}>
            <Icon className="h-8 w-8" />
          </div>
          <h2 className="font-display text-2xl font-bold mb-2">{sb.label}</h2>
          <p className="text-3xl font-mono font-bold text-slate-800 my-3">
            {Number(result.amount).toLocaleString("fr-FR")} <span className="text-base text-slate-500">{result.currency || "XOF"}</span>
          </p>
          {result.status === "pending" && (
            <p className="text-sm text-slate-600 max-w-sm mx-auto">
              Vérifiez votre téléphone et confirmez la transaction avec votre code Mobile Money.
              Cette page se mettra à jour automatiquement.
            </p>
          )}
          {result.status === "completed" && (
            <p className="text-sm text-emerald-700">Vous pouvez fermer cette page.</p>
          )}
          {result.status === "failed" && (
            <>
              <p className="text-sm text-rose-700 mb-4">{result.api_message || "La transaction a échoué."}</p>
              <button onClick={() => setResult(null)} className="rounded-lg bg-amber-600 hover:bg-amber-700 text-white px-4 py-2 text-sm font-semibold" data-testid="pay-retry-btn">
                Réessayer
              </button>
            </>
          )}
          <p className="text-[10px] text-slate-400 font-mono mt-6">Réf : {result.deposit_id?.slice(0, 13)}…</p>
        </div>
      </Shell>
    );
  }

  return (
    <Shell company={company} logoUrl={logoUrl}>
      <div className="rounded-2xl bg-white shadow-xl ring-1 ring-slate-200 overflow-hidden" data-testid="pay-link-page">
        <div className="bg-gradient-to-br from-amber-50 to-amber-100 p-5">
          <p className="text-[10px] uppercase tracking-[0.25em] text-amber-700 font-semibold">Paiement sécurisé</p>
          <h1 className="font-display text-xl font-bold text-slate-800 mt-1">{link.label}</h1>
          {link.description && <p className="text-sm text-slate-600 mt-1">{link.description}</p>}
          {!isOpen && (
            <div className="mt-3 text-3xl font-mono font-bold text-slate-900">
              {Number(link.amount).toLocaleString("fr-FR")} <span className="text-base font-semibold text-slate-500">{link.currency || "XOF"}</span>
            </div>
          )}
        </div>

        {inactive ? (
          <div className="p-6 text-center">
            <AlertCircle className="h-10 w-10 text-amber-600 mx-auto mb-2" />
            <p className="font-semibold text-slate-800">{STATE_LABEL[link.status] || "Lien non utilisable"}</p>
            <p className="text-sm text-slate-500 mt-1">Contactez l'émetteur de ce lien pour plus d'informations.</p>
          </div>
        ) : (
          <div className="p-5 space-y-4">
            {isOpen && (
              <div>
                <label className="text-xs font-semibold block mb-1">Montant à payer ({link.currency || "XOF"})</label>
                <input
                  type="number"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  placeholder="5000"
                  className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-base font-mono"
                  data-testid="pay-amount"
                />
              </div>
            )}
            <div>
              <label className="text-xs font-semibold block mb-1">Choisissez votre opérateur</label>
              <div className={`grid grid-cols-${link.allowed_mnos.length} gap-2`} style={{ gridTemplateColumns: `repeat(${link.allowed_mnos.length}, 1fr)` }}>
                {link.allowed_mnos.map((m) => {
                  const meta = MNO_LABELS[m] || { label: m, color: "#64748b" };
                  const active = mno === m;
                  return (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setMno(m)}
                      className={`rounded-lg px-2 py-3 text-sm font-semibold ring-1 transition ${active ? "ring-2 text-white shadow" : "ring-slate-200 text-slate-600 bg-white hover:bg-slate-50"}`}
                      style={active ? { backgroundColor: meta.color, borderColor: meta.color } : {}}
                      data-testid={`pay-mno-${m}`}
                    >
                      {meta.label}
                    </button>
                  );
                })}
              </div>
            </div>
            <div>
              <label className="text-xs font-semibold block mb-1">Votre numéro Mobile Money</label>
              <input
                value={msisdn}
                onChange={(e) => setMsisdn(e.target.value)}
                placeholder="22670XXXXXX"
                className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-base font-mono"
                data-testid="pay-msisdn"
              />
              <p className="text-[10px] text-slate-400 mt-0.5">Sans le « + ». Exemple : 22670000000 (Burkina).</p>
            </div>
            <div>
              <label className="text-xs font-semibold block mb-1">Votre nom (optionnel)</label>
              <input
                value={payerName}
                onChange={(e) => setPayerName(e.target.value.slice(0, 80))}
                placeholder="Pour vous identifier sur le reçu"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                data-testid="pay-name"
              />
            </div>
            <button
              onClick={submit}
              disabled={submitting}
              className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white px-4 py-3 text-base font-semibold disabled:opacity-50"
              data-testid="pay-submit-btn"
            >
              {submitting ? <Loader2 className="h-5 w-5 animate-spin" /> : <CreditCard className="h-5 w-5" />}
              {submitting ? "Initialisation…" : "Payer maintenant"}
            </button>
            <p className="text-[10px] text-slate-500 inline-flex items-center gap-1.5 justify-center w-full">
              <Lock className="h-3 w-3" /> Paiement sécurisé via PawaPay
              {link.uses_count != null && link.max_uses && (
                <span className="ml-2">• {link.uses_count}/{link.max_uses} utilisations</span>
              )}
            </p>
          </div>
        )}
      </div>
    </Shell>
  );
}

function Shell({ company, logoUrl, children }) {
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-100 via-amber-50/40 to-slate-100 flex flex-col items-center py-10 px-4">
      <div className="flex items-center gap-3 mb-6">
        <img src={logoUrl} alt={company} className="h-10 w-10 rounded ring-1 ring-slate-200 bg-white object-contain p-1" />
        <div>
          <p className="font-display font-bold text-slate-800">{company}</p>
          <p className="text-[10px] uppercase tracking-[0.25em] text-amber-700">Paiement Mobile Money</p>
        </div>
      </div>
      <div className="w-full max-w-md">{children}</div>
      <div className="mt-6 text-[10px] text-slate-400 inline-flex items-center gap-1">
        <ShieldCheck className="h-3 w-3" /> Powered by SAWALI SMART SYSTEMS × PawaPay
      </div>
    </div>
  );
}

function Centered({ children }) {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-3 bg-slate-50">
      {children}
    </div>
  );
}
