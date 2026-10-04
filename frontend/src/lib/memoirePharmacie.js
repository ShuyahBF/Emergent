// utils/memoirePharmacie.js
// -----------------------------
// § demande utilisateur : "Pour l'ouverture des ordonnances dans les
// pharmacies, il faut au moins sauvegarder le nom de la pharmacie dans un
// cookie, ce qui évitera de saisir le nom de la pharmacie pour la
// prochaine ordonnance." — utilisé par la page PUBLIQUE de vérification
// d'ordonnance (pages/public/OfficineOrdonnance.jsx (lot 57, repris de Ster), ouverte par l'officine en
// scannant le QR). Mémorise UNIQUEMENT l'officine (nom + ville), jamais une
// donnée patient ni d'ordonnance.
//   - cookie first-party "sawali_officine" : valeur JSON encodée
//     (encodeURIComponent), durée 1 an, SameSite=Lax, Secure en https ;
//   - localStorage en repli si les cookies sont bloqués (chaque accès
//     protégé par try/catch : jamais d'erreur visible pour l'officine).

const NOM_COOKIE = "sawali_officine";
const CLE_STOCKAGE = "sawali_officine";
const DUREE_SECONDES = 365 * 24 * 3600;

function nettoyer(valeur) {
  if (!valeur || typeof valeur !== "object") return null;
  const nom = String(valeur.nom || "").trim().slice(0, 120);
  if (!nom) return null;
  return { nom, ville: String(valeur.ville || "").trim().slice(0, 80) };
}

function lireCookie() {
  try {
    const morceau = document.cookie.split("; ").find((c) => c.startsWith(`${NOM_COOKIE}=`));
    return morceau ? nettoyer(JSON.parse(decodeURIComponent(morceau.slice(NOM_COOKIE.length + 1)))) : null;
  } catch {
    return null;
  }
}

/** Dernière officine mémorisée sur ce navigateur ({nom, ville}) ou null. */
export function lireOfficineMemorisee() {
  const depuisCookie = lireCookie();
  if (depuisCookie) return depuisCookie;
  try {
    return nettoyer(JSON.parse(window.localStorage.getItem(CLE_STOCKAGE) || "null"));
  } catch {
    return null;
  }
}

/** Mémorise l'officine (cookie 1 an + repli localStorage). */
export function memoriserOfficine({ nom, ville }) {
  const valeur = nettoyer({ nom, ville });
  if (!valeur) return;
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  try {
    document.cookie = `${NOM_COOKIE}=${encodeURIComponent(JSON.stringify(valeur))}; Max-Age=${DUREE_SECONDES}; Path=/; SameSite=Lax${secure}`;
  } catch { /* cookies bloqués : le repli localStorage suffit */ }
  try {
    window.localStorage.setItem(CLE_STOCKAGE, JSON.stringify(valeur));
  } catch { /* stockage bloqué (navigation privée...) : rien à faire */ }
}

/** "Ce n'est pas votre pharmacie ? Effacer" — supprime cookie et repli. */
export function effacerOfficineMemorisee() {
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  try {
    document.cookie = `${NOM_COOKIE}=; Max-Age=0; Path=/; SameSite=Lax${secure}`;
  } catch { /* ignoré */ }
  try {
    window.localStorage.removeItem(CLE_STOCKAGE);
  } catch { /* ignoré */ }
}
