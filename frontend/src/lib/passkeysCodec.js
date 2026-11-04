// =====================================================================
// Lot 369 — Conversions pures (sans appel au serveur ni au navigateur) des passkeys / WebAuthn.
// Le navigateur manipule des « ArrayBuffer », le serveur du texte base64url : ces fonctions font le passage dans les deux sens.
// Fichier testé seul (src/lib/passkeysCodec.test.js). Utilisé par lib/passkeys.js.
// =====================================================================

/** base64url (texte) → octets. */
export function b64uVersOctets(texte) {
  const b64 = String(texte).replace(/-/g, "+").replace(/_/g, "/");
  const complet = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
  const binaire = atob(complet);
  const octets = new Uint8Array(binaire.length);
  for (let i = 0; i < binaire.length; i += 1) octets[i] = binaire.charCodeAt(i);
  return octets;
}

/** octets (ArrayBuffer ou tableau d'octets) → base64url (texte, sans « = »). */
export function octetsVersB64u(tampon) {
  const octets = tampon instanceof Uint8Array ? tampon : new Uint8Array(tampon);
  let binaire = "";
  for (let i = 0; i < octets.length; i += 1) binaire += String.fromCharCode(octets[i]);
  return btoa(binaire).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Options d'enregistrement envoyées par le serveur (JSON) → options attendues par navigator.credentials.create. */
export function preparerCreation(options) {
  return {
    ...options,
    challenge: b64uVersOctets(options.challenge),
    user: { ...options.user, id: b64uVersOctets(options.user.id) },
    excludeCredentials: (options.excludeCredentials || []).map((c) => ({ ...c, id: b64uVersOctets(c.id) })),
  };
}

/** Options de connexion envoyées par le serveur (JSON) → options attendues par navigator.credentials.get. */
export function preparerObtention(options) {
  return {
    ...options,
    challenge: b64uVersOctets(options.challenge),
    allowCredentials: (options.allowCredentials || []).map((c) => ({ ...c, id: b64uVersOctets(c.id) })),
  };
}

/** Réponse du navigateur à une création → JSON à renvoyer au serveur. */
export function serialiserCreation(c) {
  return {
    id: c.id,
    rawId: octetsVersB64u(c.rawId),
    type: c.type,
    clientExtensionResults: c.getClientExtensionResults ? c.getClientExtensionResults() : {},
    response: {
      clientDataJSON: octetsVersB64u(c.response.clientDataJSON),
      attestationObject: octetsVersB64u(c.response.attestationObject),
      transports: c.response.getTransports ? c.response.getTransports() : [],
    },
  };
}

/** Réponse du navigateur à une connexion → JSON à renvoyer au serveur. */
export function serialiserObtention(c) {
  const r = c.response;
  return {
    id: c.id,
    rawId: octetsVersB64u(c.rawId),
    type: c.type,
    clientExtensionResults: c.getClientExtensionResults ? c.getClientExtensionResults() : {},
    response: {
      clientDataJSON: octetsVersB64u(r.clientDataJSON),
      authenticatorData: octetsVersB64u(r.authenticatorData),
      signature: octetsVersB64u(r.signature),
      ...(r.userHandle ? { userHandle: octetsVersB64u(r.userHandle) } : {}),
    },
  };
}

/** Message lisible pour une erreur du navigateur ou du serveur (jamais de jargon technique à l'écran). */
export function messageErreurPasskey(err) {
  const detail = err?.response?.data?.detail;
  if (typeof detail === "string" && detail) return detail;
  const nom = err?.name || "";
  if (nom === "NotAllowedError") return "Opération annulée, refusée ou expirée : réessayez et validez avec votre empreinte.";
  if (nom === "InvalidStateError") return "Cette passkey est déjà enregistrée sur cet appareil.";
  if (nom === "SecurityError") return "Cette adresse n'est pas autorisée pour les passkeys (domaine ou HTTPS).";
  if (nom === "NotSupportedError") return "Cet appareil ne gère pas ce type de passkey.";
  return "La connexion par empreinte n'a pas abouti. Utilisez votre mot de passe.";
}
