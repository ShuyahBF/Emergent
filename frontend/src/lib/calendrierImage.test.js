import { calculerLibres, plagesOccupees, texteLibres } from "./calendrierImage";

// Jour de test : mardi 27/10/2026 (heure locale du navigateur de test)
const jour = new Date(2026, 9, 27);
const heure = (h, m = 0) => new Date(2026, 9, 27, h, m).toISOString();

test("créneaux libres : le complémentaire des plages occupées, trous trop courts ignorés", () => {
  const occ = [
    { debut: heure(9, 15), fin: heure(9, 45) },      // Suivi
    { debut: heure(10, 30), fin: heure(11, 30) },    // Démonstration
    { debut: heure(11, 30), fin: heure(14, 0) },     // Génération (adjacent : fusionné avec la précédente)
    { debut: heure(14, 0), fin: heure(15, 30) },     // Formation
    { debut: heure(16, 45), fin: heure(17, 15) },    // Assistance
  ];
  const ouv = 7 * 60, fer = 19 * 60;
  expect(plagesOccupees(jour, occ, ouv, fer).length).toBe(3);                 // 9h15, 10h30–15h30, 16h45
  expect(calculerLibres(jour, occ, ouv, fer)).toEqual([[420, 555], [585, 630], [930, 1005], [1035, 1140]]);
  expect(texteLibres(calculerLibres(jour, occ, ouv, fer))).toContain("07h00 – 09h15");
});

test("journée complète : aucun créneau libre", () => {
  const occ = [{ debut: heure(6, 0), fin: heure(20, 0) }];
  expect(calculerLibres(jour, occ, 420, 1140)).toEqual([]);
  expect(texteLibres([])).toBe("Complet");
});

test("journée libre : un seul créneau sur toute l'ouverture", () => {
  expect(calculerLibres(jour, [], 420, 1140)).toEqual([[420, 1140]]);
});

// Lot 318 : libellé de la période envoyée (un jour, 3 jours ou la semaine)
import { libellePeriode } from "./calendrierImage";
test("libellePeriode : jour, 3 jours, semaine", () => {
  const fr = (d) => `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`;
  const t0 = new Date(2026, 9, 29), t2 = new Date(2026, 9, 31), t6 = new Date(2026, 10, 4);
  expect(libellePeriode(t0, t0, 1, fr)).toBe("Jeudi 29/10");
  expect(libellePeriode(t0, t2, 3, fr)).toBe("Du 29/10 au 31/10");
  expect(libellePeriode(t0, t6, 7, fr)).toBe("Semaine du 29/10 au 04/11");
});
