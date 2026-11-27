"""Lot 475 — API « Loois mobile » : requêtes préparées, connexion (mot de passe jamais gardé ni renvoyé), droits (caissier / administrateur / laboratoire), Historique de Caisse,
détail d'un reçu, Corrections de reçus, journal d'audit. Aucun accès réseau : la file « SQL à distance » est remplacée par une file simulée (Mongo simulé)."""
import asyncio
import re
import os
from datetime import datetime

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot475")

import mongomock_motor
import pytest

import android_loois as al
import appareils_android as aa


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ------------------------------------------------------------------------------------------------------------------ fonctions pures
def test_formats_hfsql_et_regles_de_validite():
    assert al.date_vente("20261126093415000") == datetime(2026, 11, 26, 9, 34, 15) and al.date_vente("20261126") == datetime(2026, 11, 26)
    assert al.date_vente("26/11/2026 09:34:15") == datetime(2026, 11, 26, 9, 34, 15) and al.date_vente("2026-11-26 09:34:15") == datetime(2026, 11, 26, 9, 34, 15)
    assert al.date_vente("") is None and al.date_vente("n'importe quoi") is None
    assert al.nombre("1 234,50") == 1234.5 and al.nombre("12 000") == 12000 and al.nombre("abc") == 0
    assert al.vrai("1") and al.vrai("Vrai") and al.vrai("True") and not al.vrai("0") and not al.vrai("")
    # règle de Loois : durée propre > 0 ET (clinique inconnue OU différente)
    assert al.necessite_correction(60, 30) and al.necessite_correction(60, None) and not al.necessite_correction(30, 30) and not al.necessite_correction(None, 30) and not al.necessite_correction(0, 30)
    assert al.date_expiration(datetime(2026, 11, 26, 15, 0), 30) == "2026-12-25 23:59:59"            # émission sans l'heure + 30 j − 1 s
    assert al.date_expiration(None, 30) == ""


def test_requetes_preparees_sans_injection_et_masquage():
    esp = al.ESPACES["biolog"]
    sql = al.sql_authentifier(esp, "o'brien", "x' OR '1'='1")
    assert "'o''brien'" in sql and "'x'' OR ''1''=''1'" in sql and "Mot_de_Passe" in sql and "SELECT [Login], [AutoriserCorrectionReçu]" in sql
    masque = al.masquer_sql_connexion(esp, "o'brien")
    assert "(mot de passe masqué)" in masque and "brien" not in masque and "OR" not in masque
    from datetime import date
    s = al.sql_recus_du_jour(date(2026, 11, 26), "tassembh")
    assert "Machine = 'TASSEMBH'" in s and "'20261126'" in s and "'20261127'" in s and "(Mag <> 'SUP' OR Mag IS NULL)" in s and "LIKE 'R-%'" in s and "TOP 201" in s
    assert "Machine" not in al.sql_recus_du_jour(date(2026, 11, 26), None).split("WHERE")[1].split("AND [Date")[0]
    assert not al.reference_valide("R-1'; DROP") and al.reference_valide("R-2026-0001") and not al.reference_valide("X-1")
    assert al.espace_de_la_zone("docx=CMC")["nom"] == "Biolog" and al.espace_de_la_zone("doc=PMT")["nom"] == "Aizenta" and al.espace_de_la_zone("ekol") is None


def test_droits_selon_les_regles_de_loois():
    b = al.ESPACES["biolog"]
    assert al.droits(b, "supervisEU", "", False, False)["voir_tous_les_recus"] is True
    labo = al.droits(b, "LAB1", "labo", True, True)
    assert labo["consultation_seule"] and labo["voir_tous_les_recus"] and labo["corrections"] and labo["supprimer_recu"] is False
    caissier = al.droits(b, "TASSEMBH", "", False, False)
    assert not caissier["voir_tous_les_recus"] and not caissier["corrections"]
    assert al.droits(b, "TASSEMBH", "", True, False)["corrections"] is True
    assert al.droits(al.ESPACES["aizenta"], "AIZ", "", False, False)["caisse"] is False                      # Aizenta : pas de caisse


# ------------------------------------------------------------------------------------------------------------------ file SQL simulée + routes
RECUS = [  # Référence, Date Vente, Code Client, Libellé, MontantRéglé, Machine, PPC, PArtAssuré, PArtAssureur
    ["R-0003", "20261126101500000", "C1", "Awa BADINI", "15 000", "TASSEMBH", "0", "15000", "0"],
    ["R-0002", "20261126093000000", "C2", "Ben Kaboré", "8 500,50", "ASI2020", "0", "8500,5", "0"],
    ["R-0001", "20261126080000000", "C3", "Fatim Sawadogo", "2 000", "TASSEMBH", "0", "2000", "0"],
]
FACTURES = [["0461/2026", "20261126110000000", "C9", "Paul KABORE", "8 000", "ASI2020", "80", "8000", "32000"]]     # lot 491 : facture d'hospitalisation (Caisse FCT), faite par un AUTRE caissier
LIGNES = {"0461/2026": [["P2", "", "CONSULT", "1", "40000"]], "R-0003": [["P1", "M1", "PEDIATRIE", "1", "10000"], ["P2", "M1", "CONSULT", "2", "2500"]], "R-0002": [["P3", "M2", "CONSULT", "1", "8500,5"]], "R-0001": [["P2", "", "CONSULT", "1", "2000"]]}


def construire_banc():
    """Banc d'essai complet (application FastAPI, file SQL simulée, appareil autorisé) : utilisé par les tests ET par le script qui produit les exemples de réponses pour l'application Android."""
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    import routes.android_loois as ra
    import routes.loois_sql_distant as lsd
    ra._cache.clear()
    al._essais.clear()
    db = mongomock_motor.AsyncMongoMockClient()["test_lot475"]
    envoyees: list = []                                        # (sql, auteur)
    etat = {"login": "tassembh", "infos": {"R-0003": ["ASI01", "1", "0", "15 000", "15 000"], "R-0002": ["TASSEMBH", "0", "1", "0", "8 500,50"], "0461/2026": ["MED07", "0", "1", "0", "40 000"]}, "refuser_maj": False, "en_ligne": True, "mdp_ok": True, "groupe": "", "autoriser": "1", "suppr": "0", "silence": False}

    def repondre(sql: str):
        S = sql
        if S.startswith("SELECT Machine, COUNT(*), SUM(MontantRéglé)"):
            return [["TASSEMBH", "2", "17000"], ["ASI2020", "1", "8500,5"], ["", "1", "100"]]
        if S.startswith("SELECT COUNT(*), SUM(MontantRéglé)"):
            return [["4", "25 600,5"]] if ">= '20261126'" in S else [["0", ""]]
        if S.startswith("SELECT [Login], [AutoriserCorrectionReçu] FROM [UtilisateurBlg]"):
            return [[etat["login"], etat["autoriser"]]] if etat["mdp_ok"] else []
        if S.startswith("SELECT [GroupeLogin]"):
            return [[etat["groupe"]]]
        if S.startswith("SELECT [PeutSupprimerRecu]"):
            return [[etat["suppr"]]]
        if S.startswith("SELECT [Code Vendeur], [Réglé], [Visée]"):                       # lot 490 : VID, réglé, visé d'un reçu
            ref = S.split("Référence = '")[1].split("'")[0]
            return [etat["infos"][ref]] if ref in etat["infos"] else []
        if S.startswith("UPDATE VenteClinique SET"):                                      # lot 492 : « Réglé » et « Visée » seulement
            ref = S.split("Référence = '")[1].split("'")[0]
            if not etat["refuser_maj"] and ref in etat["infos"]:
                for col, val in re.findall(r"\[(Réglé|Visée)\] = ([01])", S):
                    etat["infos"][ref][1 if col == "Réglé" else 2] = val
                for val in re.findall(r"\[Date Vente\] = '(\d{17})'", S):
                    for r in RECUS + FACTURES:
                        if r[0] == ref:
                            r[1] = val
                for col, val in re.findall(r"\[(PArtAssuré|PArtAssureur)\] = ([0-9.]+)", S):
                    for r in RECUS + FACTURES:
                        if r[0] == ref:
                            r[7 if col == "PArtAssuré" else 8] = val
            return []
        if S.startswith("SELECT TOP 8") and "LIKE 'R-%" in S:                             # lot 490 : recherche par numéro (fin de numéro)
            fin = S.split("LIKE 'R-%")[1].split("'")[0]
            return [r for r in RECUS if r[0].endswith(fin)]
        if "FROM VenteClinique WHERE Référence LIKE" in S:
            rows = RECUS
            if "Machine = 'TASSEMBH'" in S:
                rows = [r for r in RECUS if r[5] == "TASSEMBH"]
            return rows
        if S.startswith("SELECT TOP 8") and "Référence IN ('" in S:                       # lot 491 : recherche d'une facture d'hospitalisation
            return [r for r in FACTURES if f"'{r[0]}'" in S]
        if "FROM VenteClinique WHERE Référence = " in S:
            ref = S.split("Référence = '")[1].split("'")[0]
            return [r for r in RECUS + FACTURES if r[0] == ref]
        if "FROM A_Acheté WHERE Référence = " in S:
            return LIGNES.get(S.split("Référence = '")[1].split("'")[0], [])
        if "FROM A_Acheté WHERE Référence IN" in S:
            refs = [x.strip("'") for x in S.split("IN (")[1].rstrip(")").split(",")]
            return [[r, l[2]] for r in refs for l in LIGNES.get(r, [])]
        if "FROM Clinique" in S:
            return [["30"]]
        if "FROM Prestations" in S:
            return [["PEDIATRIE", "60"]]
        if "FROM ProduitClinique" in S:
            return [["P1", "Consultation pédiatrique"], ["P2", "Consultation"], ["P3", "Consultation"]]
        if "FROM MédecinT" in S:
            return [["M1", "OUEDRAOGO", "Paul"], ["M2", "SAWADOGO", "Aïcha"]]
        return []

    async def creer(corps, ip, auteur=""):
        rid = f"r{len(envoyees)}"
        envoyees.append((corps["sql"], auteur))
        await db.loois_reglages.update_one({"id": "sql_distant"}, {"$push": {"requetes": {"id": rid, "client": corps["client"], "sql": corps["sql"], "etat": "attente"}}}, upsert=True)
        return {"id": rid}

    async def detail(rid):
        sql = envoyees[int(rid[1:])][0]
        if etat["silence"]:
            return {"etat": "attente"}
        await db.loois_reglages.update_one({"id": "sql_distant", "requetes.id": rid}, {"$set": {"requetes.$.etat": "terminee"}})
        return {"id": rid, "etat": "terminee", "ok": True, "lignes": repondre(sql), "colonnes": [], "message": ""}

    async def clients():
        return {"clients": [{"code": "CMC", "en_ligne": etat["en_ligne"]}]}
    lsd.INTERNE.clear()
    lsd.INTERNE.update(creer=creer, detail=detail, clients=clients)
    ra.ATTENTE_RESULTAT_S = 1.5
    ra.PAS_SONDAGE_S = 0.05

    app = FastAPI()
    api = APIRouter(prefix="/api")
    admin = {"user": {"id": "u1", "role": "admin"}}

    async def utilisateur():
        return admin["user"]
    ra.setup_android_loois_routes(db=db, api=api, get_current_user=utilisateur)
    import routes.appareils_android as rap                                   # enregistrement et statut de l'appareil (lot 468)
    rap._limites.clear()
    rap.setup_appareils_android_routes(db=db, api=api, get_current_user=utilisateur)
    app.include_router(api)
    from fastapi.testclient import TestClient
    c = TestClient(app)
    fiche, jeton = aa.nouvelle_fiche("ANDROID-ID-123456", "Tab", "1.0", "41.1.1.1")
    fiche.update(etat="autorise", zone="docx=CMC", base="myAurora-CMC", client_code="CMC", nom_utilisateur="Awa")
    run(aa.creer(db, fiche))
    return c, {"jeton": jeton, "fiche": fiche, "db": db, "etat": etat, "envoyees": envoyees, "admin": admin}


@pytest.fixture()
def banc():
    return construire_banc()


def entetes(b, session=None):
    h = {"Authorization": f"Bearer {b['jeton']}", "X-Forwarded-For": "41.138.7.7"}
    if session:
        h["X-Session"] = session
    return h


def se_connecter(c, b, mdp="secret123"):
    r = c.post("/api/android/connexion", json={"login": "tassembh", "mot_de_passe": mdp}, headers=entetes(b))
    return r


def test_connexion_reussie_droits_et_mot_de_passe_jamais_garde(banc):
    c, b = banc
    r = se_connecter(c, b)
    assert r.status_code == 200
    d = r.json()
    assert d["utilisateur"] == {"login": "tassembh", "groupe": "", "espace": "Biolog"} and d["droits"]["corrections"] is True and d["droits"]["voir_tous_les_recus"] is False
    assert d["appareil"] == {"zone": "docx=CMC", "base": "myAurora-CMC", "client": "CMC"} and "secret123" not in r.text
    # le mot de passe a bien voyagé jusqu'au client…
    assert any("secret123" in sql for sql, _ in b["envoyees"])
    # … mais n'est plus dans l'historique de la file une fois la requête terminée (masquage en tâche de fond), ni dans le journal d'audit
    run(asyncio.sleep(0.3))
    doc = run(b["db"].loois_reglages.find_one({"id": "sql_distant"}))
    assert "secret123" not in str(doc)
    journal = run(b["db"].settings.find_one({"_id": "android_journal"}))
    assert "secret123" not in str(journal) and journal["lignes"][-1]["action"] == "connexion" and journal["lignes"][-1]["ip"] == "41.138.7.7" and journal["lignes"][-1]["resultat"] == "ok"


def test_mauvais_mot_de_passe_limite_d_essais_puis_blocage(banc):
    c, b = banc
    b["etat"]["mdp_ok"] = False
    for i in range(5):
        r = se_connecter(c, b, "faux")
        assert r.status_code == 401 and "incorrect" in r.json()["detail"]
    assert "0 essai" in r.json()["detail"]
    r = se_connecter(c, b, "faux")
    assert r.status_code == 429                                                                       # bloqué 15 minutes
    b["etat"]["mdp_ok"] = True
    assert se_connecter(c, b).status_code == 429                                                      # même le bon mot de passe pendant le blocage


def test_appareil_interdit_client_hors_ligne_zone_non_geree(banc):
    c, b = banc
    b["etat"]["en_ligne"] = False
    r = se_connecter(c, b)
    assert r.status_code == 503 and "n'est en ligne" in r.json()["detail"]                              # refus immédiat, sans attendre 40 s
    b["etat"]["en_ligne"] = True
    run(aa.modifier(b["db"], b["fiche"]["id"], {"zone": "ekol"}))
    assert se_connecter(c, b).status_code == 422
    run(aa.modifier(b["db"], b["fiche"]["id"], {"zone": "docx=CMC", "etat": "interdit"}))
    assert se_connecter(c, b).status_code == 403                                                      # l'interdiction est immédiate
    assert c.post("/api/android/connexion", json={"login": "a", "mot_de_passe": "b"}, headers={"Authorization": "Bearer faux"}).status_code == 401


def test_historique_caissier_voit_les_siens_administrateur_tous(banc):
    c, b = banc
    s = se_connecter(c, b).json()["session"]
    r = c.post("/api/android/caisse/historique", json={"date": "2026-11-26"}, headers=entetes(b, s))
    assert r.status_code == 200
    d = r.json()
    assert [x["reference"] for x in d["recus"]] == ["R-0003", "R-0001"] and d["nombre"] == 2 and d["total_montant"] == 17000 and d["portee"] == "TASSEMBH"
    assert d["recus"][0]["heure"] == "10:15" and d["recus"][0]["date_vente"] == "2026-11-26"
    assert c.post("/api/android/caisse/historique", json={"date": "26/11/2026"}, headers=entetes(b, s)).status_code == 422
    # un caissier ne peut pas demander un autre caissier : le filtre reste SON login
    c.post("/api/android/caisse/historique", json={"date": "2026-11-26", "caissier": "ASI2020"}, headers=entetes(b, s))
    assert "Machine = 'TASSEMBH'" in b["envoyees"][-1][0]
    # administrateur : tous les reçus
    b["etat"]["groupe"] = "LABO"
    s2 = se_connecter(c, b).json()["session"]
    r = c.post("/api/android/caisse/historique", json={"date": "2026-11-26"}, headers=entetes(b, s2))
    assert r.json()["nombre"] == 3 and r.json()["portee"] == "tous les caissiers"
    # session absente / d'un autre appareil
    assert c.post("/api/android/caisse/historique", json={}, headers=entetes(b)).status_code == 401


def test_detail_recu_lignes_validite_et_expiration(banc):
    c, b = banc
    s = se_connecter(c, b).json()["session"]
    r = c.post("/api/android/caisse/recu", json={"reference": "R-0003"}, headers=entetes(b, s))
    assert r.status_code == 200
    d = r.json()
    ped, cons = d["lignes"]
    assert ped["designation"] == "Consultation pédiatrique" and ped["medecin"] == "OUEDRAOGO Paul" and ped["necessite_correction"] is True and ped["jours_validite_propre"] == 60
    assert ped["date_expiration"] == "2027-01-24 23:59:59"                                                                      # 26/11/2026 + 60 j − 1 s
    assert cons["necessite_correction"] is False and cons["jours_validite_effective"] == 30 and cons["montant"] == 5000 and d["a_corriger"] is True and d["total"] == 15000
    assert c.post("/api/android/caisse/recu", json={"reference": "R-0002"}, headers=entetes(b, s)).status_code == 403          # reçu d'un autre caissier
    assert c.post("/api/android/caisse/recu", json={"reference": "R-0009"}, headers=entetes(b, s)).status_code == 404
    assert c.post("/api/android/caisse/recu", json={"reference": "R-1'; DROP"}, headers=entetes(b, s)).status_code == 422


def test_corrections_droit_requis_et_liste(banc):
    c, b = banc
    b["etat"]["autoriser"] = "0"
    s = se_connecter(c, b).json()["session"]
    assert c.post("/api/android/corrections/liste", json={"date": "2026-11-26"}, headers=entetes(b, s)).status_code == 403   # pas le droit de corriger
    b["etat"]["autoriser"] = "1"
    s = se_connecter(c, b).json()["session"]
    r = c.post("/api/android/corrections/liste", json={"date": "2026-11-26"}, headers=entetes(b, s))
    assert r.status_code == 200
    d = r.json()
    assert d["nombre"] == 2 and d["nombre_a_corriger"] == 1 and d["validite_clinique"] == 30
    assert [(x["reference"], x["a_corriger"], x["lignes_a_corriger"]) for x in d["recus"]] == [("R-0003", True, 1), ("R-0001", False, 0)]       # à corriger d'abord
    # le référentiel (clinique, prestations) est gardé : une 2e liste ne le relit pas
    avant = len(b["envoyees"])
    c.post("/api/android/corrections/liste", json={"date": "2026-11-26"}, headers=entetes(b, s))
    relus = [sql for sql, _ in b["envoyees"][avant:] if "FROM Clinique" in sql or "FROM Prestations" in sql]
    assert relus == []


def test_delai_depasse_et_journal_admin(banc):
    c, b = banc
    s = se_connecter(c, b).json()["session"]
    b["etat"]["silence"] = True
    r = c.post("/api/android/caisse/historique", json={"date": "2026-11-26"}, headers=entetes(b, s))
    assert r.status_code == 504 and "ne répond pas" in r.json()["detail"]
    b["etat"]["silence"] = False
    j = c.get("/api/admin/android-journal")
    assert j.status_code == 200 and j.json()["lignes"][0]["action"] == "connexion" and j.json()["total"] >= 1
    b["admin"]["user"] = {"id": "u2", "role": "client"}
    assert c.get("/api/admin/android-journal").status_code == 403


def test_tableau_de_bord_droits_jour_et_semaine(banc):
    # Lot 483 : le tableau de bord est réservé à l'administrateur et aux appareils de profil « client » ; jamais à un caissier ou au laboratoire
    c, b = banc
    s = se_connecter(c, b).json()["session"]
    assert c.post("/api/android/tableau-de-bord", json={"date": "2026-11-26"}, headers=entetes(b, s)).status_code == 403                 # caissier : refusé
    run(aa.modifier(b["db"], b["fiche"]["id"], {"profil": "client"}))
    cx = se_connecter(c, b).json()
    assert cx["droits"]["tableau_de_bord"] is True
    s = cx["session"]
    r = c.post("/api/android/tableau-de-bord", json={"date": "2026-11-26"}, headers=entetes(b, s))
    assert r.status_code == 200
    d = r.json()
    assert d["nombre"] == 4 and d["total_montant"] == 25600.5 and d["panier_moyen"] == 6400.12
    assert [x["caissier"] for x in d["par_caissier"]] == ["TASSEMBH", "ASI2020", "(sans caissier)"] and d["par_caissier"][0]["montant"] == 17000          # les plus gros montants d'abord
    assert "GROUP BY Machine" in b["envoyees"][-1][0] and "(Mag <> 'SUP' OR Mag IS NULL)" in b["envoyees"][-1][0]
    w = c.post("/api/android/tableau-de-bord/semaine", json={"date": "2026-11-26"}, headers=entetes(b, s)).json()
    assert [j["date"] for j in w["jours"]] == ["2026-11-20", "2026-11-21", "2026-11-22", "2026-11-23", "2026-11-24", "2026-11-25", "2026-11-26"]
    assert w["jours"][-1] == {"date": "2026-11-26", "nombre": 4, "montant": 25600.5} and w["jours"][0]["nombre"] == 0 and w["total_montant"] == 25600.5
    # les totaux sont gardés une minute : une 2e ouverture ne relance aucune requête
    avant = len(b["envoyees"])
    c.post("/api/android/tableau-de-bord", json={"date": "2026-11-26"}, headers=entetes(b, s))
    assert len(b["envoyees"]) == avant
    # administrateur (SUPERVISEU) sans profil client : accès ; laboratoire : jamais
    run(aa.modifier(b["db"], b["fiche"]["id"], {"profil": "agent"}))
    assert al.droits(al.ESPACES["biolog"], "SUPERVISEU", "", False, False)["tableau_de_bord"] is True
    assert al.droits(al.ESPACES["biolog"], "LAB1", "LABO", False, False, profil="client")["tableau_de_bord"] is False
    assert al.droits(al.ESPACES["aizenta"], "AIZ", "", False, False, profil="client")["tableau_de_bord"] is False                   # Aizenta : pas de caisse
    assert c.post("/api/android/tableau-de-bord", json={"date": "pas une date"}, headers=entetes(b, s)).status_code == 422


def test_lecture_des_agregats():
    assert al.lire_par_caissier([["A", "1", "100"], ["B", "3", "1 000,5"]]) == [{"caissier": "B", "nombre": 3, "montant": 1000.5}, {"caissier": "A", "nombre": 1, "montant": 100.0}]
    assert al.lire_agregat_jour([["4", "25 600,5"]]) == (4, 25600.5) and al.lire_agregat_jour([]) == (0, 0.0) and al.lire_agregat_jour([["0", ""]]) == (0, 0.0)
    from datetime import date
    s = al.sql_agregat_par_caissier(date(2026, 11, 26))
    assert "'20261126'" in s and "'20261127'" in s and s.endswith("GROUP BY Machine")


# ------------------------------------------------------------------------------------------------------------------ lot 490 : VID / réglé / visé et recherche par numéro
def test_numero_de_recherche_et_requetes_sans_injection():
    assert al.numero_recherche("R-202630889") == {"chiffres": "202630889", "reference": "R-202630889"}
    assert al.numero_recherche(" 30 889 ")["chiffres"] == "30889" and al.numero_recherche("r202630889")["reference"] == "R-202630889"
    assert al.numero_recherche("12") is None and al.numero_recherche("R-1'; DROP") is None and al.numero_recherche("") is None and al.numero_recherche("abc") is None
    sql = al.sql_recherche_recu("30889")
    assert "LIKE 'R-%30889'" in sql and "TOP 8" in sql and "(Mag <> 'SUP' OR Mag IS NULL)" in sql
    assert "[Code Vendeur]" in al.sql_infos_recu("R-1") and "[Visée]" in al.sql_infos_recu("R-1") and "Montant FROM" in al.sql_infos_recu("R-1")
    assert al.lire_infos_recu([["ASI01", "1", "0", "15 000", "20 000"]]) == {"vid": "ASI01", "regle": True, "vise": False, "montant_regle": 15000, "montant_total": 20000}
    assert al.lire_infos_recu([]) == {"vid": "", "regle": None, "vise": None, "montant_regle": None, "montant_total": None}      # inconnu ≠ « non »


def test_detail_porte_vid_regle_et_vise_et_la_recherche_trouve_le_recu(banc):
    c, b = banc
    s = se_connecter(c, b).json()["session"]
    d = c.post("/api/android/caisse/recu", json={"reference": "R-0003"}, headers=entetes(b, s)).json()
    assert d["infos"] == {"vid": "ASI01", "regle": True, "vise": False, "montant_regle": 15000, "montant_total": 15000} and d["recu"]["caissier"] == "TASSEMBH"
    r = c.post("/api/android/caisse/recu/recherche", json={"numero": "0003"}, headers=entetes(b, s)).json()
    assert r["nombre"] == 1 and r["recus"][0]["reference"] == "R-0003"
    # un caissier (TASSEMBH) ne retrouve pas le reçu d'un autre caissier (R-0002 est à ASI2020)
    assert c.post("/api/android/caisse/recu/recherche", json={"numero": "0002"}, headers=entetes(b, s)).json()["nombre"] == 0
    assert c.post("/api/android/caisse/recu/recherche", json={"numero": "12"}, headers=entetes(b, s)).status_code == 422
    journal = run(b["db"].settings.find_one({"_id": "android_journal"}))
    assert any(l["action"] == "recherche_recu" for l in journal["lignes"])


# ------------------------------------------------------------------------------------------------------------------ lot 491 : facture d'hospitalisation « 0461/2026 »
def test_numero_de_facture_d_hospitalisation():
    assert al.reference_valide("0461/2026") and al.reference_valide("R-0003") and not al.reference_valide("461/26") and not al.reference_valide("0461/2026'; DROP")
    assert al.est_facture_hospi("0461/2026") and not al.est_facture_hospi("R-0003")
    n = al.numero_recherche(" 461 / 2026 ")
    assert n["reference"] == "0461/2026" and n["sans_zero"] == "461/2026" and n["facture"] == "1"
    assert al.numero_recherche("0461/2026")["reference"] == "0461/2026" and al.numero_recherche("0461/20") is None and al.numero_recherche("04/61/2026") is None
    assert "IN ('0461/2026', '461/2026')" in al.sql_recherche_facture("0461/2026", "461/2026")


def test_une_facture_d_hospitalisation_se_retrouve_et_s_ouvre_meme_si_un_autre_caissier_l_a_faite(banc):
    c, b = banc
    s = se_connecter(c, b).json()["session"]                                   # TASSEMBH : la facture est à ASI2020
    r = c.post("/api/android/caisse/recu/recherche", json={"numero": "0461/2026"}, headers=entetes(b, s)).json()
    assert r["nombre"] == 1 and r["recus"][0]["reference"] == "0461/2026" and r["recus"][0]["ppc"] == 80
    r2 = c.post("/api/android/caisse/recu/recherche", json={"numero": "461/2026"}, headers=entetes(b, s)).json()
    assert r2["nombre"] == 1                                                   # sans le zéro de tête
    d = c.post("/api/android/caisse/recu", json={"reference": "0461/2026"}, headers=entetes(b, s))
    assert d.status_code == 200, d.text
    d = d.json()
    assert d["recu"]["caissier"] == "ASI2020" and d["infos"] == {"vid": "MED07", "regle": False, "vise": True, "montant_regle": 0.0, "montant_total": 40000} and len(d["lignes"]) == 1
    # un reçu ordinaire d'un autre caissier reste refusé
    assert c.post("/api/android/caisse/recu", json={"reference": "R-0002"}, headers=entetes(b, s)).status_code == 403


# ------------------------------------------------------------------------------------------------------------------ lot 492 : le superviseur modifie « Réglé » et « Visée »
def session_superviseur(c, b):
    b["etat"]["login"] = "SUPERVISEU"
    return se_connecter(c, b).json()["session"]


def test_requete_de_modification_limitee_a_regle_et_vise():
    sql = al.sql_modifier_recu("R-0003", True, False)
    assert sql == "UPDATE VenteClinique SET [Réglé] = 1, [Visée] = 0 WHERE Référence = 'R-0003'"
    assert al.sql_modifier_recu("0461/2026", None, True) == "UPDATE VenteClinique SET [Visée] = 1 WHERE Référence = '0461/2026'"
    with pytest.raises(ValueError):
        al.sql_modifier_recu("R-0003", None, None)
    from routes.loois_sql_distant import verifier
    assert verifier(sql)[0] is True                                                                    # accepté par le contrôle « Prudent » (UPDATE avec WHERE)


def test_le_superviseur_modifie_regle_et_vise_relu_et_journalise(banc):
    c, b = banc
    s = session_superviseur(c, b)
    r = c.post("/api/android/caisse/recu/modifier", json={"reference": "0461/2026", "regle": True, "vise": False}, headers=entetes(b, s))
    assert r.status_code == 200, r.text
    assert r.json()["infos"]["regle"] is True and r.json()["infos"]["vise"] is False
    d = c.post("/api/android/caisse/recu", json={"reference": "0461/2026"}, headers=entetes(b, s)).json()
    assert d["infos"]["regle"] is True and d["infos"]["vise"] is False                                 # la base HFSQL (simulée) a bien été modifiée
    assert any(sql.startswith("UPDATE VenteClinique SET [Réglé] = 1, [Visée] = 0 WHERE Référence = '0461/2026'") for sql, _ in b["envoyees"])
    journal = run(b["db"].settings.find_one({"_id": "android_journal"}))
    derniere = [l for l in journal["lignes"] if l["action"] == "modifier_recu"][-1]
    assert derniere["resultat"] == "ok" and "réglé False→True" in derniere["detail"] and "visé True→False" in derniere["detail"]
    # une seule case : l'autre ne change pas ; rien à changer = refusé
    assert c.post("/api/android/caisse/recu/modifier", json={"reference": "0461/2026", "vise": True}, headers=entetes(b, s)).status_code == 200
    assert c.post("/api/android/caisse/recu/modifier", json={"reference": "0461/2026", "vise": True}, headers=entetes(b, s)).status_code == 422
    assert c.post("/api/android/caisse/recu/modifier", json={"reference": "0461/2026"}, headers=entetes(b, s)).status_code == 422
    assert c.post("/api/android/caisse/recu/modifier", json={"reference": "R-9999", "regle": True}, headers=entetes(b, s)).status_code == 404
    assert c.post("/api/android/caisse/recu/modifier", json={"reference": "R-1'; DROP", "regle": True}, headers=entetes(b, s)).status_code == 422


def test_un_caissier_ou_le_laboratoire_ne_peuvent_pas_modifier(banc):
    c, b = banc
    s = se_connecter(c, b).json()["session"]                                                           # caissier TASSEMBH
    r = c.post("/api/android/caisse/recu/modifier", json={"reference": "R-0003", "regle": False}, headers=entetes(b, s))
    assert r.status_code == 403 and "superviseur" in r.json()["detail"]
    assert not any(sql.startswith("UPDATE") for sql, _ in b["envoyees"])                              # rien n'est parti vers le client
    b["etat"]["login"] = "LAB1"; b["etat"]["groupe"] = "labo"
    s2 = se_connecter(c, b).json()["session"]
    assert c.post("/api/android/caisse/recu/modifier", json={"reference": "R-0003", "regle": False}, headers=entetes(b, s2)).status_code == 403
    assert not any(sql.startswith("UPDATE") for sql, _ in b["envoyees"])


def test_modification_non_confirmee_par_la_base_est_signalee(banc):
    c, b = banc
    s = session_superviseur(c, b)
    b["etat"]["refuser_maj"] = True                                                                    # la base n'applique pas la modification
    r = c.post("/api/android/caisse/recu/modifier", json={"reference": "R-0003", "regle": False}, headers=entetes(b, s))
    assert r.status_code == 502 and "ne la confirme pas" in r.json()["detail"]
    journal = run(b["db"].settings.find_one({"_id": "android_journal"}))
    assert [l for l in journal["lignes"] if l["action"] == "modifier_recu"][-1]["resultat"] == "non confirmé"


# ------------------------------------------------------------------------------------------------------------------ lot 493 : montant, PPC, parts assuré / assureur (la contrepartie est déduite)
def test_parts_deduites_du_total():
    assert al.parts_deduites(40000, None, 25000) == (15000, 25000)               # part assureur donnée : l'assuré paie le reste
    assert al.parts_deduites(40000, 8000, None) == (8000, 32000)                 # part assuré donnée : l'assureur prend le reste
    assert al.parts_deduites(40000, 10000, 30000) == (10000, 30000)
    for mauvais in ((40000, 10000, 20000), (40000, -1, None), (40000, None, 40001), (40000, float("nan"), None)):
        with pytest.raises(ValueError):
            al.parts_deduites(*mauvais)
    with pytest.raises(ValueError):
        al.parts_deduites(None, 100, None)                                         # total inconnu : jamais de répartition devinée
    assert al.sql_modifier_recu("0461/2026", None, None, 10000, 30000) == "UPDATE VenteClinique SET [PArtAssuré] = 10000.00, [PArtAssureur] = 30000.00 WHERE Référence = '0461/2026'"
    with pytest.raises(ValueError):
        al.sql_modifier_recu("R-1", None, None, 10000, None)                       # jamais une seule part écrite seule


def test_le_superviseur_change_une_part_la_contrepartie_est_deduite_et_ecrite_ensemble(banc):
    c, b = banc
    s = session_superviseur(c, b)
    h = entetes(b, s)
    d = c.post("/api/android/caisse/recu", json={"reference": "0461/2026"}, headers=h).json()
    assert d["recu"]["ppc"] == 80 and d["recu"]["part_assure"] == 8000 and d["recu"]["part_assureur"] == 32000 and d["infos"]["montant_total"] == 40000
    r = c.post("/api/android/caisse/recu/modifier", json={"reference": "0461/2026", "part_assureur": 25000}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["recu"]["part_assure"] == 15000 and r.json()["recu"]["part_assureur"] == 25000                     # 40 000 − 25 000 = 15 000
    maj = [sql for sql, _ in b["envoyees"] if sql.startswith("UPDATE")][-1]
    assert maj == "UPDATE VenteClinique SET [PArtAssuré] = 15000.00, [PArtAssureur] = 25000.00 WHERE Référence = '0461/2026'"      # les DEUX parts, jamais le total
    journal = run(b["db"].settings.find_one({"_id": "android_journal"}))
    assert "assuré 8000→15000 assureur 32000→25000 (total 40000)" in [l for l in journal["lignes"] if l["action"] == "modifier_recu"][-1]["detail"]
    # part assuré donnée : l'assureur prend le reste ; refus si incohérent, hors bornes ou inchangé
    assert c.post("/api/android/caisse/recu/modifier", json={"reference": "0461/2026", "part_assure": 4000}, headers=h).json()["recu"]["part_assureur"] == 36000
    assert c.post("/api/android/caisse/recu/modifier", json={"reference": "0461/2026", "part_assure": 1000, "part_assureur": 1000}, headers=h).status_code == 422
    assert c.post("/api/android/caisse/recu/modifier", json={"reference": "0461/2026", "part_assure": 50000}, headers=h).status_code == 422
    assert c.post("/api/android/caisse/recu/modifier", json={"reference": "0461/2026", "part_assure": 4000}, headers=h).status_code == 422       # déjà enregistré
    # parts et « Réglé » ensemble dans UNE seule écriture
    r = c.post("/api/android/caisse/recu/modifier", json={"reference": "0461/2026", "regle": True, "part_assureur": 30000}, headers=h)
    assert r.status_code == 200 and r.json()["infos"]["regle"] is True and r.json()["recu"]["part_assure"] == 10000
    assert [sql for sql, _ in b["envoyees"] if sql.startswith("UPDATE")][-1] == "UPDATE VenteClinique SET [Réglé] = 1, [PArtAssuré] = 10000.00, [PArtAssureur] = 30000.00 WHERE Référence = '0461/2026'"


def test_un_caissier_ne_peut_pas_changer_les_parts(banc):
    c, b = banc
    s = se_connecter(c, b).json()["session"]
    assert c.post("/api/android/caisse/recu/modifier", json={"reference": "0461/2026", "part_assureur": 1000}, headers=entetes(b, s)).status_code == 403
    assert not any(sql.startswith("UPDATE") for sql, _ in b["envoyees"])


# ------------------------------------------------------------------------------------------------------------------ lot 494 : date de vente (jamais après la date système)
def test_date_de_vente_valide():
    from datetime import date
    auj = date(2026, 11, 27)
    assert al.date_vente_valide("2026-11-27", auj) == auj and al.date_vente_valide("2026-01-05", auj) == date(2026, 1, 5)
    for mauvais in ("2026-11-28", "2027-01-01", "27/11/2026", "2026-13-01", "", "2026-02-30"):
        with pytest.raises(ValueError):
            al.date_vente_valide(mauvais, auj)
    from datetime import datetime
    sql = al.sql_modifier_recu("0461/2026", None, None, None, None, datetime(2026, 11, 20, 11, 0, 0))
    assert sql == "UPDATE VenteClinique SET [Date Vente] = '20261120110000000' WHERE Référence = '0461/2026'"            # même format que la lecture, heure gardée


def test_le_superviseur_change_la_date_de_vente_heure_gardee_jamais_dans_le_futur(banc):
    from datetime import datetime, timedelta, timezone
    c, b = banc
    s = session_superviseur(c, b)
    h = entetes(b, s)
    r = c.post("/api/android/caisse/recu/modifier", json={"reference": "0461/2026", "date_vente": "2026-11-20"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["recu"]["date_vente"] == "2026-11-20" and r.json()["recu"]["heure"] == "11:00"                      # l'heure d'origine est conservée
    assert [sql for sql, _ in b["envoyees"] if sql.startswith("UPDATE")][-1] == "UPDATE VenteClinique SET [Date Vente] = '20261120110000000' WHERE Référence = '0461/2026'"
    journal = run(b["db"].settings.find_one({"_id": "android_journal"}))
    assert "date 2026-11-26→2026-11-20" in [l for l in journal["lignes"] if l["action"] == "modifier_recu"][-1]["detail"]
    demain = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    aujourdhui = datetime.now(timezone.utc).date().isoformat()
    n = len([1 for sql, _ in b["envoyees"] if sql.startswith("UPDATE")])
    rf = c.post("/api/android/caisse/recu/modifier", json={"reference": "0461/2026", "date_vente": demain}, headers=h)
    assert rf.status_code == 422 and "dépasser la date du jour" in rf.json()["detail"]                                   # jamais après la date système
    assert c.post("/api/android/caisse/recu/modifier", json={"reference": "0461/2026", "date_vente": "20/11/2026"}, headers=h).status_code == 422
    assert c.post("/api/android/caisse/recu/modifier", json={"reference": "0461/2026", "date_vente": "2026-11-20"}, headers=h).status_code == 422   # déjà cette date
    assert len([1 for sql, _ in b["envoyees"] if sql.startswith("UPDATE")]) == n                                         # aucune écriture pour les refus
    assert c.post("/api/android/caisse/recu/modifier", json={"reference": "0461/2026", "date_vente": aujourdhui, "regle": True}, headers=h).status_code == 200   # aujourd'hui : permis, avec « Réglé » dans la même écriture
    assert [sql for sql, _ in b["envoyees"] if sql.startswith("UPDATE")][-1].startswith("UPDATE VenteClinique SET [Réglé] = 1, [Date Vente] = '")


def test_un_caissier_ne_peut_pas_changer_la_date(banc):
    c, b = banc
    s = se_connecter(c, b).json()["session"]
    assert c.post("/api/android/caisse/recu/modifier", json={"reference": "R-0003", "date_vente": "2026-11-01"}, headers=entetes(b, s)).status_code == 403
    assert not any(sql.startswith("UPDATE") for sql, _ in b["envoyees"])
