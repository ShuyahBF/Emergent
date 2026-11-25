"""Lot 458 — Commande HFSQL distante via Liluvine : numéro autorisé, contrôles « Prudent », OUI pour modifier, résultat renvoyé. Aucun accès réseau."""
import asyncio
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot458")
from datetime import datetime, timedelta

import mongomock_motor
import pytest

import commande_hfsql_wa as chw
from routes import loois_sql_distant as lsd

NUM = "22670112233"


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class FileFausse:
    """Remplace la file des requêtes SQL distantes (aucun serveur)."""
    def __init__(self, en_ligne=True, etat="terminee"):
        self.deposees, self.en_ligne, self.etat = [], en_ligne, etat

    async def clients(self):
        return {"clients": [{"code": "CMC", "en_ligne": self.en_ligne, "machines": ["PC1"]}]}

    async def creer(self, corps, ip, auteur=""):
        self.deposees.append(corps)
        return {"id": "r1"}

    async def detail(self, rid):
        return {"id": rid, "etat": self.etat, "ok": True, "message": "", "base": "myAurora-CMC", "machine": "PC1", "colonnes": ["Reference", "Mag"],
                "lignes": [["R-2026367681", "SUP"]], "tronque": False, "lignes_affectees": 1, "duree_ms": 12}


@pytest.fixture()
def db():
    d = mongomock_motor.AsyncMongoMockClient()["test_lot458"]
    run(chw.enregistrer_acces(d, [{"numero": "+226 70 11 22 33", "nom": "Directeur", "actif": True}, {"numero": "22671000000", "nom": "Limité", "zones": "PHL", "actif": True}]))
    return d


@pytest.fixture()
def file_(monkeypatch):
    f = FileFausse()
    monkeypatch.setitem(lsd.INTERNE, "clients", f.clients)
    monkeypatch.setitem(lsd.INTERNE, "creer", f.creer)
    monkeypatch.setitem(lsd.INTERNE, "detail", f.detail)
    return f


async def _noop(texte):
    return None


def test_extraction_de_la_zone_et_de_la_requete():
    c = chw.extraire("hfsql docx=CMC SELECT * FROM VenteClinique WHERE Reference = 'R-1'")
    assert c["zone"] == "docx=CMC" and c["client"] == "CMC" and c["sql"].startswith("SELECT")
    assert chw.extraire("HFSQL cmc SELECT 1 WHERE 1=1")["client"] == "CMC"
    assert chw.extraire("bonjour Liluvine") is None and chw.extraire("hfsql docx=CMC") is None


def test_numero_non_autorise_ou_sans_mot_cle_ne_fait_rien(db, file_):
    assert run(chw.traiter(db, "22699999999", "hfsql docx=CMC SELECT 1 WHERE 1=1", _noop)) is None
    assert run(chw.traiter(db, NUM, "Bonjour, quelle heure ?", _noop)) is None
    assert file_.deposees == []


def test_select_est_depose_et_le_resultat_est_renvoye(db, file_):
    envoyes = []

    async def envoyer(t):
        envoyes.append(t)

    async def scenario():
        rep = await chw.traiter(db, NUM, "hfsql docx=CMC SELECT Reference, Mag FROM VenteClinique WHERE Reference = 'R-2026367681'", envoyer)
        await asyncio.sleep(0.3)
        return rep

    rep = asyncio.new_event_loop().run_until_complete(scenario())
    assert "déposée" in rep and len(file_.deposees) == 1
    assert envoyes and "Zone : docx=CMC" in envoyes[0] and "Base : myAurora-CMC" in envoyes[0] and "Commande : SELECT" in envoyes[0] and "R-2026367681 | SUP" in envoyes[0]


def test_modification_demande_oui_puis_depose(db, file_):
    sql = "UPDATE VenteClinique SET Mag = 'SUP' WHERE Reference = 'R-2026367681'"
    rep = run(chw.traiter(db, NUM, f"hfsql docx=CMC {sql}", _noop))
    assert "OUI" in rep and "MODIFICATION" in rep and file_.deposees == []          # rien n'est exécuté avant la confirmation
    rep = run(chw.traiter(db, NUM, "Oui", _noop, surveiller=False))
    assert "déposée" in rep and file_.deposees[0]["sql"] == sql and file_.deposees[0]["client"] == "CMC"
    assert run(chw.traiter(db, NUM, "oui", _noop)) is None                            # plus rien en attente


def test_non_annule_et_expiration(db, file_):
    sql = "DELETE FROM Patient WHERE Numero = 5"
    t0 = datetime(2026, 11, 25, 10, 0)
    run(chw.traiter(db, NUM, f"hfsql docx=CMC {sql}", _noop, instant=t0))
    assert "annulée" in run(chw.traiter(db, NUM, "non", _noop, instant=t0))
    run(chw.traiter(db, NUM, f"hfsql docx=CMC {sql}", _noop, instant=t0))
    assert run(chw.traiter(db, NUM, "oui", _noop, instant=t0 + timedelta(minutes=10))) is None
    assert file_.deposees == []


def test_controles_prudent_et_zone_et_hors_ligne(db, file_):
    assert "WHERE" in run(chw.traiter(db, NUM, "hfsql docx=CMC DELETE FROM Patient", _noop))          # DELETE sans WHERE refusé
    assert "refusée" in run(chw.traiter(db, NUM, "hfsql docx=CMC DROP TABLE Patient", _noop)).lower()
    assert "pas autorisé pour la zone" in run(chw.traiter(db, "22671000000", "hfsql docx=CMC SELECT 1 WHERE 1=1", _noop))
    file_.en_ligne = False
    run(chw.traiter(db, NUM, "hfsql docx=CMC UPDATE Patient SET Nom = 'X' WHERE Numero = 1", _noop))
    rep = run(chw.traiter(db, NUM, "oui", _noop, surveiller=False))
    assert "PAS déposée" in rep and file_.deposees == []
    assert any("hors ligne" in e["issue"] for e in run(chw.journal(db)))


def test_format_des_erreurs_et_resultats_vides():
    t = chw.formater_resultat("docx=CMC", "UPDATE X SET a=1 WHERE b=2", {"etat": "terminee", "ok": False, "message": "Erreur 70114 fichier non décrit", "base": "myAurora-CMC"})
    assert "Erreur du moteur HFSQL : Erreur 70114" in t and "Base : myAurora-CMC" in t
    t = chw.formater_resultat("docx=CMC", "UPDATE X SET a=1 WHERE b=2", {"etat": "terminee", "ok": True, "colonnes": [], "lignes": [], "lignes_affectees": 1, "base": "b", "duree_ms": 5})
    assert "1 ligne(s) modifiée(s)" in t
