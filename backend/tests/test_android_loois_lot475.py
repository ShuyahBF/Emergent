"""Lot 475 — API « Loois mobile » : requêtes préparées, connexion (mot de passe jamais gardé ni renvoyé), droits (caissier / administrateur / laboratoire), Historique de Caisse,
détail d'un reçu, Corrections de reçus, journal d'audit. Aucun accès réseau : la file « SQL à distance » est remplacée par une file simulée (Mongo simulé)."""
import asyncio
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
LIGNES = {"R-0003": [["P1", "M1", "PEDIATRIE", "1", "10000"], ["P2", "M1", "CONSULT", "2", "2500"]], "R-0002": [["P3", "M2", "CONSULT", "1", "8500,5"]], "R-0001": [["P2", "", "CONSULT", "1", "2000"]]}


@pytest.fixture()
def banc():
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    import routes.android_loois as ra
    import routes.loois_sql_distant as lsd
    ra._cache.clear()
    al._essais.clear()
    db = mongomock_motor.AsyncMongoMockClient()["test_lot475"]
    envoyees: list = []                                        # (sql, auteur)
    etat = {"en_ligne": True, "mdp_ok": True, "groupe": "", "autoriser": "1", "suppr": "0", "silence": False}

    def repondre(sql: str):
        S = sql
        if S.startswith("SELECT [Login], [AutoriserCorrectionReçu] FROM [UtilisateurBlg]"):
            return [["tassembh", etat["autoriser"]]] if etat["mdp_ok"] else []
        if S.startswith("SELECT [GroupeLogin]"):
            return [[etat["groupe"]]]
        if S.startswith("SELECT [PeutSupprimerRecu]"):
            return [[etat["suppr"]]]
        if "FROM VenteClinique WHERE Référence LIKE" in S:
            rows = RECUS
            if "Machine = 'TASSEMBH'" in S:
                rows = [r for r in RECUS if r[5] == "TASSEMBH"]
            return rows
        if "FROM VenteClinique WHERE Référence = " in S:
            ref = S.split("Référence = '")[1].split("'")[0]
            return [r for r in RECUS if r[0] == ref]
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
    app.include_router(api)
    from fastapi.testclient import TestClient
    c = TestClient(app)
    fiche, jeton = aa.nouvelle_fiche("ANDROID-ID-123456", "Tab", "1.0", "41.1.1.1")
    fiche.update(etat="autorise", zone="docx=CMC", base="myAurora-CMC", client_code="CMC", nom_utilisateur="Awa")
    run(aa.creer(db, fiche))
    return c, {"jeton": jeton, "fiche": fiche, "db": db, "etat": etat, "envoyees": envoyees, "admin": admin}


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
