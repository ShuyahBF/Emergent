/*
 * Lot 164 — Page publique d'accord WhatsApp : /accord/:jeton
 *
 * Le lien d'accord copié depuis la page Carrousel était un lien wa.me : touché sur un téléphone, il rouvrait
 * seulement WhatsApp. Cette page SAWALI enregistre l'accord : la personne (reconnue par son lien PERSONNEL, signé
 * par le serveur) touche « Oui, j'accepte » ou « Non merci » — ou retire un accord déjà donné.
 * Données lues et écrites par GET / POST /api/public/accord/{jeton} (prénom et 2 derniers chiffres seulement).
 * SAWALI ne coche jamais l'accord à la place de la personne : c'est son propre clic (loi n° 001-2021/AN).
 */
import React, { useEffect, useState } from "react";
import { CheckCircle2, Loader2, MessageCircle, XCircle } from "lucide-react";
import { useParams } from "react-router-dom";
import { apiClient } from "@/lib/api";

export default function AccordWhatsApp() {
  const { jeton } = useParams();
  const [info, setInfo] = useState(null);          // prénom, expéditeur, accord actuel
  const [etat, setEtat] = useState("chargement");  // chargement | pret | invalide
  const [occupe, setOccupe] = useState(false);
  const [fait, setFait] = useState(null);          // résultat du choix : { accepte, message }

  // Lecture du lien (page publique : pas de connexion)
  useEffect(() => {
    let actif = true;
    apiClient.get(`/public/accord/${encodeURIComponent(jeton || "")}`)
      .then((r) => { if (actif) { setInfo(r.data); setEtat("pret"); document.title = "Accord WhatsApp — SAWALI SMART SYSTEMS"; } })
      .catch(() => { if (actif) setEtat("invalide"); });
    return () => { actif = false; };
  }, [jeton]);

  // Enregistre le choix de la personne
  const choisir = async (accepte) => {
    setOccupe(true);
    try {
      const { data } = await apiClient.post(`/public/accord/${encodeURIComponent(jeton)}`, { accepte });
      setFait(data);
    } catch {
      setEtat("invalide");
    } finally {
      setOccupe(false);
    }
  };

  // Attente : jauge qui tourne + « Patientez… »
  if (etat === "chargement") {
    return <div className="flex min-h-[50vh] items-center justify-center gap-3 text-slate-300" role="status"><Loader2 className="h-6 w-6 animate-spin" /> Patientez…</div>;
  }
  if (etat === "invalide") {
    return (
      <div className="mx-auto max-w-xl px-4 py-20 text-center" data-testid="accord-invalide">
        <h1 className="text-3xl font-display font-bold text-white">Ce lien n'est pas valide</h1>
        <p className="mt-3 text-slate-400">Le lien est incomplet ou n'est plus actif. Demandez-en un nouveau à la personne qui vous l'a envoyé.</p>
      </div>
    );
  }
  // Après le choix : confirmation
  if (fait) {
    const Icone = fait.accepte ? CheckCircle2 : XCircle;
    return (
      <div className="mx-auto max-w-xl px-4 py-20 text-center" data-testid="accord-confirmation">
        <Icone className={`mx-auto h-12 w-12 ${fait.accepte ? "text-emerald-400" : "text-slate-400"}`} />
        <h1 className="mt-4 text-3xl font-display font-bold text-white">{fait.accepte ? "Merci, c'est noté" : "C'est noté"}</h1>
        <p className="mt-3 text-slate-300">{fait.message}</p>
      </div>
    );
  }
  return (
    <div className="mx-auto max-w-xl px-4 py-16" data-testid="accord-page">
      <div className="rounded-2xl border border-white/10 bg-white/5 p-8 text-center">
        <MessageCircle className="mx-auto h-10 w-10 text-emerald-400" />
        <h1 className="mt-4 text-2xl font-display font-bold text-white">{info.prenom ? `Bonjour ${info.prenom},` : "Bonjour,"}</h1>
        <p className="mt-3 text-slate-300">
          <b>{info.expediteur}</b> souhaite vous envoyer ses nouveautés et offres sur WhatsApp
          {info.fin_numero ? ` (numéro se terminant par ${info.fin_numero})` : ""}.
        </p>
        <p className="mt-2 text-sm text-slate-400">Vous pourrez arrêter à tout moment en écrivant STOP sur WhatsApp ou en revenant sur cette page.</p>
        {info.accepte === true && <p className="mt-4 rounded bg-emerald-500/10 p-2 text-sm text-emerald-300">Vous avez déjà accepté. Vous pouvez retirer votre accord ci-dessous.</p>}
        {info.accepte === false && <p className="mt-4 rounded bg-slate-500/10 p-2 text-sm text-slate-300">Vous avez refusé de recevoir ces messages. Vous pouvez changer d'avis ci-dessous.</p>}
        <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-center">
          <button type="button" disabled={occupe || info.accepte === true} onClick={() => choisir(true)} data-testid="accord-oui"
                  className="rounded-lg bg-emerald-500 px-6 py-3 font-semibold text-white hover:bg-emerald-400 disabled:opacity-50">
            {occupe ? "Patientez…" : "Oui, j'accepte"}
          </button>
          <button type="button" disabled={occupe || info.accepte === false} onClick={() => choisir(false)} data-testid="accord-non"
                  className="rounded-lg border border-white/20 px-6 py-3 font-semibold text-white hover:bg-white/10 disabled:opacity-50">
            {info.accepte === true ? "Retirer mon accord" : "Non merci"}
          </button>
        </div>
      </div>
    </div>
  );
}
