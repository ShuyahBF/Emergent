"""Lot 291 — la lecture du calendrier rapporte si Google a répondu (bouton « resynchroniser » de l'écran)."""
import asyncio

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from routes.calendrier_partage import attach_calendrier_partage_routes


def _client(freebusy, etat):
    base = AsyncMongoMockClient()["test_cal_291"]

    async def utilisateur():
        return {"id": "u1", "role": "admin", "client_id": "c1"}

    api = APIRouter(prefix="/api")
    attach_calendrier_partage_routes(api=api, db=base, get_current_user=utilisateur, public_base_url=lambda: "https://x",
                                     google_freebusy=freebusy, is_admin_like=lambda u: True, google_etat=lambda: etat)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app)


def test_google_a_repondu_les_blocs_google_sont_affiches():
    etat = {"ok": None, "erreur": "", "le": None}

    async def freebusy(a, b):
        etat.update({"ok": True, "erreur": "", "le": "2026-10-26T10:00:00+00:00"})
        return [{"start": "2026-10-26T10:00:00+00:00", "end": "2026-10-26T11:00:00+00:00"}]

    r = _client(freebusy, etat).get("/api/me/calendrier/occupations", params={"debut": "2026-10-26", "jours": 7}).json()
    assert r["google"] is True and r["google_etat"]["ok"] is True
    assert [o["source"] for o in r["occupations"]] == ["google"]


def test_google_muet_l_ecran_peut_expliquer_pourquoi():
    etat = {"ok": None, "erreur": "", "le": None}

    async def freebusy(a, b):
        etat.update({"ok": False, "erreur": "Google n'a pas répondu : jeton expiré", "le": "2026-10-26T10:00:00+00:00"})
        return []

    r = _client(freebusy, etat).get("/api/me/calendrier/occupations", params={"debut": "2026-10-26"}).json()
    assert r["google_etat"]["ok"] is False and "jeton expiré" in r["google_etat"]["erreur"] and r["occupations"] == []
