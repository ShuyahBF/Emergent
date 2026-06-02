// S036 — Bouton "Tester l'envoi" de l'escalation Liluvine PRO.
// Appelle POST /admin/liluvine-escalation/test qui envoie un message WA
// synthétique à l'admin configuré et retourne {sent, to, skipped_reason}.
import React, { useState } from "react";
import { apiClient } from "@/lib/api";
import { Loader2, Send, CheckCircle2, AlertCircle } from "lucide-react";

export default function LiluvineEscalationTestButton() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const runTest = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const r = await apiClient.post("/admin/liluvine-escalation/test");
      setResult(r.data);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Erreur réseau");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={runTest}
        disabled={loading}
        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-rose-500 to-fuchsia-600 hover:from-rose-600 hover:to-fuchsia-700 text-white text-sm font-semibold shadow-md disabled:opacity-50"
        data-testid="liluvine-escalation-test-btn"
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
        {loading ? "Envoi en cours..." : "Envoyer un test à l'admin"}
      </button>

      {error && (
        <div className="text-xs px-3 py-2 rounded-lg bg-rose-50 text-rose-700 ring-1 ring-rose-200 inline-flex items-center gap-2" data-testid="liluvine-escalation-test-error">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {result && (
        <div className="text-xs px-3 py-2 rounded-lg bg-slate-50 ring-1 ring-slate-200 space-y-1" data-testid="liluvine-escalation-test-result">
          {result.sent ? (
            <div className="inline-flex items-center gap-2 text-emerald-700 font-semibold">
              <CheckCircle2 className="h-4 w-4" />
              Message envoyé à <code>{result.to}</code>
            </div>
          ) : (
            <div className="inline-flex items-center gap-2 text-amber-700 font-semibold">
              <AlertCircle className="h-4 w-4" />
              Non envoyé — raison : <code>{result.skipped_reason || "inconnue"}</code>
              {result.to && <span> (cible : {result.to})</span>}
            </div>
          )}
          {result.skipped_reason === "disabled" && (
            <p className="text-[11px] text-slate-500">
              Activez le toggle ci-dessus puis sauvegardez avant de retenter.
            </p>
          )}
          {result.skipped_reason === "no_admin_phone" && (
            <p className="text-[11px] text-slate-500">
              Renseignez un numéro WhatsApp (ici ou dans la section Universal Key) puis sauvegardez.
            </p>
          )}
          {result.skipped_reason === "throttled" && (
            <p className="text-[11px] text-slate-500">
              Anti-spam actif — un message vient déjà d'être envoyé. Réessayez après le délai configuré.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
