"""Lot 23 — Centre de Messagerie : compteur de non-lus unique (badge de la
sidebar = pastilles = cloche), rapprochement message ↔ contact par les 8
derniers chiffres du numéro, « dernière interaction » limitée au tenant et
hors envois en masse, conversation = les 1000 messages les plus récents.

server.py ne s'importe pas hors de son environnement complet (nombreuses
dépendances) : les fonctions concernées sont EXTRAITES du fichier (ast) et
exécutées avec un MongoDB simulé (mongomock-motor). Aucun serveur, aucun réseau.
Lancer : cd backend && python -m pytest tests/test_messaging_center_lot23.py -q
"""
from __future__ import annotations

import ast
import asyncio
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

pytest.importorskip("mongomock_motor")
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

SERVER = Path(__file__).resolve().parents[1] / "server.py"
FUNCS = {"_phone_suffix", "_contact_phone_clauses", "_wa_unread_summary", "me_whatsapp_unread",
         "me_contact_messages_mark_read", "me_contact_messages", "me_list_contacts",
         # Lot 24
         "_wa_visible_contact_index", "_wa_attribute", "me_whatsapp_mark_all_read"}
CONSTS = {"WA_PHONE_SUFFIX_LEN", "WA_UNREAD_MAX_AGE_DAYS"}
SCOPE = ["t-pdp", "t-pdp-peer"]  # périmètre visible de l'utilisateur (tenant + pair de la même société)


class _HTTPException(Exception):
    def __init__(self, status_code, detail=""):
        super().__init__(detail)
        self.status_code = status_code


def _load(db) -> Dict[str, Any]:
    """Extrait de server.py les fonctions du lot 23 (sans leurs décorateurs de
    route) et les exécute dans un espace de noms minimal."""
    tree = ast.parse(SERVER.read_text())
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in FUNCS:
            node.decorator_list = []
            nodes.append(node)
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) in CONSTS for t in node.targets):
            nodes.append(node)
    assert {getattr(n, "name", None) for n in nodes} >= FUNCS
    ns: Dict[str, Any] = {
        "db": db, "re": re, "Optional": Optional, "List": List, "Dict": Dict, "Any": Any, "Tuple": Tuple,
        "Depends": lambda x: None, "get_current_user": None, "HTTPException": _HTTPException,
        "datetime": datetime, "timedelta": timedelta, "timezone": timezone,
        "_now": lambda: datetime.now(timezone.utc).isoformat(),
        "WA_24H_WINDOW_SECONDS": 86400, "_wa_window_open": lambda ts: bool(ts),
    }

    async def _visible(user):
        return list(SCOPE)

    async def _flags(user):
        return {}

    async def _restrictions(user):
        return {}
    ns.update(_resolve_visible_client_ids=_visible, _resolve_anon_flags=_flags,
              _apply_anon_to_contact=lambda c, f: c, _resolve_content_restrictions=_restrictions)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SERVER), "exec"), ns)  # noqa: S102
    return ns


def _ts(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


@pytest.fixture()
def env():
    db = AsyncMongoMockClient()["sawali_msg_lot23"]
    loop = asyncio.new_event_loop()
    run = loop.run_until_complete
    run(db.directory_contacts.insert_many([
        # Enregistré SANS indicatif : doit retrouver les messages de 22670111111
        {"id": "c-awa", "client_id": "t-pdp", "name": "Awa", "whatsapp": "70 11 11 11"},
        {"id": "c-ben", "client_id": "t-pdp-peer", "name": "Ben", "whatsapp": "+226 70 22 22 22"},
        {"id": "c-old", "client_id": "t-pdp", "name": "Ancien", "whatsapp": "+226 70 33 33 33"},
        {"id": "c-autre", "client_id": "t-autre", "name": "Autre tenant", "whatsapp": "+226 70 44 44 44"},
    ]))
    msgs = [
        # Awa : 2 non lus sans contact_id (rapprochés par le numéro), 1 lu
        {"id": "m1", "client_id": "t-pdp", "direction": "inbound", "phone_digits": "22670111111", "contact_id": None,
         "read_by_us_at": None, "created_at": _ts(5)},
        {"id": "m2", "client_id": "t-pdp", "direction": "inbound", "phone_digits": "22670111111", "contact_id": None,
         "read_by_us_at": None, "created_at": _ts(4)},
        {"id": "m3", "client_id": "t-pdp", "direction": "inbound", "phone_digits": "22670111111", "contact_id": "c-awa",
         "read_by_us_at": _ts(60), "created_at": _ts(90)},
        # Ben : 1 non lu avec contact_id, chez le pair de la même société
        {"id": "m4", "client_id": "t-pdp-peer", "direction": "inbound", "phone_digits": "22670222222", "contact_id": "c-ben",
         "read_by_us_at": None, "created_at": _ts(30)},
        # Expéditeur inconnu : ne gonfle pas le total
        {"id": "m5", "client_id": "t-pdp", "direction": "inbound", "phone_digits": "22699999999", "contact_id": None,
         "read_by_us_at": None, "created_at": _ts(2)},
        # Autre tenant : jamais compté
        {"id": "m6", "client_id": "t-autre", "direction": "inbound", "phone_digits": "22670444444", "contact_id": "c-autre",
         "read_by_us_at": None, "created_at": _ts(1)},
        # « Ancien » : campagne en masse récente (ne compte pas), vrai échange il y a 30 jours
        {"id": "m7", "client_id": "t-pdp", "direction": "outbound", "phone_digits": "22670333333", "bulk": True, "created_at": _ts(1)},
        {"id": "m8", "client_id": "t-pdp", "direction": "inbound", "phone_digits": "22670333333", "read_by_us_at": _ts(1),
         "created_at": _ts(60 * 24 * 30)},
        # Message d'un AUTRE tenant au numéro d'Awa : ne doit pas la faire remonter
        {"id": "m9", "client_id": "t-autre", "direction": "outbound", "phone_digits": "22670111111", "created_at": _ts(0)},
    ]
    run(db.whatsapp_messages.insert_many(msgs))
    ns = _load(db)
    yield type("Env", (), {"db": db, "run": staticmethod(run), "ns": ns})
    loop.close()


USER = {"id": "u1", "role": "client"}


def test_unread_summary_single_source(env):
    got = env.run(env.ns["_wa_unread_summary"](USER))
    assert got["by_contact"] == {"c-awa": 2, "c-ben": 1}
    assert got["total"] == 3 and got["unknown"] == 1 and got["older"] == 0
    # La route des pastilles renvoie exactement le même calcul (badge = pastilles = cloche).
    assert env.run(env.ns["me_whatsapp_unread"](user=USER)) == got


def test_admin_is_scoped_like_everyone(env):
    got = env.run(env.ns["_wa_unread_summary"]({"id": "adm", "role": "admin"}))
    assert got["total"] == 3  # plus de comptage « tous tenants » pour l'admin


def test_mark_read_matches_phone_suffix_and_clears_badge(env):
    res = env.run(env.ns["me_contact_messages_mark_read"]("c-awa", user=USER))
    assert res["updated"] == 2  # les 2 messages sans contact_id, reconnus par « 70111111 »
    got = env.run(env.ns["_wa_unread_summary"](USER))
    assert got["by_contact"] == {"c-ben": 1} and got["total"] == 1


def test_conversation_returns_most_recent_messages_in_order(env):
    # 1005 messages : la conversation doit contenir les plus récents, dans l'ordre chronologique.
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    env.run(env.db.whatsapp_messages.insert_many([
        {"id": f"x{i}", "client_id": "t-pdp", "direction": "inbound", "phone_digits": "22670222222", "contact_id": "c-ben",
         "created_at": (base + timedelta(minutes=i)).isoformat()} for i in range(1005)
    ]))
    out = env.run(env.ns["me_contact_messages"]("c-ben", user=USER))
    ids = [m["id"] for m in out["messages"]]
    assert len(ids) == 1000 and ids[-1] == "m4"          # le plus récent (il y a 30 min) est bien là
    assert "x0" not in ids and ids[0] == "x6"             # les plus anciens sont ceux qui sautent
    created = [m["created_at"] for m in out["messages"]]
    assert created == sorted(created)


def test_last_interaction_is_tenant_scoped_and_ignores_bulk(env):
    items = env.run(env.ns["me_list_contacts"](user=USER))
    by_id = {c["id"]: c for c in items}
    # Awa : dernier échange = son message d'il y a 4 min (pas le message de l'autre tenant d'il y a 0 min)
    assert by_id["c-awa"]["last_interaction_at"] == env.run(env.db.whatsapp_messages.find_one({"id": "m2"}))["created_at"]
    assert by_id["c-awa"]["last_interaction_direction"] == "in"
    # Ancien : la campagne d'il y a 1 min est ignorée → dernier vrai échange il y a 30 jours
    assert by_id["c-old"]["last_interaction_at"] == env.run(env.db.whatsapp_messages.find_one({"id": "m8"}))["created_at"]
    # Ordre attendu par l'écran (tri décroissant sur la date) : Awa, Ben, Ancien
    order = sorted([c for c in items if c.get("last_interaction_at")], key=lambda c: c["last_interaction_at"], reverse=True)
    assert [c["id"] for c in order] == ["c-awa", "c-ben", "c-old"]


def test_phone_suffix_helpers(env):
    assert env.ns["_phone_suffix"]("+226 70 11 11 11") == "70111111"
    assert env.ns["_phone_suffix"]("123") == "123"
    clauses = env.ns["_contact_phone_clauses"]({"id": "c", "whatsapp": "70111111", "phone": "+22670111111"})
    assert clauses[0] == {"contact_id": "c"} and len(clauses) == 2  # même suffixe : une seule clause
