// Lot 465 — calculs purs des captures annotées : taille d'export, rectangle normalisé, tête de flèche, nom de fichier, réglages. Aucun navigateur requis.
import { CLE_FLAGS, estImage, lireReglagesCaptures, nomFichierCapture, pointesFleche, rectangle, tailleExport } from "./annotationCapture";

const stockage = (obj) => ({ getItem: (k) => (k === CLE_FLAGS && obj !== undefined ? (typeof obj === "string" ? obj : JSON.stringify(obj)) : null) });

describe("taille de la capture insérée", () => {
  test("réduite au-delà de la largeur maximale, proportions gardées", () => {
    expect(tailleExport(1800, 700, 1600)).toEqual({ largeur: 1600, hauteur: 622 });
    expect(tailleExport(3200, 1800, 1600)).toEqual({ largeur: 1600, hauteur: 900 });
  });
  test("jamais agrandie, et une image vide ne casse rien", () => {
    expect(tailleExport(800, 600, 1600)).toEqual({ largeur: 800, hauteur: 600 });
    expect(tailleExport(0, 600)).toEqual({ largeur: 0, hauteur: 0 });
  });
});

describe("géométrie des formes", () => {
  test("rectangle normalisé dans tous les sens du glisser", () => {
    expect(rectangle(10, 20, 110, 70)).toEqual({ x: 10, y: 20, l: 100, h: 50 });
    expect(rectangle(110, 70, 10, 20)).toEqual({ x: 10, y: 20, l: 100, h: 50 });
  });
  test("tête de flèche : deux pointes derrière l'extrémité, rien pour un simple clic", () => {
    const tete = pointesFleche(0, 0, 100, 0, 6);
    expect(tete).toHaveLength(2);
    tete.forEach((p) => expect(p.x).toBeLessThan(100));                    // les pointes sont en arrière de l'extrémité
    expect(tete[0].y).toBeCloseTo(-tete[1].y, 5);                          // symétriques par rapport au trait
    expect(pointesFleche(5, 5, 5, 6)).toBeNull();
  });
  test("la tête grandit avec l'épaisseur", () => {
    const fin = pointesFleche(0, 0, 100, 0, 3), epais = pointesFleche(0, 0, 100, 0, 10);
    expect(Math.abs(epais[0].y)).toBeGreaterThan(Math.abs(fin[0].y));
  });
});

describe("nom de fichier et type d'image", () => {
  test("capture-AAAAMMJJ-HHMMSS.png", () => {
    expect(nomFichierCapture(new Date(2026, 10, 26, 9, 5, 7))).toBe("capture-20261126-090507.png");
  });
  test("seules les images annotables sont acceptées (pas de SVG ni de texte)", () => {
    expect(estImage({ type: "image/png" })).toBe(true);
    expect(estImage({ type: "image/jpeg" })).toBe(true);
    expect(estImage({ type: "image/svg+xml" })).toBe(false);
    expect(estImage({ type: "text/plain" })).toBe(false);
    expect(estImage(null)).toBe(false);
  });
});

describe("réglages lus dans le cache des réglages publics", () => {
  test("par défaut : active, 1600 px", () => {
    expect(lireReglagesCaptures(stockage(undefined))).toEqual({ actives: true, largeurMax: 1600 });
    expect(lireReglagesCaptures(stockage("pas du json"))).toEqual({ actives: true, largeurMax: 1600 });
  });
  test("désactivée et largeur bornée entre 800 et 2400", () => {
    expect(lireReglagesCaptures(stockage({ suivis_captures_actives: false })).actives).toBe(false);
    expect(lireReglagesCaptures(stockage({ suivis_captures_largeur_max: 100 })).largeurMax).toBe(800);
    expect(lireReglagesCaptures(stockage({ suivis_captures_largeur_max: 99999 })).largeurMax).toBe(2400);
    expect(lireReglagesCaptures(stockage({ suivis_captures_largeur_max: 1200 })).largeurMax).toBe(1200);
  });
});
