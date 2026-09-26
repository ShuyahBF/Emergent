"""Lot 26 — le serveur ne doit plus se figer (erreurs Cloudflare 502/520 aléatoires).

- stockage Emergent : `storage_available()` ne fait plus d'appel réseau ; les
  versions asynchrones travaillent dans un thread et laissent le serveur
  répondre aux autres requêtes pendant ce temps ; un objet absent n'est pas
  redemandé pendant 10 minutes ;
- météo : Open-Meteo injoignable -> réponse normale « indisponible » (pas 502) ;
- noms de fichiers avec caractères spéciaux : en-tête Content-Disposition sûr.
Tests autonomes : aucun réseau.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: E402


@pytest.fixture()
def slow_storage(monkeypatch):
    """Stockage configuré mais dont l'initialisation met 0,6 s (réseau lent)."""
    monkeypatch.setattr(storage, "EMERGENT_KEY", "cle-test")
    monkeypatch.setattr(storage, "_storage_key", None)
    monkeypatch.setattr(storage, "_storage_key_attempts", 0)
    monkeypatch.setattr(storage, "_storage_key_last_attempt_ts", 0.0)
    calls = []

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"storage_key": "k-123"}

    def slow_post(*a, **k):
        calls.append(time.time())
        time.sleep(0.6)
        return _Resp()
    monkeypatch.setattr(storage.httpx, "post", slow_post)
    return calls


def test_storage_available_never_blocks(slow_storage):
    t0 = time.time()
    assert storage.storage_available() is False          # pas encore de clé : réponse immédiate
    assert time.time() - t0 < 0.2
    # L'initialisation s'est faite en arrière-plan
    for _ in range(40):
        if storage._storage_key:
            break
        time.sleep(0.05)
    assert storage._storage_key == "k-123" and storage.storage_available() is True
    assert len(slow_storage) == 1


def test_async_init_keeps_event_loop_responsive(slow_storage):
    """Pendant l'initialisation lente, la boucle continue de tourner."""
    async def scenario():
        ticks = 0
        done = False

        async def ticker():
            nonlocal ticks
            while not done:
                ticks += 1
                await asyncio.sleep(0.02)
        t = asyncio.create_task(ticker())
        ok = await storage.astorage_available()
        done = True
        await t
        return ok, ticks
    ok, ticks = asyncio.run(scenario())
    assert ok is True
    assert ticks >= 10          # ~0,6 s de travail : la boucle a tourné au moins 10 fois


def test_asave_upload_and_cache_without_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "EMERGENT_KEY", None)
    path, sp, err = asyncio.run(storage.asave_upload_and_cache(upload_dir=tmp_path, filename="a.txt", data=b"bonjour"))
    assert path.read_bytes() == b"bonjour" and sp is None and err is None


def test_rehydrate_negative_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "EMERGENT_KEY", "cle")
    monkeypatch.setattr(storage, "_storage_key", "k")
    storage._missing.clear()
    calls = []

    def missing(path):
        calls.append(path)
        raise RuntimeError("404")
    monkeypatch.setattr(storage, "fetch_bytes", missing)
    target = tmp_path / "x.png"
    assert asyncio.run(storage.arehydrate_from_storage(local_path=target, remote_path="files/x.png")) is False
    assert asyncio.run(storage.arehydrate_from_storage(local_path=target, remote_path="files/x.png")) is False
    assert calls == ["files/x.png"]                      # redemandé une seule fois
    storage._missing.clear()


def test_weather_unavailable_is_not_an_error(monkeypatch):
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    import routes.weather as weather

    class _Boom:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            raise httpx.ConnectTimeout("injoignable")
    monkeypatch.setattr(weather.httpx, "AsyncClient", _Boom)
    weather._CACHE.clear()
    app = FastAPI()
    api = APIRouter(prefix="/api")
    weather.setup_weather_routes(db=None, api=api)
    app.include_router(api)
    r = TestClient(app).get("/api/public/weather/current?lat=12.37&lon=-1.52")
    assert r.status_code == 200 and r.json()["available"] is False
    # Mémorisé : pas de nouvel essai immédiat
    monkeypatch.setattr(weather.httpx, "AsyncClient", lambda *a, **k: (_ for _ in ()).throw(AssertionError("rappel")))
    assert TestClient(app).get("/api/public/weather/current?lat=12.37&lon=-1.52").json()["available"] is False
    weather._CACHE.clear()


def test_content_disposition_accepts_any_name():
    import importlib.util
    src = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
    start = src.index("def _content_disposition(")
    import re
    m = re.compile(r"\n(?=[@A-Za-z_])").search(src, start + 10)   # fin : prochaine ligne non indentée
    end = m.start()
    ns: dict = {}
    exec(compile(src[start:end], "cd", "exec"), ns)   # la fonction seule, sans démarrer le serveur
    h = ns["_content_disposition"]("attachment", "Devis d’œuvre – 2026 €.pdf")
    h.encode("latin-1")                                  # ne lève plus d'erreur
    assert h.startswith('attachment; filename="') and "filename*=UTF-8''Devis%20d%E2%80%99%C5%93uvre" in h
    assert ns["_content_disposition"]("inline", "") == "inline"
    assert importlib.util is not None


def test_whatsapp_template_params_are_cleaned():
    """#132018 : pas de retour à la ligne, tabulation ni plus de 4 espaces ; pas de valeur vide."""
    from routes.whatsapp_helpers import _wa_clean_template_components, _wa_clean_template_param
    msg = "Je suis la directrice de Deli GROCERY\nNotre machine nous a lâché hier après un délestage"
    assert _wa_clean_template_param(msg) == ("Je suis la directrice de Deli GROCERY · Notre machine nous a "
                                            "lâché hier après un délestage")
    assert _wa_clean_template_param("a\t\tb      c") == "a  b   c"
    assert _wa_clean_template_param("") == "—" and _wa_clean_template_param(None) == "—"
    comps = _wa_clean_template_components([
        {"type": "header", "parameters": [{"type": "image", "image": {"link": "https://x/y.png"}}]},
        {"type": "body", "parameters": [{"type": "text", "text": "ligne 1\r\n\r\nligne 2"}, {"type": "text", "text": ""}]},
    ])
    assert comps[0]["parameters"][0]["image"]["link"] == "https://x/y.png"
    assert [p["text"] for p in comps[1]["parameters"]] == ["ligne 1 · ligne 2", "—"]
