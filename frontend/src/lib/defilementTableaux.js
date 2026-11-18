// =============================================================================
// Tableaux de plus de 30 lignes : barre de défilement dans le tableau (règle du propriétaire, 18/11/2026)
// =============================================================================
// « Dans tes tableaux où il y a plus de 30 lignes, mets des barres de défilement pour limiter la longueur de la page.
//   C'est une règle à considérer partout sur toutes les plateformes. »
//
// Pour un développeur WinDev : un seul module installé au démarrage du site (installerDefilementTableaux()), comme les autres règles
// globales. Il surveille la page ; dès qu'un <table> a PLUS de 30 lignes de données, son conteneur reçoit une hauteur maximale
// (30 lignes + l'en-tête) et une barre de défilement verticale ; l'en-tête reste visible en haut pendant le défilement.
// Rien à ajouter tableau par tableau. Un tableau qui repasse à 30 lignes ou moins retrouve sa hauteur naturelle.
//   - conteneur = l'ancêtre proche qui défile déjà en largeur (overflow-x: auto), sinon le parent s'il ne contient que le tableau ;
//   - exception : <table data-sans-defilement> ;
//   - impression : toutes les lignes sont imprimées (règle dans index.css).
// =============================================================================

export const LIGNES_MAX = 30;
const HAUTEUR_LIGNE_PAR_DEFAUT = 36;     // px, quand la mesure est impossible (tableau masqué)

/** Nombre de lignes de DONNÉES d'un tableau (tbody ; à défaut toutes les lignes sauf celles de l'en-tête). */
export function compterLignes(table) {
  const corps = table.tBodies;
  if (corps && corps.length) return Array.from(corps).reduce((n, tb) => n + tb.rows.length, 0);
  return Array.from(table.rows).filter((r) => !(r.parentElement && r.parentElement.tagName === "THEAD")).length;
}

/** Conteneur qui portera la barre de défilement, ou null si on ne peut pas le déterminer sans risque. */
export function conteneurDeDefilement(table) {
  let el = table.parentElement;
  for (let i = 0; el && i < 3; i += 1, el = el.parentElement) {
    const x = (el.style && el.style.overflowX) || (typeof getComputedStyle === "function" ? getComputedStyle(el).overflowX : "");
    if (x === "auto" || x === "scroll") return el;
  }
  const parent = table.parentElement;
  return parent && parent.children.length === 1 ? parent : null;
}

/** Première couleur de fond non transparente en remontant du th : l'en-tête collant ne doit pas laisser voir les lignes qui défilent dessous. */
function fondEntete(th) {
  for (let el = th; el; el = el.parentElement) {
    const c = typeof getComputedStyle === "function" ? getComputedStyle(el).backgroundColor : "";
    if (c && c !== "transparent" && c !== "rgba(0, 0, 0, 0)") return c;
  }
  return "#ffffff";
}

/** Hauteur de 30 lignes + en-tête, mesurée sur le tableau. */
function hauteurMax(table) {
  const entete = table.tHead ? table.tHead.offsetHeight : 0;
  const lignes = Array.from(table.tBodies).flatMap((tb) => Array.from(tb.rows)).slice(0, LIGNES_MAX);
  const mesure = lignes.reduce((s, r) => s + r.offsetHeight, 0);
  return Math.round((entete || HAUTEUR_LIGNE_PAR_DEFAUT) + (mesure || LIGNES_MAX * HAUTEUR_LIGNE_PAR_DEFAUT)) + 2;
}

/** Applique (ou retire) le défilement d'un tableau selon son nombre de lignes. Rend vrai si le défilement est actif. */
export function appliquer(table) {
  if (!table || table.hasAttribute("data-sans-defilement")) return false;
  const conteneur = conteneurDeDefilement(table);
  if (!conteneur) return false;
  if (compterLignes(table) > LIGNES_MAX) {
    conteneur.style.maxHeight = `${hauteurMax(table)}px`;
    conteneur.style.overflowY = "auto";
    conteneur.setAttribute("data-defilement", "oui");
    conteneur.setAttribute("tabindex", "0");   // défilement possible au clavier
    Array.from(table.querySelectorAll("thead th")).forEach((th) => { th.style.backgroundColor = fondEntete(th); });
    return true;
  }
  if (conteneur.getAttribute("data-defilement") === "oui") {
    conteneur.style.maxHeight = "";
    conteneur.style.overflowY = "";
    conteneur.removeAttribute("data-defilement");
    conteneur.removeAttribute("tabindex");
  }
  return false;
}

/** Parcourt tous les tableaux de la page. */
export function appliquerATous(racine = document) {
  racine.querySelectorAll("table").forEach((t) => { try { appliquer(t); } catch { /* un tableau particulier ne doit jamais bloquer la page */ } });
}

let _installe = false;
/** À appeler UNE fois au démarrage : applique la règle maintenant puis à chaque changement de la page (anti-rebond de 250 ms). */
export function installerDefilementTableaux() {
  if (_installe || typeof document === "undefined" || typeof MutationObserver === "undefined") return;
  _installe = true;
  let minuteur = null;
  const planifier = () => { clearTimeout(minuteur); minuteur = setTimeout(() => appliquerATous(), 250); };
  new MutationObserver(planifier).observe(document.body, { childList: true, subtree: true });
  window.addEventListener("load", planifier);
  planifier();
}
