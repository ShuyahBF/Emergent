// =====================================================================
// Lot 369 — Connexion par empreinte digitale (passkeys / WebAuthn) côté navigateur.
// L'empreinte est vérifiée LOCALEMENT par le système (Windows Hello avec le lecteur d'empreintes, le téléphone ou une clé
// de sécurité) : le serveur ne reçoit JAMAIS l'empreinte, seulement une signature vérifiée avec la clé publique enregistrée.
// Backend : routes/passkeys.py (GET /auth/passkeys/config, …/register/*, …/login/*).
// Les conversions base64url / ArrayBuffer sont dans passkeysCodec.js (pures, testées).
// =====================================================================
import { apiClient } from "@/lib/api";
import { preparerCreation, preparerObtention, serialiserCreation, serialiserObtention } from "./passkeysCodec";

/** Vrai si ce navigateur sait créer et utiliser des passkeys. */
export function passkeysSupportees() {
  return typeof window !== "undefined" && !!window.PublicKeyCredential && !!navigator?.credentials;
}

export {
  b64uVersOctets, octetsVersB64u, preparerCreation, preparerObtention, serialiserCreation, serialiserObtention, messageErreurPasskey,
} from "./passkeysCodec";

/** La connexion par empreinte est-elle activée par l'administrateur ? (faux sans erreur si le serveur ne répond pas) */
export async function passkeysActivees() {
  try {
    const r = await apiClient.get("/auth/passkeys/config");
    return !!r.data?.enabled;
  } catch {
    return false;
  }
}

/** Enregistre une passkey pour le compte CONNECTÉ (le système demande l'empreinte). Renvoie la liste à jour. */
export async function enregistrerPasskey(nom) {
  const { data } = await apiClient.post("/auth/passkeys/register/options");
  const credential = await navigator.credentials.create({ publicKey: preparerCreation(data.options) });
  const reponse = await apiClient.post("/auth/passkeys/register/verify", {
    challenge_id: data.challenge_id,
    credential: serialiserCreation(credential),
    nom: nom || "",
  });
  return reponse.data.passkeys || [];
}

/** Connexion par passkey (aucun compte à nommer : le système propose les passkeys de ce site). Renvoie { access_token, user }. */
export async function connexionParPasskey() {
  const { data } = await apiClient.post("/auth/passkeys/login/options");
  const credential = await navigator.credentials.get({ publicKey: preparerObtention(data.options) });
  const reponse = await apiClient.post("/auth/passkeys/login/verify", {
    challenge_id: data.challenge_id,
    credential: serialiserObtention(credential),
  });
  return reponse.data;
}
