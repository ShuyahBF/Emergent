import { empreinteHtml, empreinteChargee, nouvelleVersionDisponible } from "./versionSite";

describe("versionSite", () => {
  test("empreinteHtml extrait et trie les fichiers principaux", () => {
    const html = '<script src="/static/js/main.abc123.js"></script><link href="/static/css/main.def456.css">';
    expect(empreinteHtml(html)).toBe("/static/css/main.def456.css|/static/js/main.abc123.js");
  });

  test("empreinteHtml vide sans fichier principal", () => {
    expect(empreinteHtml("<html></html>")).toBe("");
    expect(empreinteHtml(null)).toBe("");
  });

  test("empreinteChargee lit le document", () => {
    document.head.innerHTML = '<script src="/static/js/main.abc123.js"></script>';
    expect(empreinteChargee(document)).toBe("/static/js/main.abc123.js");
    document.head.innerHTML = "";
  });

  test("nouvelleVersionDisponible", () => {
    expect(nouvelleVersionDisponible("a", "b")).toBe(true);
    expect(nouvelleVersionDisponible("a", "a")).toBe(false);
    expect(nouvelleVersionDisponible("", "b")).toBe(false);
    expect(nouvelleVersionDisponible("a", "")).toBe(false);
  });
});
