"""Lot 460 — soumission du modèle Meta des envois en masse depuis SAWALI et suivi du statut. Aucun accès réseau : l'appel à Meta est remplacé par un faux."""
import asyncio
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot460")

import mongomock_motor
import pytest

import consignes_masse as cm


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class MetaFaux:
    """Faux serveur Meta : garde les modèles « soumis » et répond comme l'API Graph (liste filtrée par nom, création = PENDING)."""
    def __init__(self, existants=None, refuse=None):
        self.modeles = list(existants or [])
        self.appels = []
        self.refuse = refuse

    async def __call__(self, methode, url, jeton, json=None, params=None):
        self.appels.append((methode, url, json, params))
        assert jeton == "jeton-secret"
        if methode == "GET":
            return 200, {"data": [m for m in self.modeles if m["name"] == (params or {}).get("name")]}
        if self.refuse:
            return 400, {"error": {"message": "Invalid parameter", "error_user_msg": self.refuse}}
        self.modeles.append({"id": "tpl1", "name": json["name"], "language": json["language"], "category": json["category"], "status": "PENDING"})
        return 200, {"id": "tpl1", "status": "PENDING", "category": "UTILITY"}


@pytest.fixture()
def db():
    d = mongomock_motor.AsyncMongoMockClient()["test_lot460"]
    run(d["settings"].insert_one({"_id": "global", "wa_access_token": "jeton-secret", "wa_business_account_id": "123456"}))
    return d


def test_contenu_exact_envoye_a_meta():
    c = cm.contenu_modele_meta()
    corps, boutons = c["components"]
    assert c["name"] == "information_rdv" and c["category"] == "UTILITY" and c["language"] == "fr"
    assert corps["text"] == cm.MODELE_CORPS and corps["example"]["body_text"] == [["Awa", "Votre rendez-vous de demain est décalé d'une heure."]]
    assert corps["text"].count("{{") == len(corps["example"]["body_text"][0]) == 2                  # un exemple par variable : sinon Meta refuse
    assert boutons["buttons"] == [{"type": "QUICK_REPLY", "text": "Bien reçu"}]


def test_soumission_envoie_une_fois_et_garde_le_statut(db):
    meta = MetaFaux()
    r = run(cm.soumettre_modele(db, appeler=meta))
    assert r["statut"] == "PENDING" and r["libelle"].startswith("En attente") and r["deja"] is False and r["id"] == "tpl1" and r["envoye_le"]
    posts = [a for a in meta.appels if a[0] == "POST"]
    assert len(posts) == 1 and posts[0][1].endswith("/123456/message_templates") and posts[0][2] == cm.contenu_modele_meta()
    assert run(cm.lire_soumission(db))["statut"] == "PENDING"                                        # relu sans appeler Meta
    r2 = run(cm.soumettre_modele(db, appeler=meta))                                                    # un 2e clic ne renvoie rien
    assert r2["deja"] is True and len([a for a in meta.appels if a[0] == "POST"]) == 1


def test_modele_deja_connu_de_meta_est_releve_pas_renvoye(db):
    meta = MetaFaux([{"id": "t9", "name": "information_rdv", "language": "fr", "category": "UTILITY", "status": "APPROVED"}])
    r = run(cm.soumettre_modele(db, appeler=meta))
    assert r["deja"] is True and r["statut"] == "APPROVED" and not [a for a in meta.appels if a[0] == "POST"]


def test_suivi_approuve_refuse_et_categorie_modifiee(db):
    meta = MetaFaux()
    run(cm.soumettre_modele(db, appeler=meta))
    meta.modeles[0]["status"] = "APPROVED"
    v = run(cm.statut_modele(db, appeler=meta))
    assert v["statut"] == "APPROVED" and v["alerte"] == "" and v["verifie_le"] and v["envoye_le"]       # la date d'envoi est conservée
    assert v["active"] is False                                                                         # approuvé, mais pas encore ACTIVÉ : l'administrateur doit enregistrer le nom
    run(cm.regler_modele(db, "information_rdv", "fr"))
    assert run(cm.lire_soumission(db))["active"] is True
    meta.modeles[0].update(status="REJECTED", rejected_reason="INCORRECT_CATEGORY", category="MARKETING")
    v = run(cm.statut_modele(db, appeler=meta))
    assert v["statut"] == "REJECTED" and v["raison"] == "INCORRECT_CATEGORY" and "MARKETING" in v["alerte"]


def test_statut_d_un_modele_jamais_soumis(db):
    v = run(cm.statut_modele(db, appeler=MetaFaux()))
    assert v["statut"] == "ABSENT" and v["libelle"] == "Non soumis à Meta"


def test_refus_de_meta_et_reglages_manquants_et_nom_invalide(db):
    with pytest.raises(ValueError, match="Meta a répondu 400.*ne respecte pas les règles"):                # le motif donné par Meta est montré tel quel
        run(cm.soumettre_modele(db, appeler=MetaFaux(refuse="Le texte ne respecte pas les règles")))
    with pytest.raises(ValueError, match="minuscules"):
        run(cm.soumettre_modele(db, "Nom Invalide", appeler=MetaFaux()))
    vide = mongomock_motor.AsyncMongoMockClient()["test_lot460_vide"]
    with pytest.raises(ValueError, match="pas configuré"):
        run(cm.soumettre_modele(vide, appeler=MetaFaux()))
