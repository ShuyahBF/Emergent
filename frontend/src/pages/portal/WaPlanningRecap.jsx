// 2026-02 fork (P3 recap) — Deep-link auto-login page for the médecin's
// daily planning WhatsApp digest. Reads `?t=<recap-token>`, exchanges it via
// POST /auth/wa-planning-exchange, stores the resulting JWT + user in
// localStorage (through the same keys used by the AuthContext), then
// redirects to `/portal/planning`.
import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { Loader2, AlertTriangle, Calendar } from "lucide-react";

export default function WaPlanningRecap() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [state, setState] = useState({ loading: true, error: null });

  useEffect(() => {
    let alive = true;
    const t = params.get("t") || params.get("token");
    if (!t) {
      setState({ loading: false, error: "Lien invalide — jeton manquant." });
      return () => { alive = false; };
    }
    apiClient
      .post("/auth/wa-planning-exchange", { t })
      .then((r) => {
        if (!alive) return;
        const { access_token, user } = r.data || {};
        if (!access_token || !user) throw new Error("Réponse serveur invalide");
        try {
          localStorage.setItem("sawali_token", access_token);
          localStorage.setItem("sawali_user", JSON.stringify(user));
          sessionStorage.removeItem("sawali_welcome_briefing_seen");
        } catch { /* noop */ }
        // Hard redirect so AuthContext boots with the new token
        window.location.replace("/portal/planning");
      })
      .catch((err) => {
        if (!alive) return;
        const detail = err?.response?.data?.detail || "";
        const msg =
          detail === "Token expired"
            ? "Ce lien a expiré. Il n'est valable que 30 minutes après l'envoi WhatsApp."
            : detail === "Token invalid"
              ? "Ce lien est invalide. Contactez SAWALI si vous pensez qu'il s'agit d'une erreur."
              : detail === "Réservé aux comptes Médecin"
                ? "Ce lien est réservé aux comptes Médecin."
                : (detail || "Erreur pendant l'échange du jeton");
        setState({ loading: false, error: msg });
      });
    return () => { alive = false; };
  }, [params, navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 text-slate-100 p-6" data-testid="wa-recap-page">
      <div className="max-w-md w-full rounded-2xl ring-1 ring-slate-700 bg-slate-900/60 backdrop-blur px-6 py-8 shadow-2xl">
        <div className="flex items-center gap-3 mb-3">
          <Calendar className="h-6 w-6 text-sky-400" />
          <h1 className="font-display font-bold text-lg">Planning WhatsApp</h1>
        </div>
        {state.loading ? (
          <div className="flex items-center gap-3 text-sm text-slate-300" data-testid="wa-recap-loading">
            <Loader2 className="h-4 w-4 animate-spin text-sky-400" />
            Connexion en cours…
          </div>
        ) : state.error ? (
          <div className="space-y-3">
            <div className="flex items-start gap-2 rounded-lg ring-1 ring-rose-500/40 bg-rose-950/40 p-3 text-sm text-rose-200" data-testid="wa-recap-error">
              <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
              <span>{state.error}</span>
            </div>
            <button
              onClick={() => navigate("/login")}
              className="w-full rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold text-sm px-4 py-2 transition"
              data-testid="wa-recap-fallback-login"
            >
              Se connecter manuellement
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
