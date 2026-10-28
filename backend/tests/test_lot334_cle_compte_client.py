"""Lot 334 — lier une clé client Loois à un compte client de SAWALI (sinon « non_lie » → états anonymisés)."""
import importlib
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot334")

import mongomock_motor

t = importlib.import_module("tests.test_lot68_1_cles_clients")
env = t.env   # fixture partagée


def _compte(db, **champs):
    """Insère un compte client principal dans la base simulée."""
    t.lancer(db.users.insert_one({"role": "client", **champs}))


def test_liste_propose_les_comptes_et_le_contrat_non_lie(env):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot334a"]
    _compte(db, id="c1", company="École des Métiers", email="e@x.bf", contract_billing_period="monthly", last_payment_at="2999-01-01")
    _compte(db, id="c2", full_name="Suivi", email="s@x.bf", parent_client_id="c1")      # utilisateur suivi : non proposé
    c = t.application(db)
    t.creer(c)
    r = c.get("/api/admin/loois-cles-clients").json()
    assert [x["id"] for x in r["comptes_clients"]] == ["c1"]
    # Aucun compte lié : l'anonymisation s'applique
    assert r["cles"][0]["contrat"]["statut"] == "non_lie" and r["cles"][0]["contrat"]["anonymiser"] is True


def test_lier_la_cle_au_compte_active_le_contrat(env):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot334b"]
    _compte(db, id="c1", company="École des Métiers", email="e@x.bf", contract_billing_period="annual", last_payment_at="2999-01-01")
    c = t.application(db)
    fiche = t.creer(c)["fiche"]
    # Le nom envoyé par la page est ignoré : c'est celui du compte qui est gardé
    r = c.put(f"/api/admin/loois-cles-clients/{fiche['id']}", json={"tenant_id": "c1", "client_nom": "n'importe quoi"})
    assert r.status_code == 200 and r.json()["fiche"]["client_nom"] == "École des Métiers"
    liste = c.get("/api/admin/loois-cles-clients").json()["cles"][0]
    assert liste["contrat"]["actif"] is True and liste["contrat"]["anonymiser"] is False


def test_compte_inconnu_refuse_et_delier_possible(env):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot334c"]
    c = t.application(db)
    fiche = t.creer(c)["fiche"]
    assert c.put(f"/api/admin/loois-cles-clients/{fiche['id']}", json={"tenant_id": "absent"}).status_code == 422
    assert c.put(f"/api/admin/loois-cles-clients/{fiche['id']}", json={"tenant_id": ""}).status_code == 200
