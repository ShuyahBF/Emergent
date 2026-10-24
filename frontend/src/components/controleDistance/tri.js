// Lot 283 : tri de la liste des fichiers d'un poste (nom, date/heure de modification, taille).

/** Critères de tri proposés dans l'onglet Fichiers. */
export const CRITERES_TRI = [
  { id: "nom", libelle: "Nom" },
  { id: "modifie", libelle: "Date/heure" },
  { id: "taille", libelle: "Taille" },
];

// Valeur de date comparable : 0 si la date est absente ou illisible (le poste n'a pas pu la lire).
const horodatage = (e) => {
  const t = e?.modifie ? Date.parse(e.modifie) : NaN;
  return Number.isFinite(t) ? t : 0;
};

/**
 * Trie les entrées d'un dossier sans modifier la liste d'origine.
 * - Les dossiers restent toujours regroupés en tête, quel que soit le sens.
 * - critere : "nom" | "modifie" | "taille" ; sens : "asc" | "desc".
 * - Les dossiers n'ont pas de taille : entre eux, le tri par taille retombe sur le nom.
 * - À valeur égale, on départage toujours par le nom (ordre stable et prévisible).
 */
export function trierEntrees(entrees, critere = "nom", sens = "asc") {
  const facteur = sens === "desc" ? -1 : 1;
  const parNom = (a, b) => String(a.nom).localeCompare(String(b.nom), "fr", { numeric: true, sensitivity: "base" });
  const valeur = (a, b) => {
    if (critere === "modifie") return horodatage(a) - horodatage(b);
    if (critere === "taille") return (a.dossier || b.dossier ? 0 : (a.taille || 0) - (b.taille || 0));
    return parNom(a, b);
  };
  return [...(entrees || [])].sort((a, b) => {
    if (!!a.dossier !== !!b.dossier) return a.dossier ? -1 : 1;   // dossiers d'abord
    return facteur * valeur(a, b) || parNom(a, b);
  });
}
