"""Iter43-fix24n (2026-06) — Tests pour la délégation menu Officines."""
import os
import uuid

import httpx
import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

API_BASE = os.environ.get("API_BASE", "http://localhost:8001/api")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "sawali_db")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@sawalismartsystems.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@Sawali2026")


@pytest_asyncio.fixture
async def db():
    c = AsyncIOMotorClient(MONGO_URL)
    database = c[DB_NAME]
    # backup pre-test allowed list
    s_orig = await database.settings.find_one({"_id": "global"}) or {}
    orig_list = s_orig.get("officines_menu_allowed_emails", [])
    yield database, orig_list
    # restore
    await database.settings.update_one(
        {"_id": "global"},
        {"$set": {"officines_menu_allowed_emails": orig_list}},
    )
    # cleanup test officine + user (both prefixes)
    await database.officines.delete_many({"id": {"$regex": "^test-fix24n-"}})
    await database.officines.delete_many({"name": {"$regex": "^NEW-FIX24N-"}})
    await database.users.delete_many({"email": {"$regex": "^delegated-pytest-"}})
    c.close()


def _admin_token():
    with httpx.Client(timeout=15) as client:
        r1 = client.post(
            f"{API_BASE}/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        data1 = r1.json()
        if not data1.get("needs_otp"):
            return data1.get("access_token") or data1.get("token")
        r2 = client.post(
            f"{API_BASE}/auth/verify-otp",
            json={"session_token": data1["session_token"], "code": data1["dev_otp"]},
        )
        return r2.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token():
    return _admin_token()


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


async def _create_delegated_user(db_async, email, password="Delegated@2026"):
    """Crée un utilisateur 'client' (rôle non-admin) pour les tests."""
    import bcrypt
    pwd_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()
    user_doc = {
        "id": uuid.uuid4().hex,
        "email": email,
        "password_hash": pwd_hash,
        "role": "client",
        "status": "active",
        "account_status": "active",  # requis par get_current_user (auth.py:70)
        "name": "Delegated Tester",
    }
    await db_async.users.insert_one(user_doc)
    return user_doc


def _login_user(email, password, user_id=None):
    """Bypasse le flow OTP : génère directement un JWT pour le test."""
    import jwt
    from auth import JWT_SECRET, JWT_ALGORITHM
    import time
    if user_id is None:
        # fetch from DB
        from pymongo import MongoClient
        c = MongoClient(MONGO_URL)
        doc = c[DB_NAME].users.find_one({"email": email})
        user_id = doc["id"]
        c.close()
    payload = {
        "sub": user_id,
        "role": "client",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


@pytest.mark.asyncio
async def test_admin_has_full_edit_mode(db, admin_headers):
    database, _ = db
    with httpx.Client(timeout=15) as client:
        r = client.get(f"{API_BASE}/me/officines-permissions", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["can_view"] is True
    assert data["edit_mode"] == "full"
    assert data["editable_fields"] == "all"


@pytest.mark.asyncio
async def test_non_admin_not_in_list_gets_403(db):
    database, _ = db
    email = f"delegated-pytest-{uuid.uuid4().hex[:8]}@test.com"
    pwd = "Delegated@2026"
    await _create_delegated_user(database, email, pwd)
    # Ensure email is NOT in the allowed list
    await database.settings.update_one(
        {"_id": "global"},
        {"$set": {"officines_menu_allowed_emails": []}},
    )
    token = _login_user(email, pwd)
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=15) as client:
        r1 = client.get(f"{API_BASE}/me/officines-permissions", headers=headers)
    assert r1.status_code == 200
    assert r1.json()["can_view"] is False

    # Endpoint list_registry should reject with 403
    with httpx.Client(timeout=15) as client:
        r2 = client.get(f"{API_BASE}/admin/officines-registry", headers=headers)
    assert r2.status_code == 403


@pytest.mark.asyncio
async def test_delegated_user_has_limited_mode(db):
    database, _ = db
    email = f"delegated-pytest-{uuid.uuid4().hex[:8]}@test.com"
    pwd = "Delegated@2026"
    await _create_delegated_user(database, email, pwd)
    # Add email to allowed list
    await database.settings.update_one(
        {"_id": "global"},
        {"$set": {"officines_menu_allowed_emails": [email]}},
        upsert=True,
    )
    token = _login_user(email, pwd)
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=15) as client:
        r = client.get(f"{API_BASE}/me/officines-permissions", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["can_view"] is True
    assert data["edit_mode"] == "limited"
    assert set(data["editable_fields"]) == {
        "intitule", "phone", "whatsapp", "latitude", "longitude",
        "location_hint", "activite_principale",
        # Iter43-fix24v additions
        "email", "contact_name", "groupe_garde",
    }


@pytest.mark.asyncio
async def test_delegated_user_can_list_officines(db):
    database, _ = db
    email = f"delegated-pytest-{uuid.uuid4().hex[:8]}@test.com"
    pwd = "Delegated@2026"
    await _create_delegated_user(database, email, pwd)
    await database.settings.update_one(
        {"_id": "global"},
        {"$set": {"officines_menu_allowed_emails": [email]}},
        upsert=True,
    )
    token = _login_user(email, pwd)
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=15) as client:
        r = client.get(f"{API_BASE}/admin/officines-registry?limit=5", headers=headers)
    assert r.status_code == 200
    assert "items" in r.json()


@pytest.mark.asyncio
async def test_delegated_user_can_only_edit_allowed_fields(db):
    """Cœur du fix : un utilisateur délégué ne peut PAS modifier name,
    address, city, country, numero_ordre, role.
    Iter43-fix24v : email, contact_name, groupe_garde sont maintenant ALLOWED."""
    database, _ = db
    email = f"delegated-pytest-{uuid.uuid4().hex[:8]}@test.com"
    pwd = "Delegated@2026"
    await _create_delegated_user(database, email, pwd)
    await database.settings.update_one(
        {"_id": "global"},
        {"$set": {"officines_menu_allowed_emails": [email]}},
        upsert=True,
    )
    # Create test officine via admin
    test_id = f"test-fix24n-{uuid.uuid4().hex[:8]}"
    original = {
        "id": test_id, "name": "ORIGINAL_NAME", "code": "ORIGINAL_NAME",
        "intitule": "Original Intitule", "phone": "+22500001111",
        "whatsapp": "+22500002222", "email": "original@test.com",
        "address": "Original Address", "city": "Original City",
        "country": "Original Country", "numero_ordre": "999",
        "contact_name": "Original Contact", "groupe_garde": 1,
        "status": "active", "role": None,
    }
    await database.officines.insert_one(original)

    token = _login_user(email, pwd)
    headers = {"Authorization": f"Bearer {token}"}
    # Try to update ALL fields — only allowed should stick
    payload = {
        "name": "HACKED_NAME",           # forbidden
        "intitule": "New Intitule",       # ALLOWED
        "phone": "+22600003333",          # ALLOWED
        "whatsapp": "+22600004444",       # ALLOWED
        "email": "new@test.com",          # ALLOWED (fix24v)
        "contact_name": "New Contact",    # ALLOWED (fix24v)
        "groupe_garde": 3,                # ALLOWED (fix24v)
        "address": "Hacked Address",      # forbidden
        "city": "Hacked City",            # forbidden
        "country": "Hacked Country",      # forbidden
        "numero_ordre": "666",            # forbidden
        "latitude": 12.345678,            # ALLOWED
        "longitude": -1.234567,           # ALLOWED
        "location_hint": "Près du marché",  # ALLOWED
        "activite_principale": "Pharmacie d'officine",  # ALLOWED
        "role": "directeur",              # forbidden
    }
    with httpx.Client(timeout=15) as client:
        r = client.put(
            f"{API_BASE}/admin/officines-registry/{test_id}",
            json=payload, headers=headers,
        )
    assert r.status_code == 200, r.text
    # Verify in DB
    fresh = await database.officines.find_one({"id": test_id})
    # ALLOWED fields → changed
    assert fresh["intitule"] == "New Intitule"
    assert fresh["phone"] == "+22600003333"
    assert fresh["whatsapp"] == "+22600004444"
    assert fresh["latitude"] == 12.345678
    assert fresh["longitude"] == -1.234567
    assert fresh["location_hint"] == "Près du marché"
    assert fresh["activite_principale"] == "Pharmacie d'officine"
    # Iter43-fix24v — these are now editable by delegated users
    assert fresh["email"] == "new@test.com"
    assert fresh["contact_name"] == "New Contact"
    assert fresh["groupe_garde"] == 3
    # FORBIDDEN fields → UNCHANGED
    assert fresh["name"] == "ORIGINAL_NAME"
    assert fresh["address"] == "Original Address"
    assert fresh["city"] == "Original City"
    assert fresh["country"] == "Original Country"
    assert fresh["numero_ordre"] == "999"
    assert fresh.get("role") is None


@pytest.mark.asyncio
async def test_intitule_auto_computed_when_empty(db, admin_headers):
    """Iter43-fix24v : si intitule est vide et name + role sont renseignés,
    intitule = '{role} {name}' automatiquement à l'update."""
    database, _ = db
    test_id = f"test-fix24n-{uuid.uuid4().hex[:8]}"
    # Seed a role in settings if missing
    await database.settings.update_one(
        {"_id": "global"},
        {"$addToSet": {"officine_roles": "Pharmacie"}},
        upsert=True,
    )
    await database.officines.insert_one({
        "id": test_id, "name": "BELLEVUE", "code": "BELLEVUE",
        "intitule": None, "role": None,
        "status": "active",
    })
    with httpx.Client(timeout=15) as client:
        # Step 1: set role only, leave intitule empty
        r = client.put(
            f"{API_BASE}/admin/officines-registry/{test_id}",
            json={"role": "Pharmacie", "intitule": ""}, headers=admin_headers,
        )
    assert r.status_code == 200, r.text
    fresh = await database.officines.find_one({"id": test_id})
    # Expected: intitule auto-computed = "Pharmacie BELLEVUE"
    assert fresh["intitule"] == "Pharmacie BELLEVUE", fresh


@pytest.mark.asyncio
async def test_intitule_not_overwritten_when_provided(db, admin_headers):
    """Iter43-fix24v : si intitule est explicitement renseigné, on respecte
    la valeur — pas d'écrasement automatique."""
    database, _ = db
    test_id = f"test-fix24n-{uuid.uuid4().hex[:8]}"
    await database.settings.update_one(
        {"_id": "global"},
        {"$addToSet": {"officine_roles": "Pharmacie"}},
        upsert=True,
    )
    await database.officines.insert_one({
        "id": test_id, "name": "BELLEVUE", "code": "BELLEVUE",
        "intitule": None, "role": None,
        "status": "active",
    })
    with httpx.Client(timeout=15) as client:
        r = client.put(
            f"{API_BASE}/admin/officines-registry/{test_id}",
            json={"role": "Pharmacie", "intitule": "Mon Libellé Commercial"},
            headers=admin_headers,
        )
    assert r.status_code == 200, r.text
    fresh = await database.officines.find_one({"id": test_id})
    assert fresh["intitule"] == "Mon Libellé Commercial"


@pytest.mark.asyncio
async def test_admin_can_edit_all_fields(db, admin_headers):
    """Sanity : un admin reste capable de modifier TOUS les champs."""
    database, _ = db
    test_id = f"test-fix24n-{uuid.uuid4().hex[:8]}"
    await database.officines.insert_one({
        "id": test_id, "name": "ADMIN_TEST", "code": "ADMIN_TEST",
        "status": "active",
    })
    payload = {
        "name": "ADMIN_RENAMED",
        "intitule": "New Intitule",
        "email": "newemail@test.com",
        "address": "New Address",
        "city": "New City",
        "phone": "+22611112222",
    }
    with httpx.Client(timeout=15) as client:
        r = client.put(
            f"{API_BASE}/admin/officines-registry/{test_id}",
            json=payload, headers=admin_headers,
        )
    assert r.status_code == 200
    fresh = await database.officines.find_one({"id": test_id})
    # Admin → tous les champs modifiés
    assert fresh["name"] == "ADMIN_RENAMED"
    assert fresh["intitule"] == "New Intitule"
    assert fresh["email"] == "newemail@test.com"
    assert fresh["address"] == "New Address"
    assert fresh["city"] == "New City"
    assert fresh["phone"] == "+22611112222"


@pytest.mark.asyncio
async def test_delegated_user_can_create_officine_with_all_fields(db):
    """Cas spécial : à la CRÉATION, tous les champs sont éditables par un délégué."""
    database, _ = db
    email = f"delegated-pytest-{uuid.uuid4().hex[:8]}@test.com"
    pwd = "Delegated@2026"
    await _create_delegated_user(database, email, pwd)
    await database.settings.update_one(
        {"_id": "global"},
        {"$set": {"officines_menu_allowed_emails": [email]}},
        upsert=True,
    )
    token = _login_user(email, pwd)
    headers = {"Authorization": f"Bearer {token}"}
    new_name = f"NEW-FIX24N-{uuid.uuid4().hex[:8]}"
    payload = {
        "name": new_name,
        "intitule": "Nouvelle Officine",
        "email": "new@officine.com",
        "phone": "+22655556666",
        "whatsapp": "+22677778888",
        "address": "Nouvelle Adresse",
        "city": "Ouaga",
        "country": "Burkina Faso",
        "latitude": 12.371,
        "longitude": -1.519,
    }
    with httpx.Client(timeout=15) as client:
        r = client.post(
            f"{API_BASE}/admin/officines-registry",
            json=payload, headers=headers,
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("officine", {}).get("name") == new_name
    assert body["officine"]["email"] == "new@officine.com"  # le délégué peut SET email à la création
    assert body["officine"]["address"] == "Nouvelle Adresse"
