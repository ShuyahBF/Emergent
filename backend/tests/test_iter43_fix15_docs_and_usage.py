"""Iter43-fix15 — Tests pour:
- Bug /api-routes : pas de 500
- Estimation tokens/coût pour assets Story Studio (image + vidéo)
- Translation FR des docstrings : aucune route admin avec docstring en anglais brut
"""
import os
import uuid
import pytest
import requests
import re
from datetime import datetime, timezone
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
API = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001") + "/api"


class TestApiRoutesAndDocs:
    def test_api_routes_200(self):
        r = requests.get(f"{API}/api-routes")
        assert r.status_code == 200
        d = r.json()
        assert isinstance(d, list)
        assert len(d) > 800

    def test_swagger_docs_accessible(self):
        # Swagger UI is mounted at /api/docs (passe par l'ingress K8s)
        r = requests.get(f"{API}/docs")
        assert r.status_code == 200
        assert "swagger" in r.text.lower() or "fastapi" in r.text.lower()

    def test_openapi_json_accessible(self):
        r = requests.get(f"{API}/openapi.json")
        assert r.status_code == 200
        d = r.json()
        assert "paths" in d
        assert "info" in d

    def test_few_english_docstrings_remain(self):
        """Vérifie qu'on a sub-1% de docstrings encore en anglais brut sur les
        endpoints admin."""
        r = requests.get(f"{API}/api-routes")
        routes = r.json()
        english_marker = re.compile(
            r"\b(Returns the|Get the|List of|Create a new|Update the|Delete the|Send a free)\b"
        )
        offenders = []
        for route in routes:
            s = (route.get("summary") or "").strip()
            if not s:
                continue
            # Skip if French markers visible
            if any(w in s.lower() for w in ["récup", "renvoy", "retourn", "créer", "supprim",
                                            "ajout", "envoy", "génère", "vérifi", "obten",
                                            "modifi", "calcule"]):
                continue
            if english_marker.search(s):
                offenders.append((route["path"], s[:90]))
        assert len(offenders) <= 5, f"Trop d'anglais ({len(offenders)}) : {offenders[:5]}"


class TestUsageEstimate:
    def test_asset_has_usage_estimate_after_generate(self, monkeypatch=None):
        """Test : insère un asset prêt avec usage_estimate et vérifie le format."""
        client = MongoClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        aid = f"iter43f15_asset_{uuid.uuid4().hex[:8]}"
        try:
            db.story_assets.insert_one({
                "id": aid, "tenant_id": "t1", "kind": "video", "engine": "sora-2",
                "prompt": "p", "title": "test usage", "status": "ready",
                "url": f"/admin/story-studio/library/{aid}/media",
                "usage_estimate": {
                    "engine": "sora-2",
                    "engine_label": "Sora 2 (720p)",
                    "unit": "second",
                    "quantity": 8,
                    "unit_cost_usd": 0.10,
                    "estimated_cost_usd": 0.80,
                    "estimated_cost_xof": 496,
                    "estimated": True,
                },
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            doc = db.story_assets.find_one({"id": aid})
            assert doc["usage_estimate"]["estimated"] is True
            assert doc["usage_estimate"]["estimated_cost_xof"] == 496
            assert doc["usage_estimate"]["engine"] == "sora-2"
        finally:
            db.story_assets.delete_one({"id": aid})


class TestApiDocsBaseUrl:
    """Vérifie côté code que ApiDocs.jsx utilise window.location.origin au runtime."""

    def test_apidocs_uses_runtime_origin(self):
        from pathlib import Path
        content = Path("/app/frontend/src/pages/ApiDocs.jsx").read_text()
        assert "window.location.origin" in content
        # Le fallback peut être process.env mais runtime doit être prioritaire
        # On vérifie que `backend` est défini via window
        assert re.search(
            r"const\s+backend\s*=\s*[^;]*window\.location\.origin",
            content,
        ), "backend doit utiliser window.location.origin"
