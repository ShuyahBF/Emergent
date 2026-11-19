// htmlLectureSeule.js — Lot 451 : prépare un contenu HTML pour un affichage en LECTURE SEULE (fenêtre de la recherche du tableau de bord).
// Le contenu d'un rapport ou d'une note peut avoir été écrit par un AUTRE utilisateur : on retire tout ce qui pourrait s'exécuter
// (scripts, cadres, gestionnaires d'événements « onclick… », adresses « javascript: ») et tout ce qui se saisit (champs, boutons).
// Pour un développeur WinDev : c'est un « filtre » appliqué au texte riche avant de l'afficher, pour qu'il ne reste que de la mise en forme.

const BALISES_INTERDITES = ["script", "style", "iframe", "object", "embed", "link", "meta", "base", "form", "input", "button", "textarea", "select", "svg", "math"];

/** Rend le HTML nettoyé. `analyseur` : fonction qui transforme un texte en document (par défaut celle du navigateur) — remplaçable dans les tests. */
export function nettoyerHtml(html, analyseur = (t) => new DOMParser().parseFromString(t, "text/html")) {
  if (!html) return "";
  const doc = analyseur(String(html));
  // 1) balises dangereuses ou de saisie : retirées avec leur contenu
  doc.querySelectorAll(BALISES_INTERDITES.join(",")).forEach((n) => n.remove());
  // 2) attributs : aucun gestionnaire d'événement, aucune adresse « javascript: » / « data: » (sauf image), rien de modifiable
  doc.querySelectorAll("*").forEach((n) => {
    [...n.attributes].forEach((a) => {
      const nom = a.name.toLowerCase();
      const valeur = String(a.value || "").replace(/[\u0000- ]/g, "").toLowerCase();
      const adresse = ["href", "src", "xlink:href", "action", "formaction"].includes(nom);
      if (nom.startsWith("on") || nom === "contenteditable" || nom === "srcdoc"
        || (adresse && (valeur.startsWith("javascript:") || valeur.startsWith("vbscript:") || (valeur.startsWith("data:") && !valeur.startsWith("data:image/"))))) {
        n.removeAttribute(a.name);
      }
    });
    // Un lien s'ouvre dans un nouvel onglet, sans donner la main à la page ouverte
    if (n.tagName === "A") { n.setAttribute("target", "_blank"); n.setAttribute("rel", "noopener noreferrer"); }
  });
  return doc.body.innerHTML;
}
