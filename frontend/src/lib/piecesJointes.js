// Pièces jointes des demandes (lot 430) : logique PURE (testée, sans écran). Mêmes limites que le serveur de SAWALI :
// 5 pièces par demande, 400 Ko par pièce après compression, images JPEG / PNG / WebP ou PDF.
// Pour un développeur WinDev : ce sont les contrôles faits AVANT l'envoi, pour ne jamais envoyer un fichier que le serveur refuserait.
export const PIECES_MAX = 5;
export const PIECE_MAX_OCTETS = 400 * 1024;
export const TYPES_IMAGES = ["image/jpeg", "image/png", "image/webp"];
export const TYPES_ACCEPTES = [...TYPES_IMAGES, "application/pdf"];
export const ACCEPT = TYPES_ACCEPTES.join(",");

/** Taille lisible : « 312 Ko », « 1,4 Mo ». */
export function formaterTaille(octets) {
  if (!Number.isFinite(octets) || octets < 0) return "—";
  if (octets < 1024) return `${octets} o`;
  if (octets < 1024 * 1024) return `${Math.round(octets / 1024)} Ko`;
  return `${(octets / 1024 / 1024).toFixed(1).replace(".", ",")} Mo`;
}

/** Dimensions après réduction : le grand côté ne dépasse pas `max` (jamais agrandie). */
export function dimensionsCible(largeur, hauteur, max = 1600) {
  const plusGrand = Math.max(largeur, hauteur);
  if (!(plusGrand > 0)) return { largeur: 1, hauteur: 1 };
  const k = plusGrand > max ? max / plusGrand : 1;
  return { largeur: Math.max(1, Math.round(largeur * k)), hauteur: Math.max(1, Math.round(hauteur * k)) };
}

/** Essais de compression, du plus fidèle au plus léger : [{ echelle, qualite }]. On s'arrête au premier qui tient dans la limite. */
export const ESSAIS_COMPRESSION = [1, 0.85, 0.7, 0.55, 0.4].flatMap((echelle) => [0.85, 0.7, 0.55, 0.4].map((qualite) => ({ echelle, qualite })));

/** Vérifie un fichier choisi AVANT de le traiter. Rend un message d'erreur, ou null si le fichier peut être traité. */
export function refuserFichier(fichier, dejaJointes = 0) {
  if (dejaJointes >= PIECES_MAX) return `${PIECES_MAX} pièces jointes au plus par demande`;
  if (!fichier || !TYPES_ACCEPTES.includes(fichier.type)) return `« ${fichier?.name || "fichier"} » : type non accepté (images JPEG, PNG, WebP ou PDF)`;
  if (fichier.type === "application/pdf" && fichier.size > PIECE_MAX_OCTETS) return `« ${fichier.name} » : un PDF doit faire ${PIECE_MAX_OCTETS / 1024} Ko au plus (il fait ${formaterTaille(fichier.size)})`;
  return null;
}

/** Contenu (base64) d'une adresse « data:… » ; chaîne vide si l'adresse est invalide. */
export const base64DeDataUrl = (url) => { const i = String(url || "").indexOf(","); return i >= 0 ? String(url).slice(i + 1) : ""; };

/** Taille en octets d'un contenu base64. */
export const octetsDeBase64 = (b64) => { const s = String(b64 || ""); return Math.floor((s.length * 3) / 4) - (s.endsWith("==") ? 2 : s.endsWith("=") ? 1 : 0); };
