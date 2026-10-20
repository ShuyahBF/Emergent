import { majFiche } from "./majContact";

test("seule la fiche visée change, les autres gardent le même objet", () => {
  const a = { id: "a", name: "Awa", tags: [] };
  const b = { id: "b", name: "Boris", tags: ["client"] };
  const liste = [a, b];
  const maj = majFiche(liste, "a", { tags: ["prospect"] });
  expect(maj).not.toBe(liste);                       // nouvelle liste (React redessine)
  expect(maj[0]).toEqual({ id: "a", name: "Awa", tags: ["prospect"] });
  expect(maj[1]).toBe(b);                            // la ligne de Boris n'a pas bougé
  expect(a.tags).toEqual([]);                        // la fiche d'origine n'est pas modifiée
});

test("identifiant inconnu ou liste vide : rien ne casse", () => {
  const liste = [{ id: "a" }];
  expect(majFiche(liste, "zzz", { x: 1 })).toEqual([{ id: "a" }]);
  expect(majFiche(undefined, "a", { x: 1 })).toEqual([]);
});
