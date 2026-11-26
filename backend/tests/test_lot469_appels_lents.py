"""Lot 469 — appels les plus lents corrigés (règle 7).

Vérifie que le dictionnaire public des traductions est mis en cache (une 2e lecture ne relit pas la base)
et que toute écriture faite depuis l'administration vide ce cache tout de suite."""
import sys
from pathlib import Path

import mongomock_motor
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from routes import i18n  # noqa: E402


def _appli():
    """Application minimale : routes i18n + base simulée + administrateur factice."""
    db = mongomock_motor.AsyncMongoMockClient()["test_lot469"]
    api = APIRouter(prefix="/api")

    async def get_current_user():
        return {"id": "u1", "email": "admin@test", "role": "admin"}

    i18n.attach_i18n_routes(api, db=db, get_current_user=get_current_user)
    app = FastAPI()
    app.include_router(api)
    i18n._vider_cache_traductions()          # chaque test part d'un cache vide
    return TestClient(app), db


def test_le_dictionnaire_est_mis_en_cache():
    client, db = _appli()
    premier = client.get("/api/i18n/translations?lang=fr").json()
    # une ligne ajoutée DIRECTEMENT en base (sans passer par l'administration) n'apparaît pas tant que le cache est frais
    import asyncio
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        db.i18n_translations.insert_one({"key": "test.lot469.direct", "fr": "x", "en": "", "ar": "", "lg1": "", "lg2": ""}))
    second = client.get("/api/i18n/translations?lang=fr").json()
    assert second["count"] == premier["count"]
    assert "test.lot469.direct" not in second["translations"]


def test_une_ecriture_admin_vide_le_cache():
    client, _ = _appli()
    client.get("/api/i18n/translations?lang=fr")                      # remplit le cache
    r = client.post("/api/admin/i18n/translations",
                    json={"key": "test.lot469.admin", "fr": "Bonjour lot 469", "en": "", "ar": "", "lg1": "", "lg2": ""})
    assert r.status_code == 200, r.text
    apres = client.get("/api/i18n/translations?lang=fr").json()
    assert apres["translations"].get("test.lot469.admin") == "Bonjour lot 469"   # visible tout de suite


def test_la_suppression_vide_aussi_le_cache():
    client, _ = _appli()
    client.post("/api/admin/i18n/translations",
                json={"key": "test.lot469.suppr", "fr": "à supprimer", "en": "", "ar": "", "lg1": "", "lg2": ""})
    assert "test.lot469.suppr" in client.get("/api/i18n/translations?lang=fr").json()["translations"]
    client.delete("/api/admin/i18n/translations/test.lot469.suppr")
    assert "test.lot469.suppr" not in client.get("/api/i18n/translations?lang=fr").json()["translations"]
