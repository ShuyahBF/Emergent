// Tests des contrôles de pièces jointes (logique pure).
import { ESSAIS_COMPRESSION, PIECE_MAX_OCTETS, PIECES_MAX, base64DeDataUrl, dimensionsCible, formaterTaille, octetsDeBase64, refuserFichier } from "./piecesJointes";

test("tailles lisibles", () => {
  expect(formaterTaille(500)).toBe("500 o");
  expect(formaterTaille(312 * 1024)).toBe("312 Ko");
  expect(formaterTaille(1.5 * 1024 * 1024)).toBe("1,5 Mo");
  expect(formaterTaille(-1)).toBe("—");
});

test("dimensions : réduites si trop grandes, jamais agrandies", () => {
  expect(dimensionsCible(3200, 1600)).toEqual({ largeur: 1600, hauteur: 800 });
  expect(dimensionsCible(800, 600)).toEqual({ largeur: 800, hauteur: 600 });
  expect(dimensionsCible(0, 0)).toEqual({ largeur: 1, hauteur: 1 });
});

test("les essais de compression vont du plus fidèle au plus léger", () => {
  expect(ESSAIS_COMPRESSION[0]).toEqual({ echelle: 1, qualite: 0.85 });
  expect(ESSAIS_COMPRESSION[ESSAIS_COMPRESSION.length - 1]).toEqual({ echelle: 0.4, qualite: 0.4 });
});

test("refus d'un fichier avant traitement", () => {
  expect(refuserFichier({ name: "a.png", type: "image/png", size: 5 * 1024 * 1024 }, 0)).toBeNull();                 // une image trop lourde sera compressée
  expect(refuserFichier({ name: "a.exe", type: "application/x-msdownload", size: 10 }, 0)).toMatch(/type non accepté/);
  expect(refuserFichier({ name: "c.pdf", type: "application/pdf", size: PIECE_MAX_OCTETS + 1 }, 0)).toMatch(/PDF/);
  expect(refuserFichier({ name: "c.pdf", type: "application/pdf", size: 1000 }, 0)).toBeNull();
  expect(refuserFichier({ name: "a.png", type: "image/png", size: 10 }, PIECES_MAX)).toMatch(/au plus/);
});

test("base64 : contenu et taille", () => {
  expect(base64DeDataUrl("data:image/png;base64,QUJD")).toBe("QUJD");
  expect(base64DeDataUrl("pas une adresse")).toBe("");
  expect(octetsDeBase64("QUJD")).toBe(3);        // « ABC »
  expect(octetsDeBase64("QUI=")).toBe(2);        // « AB »
});
