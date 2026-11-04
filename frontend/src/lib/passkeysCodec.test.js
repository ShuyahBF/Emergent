// Lot 369 — conversions des passkeys (WebAuthn) : base64url ↔ octets, options du serveur → navigateur, réponses du navigateur → serveur.
import {
  b64uVersOctets, octetsVersB64u, preparerCreation, preparerObtention, serialiserCreation, serialiserObtention, messageErreurPasskey,
} from "./passkeysCodec";

const tampon = (...octets) => new Uint8Array(octets).buffer;

test("base64url : aller-retour sans « = », « + » ni « / »", () => {
  const octets = new Uint8Array([251, 255, 254, 0, 1, 2, 250]);   // donne des « + » et des « / » en base64 classique
  const texte = octetsVersB64u(octets);
  expect(texte).toBe("-__-AAEC-g");
  expect(texte).not.toMatch(/[+/=]/);
  expect(Array.from(b64uVersOctets(texte))).toEqual(Array.from(octets));
  expect(Array.from(b64uVersOctets(octetsVersB64u(octets.buffer)))).toEqual(Array.from(octets));   // ArrayBuffer accepté aussi
  expect(octetsVersB64u(new Uint8Array([]))).toBe("");
});

test("options d'enregistrement : défi, identifiant du compte et clés déjà enregistrées deviennent des octets", () => {
  const o = preparerCreation({ challenge: "AQID", rp: { id: "x.bf" }, user: { id: "YXdh", name: "awa@x.bf" }, excludeCredentials: [{ id: "BAUG", type: "public-key" }] });
  expect(Array.from(o.challenge)).toEqual([1, 2, 3]);
  expect(Array.from(o.user.id)).toEqual([97, 119, 97]);              // « awa »
  expect(o.user.name).toBe("awa@x.bf");
  expect(Array.from(o.excludeCredentials[0].id)).toEqual([4, 5, 6]);
  expect(o.excludeCredentials[0].type).toBe("public-key");
  expect(preparerCreation({ challenge: "AQID", user: { id: "YXdh" } }).excludeCredentials).toEqual([]);
});

test("options de connexion : défi en octets, aucune clé annoncée (passkey découvrable)", () => {
  const o = preparerObtention({ challenge: "AQID", rpId: "x.bf", userVerification: "required" });
  expect(Array.from(o.challenge)).toEqual([1, 2, 3]);
  expect(o.allowCredentials).toEqual([]);
  expect(o.userVerification).toBe("required");
});

test("réponse d'enregistrement : tout est renvoyé en base64url", () => {
  const brut = {
    id: "abc", type: "public-key", rawId: tampon(1, 2, 3),
    getClientExtensionResults: () => ({}),
    response: { clientDataJSON: tampon(9), attestationObject: tampon(8, 7), getTransports: () => ["internal"] },
  };
  expect(serialiserCreation(brut)).toEqual({
    id: "abc", rawId: "AQID", type: "public-key", clientExtensionResults: {},
    response: { clientDataJSON: "CQ", attestationObject: "CAc", transports: ["internal"] },
  });
});

test("réponse de connexion : signature et identifiant du compte (userHandle) seulement s'il existe", () => {
  const base = (userHandle) => ({
    id: "abc", type: "public-key", rawId: tampon(1),
    response: { clientDataJSON: tampon(2), authenticatorData: tampon(3), signature: tampon(4), userHandle },
  });
  const avec = serialiserObtention(base(tampon(97)));
  expect(avec.response).toEqual({ clientDataJSON: "Ag", authenticatorData: "Aw", signature: "BA", userHandle: "YQ" });
  expect(avec.clientExtensionResults).toEqual({});
  expect("userHandle" in serialiserObtention(base(null)).response).toBe(false);
});

test("messages d'erreur lisibles : le détail du serveur d'abord, jamais de jargon", () => {
  expect(messageErreurPasskey({ response: { data: { detail: "Passkey inconnue ou retirée" } } })).toBe("Passkey inconnue ou retirée");
  expect(messageErreurPasskey({ name: "NotAllowedError" })).toMatch(/annulée|refusée|expirée/);
  expect(messageErreurPasskey({ name: "InvalidStateError" })).toMatch(/déjà enregistrée/);
  expect(messageErreurPasskey({ name: "SecurityError" })).toMatch(/domaine|HTTPS/);
  expect(messageErreurPasskey(new Error("boom"))).toMatch(/mot de passe/);
  expect(messageErreurPasskey(undefined)).toMatch(/mot de passe/);
});
