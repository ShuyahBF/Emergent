/*
  Lot 321 — Page publique /suivi-rdv : le patient scanne le QR code de l'écran du hall et suit SON rendez-vous sur son téléphone.
  Identification : numéro de téléphone + 2 lettres de ses initiales (1re lettre du nom + 1re lettre du prénom).
  Le suivi est ouvert de 3 h avant à 3 h après l'heure du rendez-vous ; la page se rafraîchit toute seule toutes les 20 secondes.
  Elle ne montre que son propre rendez-vous (aucune donnée d'un autre patient). API : /suivi-rdv/info et /suivi-rdv/etat.
  Lot 328 — MODE ADMINISTRATEUR : un administrateur connecté à SAWALI qui ouvre cette page est envoyé vers le MÊME écran que la télé
  (/tv-ecran.html?admin=1 : planning par médecin avec photo, Suivi Support), en clair et sans limite de durée. Son téléphone joue le rôle
  d'une télé de contrôle. « /suivi-rdv?patient=1 » force la page patient (pour la tester).
*/
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Stethoscope } from "lucide-react";
import { apiClient, jetonCourant } from "@/lib/api";

const COULEURS = {
  attente: "bg-sky-50 text-sky-900 ring-sky-200",
  en_cours: "bg-emerald-50 text-emerald-900 ring-emerald-300",
  fait: "bg-slate-100 text-slate-700 ring-slate-300",
};

export default function SuiviRdv() {
  const [actif, setActif] = useState(null);                 // null = on vérifie si le service est ouvert
  const [tel, setTel] = useState("");
  const [ini, setIni] = useState("");
  const [etat, setEtat] = useState(null);                   // réponse du serveur (mon rendez-vous)
  const [erreur, setErreur] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const [admin, setAdmin] = useState(false);              // lot 328 : administrateur connecté → redirection vers l'écran de contrôle
  const identifiants = useRef(null);                        // gardés en mémoire seulement (jamais enregistrés sur l'appareil)

  // Lot 328 : un administrateur connecté (route réservée aux admins) est envoyé vers l'écran identique à la télé, en clair
  useEffect(() => {
    if (!jetonCourant() || /[?&]patient=1/.test(window.location.search)) return;
    apiClient.get("/admin/suivi-rdv").then(() => { setAdmin(true); window.location.replace("/tv-ecran.html?admin=1"); }).catch(() => {});
  }, []);

  useEffect(() => {
    apiClient.get("/suivi-rdv/info").then((r) => setActif(!!r.data?.actif)).catch(() => setActif(false));
  }, []);

  // Une lecture de l'état de mon rendez-vous ; `silencieux` = rafraîchissement automatique (pas de roue d'attente)
  const lire = useCallback(async (silencieux = false) => {
    if (!identifiants.current) return;
    if (!silencieux) setEnvoi(true);
    try {
      const r = await apiClient.post("/suivi-rdv/etat", identifiants.current);
      setEtat(r.data); setErreur("");
    } catch (e) {
      const detail = e?.response?.data?.detail;
      if (silencieux && e?.response?.status === 404) {                 // la fenêtre de suivi est terminée
        setEtat(null); identifiants.current = null; setErreur("Le suivi de votre rendez-vous est terminé. Merci !");
      } else setErreur(detail || "Connexion impossible : réessayez dans un instant.");
    } finally { if (!silencieux) setEnvoi(false); }
  }, []);

  useEffect(() => {
    if (!etat) return undefined;
    const t = setInterval(() => lire(true), 20000);
    return () => clearInterval(t);
  }, [etat, lire]);

  const valider = (e) => {
    e.preventDefault();
    identifiants.current = { telephone: tel, initiales: ini };
    lire(false);
  };

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-6" data-testid="suivi-rdv">
      <div className="mx-auto max-w-md space-y-4">
        <h1 className="flex items-center gap-2 text-xl font-bold text-slate-800"><Stethoscope className="h-6 w-6 text-sky-600" /> Suivre mon rendez-vous</h1>
        {admin && <Loader2 className="h-6 w-6 animate-spin text-slate-400 mx-auto" />}
        {!admin && actif === null && <Loader2 className="h-6 w-6 animate-spin text-slate-400 mx-auto" />}
        {!admin && actif === false && <p className="rounded-xl bg-white p-4 text-slate-600 ring-1 ring-slate-200">Ce service n'est pas disponible pour le moment. Adressez-vous à l'accueil.</p>}
        {!admin && actif && !etat && (
          <form onSubmit={valider} className="space-y-3 rounded-xl bg-white p-4 ring-1 ring-slate-200">
            <label className="block text-sm font-medium text-slate-700">Votre numéro de téléphone
              <input type="tel" inputMode="tel" autoComplete="tel" required value={tel} onChange={(e) => setTel(e.target.value)} placeholder="70 00 11 22"
                     className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2.5 text-base" data-testid="suivi-tel" />
            </label>
            <label className="block text-sm font-medium text-slate-700">2 lettres de vos initiales
              <span className="block text-xs font-normal text-slate-500">1re lettre du nom + 1re lettre du prénom (ex. OUEDRAOGO Alphonse → OA)</span>
              <input required maxLength={2} value={ini} onChange={(e) => setIni(e.target.value.replace(/[^a-zA-Z]/g, "").toUpperCase())} placeholder="OA" autoCapitalize="characters"
                     className="mt-1 w-24 rounded-lg border border-slate-300 px-3 py-2.5 text-center text-lg tracking-widest" data-testid="suivi-ini" />
            </label>
            <button type="submit" disabled={envoi} className="w-full rounded-lg bg-sky-600 py-2.5 text-white font-medium disabled:opacity-60" data-testid="suivi-valider">
              {envoi ? "Recherche…" : "Voir mon rendez-vous"}
            </button>
            <p className="text-xs text-slate-500">Le suivi est ouvert de 3 h avant à 3 h après l'heure de votre rendez-vous. Vos informations ne sont pas conservées.</p>
          </form>
        )}
        {!admin && erreur && <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900 ring-1 ring-amber-200" role="alert" data-testid="suivi-erreur">{erreur}</p>}
        {!admin && etat && (
          <div className={`space-y-3 rounded-xl p-5 ring-1 ${COULEURS[etat.etat] || COULEURS.attente}`} data-testid="suivi-carte">
            <p className="text-3xl font-bold" data-testid="suivi-heure">{etat.heure}</p>
            <p className="text-lg font-semibold">{etat.medecin}{etat.porte ? ` — ${etat.porte}` : ""}</p>
            <p className="text-lg" data-testid="suivi-message">{etat.message}</p>
            <p className="text-xs opacity-70">Mise à jour automatique toutes les 20 secondes · suivi ouvert jusqu'à {new Date(etat.valide_jusqua).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}</p>
          </div>
        )}
      </div>
    </div>
  );
}
