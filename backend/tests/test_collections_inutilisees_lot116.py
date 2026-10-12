"""Lot 116 — collections les moins utilisées de la base de SAWALI : mesure, sauvegarde R2, désactivation,
suppression, registre, restauration, garde-fou du démarrage. MongoDB et R2 simulés.
Lancer : cd backend && python -m pytest tests/test_collections_inutilisees_lot116.py -q
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
pytest.importorskip("cryptography")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot116")

from bson import ObjectId  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import garde_collections_archivees as garde  # noqa: E402
import routes.collections_inutilisees as ci  # noqa: E402
import routes.migration_programmation as mp  # noqa: E402
import routes.migration_render as mr  # noqa: E402

ADMIN = {"email": "admin@test", "role": "admin"}
MAINTENANT = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
BUCKET = "sawali-migration"


def lancer(coro):
    """Exécute une coroutine dans une boucle neuve."""
    return asyncio.new_event_loop().run_until_complete(coro)


def oid(jours_avant: int) -> ObjectId:
    """ObjectId daté d'il y a N jours (la date de dernière activité se lit dans l'_id)."""
    return ObjectId.from_datetime(MAINTENANT - timedelta(days=jours_avant))


class FauxR2:
    """Bucket R2 en mémoire : dépôt, vérification, lecture."""

    def __init__(self):
        self.objets = {}
        self.en_panne = False

    def upload_fileobj(self, fichier, bucket, cle, ExtraArgs=None):  # noqa: N803 (signature boto3)
        if self.en_panne:
            raise RuntimeError("R2 indisponible")
        self.objets[cle] = fichier.read()

    def head_object(self, Bucket, Key):  # noqa: N803
        return {"ContentLength": len(self.objets[Key])}

    def get_object(self, Bucket, Key):  # noqa: N803
        return {"Body": io.BytesIO(self.objets[Key])}


@pytest.fixture()
def env(monkeypatch):
    """Base SAWALI simulée : collections vides, inactives, actives, vitales, sans fonction."""
    client = mongomock_motor.AsyncMongoMockClient()
    db = client["sawali"]
    monkeypatch.setattr(mr, "db", db)
    r2 = FauxR2()

    async def ids():
        return {"r2_account_id": "a", "r2_access_key_id": "b", "r2_secret_access_key": "c", "r2_bucket": BUCKET}
    monkeypatch.setattr(mp, "charger_identifiants", ids)
    monkeypatch.setattr(mp, "_client_r2", lambda _ids: r2)

    async def faux_rapport(sujet, texte, cfg, important, maintenant=None):
        return {"envoye": True}
    monkeypatch.setattr(mp, "envoyer_rapport", faux_rapport)

    async def remplir():
        await db.settings.insert_one({"_id": "global", "bird_enabled": True, "vidal_enabled": True})
        # Vide (fonction connue avec interrupteur) → cochée par défaut
        await db.create_collection("bird_sms_messages")
        # Vide, fonction connue sans interrupteur → cochée
        await db.create_collection("carrousel_clics")
        # Inactive (200 jours), fonction connue → proposée, non cochée
        await db.story_posts.insert_many([{"_id": oid(300), "t": 1}, {"_id": oid(200), "t": 2}])
        await db.story_posts.create_index("t", name="t_1")
        # Active (5 jours), fonction VIDAL
        await db.vidal_patients.insert_one({"_id": oid(5), "nom": "x"})
        # Vide, fonction VIDAL : VIDAL ne doit PAS être coupé (vidal_patients est active)
        await db.create_collection("vidal_sync_log")
        # Vitales
        await db.users.insert_one({"_id": oid(400), "email": "a@b"})
        await db.whatsapp_messages.insert_one({"_id": oid(400)})
        await db.migration_jobs.insert_one({"_id": oid(400)})
        await db.create_collection("payments")
        # Non vide, sans fonction connue → protégée
        await db.zzz_inconnue.insert_one({"_id": oid(500)})
        # Vide sans fonction connue → proposée (rien à désactiver)
        await db.create_collection("vieux_test")
        # _id non ObjectId : la date se lit dans les champs usuels
        await db.formations.insert_one({"_id": "f1", "created_at": (MAINTENANT - timedelta(days=120)).isoformat()})
    lancer(remplir())
    garde.definir_base("sawali")
    yield db, client, r2
    garde.definir_base(os.environ.get("DB_NAME"))


def _par_nom(analyse):
    return {l["nom"]: l for l in analyse["collections"]}


def test_classement_et_protections(env):
    """vide / inactive / active ; protections ; seules les vides non protégées sont cochées."""
    db, client, _ = env
    a = lancer(ci.analyser(db, client, "sawali", 90, MAINTENANT))
    l = _par_nom(a)
    assert l["bird_sms_messages"]["etat"] == "vide" and l["bird_sms_messages"]["coche"]
    assert l["bird_sms_messages"]["cle_fonction"] == "bird_enabled"
    assert l["carrousel_clics"]["coche"] and l["carrousel_clics"]["fonction"] == "Carrousels WhatsApp"
    assert l["story_posts"]["etat"] == "inactive" and not l["story_posts"]["coche"] and not l["story_posts"]["protegee"]
    assert l["story_posts"]["derniere_activite"].startswith((MAINTENANT - timedelta(days=200)).date().isoformat())
    assert l["vidal_patients"]["etat"] == "active" and not l["vidal_patients"]["coche"]
    assert l["formations"]["etat"] == "inactive"                      # date lue dans created_at
    for nom in ("users", "whatsapp_messages", "migration_jobs", "payments", "settings"):
        assert l[nom]["protegee"] and l[nom]["raison"].startswith("vitale"), nom
        assert not l[nom]["coche"]
    assert l["payments"]["etat"] == "vide" and not l["payments"]["coche"]          # vide mais vitale
    assert l["zzz_inconnue"]["protegee"] and "fonction inconnue" in l["zzz_inconnue"]["raison"]
    assert l["vieux_test"]["coche"] and l["vieux_test"]["fonction"] == "Fonction inconnue"
    # Plan de désactivation : Bird coupé ; VIDAL gardé (vidal_patients est active)
    assert l["bird_sms_messages"]["action_fonction"]["desactiver"] is True
    assert l["vidal_sync_log"]["action_fonction"]["desactiver"] is False
    assert "vidal_patients" in l["vidal_sync_log"]["action_fonction"]["texte"]
    # Tri : vides d'abord ; synthèse
    assert a["collections"][0]["documents"] == 0
    s = a["synthese"]
    assert s["total"] == len(a["collections"])
    assert s["liberables_par_defaut"] == 4                    # bird, carrousel, vidal_sync_log, vieux_test
    assert a["jauge"]["total"] >= s["total"]


def test_correspondance_et_protection_calculee():
    assert ci.fonction_de("liluvine_agenda_alertes")["cle_fonction"] == "liluvine_agenda_actif"   # le plus long gagne
    assert ci.fonction_de("liluvine_knowledge")["libelle"] == "Liluvine (assistante)"
    assert ci.raison_protection("system.views", 0, None) == "collection système MongoDB"
    assert ci.raison_protection("vidal_prescription_audit", 3, ci.fonction_de("vidal_prescription_audit"))
    assert ci.raison_protection("liluvine_desinscriptions", 0, None)
    assert ci.raison_protection("carrousel_clics", 5, ci.fonction_de("carrousel_clics")) is None


def test_refus_sans_confirmation_et_protegee(env):
    db, client, r2 = env
    with pytest.raises(HTTPException) as e:
        lancer(ci.liberer(db, client, "sawali", ci.LibererIn(collections=["vieux_test"], confirmation="oui"), ADMIN))
    assert e.value.status_code == 400
    # Une seule protégée dans la sélection → rien n'est fait
    with pytest.raises(HTTPException) as e:
        lancer(ci.liberer(db, client, "sawali", ci.LibererIn(collections=["vieux_test", "users"],
                                                               confirmation="LIBERER"), ADMIN))
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        lancer(ci.liberer(db, client, "sawali", ci.LibererIn(collections=["vieux_test", "absente"],
                                                               confirmation="LIBERER"), ADMIN))
    assert e.value.status_code == 404
    assert "vieux_test" in lancer(db.list_collection_names()) and not r2.objets


def test_sauvegarde_suppression_registre_puis_restauration(env):
    db, client, r2 = env
    r = lancer(ci.liberer(db, client, "sawali", ci.LibererIn(
        collections=["story_posts", "bird_sms_messages", "vidal_sync_log"], confirmation="  libérer "), ADMIN,
        MAINTENANT))
    assert r["liberees"] == 3 and r["erreurs"] == 0
    noms = lancer(db.list_collection_names())
    assert not {"story_posts", "bird_sms_messages", "vidal_sync_log"} & set(noms)
    cle = "collections-archivees/20261012-120000/story_posts.json.gz"
    assert cle in r2.objets and "collections-archivees/20261012-120000/bird_sms_messages.json.gz" in r2.objets
    archive = ci.lire_archive(r2.objets[cle])
    assert len(archive["documents"]) == 2 and archive["documents"][0]["_id"] == oid(300)
    assert [ix["nom"] for ix in archive["index"]] == ["t_1"]
    vide = ci.lire_archive(r2.objets["collections-archivees/20261012-120000/bird_sms_messages.json.gz"])
    assert vide["documents"] == []                                      # collection vide quand même archivée
    # Désactivation : Bird coupé, VIDAL gardé
    g = lancer(db.settings.find_one({"_id": "global"}))
    assert g["bird_enabled"] is False and g["vidal_enabled"] is True
    # Registre
    reg = {e["nom"]: e for e in lancer(ci.lister_registre(db))}
    assert reg["story_posts"]["documents"] == 2 and reg["story_posts"]["r2_cle"] == cle
    assert reg["bird_sms_messages"]["fonction_desactivee"] is True and reg["bird_sms_messages"]["valeur_avant"] is True
    assert reg["story_posts"]["par"] == "admin@test"
    # Restauration : documents + index + fonction réactivée + registre nettoyé
    rr = lancer(ci.restaurer(db, "story_posts", ADMIN))
    assert rr["documents"] == 2 and rr["index"] == 1
    assert lancer(db.story_posts.count_documents({})) == 2
    assert "t_1" in lancer(db.story_posts.index_information())
    rb = lancer(ci.restaurer(db, "bird_sms_messages", ADMIN))
    assert rb["fonction_reactivee"] is True
    assert lancer(db.settings.find_one({"_id": "global"}))["bird_enabled"] is True
    assert "bird_sms_messages" in lancer(db.list_collection_names())
    assert {e["nom"] for e in lancer(ci.lister_registre(db))} == {"vidal_sync_log"}
    # Restaurer une collection qui a déjà des documents → 409 ; hors registre → 404
    lancer(db.settings.update_one({"_id": ci.DOC_REGISTRE}, {"$set": {"story_posts": {"nom": "story_posts",
                                                                                      "r2_cle": cle}}}))
    with pytest.raises(HTTPException) as e:
        lancer(ci.restaurer(db, "story_posts", ADMIN))
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        lancer(ci.restaurer(db, "inconnue", ADMIN))
    assert e.value.status_code == 404


def test_pas_de_suppression_si_la_sauvegarde_echoue(env):
    db, client, r2 = env
    r2.en_panne = True
    r = lancer(ci.liberer(db, client, "sawali", ci.LibererIn(collections=["story_posts"], confirmation="LIBERER"),
                          ADMIN, MAINTENANT))
    assert r["liberees"] == 0 and r["erreurs"] == 1 and "sauvegarde impossible" in r["elements"][0]["erreur"]
    assert lancer(db.story_posts.count_documents({})) == 2
    assert lancer(ci.lister_registre(db)) == []


def test_sans_identifiants_r2_rien_n_est_fait(env, monkeypatch):
    db, client, _ = env

    async def aucun():
        raise RuntimeError("Aucun identifiant enregistré pour les sauvegardes programmées")
    monkeypatch.setattr(mp, "charger_identifiants", aucun)
    with pytest.raises(HTTPException) as e:
        lancer(ci.liberer(db, client, "sawali", ci.LibererIn(collections=["vieux_test"], confirmation="LIBERER"), ADMIN))
    assert e.value.status_code == 400 and "vieux_test" in lancer(db.list_collection_names())


def test_garde_fou_demarrage(env):
    """Collection archivée : create_index ne la recrée pas ; registre absent : rien n'est bloqué."""
    db, client, _ = env
    classe = type(db.story_posts)
    garde.installer([classe])
    try:
        # Registre absent : création d'index normale
        lancer(db.nouvelle.create_index("x"))
        assert "nouvelle" in lancer(db.list_collection_names())
        assert garde.collection_archivee("story_posts") is False
        # Archivage de story_posts puis « redémarrage » (cache vidé)
        lancer(ci.liberer(db, client, "sawali", ci.LibererIn(collections=["story_posts"], confirmation="LIBERER"),
                          ADMIN, MAINTENANT))
        garde.definir_base("sawali")                       # nouveau démarrage : le registre est relu
        lancer(db.story_posts.create_index("t"))
        lancer(db.story_posts.create_indexes([]))
        assert "story_posts" not in lancer(db.list_collection_names())
        assert garde.collection_archivee("story_posts") is True
        # Autre base : jamais concernée
        autre = client["albarka"]
        lancer(autre.story_posts.create_index("t"))
        assert "story_posts" in lancer(autre.list_collection_names())
        # Une écriture réelle recrée la collection (voulu) ; au démarrage suivant ses index sont créés
        lancer(db.story_posts.insert_one({"t": 9}))
        garde.definir_base("sawali")
        lancer(db.story_posts.create_index("t", name="t_9"))
        assert "t_9" in lancer(db.story_posts.index_information())
    finally:
        garde.desinstaller(classe)
