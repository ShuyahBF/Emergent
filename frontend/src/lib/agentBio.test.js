// Lot 370 — connexion par l'agent biométrique : dialogue avec l'agent du poste et messages d'erreur (sans réseau réel).
import { interrogerAgent, messageErreurAgent, URL_AGENT } from "./agentBioCodec";

const reponse = (code, corps) => Promise.resolve({ ok: code >= 200 && code < 300, status: code, json: () => Promise.resolve(corps) });

test("l'agent reconnaît la personne : la page reçoit l'attestation", async () => {
  const appels = [];
  const faux = (url, opts) => { appels.push([url, opts]); return reponse(200, { ok: true, reconnu: true, personne: "awa", attestation: "a.b" }); };
  const r = await interrogerAgent("defi-0123456789abcdef", faux);
  expect(r.attestation).toBe("a.b");
  expect(appels[0][0]).toBe(`${URL_AGENT}/v1/identifier`);
  expect(JSON.parse(appels[0][1].body)).toEqual({ defi: "defi-0123456789abcdef" });
});

test("agent absent, site refusé, lecteur occupé, doigt inconnu : chaque cas a son message", async () => {
  await expect(interrogerAgent("d", () => Promise.reject(new TypeError("Failed to fetch")))).rejects.toMatchObject({ code: "AGENT_ABSENT" });
  await expect(interrogerAgent("d", () => reponse(403, { ok: false }))).rejects.toMatchObject({ code: "AGENT_REFUS", message: expect.stringContaining("autorisé") });
  await expect(interrogerAgent("d", () => reponse(409, { ok: false }))).rejects.toMatchObject({ code: "AGENT_REFUS", message: expect.stringContaining("déjà utilisé") });
  await expect(interrogerAgent("d", () => reponse(200, { ok: false, reconnu: false, message: "Empreinte non reconnue." }))).rejects.toMatchObject({ code: "NON_RECONNU", message: "Empreinte non reconnue." });
});

test("messages d'erreur : le détail de SAWALI d'abord, puis celui de l'agent, puis un message par défaut", () => {
  expect(messageErreurAgent({ response: { data: { detail: "Défi expiré ou invalide : recommencez" } } })).toBe("Défi expiré ou invalide : recommencez");
  expect(messageErreurAgent({ code: "AGENT_ABSENT", message: "Agent absent" })).toBe("Agent absent");
  expect(messageErreurAgent(new Error("?"))).toMatch(/mot de passe/);
});
