/*
  Lot 321 — Page publique /suivi-rdv : le patient scanne le QR code de l'écran du hall et suit SON rendez-vous sur son téléphone.
  Identification : numéro de téléphone + 2 lettres de ses initiales (1re lettre du nom + 1re lettre du prénom).
  Le suivi est ouvert de 3 h avant à 3 h après l'heure du rendez-vous ; la page se rafraîchit toute seule toutes les 20 secondes.
  Elle ne montre que son propre rendez-vous (aucune donnée d'un autre patient). API : /suivi-rdv/info et /suivi-rdv/etat.
  Lot 327 — MODE ADMINISTRATEUR : un administrateur connecté à SAWALI qui ouvre cette page voit TOUS les rendez-vous en clair
  (nom, téléphone), sans fenêtre de 3 h, même service patient éteint ; son téléphone joue le rôle d'une télé de contrôle.
  Chaque ligne montre aussi la phrase que verrait le patient. API : /admin/suivi-rdv/apercu (réservée aux admins).
*/
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, ShieldCheck, Stethoscope } from "lucide-react";
import { apiClient, jetonCourant } from "@/lib/api";

const COULEURS = {
  attente: "bg-sky-50 text-sky-900 ring-sky-200",
  en_cours: "bg-emerald-50 text-emerald-900 ring-emerald-300",
  fait: "bg-slate-100 text-slate-700 ring-slate-300",
};

const ETATS_ADMIN = {
  attente: { libelle: "En attente", classe: "bg-sky-50 text-sky-900 ring-sky-200" },
  en_cours: { libelle: "En consultation", classe: "bg-emerald-50 text-emerald-900 ring-emerald-300" },
  fait: { libelle: "Terminé", classe: "bg-slate-100 text-slate-600 ring-slate-300" },
  annule: { libelle: "Annulé", classe: "bg-rose-50 text-rose-800 ring-rose-200" },
};
const HORIZONS = [[1, "Jour"], [3, "3 jours"], [7, "Semaine"]];

// Vue ADMINISTRATEUR (lot 327) : tous les rendez-vous en clair, regroupés par jour puis par médecin, rafraîchis toutes les 20 s
function VueAdmin({ donnees, jours, setJours, rafraichir }) {
  const groupes = {};                                              // jour → médecin → lignes
  donnees.rdv.forEach((r) => { ((groupes[r.jour] ||= {})[r.medecin] ||= []).push(r); });
  return (
    <div className="space-y-3" data-testid="suivi-admin">
      <div className="flex items-center gap-2 rounded-xl bg-indigo-50 p-3 text-sm text-indigo-900 ring-1 ring-indigo-200">
        <ShieldCheck className="h-5 w-5 shrink-0" />
        <p><b>Mode administrateur</b> — tout est en clair et sans limite de durée. Les patients, eux, ne voient que leur propre rendez-vous.
          {!donnees.service_patient_actif && " Le service patient est éteint (Paramètres → Écrans TV)."}</p>
      </div>
      <div className="flex gap-2" role="group" aria-label="Période affichée">
        {HORIZONS.map(([n, nom]) => (
          <button key={n} type="button" onClick={() => setJours(n)} data-testid={`suivi-admin-jours-${n}`} aria-pressed={jours === n}
                  className={`flex-1 rounded-lg border px-3 py-2 text-sm font-medium ${jours === n ? "border-indigo-600 bg-indigo-600 text-white" : "border-slate-300 bg-white text-slate-700"}`}>{nom}</button>
        ))}
        <button type="button" onClick={rafraichir} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700" data-testid="suivi-admin-actualiser">Actualiser</button>
      </div>
      {donnees.rdv.length === 0 && <p className="rounded-xl bg-white p-4 text-slate-600 ring-1 ring-slate-200">Aucun rendez-vous sur cette période.</p>}
      {Object.entries(groupes).map(([jour, parMedecin]) => (
        <section key={jour} className="space-y-2">
          <h2 className="text-sm font-semibold text-slate-700">{new Date(`${jour}T12:00:00Z`).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" })}</h2>
          {Object.entries(parMedecin).map(([medecin, lignes]) => (
            <div key={medecin} className="space-y-1.5">
              <p className="text-sm font-medium text-slate-600">{medecin}{lignes[0].porte ? ` — ${lignes[0].porte}` : ""}</p>
              {lignes.map((r) => {
                const e = ETATS_ADMIN[r.etat] || ETATS_ADMIN.attente;
                return (
                  <div key={r.id} className={`space-y-0.5 rounded-xl p-3 ring-1 ${e.classe}`} data-testid="suivi-admin-ligne">
                    <div className="flex items-baseline justify-between gap-2">
                      <p className="text-lg font-bold">{r.heure}</p>
                      <p className="text-xs font-medium">{e.libelle}{r.dans_fenetre ? " · suivi ouvert au patient" : ""}</p>
                    </div>
                    <p className="font-semibold">{r.patient}{r.telephone ? ` · ${r.telephone}` : ""}</p>
                    {r.motif && <p className="text-sm opacity-80">{r.motif}</p>}
                    {r.message && <p className="text-xs opacity-70">Le patient lit : « {r.message} »</p>}
                  </div>
                );
              })}
            </div>
          ))}
        </section>
      ))}
      <p className="text-xs text-slate-500">Mise à jour automatique toutes les 20 secondes.</p>
    </div>
  );
}

export default function SuiviRdv() {
  const [actif, setActif] = useState(null);                 // null = on vérifie si le service est ouvert
  const [tel, setTel] = useState("");
  const [ini, setIni] = useState("");
  const [etat, setEtat] = useState(null);                   // réponse du serveur (mon rendez-vous)
  const [erreur, setErreur] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const [admin, setAdmin] = useState(null);               // lot 327 : aperçu administrateur (null = pas administrateur)
  const [jours, setJours] = useState(1);
  const identifiants = useRef(null);                        // gardés en mémoire seulement (jamais enregistrés sur l'appareil)

  // Lot 327 : si un administrateur est connecté, on charge l'aperçu complet (sinon : page patient normale)
  const lireAdmin = useCallback(async () => {
    if (!jetonCourant()) return;
    try { setAdmin((await apiClient.get("/admin/suivi-rdv/apercu", { params: { jours } })).data); }
    catch { setAdmin(null); }
  }, [jours]);
  useEffect(() => {
    lireAdmin();
    const t = setInterval(lireAdmin, 20000);
    return () => clearInterval(t);
  }, [lireAdmin]);

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
        {admin && <VueAdmin donnees={admin} jours={jours} setJours={setJours} rafraichir={lireAdmin} />}
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
