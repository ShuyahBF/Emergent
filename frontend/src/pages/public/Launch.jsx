import React, { useEffect, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { Loader2, XCircle, ShieldAlert } from "lucide-react";
import { LOGO_URL } from "@/lib/brand";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Deep-link landing page — resolves the signed token and redirects to the
// right in-app route. Invoked from external apps (e.g. Windows desktop tools)
// via URLs like https://sawali.xyz/launch?t=<jwt>
const ROUTE_BY_ACTION = {
  login: (c) => buildLoginUrl(c),
  rdv: () => "/rdv",
  appointments: () => "/portal/appointments",
  document: () => "/portal/documents",
  intervention: () => "/portal/interventions",
  contact: () => "/contact",
  dashboard: () => "/portal",
  formations: () => "/portal/formations",
  note: () => "/portal/notes/reports",
  status: () => "/uptime",
};

const buildLoginUrl = (claims) => {
  const p = new URLSearchParams();
  if (claims.username) p.set("u", claims.username);
  if (claims.client_code) p.set("c", claims.client_code);
  return `/login${p.toString() ? `?${p.toString()}` : ""}`;
};

export default function Launch() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState(null);

  useEffect(() => {
    const token = params.get("t");
    if (!token) {
      setError({ reason: "missing", label: "Lien invalide", text: "Le paramètre de lien est manquant." });
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const r = await axios.get(`${API}/integrations/resolve-link`, { params: { t: token } });
        if (cancelled) return;
        if (!r.data?.valid) {
          const reason = r.data?.reason || "invalid";
          setError({
            reason,
            label: reason === "expired" ? "Lien expiré" : "Lien invalide",
            text: reason === "expired"
              ? "Ce lien a expiré. Demandez à votre administrateur de le régénérer."
              : "Le lien est mal formé ou altéré.",
          });
          return;
        }
        const builder = ROUTE_BY_ACTION[r.data.action];
        const target = builder ? builder(r.data) : "/";
        // Stash claims in sessionStorage so the destination page (e.g. Login)
        // can consume them to pre-fill fields or show a banner.
        try { sessionStorage.setItem("sawali_launch_claims", JSON.stringify(r.data)); } catch { /* noop */ }
        navigate(target, { replace: true });
      } catch {
        if (!cancelled) {
          setError({ reason: "network", label: "Connexion impossible", text: "Le serveur est injoignable. Réessayez dans un instant." });
        }
      }
    })();
    return () => { cancelled = true; };
  }, [params, navigate]);

  return (
    <div className="min-h-screen bg-[#0E1F3D] text-white flex items-center justify-center p-6" data-testid="launch-page">
      <div className="w-full max-w-md rounded-2xl bg-white/5 ring-1 ring-white/10 p-8 text-center">
        <img src={LOGO_URL} alt="SAWALI" className="h-12 w-12 mx-auto mb-5 rounded-lg ring-1 ring-white/20" />
        {!error ? (
          <>
            <Loader2 className="h-6 w-6 mx-auto mb-3 animate-spin text-sawali-blue-light" />
            <p className="text-sm text-slate-200">Validation du lien sécurisé…</p>
            <p className="text-[11px] text-slate-400 mt-2">Redirection en cours</p>
          </>
        ) : (
          <>
            <div className="h-12 w-12 mx-auto mb-4 rounded-full bg-rose-500/20 flex items-center justify-center">
              {error.reason === "expired" ? (
                <ShieldAlert className="h-6 w-6 text-rose-300" />
              ) : (
                <XCircle className="h-6 w-6 text-rose-300" />
              )}
            </div>
            <h1 className="text-lg font-display font-bold text-rose-200" data-testid="launch-error-label">{error.label}</h1>
            <p className="text-sm text-slate-300 mt-2">{error.text}</p>
            <button
              onClick={() => navigate("/")}
              className="mt-5 inline-flex items-center rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light"
              data-testid="launch-home-button"
            >
              Retour au site
            </button>
          </>
        )}
      </div>
    </div>
  );
}
