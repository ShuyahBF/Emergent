// Lot 370 — parties PURES de la connexion par l'agent biométrique (testées sans réseau ni alias @/) : dialogue avec l'agent du poste et messages.

/** Adresse de l'agent sur CE poste (jamais le réseau). Le port peut être changé dans les réglages de l'agent : il se règle ici si besoin. */
export const URL_AGENT = "http://127.0.0.1:47821";
const DELAI_POSE_MS = 45000;   // l'agent attend le doigt 30 s au plus, plus une marge

/** Erreur lisible : « code » vaut AGENT_ABSENT, AGENT_REFUS ou NON_RECONNU. */
function erreurAgent(code, message) {
  const e = new Error(message);
  e.code = code;
  return e;
}

/** Demande à l'agent du poste d'identifier la personne qui pose le doigt ; renvoie sa réponse JSON. */
export async function interrogerAgent(defi, fetchImpl = fetch) {
  const arret = new AbortController();
  const minuterie = setTimeout(() => arret.abort(), DELAI_POSE_MS);
  let reponse;
  try {
    reponse = await fetchImpl(`${URL_AGENT}/v1/identifier`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ defi }), signal: arret.signal,
    });
  } catch {
    throw erreurAgent("AGENT_ABSENT", "L'agent biométrique n'est pas joignable sur ce poste (programme non lancé, ou accès « réseau local » refusé par le navigateur).");
  } finally { clearTimeout(minuterie); }
  let corps = {};
  try { corps = await reponse.json(); } catch { /* corps vide */ }
  if (reponse.status === 403 || reponse.status === 401) throw erreurAgent("AGENT_REFUS", "Ce site n'est pas autorisé sur ce poste : ajoutez-le dans les réglages de l'agent biométrique.");
  if (reponse.status === 409) throw erreurAgent("AGENT_REFUS", "Le lecteur est déjà utilisé : patientez quelques secondes puis recommencez.");
  if (!reponse.ok) throw erreurAgent("AGENT_REFUS", corps.erreur || "L'agent biométrique a refusé la demande.");
  if (!corps.reconnu || !corps.attestation) throw erreurAgent("NON_RECONNU", corps.message || "Empreinte non reconnue.");
  return corps;
}

/** Message à afficher pour une erreur de la connexion par l'agent (réponse de SAWALI, ou erreur de l'agent). */
export function messageErreurAgent(err) {
  const detail = err?.response?.data?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (err?.code === "AGENT_ABSENT" || err?.code === "AGENT_REFUS" || err?.code === "NON_RECONNU") return err.message;
  return "La connexion par l'agent n'a pas abouti. Utilisez votre mot de passe.";
}
