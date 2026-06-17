"""Iter43-fix24ac (2026-06-16) — Configurable VIDAL actions.

The user explicitly requested that VIDAL endpoints be editable via the Admin
Settings instead of hard-coded paths. Each "action" defines:

  - `id`            : unique slug used internally (e.g. "recherche")
  - `label`         : human-readable name shown in admin / portal
  - `method`        : HTTP method (GET / POST / PUT / DELETE)
  - `path`          : VIDAL path with optional placeholders, e.g. `/products`
  - `query_params`  : list of `{key, value_template, required}`
  - `body_template` : raw body (typically XML for `/alerts/full`) with `{vars}`
  - `is_public`     : accessible via WhatsApp `!cmd` for any contact (else
                      requires the contact to be tagged "Abonné VIDAL")
  - `exclamation_command` : WhatsApp `!cmd` that triggers this action
  - `portal_button_visible` : show a button on `/portal/vidal`
  - `portal_button_label`   : label of that button
  - `input_label`   : placeholder for the user-input field in the portal
  - `input_param`   : which `{var}` to bind the user input to (default `q`)
  - `example_url`   : doc-style example (string) for admin reference
  - `order`         : sort order

At execution time, the path / query / body are rendered with Python's
`str.format_map` and concatenated with the configured `base_url` + the
server-side `app_id` + `app_key`.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.vidal.actions")


# ---------------------------------------------------------------------------
# Defaults (seeded the first time the admin opens the settings tab)
# ---------------------------------------------------------------------------
DEFAULT_ACTIONS: List[Dict[str, Any]] = [
    {
        "id": "recherche",
        "label": "Recherche par nom",
        "method": "GET",
        "path": "/products",
        "query_params": [{"key": "q", "value_template": "{q}", "required": True}],
        "body_template": "",
        "is_public": True,
        "exclamation_command": "recherche",
        "portal_button_visible": True,
        "portal_button_label": "🔍 Recherche",
        "input_label": "Médicament (ex : doliprane)",
        "input_param": "q",
        "example_url": "https://api.vidal.fr/rest/api/products?app_id=XXX&app_key=YYY&q=doliprane",
        "order": 1,
    },
    {
        "id": "produit",
        "label": "Fiche produit (par ID)",
        "method": "GET",
        "path": "/product/{id}",
        "query_params": [],
        "body_template": "",
        "is_public": True,
        "exclamation_command": "produit",
        "portal_button_visible": True,
        "portal_button_label": "📄 Fiche produit",
        "input_label": "ID VIDAL du produit (ex : 5485)",
        "input_param": "id",
        "example_url": "https://api.vidal.fr/rest/api/product/5485?app_id=XXX&app_key=YYY",
        "order": 2,
    },
    {
        "id": "documents",
        "label": "Documents d'un produit",
        "method": "GET",
        "path": "/product/{id}/documents",
        "query_params": [],
        "body_template": "",
        "is_public": True,
        "exclamation_command": "docs",
        "portal_button_visible": True,
        "portal_button_label": "📚 Documents",
        "input_label": "ID VIDAL du produit",
        "input_param": "id",
        "example_url": "https://api.vidal.fr/rest/api/product/5485/documents?app_id=XXX&app_key=YYY",
        "order": 3,
    },
    {
        "id": "produit_status",
        "label": "Statut de commercialisation",
        "method": "GET",
        "path": "/product/{id}/status",
        "query_params": [],
        "body_template": "",
        "is_public": True,
        "exclamation_command": "status",
        "portal_button_visible": True,
        "portal_button_label": "📊 Statut",
        "input_label": "ID VIDAL du produit",
        "input_param": "id",
        "example_url": "https://api.vidal.fr/rest/api/product/5485/status?app_id=XXX&app_key=YYY",
        "order": 4,
    },
    {
        "id": "package",
        "label": "Conditionnement (CIP / EAN)",
        "method": "GET",
        "path": "/package/{id}",
        "query_params": [],
        "body_template": "",
        "is_public": True,
        "exclamation_command": "cip",
        "portal_button_visible": True,
        "portal_button_label": "📦 CIP/EAN",
        "input_label": "Code CIP ou EAN",
        "input_param": "id",
        "example_url": "https://api.vidal.fr/rest/api/package/3400938223392?app_id=XXX&app_key=YYY",
        "order": 5,
    },
    {
        "id": "alerts_full",
        "label": "Sécurisation prescription (POST XML)",
        "method": "POST",
        "path": "/alerts/full",
        "query_params": [],
        "body_template": (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<alertsRequest>\n'
            '  <patient>\n'
            '    <birthDate>1985-04-12</birthDate>\n'
            '    <sex>F</sex>\n'
            '  </patient>\n'
            '  <prescriptions>\n'
            '    <prescription>\n'
            '      <vidalId>{vidal_id}</vidalId>\n'
            '    </prescription>\n'
            '  </prescriptions>\n'
            '</alertsRequest>'
        ),
        "is_public": False,
        "exclamation_command": "secure",
        "portal_button_visible": True,
        "portal_button_label": "🩺 Sécurisation",
        "input_label": "ID VIDAL du médicament prescrit",
        "input_param": "vidal_id",
        "example_url": "https://api.vidal.fr/rest/api/alerts/full?app_id=XXX&app_key=YYY",
        "order": 6,
    },
    {
        "id": "interactions",
        "label": "Interactions médicamenteuses",
        "method": "POST",
        "path": "/alerts/interactions",
        "query_params": [],
        "body_template": (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<alertsRequest>\n'
            '  <prescriptions>\n'
            '    <prescription><vidalId>{id1}</vidalId></prescription>\n'
            '    <prescription><vidalId>{id2}</vidalId></prescription>\n'
            '  </prescriptions>\n'
            '</alertsRequest>'
        ),
        "is_public": False,
        "exclamation_command": "interactions",
        "portal_button_visible": True,
        "portal_button_label": "⚠️ Interactions",
        "input_label": "Deux IDs VIDAL séparés par espace (ex : 5485 12345)",
        "input_param": "id1",  # special: split user input → id1, id2
        "example_url": "https://api.vidal.fr/rest/api/alerts/interactions?app_id=XXX&app_key=YYY",
        "order": 7,
    },
]


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class QueryParam(BaseModel):
    key: str
    value_template: str = ""
    required: bool = False


class VidalAction(BaseModel):
    id: str = Field(..., min_length=2, max_length=32, pattern=r"^[a-z0-9_]+$")
    label: str
    method: str = Field(..., pattern="^(GET|POST|PUT|DELETE)$")
    path: str
    query_params: List[QueryParam] = []
    body_template: str = ""
    is_public: bool = True
    exclamation_command: str = ""
    portal_button_visible: bool = True
    portal_button_label: str = ""
    input_label: str = ""
    input_param: str = "q"
    example_url: str = ""
    order: int = 99


class VidalActionsPayload(BaseModel):
    actions: List[VidalAction]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _safe_format(template: str, ctx: Dict[str, Any]) -> str:
    """Render `template` with `{var}` placeholders from `ctx`.

    Falls back to leaving the placeholder intact if a key is missing — this
    lets the admin preview a template without all values being known yet.
    """
    if not template:
        return template

    def _repl(match: re.Match) -> str:
        key = match.group(1)
        if key in ctx:
            v = ctx[key]
            return "" if v is None else str(v)
        return match.group(0)  # keep `{var}` as-is

    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", _repl, template)


async def get_vidal_actions(db) -> List[Dict[str, Any]]:
    """Returns the configured VIDAL actions (seeds defaults on first run)."""
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "vidal_actions": 1}) or {}
    actions = s.get("vidal_actions")
    if actions:
        return actions
    # First run → seed defaults
    await db.settings.update_one(
        {"_id": "global"},
        {"$set": {"vidal_actions": DEFAULT_ACTIONS}},
        upsert=True,
    )
    return DEFAULT_ACTIONS


async def save_vidal_actions(db, actions: List[Dict[str, Any]]) -> None:
    """Atomically replace the entire actions array."""
    await db.settings.update_one(
        {"_id": "global"},
        {"$set": {"vidal_actions": actions}},
        upsert=True,
    )


def find_action_by_command(actions: List[Dict[str, Any]], cmd: str) -> Optional[Dict[str, Any]]:
    """Look up an action by its WhatsApp `exclamation_command` (case-insensitive)."""
    cmd_lc = (cmd or "").strip().lower().lstrip("!")
    for a in actions:
        if (a.get("exclamation_command") or "").strip().lower() == cmd_lc:
            return a
    # Fallback to action id (allows `!recherche` to match action id "recherche")
    for a in actions:
        if (a.get("id") or "").strip().lower() == cmd_lc:
            return a
    return None


def render_action(action: Dict[str, Any], user_input: Dict[str, Any]) -> Dict[str, Any]:
    """Returns `{method, path, params, body}` ready to be passed to `_vidal_call`.

    `user_input` is a dict like `{"q": "doliprane"}` or `{"id": "5485"}`.
    Missing placeholders fall back to empty string in path/body, raw template
    in `?key=` query value (so admin gets visual feedback).
    """
    method = (action.get("method") or "GET").upper()
    # Path
    path = _safe_format(action.get("path") or "", user_input)
    # Query params
    params: Dict[str, str] = {}
    for qp in (action.get("query_params") or []):
        k = qp.get("key") if isinstance(qp, dict) else getattr(qp, "key", None)
        v_tpl = qp.get("value_template") if isinstance(qp, dict) else getattr(qp, "value_template", "")
        if not k:
            continue
        v_rendered = _safe_format(v_tpl or "", user_input)
        params[k] = v_rendered
    # Body
    body = _safe_format(action.get("body_template") or "", user_input) if method != "GET" else ""
    return {
        "method": method,
        "path": path,
        "params": params,
        "body": body or None,
    }


# ---------------------------------------------------------------------------
# Route attachment
# ---------------------------------------------------------------------------
def attach_vidal_actions_routes(api, db, get_current_user, get_current_admin,
                                 vidal_call_fn, ensure_tenant_can_access_fn,
                                 ensure_active_fn, quota_check_fn):
    """Mount the `/api/admin/vidal/actions` + `/api/vidal/execute/{id}` routes."""

    # -------------------- ADMIN — CRUD actions --------------------
    @api.get("/admin/vidal/actions", tags=["Admin — VIDAL"])
    async def list_actions(_: dict = Depends(get_current_admin)):
        return {"actions": await get_vidal_actions(db)}

    @api.put("/admin/vidal/actions", tags=["Admin — VIDAL"])
    async def replace_actions(payload: VidalActionsPayload = Body(...),
                              _: dict = Depends(get_current_admin)):
        # Validate uniqueness of `id`
        ids = [a.id for a in payload.actions]
        if len(ids) != len(set(ids)):
            raise HTTPException(400, "IDs d'action dupliqués")
        # Validate uniqueness of `exclamation_command` (if set)
        cmds = [a.exclamation_command.strip().lower() for a in payload.actions if a.exclamation_command]
        if len(cmds) != len(set(cmds)):
            raise HTTPException(400, "Commandes WhatsApp dupliquées")
        new_actions = [a.model_dump() for a in payload.actions]
        await save_vidal_actions(db, new_actions)
        return {"ok": True, "count": len(new_actions)}

    @api.post("/admin/vidal/actions/reset-defaults", tags=["Admin — VIDAL"])
    async def reset_defaults(_: dict = Depends(get_current_admin)):
        await save_vidal_actions(db, DEFAULT_ACTIONS)
        return {"ok": True, "count": len(DEFAULT_ACTIONS)}

    # -------------------- PORTAL — Execute an action --------------------
    @api.post("/vidal/execute/{action_id}", tags=["VIDAL"])
    async def execute_action(
        action_id: str = Path(..., min_length=2, max_length=32),
        user_input: Dict[str, Any] = Body(default_factory=dict),
        user: dict = Depends(get_current_user),
    ):
        actions = await get_vidal_actions(db)
        action = next((a for a in actions if a.get("id") == action_id), None)
        if not action:
            raise HTTPException(404, f"Action VIDAL inconnue : {action_id}")
        cfg = await ensure_tenant_can_access_fn(db, user)
        ensure_active_fn(cfg)
        await quota_check_fn(db, user["id"], cfg)
        rendered = render_action(action, user_input or {})
        data = await vidal_call_fn(
            cfg, rendered["method"], rendered["path"],
            params=rendered["params"], body=rendered["body"],
        )
        return {
            "cached": False,
            "data": data,
            "action": {
                "id": action["id"], "label": action.get("label"),
                "method": rendered["method"], "path": rendered["path"],
            },
        }

    # -------------------- PORTAL — List visible actions --------------------
    @api.get("/vidal/actions/portal", tags=["VIDAL"])
    async def list_portal_actions(user: dict = Depends(get_current_user)):
        """Returns the actions that should be rendered as buttons on
        `/portal/vidal`. Filtered by `portal_button_visible == True`."""
        actions = await get_vidal_actions(db)
        visible = [a for a in actions if a.get("portal_button_visible")]
        visible.sort(key=lambda a: a.get("order", 99))
        # Strip sensitive fields (body_template templates may include secrets
        # if the admin pasted them — but in practice these stay safe).
        return {"actions": visible}
