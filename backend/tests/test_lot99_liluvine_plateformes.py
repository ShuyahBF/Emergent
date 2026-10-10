"""Lot 99 — réponse automatique de Liluvine dans le support des plateformes web (règles du lot 98 : réponses courtes,
dialogue de 3 réponses au plus puis relais à un agent, pastille, relais Claude) + réglage par plateforme ;
message clair quand Facebook refuse la lecture des pages.
Lancer : cd backend && python -m pytest tests/test_lot99_liluvine_plateformes.py -q
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("mongomock_motor")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "test_lot99")

from tests.test_lot90_support_plateformes import H_ADMIN, UTILISATEUR, env, poster  # noqa: E402,F401

import routes.avis_claude as avis_claude  # noqa: E402
import routes.support_loois_sessions as sessions  # noqa: E402
import routes.support_plateformes as sp  # noqa: E402


@pytest.fixture()
def ia(monkeypatch):
    """Liluvine active, pas de demande de fonctionnalité, IA simulée (réponse donnée par `reponses`)."""
    reponses = []

    async def faux_ia(systeme, texte, modele):
        reponses.append(systeme)
        return "Pouvez-vous préciser la page concernée ?"

    async def pas_une_demande(db, **kw):
        return False

    monkeypatch.setattr(sessions, "liluvine_active", lambda: True)
    monkeypatch.setattr(sessions, "appeler_ia", faux_ia)
    monkeypatch.setattr(avis_claude, "traiter", pas_une_demande)
    return reponses


def attendre_reponses(c, n, essais=50):
    """La réponse de Liluvine part en tâche de fond : on relit le fil jusqu'à la voir."""
    for _ in range(essais):
        fil = poster(c, "/api/support-plateforme/fil", {"utilisateur": UTILISATEUR, "marquer_lu": False}).json()
        lili = [m for m in fil["messages"] if m["de"] == "support"]
        if len(lili) >= n:
            return lili
        time.sleep(0.05)
    return lili


def test_liluvine_repond_puis_passe_la_main(env, ia):
    c, db = env
    c.put("/api/admin/support-plateformes/ster", json={"support_actif": True}, headers=H_ADMIN)
    # Réglage par défaut : réponse automatique activée
    plat = next(p for p in c.get("/api/admin/support-plateformes", headers=H_ADMIN).json()["plateformes"] if p["code"] == "ster")
    assert plat["liluvine_auto"] is True

    # 3 réponses de Liluvine au plus (règle 2), puis un seul message de relais, puis silence
    for i in range(5):
        poster(c, "/api/support-plateforme/messages", {"utilisateur": UTILISATEUR, "texte": f"Ça ne marche pas {i}"})
        attendre_reponses(c, min(i + 1, sp.LILUVINE_TOURS_MAX + 1))
    lili = attendre_reponses(c, sp.LILUVINE_TOURS_MAX + 1)
    assert len(lili) == sp.LILUVINE_TOURS_MAX + 1
    assert lili[0]["auteur"].startswith("🤖 Liluvine")
    assert lili[-1]["texte"] == sp.TEXTE_RELAIS
    # Consignes : règles du lot 98 et nom de la plateforme ; la dernière réponse conclut
    assert "RÈGLES DE RÉPONSE" in ia[0] and "sTer" in ia[0]
    assert "dernière réponse" in ia[sp.LILUVINE_TOURS_MAX - 1]
    # La requête reste « en attente » (Liluvine n'est pas un agent)
    req = c.portal.call(db.support_plateformes_requetes.find_one, {"plateforme": "ster"})
    assert req["statut"] == "attente" and req["liluvine_tours"] == sp.LILUVINE_TOURS_MAX


def test_reglage_desactive(env, ia):
    c, _ = env
    c.put("/api/admin/support-plateformes/ster", json={"support_actif": True}, headers=H_ADMIN)
    r = c.put("/api/admin/support-plateformes/ster", json={"liluvine_auto": False}, headers=H_ADMIN).json()
    assert r == {"ok": True, "code": "ster", "liluvine_auto": False}
    poster(c, "/api/support-plateforme/messages", {"utilisateur": UTILISATEUR, "texte": "Bonjour, aide svp"})
    time.sleep(0.3)
    assert attendre_reponses(c, 1, essais=3) == [] and ia == []
    # Le support reste activé (on ne modifie que le champ envoyé)
    plat = next(p for p in c.get("/api/admin/support-plateformes", headers=H_ADMIN).json()["plateformes"] if p["code"] == "ster")
    assert plat["support_actif"] is True and plat["liluvine_auto"] is False


def test_message_erreur_facebook():
    from routes.facebook_animation import message_erreur_facebook

    class Rep:
        def __init__(self, corps, statut=400):
            self.corps, self.status_code = corps, statut

        def json(self):
            return self.corps

    assert "Reconnecter Facebook" in message_erreur_facebook(Rep({"error": {"code": 190, "message": "Session expired"}}))
    assert "pages_show_list" in message_erreur_facebook(Rep({"error": {"code": 200, "message": "Permissions error"}}))
    assert message_erreur_facebook(Rep({"error": {"code": 1, "message": "Oups"}})).endswith("(400) : Oups")
