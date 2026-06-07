// Iter42 — Magic link callback handler.
// User clicks the link in the email; we exchange the URL token for a JWT.
import React from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { officineApi, saveOfficineSession } from "@/lib/officineApi";
import { LOGO_URL } from "@/lib/brand";
import { ShieldAlert, ShieldCheck } from "lucide-react";

export default function OfficineMagicCallback() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [state, setState] = React.useState({ status: "loading", message: "" });

  React.useEffect(() => {
    const token = params.get("token");
    if (!token) {
      setState({ status: "error", message: "Lien invalide — token manquant." });
      return;
    }
    (async () => {
      try {
        const r = await officineApi.get("/officines-portal/auth/magic-callback", { params: { token } });
        saveOfficineSession(r.data.token, r.data.officine);
        setState({ status: "ok", message: "Connecté — redirection..." });
        setTimeout(() => navigate("/officines", { replace: true }), 800);
      } catch (err) {
        setState({
          status: "error",
          message: err?.response?.data?.detail || "Lien invalide ou expiré.",
        });
      }
    })();
  }, [params, navigate]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#0E1F3D] via-[#11264a] to-[#0E1F3D] flex items-center justify-center px-4">
      <div className="bg-white rounded-2xl shadow-2xl p-8 max-w-md text-center" data-testid="officine-magic-callback">
        <img src={LOGO_URL} alt="SAWALI" className="h-12 w-12 mx-auto rounded-lg" />
        {state.status === "loading" && (
          <>
            <div className="mt-4 h-8 w-8 mx-auto border-4 border-slate-200 border-t-sawali-blue rounded-full animate-spin" />
            <p className="mt-4 text-sm text-slate-700">Validation du lien en cours…</p>
          </>
        )}
        {state.status === "ok" && (
          <>
            <ShieldCheck className="mt-4 h-10 w-10 text-emerald-500 mx-auto" />
            <p className="mt-3 text-sm font-medium text-slate-800">{state.message}</p>
          </>
        )}
        {state.status === "error" && (
          <>
            <ShieldAlert className="mt-4 h-10 w-10 text-rose-500 mx-auto" />
            <p className="mt-3 text-sm font-medium text-slate-800">{state.message}</p>
            <button
              onClick={() => navigate("/officines/login", { replace: true })}
              className="mt-4 text-xs px-4 py-2 rounded-lg bg-sawali-blue text-white hover:bg-sawali-blue/90"
              data-testid="officine-magic-back"
            >
              Retour à la connexion
            </button>
          </>
        )}
      </div>
    </div>
  );
}
