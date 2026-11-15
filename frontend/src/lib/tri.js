// tri.js — règle 19 (14/11/2026) : sur TOUT tableau qui présente des données, TOUTES les colonnes sont triables quand le type de champ le permet
// (texte, nombre, date). Ce fichier : le tri côté navigateur pour les petits tableaux entièrement chargés ; les tableaux paginés trient côté serveur.
import { useMemo, useState } from "react";

/** Compare deux valeurs : nombres en ordre numérique, textes sans accents ni majuscules (« Étoile » après « Abeille »), chiffres dans les textes comparés comme des nombres. */
export function comparer(a, b) {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), "fr", { sensitivity: "base", numeric: true });
}

/**
 * Trie `lignes` selon `tri` = { cle, sens: "asc" | "desc" } ; `acces` = { cle: (ligne) => valeur }. Les valeurs vides (null, "", « — ») restent TOUJOURS en dernier, quel que soit le sens.
 * Sans tri (tri nul) : ordre d'origine.
 */
export function trierLignes(lignes, tri, acces) {
  if (!tri || !acces[tri.cle]) return lignes;
  const vide = (v) => v === null || v === undefined || v === "" || v === "—";
  const valeur = (l) => acces[tri.cle](l);
  const avec = lignes.filter((l) => !vide(valeur(l)));
  const sans = lignes.filter((l) => vide(valeur(l)));
  avec.sort((x, y) => (tri.sens === "desc" ? -1 : 1) * comparer(valeur(x), valeur(y)));
  return [...avec, ...sans];
}

/** Cycle d'un clic sur un en-tête : croissant → décroissant → ordre d'origine. */
export function basculerTri(tri, cle) {
  if (!tri || tri.cle !== cle) return { cle, sens: "asc" };
  return tri.sens === "asc" ? { cle, sens: "desc" } : null;
}

/** Tri local d'un petit tableau : `const { lignes: triees, tri, basculer } = useTri(lignes, { nom: (l) => l.nom, total: (l) => l.total })`. */
export function useTri(lignes, acces, triInitial = null) {
  const [tri, setTri] = useState(triInitial);
  const triees = useMemo(() => trierLignes(lignes, tri, acces), [lignes, tri]);   // eslint-disable-line react-hooks/exhaustive-deps
  return { lignes: triees, tri, basculer: (cle) => setTri((t) => basculerTri(t, cle)) };
}
