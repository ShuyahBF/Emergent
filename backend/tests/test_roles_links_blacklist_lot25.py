"""Lot 25 — Droits et verrous :
  (3) rôle modérateur accepté sous ses deux orthographes (moderateur / moderator) ;
  (5) création de liens cryptés réservée au super-admin SAWALI ;
  (7) profil Fabricant (business_type) du client parent transmis aux utilisateurs suivis ;
  (11) liste noire IP : refus de bloquer sa propre IP, super-admin jamais bloqué.
Fonctions extraites de server.py / auth.py (ast), MongoDB simulé. Aucun réseau.
Lancer : cd backend && python -m pytest tests/test_roles_links_blacklist_lot25.py -q
"""
from __future__ import annotations

import ast
import asyncio
import ipaddress
import sys
import types
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import jwt as pyjwt
import pytest

pytest.importorskip("mongomock_motor")
from mongomock_motor import AsyncMongoMockClient  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
SERVER = BACKEND / "server.py"
AUTH = BACKEND / "auth.py"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

SUPER_EMAIL = "admin@sawalismartsystems.com"
TEST_SECRET = "secret-de-test-lot25"


class _HTTPException(Exception):
    """Remplace fastapi.HTTPException : garde le code HTTP pour les vérifications."""

    def __init__(self, status_code, detail=""):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _extract(path: Path, funcs: set, consts: set = frozenset()) -> List[ast.stmt]:
    """Extrait du fichier les fonctions (sans décorateurs) et constantes demandées."""
    tree = ast.parse(path.read_text())
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in funcs:
            node.decorator_list = []
            nodes.append(node)
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) in consts for t in node.targets):
            nodes.append(node)
    assert {getattr(n, "name", None) for n in nodes if hasattr(n, "name")} >= set(funcs)
    return nodes


def _exec(path: Path, nodes: List[ast.stmt], ns: Dict[str, Any]) -> Dict[str, Any]:
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), ns)  # noqa: S102
    return ns


@pytest.fixture()
def env(monkeypatch):
    # Faux module `auth` : server.py fait `from auth import decode_token` en local.
    fake_auth = types.ModuleType("auth")
    fake_auth.decode_token = lambda tok: pyjwt.decode(tok, TEST_SECRET, algorithms=["HS256"])
    monkeypatch.setitem(sys.modules, "auth", fake_auth)
    monkeypatch.delenv("SUPER_ADMIN_EMAIL", raising=False)
    db = AsyncMongoMockClient()["sawali_lot25"]
    loop = asyncio.new_event_loop()
    yield types.SimpleNamespace(db=db, run=loop.run_until_complete)
    loop.close()


def _server_ns(db) -> Dict[str, Any]:
    funcs = {"_is_super_admin", "integrations_build_link", "_reload_blacklist", "_client_ip_from_request",
             "_ip_in_cidr", "_request_is_super_admin", "ip_blacklist_middleware", "admin_add_blacklist",
             "_to_user_public"}
    ns = {"db": db, "os": __import__("os"), "ipaddress": ipaddress, "datetime": datetime, "timezone": timezone,
          "Optional": Optional, "Dict": Dict, "Any": Any, "List": List,
          "Depends": lambda x: None, "get_current_admin": None, "HTTPException": _HTTPException,
          "Request": None, "BuildLinkRequest": None, "BlacklistedIPCreate": None, "JSONResponse": JSONResponse,
          "_BLACKLIST_CACHE": {"nets": [], "loaded": False},
          "LINK_ACTIONS": {"login": "Connexion", "dashboard": "Tableau de bord"},
          "LINK_DEFAULT_TTL_SECONDS": 900, "LINK_JWT_SECRET": "lien", "LINK_JWT_ALGO": "HS256",
          "_pyjwt_links": pyjwt, "PUBLIC_BASE_URL": "https://exemple.test",
          "_public_base_url": lambda request=None: "https://exemple.test",
          "_uuid": lambda: uuid.uuid4().hex, "_now": lambda: datetime.now(timezone.utc).isoformat()}
    return _exec(SERVER, _extract(SERVER, funcs), ns)


def _request(ip: str, token: Optional[str] = None, path: str = "/api/me/x"):
    """Fausse requête HTTP : IP (via X-Forwarded-For), jeton Bearer et chemin."""
    headers = {"x-forwarded-for": ip}
    if token:
        headers["authorization"] = f"Bearer {token}"
    return types.SimpleNamespace(headers=headers, client=types.SimpleNamespace(host=ip),
                                 url=types.SimpleNamespace(path=path))


def _token(user_id: str) -> str:
    return pyjwt.encode({"sub": user_id}, TEST_SECRET, algorithm="HS256")


# ---------------------------------------------------------------- (3) modérateur
@pytest.mark.parametrize("role", ["moderateur", "moderator", "admin", "superviseur"])
def test_admin_or_moderator_accepts_both_spellings(env, role):
    ns = _exec(AUTH, _extract(AUTH, {"get_current_admin_or_moderator"}),
               {"Depends": lambda x: None, "get_current_user": None, "HTTPException": _HTTPException})
    user = {"id": "u", "role": role}
    assert env.run(ns["get_current_admin_or_moderator"](user=user)) is user


def test_admin_or_moderator_refuses_client(env):
    ns = _exec(AUTH, _extract(AUTH, {"get_current_admin_or_moderator"}),
               {"Depends": lambda x: None, "get_current_user": None, "HTTPException": _HTTPException})
    with pytest.raises(_HTTPException) as exc:
        env.run(ns["get_current_admin_or_moderator"](user={"id": "u", "role": "client"}))
    assert exc.value.status_code == 403


@pytest.mark.parametrize("role", ["moderateur", "moderator"])
def test_other_moderator_checks_accept_both_spellings(role):
    from routes import error_registry, smart_comm_senders
    assert error_registry._can_access({"role": role}) is True
    smart_comm_senders._require_channel_operator({"role": role})  # ne lève pas d'erreur


def test_error_registry_refuses_tracked_moderation():
    # Registre global (non cloisonné par client) : le modérateur SUIVI n'y a pas accès.
    from routes import error_registry
    assert error_registry._can_access({"role": "client", "tracked_role": "Moderation"}) is False


def test_access_summary_bypass_for_moderateur(env):
    ns = _exec(SERVER, _extract(SERVER, {"_is_super_admin", "me_access_summary"}),
               {"db": env.db, "os": __import__("os"), "Depends": lambda x: None, "get_current_user": None})
    out = env.run(ns["me_access_summary"](user={"id": "m", "role": "moderateur", "email": "m@x.bf"}))
    assert out == {"has_documents": True, "has_formations": True, "has_forms": True}


# ---------------------------------------------------------------- (5) liens cryptés
def test_build_link_refused_for_plain_admin(env):
    ns = _server_ns(env.db)
    payload = types.SimpleNamespace(action="login", client_code="C1", username="x", target_id=None, ttl_seconds=None)
    with pytest.raises(_HTTPException) as exc:
        env.run(ns["integrations_build_link"](_request("1.1.1.1"), payload, user={"role": "admin", "email": "admin@client.bf"}))
    assert exc.value.status_code == 403


def test_build_link_allowed_for_super_admin(env):
    ns = _server_ns(env.db)
    payload = types.SimpleNamespace(action="login", client_code="C1", username="x", target_id=None, ttl_seconds=None)
    out = env.run(ns["integrations_build_link"](_request("1.1.1.1"), payload, user={"role": "admin", "email": SUPER_EMAIL.upper()}))
    assert out["url"].startswith("https://exemple.test/launch?t=")
    assert pyjwt.decode(out["token"], "lien", algorithms=["HS256"])["action"] == "login"


# ---------------------------------------------------------------- (7) profil Fabricant
def test_auth_me_returns_parent_business_type_for_tracked_user(env):
    from fastapi import APIRouter
    from routes.auth import attach_auth_routes
    ns = _server_ns(env.db)
    env.run(env.db.users.insert_one({"id": "t-fab", "business_type": "fabricant"}))
    api = APIRouter()
    helpers = {k: None for k in ("verify_password", "hash_password", "verify_recaptcha", "generate_otp",
                                 "generate_session_token", "send_otp_email", "create_access_token", "_uuid", "_now")}
    helpers.update({"get_current_user": lambda: None, "_to_user_public": ns["_to_user_public"]})
    attach_auth_routes(api, db=env.db, helpers=helpers)
    auth_me = next(r.endpoint for r in api.routes if getattr(r, "path", "") == "/auth/me")
    base = {"email": "a@x.bf", "full_name": "A", "role": "client", "created_at": "2026-01-01"}
    tracked = {**base, "id": "u-suivi", "tracked_role": "Edition", "parent_client_id": "t-fab", "client_id": "t-fab"}
    assert env.run(auth_me(user=tracked))["business_type"] == "fabricant"
    # Compte principal (non suivi) : sa propre valeur est conservée.
    owner = {**base, "id": "t-autre", "business_type": "distributeur"}
    assert env.run(auth_me(user=owner))["business_type"] == "distributeur"


# ---------------------------------------------------------------- (11) liste noire IP
def test_ip_in_cidr():
    ns = _server_ns(None)
    assert ns["_ip_in_cidr"]("10.0.0.5", "10.0.0.0/24") is True
    assert ns["_ip_in_cidr"]("10.0.0.5", "10.0.0.5") is True
    assert ns["_ip_in_cidr"]("10.0.1.5", "10.0.0.0/24") is False
    assert ns["_ip_in_cidr"]("pas-une-ip", "10.0.0.0/24") is False


def test_cannot_blacklist_own_ip(env):
    ns = _server_ns(env.db)
    for cidr in ("41.207.1.10", "41.207.1.0/24"):
        with pytest.raises(_HTTPException) as exc:
            env.run(ns["admin_add_blacklist"](types.SimpleNamespace(cidr=cidr, reason=""), _request("41.207.1.10"), _={}))
        assert exc.value.status_code == 400
        assert "votre propre adresse IP" in exc.value.detail
    assert env.run(env.db.blacklisted_ips.count_documents({})) == 0


def test_can_blacklist_other_ip(env):
    ns = _server_ns(env.db)
    doc = env.run(ns["admin_add_blacklist"](types.SimpleNamespace(cidr="5.5.5.5", reason="spam"), _request("41.207.1.10"), _={}))
    assert doc["cidr"] == "5.5.5.5"
    assert env.run(env.db.blacklisted_ips.count_documents({})) == 1


def _call_middleware(env, ns, request):
    async def _next(req):
        return "SUITE"
    return env.run(ns["ip_blacklist_middleware"](request, _next))


def test_middleware_blocks_listed_ip_but_never_super_admin(env):
    ns = _server_ns(env.db)
    env.run(env.db.users.insert_many([{"id": "sa", "email": SUPER_EMAIL}, {"id": "adm", "email": "admin@client.bf"}]))
    env.run(env.db.blacklisted_ips.insert_one({"id": "b1", "cidr": "9.9.9.0/24"}))
    # IP bloquée, sans jeton ou avec le jeton d'un admin ordinaire → 403
    assert isinstance(_call_middleware(env, ns, _request("9.9.9.9")), JSONResponse)
    blocked = _call_middleware(env, ns, _request("9.9.9.9", _token("adm")))
    assert isinstance(blocked, JSONResponse) and blocked.status_code == 403
    # Super-admin : jamais bloqué
    assert _call_middleware(env, ns, _request("9.9.9.9", _token("sa"))) == "SUITE"
    # Jeton invalide → traité comme anonyme (bloqué)
    assert isinstance(_call_middleware(env, ns, _request("9.9.9.9", "jeton-invalide")), JSONResponse)
    # IP non bloquée → passe
    assert _call_middleware(env, ns, _request("8.8.8.8")) == "SUITE"
