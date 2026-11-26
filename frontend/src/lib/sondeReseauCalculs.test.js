// Lot 470 — tests des calculs purs de la sonde réseau (aucun réseau, aucun écran)
import { debitMbps, doitMesurerDebit, enCsv, niveauDebit, niveauPerte, pctPerte, statsLatence } from "./sondeReseauCalculs";

test("latence : moyenne, minimum, maximum et requêtes perdues", () => {
  const s = statsLatence([80, 90, 100], 2);
  expect(s).toEqual({ essais: 5, perdus: 2, moy: 90, min: 80, max: 100 });
  expect(statsLatence([], 10)).toEqual({ essais: 10, perdus: 10, moy: null, min: null, max: null });   // tout perdu : pas de latence
});

test("débit en Mb/s : 1 250 000 octets en 1 s = 10 Mb/s ; mesure inexploitable = null", () => {
  expect(debitMbps(1_250_000, 1000)).toBe(10);
  expect(debitMbps(0, 1000)).toBeNull();
  expect(debitMbps(1000, 0)).toBeNull();
});

test("les débits ne sont mesurés qu'un cycle sur quatre à 15 minutes (une fois par heure)", () => {
  expect([0, 1, 2, 3, 4, 5].map((n) => doitMesurerDebit(n, 15))).toEqual([true, false, false, false, true, false]);
  expect(doitMesurerDebit(3, 60)).toBe(true);        // intervalle d'une heure : toujours
  expect(doitMesurerDebit(1, 5)).toBe(false);        // 5 minutes : un cycle sur douze
  expect(doitMesurerDebit(12, 5)).toBe(true);
});

test("niveaux de perte et de débit", () => {
  expect(pctPerte({ essais: 10, perdus: 4 })).toBe(40);
  expect(pctPerte({ essais: 0, perdus: 0 })).toBeNull();
  expect([niveauPerte(0), niveauPerte(2), niveauPerte(10), niveauPerte(null)]).toEqual(["ok", "attention", "critique", "inconnu"]);
  expect([niveauDebit(0.9), niveauDebit(34), niveauDebit(null)]).toEqual(["attention", "ok", "inconnu"]);
});

test("export CSV : séparateur point-virgule, virgule décimale, textes protégés", () => {
  const csv = enCsv([{ le: "2026-11-26T10:00:00+00:00", poste: 'PC "box"; 1', type: "pc", essais: 10, perdus: 4, latence_moy_ms: 83.2, https_ok: 8, https_total: 9, debit_desc_mbps: 0.9 }]);
  const [entete, ligne] = csv.split("\r\n");
  expect(entete.startsWith("Date (UTC);Poste;Type")).toBe(true);
  expect(ligne).toContain('"PC ""box""; 1"');          // guillemets doublés, champ entouré
  expect(ligne).toContain(";40;83,2;");                 // perte 40 % et latence avec virgule
});
