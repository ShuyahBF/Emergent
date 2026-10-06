"""Lot 63 — Barrière anti-rafale WhatsApp : seuil de messages sans réponse, réponse automatique
au seuil, messages retenus au-delà, levée par une réponse humaine (ou de Liluvine si réglé),
commandes « ! » et numéros exemptés jamais bloqués ; présence (utilisateurs connectés) des
plateformes. MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_lot63_barriere_wa.py -q
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.barriere_wa as bw  # noqa: E402
import routes.stats_plateformes as sp  # noqa: E402

REGLAGES = {"wa_barriere_active": True, "wa_barriere_seuil": 2}
TEL = "22670112233"


def lancer(coro):
    """Exécute une coroutine dans une boucle neuve."""
    return asyncio.new_event_loop().run_until_complete(coro)


def il_y_a(minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


@pytest.fixture()
def db():
    return mongomock_motor.AsyncMongoMockClient()["sawali_lot63"]


def recu(db, minutes, **extra):
    """Enregistre un message reçu du correspondant il y a `minutes` minutes."""
    lancer(db.whatsapp_messages.insert_one({"direction": "inbound", "phone_digits": TEL,
                                            "created_at": il_y_a(minutes), **extra}))


def test_seuil_avertissement_puis_retenue_puis_levee(db):
    # 1er message : normal ; 2e : avertissement ; 3e : retenu
    assert lancer(bw.decision(db, TEL, "text", "Bonjour", REGLAGES)) == "normal"
    recu(db, 10)
    assert lancer(bw.decision(db, TEL, "text", "Vous êtes là ?", REGLAGES)) == "avertir"
    recu(db, 9)
    # Lot 64.5 — tant que l'avertissement n'est pas parti, il est retenté au message suivant
    assert lancer(bw.decision(db, TEL, "image", None, REGLAGES)) == "avertir"
    lancer(db.whatsapp_messages.insert_one({"direction": "outbound", "to": "+" + TEL, "created_at": il_y_a(8.5),
                                            "barriere_auto": True, "ai_generated": True}))
    assert lancer(bw.decision(db, TEL, "image", None, REGLAGES)) == "retenir"
    # La réponse automatique de la barrière et celles de Liluvine ne lèvent PAS la barrière
    lancer(db.whatsapp_messages.insert_many([
        {"direction": "outbound", "phone_digits": TEL, "created_at": il_y_a(7), "ai_generated": True},
    ]))
    assert lancer(bw.decision(db, TEL, "text", "Allô", REGLAGES)) == "retenir"
    # … sauf si le réglage l'autorise
    assert lancer(bw.decision(db, TEL, "text", "Allô", {**REGLAGES, "wa_barriere_liluvine_compte": True})) == "normal"
    # Réponse d'un utilisateur : la barrière se lève
    # Lot 64.2 — une réponse automatique SANS la marque ai_generated (ex. VIDAL) ne lève pas non plus la barrière
    lancer(db.whatsapp_messages.insert_one({"direction": "outbound", "to": "+" + TEL, "created_at": il_y_a(6), "auto_reply": True}))
    assert lancer(bw.decision(db, TEL, "text", "Allô", REGLAGES)) == "retenir"
    lancer(db.whatsapp_messages.insert_one({"direction": "outbound", "to_number": "+" + TEL, "created_at": il_y_a(5),
                                            "sender_id": "u1", "sender_label": "Agent"}))
    assert lancer(bw.decision(db, TEL, "text", "Merci", REGLAGES)) == "normal"


def test_exceptions_et_desactivation(db):
    recu(db, 10)
    recu(db, 9)
    assert lancer(bw.decision(db, TEL, "text", "!garde", REGLAGES)) == "normal"          # commande
    assert lancer(bw.decision(db, TEL, "interactive", None, REGLAGES)) == "normal"       # bouton / formulaire
    assert lancer(bw.decision(db, TEL, "text", "x", {**REGLAGES, "wa_barriere_exemptes": "+226 70 11 22 33"})) == "normal"
    assert lancer(bw.decision(db, TEL, "text", "x", {"wa_barriere_active": False})) == "normal"
    # Messages hors de la fenêtre de temps : ignorés
    assert lancer(bw.decision(db, TEL, "text", "x", {**REGLAGES, "wa_barriere_seuil": 3})) == "avertir"
    # Seuil dépassé sans avertissement encore envoyé : avertissement (lot 64.5)
    assert lancer(bw.decision(db, TEL, "text", "x", {**REGLAGES, "wa_barriere_fenetre_heures": 1})) == "avertir"
    vieux = mongomock_motor.AsyncMongoMockClient()["sawali_lot63b"]
    lancer(vieux.whatsapp_messages.insert_many([
        {"direction": "inbound", "phone_digits": TEL, "created_at": il_y_a(60 * 30)},
        {"direction": "inbound", "phone_digits": TEL, "created_at": il_y_a(60 * 29)},
    ]))
    assert lancer(bw.decision(vieux, TEL, "text", "x", REGLAGES)) == "normal"            # > 24 h


def test_message_par_defaut_et_reglages():
    r = bw.reglages_barriere({"wa_barriere_active": True, "wa_barriere_seuil": "0"})
    assert r["seuil"] == 1 and r["message"] == bw.MESSAGE_DEFAUT and r["image_url"] == ""
    assert bw.reglages_barriere({}) is None


def test_presence_plateforme_nettoyee():
    r = sp._nettoyer({"indicateurs": [{"cle": "c", "libelle": "Connexions", "valeur": 3}], "utilisateurs_connectes": 2})
    assert r["utilisateurs_connectes"] == 2
    assert sp._nettoyer({"indicateurs": [{"cle": "c", "libelle": "C", "valeur": 1}]})["utilisateurs_connectes"] is None
    assert sp._nettoyer({"indicateurs": [{"cle": "c", "libelle": "C", "valeur": 1}], "utilisateurs_connectes": "x"})["utilisateurs_connectes"] is None


def test_diagnostic_barriere(db):
    """Lot 64.2 — diagnostic d'un numéro : désactivée, puis seuil atteint, puis levée."""
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient

    async def utilisateur():
        """Administrateur factice (pas d'authentification dans ce test)."""
        return {"id": "adm", "role": "admin"}

    api = APIRouter(prefix="/api")
    bw.setup_barriere_wa_routes(db=db, api=api, get_current_user=utilisateur)
    app = FastAPI()
    app.include_router(api)
    c = TestClient(app)
    lancer(db.settings.insert_one({"_id": "global", "wa_barriere_active": False}))
    assert c.get("/api/admin/barriere-wa/diagnostic", params={"numero": "+226 70 11 22 33"}).json()["active"] is False
    lancer(db.settings.update_one({"_id": "global"}, {"$set": {"wa_barriere_active": True, "wa_barriere_seuil": 2}}))
    recu(db, 10)
    r = c.get("/api/admin/barriere-wa/diagnostic", params={"numero": "+226 70 11 22 33"}).json()
    assert r["messages_sans_reponse"] == 1 and r["decision"] == "avertir"
    lancer(db.whatsapp_messages.insert_one({"direction": "outbound", "to": "+" + TEL, "created_at": il_y_a(5),
                                            "sender_id": "u1", "sender_label": "Agent"}))
    r = c.get("/api/admin/barriere-wa/diagnostic", params={"numero": TEL}).json()
    assert r["decision"] == "normal" and r["derniere_reponse_par"] == "Agent"


def test_seuil_depasse_sans_avertissement(db):
    """Lot 64.5 — compteur déjà au-delà du seuil (messages antérieurs) : l'avertissement part
    quand même une fois, puis les messages suivants sont retenus."""
    for m in (30, 29, 28, 27, 26):
        recu(db, m)
    assert lancer(bw.decision(db, TEL, "text", "Encore moi", REGLAGES)) == "avertir"
    lancer(db.whatsapp_messages.insert_one({"direction": "outbound", "to": "+" + TEL, "created_at": il_y_a(1),
                                            "barriere_auto": True, "ai_generated": True}))
    recu(db, 0.5)
    assert lancer(bw.decision(db, TEL, "text", "Toujours moi", REGLAGES)) == "retenir"
