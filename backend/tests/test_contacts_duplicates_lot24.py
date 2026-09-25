"""Lot 24 — Contacts : plus de doublon à l'enregistrement d'un numéro inconnu
(idempotent, entrées déjà couvertes retirées), et outil de dédoublonnage
(fiche la plus complète gardée, à égalité la plus ancienne ; suppression
seulement des fiches cochées, messages rattachés à la fiche gardée).
Fonctions extraites de server.py (ast), MongoDB simulé. Aucun réseau.
Lancer : cd backend && python -m pytest tests/test_contacts_duplicates_lot24.py -q
"""
from __future__ import annotations

import ast
import asyncio
import re
import types
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

pytest.importorskip("mongomock_motor")
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

SERVER = Path(__file__).resolve().parents[1] / "server.py"
FUNCS = {"_phone_suffix", "_phone_suffix_regex", "_find_contact_by_phone", "me_list_wa_pending_imports",
         "me_import_wa_pending", "_contact_completeness", "_duplicate_groups", "me_contacts_duplicates",
         "me_contacts_duplicates_delete"}
CONSTS = {"WA_PHONE_SUFFIX_LEN", "_DUP_SCORE_FIELDS"}
SCOPE = ["t-pdp"]


class _HTTPException(Exception):
    def __init__(self, status_code, detail=""):
        super().__init__(detail)
        self.status_code = status_code


def _load(db):
    tree = ast.parse(SERVER.read_text())
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in FUNCS:
            node.decorator_list = []
            nodes.append(node)
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) in CONSTS for t in node.targets):
            nodes.append(node)
    assert {getattr(n, "name", None) for n in nodes} >= FUNCS

    async def _visible(user):
        return list(SCOPE)

    async def _log(**kw):
        return None
    ns = {"db": db, "re": re, "Optional": Optional, "List": List, "Dict": Dict, "Any": Any, "Tuple": Tuple,
          "Depends": lambda x: None, "get_current_user": None, "HTTPException": _HTTPException,
          "WaPendingImportRequest": None, "ContactsDuplicatesDeleteRequest": None,
          "_now": lambda: datetime.now(timezone.utc).isoformat(), "_uuid": lambda: uuid.uuid4().hex,
          "_resolve_visible_client_ids": _visible, "_log_activity": _log}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SERVER), "exec"), ns)  # noqa: S102
    return ns


@pytest.fixture()
def env():
    db = AsyncMongoMockClient()["sawali_dup_lot24"]
    loop = asyncio.new_event_loop()
    yield types.SimpleNamespace(db=db, run=loop.run_until_complete, ns=_load(db))
    loop.close()


SUP = {"id": "sup", "role": "superviseur", "client_id": "t-pdp"}
ADMIN = {"id": "adm", "role": "admin", "client_id": "t-pdp"}
CLIENT = {"id": "u1", "role": "client", "client_id": "t-pdp"}
REQ = types.SimpleNamespace(name=None, company=None, email=None)


def test_import_is_idempotent_when_contact_already_exists(env):
    # Contact créé entre-temps par l'ajout automatique de Liluvine, saisi avec espaces
    env.run(env.db.directory_contacts.insert_one({"id": "c-auto", "client_id": "t-pdp", "name": "Awa", "whatsapp": "+226 70 11 11 11"}))
    env.run(env.db.wa_pending_imports.insert_one({"id": "p1", "client_id": "t-pdp", "phone_digits": "22670111111", "from": "+22670111111"}))
    env.run(env.db.whatsapp_messages.insert_one({"id": "m1", "client_id": "t-pdp", "direction": "inbound",
                                                 "phone_digits": "22670111111", "contact_id": None}))
    res = env.run(env.ns["me_import_wa_pending"]("p1", REQ, user=CLIENT))
    assert res["already_present"] is True and res["contact"]["id"] == "c-auto"
    assert env.run(env.db.directory_contacts.count_documents({})) == 1          # pas de doublon
    assert env.run(env.db.whatsapp_messages.find_one({"id": "m1"}))["contact_id"] == "c-auto"
    assert env.run(env.db.wa_pending_imports.count_documents({})) == 0


def test_import_twice_creates_a_single_contact(env):
    env.run(env.db.wa_pending_imports.insert_many([
        {"id": "p1", "client_id": "t-pdp", "phone_digits": "22670222222", "from": "+22670222222", "wa_profile_name": "Ben"},
        {"id": "p2", "client_id": "t-pdp", "phone_digits": "22670222222", "from": "+22670222222", "wa_profile_name": "Ben"},
    ]))
    first = env.run(env.ns["me_import_wa_pending"]("p1", REQ, user=CLIENT))
    assert first["already_present"] is False
    # La 2e entrée du même numéro a été retirée avec la 1re : un 2e clic ne recrée rien.
    assert env.run(env.db.wa_pending_imports.count_documents({})) == 0
    assert env.run(env.db.directory_contacts.count_documents({})) == 1


def test_pending_list_drops_numbers_already_in_directory(env):
    env.run(env.db.directory_contacts.insert_one({"id": "c1", "client_id": "t-pdp", "name": "Awa", "whatsapp": "70111111"}))
    env.run(env.db.wa_pending_imports.insert_many([
        {"id": "p1", "client_id": "t-pdp", "phone_digits": "22670111111", "last_seen_at": "2026-09-25"},
        {"id": "p2", "client_id": "t-pdp", "phone_digits": "22670999999", "last_seen_at": "2026-09-24"},
    ]))
    items = env.run(env.ns["me_list_wa_pending_imports"](user=CLIENT))
    assert [i["id"] for i in items] == ["p2"]
    assert env.run(env.db.wa_pending_imports.count_documents({})) == 1


def test_duplicates_keep_most_complete_then_oldest(env):
    env.run(env.db.directory_contacts.insert_many([
        # Groupe 1 : la fiche la plus complète est gardée même si elle est plus récente
        {"id": "a-old", "client_id": "t-pdp", "name": "+22670111111", "whatsapp": "+22670111111", "created_at": "2026-01-01"},
        {"id": "a-full", "client_id": "t-pdp", "name": "Awa Traoré", "whatsapp": "+226 70 11 11 11",
         "company": "PDP", "email": "awa@x.bf", "created_at": "2026-05-01"},
        # Groupe 2 : complétude égale → la plus ancienne est gardée, la plus récente proposée
        {"id": "b-1", "client_id": "t-pdp", "name": "Ben", "whatsapp": "70222222", "created_at": "2026-02-01"},
        {"id": "b-2", "client_id": "t-pdp", "name": "Ben O.", "whatsapp": "+22670222222", "created_at": "2026-03-01"},
        # Unique : pas de groupe
        {"id": "c-1", "client_id": "t-pdp", "name": "Chantal", "whatsapp": "+22670333333"},
        # Autre tenant : hors périmètre
        {"id": "x-1", "client_id": "t-autre", "name": "Awa bis", "whatsapp": "+22670111111"},
    ]))
    out = env.run(env.ns["me_contacts_duplicates"](user=SUP))
    groups = {g["phone_suffix"]: g for g in out["groups"]}
    assert groups["70111111"]["keep"]["id"] == "a-full" and [d["id"] for d in groups["70111111"]["duplicates"]] == ["a-old"]
    assert groups["70222222"]["keep"]["id"] == "b-1" and [d["id"] for d in groups["70222222"]["duplicates"]] == ["b-2"]
    assert out["duplicates_count"] == 2 and "70333333" not in groups
    # Réservé au superviseur : ni l'admin ni un client n'y ont accès.
    for other in (ADMIN, CLIENT):
        with pytest.raises(_HTTPException):
            env.run(env.ns["me_contacts_duplicates"](user=other))


def test_delete_only_checked_duplicates_and_relink_messages(env):
    env.run(env.db.directory_contacts.insert_many([
        {"id": "a-keep", "client_id": "t-pdp", "name": "Awa", "whatsapp": "+22670111111", "company": "PDP", "created_at": "2026-01-01"},
        {"id": "a-dup", "client_id": "t-pdp", "name": "Awa", "whatsapp": "70111111", "created_at": "2026-02-01"},
    ]))
    env.run(env.db.whatsapp_messages.insert_one({"id": "m1", "contact_id": "a-dup", "client_id": "t-pdp"}))
    req = types.SimpleNamespace(ids=["a-dup", "a-keep", "inconnu"])  # la fiche gardée ne peut pas être supprimée
    with pytest.raises(_HTTPException):
        env.run(env.ns["me_contacts_duplicates_delete"](req, user=ADMIN))  # l'admin ne peut pas supprimer
    res = env.run(env.ns["me_contacts_duplicates_delete"](req, user=SUP))
    assert res["deleted"] == 1 and res["ignored"] == 2
    assert [c["id"] for c in env.run(env.db.directory_contacts.find({}, {"_id": 0}).to_list(10))] == ["a-keep"]
    assert env.run(env.db.whatsapp_messages.find_one({"id": "m1"}))["contact_id"] == "a-keep"


def test_suffix_regex_matches_any_formatting(env):
    rx = env.ns["_phone_suffix_regex"]("22670111111")
    for stored in ("+226 70 11 11 11", "70111111", "+22670111111", "70-11-11-11"):
        assert re.search(rx, stored), stored
    assert not re.search(rx, "+22670111112")
