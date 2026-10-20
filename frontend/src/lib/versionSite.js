/*
  versionSite.js — détection d'une nouvelle version du site (lot 264).

  Principe : à chaque déploiement, le build du site produit des fichiers dont le nom change
  (ex. /static/js/main.1a2b3c4d.js). La page ouverte dans le navigateur garde les anciens noms.
  Si la page d'accueil fraîchement téléchargée cite d'autres noms, une nouvelle version est en ligne.
*/

// Extrait l'empreinte (noms des fichiers main.*.js / main.*.css) d'un texte HTML.
// Retourne une chaîne triée et jointe, ou "" si aucun fichier principal n'est trouvé.
export function empreinteHtml(html) {
  const trouves = String(html || "").match(/\/static\/(?:js|css)\/main\.[0-9a-f]+\.(?:js|css)/g) || [];
  return [...new Set(trouves)].sort().join("|");
}

// Empreinte de la page actuellement chargée : lit les balises <script> et <link> du document.
export function empreinteChargee(doc) {
  const morceaux = [];
  doc.querySelectorAll("script[src], link[rel='stylesheet'][href]").forEach((el) => {
    morceaux.push(el.getAttribute("src") || el.getAttribute("href") || "");
  });
  return empreinteHtml(morceaux.join("\n"));
}

// Vrai si une nouvelle version est en ligne : les deux empreintes existent et diffèrent.
// En développement (aucun fichier « main.<hash> »), l'empreinte est vide : jamais d'avertissement.
export function nouvelleVersionDisponible(chargee, enLigne) {
  return !!chargee && !!enLigne && chargee !== enLigne;
}
