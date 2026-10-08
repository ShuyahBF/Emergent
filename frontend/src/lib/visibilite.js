// visibilite.js — Lot 79.6 : relectures automatiques en pause quand l'onglet est masqué.
//
// Render facture la bande passante : un onglet SAWALI oublié en arrière-plan interrogeait le serveur
// toutes les quelques secondes pour rien. siVisible(fn) renvoie une fonction qui n'appelle fn QUE si la
// page est visible ; la relecture reprend d'elle-même au tic suivant quand on revient sur l'onglet.
// À NE PAS utiliser pour ce qui doit prévenir l'utilisateur onglet masqué (sonneries d'appel,
// notifications WhatsApp, titre de l'onglet avec les non-lus) : ces relectures-là restent actives.
export function pageVisible() {
  // Hors navigateur (tests) : considérée visible
  return typeof document === "undefined" || !document.hidden;
}

export function siVisible(fn) {
  // Enveloppe une fonction de relecture : ignorée tant que l'onglet est masqué
  return (...args) => (pageVisible() ? fn(...args) : undefined);
}
