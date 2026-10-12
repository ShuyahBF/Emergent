// =============================================================================
// Reprendre la valeur par défaut d'un champ (règle 9 du propriétaire, 12/10/2026)
// =============================================================================
// Dans TOUT champ de saisie (input / textarea) qui affiche un texte gris par défaut
// (« placeholder ») :
//   - Ctrl + Espace           → recopie ce texte dans le champ, pour le modifier ;
//   - double-clic / double appui (téléphone) sur un champ VIDE → même chose.
// Le texte recopié devient une vraie valeur, que l'on peut corriger puis enregistrer.
// Une infobulle rappelle le raccourci quand le champ est vide.
//
// Installé UNE fois au démarrage du site (installerValeurParDefaut()) : un seul écouteur
// pour toute la page, rien à ajouter champ par champ.
// =============================================================================

// Types de champs concernés (jamais les mots de passe, cases à cocher, fichiers…)
const TYPES_TEXTE = new Set(["text", "search", "email", "tel", "url", "number", ""]);
const INFOBULLE = "Ctrl + Espace (ou double-clic) : reprendre le texte proposé pour le modifier";

// Le champ accepte-t-il qu'on y recopie son texte par défaut ?
function champEligible(el) {
  if (!el || el.disabled || el.readOnly) return false;
  const balise = el.tagName;
  if (balise === "TEXTAREA") return Boolean(el.placeholder);
  if (balise !== "INPUT") return false;
  const type = (el.getAttribute("type") || "").toLowerCase();
  return TYPES_TEXTE.has(type) && Boolean(el.placeholder);
}

// Écrit la valeur comme si l'utilisateur l'avait tapée : React (champs « contrôlés »)
// ne voit un changement que par le « setter » natif suivi d'un événement « input ».
function ecrireValeur(el, valeur) {
  const proto = el.tagName === "TEXTAREA" ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  if (setter) setter.call(el, valeur); else el.value = valeur;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  // Curseur à la fin du texte, prêt à être modifié
  try { el.setSelectionRange(valeur.length, valeur.length); } catch { /* type number : pas de sélection */ }
}

// Recopie le texte par défaut (placeholder) dans le champ
function reprendreDefaut(el) {
  let texte = el.placeholder || "";
  // Champ numérique : on ne garde que le nombre (« 60 », « 5 j » → 5)
  if (el.tagName === "INPUT" && (el.getAttribute("type") || "").toLowerCase() === "number") {
    const nombre = texte.replace(",", ".").match(/-?\d+(\.\d+)?/);
    if (!nombre) return;
    texte = nombre[0];
  }
  ecrireValeur(el, texte);
}

export function installerValeurParDefaut() {
  if (typeof window === "undefined" || window.__valeurParDefautInstallee) return;
  window.__valeurParDefautInstallee = true;

  // 1. Ctrl + Espace dans un champ
  document.addEventListener("keydown", (e) => {
    if (!(e.ctrlKey && (e.code === "Space" || e.key === " "))) return;
    const el = e.target;
    if (!champEligible(el)) return;
    e.preventDefault();
    reprendreDefaut(el);
  }, true);

  // 2. Double-clic (ordinateur) ou double appui (téléphone, via dblclick) sur un champ VIDE
  document.addEventListener("dblclick", (e) => {
    const el = e.target;
    if (!champEligible(el) || el.value) return;
    reprendreDefaut(el);
  }, true);

  // 3. Infobulle de rappel sur les champs vides (sans écraser une infobulle existante)
  document.addEventListener("focusin", (e) => {
    const el = e.target;
    if (!champEligible(el) || el.value) return;
    if (!el.title) { el.title = INFOBULLE; el.dataset.infobulleDefaut = "1"; }
  }, true);
}
