/*
  Photos de pages prises au téléphone — outils communs (lots 32 et 33) :
  OCR sur Pièces (listes de pointage) et « Créer depuis un document »
  (formulaires, sondages).
*/

export const PHOTO_MAX_PX = 2400;       // même plafond que le serveur (ocr_pointage.PHOTO_MAX_PX)
export const PHOTO_QUALITE = 0.85;

// Tri « naturel » par nom (IMG_2 avant IMG_10) : l'appareil photo numérote les prises
// dans l'ordre, alors que l'ordre de sélection n'est pas garanti.
export const triNaturel = (a, b) => a.name.localeCompare(b.name, "fr", { numeric: true, sensitivity: "base" });

// Photo ? (extension ou type MIME ; « image/* » couvre les photos converties par l'iPhone)
export const estPhoto = (f) => /\.(jpe?g|png|webp)$/i.test(f.name) || (f.type || "").startsWith("image/");

// Réduit une photo de téléphone (souvent 3 à 6 Mo) avant l'envoi : ~0,5 Mo par page,
// orientation EXIF appliquée. En cas d'échec (format que le navigateur ne sait pas lire),
// la photo d'origine est envoyée telle quelle et le serveur donnera un message clair.
export async function reduirePhoto(fichier) {
  try {
    const bitmap = await createImageBitmap(fichier, { imageOrientation: "from-image" });
    const echelle = Math.min(1, PHOTO_MAX_PX / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * echelle);
    canvas.height = Math.round(bitmap.height * echelle);
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close?.();
    const blob = await new Promise((ok) => canvas.toBlob(ok, "image/jpeg", PHOTO_QUALITE));
    if (!blob) return fichier;
    const nom = fichier.name.replace(/\.[^.]*$/, "") + ".jpg";
    return new File([blob], nom, { type: "image/jpeg" });
  } catch {
    return fichier;
  }
}
