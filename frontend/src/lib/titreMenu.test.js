import { titreMenu } from "@/lib/titreMenu";

// Règle 18 : chaque mot d'un libellé de menu commence par une majuscule, sans abaisser le reste ; exception possible
describe("titreMenu", () => {
  it("met la première lettre de chaque mot en majuscule", () => {
    expect(titreMenu("Gestion des contacts")).toBe("Gestion Des Contacts");
    expect(titreMenu("Demandes à SAWALI")).toBe("Demandes À SAWALI");
    expect(titreMenu("contacts clients")).toBe("Contacts Clients");
  });
  it("ne baisse jamais une majuscule existante (sigles)", () => {
    expect(titreMenu("OHADA comptabilité")).toBe("OHADA Comptabilité");
    expect(titreMenu("Services Web")).toBe("Services Web");
  });
  it("laisse les pictogrammes et le mot après une apostrophe", () => {
    expect(titreMenu("📮 demandes des plateformes")).toBe("📮 Demandes Des Plateformes");
    expect(titreMenu("l'ordre du jour")).toBe("L'ordre Du Jour");
  });
  it("respecte l'exception « casse libre »", () => {
    expect(titreMenu("mes pièces", true)).toBe("mes pièces");
  });
});
