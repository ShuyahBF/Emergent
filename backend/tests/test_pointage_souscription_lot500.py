# Lot 500 — souscription au pointage (semaine, mois, année, illimité), vérifiée par le SMS de paiement ou par l'administrateur.
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("JWT_SECRET", "secret-de-test")

import pytest  # noqa: E402
from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

import pointage_telephone as pt  # noqa: E402
from routes.pointage_telephone import setup_pointage_telephone_routes  # noqa: E402

T0 = datetime(2026, 11, 28, 10, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------- logique pure
def _v(debut, jours):
    return {"statut": "verifiee", "debut": debut.isoformat(), "fin": (debut + timedelta(days=jours)).isoformat() if jours else None}


def test_etat_et_periodes_enchainees():
    assert pt.etat_souscription([], quand=T0)["valide"] is False
    sem = _v(T0 - timedelta(days=2), 7)
    e = pt.etat_souscription([sem], quand=T0)
    assert e["valide"] and e["fin"] == (T0 + timedelta(days=5)).isoformat()
    # Renouveler tôt : la nouvelle période commence à la FIN de l'actuelle (aucun jour perdu)
    debut, fin = pt.periode_suivante([sem], "mois", quand=T0)
    assert debut == (T0 + timedelta(days=5)).isoformat() and fin == (T0 + timedelta(days=35)).isoformat()
    deux = [sem, {"statut": "verifiee", "debut": debut, "fin": fin}]
    assert pt.etat_souscription(deux, quand=T0)["fin"] == fin
    assert pt.etat_souscription([_v(T0 - timedelta(days=400), None)], quand=T0) == {"valide": True, "illimite": True, "fin": None, "en_attente": 0}
    # Une demande en attente ou refusée n'ouvre rien
    assert pt.etat_souscription([{"statut": "en_attente"}, {"statut": "refusee", "debut": T0.isoformat()}], quand=T0)["valide"] is False


def test_couvert():
    sem = _v(T0 - timedelta(days=10), 7)
    assert pt.couvert([sem], T0 - timedelta(days=5)) and not pt.couvert([sem], T0) and not pt.couvert([sem], None)


def test_tarifs():
    t = pt.valider_tarifs({"tarifs": {"semaine": "2500", "mois": 7500, "annee": ""}, "codes": {"orange": "12 34 56"}, "devise": "FCFA"})
    assert t == {"tarifs": {"semaine": 2500, "mois": 7500}, "codes": {"orange": "123456"}, "devise": "FCFA"}
    with pytest.raises(ValueError):
        pt.valider_tarifs({"tarifs": {"mois": -1}})
    with pytest.raises(ValueError):
        pt.valider_tarifs({"codes": {"moov": "12A"}})
    assert pt.sequence_ussd("orange", "123456", 2500) == "*144*10*123456*2500#"      # catalogue unique des officines (source auRor)


def test_rapprochement_sms():
    ms = lambda jours: int((T0 - timedelta(days=jours)).timestamp() * 1000)
    tx = [{"k": "a", "genre": "RECETTE", "reference": "PP2511.28.A1", "montant": 2500, "ms": ms(1)},
          {"k": "b", "genre": "DEPENSE", "reference": "XX99", "montant": 9000, "ms": ms(1)},
          {"k": "c", "genre": "RECETTE", "reference": "OLD123", "montant": 9000, "ms": ms(30)}]
    assert pt.rapprocher("pp 251128 a1", 2500, tx, set(), quand=T0)["k"] == "a"
    assert pt.rapprocher("PP251128A1", 3000, tx, set(), quand=T0) is None          # montant insuffisant
    assert pt.rapprocher("PP251128A1", 2500, tx, {"a"}, quand=T0) is None          # SMS déjà utilisé
    assert pt.rapprocher("XX99", 100, tx, set(), quand=T0) is None                 # dépense, pas une recette
    assert pt.rapprocher("OLD123", 100, tx, set(), quand=T0) is None               # trop ancien


# ---------------------------------------------------------------------------- routes
UTILISATEUR = {"role": "admin", "email": "admin@test"}


@pytest.fixture
def ctx():
    db = AsyncMongoMockClient()["test"]
    app, api = FastAPI(), APIRouter(prefix="/api")

    async def utilisateur():
        return UTILISATEUR
    setup_pointage_telephone_routes(db=db, api=api, get_current_user=utilisateur)
    app.include_router(api)
    with TestClient(app) as c:
        yield c, db


def _commerce(c):
    com = c.post("/api/admin/pointage-structures", json={"nom": "Boutique Awa", "type": "Boutique"}).json()
    cx = c.post("/api/pointage-espace/connexion", json={"cle": com["acces"]["cle"], "mot_de_passe": com["mot_de_passe"]}).json()
    return com, {"X-Pointage-Jeton": cx["jeton"]}


def test_sans_souscription_tout_est_ferme(ctx):
    c, _ = ctx
    com, h = _commerce(c)
    assert c.post("/api/pointage-espace/inventaires", headers=h, json={"contenu": "Article\nSavon\n"}).status_code == 402
    # Inventaire créé par l'administrateur : le téléphone ne peut pas le télécharger tant que la souscription n'est pas vérifiée
    inv = c.post("/api/admin/pointage-inventaires", json={"structure": {"source": "commerce", "id": com["id"]}, "contenu": "Article\nSavon\n"}).json()
    jeton = c.get(f"/api/admin/pointage-inventaires/{inv['id']}").json()["jeton"]
    assert c.get(f"/api/public/pointage/{jeton}").json()["souscription"]["valide"] is False
    r = c.post(f"/api/public/pointage/{jeton}/acces", json={"mot_de_passe": com["mot_de_passe"]})
    assert r.status_code == 402 and "Souscription" in r.json()["detail"]


def test_paiement_mobile_verifie_par_sms(ctx):
    c, db = ctx
    c.put("/api/admin/pointage-tarifs", json={"tarifs": {"semaine": 2500, "mois": 7500}, "codes": {"orange": "123456"}, "devise": "FCFA"})
    com, h = _commerce(c)
    s = c.get("/api/pointage-espace/souscription", headers=h).json()
    assert s["etat"]["valide"] is False
    orange = s["operateurs"][0]
    assert orange["formules"]["semaine"]["sequence"] == "*144*10*123456*2500#" and orange["formules"]["semaine"]["lien"].startswith("tel:")
    # SMS de paiement reçu par le téléphone de SAWALI (module Transactions SMS)
    ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    mois = datetime.now(timezone.utc).strftime("%Y-%m")
    c.portal.call(db.settings.insert_one, {"_id": f"transactions-sms:{mois}", "items": [
        {"k": "sms1", "genre": "RECETTE", "reference": "PP2511.28.A1", "montant": 2500, "ms": ms}]})
    r = c.post("/api/pointage-espace/souscription", headers=h, json={"formule": "semaine", "operateur": "orange", "reference": "pp251128a1"}).json()
    assert r["souscription"]["statut"] == "verifiee" and r["etat"]["valide"] is True
    # Le même SMS ne sert pas deux fois
    r2 = c.post("/api/pointage-espace/souscription", headers=h, json={"formule": "semaine", "operateur": "orange", "reference": "PP251128A1"}).json()
    assert r2["souscription"]["statut"] == "en_attente"
    # L'Espace peut maintenant créer un inventaire
    assert c.post("/api/pointage-espace/inventaires", headers=h, json={"contenu": "Article\nSavon\n"}).status_code == 200


def test_validation_par_l_administrateur(ctx):
    c, _ = ctx
    c.put("/api/admin/pointage-tarifs", json={"tarifs": {"mois": 7500}, "codes": {"moov": "998877"}})
    com, h = _commerce(c)
    assert c.post("/api/pointage-espace/souscription", headers=h, json={"formule": "annee", "operateur": "moov", "reference": "REF1234"}).status_code == 400
    d = c.post("/api/pointage-espace/souscription", headers=h, json={"formule": "mois", "operateur": "moov", "reference": "MP251128.1234"}).json()
    assert d["souscription"]["statut"] == "en_attente" and d["etat"]["en_attente"] == 1
    liste = c.get("/api/admin/pointage-souscriptions").json()["souscriptions"]
    assert liste[0]["statut"] == "en_attente" and liste[0]["commerce"] == "Boutique Awa"
    v = c.post(f"/api/admin/pointage-souscriptions/{liste[0]['id']}/valider").json()
    assert v["statut"] == "verifiee" and v["fin"]
    assert c.post(f"/api/admin/pointage-souscriptions/{liste[0]['id']}/refuser").status_code == 409
    acces = c.get("/api/admin/pointage-acces").json()["acces"][0]
    assert acces["souscription"]["valide"] is True


def test_expiration_finir_l_envoi_seulement(ctx):
    c, db = ctx
    com, _ = _commerce(c)
    # Souscription d'une semaine terminée hier
    c.portal.call(db[pt.COL_SOUSCRIPTIONS].insert_one, {"id": "s-ancienne", "acces_id": com["acces"]["id"], "formule": "semaine", "statut": "verifiee",
                                                        "debut": (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(),
                                                        "fin": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), "demandee_le": "x"})
    inv = c.post("/api/admin/pointage-inventaires", json={"structure": {"source": "commerce", "id": com["id"]}, "contenu": "Article\nSavon\nRiz\n"}).json()
    jeton = c.get(f"/api/admin/pointage-inventaires/{inv['id']}").json()["jeton"]
    # Le téléphone avait téléchargé l'inventaire pendant la souscription : on simule son jeton
    sous = pt.etat_souscription([])
    assert sous["valide"] is False
    acces = c.portal.call(db[pt.COL_ACCES].find_one, {"id": com["acces"]["id"]})
    doc = c.portal.call(db[pt.COL_INVENTAIRES].find_one, {"id": inv["id"]})
    h = {"X-Pointage-Telephone": pt.jeton_telephone(os.environ["JWT_SECRET"], doc, acces)}
    pendant = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    apres = datetime.now(timezone.utc).isoformat()
    r = c.post(f"/api/public/pointage/{jeton}/saisies", headers=h, json={"prenom": "Awa", "appareil": "appareil-0001", "saisies": [
        {"uid": "saisie-pendant", "chrono": 1, "qte": 4, "lieu": "L1", "le": pendant},
        {"uid": "saisie-apres1", "chrono": 2, "qte": 9, "lieu": "L1", "le": apres},
        {"uid": "saisie-sansheure", "chrono": 2, "qte": 9, "lieu": "L1"}]}).json()
    assert r["acceptees"] == ["saisie-pendant"]
    assert {x["uid"] for x in r["refusees"]} == {"saisie-apres1", "saisie-sansheure"}
