// components/vidal/ChronoSaisie.jsx
// ------------------------------------
// Lot 56.4 — chronomètre de saisie, demande du propriétaire pour la recette du
// mode « Validation VIDAL » (il mesure lui-même le temps de saisie du médecin).
// Utilisé par « Sécurisation VIDAL » et « Analyse prescription ».
//
// Fonctionnement :
//   - AFFICHÉ UNIQUEMENT en mode « Validation VIDAL » (chargerEtatValidation) ;
//   - DÉMARRE à la première modification d'une donnée clinique ou de
//     prescription (la page fournit une « signature » de sa saisie : toute
//     variation de cette signature = une modification), ou à la sélection
//     d'un patient (`demarrer()`) ;
//   - s'affiche EN DIRECT (mm:ss) ;
//   - S'ARRÊTE au clic sur le bouton d'action (`arreter()`) et affiche alors
//     « Durée de saisie : mm:ss » ;
//   - si l'analyse est refusée pour une saisie à corriger, la page appelle
//     `reprendre()` : le chrono continue depuis son départ (le temps de
//     correction fait partie de la saisie) ;
//   - REPART DE ZÉRO pour un nouveau patient (`demarrer()` ou
//     `reinitialiser()`) ou à la première modification qui suit l'analyse.

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Timer } from "lucide-react";
import { chargerEtatValidation } from "./BandeauValidationVidal";

/** 125 000 ms -> "02:05" (les minutes peuvent dépasser 59 : "75:12"). */
export function formaterDuree(ms) {
  const secondes = Math.max(0, Math.floor((ms || 0) / 1000));
  const mm = String(Math.floor(secondes / 60)).padStart(2, "0");
  const ss = String(secondes % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

/**
 * Logique du chronomètre. `signature` = texte résumant la saisie de la page
 * (données cliniques + prescription) : il change à chaque modification.
 * Renvoie { actif, debut, fin, maintenant, demarrer, arreter, reprendre, reinitialiser }.
 */
export function useChronoSaisie(signature) {
  // Mode « Validation VIDAL » de l'établissement : sinon rien n'est mesuré ni affiché.
  const [actif, setActif] = useState(false);
  useEffect(() => {
    let vivant = true;
    chargerEtatValidation().then((etat) => { if (vivant) setActif(!!etat?.mode_validation); });
    return () => { vivant = false; };
  }, []);

  const [debut, setDebut] = useState(null); // horodatage du départ (ms) ou null
  const [fin, setFin] = useState(null); // horodatage de l'arrêt (ms) ou null
  const [maintenant, setMaintenant] = useState(Date.now());
  // Dernière signature connue : une signature différente = une modification de la saisie.
  const signatureRef = useRef(signature);

  // Détection des modifications de la saisie.
  useEffect(() => {
    if (signature === signatureRef.current) return;
    signatureRef.current = signature;
    if (!actif) return;
    if (debut == null || fin != null) {
      // Première modification, ou nouvelle saisie après l'analyse : départ à zéro.
      setDebut(Date.now());
      setFin(null);
    }
  }, [signature, actif, debut, fin]);

  // Affichage en direct : rafraîchi toutes les 250 ms tant que le chrono tourne.
  useEffect(() => {
    if (debut == null || fin != null) return undefined;
    const minuteur = setInterval(() => setMaintenant(Date.now()), 250);
    return () => clearInterval(minuteur);
  }, [debut, fin]);

  // Sélection d'un patient : départ (ou redépart) à zéro.
  const demarrer = useCallback(() => {
    setDebut(Date.now());
    setFin(null);
    setMaintenant(Date.now());
  }, []);
  // Clic sur le bouton d'action : arrêt (sans effet si rien n'a été saisi).
  const arreter = useCallback(() => {
    setFin((f) => f ?? Date.now());
  }, []);
  // Analyse refusée (saisie à corriger) : le chrono continue depuis son départ.
  const reprendre = useCallback(() => {
    setFin(null);
    setMaintenant(Date.now());
  }, []);
  // Nouveau patient vide : retour à « en attente », la signature fournie devient la référence.
  const reinitialiser = useCallback((signatureVide) => {
    if (signatureVide !== undefined) signatureRef.current = signatureVide;
    setDebut(null);
    setFin(null);
  }, []);

  return { actif, debut, fin, maintenant, demarrer, arreter, reprendre, reinitialiser };
}

/** Affichage du chronomètre (rien hors mode « Validation VIDAL »). */
export default function ChronoSaisie({ chrono }) {
  if (!chrono?.actif) return null;
  const { debut, fin, maintenant } = chrono;
  const arrete = debut != null && fin != null;
  const duree = debut == null ? 0 : (fin ?? maintenant) - debut;
  const texte = debut == null
    ? "Chronomètre de saisie : 00:00 — démarre à la première saisie ou au choix du patient"
    : arrete ? `Durée de saisie : ${formaterDuree(duree)}` : `Saisie en cours : ${formaterDuree(duree)}`;
  return (
    <div
      role="timer"
      aria-live="off"
      data-testid="chrono-saisie"
      data-etat={debut == null ? "attente" : arrete ? "arrete" : "en-cours"}
      style={{
        display: "inline-flex", alignItems: "center", gap: 8, padding: "6px 12px", borderRadius: 999,
        fontSize: 13, fontVariantNumeric: "tabular-nums",
        // Vert du mode validation quand la durée est figée, bleu clair pendant la saisie.
        background: arrete ? "#15803d" : "rgba(56, 189, 248, 0.16)",
        color: arrete ? "#ffffff" : "inherit",
        border: arrete ? "1px solid #166534" : "1px solid rgba(56, 189, 248, 0.45)",
      }}
    >
      <Timer size={15} />
      <span style={{ fontWeight: arrete ? 700 : 500 }}>{texte}</span>
    </div>
  );
}
