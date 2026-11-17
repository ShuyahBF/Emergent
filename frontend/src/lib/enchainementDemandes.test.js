// Tests de la vue d'enchaînement des demandes non terminées (logique pure).
import { avecPredecesseurs, demandesOuvertes, pointsMorts, resume } from "./enchainementDemandes";

const J = 86400000;
const NOW = new Date("2026-11-17T12:00:00").getTime();
const iso = (n) => new Date(NOW + n * J).toISOString();
const jour = (n) => iso(n).slice(0, 10);
const demandes = [
  { id: "a", statut: "remontee", demandee_le: iso(-40), prevue_le: jour(-30) },   // terminée (date dépassée) il y a 30 j
  { id: "b", statut: "remontee", demandee_le: iso(-20), prevue_le: jour(5) },     // commence 10 j après la fin de a
  { id: "c", statut: "remontee", demandee_le: iso(-30), prevue_le: null },        // sans date depuis 30 j : point mort
  { id: "e", statut: "realisee", demandee_le: iso(-50), realisee_le: iso(-45) },  // terminée : ignorée
  { id: "f", statut: "refusee", demandee_le: iso(-5) },                           // refusée : ignorée
];

test("seules les demandes non terminées sont gardées, avec leur état", () => {
  const o = demandesOuvertes(demandes, NOW);
  expect(o.map((x) => [x.id, x.etat])).toEqual([["a", "en_retard"], ["c", "point_mort"], ["b", "prevue"]]);
});

test("une demande suit celle qui se termine juste avant son début", () => {
  const o = avecPredecesseurs(demandesOuvertes(demandes, NOW));
  expect(o.find((x) => x.id === "b").suit).toBe("a");
  expect(o.find((x) => x.id === "a").suit).toBeNull();
});

test("points morts : période sans aucune demande en cours", () => {
  const seules = demandesOuvertes(demandes.filter((d) => d.id !== "c"), NOW);       // sans c, il y a un trou de 10 j entre a et b
  expect(pointsMorts(seules).map((t) => t.jours)).toEqual([10]);
  expect(pointsMorts(demandesOuvertes(demandes, NOW))).toEqual([]);                  // c couvre le trou
  const r = resume(seules, pointsMorts(seules));
  expect(r).toMatchObject({ ouvertes: 2, en_retard: 1, trous: 1, jours_a_l_arret: 10 });
});
