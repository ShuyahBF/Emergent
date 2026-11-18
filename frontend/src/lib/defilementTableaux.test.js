import { LIGNES_MAX, appliquer, compterLignes, conteneurDeDefilement } from "./defilementTableaux";

/** Construit <div style="overflow-x:auto"><table> avec n lignes de données. */
function tableau(n, { enveloppe = true } = {}) {
  document.body.innerHTML = "";
  const div = document.createElement("div");
  if (enveloppe) div.style.overflowX = "auto";
  const table = document.createElement("table");
  table.innerHTML = `<thead><tr><th>A</th></tr></thead><tbody>${Array.from({ length: n }, (_, i) => `<tr><td>${i}</td></tr>`).join("")}</tbody>`;
  div.appendChild(table);
  document.body.appendChild(div);
  return { div, table };
}

test("30 lignes ou moins : aucun défilement", () => {
  const { div, table } = tableau(LIGNES_MAX);
  expect(compterLignes(table)).toBe(30);
  expect(appliquer(table)).toBe(false);
  expect(div.hasAttribute("data-defilement")).toBe(false);
});

test("31 lignes : le conteneur défile et l'en-tête reste visible", () => {
  const { div, table } = tableau(LIGNES_MAX + 1);
  expect(appliquer(table)).toBe(true);
  expect(div.getAttribute("data-defilement")).toBe("oui");
  expect(div.style.overflowY).toBe("auto");
  expect(div.style.maxHeight).toMatch(/^\d+px$/);
  expect(div.getAttribute("tabindex")).toBe("0");
});

test("le tableau qui repasse sous la limite retrouve sa hauteur naturelle", () => {
  const { div, table } = tableau(45);
  appliquer(table);
  Array.from(table.tBodies[0].rows).slice(30).forEach((r) => r.remove());
  expect(appliquer(table)).toBe(false);
  expect(div.hasAttribute("data-defilement")).toBe(false);
  expect(div.style.maxHeight).toBe("");
});

test("exception data-sans-defilement et conteneur introuvable", () => {
  const { table } = tableau(60);
  table.setAttribute("data-sans-defilement", "");
  expect(appliquer(table)).toBe(false);
  const sans = tableau(60, { enveloppe: false });
  const frere = document.createElement("p");
  sans.div.appendChild(frere);                       // le parent contient autre chose que le tableau : on ne le touche pas
  expect(conteneurDeDefilement(sans.table)).toBeNull();
  expect(appliquer(sans.table)).toBe(false);
});

test("sans enveloppe mais parent réservé au tableau : le parent porte le défilement", () => {
  const { div, table } = tableau(60, { enveloppe: false });
  expect(conteneurDeDefilement(table)).toBe(div);
  expect(appliquer(table)).toBe(true);
});
