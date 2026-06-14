"""Iter43-fix9 — Backend tests for Officines Registry CSV import, edit,
upload logo, import-to-contacts, and approve activation tracking."""
from __future__ import annotations

import io
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt as pyjwt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))
load_dotenv(Path("/app/frontend/.env"))
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
JWT_SECRET = os.environ["JWT_SECRET"]


def _forge_admin(uid: str) -> str:
    return pyjwt.encode({
        "sub": uid, "role": "admin",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture(scope="module")
def db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def admin_ctx(db):
    aid = f"iter43f9_adm_{uuid.uuid4().hex[:8]}"
    email = f"{aid}@admintest.com"
    db.users.insert_one({
        "id": aid, "email": email, "password_hash": "x",
        "role": "admin", "account_status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    headers = {"Authorization": f"Bearer {_forge_admin(aid)}"}
    yield {"id": aid, "email": email, "headers": headers}
    db.users.delete_one({"id": aid})


@pytest.fixture()
def cleanup(db):
    ids = []
    contact_ids = []
    group_ids = []
    yield {"ids": ids, "contact_ids": contact_ids, "group_ids": group_ids}
    if ids:
        db.officines.delete_many({"id": {"$in": ids}})
        db.officine_audit_log.delete_many({"officine_id": {"$in": ids}})
    if contact_ids:
        db.directory_contacts.delete_many({"id": {"$in": contact_ids}})
    if group_ids:
        db.contact_groups.delete_many({"id": {"$in": group_ids}})


# ============================================================================
# CSV IMPORT
# ============================================================================
class TestCsvImport:
    def test_400_missing_file(self, admin_ctx):
        r = requests.post(f"{API}/admin/officines-registry/import-csv",
                          headers=admin_ctx["headers"])
        assert r.status_code == 400, r.text

    def test_400_invalid_headers(self, admin_ctx, cleanup):
        """Iter43-fix9a — En-tête optionnelle. Si la 1ère ligne ne ressemble
        pas à un en-tête, elle est traitée comme une ligne de données. Donc
        ici la ligne 'Foo;Bar;Baz;Qux;Quux' devient une officine valide (nom=Foo)
        et 'A;B;C;D;E' devient une 2nde officine (nom=A)."""
        csv = "Foo;Bar;Baz;Qux;Quux\nA;B;C;D;E\n".encode("utf-8")
        r = requests.post(
            f"{API}/admin/officines-registry/import-csv",
            headers=admin_ctx["headers"],
            files={"file": ("nohdr.csv", csv, "text/csv")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["header_detected"] is False
        assert body["created"] == 2
        # Cleanup : les 2 officines créées
        from pymongo import MongoClient
        import os
        sync = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        sync.officines.delete_many({"name": {"$in": ["Foo", "A"]}})
        ids = [d["officine_id"] for d in (body.get("results") or []) if d.get("officine_id")]
        if ids:
            sync.officine_audit_log.delete_many({"officine_id": {"$in": ids}})

    def test_400_invalid_encoding(self, admin_ctx):
        # Bytes invalides à la fois pour utf-8 et latin-1: latin-1 décode tout en fait
        # → on simule par un body décodable mais avec headers invalides.
        # Le code accepte latin-1 fallback ; on teste la chaîne d'erreurs d'en-tête déjà couverte.
        # Ici on envoie en latin-1 avec accents → doit passer (utf-8-sig fail, latin-1 OK).
        header = "Nom de la pharmacie;Téléphone;Ville;Indications de localisation;Numéro d'ordre\n"
        raw = header.encode("latin-1") + b"Test Phcie;+22501020304;Abidjan;Plateau;NO-123\n"
        r = requests.post(
            f"{API}/admin/officines-registry/import-csv",
            headers=admin_ctx["headers"],
            files={"file": ("ok.csv", raw, "text/csv")},
        )
        assert r.status_code == 200, r.text

    def test_import_valid_rows_and_skip_dup_and_empty(self, db, admin_ctx, cleanup):
        # Pré-insertion d'un doublon par phone_digits
        existing_id = f"iter43f9_off_{uuid.uuid4().hex[:8]}"
        cleanup["ids"].append(existing_id)
        db.officines.insert_one({
            "id": existing_id,
            "name": "Pharmacie Dupliquée Existante",
            "phone_digits": "22501020304",
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        uniq = uuid.uuid4().hex[:6]
        csv = (
            "Nom de la pharmacie;Téléphone;Ville;Indications de localisation;Numéro d'ordre\n"
            f"Pharmacie Valide {uniq};+225 06 07 08 09 10;Abidjan;Près de la mairie;ORD-{uniq}\n"
            ";;;;\n"  # ligne vide → skip
            "Pharmacie Doublon;+225 01 02 03 04;Cocody;Indication;ORD-DUP\n"  # doublon phone
        ).encode("utf-8-sig")

        r = requests.post(
            f"{API}/admin/officines-registry/import-csv",
            headers=admin_ctx["headers"],
            files={"file": ("ok.csv", csv, "text/csv")},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["created"] == 1
        assert data["skipped"] == 1  # ligne vide ignorée silencieusement, doublon compté
        # Vérifie qu'une officine 'pending' avec name=code et created_via='csv_import' a été créée
        created = data["results"]
        new_entry = next(x for x in created if not x.get("skipped"))
        new_id = new_entry["officine_id"]
        cleanup["ids"].append(new_id)
        doc = db.officines.find_one({"id": new_id}, {"_id": 0})
        assert doc["name"] == f"Pharmacie Valide {uniq}"
        assert doc["code"] == doc["name"]
        assert doc["status"] == "pending"
        assert doc["created_via"] == "csv_import"
        assert doc["city"] == "Abidjan"
        assert doc["location_hint"] == "Près de la mairie"
        assert doc["numero_ordre"] == f"ORD-{uniq}"

    def test_import_user_file_no_header_with_spaces_in_phone(self, db, admin_ctx, cleanup):
        """Iter43-fix9a — Reproduit le fichier utilisateur réel :
        - pas de ligne d'en-tête
        - téléphones avec espaces : `+226 79 20 01 83`
        - cellule 'Indications de localisation' éventuellement vide
        """
        uniq = uuid.uuid4().hex[:6]
        csv_text = (
            f"Archanges {uniq};+226 79 20 01 83;Ouagadougou;"
            "Pissy Face station OTAM Croisement rue 17.619 Boassa cote Ecole Adventiste Elysee.;1\n"
            f"Baani {uniq};+226 77 52 00 36;Ouagadougou;;2\n"
            f"Avenir {uniq};+226 25 65 10 71;Ouagadougou;"
            "1296 av. BABANGUIDA face station Total;3\n"
        )
        r = requests.post(
            f"{API}/admin/officines-registry/import-csv",
            headers=admin_ctx["headers"],
            files={"file": ("user_file.csv", csv_text.encode("utf-8"), "text/csv")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["header_detected"] is False
        assert body["created"] == 3
        # Vérifie qu'on retrouve bien Archanges avec téléphone normalisé
        archanges = db.officines.find_one({"name": f"Archanges {uniq}"}, {"_id": 0})
        assert archanges is not None
        cleanup["ids"].extend([
            archanges["id"],
            db.officines.find_one({"name": f"Baani {uniq}"})["id"],
            db.officines.find_one({"name": f"Avenir {uniq}"})["id"],
        ])
        # Espaces retirés des digits
        assert archanges["phone_digits"] == "22679200183"
        assert archanges["phone"] == "+22679200183"
        assert archanges["city"] == "Ouagadougou"
        assert archanges["numero_ordre"] == "1"
        # Indications vide doit donner None
        baani = db.officines.find_one({"name": f"Baani {uniq}"}, {"_id": 0})
        assert baani["location_hint"] is None


# ============================================================================
# PUT EDIT
# ============================================================================
class TestUpdateOfficine:
    def test_404_unknown(self, admin_ctx):
        r = requests.put(
            f"{API}/admin/officines-registry/nonexistent_iter43f9",
            headers={**admin_ctx["headers"], "Content-Type": "application/json"},
            json={"name": "X"},
        )
        assert r.status_code == 404

    def test_400_bad_lat(self, db, admin_ctx, cleanup):
        oid = f"iter43f9_off_{uuid.uuid4().hex[:8]}"
        cleanup["ids"].append(oid)
        db.officines.insert_one({"id": oid, "name": "T", "status": "pending",
                                  "created_at": datetime.now(timezone.utc).isoformat()})
        r = requests.put(
            f"{API}/admin/officines-registry/{oid}",
            headers=admin_ctx["headers"],
            json={"latitude": "not-a-number"},
        )
        assert r.status_code == 400

    def test_400_no_valid_field(self, db, admin_ctx, cleanup):
        oid = f"iter43f9_off_{uuid.uuid4().hex[:8]}"
        cleanup["ids"].append(oid)
        db.officines.insert_one({"id": oid, "name": "T", "status": "pending",
                                  "created_at": datetime.now(timezone.utc).isoformat()})
        r = requests.put(
            f"{API}/admin/officines-registry/{oid}",
            headers=admin_ctx["headers"],
            json={"foo_bar_unknown": "x"},
        )
        assert r.status_code == 400

    def test_full_update_persists(self, db, admin_ctx, cleanup):
        oid = f"iter43f9_off_{uuid.uuid4().hex[:8]}"
        cleanup["ids"].append(oid)
        db.officines.insert_one({"id": oid, "name": "Old", "code": "Old", "status": "pending",
                                  "created_at": datetime.now(timezone.utc).isoformat()})
        payload = {
            "name": "Pharmacie Centrale",
            "intitule": "Pharmacie Centrale SARL",
            "email": "centrale@ph.ci",
            "phone": "+225 01 02 03 04 05",
            "whatsapp": "+225 06 07 08 09 10",
            "address": "BP 100",
            "city": "Abidjan",
            "country": "CI",
            "location_hint": "Face mairie",
            "numero_ordre": "ORD-9999",
            "contact_name": "M. Diallo",
            "logo_url": "",  # → null
            "latitude": "5.345",
            "longitude": -4.012,
        }
        r = requests.put(
            f"{API}/admin/officines-registry/{oid}",
            headers=admin_ctx["headers"],
            json=payload,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        off = body["officine"]
        assert off["name"] == "Pharmacie Centrale"
        assert off["code"] == "Pharmacie Centrale"  # synced
        assert off["intitule"] == "Pharmacie Centrale SARL"
        assert off["logo_url"] is None  # '' → null
        assert off["phone_digits"] == "2250102030405"
        assert off["whatsapp_digits"] == "2250607080910"
        assert isinstance(off["latitude"], float) and abs(off["latitude"] - 5.345) < 1e-6
        assert isinstance(off["longitude"], float) and abs(off["longitude"] + 4.012) < 1e-6
        assert off.get("updated_at")
        assert off.get("updated_by") == admin_ctx["email"]
        # Audit log
        n = db.officine_audit_log.count_documents({"officine_id": oid, "action": "edit"})
        assert n >= 1


# ============================================================================
# UPLOAD LOGO
# ============================================================================
class TestUploadLogo:
    def test_404_unknown(self, admin_ctx):
        r = requests.post(
            f"{API}/admin/officines-registry/nope_iter43f9/upload-logo",
            headers=admin_ctx["headers"],
            files={"file": ("logo.png", b"\x89PNG\r\n\x1a\n" + b"x" * 100, "image/png")},
        )
        assert r.status_code == 404

    def test_400_missing_file(self, db, admin_ctx, cleanup):
        oid = f"iter43f9_off_{uuid.uuid4().hex[:8]}"
        cleanup["ids"].append(oid)
        db.officines.insert_one({"id": oid, "name": "T", "status": "pending",
                                  "created_at": datetime.now(timezone.utc).isoformat()})
        r = requests.post(
            f"{API}/admin/officines-registry/{oid}/upload-logo",
            headers=admin_ctx["headers"],
        )
        assert r.status_code == 400

    def test_413_too_large(self, db, admin_ctx, cleanup):
        oid = f"iter43f9_off_{uuid.uuid4().hex[:8]}"
        cleanup["ids"].append(oid)
        db.officines.insert_one({"id": oid, "name": "T", "status": "pending",
                                  "created_at": datetime.now(timezone.utc).isoformat()})
        big = b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024 + 10)
        r = requests.post(
            f"{API}/admin/officines-registry/{oid}/upload-logo",
            headers=admin_ctx["headers"],
            files={"file": ("big.png", big, "image/png")},
        )
        assert r.status_code == 413

    def test_400_bad_ext(self, db, admin_ctx, cleanup):
        oid = f"iter43f9_off_{uuid.uuid4().hex[:8]}"
        cleanup["ids"].append(oid)
        db.officines.insert_one({"id": oid, "name": "T", "status": "pending",
                                  "created_at": datetime.now(timezone.utc).isoformat()})
        r = requests.post(
            f"{API}/admin/officines-registry/{oid}/upload-logo",
            headers=admin_ctx["headers"],
            files={"file": ("logo.exe", b"MZ" + b"x" * 50, "application/octet-stream")},
        )
        assert r.status_code == 400

    def test_upload_ok_updates_logo_url_and_audit(self, db, admin_ctx, cleanup):
        oid = f"iter43f9_off_{uuid.uuid4().hex[:8]}"
        cleanup["ids"].append(oid)
        db.officines.insert_one({"id": oid, "name": "T", "status": "pending",
                                  "created_at": datetime.now(timezone.utc).isoformat()})
        payload = b"\x89PNG\r\n\x1a\n" + b"y" * 200
        r = requests.post(
            f"{API}/admin/officines-registry/{oid}/upload-logo",
            headers=admin_ctx["headers"],
            files={"file": ("logo.png", payload, "image/png")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["logo_url"].startswith("/officines-registry/") and body["logo_url"].endswith("/logo")
        # Le fichier .png est stocké sur disque, vérifiable via logo_path en DB
        doc = db.officines.find_one({"id": oid})
        assert doc["logo_url"] == body["logo_url"]
        assert doc.get("logo_ext") == "png"
        assert doc.get("logo_path", "").endswith(".png")
        assert db.officine_audit_log.count_documents(
            {"officine_id": oid, "action": "upload_logo"}) >= 1

    def test_get_logo_public_no_auth(self, db):
        """Iter43-fix10b — Le logo est servi via endpoint PUBLIC (pas d'auth)."""
        oid = f"iter43f10b_off_{uuid.uuid4().hex[:8]}"
        # Crée fichier sur disque
        from pathlib import Path as _P
        upload_dir = _P(os.environ.get("UPLOAD_DIR", "/app/backend/uploads")) / "officines"
        upload_dir.mkdir(parents=True, exist_ok=True)
        fpath = upload_dir / f"officine_{oid[:8]}_test.png"
        # PNG minimal valide
        fpath.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
        try:
            db.officines.insert_one({
                "id": oid, "name": "TestLogoPublic", "code": "TestLogoPublic",
                "status": "pending", "logo_path": str(fpath), "logo_ext": "png",
                "logo_url": f"/officines-registry/{oid}/logo",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            # Pas de headers Authorization
            r = requests.get(f"{API}/officines-registry/{oid}/logo")
            assert r.status_code == 200, r.text
            assert r.headers["content-type"] == "image/png"
            assert r.content.startswith(b"\x89PNG")
        finally:
            db.officines.delete_one({"id": oid})
            if fpath.exists():
                fpath.unlink()

    def test_get_logo_404_unknown(self):
        r = requests.get(f"{API}/officines-registry/unknown_iter43f10b/logo")
        assert r.status_code == 404

    def test_get_logo_404_no_file(self, db):
        oid = f"iter43f10b_off_{uuid.uuid4().hex[:8]}"
        try:
            db.officines.insert_one({
                "id": oid, "name": "NoFile", "status": "pending",
                "logo_path": "/nonexistent/x.png", "logo_ext": "png",
                "logo_url": f"/officines-registry/{oid}/logo",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            r = requests.get(f"{API}/officines-registry/{oid}/logo")
            assert r.status_code == 404
        finally:
            db.officines.delete_one({"id": oid})


# ============================================================================
# IMPORT TO CONTACTS
# ============================================================================
class TestImportToContacts:
    def test_400_empty_list(self, admin_ctx):
        r = requests.post(
            f"{API}/admin/officines-registry/import-to-contacts",
            headers=admin_ctx["headers"],
            json={"officine_ids": []},
        )
        assert r.status_code == 400

    def test_404_no_officines_found(self, admin_ctx):
        r = requests.post(
            f"{API}/admin/officines-registry/import-to-contacts",
            headers=admin_ctx["headers"],
            json={"officine_ids": ["does_not_exist_iter43f9_xxx"]},
        )
        assert r.status_code == 404

    def test_create_group_and_contacts(self, db, admin_ctx, cleanup):
        oid = f"iter43f9_off_{uuid.uuid4().hex[:8]}"
        cleanup["ids"].append(oid)
        db.officines.insert_one({
            "id": oid, "name": f"Phcie Import {uuid.uuid4().hex[:6]}",
            "code": "code-x", "intitule": "Intitulé X",
            "phone": "+22501020304", "phone_digits": "22501020304",
            "city": "Abidjan", "numero_ordre": "ORD-77",
            "logo_url": "/uploads/officines/x.png",
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        # 1er appel : créé groupe + contact
        r = requests.post(
            f"{API}/admin/officines-registry/import-to-contacts",
            headers=admin_ctx["headers"],
            json={"officine_ids": [oid], "group_name": f"TEST_Officines_{uuid.uuid4().hex[:6]}"},
        )
        assert r.status_code == 200, r.text
        d1 = r.json()
        assert d1["ok"] is True
        assert d1["created"] == 1
        assert d1["already_existing"] == 0
        assert d1["total_in_group"] == 1
        cleanup["group_ids"].append(d1["group_id"])

        # Vérifie le contact
        contacts = list(db.directory_contacts.find({"officine_id": oid}))
        assert len(contacts) == 1
        c = contacts[0]
        cleanup["contact_ids"].append(c["id"])
        assert "Officine" in (c.get("tags") or [])
        assert c.get("photo_url") == "/uploads/officines/x.png"
        assert "ORD-77" in (c.get("notes") or "")
        assert "Abidjan" in (c.get("notes") or "")

        # 2e appel : dédoublonné
        r2 = requests.post(
            f"{API}/admin/officines-registry/import-to-contacts",
            headers=admin_ctx["headers"],
            json={"officine_ids": [oid], "group_name": d1["group_name"]},
        )
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["created"] == 0
        assert d2["already_existing"] == 1
        assert d2["group_id"] == d1["group_id"]


# ============================================================================
# APPROVE → activated_at
# ============================================================================
class TestApproveActivatedAt:
    def test_approve_sets_activated_fields(self, db, admin_ctx, cleanup):
        oid = f"iter43f9_off_{uuid.uuid4().hex[:8]}"
        cleanup["ids"].append(oid)
        db.officines.insert_one({
            "id": oid, "name": "AppvTest", "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        r = requests.post(
            f"{API}/admin/officines-registry/{oid}/approve",
            headers=admin_ctx["headers"],
        )
        assert r.status_code == 200, r.text
        doc = db.officines.find_one({"id": oid})
        assert doc["status"] == "active"
        # nouveaux champs
        assert doc.get("activated_at")
        assert doc.get("activated_by") == admin_ctx["email"]
        assert doc.get("activated_via") == "admin"
        # rétro-compat conservée
        assert doc.get("validated_at")
        assert doc.get("validated_by") == admin_ctx["email"]
