// S033 — Bouton "Tester maintenant" du solde Universal Key Emergent.
// Appelle POST /admin/llm-health/test-summary qui force un ping puis
// renvoie le résumé formaté + les métriques S032.
import React, { useState } from "react";
import { apiClient } from "@/lib/api";
import { Loader2, FlaskConical, AlertCircle, CheckCircle2 } from "lucide-react";

const LEVEL_BADGE = {
  ok: { cls: "bg-emerald-100 text-emerald-700 ring-emerald-200", label: "OK" },
  warning: { cls: "bg-amber-100 text-amber-700 ring-amber-200", label: "Avertissement" },
  critical: { cls: "bg-orange-100 text-orange-700 ring-orange-200", label: "CRITIQUE" },
  exhausted: { cls: "bg-rose-100 text-rose-700 ring-rose-200", label: "ÉPUISÉE" },
  error: { cls: "bg-slate-100 text-slate-700 ring-slate-200", label: "Erreur IA" },
};

export default function LlmBudgetTestButton() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const runTest = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await apiClient.post("/admin/llm-health/test-summary");
      setResult(r.data);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Erreur réseau");
    } finally {
      setLoading(false);
    }
  };

  // Iter43-fix (2026-03) — Bouton de reset des valeurs figées par une ancienne
  // erreur Emergent « Budget exceeded ». À utiliser quand le banner reste
  // bloqué à 100% après une recharge.
  const [resetting, setResetting] = useState(false);
  const resetStale = async () => {
    if (!window.confirm("Réinitialiser le compteur Universal Key Emergent ?\n\nCela efface les valeurs `current_cost` et `max_budget` figées par une ancienne erreur, et relance un probe. À utiliser uniquement si vous venez de recharger votre solde et que le banner reste à 100%.")) return;
    setResetting(true);
    setError(null);
    try {
      const r = await apiClient.post("/admin/llm-health/reset-stale");
      setResult(r.data);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Erreur réseau");
    } finally { setResetting(false); }
  };

  const lvl = result?.status_level;
  const badge = lvl ? LEVEL_BADGE[lvl] : null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={runTest}
          disabled={loading || resetting}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-indigo-600 to-fuchsia-600 hover:from-indigo-700 hover:to-fuchsia-700 text-white text-sm font-semibold shadow-md disabled:opacity-50"
          data-testid="llm-budget-test-now-btn"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FlaskConical className="h-4 w-4" />}
          {loading ? "Test en cours..." : "Tester maintenant"}
        </button>
        <button
          type="button"
          onClick={resetStale}
          disabled={loading || resetting}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg ring-1 ring-rose-300 bg-rose-50 hover:bg-rose-100 text-rose-700 text-sm font-medium disabled:opacity-50"
          data-testid="llm-budget-reset-stale-btn"
          title="Efface les valeurs figées par une ancienne erreur « Budget exceeded »"
        >
          {resetting ? <Loader2 className="h-4 w-4 animate-spin" /> : <AlertCircle className="h-4 w-4" />}
          {resetting ? "Reset en cours..." : "Réinitialiser après recharge"}
        </button>
      </div>

      {error && (
        <div className="text-xs px-3 py-2 rounded-lg bg-rose-50 text-rose-700 ring-1 ring-rose-200 inline-flex items-center gap-2" data-testid="llm-budget-test-error">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {result && (
        <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 text-xs space-y-2" data-testid="llm-budget-test-result">
          <div className="flex items-center gap-2 flex-wrap">
            <CheckCircle2 className="h-4 w-4 text-emerald-600" />
            <span className="font-semibold">Résultat du test :</span>
            {badge && (
              <span className={`text-[11px] px-2 py-0.5 rounded-full ring-1 font-bold ${badge.cls}`} data-testid="llm-budget-test-level">
                {badge.label}
              </span>
            )}
          </div>
          <div className="grid sm:grid-cols-2 gap-x-4 gap-y-1 font-mono">
            <div>Consommation : <strong>{result.current_cost_usd?.toFixed(2)} / {result.max_budget_usd?.toFixed(2)} USD</strong> ({result.pct_used?.toFixed(1)}%)</div>
            <div>Vitesse 24h : ~{result.burn_rate_24h_usd?.toFixed(4)} USD ({result.calls_24h ?? 0} appels)</div>
            <div>Vitesse 1h : ~{result.burn_rate_1h_usd?.toFixed(4)} USD</div>
            <div>Projection : {typeof result.projected_days_left === "number"
              ? (result.projected_days_left < 1
                ? `~${Math.max(1, Math.round(result.projected_days_left * 24))}h`
                : `~${result.projected_days_left.toFixed(1)} jours`)
              : "indéterminée"}
            </div>
            <div>Seuils : warn {result.warning_pct}% / crit {result.critical_pct}%</div>
            <div>Source coût : {result.cost_source === "emergent_error" ? "Emergent (vérité)" : "Estimation locale"}</div>
          </div>
          {result.summary_text && (
            <details className="pt-2 border-t border-slate-200">
              <summary className="cursor-pointer text-[11px] text-slate-600 hover:text-slate-800">
                Voir le message WhatsApp envoyé en cas de requête « SOLDE »
              </summary>
              <pre className="mt-2 whitespace-pre-wrap text-[11px] font-mono bg-white p-2 rounded ring-1 ring-slate-200 max-h-64 overflow-auto" data-testid="llm-budget-test-summary-text">{result.summary_text}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
