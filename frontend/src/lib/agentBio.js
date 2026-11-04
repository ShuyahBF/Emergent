// =====================================================================
// Lot 370 — Connexion par l'agent biométrique Loois (lecteur d'empreintes d'un poste partagé), côté navigateur.
// Déroulé : 1) SAWALI donne un défi à usage unique ; 2) la page le remet à l'agent du POSTE (127.0.0.1) qui fait poser le doigt,
// reconnaît la personne et répond par une attestation signée ; 3) la page la transmet à SAWALI qui vérifie la signature.
// Aucune empreinte ne circule. Backend : routes/agent_biometrique.py. Programme du poste : LooisBioAgent (dépôt Loois).
// =====================================================================
import { apiClient } from "@/lib/api";

export { URL_AGENT, interrogerAgent, messageErreurAgent } from "./agentBioCodec";
import { interrogerAgent } from "./agentBioCodec";

/** La connexion par l'agent est-elle activée (et un agent enregistré) ? Faux sans erreur si le serveur ne répond pas. */
export async function agentBioActive() {
  try {
    const r = await apiClient.get("/auth/agent-bio/config");
    return !!r.data?.enabled;
  } catch {
    return false;
  }
}

/** Connexion complète. Renvoie { access_token, user } comme les autres modes de connexion. */
export async function connexionParAgent() {
  const { data } = await apiClient.post("/auth/agent-bio/defi");
  const rep = await interrogerAgent(data.defi);
  const r = await apiClient.post("/auth/agent-bio/connexion", { challenge_id: data.challenge_id, attestation: rep.attestation });
  return r.data;
}

