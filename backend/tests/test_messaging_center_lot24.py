"""Lot 24 — Centre de Messagerie : les non-lus de plus de 30 jours ne sont
plus comptés comme nouveaux (historique jamais marqué comme lu), et « Tout
marquer comme lu » traite tous les non-lus des contacts visibles.
Réutilise l'environnement du lot 23 (fonctions extraites de server.py, Mongo simulé).
Lancer : cd backend && python -m pytest tests/test_messaging_center_lot24.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_messaging_center_lot23 import USER, _ts, env  # noqa: E402,F401 — fixture réutilisée


def _add_old_unread(env, n=47):
    """47 vieux messages jamais lus (45 jours), rattachés à Awa par son numéro."""
    env.run(env.db.whatsapp_messages.insert_many([
        {"id": f"old{i}", "client_id": "t-pdp", "direction": "inbound", "phone_digits": "22670111111",
         "contact_id": None, "read_by_us_at": None, "created_at": _ts(60 * 24 * 45 + i)} for i in range(n)
    ]))


def test_old_unread_not_counted_but_reported(env):
    _add_old_unread(env)
    got = env.run(env.ns["_wa_unread_summary"](USER))
    assert got["by_contact"] == {"c-awa": 2, "c-ben": 1} and got["total"] == 3
    assert got["older"] == 47 and got["max_age_days"] == 30


def test_mark_all_read_clears_contacts_but_not_unknown_senders(env):
    _add_old_unread(env)
    res = env.run(env.ns["me_whatsapp_mark_all_read"](user=USER))
    assert res["updated"] == 2 + 1 + 47
    got = env.run(env.ns["_wa_unread_summary"](USER))
    assert got["total"] == 0 and got["older"] == 0
    # L'expéditeur inconnu (Inbox unifiée) et l'autre tenant ne sont pas touchés.
    assert env.run(env.db.whatsapp_messages.find_one({"id": "m5"}))["read_by_us_at"] is None
    assert env.run(env.db.whatsapp_messages.find_one({"id": "m6"}))["read_by_us_at"] is None
