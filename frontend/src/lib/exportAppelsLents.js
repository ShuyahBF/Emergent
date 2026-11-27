// ============================================================================
// Lot 470 — Export COMPLET du tableau « Appels les plus lents » (Paramètres → Performance du serveur), pensé pour être lu par une machine :
//   • JSON : le contexte (période, totaux, objectif) + le classement entier + la description de chaque champ + la mémoire du serveur ;
//   • CSV  : une ligne par route (séparateur « ; », virgule décimale), s'ouvre directement dans Excel.
// Fonctions pures (aucun réseau, aucun écran) : testées dans exportAppelsLents.test.js.
// ============================================================================

// Description de chaque champ : le fichier se comprend sans notice
export const CHAMPS_APPELS = {
  methode: "Méthode HTTP (GET, POST…)",
  route: "Route de l'API, paramètres entre accolades (ex. /api/files/{file_id})",
  appels: "Nombre d'appels mesurés depuis le dernier redémarrage ou la dernière remise à zéro",
  moyenne_ms: "Durée moyenne côté serveur, en millisecondes",
  derniers_ms: "Durées des 5 derniers appels, en millisecondes (le plus ancien d'abord)",
  dernier_ms: "Durée du dernier appel, en millisecondes",
  maximum_ms: "Durée du plus lent des appels, en millisecondes",
  lents: "Nombre d'appels de plus d'1 seconde (objectif : zéro)",
  erreurs: "Nombre d'erreurs serveur (code 5xx)",
  ops_moy: "Nombre moyen de requêtes à la base MongoDB par appel (chacune coûte ~10 ms d'aller-retour Francfort ↔ Paris) : 25 ou plus = route à corriger en priorité",
  ops_max: "Plus grand nombre de requêtes à la base faites par un seul appel",
  base_ms_moy: "Temps moyen CUMULÉ passé dans la base par appel, en millisecondes (peut dépasser la durée de l'appel quand les requêtes se chevauchent)",
};

// Document JSON : `appels` = réponse de GET /admin/performance/appels, `memoire` = réponse de GET /admin/performance/memoire (facultative)
export function appelsEnJson(appels, memoire, exporteLe) {
  return JSON.stringify({
    export: "SAWALI — Performance du serveur : appels les plus lents",
    exporte_le: exporteLe,
    source: appels.source,                       // « direct » (compteurs en mémoire), « releve » (relevé horaire après redémarrage) ou « vide »
    depuis: appels.depuis || null,
    releve_le: appels.releve_le || null,
    objectif_ms: appels.objectif_ms,
    totaux: { routes: appels.routes, appels: appels.appels, appels_de_plus_d_1_s: appels.lents, erreurs_5xx: appels.erreurs },
    memoire: memoire && memoire.lisible ? { utilise_mo: memoire.utilise_mo, limite_mo: memoire.limite_mo, pourcentage: memoire.pourcentage, processus_mo: memoire.processus_mo ?? null } : null,
    boucle: appels.boucle || null,               // réactivité du serveur : retard de la boucle d'événements (près de zéro = tout va bien)
    champs: CHAMPS_APPELS,
    classement: appels.classement || [],         // toutes les routes, de la plus lente (moyenne) à la plus rapide
  }, null, 2);
}

// Document CSV : une ligne par route
export function appelsEnCsv(appels) {
  const entetes = ["Méthode", "Route", "Appels", "Moyenne ms", "5 derniers ms", "Dernier ms", "Maximum ms", "Appels > 1 s", "Erreurs 5xx", "Requêtes base / appel", "Requêtes base max", "Temps base ms"];
  const protege = (c) => { const t = c == null ? "" : String(c); return /[;"\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
  const lignes = (appels.classement || []).map((l) => [l.methode, l.route, l.appels, l.moyenne_ms, (l.derniers_ms || []).join(" "), l.dernier_ms, l.maximum_ms, l.lents, l.erreurs, l.ops_moy, l.ops_max, l.base_ms_moy]);
  return [entetes, ...lignes].map((l) => l.map(protege).join(";")).join("\r\n");
}
