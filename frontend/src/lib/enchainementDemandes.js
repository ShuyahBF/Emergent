// Vue d'ENCHAÎNEMENT des demandes non terminées (lot 118) : où elles se suivent, se chevauchent, où le travail s'arrête (points morts).
// Logique pure, testée. Pour un développeur WinDev : on place chaque demande sur une règle du temps puis on calcule les « trous » et les suites.
// Limite honnête : aucune dépendance entre demandes n'est saisie ; l'enchaînement est DÉDUIT des dates (une demande « suit » celle qui se termine juste avant son début).
import { enMs, dateEstimee } from "./ganttDemandes";

const JOUR = 86400000;
export const SEUIL_SANS_REPONSE_JOURS = 14;      // demande sans date de SAWALI depuis plus de 14 jours : point mort

/**
 * Demandes NON terminées (ni réalisées, ni refusées), avec début, fin estimée et état. Tri : début croissant.
 * Lot 429 : quand SAWALI a calculé le PLANNING (durée estimée), la barre va du DÉBUT PRÉVU à la FIN PRÉVUE : les demandes s'enchaînent
 * comme dans un vrai diagramme de Gantt. Sans planning, on retombe sur l'ancien calcul (de la date de la demande à la date prévue).
 */
export function demandesOuvertes(demandes, maintenant = Date.now()) {
  return (demandes || [])
    .filter((d) => d.statut !== "realisee" && d.statut !== "refusee")
    .map((d) => {
      const debutPlan = enMs(d.debut_prevu_le || (d.statut === "point_mort" ? d.debut_le : null));
      const finPlan = enMs(d.fin_prevue_le || d.prevue_le);
      const debut = debutPlan ?? enMs(d.demandee_le) ?? maintenant;
      const prevue = dateEstimee({ ...d, prevue_le: d.fin_prevue_le || d.prevue_le });
      let fin = Math.max(prevue ?? maintenant, debut + JOUR);
      let etat = "prevue";
      if (d.statut === "a_remonter") etat = "a_remonter";
      else if (d.statut === "point_mort") { etat = "point_mort_declare"; fin = Math.max(maintenant, debut + JOUR); }     // travail arrêté : de son début à aujourd'hui
      else if (d.statut === "en_cours") etat = prevue !== null && prevue < maintenant ? "en_retard" : "en_cours";
      else if (prevue === null) etat = (maintenant - debut) / JOUR > SEUIL_SANS_REPONSE_JOURS ? "point_mort" : "sans_date";
      else if (prevue < maintenant) etat = "en_retard";
      return { id: d.id, numero: d.numero_sawali || d.id, plateforme: d.plateforme || "", texte: d.texte || "", debut, fin, etat, prevue, planifiee: debutPlan !== null && finPlan !== null };
    })
    .sort((a, b) => a.debut - b.debut || a.fin - b.fin);
}

/** Pour chaque demande : celle qu'elle SUIT (la dernière à se terminer avant son début), pour tracer l'enchaînement. */
export function avecPredecesseurs(ouvertes) {
  return ouvertes.map((d) => {
    const avant = ouvertes.filter((x) => x.id !== d.id && x.fin <= d.debut).sort((a, b) => b.fin - a.fin)[0];
    return { ...d, suit: avant ? avant.id : null };
  });
}

/** POINTS MORTS : périodes de la règle du temps où AUCUNE demande ouverte n'est en cours (trous entre les barres). [{ debut, fin, jours }] */
export function pointsMorts(ouvertes) {
  if (ouvertes.length < 2) return [];
  const triees = [...ouvertes].sort((a, b) => a.debut - b.debut);
  const trous = [];
  let finMax = triees[0].fin;
  for (const d of triees.slice(1)) {
    if (d.debut > finMax) trous.push({ debut: finMax, fin: d.debut, jours: Math.round((d.debut - finMax) / JOUR) });
    finMax = Math.max(finMax, d.fin);
  }
  return trous.filter((t) => t.jours >= 1);
}

/** Bornes de l'axe commun (du début de la plus ancienne ouverte à la fin la plus lointaine, aujourd'hui compris). */
export function bornesEnchainement(ouvertes, maintenant = Date.now()) {
  let debut = maintenant, fin = maintenant;
  for (const d of ouvertes) { debut = Math.min(debut, d.debut); fin = Math.max(fin, d.fin); }
  return { debut, fin: Math.max(fin + 2 * JOUR, debut + 7 * JOUR) };
}

/** Résumé chiffré : nombre ouvertes, en retard, sans réponse (points morts), trous, chaînes. */
export function resume(ouvertes, trous) {
  const nb = (e) => ouvertes.filter((d) => d.etat === e).length;
  return { ouvertes: ouvertes.length, en_cours: nb("en_cours"), en_retard: nb("en_retard"), points_morts: nb("point_mort") + nb("point_mort_declare"), sans_date: nb("sans_date"), a_remonter: nb("a_remonter"),
    trous: trous.length, jours_a_l_arret: trous.reduce((s, t) => s + t.jours, 0) };
}
