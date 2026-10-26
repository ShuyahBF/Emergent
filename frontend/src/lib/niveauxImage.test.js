import { texteTarifExpress } from "./niveauxImage";

test("tarif EXPRESS : forfait du client, sinon « précisé avant l'intervention »", () => {
  expect(texteTarifExpress(25000)).toBe("25 000 FCFA");
  expect(texteTarifExpress(0)).toBe("Tarif précisé avant l'intervention");
  expect(texteTarifExpress(null)).toBe("Tarif précisé avant l'intervention");
  expect(texteTarifExpress(undefined)).toBe("Tarif précisé avant l'intervention");
});
