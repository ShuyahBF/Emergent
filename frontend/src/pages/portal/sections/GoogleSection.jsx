// « Mon compte » : compte Google lié (connexion par Google). Aucun compte Google n'ouvre une session sans avoir été lié ici, une fois connecté ;
// le code de vérification reste demandé. Retirer la liaison demande le mot de passe. Rubrique masquée tant que le serveur n'est pas configuré pour Google.
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Check, Link2, Link2Off, X } from "lucide-react";
import { apiClient } from "@/lib/api";
import PasswordInput from "@/components/PasswordInput";
import { MESSAGES_GOOGLE } from "@/lib/googleConnexion";

export default function GoogleSection() {
  const [etat, setEtat] = useState(null);                 // { disponible, lie, email, lie_le }
  const [mdp, setMdp] = useState("");
  const [retrait, setRetrait] = useState(false);
  const [enCours, setEnCours] = useState(false);
  const charger = useCallback(() => apiClient.get("/auth/google/etat").then((r) => setEtat(r.data)).catch(() => setEtat({ disponible: false })), []);
  useEffect(() => { charger(); }, [charger]);
  if (!etat?.disponible) return null;

  const lier = async () => {
    setEnCours(true);
    toast("Ouverture de Google en cours…");
    try { const r = await apiClient.post("/auth/google/lier-url", { cible: "web" }); window.location.href = r.data.url; }
    catch (e) { toast.error(e?.response?.data?.detail || MESSAGES_GOOGLE.google); setEnCours(false); }
  };
  const retirer = async () => {
    setEnCours(true);
    try { await apiClient.post("/auth/google/delier", { mot_de_passe: mdp }); toast.success("Liaison Google retirée"); setMdp(""); setRetrait(false); await charger(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Retrait impossible"); } finally { setEnCours(false); }
  };

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 space-y-3" data-testid="bloc-google">
      <h3 className="flex items-center gap-2 font-semibold"><Link2 className="h-4 w-4" aria-hidden="true" />Compte Google</h3>
      {etat.lie ? (
        <>
          <p className="text-sm">Lié à <b>{etat.email}</b>. « Se connecter avec Google » remplace le mot de passe ; le code de vérification reste demandé.</p>
          {!retrait ? <button type="button" onClick={() => setRetrait(true)} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm"><Link2Off className="h-4 w-4" />Retirer la liaison</button> : (
            <div className="space-y-2">
              <label className="text-sm" htmlFor="google-mdp">Mot de passe SAWALI (pour confirmer)</label>
              <PasswordInput id="google-mdp" value={mdp} onChange={(e) => setMdp(e.target.value)} autoComplete="current-password" />
              <div className="flex gap-2">
                <button type="button" disabled={enCours || !mdp} onClick={retirer} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue px-3 py-2 text-sm text-white disabled:opacity-50"><Check className="h-4 w-4" />Confirmer</button>
                <button type="button" onClick={() => { setRetrait(false); setMdp(""); }} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm"><X className="h-4 w-4" />Annuler</button>
              </div>
            </div>
          )}
        </>
      ) : (
        <>
          <p className="text-sm text-slate-600">Liez votre compte Google pour vous connecter sans taper votre mot de passe. Google confirme votre identité ; SAWALI ne reçoit jamais votre mot de passe Google.</p>
          <button type="button" disabled={enCours} onClick={lier} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue px-3 py-2 text-sm text-white disabled:opacity-50"><Link2 className="h-4 w-4" />Lier mon compte Google</button>
        </>
      )}
    </section>
  );
}
