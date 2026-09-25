"""Lot 24 — Les réponses automatiques de Liluvine apparaissent dans le fil :
réponse à un modèle d'annonce, message de correction de commande et
`!reactions` sont désormais copiés dans `whatsapp_messages` (avant : envoyés
sur WhatsApp mais absents de la conversation).
Réutilise l'environnement du lot 21 (Mongo, IA et WhatsApp simulés).
Lancer : cd backend && python -m pytest tests/test_liluvine_thread_mirror_lot24.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_liluvine_wa_prospects_lot21 import CLIENT_CONTACT, env  # noqa: E402,F401 — fixture réutilisée


def test_ad_template_reply_is_copied_into_thread(env):
    async def fake_ad(text, send, from_num, **kw):
        await send(from_num, "Merci ! Voici notre offre de lancement.")
        return {"sent": True, "template": {"id": "tpl-123456789", "response_text": "Merci ! Voici notre offre de lancement."}}
    sys.modules["server"].LILUVINE_REACTIONS_HELPERS = {"try_reply_ad_template": fake_ad}
    try:
        res = env.run(CLIENT_CONTACT, "pharma", contact={"id": "c-client", "client_id": "pharma", "name": "Client fidèle"},
                      text="Je viens de votre publicité")
    finally:
        sys.modules["server"].LILUVINE_REACTIONS_HELPERS = {}
    assert res["ok"] is True and res["command"].startswith("ad_template")
    m = env.loop.run_until_complete(env.db.whatsapp_messages.find_one({"direction": "outbound"}, {"_id": 0}))
    assert m["body"] == "Merci ! Voici notre offre de lancement." and m["command"] == "ad_template"
    assert m["contact_id"] == "c-client" and m["phone_digits"] == CLIENT_CONTACT and m["client_id"] == "pharma"
    assert env.sent and env.sent[0]["text"] == m["body"]


def test_fuzzy_correction_message_is_copied_into_thread(env):
    async def fake_fuzzy(text):
        return {"cmd": "garde", "score": 91, "correction_prefix": "Vous vouliez dire « !garde » ?"}
    sys.modules["server"].LILUVINE_REACTIONS_HELPERS = {"try_fuzzy_command_correction": fake_fuzzy}
    try:
        env.run(CLIENT_CONTACT, "pharma", contact={"id": "c-client", "client_id": "pharma", "name": "Client fidèle"},
                text="pharmacie de gard")
    except Exception:  # noqa: BLE001 — la suite (commande !garde) dépend d'autres modules, hors sujet ici
        pass
    finally:
        sys.modules["server"].LILUVINE_REACTIONS_HELPERS = {}
    bodies = [m["body"] for m in env.loop.run_until_complete(
        env.db.whatsapp_messages.find({"command": "fuzzy_correction"}, {"_id": 0}).to_list(5))]
    assert bodies == ["Vous vouliez dire « !garde » ?"]
