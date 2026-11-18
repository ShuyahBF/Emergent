// Lot 448.2 — adresse d'actualisation sans cache du bandeau « nouvelle version ».
import { adresseSansCache, adresseSansParametreMaj } from "./NouvelleVersionBandeau";

test("« Actualiser » ajoute un paramètre unique et garde le reste de l'adresse", () => {
  expect(adresseSansCache("https://sawali.test/admin/loois-dossiers-hospitalisation", 123)).toBe("https://sawali.test/admin/loois-dossiers-hospitalisation?maj=123");
  expect(adresseSansCache("https://sawali.test/p?a=1#haut", 456)).toBe("https://sawali.test/p?a=1&maj=456#haut");
  expect(adresseSansCache("https://sawali.test/p?maj=1", 789)).toBe("https://sawali.test/p?maj=789");   // un seul paramètre « maj », jamais empilé
});

test("le paramètre « maj » est retiré de la barre d'adresse", () => {
  expect(adresseSansParametreMaj("https://sawali.test/p?a=1&maj=456#haut")).toBe("https://sawali.test/p?a=1#haut");
  expect(adresseSansParametreMaj("https://sawali.test/p")).toBe("https://sawali.test/p");
});
