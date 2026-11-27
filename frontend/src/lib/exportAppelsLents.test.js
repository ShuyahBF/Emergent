// Lot 470 — tests de l'export du tableau « Appels les plus lents »
import { appelsEnCsv, appelsEnJson, CHAMPS_APPELS } from "./exportAppelsLents";

const appels = {
  source: "direct", depuis: "2026-11-26T23:11:00+00:00", routes: 2, appels: 6, lents: 1, erreurs: 0, objectif_ms: 1000,
  classement: [
    { methode: "GET", route: "/api/admin/plateformes-activite", appels: 5, moyenne_ms: 635, derniers_ms: [1249, 353, 414], dernier_ms: 430, maximum_ms: 1249, lents: 1, erreurs: 0, ops_moy: 18.5, ops_max: 31, base_ms_moy: 410 },
    { methode: "GET", route: "/api/admin/whatsapp/templates", appels: 1, moyenne_ms: 853, derniers_ms: [853], dernier_ms: 853, maximum_ms: 853, lents: 0, erreurs: 0, ops_moy: 3, ops_max: 3, base_ms_moy: 35 },
  ],
};

test("JSON : contexte, totaux, description des champs et classement complet", () => {
  const j = JSON.parse(appelsEnJson(appels, { lisible: true, utilise_mo: 327.2, limite_mo: 512, pourcentage: 63.9, processus_mo: 317.9 }, "2026-11-26T23:30:00Z"));
  expect(j.totaux).toEqual({ routes: 2, appels: 6, appels_de_plus_d_1_s: 1, erreurs_5xx: 0 });
  expect(j.classement.length).toBe(2);
  expect(j.classement[0].ops_moy).toBe(18.5);                       // le nombre de requêtes à la base accompagne chaque route
  expect(CHAMPS_APPELS.ops_moy.includes("MongoDB")).toBe(true);
  expect(j.champs).toEqual(CHAMPS_APPELS);
  expect(j.memoire.utilise_mo).toBe(327.2);
  expect(j.exporte_le).toBe("2026-11-26T23:30:00Z");
});

test("JSON : mémoire absente ou illisible = null", () => {
  expect(JSON.parse(appelsEnJson(appels, null, "x")).memoire).toBeNull();
  expect(JSON.parse(appelsEnJson(appels, { lisible: false }, "x")).memoire).toBeNull();
});

test("CSV : une ligne par route plus l'en-tête, séparateur point-virgule", () => {
  const lignes = appelsEnCsv(appels).split("\r\n");
  expect(lignes.length).toBe(3);
  expect(lignes[0].startsWith("Méthode;Route;Appels;Moyenne ms")).toBe(true);
  expect(lignes[1]).toBe("GET;/api/admin/plateformes-activite;5;635;1249 353 414;430;1249;1;0;18.5;31;410");
});
