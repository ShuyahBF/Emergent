"""Lot 93 — pictogrammes de la fenêtre de chat des plateformes (comme dans SAWALI) : image / trombone (fichier relayé
en base64 par la plateforme, stocké, visible par l'équipe), note vocale transcrite, et lecture d'un média du fil
réservée à l'utilisateur concerné.
Lancer : cd backend && python -m pytest tests/test_lot93_pictos_support_plateformes.py -q
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("mongomock_motor")

import routes.support_plateformes as sp  # noqa: E402
from tests.test_lot90_support_plateformes import H_ADMIN, UTILISATEUR, env, poster  # noqa: E402,F401

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"
PDF = b"%PDF-1.4\n" + b"0" * 64


def data_url(octets: bytes, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(octets).decode()


@pytest.fixture()
def stockage(monkeypatch):
    """Stockage objet simulé (dictionnaire en mémoire)."""
    import storage
    boite = {}

    async def dispo():
        return True

    async def deposer(chemin, data, type_):
        boite[chemin] = (data, type_)
        return chemin

    async def lire(chemin):
        return boite[chemin]

    monkeypatch.setattr(storage, "astorage_available", dispo)
    monkeypatch.setattr(storage, "aupload_bytes", deposer)
    monkeypatch.setattr(storage, "afetch_bytes", lire)
    return boite


def test_fonctions_pures():
    assert sp.decoder_base64(data_url(JPEG, "image/jpeg")) == (JPEG, "image/jpeg")
    assert sp.decoder_base64(base64.b64encode(PDF).decode()) == (PDF, "")
    with pytest.raises(ValueError):
        sp.decoder_base64("data:image/png;base64,@@pas du base64@@")
    assert sp.vue_media({"id": "m1", "text": "x"}) is None
    v = sp.vue_media({"id": "m1", "media_url": "/api/me/chat/media/m1", "media_mime": "application/pdf",
                      "media_kind": "document", "file_name": "devis.pdf", "media_size": 10, "storage_path": "secret/chemin"})
    assert v == {"id": "m1", "type": "application/pdf", "genre": "document", "nom": "devis.pdf", "taille": 10}


def test_fichier_fil_et_media(env, stockage):
    c, _ = env
    c.put("/api/admin/support-plateformes/ster", json={"support_actif": True}, headers=H_ADMIN)
    # Type refusé, fichier illisible
    assert poster(c, "/api/support-plateforme/fichier", {"utilisateur": UTILISATEUR, "fichier": data_url(b"MZ...", "application/x-msdownload"), "nom": "virus.exe"}).status_code == 415
    assert poster(c, "/api/support-plateforme/fichier", {"utilisateur": UTILISATEUR, "fichier": "data:image/jpeg;base64,@@"}).status_code == 422

    # Photo avec légende → requête ouverte, message visible par l'équipe avec son média
    r = poster(c, "/api/support-plateforme/fichier", {"utilisateur": UTILISATEUR, "fichier": data_url(JPEG, "image/jpeg"),
                                                      "nom": "capture.jpg", "legende": "Voici l'erreur"})
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["requete"]["statut"] == "attente" and corps["message"]["media"]["genre"] == "image"
    mid = corps["message"]["id"]
    fils = c.get("/api/me/chat/support-plat-ster/threads", headers=H_ADMIN).json()
    msgs = c.get("/api/me/chat/support-plat-ster/messages", params={"with_user": fils[0]["key"]}, headers=H_ADMIN).json()
    liste = msgs if isinstance(msgs, list) else msgs.get("messages", [])
    assert any(m.get("media_url") == f"/api/me/chat/media/{mid}" for m in liste)
    assert c.get(f"/api/me/chat/media/{mid}", headers=H_ADMIN).content == JPEG

    # Document PDF ; le fil de l'utilisateur montre les deux pièces jointes (sans chemin de stockage)
    poster(c, "/api/support-plateforme/fichier", {"utilisateur": UTILISATEUR, "fichier": data_url(PDF, "application/pdf"), "nom": "devis.pdf"})
    fil = poster(c, "/api/support-plateforme/fil", {"utilisateur": {"id": "u-42"}}).json()
    medias = [m["media"] for m in fil["messages"] if m.get("media")]
    assert [x["genre"] for x in medias] == ["image", "document"] and medias[1]["nom"] == "devis.pdf"
    assert "storage_path" not in str(fil)

    # Lecture du média : l'utilisateur concerné seulement
    lu = poster(c, "/api/support-plateforme/media", {"utilisateur": {"id": "u-42"}, "message_id": mid}).json()
    assert base64.b64decode(lu["contenu"]) == JPEG and lu["type"] == "image/jpeg"
    assert poster(c, "/api/support-plateforme/media", {"utilisateur": {"id": "autre"}, "message_id": mid}).status_code == 404


def test_transcription(env, monkeypatch):
    c, _ = env
    c.put("/api/admin/support-plateformes/ster", json={"support_actif": True}, headers=H_ADMIN)
    import ia_client

    class FauxWhisper:
        def __init__(self, api_key=None):
            pass

        async def transcribe(self, **kw):
            class R:
                text = " Bonjour, ma caisse est bloquée. "
            return R()

    monkeypatch.setattr(ia_client, "OpenAISpeechToText", FauxWhisper)
    monkeypatch.setattr(ia_client, "cle_ia", lambda *a, **k: "cle")
    r = poster(c, "/api/support-plateforme/transcrire", {"utilisateur": UTILISATEUR, "audio": data_url(b"\x1aE\xdf\xa3" + b"0" * 40, "audio/webm"), "nom": "note.webm"})
    assert r.status_code == 200, r.text
    assert r.json()["texte"] == "Bonjour, ma caisse est bloquée."
    assert poster(c, "/api/support-plateforme/transcrire", {"utilisateur": UTILISATEUR, "audio": ""}).status_code == 422
