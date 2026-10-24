// =====================================================================
// Lot 281 — Contrôle à distance : REPRISE et historique des transferts de fichiers (sans affichage).
// Pour un développeur WinDev : « procédures globales » de la liste des transferts du volet « Fichiers ».
//   - un fichier RÉCUPÉRÉ du poste est reçu par morceaux gardés en mémoire (« partiel ») ; si la liaison tombe, le partiel reste là
//     (tant que la page est ouverte) et « Reprendre » demande au poste la FIN du fichier (depuis = octets déjà reçus) ;
//   - un fichier ENVOYÉ au poste est gardé sur le poste en « nom.partiel » ; « Reprendre » redemande combien d'octets il a (« fichier_pret »)
//     et renvoie la fin ;
//   - dans les deux cas, si le fichier a changé entre-temps (date de modification), le transfert repart du début.
// =====================================================================

/** Fichiers partiellement reçus du poste, gardés tant que la page est ouverte : clé « poste|chemin » → {nom, taille, modifie, morceaux, recu}. */
export const partielsReception = new Map();

export const clePartiel = (posteId, chemin) => `${posteId || ""}|${chemin || ""}`;

/**
 * Début de réception annoncé par le poste (« fichier_debut » : nom, taille, depuis, modifie).
 * Le partiel existant est CONTINUÉ seulement si le poste reprend exactement là où on s'est arrêté (même taille, même date de modification) ;
 * sinon un partiel neuf commence (le poste repart du début).
 */
export function debutReception(partiels, cle, m) {
  const depuis = Number(m.depuis) || 0;
  const modifie = Number(m.modifie) || 0;
  const taille = Number(m.taille) || 0;
  const p = partiels.get(cle);
  if (depuis > 0 && p && p.recu === depuis && p.taille === taille && p.modifie === modifie) return { partiel: p, repris: true };
  const neuf = { nom: m.nom, taille, modifie, morceaux: [], recu: 0 };
  partiels.set(cle, neuf);
  return { partiel: neuf, repris: false };
}

/** Ce qu'il faut demander au poste pour reprendre un fichier : { depuis, modifie } (0 / 0 = depuis le début). */
export function departDemande(partiels, cle) {
  const p = partiels.get(cle);
  return p && p.recu > 0 && p.recu < p.taille && p.modifie ? { depuis: p.recu, modifie: p.modifie } : { depuis: 0, modifie: 0 };
}

/** Un transfert est-il REPRENABLE ? Envoi : le fichier du technicien est encore en mémoire ; réception : des octets sont gardés. */
export function reprenable(t, partiels = partielsReception) {
  if (t.sens === "envoi") return Boolean(t.fichier);
  const p = t.cle ? partiels.get(t.cle) : null;
  return Boolean(p && p.recu > 0 && p.recu < p.taille);
}

/** La liaison est tombée : les transferts en cours deviennent « interrompus » (reprenables ou non), jamais « en cours » à jamais. */
export function interrompre(liste, partiels = partielsReception) {
  return liste.map((x) => (x.fini || x.erreur ? x : { ...x, erreur: "connexion interrompue", interrompu: true, reprenable: reprenable(x, partiels) }));
}

/**
 * Efface des lignes de l'historique : une ligne (`uid`) ou toutes (`tout`). Seules les lignes TERMINÉES ou en ÉCHEC sont retirées :
 * un transfert en cours n'est jamais effacé. Renvoie { liste, retires } ; `retires` sert à libérer la mémoire des partiels.
 */
export function effacerTransferts(liste, { uid = null, tout = false } = {}) {
  const retirable = (x) => Boolean(x.fini || x.erreur);
  const retires = liste.filter((x) => retirable(x) && (tout || x.uid === uid));
  return { liste: liste.filter((x) => !retires.includes(x)), retires };
}

/** Libère les partiels des lignes retirées (échecs : les octets gardés ne servent plus). */
export function oublierPartiels(retires, partiels = partielsReception) {
  retires.forEach((x) => { if (x.sens === "reception" && x.cle && !x.fini) partiels.delete(x.cle); });
}
