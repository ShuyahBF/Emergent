// dossiersHospitalisation.js — Lot 448 : logique PURE (sans écran, sans réseau) de la page web « Loois → Dossiers d'hospitalisation ».
//
// Même méthode que l'écran Loois « Gestion des dossiers d'hospitalisation » (DossiersExamenFormesLogique.cs), validée le 18/11/2026 sur le client IPM
// depuis SAWALI → SQL Distant (chaque requête répond en ~0,4 s) :
//   1. SELECT MAX([Dos_num]) FROM [DOSSIER EXAMEN]                                   → dernier numéro de dossier ;
//   2. fenêtres de 200 numéros, du plus récent au plus ancien (on s'arrête dès que la période est dépassée) ;
//   3. noms des patients : une requête groupée par paquet de codes (table [Patient]).
// Pour un développeur WinDev : ce fichier ressemble à une « collection de procédures globales » ; aucune ne touche l'écran.

/** Nom du fichier HFSQL (avec une ESPACE : toujours entre crochets dans le SQL). */
export const FICHIER = "DOSSIER EXAMEN";
/** Colonnes lues (mêmes que Loois). */
// Lien dossier → patient (précisé par le propriétaire le 18/11/2026) : la colonne [Numéro_Enreg] du dossier correspond à [Numéro_Enreg] de la table [Patient]
// (SELECT * FROM PATIENT WHERE PATIENT.NUMERO_ENREG = [DOSSIER EXAMEN].NUMERO_ENREG). La colonne [Client] n'est PAS le code du patient.
export const COLONNES = "[Dos_num], [Dos_lib], [Da_dépôt], [He_Dépôt], [Montant], [Numéro_Enreg], [Modificateur], [Réglé]";
/** Taille d'une fenêtre de numéros (un résultat distant contient 200 lignes au plus). */
export const TAILLE_FENETRE = 200;
/** Nombre maximal de tranches lues : 80 × 200 = 16 000 numéros (environ 3 mois chez IPM, ~145 dossiers par jour). Au-delà, la lecture est PARTIELLE et l'écran le dit. */
export const FENETRES_MAX = 80;
/** Durée maximale de la lecture des dossiers (millisecondes) : 3 minutes (une tranche prend ~2 s depuis le lot 449.1 : 90 jours ≈ 65 tranches ≈ 2 min 15 s). */
export const BUDGET_MS = 180000;
/** Codes patients par requête de noms (la requête reste bien sous la limite de 4 000 caractères). */
export const PAQUET_PATIENTS = 150;
/** Paquets de noms au plus par lecture (150 × 110 = 16 500 patients : autant que 80 tranches de 200 dossiers). */
export const PAQUETS_MAX = 110;

/** Périodes proposées (liste déroulante : l'ensemble des choix est fini). */
// Retour du propriétaire (18/11/2026) : surtout les 7 derniers jours (choix par défaut), 30, 60 ou 90 jours seulement à de rares occasions.
export const PERIODES = [
  { code: "7", jours: 7, libelle: "7 derniers jours" },
  { code: "30", jours: 30, libelle: "30 derniers jours" },
  { code: "60", jours: 60, libelle: "60 derniers jours" },
  { code: "90", jours: 90, libelle: "90 derniers jours (maximum)" },
];
/** Période choisie au départ. */
export const PERIODE_DEFAUT = "7";

/** Requête du dernier numéro de dossier. */
export const sqlMax = () => `SELECT MAX([Dos_num]) FROM [${FICHIER}]`;

/** Fenêtre de numéros [bas ; haut] (le numéro 1 est le plus petit possible). */
export const fenetre = (haut) => ({ bas: Math.max(1, haut - TAILLE_FENETRE + 1), haut });

/** Requête d'une fenêtre de numéros. */
export const sqlFenetre = (bas, haut) =>
  `SELECT ${COLONNES} FROM [${FICHIER}] WHERE [Dos_num] >= ${Math.trunc(bas)} AND [Dos_num] <= ${Math.trunc(haut)} LIMIT ${TAILLE_FENETRE}`;

/** Repli : toutes les colonnes (si le nom exact d'une colonne est refusé par HFSQL). Les colonnes sont ensuite retrouvées par leur nom, accents et casse ignorés. */
export const sqlFenetreToutes = (bas, haut) =>
  `SELECT * FROM [${FICHIER}] WHERE [Dos_num] >= ${Math.trunc(bas)} AND [Dos_num] <= ${Math.trunc(haut)} LIMIT ${TAILLE_FENETRE}`;

/**
 * Jointure dossiers + patients : DÉSACTIVÉE (propriétaire, 18/11/2026 : « le pilote OLE DB HFSQL ne fait pas de jointure de tables »). Le code reste en réserve ; mettre `true` seulement
 * si une base l'accepte. Désactivée, la page lit les dossiers et, EN PARALLÈLE, les noms des patients par paquets de 150 (lot 449.7), sans requête d'essai.
 */
export const JOINTURE_ACTIVE = false;

/**
 * Dossiers ET noms des patients en UNE requête (propriétaire, 18/11/2026 : « chaque base de données est complète et autonome » : le fichier des dossiers et celui des patients sont dans la même base).
 * LEFT JOIN : un dossier sans patient reste dans la liste (nom vide). Une requête par tranche au lieu de deux : environ deux fois moins de requêtes.
 * Syntaxe non encore éprouvée sur HFSQL : la page essaie cette forme sur la première tranche et se replie sur la lecture en deux temps si elle est refusée.
 */
export const sqlFenetreJointure = (bas, haut) =>
  `SELECT D.[Dos_num], D.[Dos_lib], D.[Da_dépôt], D.[He_Dépôt], D.[Montant], D.[Numéro_Enreg], D.[Modificateur], D.[Réglé], P.[Nom], P.[Prénoms] ` +
  `FROM [${FICHIER}] D LEFT JOIN [Patient] P ON D.[Numéro_Enreg] = P.[Numéro_Enreg] ` +
  `WHERE D.[Dos_num] >= ${Math.trunc(bas)} AND D.[Dos_num] <= ${Math.trunc(haut)} LIMIT ${TAILLE_FENETRE}`;

/** Noms des patients lus dans le résultat d'une jointure : { code: « NOM Prénoms » } ; null si le résultat n'a pas les colonnes Nom, Prénoms et Numéro_Enreg (ce n'est pas une jointure). */
export function lireNomsJointure(lignes, colonnes) {
  const iNom = indexColonne(colonnes, "Nom");
  const iPrenoms = indexColonne(colonnes, "Prénoms");
  const iCode = indexColonne(colonnes, "Numéro_Enreg");
  if (iNom < 0 || iPrenoms < 0 || iCode < 0) return null;
  const noms = {};
  for (const l of lignes || []) {
    const code = Number.parseInt(l[iCode], 10);
    const nom = `${String(l[iNom] || "").trim()} ${String(l[iPrenoms] || "").trim()}`.trim();
    if (Number.isInteger(code) && code > 0 && nom) noms[code] = nom;
  }
  return noms;
}

/** Requête des noms de patients pour une liste de codes (seuls les entiers positifs sont gardés : jamais de texte libre dans le SQL). */
export function sqlPatients(codes) {
  const propres = [...new Set((codes || []).map((c) => Number(c)).filter((n) => Number.isInteger(n) && n > 0))];
  if (propres.length === 0) return null;
  return `SELECT [Numéro_Enreg], [Nom], [Prénoms] FROM [Patient] WHERE [Numéro_Enreg] IN (${propres.join(", ")})`;
}

/**
 * Lecture EN PARALLÈLE des noms (retour du propriétaire, 18/11/2026) : la lecture des dossiers dépose les codes de patients dans une FILE ; un second travail les prend par paquets
 * pendant que les dossiers continuent d'être lus. Renvoie le prochain paquet à interroger (et le RETIRE de la file) : `taille` codes dès que la file en contient assez
 * (jamais de petits paquets : le nombre de requêtes reste le même), ou ce qui reste (moins de `taille`) seulement quand les dossiers sont tous lus (`fini`). Sinon null : rien à faire pour l'instant.
 */
export function prendrePaquet(file, taille, fini) {
  if (file.length >= taille) return file.splice(0, taille);
  if (fini && file.length > 0) return file.splice(0, file.length);
  return null;
}

/** Coupe une liste en paquets de `taille` éléments. */
export function paquets(liste, taille) {
  const sortie = [];
  for (let i = 0; i < liste.length; i += taille) sortie.push(liste.slice(i, i + taille));
  return sortie;
}

/** Nom de colonne comparable : sans accents, sans majuscules, sans « _ » (un pilote qui abîme les accents ne doit pas gêner). */
export const normaliser = (nom) => String(nom || "").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^A-Za-z0-9]/g, "").toLowerCase();

/** Position d'une colonne dans le résultat (-1 si absente). */
export function indexColonne(colonnes, nom) {
  const cible = normaliser(nom);
  return (colonnes || []).findIndex((c) => normaliser(c) === cible);
}

/** Date lue dans une cellule (« 2026-02-14 07:49:13 », « 2026-02-14 » ou « 14/02/2026 ») → « AAAA-MM-JJ », ou "" si illisible. */
export function dateIso(cellule) {
  const t = String(cellule || "").trim();
  let m = t.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) return `${m[1]}-${m[2]}-${m[3]}`;
  m = t.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  if (m) return `${m[3]}-${m[2].padStart(2, "0")}-${m[1].padStart(2, "0")}`;
  return "";
}

/** Heure « HH:MM » d'une cellule (« 07:49:13 » ou « 2026-02-14 07:49:13 »), ou "". */
export function heureCourte(cellule) {
  const m = String(cellule || "").match(/(\d{1,2}):(\d{2})/);
  return m ? `${m[1].padStart(2, "0")}:${m[2]}` : "";
}

/** Nombre lu dans une cellule (virgule ou point décimal), ou null. */
export function nombre(cellule) {
  const t = String(cellule ?? "").replace(/\s/g, "").replace(",", ".");
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

/** Vrai pour « 1 », « vrai », « true », « oui » (colonne « Réglé » : booléen HFSQL rendu en texte). */
export const booleen = (cellule) => /^(1|vrai|true|oui|o)$/i.test(String(cellule || "").trim());

/** Une ligne du résultat → un dossier lisible par l'écran (null si le numéro est illisible). */
export function lireDossier(ligne, colonnes) {
  const cel = (nom) => { const i = indexColonne(colonnes, nom); return i >= 0 ? ligne[i] : ""; };
  const numero = Number.parseInt(cel("Dos_num"), 10);
  if (!Number.isInteger(numero)) return null;
  const date = dateIso(cel("Da_dépôt"));
  const heure = heureCourte(cel("He_Dépôt")) || heureCourte(cel("Da_dépôt"));
  const codePatient = Number.parseInt(cel("Numéro_Enreg"), 10);          // code du patient = Numéro_Enreg du dossier
  return {
    numero,
    libelle: String(cel("Dos_lib") || "").trim(),
    date,                                                       // « AAAA-MM-JJ » (tri chronologique par simple comparaison de texte)
    heure,
    montant: nombre(cel("Montant")),
    codePatient: Number.isInteger(codePatient) && codePatient > 0 ? codePatient : null,
    modificateur: String(cel("Modificateur") || "").trim(),
    regle: booleen(cel("Réglé")),
  };
}

/** Vrai si la fenêtre contient déjà un dossier PLUS ANCIEN que le début de la période : inutile d'aller plus loin (mêmes règles que Loois). */
export function periodeDepassee(dossiers, debutIso) {
  const dates = (dossiers || []).map((d) => d.date).filter(Boolean);
  if (dates.length === 0) return false;
  return dates.reduce((a, b) => (a < b ? a : b)) < debutIso;
}

/** Garde les dossiers de la période [debutIso ; finIso] (un dossier sans date lisible est gardé : on ne cache jamais un dossier à cause d'une date abîmée). */
export const dansLaPeriode = (dossiers, debutIso, finIso) =>
  (dossiers || []).filter((d) => !d.date || (d.date >= debutIso && d.date <= finIso));

/** « AAAA-MM-JJ » de la date `jour` (objet Date) décalée de `moinsJours` jours, en heure locale du navigateur. */
export function jourIso(jour, moinsJours = 0) {
  const d = new Date(jour.getFullYear(), jour.getMonth(), jour.getDate() - moinsJours);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** « AAAA-MM-JJ » → « JJ/MM/AAAA » (affichage français), "—" si vide. */
export function dateFr(iso) {
  const m = String(iso || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : "—";
}

/** Noms des patients lus : [Numéro_Enreg, Nom, Prénoms] → { code: « NOM Prénoms » }. */
export function lireNoms(lignes, colonnes) {
  const iCode = indexColonne(colonnes, "Numéro_Enreg") >= 0 ? indexColonne(colonnes, "Numéro_Enreg") : 0;
  const iNom = indexColonne(colonnes, "Nom") >= 0 ? indexColonne(colonnes, "Nom") : 1;
  const iPrenoms = indexColonne(colonnes, "Prénoms") >= 0 ? indexColonne(colonnes, "Prénoms") : 2;
  const noms = {};
  for (const l of lignes || []) {
    const code = Number.parseInt(l[iCode], 10);
    if (!Number.isInteger(code)) continue;
    const nom = `${String(l[iNom] || "").trim()} ${String(l[iPrenoms] || "").trim()}`.trim();
    if (nom) noms[code] = nom;
  }
  return noms;
}

/** Texte du patient affiché : son nom, sinon « Code n° X » (nom pas encore lu, introuvable ou indisponible), sinon « — ».
 *  (Le lien dossier → patient est la colonne « Numéro_Enreg » ; on n'écrit jamais un nom qu'on n'a pas lu.) */
export const libellePatient = (dossier, noms) =>
  dossier.codePatient === null ? "—" : (noms && noms[dossier.codePatient]) || `Code n° ${dossier.codePatient}`;

/** Dossiers du plus récent au plus ancien (numéro décroissant) : ordre d'affichage par défaut (retour du propriétaire, 18/11/2026). */
export const plusRecentsDabord = (dossiers) => [...(dossiers || [])].sort((a, b) => b.numero - a.numero);

/** Durée « m:ss » à partir de secondes. */
export const dureeMmSs = (secondes) => `${Math.floor(secondes / 60)}:${String(secondes % 60).padStart(2, "0")}`;
