// ============================================================================
// Lot 471 — Sonde réseau : envoi des mesures en attente, avec classement des réponses du serveur. PUR (aucun réseau ni écran) : testé dans sondeEnvoi.test.js.
// Constat (avis du 26/11/2026) : la page est laissée ouverte toute la nuit sur un PC ; la session de l'administrateur expire (12 h ou inactivité). Avant ce lot,
// toute réponse 4xx faisait ABANDONNER la mesure : après l'expiration, chaque mesure disparaissait sans rien dire. Maintenant :
//   2xx                      → envoyée ;
//   401 / 403 / 503          → l'accès est en cause (session expirée, clé fausse ou non configurée) : on GARDE toutes les mesures et on le DIT (bandeau rouge) ;
//   réseau coupé / 5xx       → on garde et on réessaie au prochain cycle ;
//   422 (incohérente) / 429 (trop rapprochée) → cette mesure-là est abandonnée (la renvoyer ne servirait à rien), on continue.
// ============================================================================
export const FILE_MAX = 50;            // mesures gardées en attente au plus (≈ 12 heures à une mesure par quart d'heure)

// `envoyeur(mesure)` rend { status } (0 = pas de réponse du tout : réseau coupé). Rend { reste, alerte } : `alerte` vaut null, "acces", "serveur" ou "reseau".
export async function viderFile(file, envoyeur) {
  const reste = [];
  let alerte = null;
  const enAttente = file.slice(-FILE_MAX);
  for (let i = 0; i < enAttente.length; i += 1) {
    const m = enAttente[i];
    let status = 0;
    try { status = (await envoyeur(m)).status; } catch { status = 0; }
    if (status >= 200 && status < 300) continue;                                          // envoyée
    if (status === 401 || status === 403 || status === 503) { alerte = "acces"; reste.push(...enAttente.slice(i)); break; }   // accès : on garde TOUT le reste
    if (status === 0) { alerte = "reseau"; reste.push(...enAttente.slice(i)); break; }    // pas de réponse : inutile d'insister maintenant
    if (status >= 500) { alerte = "serveur"; reste.push(...enAttente.slice(i)); break; }
    // 422, 429 et autres 4xx : cette mesure est abandonnée, on passe à la suivante
  }
  return { reste, alerte };
}

// Texte du bandeau rouge selon l'alerte et le mode d'envoi (avec ou sans clé de sonde)
export function messageAlerte(alerte, nbEnAttente, avecCle) {
  if (!alerte) return "";
  const n = `${nbEnAttente} mesure(s) en attente d'envoi`;
  if (alerte === "acces") return avecCle
    ? `Clé de la sonde refusée ou non configurée sur le serveur : ${n}. Vérifiez la clé saisie et la variable SONDE_RESEAU_CLE dans Render.`
    : `Session expirée : ${n}. Reconnectez-vous, ou saisissez la clé de la sonde pour que l'envoi ne dépende plus de votre session.`;
  if (alerte === "serveur") return `Serveur SAWALI indisponible : ${n}, nouvel essai au prochain cycle.`;
  return `Réseau coupé : ${n}, nouvel essai au prochain cycle.`;
}
