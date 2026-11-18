// Tests de la logique pure de la page « Loois → Dossiers d'hospitalisation » (lot 448).
import {
  FENETRES_MAX, PERIODES, PERIODE_DEFAUT, TAILLE_FENETRE, dateFr, dateIso, fenetre, indexColonne, jourIso, libellePatient, lireDossier, lireNoms,
  dansLaPeriode, lireNomsJointure, paquets, periodeDepassee, plusRecentsDabord, prendrePaquet, sqlFenetreJointure, sqlFenetre, sqlFenetreToutes, sqlMax, sqlPatients,
} from "./dossiersHospitalisation";

const COLS = ["Dos_num", "Dos_lib", "Da_dépôt", "He_Dépôt", "Montant", "Numéro_Enreg", "Modificateur", "Réglé"];

describe("requêtes validées sur IPM le 18/11/2026", () => {
  test("le lien dossier → patient est Numéro_Enreg, jamais Client", () => {
    expect(sqlFenetre(1, 200)).toContain("[Numéro_Enreg]");
    expect(sqlFenetre(1, 200)).not.toContain("[Client]");
    expect(sqlFenetreToutes(105001, 105200)).toBe("SELECT * FROM [DOSSIER EXAMEN] WHERE [Dos_num] >= 105001 AND [Dos_num] <= 105200 LIMIT 200");   // repli
    expect(indexColonne(["DOS_NUM", "NUMERO_ENREG"], "Numéro_Enreg")).toBe(1);                                                                      // nom sans accent retrouvé
  });
  test("le nom du fichier avec espace est entre crochets", () => {
    expect(sqlMax()).toBe("SELECT MAX([Dos_num]) FROM [DOSSIER EXAMEN]");
    expect(sqlFenetre(105001, 105200)).toContain("FROM [DOSSIER EXAMEN] WHERE [Dos_num] >= 105001 AND [Dos_num] <= 105200 LIMIT 200");
  });
  test("fenêtres de 200 numéros, jamais sous 1", () => {
    expect(fenetre(134668)).toEqual({ bas: 134469, haut: 134668 });
    expect(fenetre(50)).toEqual({ bas: 1, haut: 50 });
    expect(TAILLE_FENETRE).toBe(200);
    expect(FENETRES_MAX).toBe(80);
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
    expect(libellePatient({ codePatient: 999 }, noms)).toBe("Code n° 999");
    expect(libellePatient({ codePatient: null }, noms)).toBe("—");
  });
});

describe("jointure dossiers + patients (une requête par tranche)", () => {
  test("requête : une seule instruction, LEFT JOIN sur Numéro_Enreg, 200 lignes au plus", () => {
    const sql = sqlFenetreJointure(105001, 105200);
    expect(sql).toContain("FROM [DOSSIER EXAMEN] D LEFT JOIN [Patient] P ON D.[Numéro_Enreg] = P.[Numéro_Enreg]");
    expect(sql).toContain("WHERE D.[Dos_num] >= 105001 AND D.[Dos_num] <= 105200 LIMIT 200");
    assert.ok(!sql.includes(";"));
  });
  test("noms lus dans le résultat ; null si ce n'est pas une jointure", () => {
    const cols = ["Dos_num", "Dos_lib", "Da_dépôt", "He_Dépôt", "Montant", "Numéro_Enreg", "Modificateur", "Réglé", "Nom", "Prénoms"];
    const lignes = [["1", "x", "2026-11-18", "10:00", "0", "321", "AB", "1", "DIALLO", "Ousseni"], ["2", "x", "2026-11-18", "10:01", "0", "654", "AB", "0", "", ""], ["3", "x", "2026-11-18", "10:02", "0", "", "AB", "0", "ZONGO", "R"]];
    expect(lireNomsJointure(lignes, cols)).toEqual({ 321: "DIALLO Ousseni" });             // patient absent (LEFT JOIN) ou code illisible : ignorés
    expect(lireNomsJointure(lignes, ["Dos_num", "Dos_lib"])).toBeNull();
    expect(lireNomsJointure(lignes, ["DOS_NUM", "NUMERO_ENREG", "NOM", "PRENOMS"])).toEqual({});   // accents et casse ignorés (indices décalés : aucune ligne valide)
  });
});

describe("lecture des noms en parallèle", () => {
  test("un paquet complet dès que la file est assez pleine, le reste seulement quand les dossiers sont finis", () => {
    const file = [1, 2, 3, 4, 5];
    expect(prendrePaquet(file, 3, false)).toEqual([1, 2, 3]);            // file assez pleine : paquet de 3
    expect(file).toEqual([4, 5]);                                         // les codes pris sont retirés de la file
    expect(prendrePaquet(file, 3, false)).toBeNull();                     // pas assez de codes et dossiers pas finis : on attend (pas de petit paquet)
    expect(prendrePaquet(file, 3, true)).toEqual([4, 5]);                 // dossiers finis : on vide ce qui reste
    expect(file).toEqual([]);
    expect(prendrePaquet(file, 3, true)).toBeNull();                      // plus rien
  });
});

describe("affichage", () => {
  test("du plus récent au plus ancien, 7 jours par défaut, jusqu'à 90 jours", () => {
    expect(plusRecentsDabord([{ numero: 134481 }, { numero: 134680 }, { numero: 134500 }]).map((d) => d.numero)).toEqual([134680, 134500, 134481]);
    expect(plusRecentsDabord(null)).toEqual([]);
    expect(PERIODE_DEFAUT).toBe("7");
    expect(PERIODES.map((p) => p.jours)).toEqual([7, 30, 60, 90]);
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
