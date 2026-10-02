import { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api";

// ---------------------------------------------------------------------------
// Lot 50 — Maintenance de la plateforme (déconnexion programmée de tous les
// utilisateurs, règle R8 ; même comportement qu'adLyn).
// L'état est lu sur la route PUBLIQUE /maintenance/etat toutes les 15 secondes
// et au retour sur l'onglet ; le décompte est recalculé chaque seconde dans le
// navigateur, CALÉ SUR L'HEURE DU SERVEUR (maintenant_serveur) : une horloge
// d'ordinateur mal réglée ne décale donc pas la déconnexion.
// Phases : aucune -> annonce (modale fermable) -> verrouillage (écran bloqué)
//          -> maintenance (déconnexion forcée, connexions bloquées).
// ---------------------------------------------------------------------------
export const INTERVALLE_LECTURE_MS = 15000;
// Événement émis après une action du super-admin (annonce, annulation, réactivation) :
// tous les écrans ouverts relisent aussitôt l'état
export const EVENEMENT_MAINTENANCE = "sawali:maintenance";

export function signalerChangementMaintenance() {
  window.dispatchEvent(new Event(EVENEMENT_MAINTENANCE));
}

/** Phase à l'instant `maintenant` (ms, heure du serveur) d'après les dates de l'annonce. */
export function phaseA(etat, maintenant) {
  if (!etat?.active) return "aucune";
  if (maintenant >= Date.parse(etat.echeance)) return "maintenance";
  if (maintenant >= Date.parse(etat.debut_verrouillage)) return "verrouillage";
  return "annonce";
}

/** Décompte « mm:ss » (ou « h:mm:ss » au-delà d'une heure). */
export function formatDecompte(secondes) {
  const s = Math.max(0, Math.floor(secondes || 0));
  const h = Math.floor(s / 3600);
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** Heure locale lisible (« 14:05:30 ») d'une date ISO ou d'un nombre de millisecondes. */
export function heureLocale(date) {
  if (date === null || date === undefined || date === "") return "";
  return new Date(date).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** Durée lisible : « 4 min », « 1 min 30 s », « 45 s ». */
export function dureeLisible(secondes) {
  const s = Math.round(secondes);
  const m = Math.floor(s / 60);
  const r = s % 60;
  if (!m) return `${r} s`;
  return r ? `${m} min ${r} s` : `${m} min`;
}

/**
 * Suivi de l'état de maintenance (actif = false : aucune lecture, ex. visiteur du portail).
 * Renvoie { etat, phase, secondes, maintenantServeur, recharger }.
 * `source` permet de lire une autre route qui renvoie le même état (écran du super-admin).
 */
export function useEtatMaintenance(actif = true, source = "/maintenance/etat") {
  const [etat, setEtat] = useState(null);
  const [, setTic] = useState(0);
  // Écart (ms) entre l'heure du serveur et celle du navigateur
  const decalage = useRef(0);

  const recharger = useCallback(async () => {
    const avant = Date.now();
    try {
      // Requête automatique : ne compte pas comme une activité de l'utilisateur
      const { data } = await apiClient.get(source, { headers: { "X-Requete-Fond": "1" } });
      const apres = Date.now();
      // Heure du serveur rapportée au milieu de l'aller-retour
      decalage.current = Date.parse(data.maintenant_serveur) - (avant + apres) / 2;
      setEtat(data);
      return data;
    } catch {
      return null; // serveur injoignable : on garde le dernier état connu
    }
  }, [source]);

  useEffect(() => {
    if (!actif) { setEtat(null); return undefined; }
    recharger();
    const lecture = setInterval(recharger, INTERVALLE_LECTURE_MS);
    const tic = setInterval(() => setTic((n) => n + 1), 1000);
    const auRetour = () => { if (document.visibilityState !== "hidden") recharger(); };
    window.addEventListener("focus", auRetour);
    document.addEventListener("visibilitychange", auRetour);
    window.addEventListener(EVENEMENT_MAINTENANCE, recharger);
    return () => {
      clearInterval(lecture);
      clearInterval(tic);
      window.removeEventListener("focus", auRetour);
      document.removeEventListener("visibilitychange", auRetour);
      window.removeEventListener(EVENEMENT_MAINTENANCE, recharger);
    };
  }, [actif, recharger]);

  const maintenantServeur = Date.now() + decalage.current;
  const phase = phaseA(etat, maintenantServeur);
  const secondes = etat?.active ? Math.max(0, Math.ceil((Date.parse(etat.echeance) - maintenantServeur) / 1000)) : 0;
  return { etat, phase, secondes, maintenantServeur, recharger };
}
