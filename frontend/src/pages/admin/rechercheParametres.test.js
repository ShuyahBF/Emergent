// Lot 203 — recherche en texte intégral des Paramètres (fonction pure)
import { correspondanceRecherche, sansAccent } from "./rechercheParametres";
import INDEX from "./settingsIndex.json";

const index = { "Rubrique A": "Chaque client a sa liste de logiciels, produits et services · Qdrant", "Rubrique B": "Sauvegarde des bases" };

test("sans accent ni casse, longueur conservée", () => {
  expect(sansAccent("Épée DÉJÀ")).toBe("epee deja");
});
test("titre, contenu, tous les mots, aucune correspondance", () => {
  expect(correspondanceRecherche("Rubrique A", "rubrique", index)).toEqual({ dans: "titre" });
  const c = correspondanceRecherche("Rubrique A", "LOGICIELS produits", index);
  expect(c.dans).toBe("contenu");
  expect(c.extrait).toContain("logiciels");
  expect(correspondanceRecherche("Rubrique B", "logiciels", index)).toBeNull();
  expect(correspondanceRecherche("Rubrique A", "", index)).toEqual({ dans: "tout" });
});
test("l'index réel retrouve une rubrique par un mot de son contenu", () => {
  const trouvees = Object.keys(INDEX.sections).filter((t) => correspondanceRecherche(t, "qdrant", INDEX.sections));
  expect(trouvees.length).toBeGreaterThan(0);
  expect(Object.keys(INDEX.sections).length).toBeGreaterThan(80);
});
