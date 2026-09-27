"""Lot 29 — performances du Centre de Messagerie : les nouveaux calculs donnent
EXACTEMENT les mêmes résultats que les anciens.

- /me/contacts : « dernière interaction » calculée par MongoDB (regroupement)
  au lieu d'un parcours Python de 20 000 WhatsApp + 20 000 SMS ;
- /me/wa-pending-imports : le carnet est lu une fois au lieu d'une recherche par
  expression régulière pour chaque numéro en attente.
Données tirées au hasard (graine fixe), MongoDB simulé. Aucun réseau.
"""
from __future__ import annotations

import ast
import asyncio
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pytest

pytest.importorskip("mongomock_motor")
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

from _source_serveur import source_serveur  # noqa: E402

FUNCS = {"_phone_suffix", "_phone_suffix_regex", "_find_contact_by_phone", "me_list_contacts",
         "me_list_wa_pending_imports"}
CONSTS = {"WA_PHONE_SUFFIX_LEN"}
SCOPE = ["t1", "t1-peer"]


def _load(db) -> Dict[str, Any]:
    tree = ast.parse(source_serveur())
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in FUNCS:
            node.decorator_list = []
            nodes.append(node)
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) in CONSTS for t in node.targets):
            nodes.append(node)
    ns: Dict[str, Any] = {"db": db, "re": re, "Optional": Optional, "List": List, "Dict": Dict, "Any": Any,
                          "Tuple": Tuple, "Depends": lambda x: None, "get_current_user": None}

    async def _visible(user):
        return list(SCOPE)

    async def _flags(user):
        return {}
    ns.update(_resolve_visible_client_ids=_visible, _resolve_anon_flags=_flags, _apply_anon_to_contact=lambda c, f: c)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "server", "exec"), ns)  # noqa: S102
    return ns


# ---------------------------------------------------------------- anciens calculs (copie du code d'avant le lot 29)
async def _ancien_last_interaction(db, ns, contacts, client_ids):
    phone_map: Dict[str, List[Dict[str, Any]]] = {}
    for c in contacts:
        d10 = ns["_phone_suffix"](c.get("whatsapp") or c.get("phone"))
        if len(d10) >= 6:
            phone_map.setdefault(d10, []).append(c)
    last: Dict[str, Tuple[str, str]] = {}

    def _note(msg, direction):
        ts = str(msg.get("created_at") or "")
        if not ts:
            return
        for k in ("phone_digits", "from", "to"):
            d10 = ns["_phone_suffix"](msg.get(k))
            if d10 in phone_map:
                if d10 not in last or ts > last[d10][0]:
                    last[d10] = (ts, direction)
                break
    q = {"client_id": {"$in": client_ids}, "bulk": {"$ne": True}}
    for coll in (db.whatsapp_messages, db.sms_messages):
        async for m in coll.find(q, {"_id": 0}).sort("created_at", -1).limit(20000):
            _note(m, "in" if m.get("direction") == "inbound" else "out")
    out = {}
    for d10, cs in phone_map.items():
        for c in cs:
            out[c["id"]] = last.get(d10, (None, None))
    return out


def _numero(rng):
    """Numéro dans des formats variés (avec/sans indicatif, espaces, +)."""
    base = "".join(rng.choice("0123456789") for _ in range(8))
    return rng.choice([base, "226" + base, "+226 " + " ".join(base[i:i + 2] for i in range(0, 8, 2)),
                       "00226" + base, base[:6], ""])


@pytest.mark.parametrize("graine", [1, 2, 3, 4, 5])
def test_derniere_interaction_identique(graine):
    rng = random.Random(graine)
    db = AsyncMongoMockClient()[f"lot29_{graine}"]
    ns = _load(db)
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)

    async def run():
        numeros = [_numero(rng) for _ in range(40)]
        contacts = []
        for i in range(60):
            n = rng.choice(numeros)
            contacts.append({"id": f"c{i}", "name": f"N{i:03d}", "client_id": rng.choice(SCOPE + ["autre"]),
                             "whatsapp": n if rng.random() < .7 else "", "phone": rng.choice(numeros)})
        await db.directory_contacts.insert_many([dict(c) for c in contacts])
        for coll in (db.whatsapp_messages, db.sms_messages):
            docs = []
            for j in range(900):
                n = rng.choice(numeros)
                docs.append({"id": f"{coll.name}{j}", "client_id": rng.choice(SCOPE + ["autre"]),
                             "bulk": rng.random() < .1,
                             "direction": rng.choice(["inbound", "outbound"]),
                             "phone_digits": re.sub(r"\D", "", n) if rng.random() < .8 else None,
                             "from": rng.choice(numeros), "to": rng.choice(numeros),
                             "created_at": (t0 + timedelta(minutes=rng.randint(0, 50000))).isoformat()})
            await coll.insert_many(docs)
        nouveau = {c["id"]: (c.get("last_interaction_at"), c.get("last_interaction_direction"))
                   for c in await ns["me_list_contacts"]({"id": "u"}) if "last_interaction_at" in c}
        visibles = [c for c in contacts if c["client_id"] in SCOPE]
        ancien = await _ancien_last_interaction(db, ns, visibles, SCOPE)
        # mêmes dates ; même sens sauf égalité de date (ordre indéfini dans les deux cas)
        assert {k: v[0] for k, v in nouveau.items()} == {k: v[0] for k, v in ancien.items()}
        assert sum(1 for k in ancien if ancien[k][1] != nouveau[k][1]) <= 1
        assert any(v[0] for v in ancien.values())          # le test porte bien sur des dates réelles
    asyncio.run(run())


@pytest.mark.parametrize("graine", [11, 12, 13])
def test_imports_en_attente_identiques(graine):
    rng = random.Random(graine)
    db = AsyncMongoMockClient()[f"lot29p_{graine}"]
    ns = _load(db)

    async def run():
        numeros = [_numero(rng) for _ in range(30)]
        await db.directory_contacts.insert_many([
            {"id": f"c{i}", "client_id": rng.choice(SCOPE + ["autre"]), "whatsapp": rng.choice(numeros),
             "phone": rng.choice(numeros), "phone_digits": re.sub(r"\D", "", rng.choice(numeros)),
             "created_at": f"2026-01-{i % 28 + 1:02d}"} for i in range(40)])
        pend = [{"id": f"p{i}", "client_id": "t1", "phone_digits": re.sub(r"\D", "", rng.choice(numeros)) or None,
                 "from": rng.choice(numeros), "last_seen_at": f"2026-09-{i % 28 + 1:02d}T{i:02d}:00"} for i in range(35)]
        await db.wa_pending_imports.insert_many([dict(p) for p in pend])
        # ancien calcul : _find_contact_by_phone (regex) pour chaque numéro en attente
        attendus, vus = [], set()
        for it in sorted(pend, key=lambda p: p["last_seen_at"], reverse=True)[:50]:
            suffix = ns["_phone_suffix"](it.get("phone_digits") or it.get("from"))
            existe = await ns["_find_contact_by_phone"](SCOPE, it.get("phone_digits") or it.get("from"))
            if existe or (suffix and suffix in vus):
                continue
            vus.add(suffix)
            attendus.append(it["id"])
        garde = await ns["me_list_wa_pending_imports"]({"id": "u", "client_id": "t1", "role": "client"})
        assert [x["id"] for x in garde] == attendus
        assert 0 < len(attendus) < len(pend)               # des numéros gardés ET des numéros retirés
    asyncio.run(run())
