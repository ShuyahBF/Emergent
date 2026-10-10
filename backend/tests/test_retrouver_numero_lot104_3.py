"""Lot 104.3 — « Retrouver un numéro » : diagnostic des messages invisibles dans le Centre de messagerie
(fiche dans un autre espace, messages sans fiche) et réparation en un clic. MongoDB simulé, aucun réseau."""
from __future__ import annotations

import ast
import asyncio
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pytest

pytest.importorskip("mongomock_motor")
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

from _source_serveur import source_serveur  # noqa: E402

FUNCS = {"_phone_suffix", "_phone_suffix_regex", "_exiger_admin_ou_superviseur", "me_retrouver_numero",
         "me_retrouver_numero_rattacher"}
CONSTS = {"WA_PHONE_SUFFIX_LEN"}


class _Vis:
    """Visibilité des lignes : aucune restriction (cas de l'administrateur)."""
    restreint = False

    @classmethod
    async def charger(cls, db, user, complet=False):
        return cls()

    def contact_visible(self, c, tel=None):
        return True


def _load(db) -> Dict[str, Any]:
    tree = ast.parse(source_serveur())
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in FUNCS:
            node.decorator_list = []
            nodes.append(node)
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) in CONSTS for t in node.targets):
            nodes.append(node)
    from fastapi import HTTPException
    ns: Dict[str, Any] = {"db": db, "re": re, "Optional": Optional, "List": List, "Dict": Dict, "Any": Any,
                          "Tuple": Tuple, "Depends": lambda x: None, "Body": lambda *a, **k: None,
                          "get_current_user": None, "HTTPException": HTTPException,
                          "_uuid": lambda: str(uuid.uuid4()), "_now": lambda: datetime.now(timezone.utc).isoformat()}

    async def _visible(user):
        return ["moi"]
    ns["_resolve_visible_client_ids"] = _visible
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "server", "exec"), ns)  # noqa: S102
    return ns


def test_diagnostic_puis_reparation(monkeypatch):
    import routes.numeros_wa as nw
    monkeypatch.setattr(nw, "VisibiliteLignes", _Vis)
    db = AsyncMongoMockClient()["lot104_3"]
    ns = _load(db)
    admin = {"id": "a1", "role": "admin", "full_name": "Admin"}

    async def run():
        # Fiche créée automatiquement dans un AUTRE espace ; 2 messages reçus sans fiche, hors de mon espace
        await db.directory_contacts.insert_one({"id": "c1", "client_id": "autre", "name": "kygeorgesemmanuel",
                                                "whatsapp": "+22655859615", "tags": ["auto-liluvine"], "created_at": "1"})
        for i, texte in enumerate(["Nous sommes déjà la", "Confirmer"]):
            await db.whatsapp_messages.insert_one({"id": f"m{i}", "client_id": "superviseur", "direction": "inbound",
                                                   "phone_digits": "22655859615", "contact_id": None, "body": texte,
                                                   "created_at": f"2026-10-10T14:38:{i}0"})
        d = await ns["me_retrouver_numero"]("55 85 96 15", admin)
        assert d["messages"]["total"] == 2 and d["messages"]["hors_espace"] == 2 and d["messages"]["sans_fiche"] == 2
        assert any("AUTRE espace" in c for c in d["causes"]) and d["reparable"]
        r = await ns["me_retrouver_numero_rattacher"]({"numero": "+226 55 85 96 15"}, admin)
        assert r["rattaches"] == 2 and r["fiche_deplacee"] and r["fiche_id"] == "c1"
        d2 = await ns["me_retrouver_numero"]("55859615", admin)
        assert d2["messages"]["hors_espace"] == 0 and d2["messages"]["sans_fiche"] == 0 and not d2["reparable"]
        assert all(f["dans_mon_espace"] for f in d2["fiches"])
        # Lot 104.4 : l'espace de réception des nouveaux numéros devient le mien
        reg = await db.settings.find_one({"_id": "global"})
        assert reg["wa_espace_reception"] == "moi" and d2["reception_dans_mon_espace"]
        assert any("NOUVEAUX numéros" in c for c in d["causes"])
        # Accès refusé à un simple utilisateur
        with pytest.raises(Exception):
            await ns["me_retrouver_numero"]("55859615", {"id": "u", "role": "client"})
    asyncio.run(run())
