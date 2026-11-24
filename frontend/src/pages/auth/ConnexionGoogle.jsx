// Page d'arrivée après Google : « /connexion-google?code=… » (ou ?erreur=…, ?lie=1).
// Le code à usage unique est échangé contre un code de vérification (comme après un mot de passe) : on revient alors à la page de connexion à l'étape « code ».
import React, { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft } from "lucide-react";
import { apiClient } from "@/lib/api";
import { MESSAGES_GOOGLE } from "@/lib/googleConnexion";

export default function ConnexionGoogle() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [erreur, setErreur] = useState("");
  const fait = useRef(false);                       // le code ne sert qu'une fois : un seul échange, même si React redessine la page
  const code = params.get("code"), echec = params.get("erreur"), lie = params.get("lie");

  useEffect(() => {
    if (fait.current) return;
    fait.current = true;
    if (lie) { toast.success("Compte Google lié : vous pouvez maintenant vous connecter avec Google."); navigate("/portal/my-account", { replace: true }); return; }
    if (echec || !code) { setErreur(MESSAGES_GOOGLE[echec] || "Connexion par Google impossible."); return; }
    apiClient.post("/auth/google/echange", { code })
      .then((r) => navigate("/login", { replace: true, state: { otp: { session_token: r.data.session_token, dev_otp: r.data.dev_otp || null, message: r.data.message || null } } }))
      .catch((err) => setErreur(err?.response?.data?.detail || "Connexion par Google impossible"));
  }, [code, echec, lie, navigate]);

  return (
    <div className="mx-auto max-w-md px-4 py-16" data-testid="connexion-google">
      {erreur ? (
        <div className="space-y-3 rounded-xl bg-white p-5 text-center shadow">
          <p className="rounded-lg bg-red-50 p-3 text-sm text-red-900">{erreur}</p>
          <Link to="/login" className="inline-flex items-center gap-2 text-sm font-semibold text-sawali-blue"><ArrowLeft className="h-4 w-4" />Retour à la connexion</Link>
        </div>
      ) : <p className="text-center text-sm text-slate-600">Patientez… connexion par Google en cours.</p>}
    </div>
  );
}
