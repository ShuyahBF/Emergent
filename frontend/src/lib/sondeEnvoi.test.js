// Lot 471 — tests de l'envoi des mesures en attente
import { FILE_MAX, messageAlerte, viderFile } from "./sondeEnvoi";

const fabrique = (n) => Array.from({ length: n }, (_, i) => ({ id: i }));
const reponses = (codes) => { let i = 0; return async () => ({ status: codes[Math.min(i++, codes.length - 1)] }); };

test("tout est envoyé : la file est vidée", async () => {
  expect(await viderFile(fabrique(3), reponses([200]))).toEqual({ reste: [], alerte: null });
});

test("session expirée (401) : AUCUNE mesure n'est perdue et l'alerte est « acces »", async () => {
  const r = await viderFile(fabrique(3), reponses([401]));
  expect(r.reste.length).toBe(3);
  expect(r.alerte).toBe("acces");
});

test("l'accès tombe en cours de route : les mesures déjà envoyées sont retirées, le reste est gardé", async () => {
  const r = await viderFile(fabrique(4), reponses([200, 200, 403]));
  expect(r.reste).toEqual([{ id: 2 }, { id: 3 }]);
  expect(r.alerte).toBe("acces");
});

test("clé non configurée sur le serveur (503) : gardées, alerte « acces »", async () => {
  expect((await viderFile(fabrique(2), reponses([503]))).alerte).toBe("acces");
});

test("réseau coupé ou serveur en panne : gardées, on réessaiera", async () => {
  expect(await viderFile(fabrique(2), async () => { throw new Error("réseau"); })).toEqual({ reste: fabrique(2), alerte: "reseau" });
  expect((await viderFile(fabrique(2), reponses([502]))).alerte).toBe("serveur");
});

test("mesure incohérente (422) ou trop rapprochée (429) : abandonnée, les suivantes continuent", async () => {
  const r = await viderFile(fabrique(3), reponses([422, 429, 200]));
  expect(r).toEqual({ reste: [], alerte: null });
});

test("la file est plafonnée aux mesures les plus récentes", async () => {
  const r = await viderFile(fabrique(FILE_MAX + 10), reponses([401]));
  expect(r.reste.length).toBe(FILE_MAX);
  expect(r.reste[0]).toEqual({ id: 10 });
});

test("messages du bandeau", () => {
  expect(messageAlerte(null, 0, false)).toBe("");
  expect(messageAlerte("acces", 5, false)).toContain("Session expirée");
  expect(messageAlerte("acces", 5, true)).toContain("SONDE_RESEAU_CLE");
  expect(messageAlerte("reseau", 2, true)).toContain("Réseau coupé");
});
