// S031 + S032 — Universal Key health banner & burn-rate alerts.
// Shown ONLY to admin@sawalismartsystems.com (the super-admin).
// Polls /api/admin/llm-health every 60 s.
//   - status_level = "exhausted"  → rose/red banner (S031, hard outage)
//   - status_level = "critical"   → orange banner with burn-rate stats (S032)
//   - status_level = "warning"    → amber banner with burn-rate stats (S032)
//   - status_level = "error"      → amber banner (key missing / unknown)
//   - status_level = "ok"         → no banner rendered
import React, { useEffect, useState, useCallback, useRef } from "react";
import { useLocation } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { AlertTriangle, RefreshCw, X as XIcon, Loader2, TrendingUp, Clock } from "lucide-react";

const SUPER_ADMIN_EMAIL = "admin@sawalismartsystems.com";
const POLL_MS = 60_000;

const LEVEL_STYLES = {
  exhausted: "from-rose-600 to-red-700",
  critical: "from-orange-500 to-rose-600",
  warning: "from-amber-400 to-amber-600",
  error: "from-amber-500 to-orange-600",
};

const LEVEL_LABELS = {
  exhausted: "Universal Key Emergent ÉPUISÉE — service IA indisponible",
  critical: "Universal Key Emergent — Consommation CRITIQUE",
  warning: "Universal Key Emergent — Avertissement de consommation",
  error: "Universal Key Emergent — Erreur IA détectée",
};

function fmtUsd(v) {
  if (typeof v !== "number" || Number.isNaN(v)) return "—";
  return v.toFixed(v < 0.01 ? 4 : 2);
}

function fmtDays(d) {
  if (typeof d !== "number" || !Number.isFinite(d)) return "indéterminée";
  if (d < 1) return `~${Math.max(1, Math.round(d * 24))}h`;
  if (d < 30) return `~${d.toFixed(1)} jours`;
  return "30+ jours";
}

export default function LlmHealthBanner() {
  const { user } = useAuth() || {};
  const location = useLocation();
  const [state, setState] = useState(null);
  const [dismissed, setDismissed] = useState(false);
  const [pinging, setPinging] = useState(false);
  const timerRef = useRef(null);

  // Gate 1 : connecté ET super-admin uniquement.
  // Gate 2 : pages /admin/* uniquement (pas le portail utilisateur, pas la page publique).
  const isSuper = !!user && (user?.email || "").toLowerCase() === SUPER_ADMIN_EMAIL;
  const isAdminRoute = (location?.pathname || "").startsWith("/admin");
  const canRender = isSuper && isAdminRoute;

  const refresh = useCallback(async () => {
    if (!user) return;
    try {
      const r = await apiClient.get("/admin/llm-health");
      setState(r.data || null);
    } catch {
      // Silently ignore — non-admins get 403 which is expected.
    }
  }, [user]);

  useEffect(() => {
    if (!canRender) return;
    refresh();
    timerRef.current = setInterval(refresh, POLL_MS);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [canRender, refresh]);

  // Reset the dismissed flag whenever the level changes
  useEffect(() => {
    if (state?.status_level === "ok") setDismissed(false);
  }, [state?.status_level]);

  const ping = async () => {
    setPinging(true);
    try {
      const r = await apiClient.post("/admin/llm-health/ping");
      setState(r.data);
    } catch { /* noop */ }
    finally { setPinging(false); }
  };

  if (!canRender || !state) return null;
  const level = state.status_level || "ok";
  if (level === "ok") return null;
  if (dismissed) return null;

  const label = LEVEL_LABELS[level] || "Problème IA détecté";
  const gradient = LEVEL_STYLES[level] || LEVEL_STYLES.warning;
  const cost = state.current_cost_usd ?? state.current_cost;
  const max = state.max_budget_usd ?? state.max_budget;
  const pct = typeof state.pct_used === "number" ? state.pct_used : null;
  const burn24 = state.burn_rate_24h_usd;
  const projDays = state.projected_days_left;
  const checked = state.last_checked_at ? new Date(state.last_checked_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—";

  return (
    <div
      className={`sticky top-0 z-[80] bg-gradient-to-r ${gradient} text-white shadow-lg`}
      role="alert"
      data-testid="llm-health-banner"
      data-level={level}
    >
      <div className="max-w-7xl mx-auto px-4 py-2 flex items-center gap-3 flex-wrap">
        <AlertTriangle className="h-5 w-5 shrink-0 animate-pulse" />
        <div className="flex-1 min-w-0 text-sm">
          <p className="font-display font-bold leading-tight flex items-center gap-2 flex-wrap" data-testid="llm-health-banner-title">
            <span>{label}</span>
            {typeof cost === "number" && typeof max === "number" && (
              <span className="text-xs font-mono opacity-90" data-testid="llm-health-banner-cost">
                {fmtUsd(cost)} / {fmtUsd(max)} USD
                {pct !== null && <span className="ml-1">({pct.toFixed(0)}%)</span>}
              </span>
            )}
          </p>
          {(level === "warning" || level === "critical") && (
            <p className="text-xs opacity-95 leading-tight mt-1 flex items-center gap-3 flex-wrap" data-testid="llm-health-banner-metrics">
              <span className="inline-flex items-center gap-1"><TrendingUp className="h-3 w-3" /> Vitesse 24h : <strong>~{fmtUsd(burn24)} USD</strong></span>
              <span className="inline-flex items-center gap-1"><Clock className="h-3 w-3" /> Épuisement projeté : <strong data-testid="llm-health-banner-projection">{fmtDays(projDays)}</strong></span>
              <span className="opacity-75">Appels IA (24h) : {state.calls_24h ?? 0}</span>
            </p>
          )}
          <p className="text-xs opacity-90 leading-tight mt-0.5" data-testid="llm-health-banner-instructions">
            {level === "exhausted" ? (
              <>Liluvine PRO, auto-réponses WA, OCR KB et planificateur IA sont indisponibles. </>
            ) : level === "critical" ? (
              <>Rechargez la clé Universal Key <strong>immédiatement</strong> pour éviter une coupure imminente du service. </>
            ) : level === "warning" ? (
              <>Anticipez une recharge pour éviter une coupure du service. </>
            ) : (
              <>Vérifiez le service IA — un problème inattendu a été détecté. </>
            )}
            <strong className="ml-1">Pour rétablir :</strong> Plateforme Emergent → Profile → Universal Key → <strong>Add Balance</strong>.
            <span className="opacity-75 ml-2">Dernier check : {checked}</span>
          </p>
        </div>
        <button
          onClick={ping}
          disabled={pinging}
          className="text-xs inline-flex items-center gap-1 px-2.5 py-1 rounded bg-white/20 hover:bg-white/30 ring-1 ring-white/30 disabled:opacity-50"
          data-testid="llm-health-banner-retest"
          title="Refaire un test IA pour vérifier"
        >
          {pinging ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          Re-tester
        </button>
        <button
          onClick={() => setDismissed(true)}
          className="text-xs p-1 rounded bg-white/10 hover:bg-white/20"
          aria-label="Masquer jusqu'à la prochaine session"
          data-testid="llm-health-banner-dismiss"
          title="Masquer (réapparaît au prochain check)"
        >
          <XIcon className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
