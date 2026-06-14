"""Iter43-fix12 (2026-03) — Tests Officines Registry:
- Tri alphabétique + products_count agrégé
- Filtre par activité principale
- CRUD activités principales (GET / PUT)
- Import produits CSV (séparateur , ou ;) avec/sans en-tête
- Import produits JSON imbriqué (flatten)
- Mode replace vs append
- Anti-doublons intra-fichier sur (officine, produit, conditionnement)
- Liste produits paginée + recherche
- Suppression tous les produits
- Export CSV
- BugFix /api-routes (n'est plus 500)
"""
import os
import uuid
import io
import pytest
import requests
from datetime import datetime, timezone
from pymongo import MongoClient
import jwt
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

API = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001") + "/api"
JWT_SECRET = os.environ.get("JWT_SECRET", "sawali-jwt-secret-change-me")


def _admin_token(uid: str) -> str:
    return jwt.encode(
        {"sub": uid, "user_id": uid, "id": uid, "role": "admin",
         "email": f"{uid}@admintest.com",
         "exp": datetime.now(timezone.utc).timestamp() + 3600},
        JWT_SECRET, algorithm="HS256",
    )


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin(db):
    uid = f"iter43f12_adm_{uuid.uuid4().hex[:8]}"
    db.users.insert_one({
        "id": uid, "email": f"{uid}@admintest.com", "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {"id": uid, "headers": {"Authorization": f"Bearer {_admin_token(uid)}"}}
    db.users.delete_one({"id": uid})


@pytest.fixture()
def cleanup(db):
    ids = {"officines": [], "products_office": []}
    yield ids
    if ids["officines"]:
        db.officines.delete_many({"id": {"$in": ids["officines"]}})
    if ids["products_office"]:
        db.officine_products.delete_many({"officine_id": {"$in": ids["products_office"]}})


def _make_officine(db, cleanup, name, **extras):
    oid = f"iter43f12_off_{uuid.uuid4().hex[:8]}"
    cleanup["officines"].append(oid)
    cleanup["products_office"].append(oid)
    doc = {
        "id": oid, "name": name, "code": name.upper().replace(" ", "_"),
        "email": f"{name.lower().replace(' ', '')}@example.com",
        "phone": "+22670000000", "phone_digits": "22670000000",
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    doc.update(extras)
    db.officines.insert_one(doc)
    return oid


class TestAlphabeticalSorting:
    def test_sorts_by_name_asc(self, admin, db, cleanup):
        # Insert in non-alphabetical order
        _make_officine(db, cleanup, "Zenith")
        _make_officine(db, cleanup, "Alpha")
        _make_officine(db, cleanup, "Bêta")  # accent test
        r = requests.get(f"{API}/admin/officines-registry", headers=admin["headers"],
                         params={"status": "active", "limit": 500})
        assert r.status_code == 200
        names = [it["name"] for it in r.json()["items"]
                 if it["name"] in {"Zenith", "Alpha", "Bêta"}]
        assert names == ["Alpha", "Bêta", "Zenith"]

    def test_products_count_included(self, admin, db, cleanup):
        oid = _make_officine(db, cleanup, f"WithProducts_{uuid.uuid4().hex[:6]}")
        for i in range(7):
            db.officine_products.insert_one({
                "id": str(uuid.uuid4()), "officine_id": oid,
                "product_name": f"Med{i}", "product_name_norm": f"med{i}",
                "conditionnement": "Bte 10", "conditionnement_norm": "bte 10",
                "stock": i,
            })
        r = requests.get(f"{API}/admin/officines-registry", headers=admin["headers"], params={"limit": 500})
        target = next((x for x in r.json()["items"] if x["id"] == oid), None)
        assert target is not None
        assert target["products_count"] == 7


class TestActivitiesCRUD:
    def test_default_activities(self, admin, db):
        # Force le retour aux valeurs par défaut (autres tests peuvent l'avoir modifié)
        db.settings.update_one({"_id": "global"},
                               {"$unset": {"officines_activities": ""}})
        r = requests.get(f"{API}/admin/officine-activities", headers=admin["headers"])
        assert r.status_code == 200
        acts = r.json()["activities"]
        assert "Pharmacie" in acts
        assert "Grossiste" in acts
        assert "Dépôt" in acts
        assert "Distributeur" in acts

    def test_update_activities(self, admin, db):
        new_list = ["Pharmacie", "Grossiste", "Dépôt", "Distributeur", "Hôpital"]
        r = requests.put(f"{API}/admin/officine-activities",
                         headers={**admin["headers"], "Content-Type": "application/json"},
                         json={"activities": new_list})
        assert r.status_code == 200
        assert r.json()["activities"] == new_list
        # Persistance DB
        doc = db.settings.find_one({"_id": "global"})
        assert doc["officines_activities"] == new_list
        # Dédoublonnage
        r = requests.put(f"{API}/admin/officine-activities",
                         headers={**admin["headers"], "Content-Type": "application/json"},
                         json={"activities": ["Pharmacie", "pharmacie", "Grossiste"]})
        assert r.status_code == 200
        assert len(r.json()["activities"]) == 2  # déduplication insensible casse

    def test_empty_activities_rejected(self, admin):
        r = requests.put(f"{API}/admin/officine-activities",
                         headers={**admin["headers"], "Content-Type": "application/json"},
                         json={"activities": []})
        assert r.status_code == 400


class TestActivityFilter:
    def test_filter_by_activite(self, admin, db, cleanup):
        _make_officine(db, cleanup, f"TestPharm_{uuid.uuid4().hex[:6]}", activite_principale="Pharmacie")
        _make_officine(db, cleanup, f"TestGross_{uuid.uuid4().hex[:6]}", activite_principale="Grossiste")
        _make_officine(db, cleanup, f"TestNoActiv_{uuid.uuid4().hex[:6]}")
        r = requests.get(f"{API}/admin/officines-registry", headers=admin["headers"],
                         params={"activite": "Pharmacie", "limit": 500})
        items = r.json()["items"]
        assert all(it.get("activite_principale") == "Pharmacie" for it in items)
        assert len(items) >= 1


class TestUpdateOfficineActivity:
    def test_can_set_activite(self, admin, db, cleanup):
        oid = _make_officine(db, cleanup, f"UpdAct_{uuid.uuid4().hex[:6]}")
        r = requests.put(f"{API}/admin/officines-registry/{oid}",
                         headers={**admin["headers"], "Content-Type": "application/json"},
                         json={"activite_principale": "Distributeur"})
        assert r.status_code == 200, r.text
        doc = db.officines.find_one({"id": oid})
        assert doc["activite_principale"] == "Distributeur"


class TestProductsImportCSV:
    def test_csv_semicolon_with_header(self, admin, db, cleanup):
        oid = _make_officine(db, cleanup, f"CSV_Semi_{uuid.uuid4().hex[:6]}")
        csv_data = b"""Code Officine;Produit;Conditionnement;CIP;Stock
PH01;Doliprane 1000mg;Bte 8;3400938954341;120
PH01;Doliprane 1000mg;Bte 8;3400938954341;120
PH01;Efferalgan 500mg;Bte 16;3400933889340;45
"""
        r = requests.post(
            f"{API}/admin/officines-registry/{oid}/products/import",
            headers=admin["headers"],
            data={"mode": "replace"},
            files={"file": ("products.csv", io.BytesIO(csv_data), "text/csv")},
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["format"] == "csv"
        assert d["header_detected"] is True
        assert d["created"] == 2  # 1 doublon skipped
        assert d["skipped"] == 1
        total = db.officine_products.count_documents({"officine_id": oid})
        assert total == 2

    def test_csv_comma_no_header_positional(self, admin, db, cleanup):
        oid = _make_officine(db, cleanup, f"CSV_Pos_{uuid.uuid4().hex[:6]}")
        csv_data = b"PH02,Aspirine,Bte 20,3400932111111,80\nPH02,Vitamine C,Tube 10,,15\n"
        r = requests.post(
            f"{API}/admin/officines-registry/{oid}/products/import",
            headers=admin["headers"],
            data={"mode": "replace"},
            files={"file": ("p.csv", io.BytesIO(csv_data), "text/csv")},
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["created"] == 2
        assert d["header_detected"] is False
        # CIP optionnel pour Vitamine C
        prods = list(db.officine_products.find({"officine_id": oid}, {"_id": 0}).sort("product_name", 1))
        assert prods[0]["product_name"] == "Aspirine"
        assert prods[1]["product_name"] == "Vitamine C"
        assert prods[1]["cip"] is None

    def test_csv_replace_then_append(self, admin, db, cleanup):
        oid = _make_officine(db, cleanup, f"CSV_RA_{uuid.uuid4().hex[:6]}")
        # Initial replace
        csv1 = b"Produit,Conditionnement,Stock\nP1,Bte,10\nP2,Sac,5\n"
        requests.post(
            f"{API}/admin/officines-registry/{oid}/products/import",
            headers=admin["headers"], data={"mode": "replace"},
            files={"file": ("p.csv", io.BytesIO(csv1), "text/csv")},
        )
        assert db.officine_products.count_documents({"officine_id": oid}) == 2
        # Append : ajoute P3 et met à jour P1
        csv2 = b"Produit,Conditionnement,Stock\nP1,Bte,99\nP3,Box,7\n"
        r = requests.post(
            f"{API}/admin/officines-registry/{oid}/products/import",
            headers=admin["headers"], data={"mode": "append"},
            files={"file": ("p.csv", io.BytesIO(csv2), "text/csv")},
        )
        d = r.json()
        assert d["mode"] == "append"
        assert d["updated"] == 1  # P1 mis à jour
        assert d["created"] == 1  # P3 créé
        # P1 doit avoir stock=99
        p1 = db.officine_products.find_one({"officine_id": oid, "product_name": "P1"})
        assert p1["stock"] == 99
        # Total = 3
        assert db.officine_products.count_documents({"officine_id": oid}) == 3


class TestProductsImportJSON:
    def test_json_flat_list(self, admin, db, cleanup):
        oid = _make_officine(db, cleanup, f"JSON_Flat_{uuid.uuid4().hex[:6]}")
        json_data = b'[{"Produit":"X","Conditionnement":"C","Stock":3,"CIP":"123"},{"Produit":"Y","Stock":1}]'
        r = requests.post(
            f"{API}/admin/officines-registry/{oid}/products/import",
            headers=admin["headers"], data={"mode": "replace"},
            files={"file": ("p.json", io.BytesIO(json_data), "application/json")},
        )
        assert r.status_code == 200
        d = r.json()
        assert d["format"] == "json"
        assert d["created"] == 2

    def test_json_nested_structure(self, admin, db, cleanup):
        oid = _make_officine(db, cleanup, f"JSON_Nested_{uuid.uuid4().hex[:6]}")
        json_data = (
            b'{"officine":"X","data":{"items":{"produits":['
            b'{"Produit":"P1","Conditionnement":"Bte","Stock":5,"CIP":"111"},'
            b'{"produit":"P2","Stock":2}]}}}'
        )
        r = requests.post(
            f"{API}/admin/officines-registry/{oid}/products/import",
            headers=admin["headers"], data={"mode": "replace"},
            files={"file": ("p.json", io.BytesIO(json_data), "application/json")},
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["created"] == 2

    def test_invalid_json(self, admin, cleanup, db):
        oid = _make_officine(db, cleanup, f"JSON_Bad_{uuid.uuid4().hex[:6]}")
        r = requests.post(
            f"{API}/admin/officines-registry/{oid}/products/import",
            headers=admin["headers"], data={"mode": "replace"},
            files={"file": ("p.json", io.BytesIO(b"{not json"), "application/json")},
        )
        assert r.status_code == 400


class TestProductsListAndExport:
    def _setup(self, db, cleanup):
        oid = _make_officine(db, cleanup, f"Plist_{uuid.uuid4().hex[:6]}")
        # 5 produits
        for i in range(5):
            db.officine_products.insert_one({
                "id": str(uuid.uuid4()), "officine_id": oid,
                "product_name": f"Med{i:02d}", "product_name_norm": f"med{i:02d}",
                "conditionnement": "Bte", "conditionnement_norm": "bte",
                "cip": f"CIP{i:03d}", "stock": (i + 1) * 10,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        return oid

    def test_list_pagination_search(self, admin, db, cleanup):
        oid = self._setup(db, cleanup)
        # Pagination
        r = requests.get(f"{API}/admin/officines-registry/{oid}/products",
                         headers=admin["headers"], params={"limit": 2, "offset": 0})
        assert r.status_code == 200
        d = r.json()
        assert d["total"] == 5
        assert len(d["items"]) == 2
        # Search
        r2 = requests.get(f"{API}/admin/officines-registry/{oid}/products",
                          headers=admin["headers"], params={"q": "Med03"})
        assert r2.json()["total"] == 1
        # Sort
        r3 = requests.get(f"{API}/admin/officines-registry/{oid}/products",
                          headers=admin["headers"], params={"sort": "stock", "order": "desc"})
        items = r3.json()["items"]
        assert items[0]["stock"] >= items[-1]["stock"]

    def test_clear_all_products(self, admin, db, cleanup):
        oid = self._setup(db, cleanup)
        r = requests.delete(f"{API}/admin/officines-registry/{oid}/products",
                            headers=admin["headers"])
        assert r.status_code == 200
        assert r.json()["deleted"] == 5
        assert db.officine_products.count_documents({"officine_id": oid}) == 0

    def test_export_csv(self, admin, db, cleanup):
        oid = self._setup(db, cleanup)
        r = requests.get(f"{API}/admin/officines-registry/{oid}/products/export.csv",
                        headers=admin["headers"])
        assert r.status_code == 200
        body = r.text
        # Header + 5 rows
        lines = [ln for ln in body.split("\n") if ln.strip()]
        assert len(lines) == 6
        assert lines[0].startswith("Code Officine,Produit,Conditionnement,CIP,Stock")
        assert "Med00" in body
        assert "Med04" in body


class TestEdgeCases:
    def test_import_unknown_officine_404(self, admin):
        r = requests.post(
            f"{API}/admin/officines-registry/unknown-iter43f12/products/import",
            headers=admin["headers"], data={"mode": "replace"},
            files={"file": ("p.csv", io.BytesIO(b"Produit\nX\n"), "text/csv")},
        )
        assert r.status_code == 404

    def test_missing_file(self, admin, db, cleanup):
        oid = _make_officine(db, cleanup, f"NoFile_{uuid.uuid4().hex[:6]}")
        r = requests.post(
            f"{API}/admin/officines-registry/{oid}/products/import",
            headers=admin["headers"], data={"mode": "replace"},
        )
        assert r.status_code == 400

    def test_invalid_mode(self, admin, db, cleanup):
        oid = _make_officine(db, cleanup, f"BadMode_{uuid.uuid4().hex[:6]}")
        r = requests.post(
            f"{API}/admin/officines-registry/{oid}/products/import",
            headers=admin["headers"], data={"mode": "weird"},
            files={"file": ("p.csv", io.BytesIO(b"Produit\nX\n"), "text/csv")},
        )
        assert r.status_code == 400


class TestApiRoutesBugFix:
    def test_api_routes_no_500(self):
        """Iter43-fix12 bug-fix : /api-routes ne doit plus crasher avec TypeError."""
        r = requests.get(f"{API}/api-routes")
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert isinstance(d, list)
        assert len(d) > 100  # ~850 routes en réalité
        # Vérifie qu'on a bien `methods`, `path`, `tags`
        sample = d[0]
        assert "methods" in sample
        assert "path" in sample
        assert isinstance(sample["methods"], list)
