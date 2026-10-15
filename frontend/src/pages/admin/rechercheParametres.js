// rechercheParametres.js — Lot 203 : recherche en texte intégral dans la page Paramètres.
//
// L'index (titre de rubrique → tout son texte affiché) est généré par scripts/indexer-parametres.js avant chaque build.
// Règle : minuscules, sans accent ; TOUS les mots saisis doivent se trouver dans le titre ou dans le contenu de la rubrique.
// Fonction pure (testée) : aucune rubrique n'a besoin d'être montée pour être trouvée.

// Minuscules sans accent ; la longueur du texte est conservée (permet de prélever un extrait dans le texte d'origine)
export const sansAccent = (t) => String(t || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

const _cache = new WeakMap();
const contenuNormalise = (index, titre) => {
  let c = _cache.get(index);
  if (!c) { c = {}; _cache.set(index, c); }
  if (!(titre in c)) c[titre] = sansAccent(index[titre] || "");
  return c[titre];
};

/** null (pas de correspondance), { dans: "tout" } (recherche vide), { dans: "titre" } ou { dans: "contenu", extrait }. */
export const correspondanceRecherche = (titre, recherche, index = {}) => {
  const mots = sansAccent(recherche).split(/\s+/).filter(Boolean);
  if (!mots.length) return { dans: "tout" };
  const t = sansAccent(titre);
  if (mots.every((m) => t.includes(m))) return { dans: "titre" };
  const c = contenuNormalise(index, titre);
  if (!mots.every((m) => t.includes(m) || c.includes(m))) return null;
  // Extrait autour du premier mot trouvé dans le contenu
  const positions = mots.map((m) => c.indexOf(m)).filter((x) => x >= 0).sort((a, b) => a - b);
  const i = positions.length ? positions[0] : 0;
  const brut = index[titre] || "";
  const debut = Math.max(0, i - 50);
  return { dans: "contenu", extrait: `${debut > 0 ? "…" : ""}${brut.slice(debut, i + 110)}${i + 110 < brut.length ? "…" : ""}` };
};
