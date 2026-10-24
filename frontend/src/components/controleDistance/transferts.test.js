import { clePartiel, debutReception, departDemande, effacerTransferts, interrompre, oublierPartiels, reprenable } from "./transferts";

const octets = (n) => new ArrayBuffer(n);

describe("reprise d'un fichier récupéré du poste", () => {
  test("le poste reprend là où on s'est arrêté : le partiel est continué", () => {
    const partiels = new Map();
    const cle = clePartiel("p1", "C:\\Sauvegarde.rar");
    const a = debutReception(partiels, cle, { nom: "Sauvegarde.rar", taille: 1000, depuis: 0, modifie: 50 });
    expect(a.repris).toBe(false);
    a.partiel.morceaux.push(octets(600));
    a.partiel.recu = 600;
    expect(departDemande(partiels, cle)).toEqual({ depuis: 600, modifie: 50 });
    const b = debutReception(partiels, cle, { nom: "Sauvegarde.rar", taille: 1000, depuis: 600, modifie: 50 });
    expect(b.repris).toBe(true);
    expect(b.partiel).toBe(a.partiel);
    expect(b.partiel.recu).toBe(600);
  });

  test("fichier modifié, taille différente ou poste sans reprise : on repart de zéro", () => {
    const partiels = new Map();
    const cle = clePartiel("p1", "C:\\x");
    const a = debutReception(partiels, cle, { nom: "x", taille: 1000, modifie: 50 });
    a.partiel.recu = 600;
    expect(debutReception(partiels, cle, { nom: "x", taille: 1000, depuis: 600, modifie: 51 }).repris).toBe(false);   // date changée
    partiels.set(cle, { nom: "x", taille: 1000, modifie: 50, morceaux: [octets(600)], recu: 600 });
    expect(debutReception(partiels, cle, { nom: "x", taille: 2000, depuis: 600, modifie: 50 }).repris).toBe(false);   // taille changée
    partiels.set(cle, { nom: "x", taille: 1000, modifie: 50, morceaux: [octets(600)], recu: 600 });
    const ancien = debutReception(partiels, cle, { nom: "x", taille: 1000 });                                          // ancien poste : pas de « depuis »
    expect(ancien.repris).toBe(false);
    expect(ancien.partiel.recu).toBe(0);
  });

  test("sans partiel ou sans date connue, on demande le fichier depuis le début", () => {
    const partiels = new Map();
    expect(departDemande(partiels, "p1|x")).toEqual({ depuis: 0, modifie: 0 });
    partiels.set("p1|x", { nom: "x", taille: 1000, modifie: 0, morceaux: [], recu: 500 });                             // date inconnue (ancien poste)
    expect(departDemande(partiels, "p1|x")).toEqual({ depuis: 0, modifie: 0 });
    partiels.set("p1|x", { nom: "x", taille: 1000, modifie: 9, morceaux: [], recu: 1000 });                            // déjà complet
    expect(departDemande(partiels, "p1|x")).toEqual({ depuis: 0, modifie: 0 });
  });
});

describe("historique des transferts", () => {
  const partiels = new Map([["p1|a", { nom: "a", taille: 1000, modifie: 5, morceaux: [], recu: 400 }]]);
  const liste = () => [
    { uid: 1, sens: "reception", nom: "a", taille: 1000, fait: 400, cle: "p1|a" },                      // en cours (liaison tombée)
    { uid: 2, sens: "envoi", nom: "b", taille: 10, fait: 10, fini: true },
    { uid: 3, sens: "envoi", nom: "c", taille: 10, fait: 3, fichier: { name: "c" } },
    { uid: 4, sens: "envoi", nom: "d", taille: 10, fait: 5 },                                              // sans fichier gardé
  ];

  test("la liaison tombe : les transferts en cours sont marqués interrompus, reprenables ou non", () => {
    const l = interrompre(liste(), partiels);
    expect(l[0]).toMatchObject({ erreur: "connexion interrompue", interrompu: true, reprenable: true });
    expect(l[1].erreur).toBeUndefined();                                                                    // le terminé reste terminé
    expect(l[2].reprenable).toBe(true);
    expect(l[3].reprenable).toBe(false);
    expect(reprenable({ sens: "reception", cle: "p1|a" }, partiels)).toBe(true);
  });

  test("effacer : une ligne, ou tout ; jamais un transfert en cours", () => {
    const l = interrompre(liste(), partiels);
    const une = effacerTransferts(l, { uid: 2 });
    expect(une.liste.map((x) => x.uid)).toEqual([1, 3, 4]);
    const tout = effacerTransferts(l, { tout: true });
    expect(tout.liste).toEqual([]);
    expect(tout.retires).toHaveLength(4);
    const enCours = effacerTransferts(liste(), { tout: true });                                              // aucun n'est terminé ni en échec, sauf le n° 2
    expect(enCours.liste.map((x) => x.uid)).toEqual([1, 3, 4]);
    oublierPartiels(tout.retires, partiels);
    expect(partiels.has("p1|a")).toBe(false);                                                                // mémoire libérée
  });
});
