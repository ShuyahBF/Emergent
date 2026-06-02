// S031 — Universal Key budget-exceeded banner.
// Shown ONLY to admin@sawalismartsystems.com (the super-admin).
// Polls /api/admin/llm-health every 60 s. When status is "budget_exceeded",
// "key_missing" or "unknown_error", renders a sticky alert banner with the
// recharge instructions.
import React, { useEffect, useState, useCallback, useRef } from "react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { AlertTriangle, RefreshCw, X as XIcon, Loader2 } from "lucide-react";

const SUPER_ADMIN_EMAIL = "admin@sawalismartsystems.com";
const POLL_MS = 60_000;

const STATUS_LABEL = {
  budget_exceeded: "Universal Key Emergent épuisée",
  key_missing: "EMERGENT_LLM_KEY manquante côté serveur",
  unknown_error: "Erreur IA inattendue (Universal Key)",
};

export default function LlmHealthBanner() {
  const { user } = useAuth() || {};
  const [state, setState] = useState(null);
  const [dismissed, setDismissed] = useState(false);
  const [pinging, setPinging] = useState(false);
  const timerRef = useRef(null);

  // Gate: only the super-admin email sees the banner. Other admins still
  // have the data via /api/admin/llm-health but no banner is rendered.
  const isSuper = (user?.email || "").toLowerCase() === SUPER_ADMIN_EMAIL;

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
    if (!isSuper) return;
    refresh();
    timerRef.current = setInterval(refresh, POLL_MS);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [isSuper, refresh]);

  // Reset the dismissed flag whenever the underlying status changes back to ok
  useEffect(() => {
    if (state?.status === "ok") setDismissed(false);
  }, [state?.status]);

  const ping = async () => {
    setPinging(true);
    try {
      const r = await apiClient.post("/admin/llm-health/ping");
      setState(r.data);
    } catch {
      // noop
    } finally {
      setPinging(false);
    }
  };

  if (!isSuper || !state) return null;
  if (state.status === "ok" || state.status === "unknown") return null;
  if (dismissed) return null;

  const label = STATUS_LABEL[state.status] || "Problème IA détecté";
  const cost = state.current_cost;
  const max = state.max_budget;
  const checked = state.last_checked_at ? new Date(state.last_checked_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—";

  return (
    <div
      className="sticky top-0 z-[80] bg-gradient-to-r from-amber-500 to-rose-600 text-white shadow-lg"
      role="alert"
      data-testid="llm-health-banner"
    >
      <div className="max-w-7xl mx-auto px-4 py-2 flex items-center gap-3 flex-wrap">
        <AlertTriangle className="h-5 w-5 shrink-0 animate-pulse" />
        <div className="flex-1 min-w-0 text-sm">
          <p className="font-display font-bold leading-tight" data-testid="llm-health-banner-title">
            {label}
            {typeof cost === "number" && typeof max === "number" && (
              <span className="ml-2 text-xs font-mono opacity-90">
                ({cost.toFixed(2)} / {max.toFixed(2)} USD)
              </span>
            )}
          </p>
          <p className="text-xs opacity-90 leading-tight mt-0.5" data-testid="llm-health-banner-instructions">
            Liluvine PRO, auto-réponses WA, OCR KB et planificateur IA sont indisponibles.
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
          title="Masquer (réapparaît au prochain check de 15 min)"
        >
          <XIcon className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
