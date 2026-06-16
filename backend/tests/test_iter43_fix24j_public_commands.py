"""Iter43-fix24j (2026-06) — Tests pour les 3 nouvelles commandes WhatsApp publiques :
`!adresse` (avec géolocalisation type=location), `!horaires`, `!stock <médic>`."""
import os
import uuid

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from routes import liluvine_wa_autoreply as autoreply  # noqa: E402

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "sawali_db")


class _FakeSend:
    def __init__(self):
        self.calls = []
        self.next_response = {"ok": True, "message_id": "wamid.test"}

    async def __call__(self, to, text, **kw):
        self.calls.append({"to": to, "text": text, **kw})
        return self.next_response


@pytest_asyncio.fixture
async def db():
    c = AsyncIOMotorClient(MONGO_URL)
    database = c[DB_NAME]
    # Backup brand fields
    orig = await database.settings.find_one({"_id": "global"}) or {}
    backup = {k: orig.get(k) for k in orig if k.startswith("liluvine_wa_brand_") or k == "liluvine_wa_unknown_cmd_reply"}
    # cleanup test inventory + officines if any
    await database.officine_inventory_items.delete_many({"officine_id": "test-off-1"})
    await database.officines.delete_many({"id": "test-off-1"})
    await database.whatsapp_messages.delete_many({"command": {"$in": ["!adresse", "!horaires", "!stock"]}})
    await database.liluvine_exclamations.delete_many({"phone_digits": "33600000099"})
    yield database, backup
    # restore brand settings
    await database.settings.update_one({"_id": "global"}, {"$set": backup})
    # cleanup test inventory
    await database.officine_inventory_items.delete_many({"officine_id": "test-off-1"})
    await database.officines.delete_many({"id": "test-off-1"})
    await database.whatsapp_messages.delete_many({"command": {"$in": ["!adresse", "!horaires", "!stock"]}})
    await database.liluvine_exclamations.delete_many({"phone_digits": "33600000099"})
    c.close()


def _inbound(text):
    return {
        "id": "test-inbound-id",
        "from": "+33600000099",
        "phone_digits": "33600000099",
        "body": text,
        "wa_message_id": "wamid.test-in-1",
        "client_id": "test-uid",
        "message_type": "text",
        "from_profile_name": "Testeur",
    }


def _settings(**overrides):
    base = {
        "liluvine_wa_autoreply_enabled": False,  # off : confirme que les `!` marchent quand même
        "liluvine_wa_autoreply_allow_mode": "any",
        "liluvine_wa_autoreply_schedule": "always",
        "liluvine_wa_autoreply_keywords": [],
        "liluvine_wa_autoreply_cooldown_seconds": 0,
        "liluvine_wa_autoreply_signature": "🤖 Liluvine",
    }
    base.update(overrides)
    return base


class TestAdresseCommand:
    @pytest.mark.asyncio
    async def test_adresse_with_brand_configured(self, db):
        database, _ = db
        await database.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "liluvine_wa_brand_name": "SAWALI HQ",
                "liluvine_wa_brand_phone": "+22501234567",
                "liluvine_wa_brand_whatsapp": "+22507654321",
                "liluvine_wa_brand_address": "12 Avenue Houphouët",
                "liluvine_wa_brand_city": "Abidjan",
                "liluvine_wa_brand_country": "Côte d'Ivoire",
                "liluvine_wa_brand_location_hint": "À côté de la station Total",
                "liluvine_wa_brand_latitude": 5.3097,
                "liluvine_wa_brand_longitude": -4.0177,
            }},
            upsert=True,
        )
        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            database,
            inbound_doc=_inbound("!adresse"),
            contact=None,
            settings_doc=_settings(),
            wa_send_text=sender,
        )
        assert res["ok"] is True, res
        assert res["command"] == "!adresse"
        assert len(sender.calls) == 1
        body = sender.calls[0]["text"]
        assert "SAWALI HQ" in body
        assert "+22501234567" in body
        assert "+22507654321" in body
        assert "Abidjan" in body
        assert "À côté de la station Total" in body
        # Lien Google Maps avec les coords
        assert "google.com/maps?q=5.3097" in body or "google.com/maps" in body

    @pytest.mark.asyncio
    async def test_adresse_with_no_brand_uses_defaults(self, db):
        """Sans aucune config brand, doit renvoyer le nom 'SAWALI SMART SYSTEMS' + texte minimal."""
        database, _ = db
        # Wipe brand fields
        await database.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "liluvine_wa_brand_name": "",
                "liluvine_wa_brand_phone": "",
                "liluvine_wa_brand_whatsapp": "",
                "liluvine_wa_brand_address": "",
                "liluvine_wa_brand_city": "",
                "liluvine_wa_brand_country": "",
                "liluvine_wa_brand_location_hint": "",
                "liluvine_wa_brand_latitude": None,
                "liluvine_wa_brand_longitude": None,
                "liluvine_wa_brand_hours": "",
                "liluvine_wa_brand_maps_url": "",
                "company_phone": "",
                "public_brand_name": "",
            }},
        )
        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            database,
            inbound_doc=_inbound("!adresse"),
            contact=None,
            settings_doc=_settings(),
            wa_send_text=sender,
        )
        assert res["ok"] is True
        body = sender.calls[0]["text"]
        assert "SAWALI SMART SYSTEMS" in body

    @pytest.mark.asyncio
    async def test_contact_alias_works(self, db):
        """`!contact` doit fonctionner comme alias de `!adresse`."""
        database, _ = db
        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            database,
            inbound_doc=_inbound("!contact"),
            contact=None,
            settings_doc=_settings(),
            wa_send_text=sender,
        )
        assert res["ok"] is True
        assert res["command"] == "!adresse"


class TestHorairesCommand:
    @pytest.mark.asyncio
    async def test_horaires_with_hours_configured(self, db):
        database, _ = db
        await database.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "liluvine_wa_brand_name": "Pharmacie SAWALI",
                "liluvine_wa_brand_hours": (
                    "Lundi : 08h00 - 19h30\n"
                    "Mardi : 08h00 - 19h30\n"
                    "Mercredi : 08h00 - 19h30\n"
                    "Jeudi : 08h00 - 19h30\n"
                    "Vendredi : 08h00 - 19h30\n"
                    "Samedi : 09h00 - 13h00\n"
                    "Dimanche : Fermé"
                ),
            }},
        )
        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            database,
            inbound_doc=_inbound("!horaires"),
            contact=None,
            settings_doc=_settings(),
            wa_send_text=sender,
        )
        assert res["ok"] is True
        body = sender.calls[0]["text"]
        assert "Pharmacie SAWALI" in body
        assert "Lundi" in body
        assert "Dimanche" in body
        # Le marqueur "aujourd'hui" doit apparaître quelque part
        assert "aujourd'hui" in body or "Nous sommes" in body

    @pytest.mark.asyncio
    async def test_horaire_singular_also_works(self, db):
        database, _ = db
        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            database,
            inbound_doc=_inbound("!horaire"),
            contact=None,
            settings_doc=_settings(),
            wa_send_text=sender,
        )
        assert res["ok"] is True
        assert res["command"] == "!horaires"

    @pytest.mark.asyncio
    async def test_horaires_without_config_returns_friendly_message(self, db):
        database, _ = db
        await database.settings.update_one(
            {"_id": "global"},
            {"$set": {"liluvine_wa_brand_hours": ""}},
        )
        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            database,
            inbound_doc=_inbound("!horaires"),
            contact=None,
            settings_doc=_settings(),
            wa_send_text=sender,
        )
        assert res["ok"] is True
        body = sender.calls[0]["text"]
        assert "non" in body.lower() or "pas encore" in body or "Contactez" in body


class TestStockCommand:
    @pytest.mark.asyncio
    async def test_stock_finds_product(self, db):
        database, _ = db
        # Seed officine + 2 stock items with UNIQUE test product names
        await database.officines.insert_one({
            "id": "test-off-1",
            "name": "Pharmacie du Test",
            "phone": "+22500111222",
            "whatsapp": "+22500111222",
            "city": "Abidjan",
            "location_hint": "Près de la mairie",
            "status": "active",
        })
        await database.officine_inventory_items.insert_many([
            {
                "id": uuid.uuid4().hex,
                "officine_id": "test-off-1",
                "product_name": "ZyloxTestSAWALI 500 mg",
                "quantity": 42, "unit_price": 250, "currency": "XOF",
                "available": True,
            },
        ])
        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            database,
            inbound_doc=_inbound("!stock ZyloxTestSAWALI"),
            contact=None,
            settings_doc=_settings(),
            wa_send_text=sender,
        )
        assert res["ok"] is True, res
        assert res["command"] == "!stock"
        body = sender.calls[0]["text"]
        assert "Pharmacie du Test" in body
        assert "ZyloxTestSAWALI 500 mg" in body
        assert "42" in body  # quantity
        assert "250 XOF" in body or "250" in body
        assert "Abidjan" in body or "Près de la mairie" in body

    @pytest.mark.asyncio
    async def test_stock_with_no_args_returns_usage(self, db):
        database, _ = db
        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            database,
            inbound_doc=_inbound("!stock"),
            contact=None,
            settings_doc=_settings(),
            wa_send_text=sender,
        )
        assert res["ok"] is True
        body = sender.calls[0]["text"]
        assert "Utilisation" in body
        assert "!stock" in body.lower() or "stock" in body.lower()

    @pytest.mark.asyncio
    async def test_stock_no_results(self, db):
        database, _ = db
        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            database,
            inbound_doc=_inbound("!stock InventionImaginaire9000"),
            contact=None,
            settings_doc=_settings(),
            wa_send_text=sender,
        )
        assert res["ok"] is True
        body = sender.calls[0]["text"]
        assert "Aucune" in body or "❌" in body

    @pytest.mark.asyncio
    async def test_dispo_alias_works(self, db):
        """`!dispo` doit être un alias de `!stock`."""
        database, _ = db
        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            database,
            inbound_doc=_inbound("!dispo paracetamol"),
            contact=None,
            settings_doc=_settings(),
            wa_send_text=sender,
        )
        assert res["ok"] is True
        assert res["command"] == "!stock"

    @pytest.mark.asyncio
    async def test_stock_excludes_suspended_officines(self, db):
        database, _ = db
        await database.officines.insert_one({
            "id": "test-off-1",
            "name": "Pharmacie Suspendue Test",
            "status": "suspended",
        })
        await database.officine_inventory_items.insert_one({
            "id": uuid.uuid4().hex,
            "officine_id": "test-off-1",
            "product_name": "MoldoxTestSAWALI 500",  # unique name
            "quantity": 100, "unit_price": 250, "currency": "XOF",
            "available": True,
        })
        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            database,
            inbound_doc=_inbound("!stock MoldoxTestSAWALI"),
            contact=None,
            settings_doc=_settings(),
            wa_send_text=sender,
        )
        assert res["ok"] is True
        body = sender.calls[0]["text"]
        assert "Pharmacie Suspendue Test" not in body
        # Le produit existe mais aucune officine active → message dédié
        assert "active" in body.lower() or "Aucune" in body


class TestPublicCommandsAlwaysWork:
    @pytest.mark.asyncio
    async def test_adresse_works_when_autoreply_globally_disabled(self, db):
        """Sanity check : Iter43-fix24i — les `!commandes` ne dépendent PAS
        du toggle global `liluvine_wa_autoreply_enabled`."""
        database, _ = db
        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            database,
            inbound_doc=_inbound("!adresse"),
            contact=None,
            settings_doc=_settings(liluvine_wa_autoreply_enabled=False),
            wa_send_text=sender,
        )
        assert res["ok"] is True
        assert len(sender.calls) == 1
