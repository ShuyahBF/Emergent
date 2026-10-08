"""Lot 79.6 — compression gzip sélective des réponses (bande passante Render) et écran
« Messages bloqués » (messages retenus par la barrière anti-rafale, tous correspondants).
Lancer : cd backend && python -m pytest tests/test_lot79_6_bande_passante_bloques.py -q
"""
from __future__ import annotations

import asyncio
import gzip
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import JSONResponse, Response, StreamingResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.barriere_wa as bw  # noqa: E402
from compression_reponses import CompressionSelective, compressible  # noqa: E402


def lancer(coro):
    """Exécute une coroutine dans une boucle neuve."""
    return asyncio.new_event_loop().run_until_complete(coro)


def il_y_a(minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


# ---------------------------------------------------------------------------
# Compression sélective
# ---------------------------------------------------------------------------
@pytest.fixture()
def client():
    """Petite application avec les cas utiles : gros JSON, petit JSON, flux, PDF, déjà compressé."""
    app = FastAPI()
    app.add_middleware(CompressionSelective)

    @app.get("/gros")
    def gros():
        return JSONResponse({"lignes": [{"nom": f"Contact {i}", "tel": "22670112233"} for i in range(300)]})

    @app.get("/petit")
    def petit():
        return {"ok": True}

    @app.get("/flux")
    def flux():
        async def morceaux():
            for i in range(3):
                yield f"data: morceau {i} " + "x" * 600 + "\n\n"
        return StreamingResponse(morceaux(), media_type="text/event-stream")

    @app.get("/pdf")
    def pdf():
        return Response(b"%PDF-1.4 " + b"0" * 5000, media_type="application/pdf")

    @app.get("/deja")
    def deja():
        return Response(gzip.compress(b"a" * 5000), media_type="application/json", headers={"Content-Encoding": "gzip"})

    return TestClient(app)


def test_gros_json_compresse_et_lisible(client):
    r = client.get("/gros", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
    assert int(r.headers["content-length"]) < 3000            # ~15 Ko de JSON → bien moins
    assert len(r.json()["lignes"]) == 300                    # le client décompresse : contenu intact
    assert "accept-encoding" in r.headers.get("vary", "").lower()


def test_sans_accept_encoding_rien_ne_change(client):
    r = client.get("/gros", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in r.headers
    assert len(r.json()["lignes"]) == 300


def test_petite_reponse_non_compressee(client):
    r = client.get("/petit", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in r.headers and r.json() == {"ok": True}


def test_flux_en_continu_jamais_compresse(client):
    r = client.get("/flux", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in r.headers
    assert r.text.count("morceau") == 3


def test_pdf_et_reponse_deja_compressee_intacts(client):
    r = client.get("/pdf", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in r.headers and r.content.startswith(b"%PDF")
    r = client.get("/deja", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"       # une seule compression, pas deux
    assert r.content == b"a" * 5000


def test_types_compressibles():
    assert compressible("application/json") and compressible("text/html; charset=utf-8")
    assert not compressible("text/event-stream") and not compressible("image/png")
    assert not compressible("application/gzip") and not compressible("")


def test_middleware_installe_dans_le_serveur():
    source = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
    assert "app.add_middleware(CompressionSelective)" in source


# ---------------------------------------------------------------------------
# Messages bloqués
# ---------------------------------------------------------------------------
@pytest.fixture()
def db():
    return mongomock_motor.AsyncMongoMockClient()["sawali_lot79_6"]


def _retenu(db, tel, minutes, client_id="c1", **extra):
    lancer(db.whatsapp_messages.insert_one({
        "direction": "inbound", "phone_digits": tel, "client_id": client_id, "barriere_retenu": True,
        "created_at": il_y_a(minutes), "body": f"message {minutes}", "contact_name": "Awa", "contact_id": "k1",
        **extra}))


def test_liste_regroupee_par_correspondant_et_limitee_au_perimetre(db):
    _retenu(db, "22670112233", 30)
    _retenu(db, "22670112233", 10)
    _retenu(db, "22676000000", 5, contact_name="Issa", contact_id="k2")
    _retenu(db, "22671999999", 1, client_id="autre")            # hors périmètre : invisible
    # Avertissement automatique envoyé à Awa
    lancer(db.whatsapp_messages.insert_one({"direction": "outbound", "barriere_auto": True,
                                            "to": "+22670112233", "created_at": il_y_a(31)}))
    r = lancer(bw.lister_retenus(db, ["c1"]))
    assert r["total_retenus"] == 3 and len(r["bloques"]) == 2
    premier, second = r["bloques"]                               # le plus récent en tête
    assert premier["nom"] == "Issa" and premier["retenus"] == 1
    assert second["nom"] == "Awa" and second["retenus"] == 2
    assert second["dernier_texte"] == "message 10"
    assert second["premier_le"] < second["dernier_le"]
    assert second["averti_le"] and premier["averti_le"] is None


def test_liberer_remet_dans_la_conversation_et_trace(db):
    _retenu(db, "22670112233", 10)
    _retenu(db, "22670112233", 5)
    _retenu(db, "22670112233", 4, client_id="autre")            # autre périmètre : intouché
    n = lancer(bw.liberer_numero(db, ["c1"], "+226 70 11 22 33", "Admin"))
    assert n == 2
    r = lancer(bw.lister_retenus(db, ["c1"]))
    assert r["bloques"] == [] and r["liberes"][0]["messages"] == 2 and r["liberes"][0]["libere_par"] == "Admin"
    assert lancer(db.whatsapp_messages.count_documents({"barriere_retenu": True})) == 1
    assert lancer(bw.liberer_numero(db, ["c1"], "123", "Admin")) == 0   # numéro trop court : rien


def test_element_partageable_et_menu():
    from routes.liluvine_partage import ELEMENTS
    assert "bloques" in ELEMENTS
    racine = Path(__file__).resolve().parents[2] / "frontend" / "src"
    menu = (racine / "components" / "PortalLayout.jsx").read_text(encoding="utf-8")
    assert menu.count('partage: "bloques"') == 2               # portail (superviseurs) et administration
    app = (racine / "App.js").read_text(encoding="utf-8")
    assert app.count('path="liluvine-messages-bloques"') == 2
