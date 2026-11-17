// Diagramme de Gantt des demandes à SAWALI (lot 117) : une barre par demande, de la date de la demande à la DATE ESTIMÉE de disponibilité de la mise à jour.
// Toutes les barres partagent le MÊME axe du temps (de la plus ancienne demande à la plus lointaine échéance, aujourd'hui compris) : on compare d'un coup d'œil.
// Logique pure, testée (ganttDemandes.test.js). Pour un développeur WinDev : on convertit chaque date en position (0 à 100 %) sur une règle commune.

const JOUR = 86400000;

/** Date ISO (datetime) ou jour « AAAA-MM-JJ » → millisecondes ; null si illisible. Un jour seul vaut midi (pas de décalage de fuseau). */
export function enMs(valeur) {
  if (!valeur) return null;
  const t = String(valeur);
  const d = new Date(t.length <= 10 ? `${t}T12:00:00` : t);
  return Number.isNaN(d.getTime()) ? null : d.getTime();
}

/** Date estimée d'une demande : réalisée → date de réalisation ; remontée → date prévue ; refusée ou sans date → null. */
export function dateEstimee(d) {
  if (d.statut === "realisee") return enMs(d.realisee_le);
  if (d.statut === "remontee" || d.statut === "en_cours") return enMs(d.prevue_le);     // lot 429 : la date prévue vient du planning (durée estimée)
  return null;
}

/** Bornes communes de l'axe : de la plus ancienne demande à la plus lointaine date (ou aujourd'hui), avec une petite marge (au moins 7 jours au total). */
export function bornesGantt(demandes, maintenant = Date.now()) {
  let debut = maintenant; let fin = maintenant;
  for (const d of demandes || []) {
    const a = enMs(d.demandee_le); if (a !== null) debut = Math.min(debut, a);
    const e = dateEstimee(d); if (e !== null) fin = Math.max(fin, e);
  }
  fin = Math.max(fin + 2 * JOUR, debut + 7 * JOUR);
  return { debut, fin };
}

const pourcent = (t, b) => Math.min(100, Math.max(0, ((t - b.debut) / (b.fin - b.debut)) * 100));

/** Position de la ligne « aujourd'hui » (en %). */
export const positionAujourdhui = (b, maintenant = Date.now()) => pourcent(maintenant, b);

/**
 * Barre d'une demande : { gauche, largeur, etat, libelle, jours } (gauche et largeur en %).
 * États : « realisee » (verte, de la demande à la réalisation), « prevue » (bleue, jusqu'à la date prévue), « en_retard » (rouge : date prévue dépassée),
 *         « sans_date » (grise hachurée, de la demande à aujourd'hui : SAWALI n'a pas encore donné de date), « refusee » (barre grise courte, sans date), « a_remonter » (vide).
 */
export function barreGantt(d, b, maintenant = Date.now()) {
  const debut = enMs(d.demandee_le) ?? maintenant;
  const gauche = pourcent(debut, b);
  const sortie = (fin, etat, libelle, jours = null) => {
    const droite = pourcent(Math.max(fin, debut + JOUR), b);            // une barre fait au moins un jour
    return { gauche, largeur: Math.max(droite - gauche, 1.5), etat, libelle, jours };
  };
  const jourFr = (t) => new Date(t).toLocaleDateString("fr-FR");
  if (d.statut === "a_remonter") return { gauche, largeur: 0, etat: "a_remonter", libelle: "Pas encore envoyée à SAWALI", jours: null };
  if (d.statut === "refusee") return sortie(debut + JOUR, "refusee", "Refusée par SAWALI");
  if (d.statut === "point_mort") return sortie(maintenant, "point_mort", "Point mort : le travail est arrêté");
  const fin = dateEstimee(d);
  if (d.statut === "realisee") return sortie(fin ?? maintenant, "realisee", `Réalisée le ${jourFr(fin ?? maintenant)}`);
  if (fin === null) return sortie(maintenant, "sans_date", "Date de disponibilité à venir");
  const reste = Math.ceil((fin - maintenant) / JOUR);
  if (reste < 0) return sortie(fin, "en_retard", `Date prévue dépassée de ${-reste} j (${jourFr(fin)})`, reste);
  return sortie(fin, "prevue", reste === 0 ? `Prévue aujourd'hui (${jourFr(fin)})` : `Prévue le ${jourFr(fin)} (dans ${reste} j)`, reste);
}
