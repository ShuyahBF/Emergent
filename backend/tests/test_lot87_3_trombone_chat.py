"""Lot 87.3 — trombone du chat : envoi d'un document ou d'une vidéo dans n'importe quelle discussion.
Lancer : cd backend && python -m pytest tests/test_lot87_3_trombone_chat.py -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import storage  # noqa: E402
from routes import internal_chat  # noqa: E402


def test_document_et_video_envoyes_dans_une_discussion(monkeypatch):
    # Stockage imité : on garde les octets en mémoire
    depot = {}

    async def disponible():
        return True

    async def deposer(chemin, data, mime):
        depot[chemin] = (data, mime)
        return chemin

    monkeypatch.setattr(storage, "astorage_available", disponible)
    monkeypatch.setattr(storage, "aupload_bytes", deposer)

    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot873"]
    asyncio.new_event_loop().run_until_complete(db.users.insert_many([
        {"id": "t1", "role": "client", "features": {"internal_chat": True}},
        {"id": "a1", "role": "admin", "full_name": "Admin"},
    ]))
    utilisateur = {"id": "a1", "role": "admin", "full_name": "Admin"}
    app = FastAPI()
    app.include_router(internal_chat.make_router(db=db, get_current_user=lambda: utilisateur, decode_token=lambda t: None),
                       prefix="/api")
    c = TestClient(app)

    # PDF dans #général du client t1
    r = c.post("/api/me/chat/t1/messages/fichier", files={"fichier": ("Devis mars.pdf", b"%PDF-1.4 test", "application/pdf")},
               data={"caption": "Voici le devis"})
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["media_kind"] == "document" and m["file_name"] == "Devis mars.pdf" and m["text"] == "Voici le devis"
    assert m["media_url"] == f"/api/me/chat/media/{m['id']}" and m["storage_path"].endswith(".pdf")
    # Vidéo MP4 en message privé au client
    r = c.post("/api/me/chat/t1/messages/fichier", files={"fichier": ("ecran.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")},
               data={"recipient_id": "t1"})
    assert r.status_code == 200 and r.json()["media_kind"] == "video" and r.json()["recipient_id"] == "t1"
    # Types refusés et fichier vide
    assert c.post("/api/me/chat/t1/messages/fichier", files={"fichier": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 400
    assert c.post("/api/me/chat/t1/messages/fichier", files={"fichier": ("vide.pdf", b"", "application/pdf")}).status_code == 400
    assert len(depot) == 2
