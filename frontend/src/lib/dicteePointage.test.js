import { analyserDictee, jetons } from "./dicteePointage";

// Valeurs utiles d'un résultat (sans les champs vides) pour des comparaisons lisibles
const r = (t) => {
  const x = analyserDictee(t);
  return Object.fromEntries(Object.entries(x).filter(([, v]) => v !== undefined && v !== null && !(Array.isArray(v) && !v.length)));
};

describe("dictée du pointage", () => {
  test("chiffres simples, dans l'ordre ligne, quantité, péremption", () => {
    expect(r("245 12 mars 2027 suivant")).toEqual({ chrono: 245, qte: 12, peremption: "03/2027", commande: "suivant" });
  });
  test("avec étiquettes, dans n'importe quel ordre", () => {
    expect(r("quantité 12 ligne 245 péremption 03/27")).toEqual({ chrono: 245, qte: 12, peremption: "03/2027" });
  });
  test("nombres en toutes lettres", () => {
    expect(r("deux cent quarante-cinq douze")).toEqual({ chrono: 245, qte: 12 });
    expect(r("ligne quatre-vingt-dix-sept quantité soixante-dix")).toEqual({ chrono: 97, qte: 70 });
    expect(r("mille deux cent trois, vingt et un")).toEqual({ chrono: 1203, qte: 21 });
  });
  test("péremption : mois et année en nombres, ou collés", () => {
    expect(r("245 12 6 2028")).toEqual({ chrono: 245, qte: 12, peremption: "06/2028" });
    expect(r("245 12 péremption 062028")).toEqual({ chrono: 245, qte: 12, peremption: "06/2028" });
    expect(r("245 12 juin 28")).toEqual({ chrono: 245, qte: 12, peremption: "06/2028" });
  });
  test("péremption facultative et quantité zéro", () => {
    expect(r("ligne 1 zéro suivant")).toEqual({ chrono: 1, qte: 0, commande: "suivant" });
  });
  test("commandes seules", () => {
    expect(r("Suivant")).toEqual({ commande: "suivant" });
    expect(r("annule")).toEqual({ commande: "annule" });
  });
  test("mots parasites ignorés, mois invalide refusé", () => {
    expect(r("ligne 245 et 12 boîtes")).toEqual({ chrono: 245, qte: 12 });
    expect(r("245 12 péremption 13 2027").peremption).toBeUndefined();
  });
  test("anglais (lot 499)", () => {
    expect(r("line 245 twelve March 2027 next")).toEqual({ chrono: 245, qte: 12, peremption: "03/2027", commande: "suivant" });
    expect(r("two hundred and forty five, quantity twenty one")).toEqual({ chrono: 245, qte: 21 });
    expect(r("undo")).toEqual({ commande: "annule" });
  });
  test("le N° écrit avec le signe n°", () => {
    expect(jetons("N° 12")).toEqual([{ t: "etiquette", v: "chrono" }, { t: "nombre", v: 12, brut: "12" }]);
  });
});
