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

// ---- Lot 429 : planning par DURÉE ESTIMÉE (début prévu → fin prévue), « en cours » et « point mort » déclaré
const planifiees = [
  { id: "p1", statut: "en_cours", demandee_le: iso(-10), debut_prevu_le: jour(-2), prevue_le: jour(5) },                 // en cours : 7 j
  { id: "p2", statut: "remontee", demandee_le: iso(-9), debut_prevu_le: jour(5), prevue_le: jour(8) },                   // commence quand p1 finit
  { id: "p3", statut: "remontee", demandee_le: iso(-8), debut_prevu_le: jour(8), prevue_le: jour(15) },
  { id: "pm", statut: "point_mort", demandee_le: iso(-30), debut_le: jour(-20) },                                        // arrêtée depuis 20 j
  { id: "re", statut: "en_cours", demandee_le: iso(-30), debut_prevu_le: jour(-20), prevue_le: jour(-3) },               // fin dépassée
];

test("barres du planning : du début prévu à la fin prévue, états en cours / en attente / retard / point mort", () => {
  const o = demandesOuvertes(planifiees, NOW);
  const par = Object.fromEntries(o.map((x) => [x.id, x]));
  expect(par.p1.etat).toBe("en_cours");
  expect(par.p2.etat).toBe("prevue");
  expect(par.re.etat).toBe("en_retard");
  expect(par.pm.etat).toBe("point_mort_declare");
  expect(par.p2.debut).toBe(par.p1.fin);                                    // la 2e commence quand la 1re finit
  expect(par.p2.planifiee).toBe(true);
});

test("l'enchaînement par durées : p2 suit p1, p3 suit p2", () => {
  const o = avecPredecesseurs(demandesOuvertes(planifiees, NOW));
  expect(o.find((x) => x.id === "p2").suit).toBe("p1");
  expect(o.find((x) => x.id === "p3").suit).toBe("p2");
});

test("le résumé compte les demandes en cours et les points morts déclarés", () => {
  const o = demandesOuvertes(planifiees, NOW);
  const r = resume(o, pointsMorts(o));
  expect(r.en_cours).toBe(1);
  expect(r.points_morts).toBe(1);
  expect(r.en_retard).toBe(1);
});

// ---- Chevauchement et dates de l'ensemble (lot 429.1)
import { chevauchements, projet } from "./enchainementDemandes";
const enParallele = [
  { id: "x", statut: "en_cours", demandee_le: iso(-5), debut_prevu_le: jour(0), prevue_le: jour(10) },
  { id: "y", statut: "remontee", demandee_le: iso(-4), debut_prevu_le: jour(5), prevue_le: jour(12) },      // chevauche x pendant 5 j
  { id: "z", statut: "remontee", demandee_le: iso(-3), debut_prevu_le: jour(12), prevue_le: jour(15) },     // suit y : pas de chevauchement
];

test("chevauchement : deux demandes menées en même temps ; une qui commence quand l'autre finit n'en est pas un", () => {
  const ch = chevauchements(demandesOuvertes(enParallele, NOW));
  expect(ch.length).toBe(1);
  expect(ch[0].jours).toBe(5);
});

test("durée et dates de l'ensemble : de la première à la dernière", () => {
  const p = projet(demandesOuvertes(enParallele, NOW));
  expect(p.jours).toBe(15);
  expect(projet([])).toBeNull();
  expect(resume(demandesOuvertes(enParallele, NOW), []).chevauchements).toBe(1);
});
