import { trierEntrees } from "./tri";

const liste = [
  { nom: "b.txt", dossier: false, taille: 500, modifie: "2026-10-02T10:00:00" },
  { nom: "Zeta", dossier: true, taille: 0, modifie: "2026-10-05T08:00:00" },
  { nom: "a.txt", dossier: false, taille: 900, modifie: "2026-10-03T09:30:00" },
  { nom: "Alpha", dossier: true, taille: 0, modifie: "2026-10-01T08:00:00" },
  { nom: "c.txt", dossier: false, taille: 100 },
];
const noms = (l) => l.map((e) => e.nom);

describe("tri de la liste des fichiers", () => {
  test("par nom : dossiers d'abord, ordre alphabétique", () => {
    expect(noms(trierEntrees(liste, "nom", "asc"))).toEqual(["Alpha", "Zeta", "a.txt", "b.txt", "c.txt"]);
    expect(noms(trierEntrees(liste, "nom", "desc"))).toEqual(["Zeta", "Alpha", "c.txt", "b.txt", "a.txt"]);
  });
  test("par date : le plus récent en premier en décroissant, sans date en dernier en croissant inversé", () => {
    expect(noms(trierEntrees(liste, "modifie", "desc"))).toEqual(["Zeta", "Alpha", "a.txt", "b.txt", "c.txt"]);
    expect(noms(trierEntrees(liste, "modifie", "asc"))).toEqual(["Alpha", "Zeta", "c.txt", "b.txt", "a.txt"]);
  });
  test("par taille : les dossiers restent en tête", () => {
    expect(noms(trierEntrees(liste, "taille", "desc"))).toEqual(["Alpha", "Zeta", "a.txt", "b.txt", "c.txt"]);
    expect(noms(trierEntrees(liste, "taille", "asc"))).toEqual(["Alpha", "Zeta", "c.txt", "b.txt", "a.txt"]);
  });
  test("la liste d'origine n'est pas modifiée et une liste vide est acceptée", () => {
    const copie = [...liste];
    trierEntrees(liste, "taille", "desc");
    expect(liste).toEqual(copie);
    expect(trierEntrees(undefined)).toEqual([]);
  });
});
