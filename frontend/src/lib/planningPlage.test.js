import { trierJour } from "./planningPlage";

test("un jour : RDV par heure, puis patients sans RDV par numéro d'ordre", () => {
  const items = [
    { id: "w2", is_rdv: 0, numero_ordre: 2 }, { id: "r2", start_at: "2026-10-27T10:00:00+00:00" },
    { id: "w1", is_rdv: 0, numero_ordre: 1 }, { id: "r1", start_at: "2026-10-27T08:30:00+00:00" },
  ];
  expect(trierJour(items).map((a) => a.id)).toEqual(["r1", "r2", "w1", "w2"]);
  expect(trierJour(undefined)).toEqual([]);
});
