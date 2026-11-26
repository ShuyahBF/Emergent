// ============================================================================
// Lot 465 — CAPTURES D'ÉCRAN ANNOTÉES dans les suivis (outils de calcul et de dessin, sans interface).
// Une capture collée (Ctrl + V) dans le contenu d'un suivi s'ouvre dans une fenêtre d'annotation (flèche, cadre, ovale, crayon, surligneur, texte, masquage) ;
// « Insérer » la téléverse (/me/upload) et la place dans le texte, AVANT l'enregistrement du suivi.
// Ce fichier : les calculs purs (taille, géométrie de la flèche, nom du fichier, réglages) — testés sans navigateur — et le DESSIN des formes sur un canevas.
// Pour un développeur WinDev : un « canevas » est la zone de dessin (comme un champ Image) ; chaque forme est mémorisée dans une liste pour pouvoir
// annuler / rétablir : on redessine l'image de départ puis toutes les formes à chaque changement.
// ============================================================================

export const CLE_FLAGS = "ui_flags_cache_v1";                 // réglages publics gardés par useUIFlags (même clé)
export const LARGEUR_DEFAUT = 1600;                           // largeur maximale (pixels) d'une capture insérée
export const LARGEUR_MIN = 800;
export const LARGEUR_MAX = 2400;

/** Couleurs proposées : nom lu par les lecteurs d'écran + valeur. */
export const COULEURS = [
  { nom: "Rouge", valeur: "#dc2626" }, { nom: "Orange", valeur: "#ea580c" }, { nom: "Jaune", valeur: "#facc15" },
  { nom: "Vert", valeur: "#16a34a" }, { nom: "Bleu", valeur: "#2563eb" }, { nom: "Noir", valeur: "#0f172a" },
];
/** Épaisseurs du trait (pixels, avant mise à l'échelle). */
export const EPAISSEURS = [{ nom: "Fin", valeur: 3 }, { nom: "Moyen", valeur: 6 }, { nom: "Épais", valeur: 10 }];

/** Réglages des captures lus dans le cache des réglages publics : { actives, largeurMax }. Absent ou illisible : fonction active, 1600 px. */
export function lireReglagesCaptures(stockage) {
  let flags = {};
  try { flags = JSON.parse((stockage || globalThis.localStorage).getItem(CLE_FLAGS) || "{}") || {}; } catch { flags = {}; }
  const largeur = Number(flags.suivis_captures_largeur_max);
  return {
    actives: flags.suivis_captures_actives !== false,
    largeurMax: Number.isFinite(largeur) && largeur > 0 ? Math.min(LARGEUR_MAX, Math.max(LARGEUR_MIN, Math.round(largeur))) : LARGEUR_DEFAUT,
  };
}

/** Taille de la capture insérée : réduite si elle dépasse `max` pixels de large (proportions gardées), JAMAIS agrandie. */
export function tailleExport(largeur, hauteur, max = LARGEUR_DEFAUT) {
  if (!(largeur > 0) || !(hauteur > 0)) return { largeur: 0, hauteur: 0 };
  if (largeur <= max) return { largeur: Math.round(largeur), hauteur: Math.round(hauteur) };
  const rapport = max / largeur;
  return { largeur: Math.round(max), hauteur: Math.max(1, Math.round(hauteur * rapport)) };
}

/** Rectangle normalisé : fonctionne quel que soit le sens du glisser (haut-gauche vers bas-droite ou l'inverse). */
export function rectangle(x1, y1, x2, y2) {
  return { x: Math.min(x1, x2), y: Math.min(y1, y2), l: Math.abs(x2 - x1), h: Math.abs(y2 - y1) };
}

/** Les deux pointes de la tête de flèche (trait de x1,y1 vers x2,y2). La tête grandit avec l'épaisseur ; rien à dessiner si le trait est un point. */
export function pointesFleche(x1, y1, x2, y2, epaisseur = 6) {
  const dx = x2 - x1, dy = y2 - y1;
  if (Math.hypot(dx, dy) < 2) return null;
  const angle = Math.atan2(dy, dx);
  const taille = Math.max(14, epaisseur * 3.2);
  const ouverture = Math.PI / 7;
  return [
    { x: x2 - taille * Math.cos(angle - ouverture), y: y2 - taille * Math.sin(angle - ouverture) },
    { x: x2 - taille * Math.cos(angle + ouverture), y: y2 - taille * Math.sin(angle + ouverture) },
  ];
}

/** Nom du fichier téléversé : « capture-20261126-094512.png » (date et heure locales, tri chronologique). */
export function nomFichierCapture(date = new Date()) {
  const d = (n, l = 2) => String(n).padStart(l, "0");
  return `capture-${date.getFullYear()}${d(date.getMonth() + 1)}${d(date.getDate())}-${d(date.getHours())}${d(date.getMinutes())}${d(date.getSeconds())}.png`;
}

/** Vrai si le fichier collé ou déposé est une image que l'on peut annoter. */
export function estImage(fichier) {
  return !!fichier && typeof fichier.type === "string" && fichier.type.startsWith("image/") && fichier.type !== "image/svg+xml";
}

/**
 * Dessine TOUTES les formes sur le contexte du canevas. Chaque forme : { type, couleur, epaisseur, ... } (voir les cas ci-dessous).
 * Types : crayon (points), fleche, cadre, ovale, surligneur (rectangle translucide), masquer (rectangle noir plein), texte.
 */
export function dessinerFormes(ctx, formes) {
  for (const f of formes) {
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = f.couleur;
    ctx.fillStyle = f.couleur;
    ctx.lineWidth = f.epaisseur;
    if (f.type === "crayon" && f.points.length) {
      ctx.beginPath();
      ctx.moveTo(f.points[0].x, f.points[0].y);
      f.points.slice(1).forEach((p) => ctx.lineTo(p.x, p.y));
      if (f.points.length === 1) ctx.lineTo(f.points[0].x + 0.01, f.points[0].y);
      ctx.stroke();
    } else if (f.type === "fleche") {
      ctx.beginPath(); ctx.moveTo(f.x1, f.y1); ctx.lineTo(f.x2, f.y2); ctx.stroke();
      const tete = pointesFleche(f.x1, f.y1, f.x2, f.y2, f.epaisseur);
      if (tete) { ctx.beginPath(); ctx.moveTo(f.x2, f.y2); ctx.lineTo(tete[0].x, tete[0].y); ctx.moveTo(f.x2, f.y2); ctx.lineTo(tete[1].x, tete[1].y); ctx.stroke(); }
    } else if (f.type === "cadre") {
      const r = rectangle(f.x1, f.y1, f.x2, f.y2); ctx.strokeRect(r.x, r.y, r.l, r.h);
    } else if (f.type === "ovale") {
      const r = rectangle(f.x1, f.y1, f.x2, f.y2);
      ctx.beginPath(); ctx.ellipse(r.x + r.l / 2, r.y + r.h / 2, Math.max(1, r.l / 2), Math.max(1, r.h / 2), 0, 0, Math.PI * 2); ctx.stroke();
    } else if (f.type === "surligneur") {
      const r = rectangle(f.x1, f.y1, f.x2, f.y2); ctx.globalAlpha = 0.35; ctx.fillRect(r.x, r.y, r.l, r.h);
    } else if (f.type === "masquer") {
      const r = rectangle(f.x1, f.y1, f.x2, f.y2); ctx.fillStyle = "#000000"; ctx.fillRect(r.x, r.y, r.l, r.h);          // cache une donnée sensible (nom, numéro, montant…)
    } else if (f.type === "texte" && f.texte) {
      const taille = 16 + f.epaisseur * 3;
      ctx.font = `700 ${taille}px "Segoe UI", Arial, sans-serif`;
      ctx.textBaseline = "top";
      ctx.lineWidth = 4; ctx.strokeStyle = "#ffffff"; ctx.strokeText(f.texte, f.x1, f.y1);                              // liseré blanc : lisible sur tout fond
      ctx.fillText(f.texte, f.x1, f.y1);
    }
    ctx.restore();
  }
}
