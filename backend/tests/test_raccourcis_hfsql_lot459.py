"""Lot 459 — raccourcis de commandes SQL distantes avec paramètres {nom} : détection dans l'ordre, valeurs demandées une à une par WhatsApp, valeurs sûres, limite. Aucun accès réseau."""
import asyncio
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot459")

import mongomock_motor
import pytest

import commande_hfsql_wa as chw
import raccourcis_hfsql as rh
from routes import loois_sql_distant as lsd

NUM = "22670112233"
MODELE = "UPDATE VenteClinique SET Mag = {vStatut} WHERE Référence = {RefNum}"


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class FileFausse:
    def __init__(self):
        self.deposees = []

    async def clients(self):
        return {"clients": [{"code": "CMC", "en_ligne": True, "machines": ["PC1"]}, {"code": "PHL", "en_ligne": True, "machines": ["PC2"]}]}

    async def creer(self, corps, ip, auteur=""):
        self.deposees.append(corps)
        return {"id": f"r{len(self.deposees)}"}

    async def detail(self, rid):
        return {"id": rid, "etat": "terminee", "ok": True, "message": "", "base": "myAurora-CMC", "machine": "PC1", "colonnes": [], "lignes": [], "tronque": False,
                "lignes_affectees": 1, "duree_ms": 9}


@pytest.fixture()
def db():
    d = mongomock_motor.AsyncMongoMockClient()["test_lot459"]
    run(chw.enregistrer_acces(d, [{"numero": "+226 70 11 22 33", "nom": "Directeur", "actif": True}]))
    return d


@pytest.fixture()
def file_(monkeypatch):
    f = FileFausse()
    monkeypatch.setitem(lsd.INTERNE, "clients", f.clients)
    monkeypatch.setitem(lsd.INTERNE, "creer", f.creer)
    monkeypatch.setitem(lsd.INTERNE, "detail", f.detail)
    return f


async def _noop(t):
    return None


def test_parametres_dans_l_ordre_sans_doublon():
    assert rh.parametres(MODELE) == ["vStatut", "RefNum"]
    assert rh.parametres("SELECT * FROM A WHERE X = {a} OR Y = {a} OR Z = {b}") == ["a", "b"]
    assert rh.parametres("SELECT 1 WHERE 1 = 1") == []


def test_valeurs_sures_contre_l_injection():
    r = rh.resoudre(MODELE, {"vStatut": "SUP", "RefNum": "R-2026367681"})
    assert r == "UPDATE VenteClinique SET Mag = 'SUP' WHERE Référence = 'R-2026367681'"
    assert rh.resoudre(MODELE, {"vStatut": "SUP", "RefNum": "367681"}).endswith("Référence = 367681")                  # un nombre reste un nombre
    piege = rh.resoudre(MODELE, {"vStatut": "x' WHERE 1=1; DROP TABLE A; --", "RefNum": "1"})
    assert piege.startswith("UPDATE VenteClinique SET Mag = 'x'' WHERE 1=1; DROP TABLE A; --'")                          # tout reste DANS le texte
    from routes.loois_sql_distant import verifier
    assert verifier(piege)[0]                                                                                              # une seule instruction : le contrôle Prudent l'accepte
    assert rh.resoudre("SELECT * FROM A WHERE Nom = '{n}'", {"n": "O'Brien"}).endswith("'O''Brien'")                  # déjà entre apostrophes
    for mauvais in ("", "a\nb", "a{b}", "x" * 300):
        with pytest.raises(ValueError):
            rh.resoudre(MODELE, {"vStatut": mauvais, "RefNum": "1"})
    with pytest.raises(ValueError):
        rh.resoudre(MODELE, {"vStatut": "SUP"})


def test_creation_controles_et_limite(db):
    f = run(rh.creer(db, "Statut d'un reçu", MODELE, "docx=CMC"))
    assert f["parametres"] == ["vStatut", "RefNum"] and f["nature"] == "MODIF"
    with pytest.raises(ValueError):
        run(rh.creer(db, "statut d'un RECU", MODELE, "docx=CMC"))                    # même nom (sans casse ni accents)
    with pytest.raises(ValueError):
        run(rh.creer(db, "Sans where", "DELETE FROM Patient", "docx=CMC"))            # Prudent : DELETE sans WHERE
    with pytest.raises(ValueError):
        run(rh.creer(db, "Mal écrit", "SELECT * FROM A WHERE X = {a b}", "docx=CMC"))
    for i in range(rh.MAX_RACCOURCIS - 1):
        run(rh.creer(db, f"Raccourci {i}", "SELECT * FROM A WHERE X = {a}", "docx=CMC"))
    with pytest.raises(ValueError):
        run(rh.creer(db, "De trop", "SELECT * FROM A WHERE X = {a}", "docx=CMC"))
    assert rh.MAX_RACCOURCIS >= 10


def test_trouver_par_numero_ou_nom(db):
    run(rh.creer(db, "Statut d'un reçu", MODELE, "docx=CMC"))
    run(rh.creer(db, "Lire un patient", "SELECT * FROM Patient WHERE Numero = {n}", "docx=CMC"))
    liste = run(rh.lister(db))
    assert rh.trouver(liste, "2")["nom"] == "Lire un patient" and rh.trouver(liste, "9") is None
    assert rh.trouver(liste, "statut d'un recu")["nom"] == "Statut d'un reçu" and rh.trouver(liste, "lire")["nom"] == "Lire un patient"


def test_whatsapp_menu_puis_valeurs_une_a_une_puis_execution(db, file_):
    run(rh.creer(db, "Statut d'un reçu", MODELE, "docx=CMC"))
    menu = run(chw.traiter(db, NUM, "hfsql", _noop))
    assert "1. Statut d'un reçu" in menu and "vStatut, RefNum" in menu
    q1 = run(chw.traiter(db, NUM, "hfsql 1", _noop))
    assert "vStatut" in q1 and "1/2" in q1 and file_.deposees == []
    q2 = run(chw.traiter(db, NUM, "SUP", _noop))
    assert "RefNum" in q2 and "2/2" in q2 and file_.deposees == []
    envoyes = []

    async def envoyer(t):
        envoyes.append(t)

    async def scenario():
        rep = await chw.traiter(db, NUM, "R-2026367681", envoyer)
        await asyncio.sleep(0.3)
        return rep

    rep = asyncio.new_event_loop().run_until_complete(scenario())
    assert "déposée" in rep
    assert file_.deposees[0]["sql"] == "UPDATE VenteClinique SET Mag = 'SUP' WHERE Référence = 'R-2026367681'" and file_.deposees[0]["client"] == "CMC"
    assert envoyes and "Commande : UPDATE VenteClinique" in envoyes[0] and "Base : myAurora-CMC" in envoyes[0]


def test_valeur_refusee_est_redemandee_et_annuler_arrete(db, file_):
    run(rh.creer(db, "Statut d'un reçu", MODELE, "docx=CMC"))
    run(chw.traiter(db, NUM, "hfsql statut", _noop))
    rep = run(chw.traiter(db, NUM, "ligne1\nligne2", _noop))
    assert "refusé" in rep and "vStatut" in rep and file_.deposees == []            # redemandée, rien exécuté
    assert "annulé" in run(chw.traiter(db, NUM, "annuler", _noop))
    assert run(chw.traiter(db, NUM, "SUP", _noop)) is None                            # plus de raccourci en cours : traitement habituel


def test_raccourci_avec_confirmation_et_autre_zone(db, file_):
    run(rh.creer(db, "Statut d'un reçu", MODELE, "docx=CMC", confirmer=True))
    run(chw.traiter(db, NUM, "hfsql 1 docx=PHL", _noop))
    run(chw.traiter(db, NUM, "SUP", _noop))
    rep = run(chw.traiter(db, NUM, "367681", _noop))
    assert "OUI" in rep and "docx=PHL" in rep and file_.deposees == []                # le propriétaire a demandé OUI pour ce raccourci
    rep = run(chw.traiter(db, NUM, "oui", _noop, surveiller=False))
    assert "déposée" in rep and file_.deposees[0]["client"] == "PHL"


def test_raccourci_inconnu_et_zone_limitee(db, file_):
    assert "Je ne trouve pas" in run(chw.traiter(db, NUM, "hfsql 7", _noop))
    run(chw.enregistrer_acces(db, [{"numero": NUM, "nom": "Limité", "zones": "PHL", "actif": True}]))
    run(rh.creer(db, "Lire", "SELECT * FROM A WHERE X = {a}", "docx=CMC"))
    run(chw.traiter(db, NUM, "hfsql 1", _noop))
    assert "pas autorisé pour la zone" in run(chw.traiter(db, NUM, "5", _noop))
