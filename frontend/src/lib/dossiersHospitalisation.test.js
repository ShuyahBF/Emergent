// Tests de la logique pure de la page « Loois → Dossiers d'hospitalisation » (lot 448).
import {
  FENETRES_MAX, TAILLE_FENETRE, dateFr, dateIso, fenetre, indexColonne, jourIso, libellePatient, lireDossier, lireNoms,
  dansLaPeriode, paquets, periodeDepassee, sqlFenetre, sqlMax, sqlPatients,
} from "./dossiersHospitalisation";

const COLS = ["Dos_num", "Dos_lib", "Da_dépôt", "He_Dépôt", "Montant", "Client", "Modificateur", "Réglé"];

describe("requêtes validées sur IPM le 18/11/2026", () => {
  test("le nom du fichier avec espace est entre crochets", () => {
    expect(sqlMax()).toBe("SELECT MAX([Dos_num]) FROM [DOSSIER EXAMEN]");
    expect(sqlFenetre(105001, 105200)).toContain("FROM [DOSSIER EXAMEN] WHERE [Dos_num] >= 105001 AND [Dos_num] <= 105200 LIMIT 200");
  });
  test("fenêtres de 200 numéros, jamais sous 1", () => {
    expect(fenetre(134668)).toEqual({ bas: 134469, haut: 134668 });
    expect(fenetre(50)).toEqual({ bas: 1, haut: 50 });
    expect(TAILLE_FENETRE).toBe(200);
    expect(FENETRES_MAX).toBe(40);
  });
  test("requête des patients : seulement des entiers positifs, sans doublon (aucun texte libre dans le SQL)", () => {
    expect(sqlPatients([5, "7", 5, "x'; DROP", -2, 0, 3.5])).toBe("SELECT [Numéro_Enreg], [Nom], [Prénoms] FROM [Patient] WHERE [Numéro_Enreg] IN (5, 7)");
    expect(sqlPatients([])).toBeNull();
    expect(sqlPatients(["abc"])).toBeNull();
  });
  test("paquets", () => {
    expect(paquets([1, 2, 3, 4, 5], 2)).toEqual([[1, 2], [3, 4], [5]]);
  });
});

describe("lecture des cellules", () => {
  test("dates et colonnes malgré des accents abîmés", () => {
    expect(dateIso("2026-02-14 07:49:13")).toBe("2026-02-14");
    expect(dateIso("14/02/2026")).toBe("2026-02-14");
    expect(dateIso("n'importe quoi")).toBe("");
    expect(dateFr("2026-02-14")).toBe("14/02/2026");
    expect(dateFr("")).toBe("—");
    expect(indexColonne(["Dos_num", "Da_d?p?t"], "Da_dépôt")).toBe(-1);   // « ? » remplace l'accent : colonne non reconnue (repli prévu par l'écran)
    expect(indexColonne(["DOS_NUM", "da_depot"], "Da_dépôt")).toBe(1);
  });
  test("un dossier lu depuis une ligne", () => {
    const d = lireDossier(["105001", "Caisse: Divers", "2026-02-14 07:49:13", "07:49:13", "1500,5", "321", "AB", "1"], COLS);
    expect(d).toMatchObject({ numero: 105001, libelle: "Caisse: Divers", date: "2026-02-14", heure: "07:49", montant: 1500.5, codePatient: 321, modificateur: "AB", regle: true });
    expect(lireDossier(["abc"], COLS)).toBeNull();
  });
  test("noms des patients et libellé de repli", () => {
    const noms = lireNoms([["321", "BADINI", "Awa"], ["x", "?", "?"]], ["Numéro_Enreg", "Nom", "Prénoms"]);
    expect(noms).toEqual({ 321: "BADINI Awa" });
    expect(libellePatient({ codePatient: 321 }, noms)).toBe("BADINI Awa");
    expect(libellePatient({ codePatient: 999 }, noms)).toBe("Patient n° 999");
    expect(libellePatient({ codePatient: null }, noms)).toBe("—");
  });
});

describe("période", () => {
  const d = (date) => ({ numero: 1, date });
  test("la lecture s'arrête quand un dossier de la fenêtre est plus ancien que le début", () => {
    expect(periodeDepassee([d("2026-11-01"), d("2026-10-20")], "2026-10-25")).toBe(true);
    expect(periodeDepassee([d("2026-11-01"), d("2026-10-30")], "2026-10-25")).toBe(false);
    expect(periodeDepassee([d("")], "2026-10-25")).toBe(false);
  });
  test("filtre de période : un dossier sans date lisible n'est jamais caché", () => {
    const l = [d("2026-10-20"), d("2026-10-26"), d(""), d("2026-11-30")];
    expect(dansLaPeriode(l, "2026-10-25", "2026-11-18").map((x) => x.date)).toEqual(["2026-10-26", ""]);
  });
  test("jour décalé", () => {
    expect(jourIso(new Date(2026, 10, 18), 30)).toBe("2026-10-19");
    expect(jourIso(new Date(2026, 2, 1), 1)).toBe("2026-02-28");
  });
});
