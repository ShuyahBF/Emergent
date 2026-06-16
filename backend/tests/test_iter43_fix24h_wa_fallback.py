"""Iter43-fix24h (2026-06) — Tests pour le catch-all `!commande` inconnue.

Vérifie que `autoreply_to_inbound` envoie toujours une réponse de
fallback (par défaut `…`) pour les exclamations `!xxx` non reconnues, ET que
les handlers `!garde`/`!meteo` qui plantent envoient malgré tout une réponse
au lieu de rester silencieux.
"""
import os

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

# Ces tests interrogent directement la fonction (pas via HTTP).
from routes import liluvine_wa_autoreply as autoreply  # noqa: E402

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "sawali_db")


class _FakeSend:
    """Faux wa_send_text qui enregistre les appels au lieu d'envoyer pour de vrai."""

    def __init__(self):
        self.calls = []
        self.next_response = {"ok": True, "message_id": "wamid.test"}
        self.raise_exc = None

    async def __call__(self, to, text, **kw):
        if self.raise_exc:
            raise self.raise_exc
        self.calls.append({"to": to, "text": text, **kw})
        return self.next_response


@pytest_asyncio.fixture
async def db():
    """Create motor client INSIDE the test's event loop to avoid loop binding issues."""
    c = AsyncIOMotorClient(MONGO_URL)
    database = c[DB_NAME]
    # cleanup before
    await database.whatsapp_messages.delete_many({"command": {"$in": ["unknown_fallback", "!garde", "!meteo"]}})
    await database.liluvine_exclamations.delete_many({"phone_digits": "33600000099"})
    yield database
    # cleanup after
    await database.whatsapp_messages.delete_many({"command": {"$in": ["unknown_fallback", "!garde", "!meteo"]}})
    await database.liluvine_exclamations.delete_many({"phone_digits": "33600000099"})
    c.close()


def _inbound(text="!unknowncmd"):
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
        "liluvine_wa_autoreply_enabled": True,
        "liluvine_wa_autoreply_allow_mode": "any",
        "liluvine_wa_autoreply_schedule": "always",
        "liluvine_wa_autoreply_keywords": [],
        "liluvine_wa_autoreply_cooldown_seconds": 0,
        "liluvine_wa_autoreply_signature": "🤖 Liluvine",
    }
    base.update(overrides)
    return base


class TestUnknownCommandFallback:
    @pytest.mark.asyncio
    async def test_unknown_command_sends_default_ellipsis(self, db):
        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            db,
            inbound_doc=_inbound("!Aizenta"),
            contact=None,
            settings_doc=_settings(),
            wa_send_text=sender,
        )
        assert res["ok"] is True
        assert res["command"] == "unknown_fallback"
        assert len(sender.calls) == 1
        assert sender.calls[0]["text"] == "…"
        assert sender.calls[0]["to"] == "+33600000099"

    @pytest.mark.asyncio
    async def test_unknown_command_custom_reply(self, db):
        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            db,
            inbound_doc=_inbound("!hello"),
            contact=None,
            settings_doc=_settings(
                liluvine_wa_unknown_cmd_reply="Commande inconnue, contactez le support.",
            ),
            wa_send_text=sender,
        )
        assert res["ok"] is True
        assert sender.calls[0]["text"] == "Commande inconnue, contactez le support."

    @pytest.mark.asyncio
    async def test_unknown_command_respects_denylist(self, db):
        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            db,
            inbound_doc=_inbound("!hello"),
            contact=None,
            settings_doc=_settings(
                liluvine_wa_autoreply_deny_phones=["33600000099"],
            ),
            wa_send_text=sender,
        )
        assert res["ok"] is False
        assert res["reason"] == "denylisted"
        assert len(sender.calls) == 0  # No reply sent

    @pytest.mark.asyncio
    async def test_unknown_command_works_when_global_autoreply_disabled(self, db):
        """Iter43-fix24i — Le toggle `liluvine_wa_autoreply_enabled` ne contrôle
        QUE l'auto-reply LLM. Les `!commandes` doivent toujours fonctionner."""
        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            db,
            inbound_doc=_inbound("!whatever"),
            contact=None,
            settings_doc=_settings(liluvine_wa_autoreply_enabled=False),
            wa_send_text=sender,
        )
        assert res["ok"] is True
        assert res["command"] == "unknown_fallback"
        assert len(sender.calls) == 1
        assert sender.calls[0]["text"] == "…"

    @pytest.mark.asyncio
    async def test_unknown_command_persists_exclamation_handled(self, db):
        sender = _FakeSend()
        await autoreply.autoreply_to_inbound(
            db,
            inbound_doc=_inbound("!nouvellecmd test"),
            contact=None,
            settings_doc=_settings(),
            wa_send_text=sender,
        )
        # Vérifie que l'exclamation a bien été persistée ET marquée handled
        exc = await db.liluvine_exclamations.find_one(
            {"wa_message_id": "wamid.test-in-1", "direction": "inbound"},
        )
        assert exc is not None, "Exclamation pas persistée"
        assert exc["command"] == "nouvellecmd"
        assert exc.get("handled") is True
        assert exc.get("fallback") is True


class TestPublicCommandHandlerResilience:
    @pytest.mark.asyncio
    async def test_meteo_with_unknown_city_still_replies(self, db):
        """Si !meteo ne trouve pas la ville, doit quand même répondre."""
        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            db,
            inbound_doc=_inbound("!meteo ZZZZZZZZZZZZZZZ"),
            contact=None,
            settings_doc=_settings(),
            wa_send_text=sender,
        )
        assert res["ok"] is True
        assert res["command"] == "!meteo"
        assert len(sender.calls) == 1
        # Doit contenir au moins un texte non-vide
        assert sender.calls[0]["text"].strip()

    @pytest.mark.asyncio
    async def test_garde_handler_resilient_on_db_exception(self, db, monkeypatch):
        """Patche _build_garde_reply pour qu'il lève — la fonction principale doit
        envoyer un message d'erreur user-friendly au lieu d'un silence."""
        async def _raising(_db):
            raise RuntimeError("DB down test")

        monkeypatch.setattr(autoreply, "_build_garde_reply", _raising)

        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            db,
            inbound_doc=_inbound("!garde"),
            contact=None,
            settings_doc=_settings(),
            wa_send_text=sender,
        )
        assert res["ok"] is True
        assert len(sender.calls) == 1
        # Le message envoyé doit indiquer une erreur user-friendly
        assert "Désolé" in sender.calls[0]["text"] or "…" in sender.calls[0]["text"]

    # Iter43-fix24i — Tests critiques : les commandes publiques `!garde`/`!meteo`
    # ainsi que le fallback `!xxx` inconnu doivent fonctionner MÊME SI le toggle
    # global `liluvine_wa_autoreply_enabled` est FALSE (qui ne contrôle QUE le
    # LLM auto-reply, pas les commandes manuelles avec préfixe `!`).
    @pytest.mark.asyncio
    async def test_garde_works_even_when_autoreply_globally_disabled(self, db):
        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            db,
            inbound_doc=_inbound("!garde"),
            contact=None,
            settings_doc=_settings(liluvine_wa_autoreply_enabled=False),
            wa_send_text=sender,
        )
        assert res["ok"] is True, res
        assert res["command"] == "!garde"
        assert len(sender.calls) == 1
        assert sender.calls[0]["text"].strip()  # non-empty

    @pytest.mark.asyncio
    async def test_meteo_works_even_when_autoreply_globally_disabled(self, db):
        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            db,
            inbound_doc=_inbound("!meteo Ouagadougou"),
            contact=None,
            settings_doc=_settings(liluvine_wa_autoreply_enabled=False),
            wa_send_text=sender,
        )
        assert res["ok"] is True, res
        assert res["command"] == "!meteo"
        assert len(sender.calls) == 1

    @pytest.mark.asyncio
    async def test_unknown_fallback_works_even_when_autoreply_globally_disabled(self, db):
        """Le toggle `liluvine_wa_autoreply_enabled` ne doit PAS bloquer le fallback `…`."""
        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            db,
            inbound_doc=_inbound("!Aizenta"),
            contact=None,
            settings_doc=_settings(liluvine_wa_autoreply_enabled=False),
            wa_send_text=sender,
        )
        assert res["ok"] is True, res
        assert res["command"] == "unknown_fallback"
        assert sender.calls[0]["text"] == "…"

    @pytest.mark.asyncio
    async def test_unknown_fallback_can_be_explicitly_disabled(self, db):
        """Un admin peut désactiver le fallback `…` via le réglage dédié."""
        sender = _FakeSend()
        res = await autoreply.autoreply_to_inbound(
            db,
            inbound_doc=_inbound("!Aizenta"),
            contact=None,
            settings_doc=_settings(
                liluvine_wa_autoreply_enabled=True,
                liluvine_wa_unknown_cmd_fallback_enabled=False,
            ),
            wa_send_text=sender,
        )
        assert res["ok"] is False
        assert res["reason"] == "unknown_fallback_disabled"
        assert len(sender.calls) == 0
