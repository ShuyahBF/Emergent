"""Lot 55 — Dernière connexion et adresse IP des utilisateurs suivis, historique des connexions,
blocage / autorisation d'une IP par compte (et globalement pour le super-admin).
MongoDB simulé (mongomock_motor), vrais jetons JWT, vraie dépendance auth.get_current_user,
vraies routes de connexion (mot de passe, code e-mail, code WhatsApp).
Lancer : cd backend && python -m pytest tests/test_lot55_connexions_ip.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot55")

import jwt  # noqa: E402
from fastapi import APIRouter, Depends, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import abonnement_acces as abo  # noqa: E402
import auth  # noqa: E402
import connexions_ip as cip  # noqa: E402
import controle_acces  # noqa: E402
import cycle_vie_abonnements as cva  # noqa: E402
import maintenance_plateforme as mp  # noqa: E402
import sessions_comptes as sess  # noqa: E402
from ip_client import ip_reelle  # noqa: E402
from routes.auth import attach_auth_routes  # noqa: E402
from routes.connexions_ip import router as r_connexions  # noqa: E402
from routes.wa_otp_login_9o import setup_wa_otp_routes  # noqa: E402

UTC = timezone.utc
SUPER = "admin@sawalismartsystems.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"
IP_A, IP_B, IP_ADMIN = "41.138.10.1", "102.67.5.9", "196.28.0.7"
MESSAGE = "Connexion refusée depuis cette adresse. Contactez l'administrateur."


@pytest.fixture()
def env(monkeypatch):
    b = mongomock_motor.AsyncMongoMockClient()[f"lot55_{time.time_ns()}"]
    for mod in (auth, mp, sess, abo, cva):
        monkeypatch.setattr(mod, "db", b)
    monkeypatch.delenv("SUPER_ADMIN_EMAIL", raising=False)
    mp.vider_cache()
    sess.vider_caches()
    sess._index_ok["fait"] = False
    abo.vider_cache()
    cip.vider_cache()
    cip._index_ok["fait"] = False

    app = FastAPI()
    app.add_exception_handler(controle_acces.RefusAcces, controle_acces.gestionnaire_refus)
    api = APIRouter(prefix="/api")

    @api.get("/donnees")
    async def donnees(user: dict = Depends(auth.get_current_user)):
        return {"ok": True, "user": user["id"]}

    async def _captcha(*a, **k):
        return {"success": True, "reason": ""}

    async def _envoi(*a, **k):
        return True

    attach_auth_routes(api, db=b, helpers={
        "verify_password": lambda p, h: p == "bon-mot-de-passe", "hash_password": lambda p: "h",
        "verify_recaptcha": _captcha, "generate_otp": lambda: "123456",
        "generate_session_token": lambda: f"s-{time.time_ns()}", "send_otp_email": _envoi,
        "create_access_token": auth.create_access_token, "get_current_user": auth.get_current_user,
        "_to_user_public": lambda u: {k: u.get(k) for k in ("id", "email", "full_name", "role", "created_at")},
        "_uuid": lambda: str(time.time_ns()), "_now": lambda: datetime.now(UTC).isoformat(),
        "refuser_si_maintenance": mp.refuser_si_maintenance, "create_session_token": auth.create_session_token,
        "refuser_si_cycle_vie": cva.refuser_connexion,
    })

    async def _jeton_wa(u, request=None):   # comme server_parts/p20 (_create_jwt_token_wrapper)
        return await auth.create_session_token(u, request, methode="code_whatsapp")

    setup_wa_otp_routes(api, b, auth.get_current_user, _jeton_wa, lambda p: "h")
    api.include_router(r_connexions)
    app.include_router(api)

    e = SimpleNamespace(db=b, client=TestClient(app))
    boucle = asyncio.new_event_loop()
    e.run = boucle.run_until_complete
    e.run(b.users.insert_many([
        {"id": "super", "email": SUPER, "full_name": "Super Admin", "role": "admin", "account_status": "active",
         "password_hash": "h", "created_at": "2026-01-01"},
        {"id": "adm2", "email": "admin2@sawali.bf", "full_name": "Admin 2", "role": "admin",
         "account_status": "active", "password_hash": "h", "created_at": "2026-01-01"},
        {"id": "sup", "email": "sup@sawali.bf", "full_name": "Superviseur", "role": "superviseur",
         "account_status": "active", "password_hash": "h", "created_at": "2026-01-01"},
        {"id": "pharma", "email": "pharma@x.bf", "full_name": "Pharmacie", "role": "client",
         "account_status": "active", "password_hash": "h", "created_at": "2026-01-01"},
        {"id": "caisse", "email": "caisse@x.bf", "full_name": "Caissière", "role": "client", "tracked_role": "Caissier",
         "parent_client_id": "pharma", "client_id": "pharma", "account_status": "active", "password_hash": "h", "created_at": "2026-01-01",
         "phone_digits": "22670000001", "whatsapp": "+22670000001"},
        {"id": "compta", "email": "compta@x.bf", "full_name": "Comptable", "role": "client",
         "tracked_role": "Comptable", "parent_client_id": "pharma", "client_id": "pharma",
         "account_status": "active", "password_hash": "h", "created_at": "2026-01-01"},
    ]))
    e.run(b.tracked_users.insert_many([
        {"id": "tu-caisse", "client_id": "pharma", "name": "Caissière", "email": "caisse@x.bf",
         "user_account_id": "caisse", "status": "active"},
        {"id": "tu-compta", "client_id": "pharma", "name": "Comptable", "email": "compta@x.bf",
         "user_account_id": "compta", "status": "active"},
        {"id": "tu-sans-compte", "client_id": "pharma", "name": "Sans accès", "status": "active"},
        # Fiche qui pointe vers le compte du super-admin (garde-fou : jamais bloqué)
        {"id": "tu-super", "client_id": "pharma", "name": "Super", "email": SUPER, "user_account_id": "super",
         "status": "active"},
    ]))
    yield e
    boucle.close()


def jeton(uid, role="client"):
    now = int(time.time())
    return jwt.encode({"sub": uid, "role": role, "iat": now, "exp": now + 3600}, auth.JWT_SECRET,
                      algorithm=auth.JWT_ALGORITHM)


def h(tok=None, ip=IP_ADMIN):
    d = {"User-Agent": UA, "X-Forwarded-For": f"{ip}, 10.0.0.1"}
    if tok:
        d["Authorization"] = f"Bearer {tok}"
    return d


def connexion_code_email(env, uid, ip):
    """Connexion complète : mot de passe (étape 1) puis code e-mail (étape 2)."""
    email = env.run(env.db.users.find_one({"id": uid}))["email"]
    r1 = env.client.post("/api/auth/login", json={"email": email, "password": "bon-mot-de-passe"}, headers=h(ip=ip))
    if r1.status_code != 200:
        return r1
    return env.client.post("/api/auth/verify-otp", json={"session_token": r1.json()["session_token"], "code": "123456"},
                           headers=h(ip=ip))


def connexion_whatsapp(env, ip, code="654321"):
    env.run(env.db.wa_otp_requests.update_one({"msisdn": "22670000001"}, {"$set": {
        "msisdn": "22670000001", "code": "654321", "attempts": 0,
        "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()}}, upsert=True))
    return env.client.post("/api/auth/wa-otp/verify", json={"msisdn": "22670000001", "code": code}, headers=h(ip=ip))


# ---------------------------------------------------------------------------
# 1. IP réelle derrière Render
# ---------------------------------------------------------------------------
def test_ip_lue_dans_x_forwarded_for(env):
    req = SimpleNamespace(headers={"x-forwarded-for": " 41.1.2.3 , 10.0.0.1, 10.0.0.2"},
                          client=SimpleNamespace(host="10.9.9.9"))
    assert ip_reelle(req) == "41.1.2.3"
    assert ip_reelle(SimpleNamespace(headers={}, client=SimpleNamespace(host="10.9.9.9"))) == "10.9.9.9"
    assert ip_reelle(SimpleNamespace(headers={}, client=None)) == "" and ip_reelle(None) == ""
    # Les anciennes fonctions passent par la fonction unique
    assert sess.ip_de(req) == "41.1.2.3"
    texte = (RACINE / "server.py").read_text(encoding="utf-8")
    assert "from ip_client import ip_reelle\n    return ip_reelle(request)" in texte
    # La connexion note l'IP du visiteur (premier élément), pas celle du proxy de Render
    assert connexion_code_email(env, "caisse", IP_A).status_code == 200
    j = env.run(env.db.connexions_journal.find_one({"user_id": "caisse"}, {"_id": 0}))
    assert j["ip"] == IP_A and j["appareil"] == "Chrome · Windows" and j["methode"] == "code_email"
    assert j["resultat"] == "reussie" and j["sid"]
    s = env.run(env.db.sessions_comptes.find_one({"id": j["sid"]}, {"_id": 0}))
    assert s["ip"] == IP_A


def test_index_journal_user_date_et_ttl_180_jours(env):
    env.run(cip.assurer_index())
    idx = env.run(env.db.connexions_journal.index_information())
    assert idx["user_date"]["key"] == [("user_id", 1), ("date", -1)]
    assert idx["ttl_date"]["expireAfterSeconds"] == 180 * 86400


# ---------------------------------------------------------------------------
# 2. Dernière connexion et IP sur la page
# ---------------------------------------------------------------------------
def test_derniere_connexion_et_ip_affichees(env):
    c = env.client
    assert connexion_code_email(env, "caisse", IP_B).status_code == 200
    time.sleep(0.01)
    assert connexion_code_email(env, "caisse", IP_A).status_code == 200
    # Une tentative refusée (mauvais mot de passe) ne change pas la « dernière connexion »
    r = c.post("/api/auth/login", json={"email": "caisse@x.bf", "password": "faux"}, headers=h(ip="8.8.8.8"))
    assert r.status_code == 401
    r = c.get("/api/admin/tracked-users/connexions", headers=h(jeton("adm2", "admin")))
    assert r.status_code == 200
    items = r.json()["items"]
    assert items["tu-caisse"]["ip"] == IP_A and items["tu-caisse"]["derniere_connexion"]
    assert items["tu-caisse"]["derniere_connexion"].endswith("+00:00")     # fuseau explicite
    assert items["tu-caisse"]["ip_statut"] is None
    assert items["tu-compta"]["derniere_connexion"] is None and items["tu-sans-compte"]["compte"] is False
    refus = env.run(env.db.connexions_journal.find_one({"resultat": "refusee"}, {"_id": 0}))
    assert refus["motif"] == "Mot de passe incorrect" and refus["ip"] == "8.8.8.8" and refus["methode"] == "mot_de_passe"


# ---------------------------------------------------------------------------
# 3. Historique paginé
# ---------------------------------------------------------------------------
def test_historique_pagine_recent_d_abord_et_filtre_ip(env):
    base = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
    env.run(env.db.connexions_journal.insert_many([
        {"id": f"j{i}", "user_id": "caisse", "date": base + timedelta(minutes=i),
         "ip": IP_A if i % 2 else IP_B, "appareil": "Chrome · Windows", "methode": "code_email",
         "resultat": "reussie", "sid": f"s{i}"} for i in range(120)]))
    c, tok = env.client, jeton("adm2", "admin")
    p1 = c.get("/api/admin/tracked-users/tu-caisse/connexions", headers=h(tok)).json()
    assert p1["total"] == 120 and p1["pages"] == 3 and p1["par_page"] == 50 and len(p1["items"]) == 50
    assert p1["items"][0]["id"] == "j119" and p1["items"][49]["id"] == "j70"
    p3 = c.get("/api/admin/tracked-users/tu-caisse/connexions?page=3", headers=h(tok)).json()
    assert len(p3["items"]) == 20 and p3["items"][-1]["id"] == "j0"
    f = c.get(f"/api/admin/tracked-users/tu-caisse/connexions?ip={IP_A}", headers=h(tok)).json()
    assert f["total"] == 60 and all(x["ip"] == IP_A for x in f["items"])
    assert p1["ip_courante"] == IP_ADMIN and p1["compte"]["email"] == "caisse@x.bf"
    assert p1["peut_bloquer_global"] is False
    vide = c.get("/api/admin/tracked-users/tu-sans-compte/connexions", headers=h(tok)).json()
    assert vide["compte"] is None and vide["items"] == []


# ---------------------------------------------------------------------------
# 4. Blocage : 3 méthodes refusées, sessions fermées, requêtes suivantes en 401
# ---------------------------------------------------------------------------
def test_blocage_refuse_les_trois_methodes_et_ferme_les_sessions(env):
    c = env.client
    tok_a = connexion_code_email(env, "caisse", IP_A).json()["access_token"]
    tok_b = connexion_code_email(env, "caisse", IP_B).json()["access_token"]
    tok_compta = connexion_code_email(env, "compta", IP_A).json()["access_token"]
    assert c.get("/api/donnees", headers=h(tok_a, ip=IP_A)).status_code == 200
    r = c.post("/api/admin/tracked-users/tu-caisse/connexions/bloquer", json={"ip": IP_A},
               headers=h(jeton("adm2", "admin")))
    assert r.status_code == 200, r.text
    assert r.json()["sessions_fermees"] == 1 and r.json()["portee"] == "compte"
    # Session ouverte depuis IP_A : fermée (401 avec le message)
    r = c.get("/api/donnees", headers=h(tok_a, ip=IP_A))
    assert r.status_code == 401 and r.json()["detail"] == MESSAGE and r.json()["code"] == "session_ip_bloquee"
    # Session du même compte ouverte depuis IP_B : intacte, mais une requête venant de IP_A reçoit 401
    assert c.get("/api/donnees", headers=h(tok_b, ip=IP_B)).status_code == 200
    r = c.get("/api/donnees", headers=h(tok_b, ip=IP_A))
    assert r.status_code == 401 and r.json()["code"] == "session_ip_bloquee"
    # Un autre compte depuis IP_A n'est pas concerné
    assert c.get("/api/donnees", headers=h(tok_compta, ip=IP_A)).status_code == 200
    # Méthode 1 : mot de passe
    r = c.post("/api/auth/login", json={"email": "caisse@x.bf", "password": "bon-mot-de-passe"}, headers=h(ip=IP_A))
    assert r.status_code == 403 and r.json()["detail"] == MESSAGE
    # Méthode 2 : code e-mail (code demandé avant le blocage)
    env.run(env.db.otps.insert_one({"id": "o1", "user_id": "caisse", "session_token": "st-avant", "code": "123456",
                                    "used": False, "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()}))
    r = c.post("/api/auth/verify-otp", json={"session_token": "st-avant", "code": "123456"}, headers=h(ip=IP_A))
    assert r.status_code == 403 and r.json()["detail"] == MESSAGE
    # Méthode 3 : code WhatsApp
    r = connexion_whatsapp(env, IP_A)
    assert r.status_code == 403 and r.json()["detail"] == MESSAGE
    # Depuis une autre adresse, les trois méthodes fonctionnent
    assert connexion_code_email(env, "caisse", IP_B).status_code == 200
    assert connexion_whatsapp(env, IP_B).status_code == 200
    # Refus notés avec le motif « IP bloquée » (mot de passe, code e-mail, code WhatsApp)
    refus = env.run(env.db.connexions_journal.find({"user_id": "caisse", "motif": "IP bloquée"}, {"_id": 0}).to_list(10))
    assert sorted(x["methode"] for x in refus) == ["code_email", "code_whatsapp", "mot_de_passe"]
    assert all(x["resultat"] == "refusee" and x["ip"] == IP_A for x in refus)
    # Page : la dernière connexion réussie de la Caissière vient maintenant de IP_B ; le blocage de IP_A
    # ne concerne que la Caissière (pas de badge sur la fiche Comptable, connectée depuis IP_A)
    items = c.get("/api/admin/tracked-users/connexions", headers=h(jeton("adm2", "admin"))).json()["items"]
    assert items["tu-caisse"]["ip"] == IP_B and items["tu-caisse"]["ip_statut"] is None
    assert items["tu-compta"]["ip"] == IP_A and items["tu-compta"]["ip_statut"] is None
    hist = c.get("/api/admin/tracked-users/tu-caisse/connexions", headers=h(jeton("adm2", "admin"))).json()
    assert [b["ip"] for b in hist["bloquees"]] == [IP_A] and hist["bloquees"][0]["portee"] == "compte"
    # Action journalisée : qui, quand, IP, compte, portée
    act = env.run(env.db.connexions_ip_actions.find_one({"action": "BLOQUER"}, {"_id": 0}))
    assert act["par"]["email"] == "admin2@sawali.bf" and act["ip"] == IP_A and act["user_id"] == "caisse"
    assert act["portee"] == "compte" and act["ip_admin"] == IP_ADMIN and act["date"]


def test_badge_bloquee_sur_la_derniere_ip(env):
    connexion_code_email(env, "caisse", IP_A)
    c, tok = env.client, jeton("adm2", "admin")
    assert c.post("/api/admin/tracked-users/tu-caisse/connexions/bloquer", json={"ip": IP_A}, headers=h(tok)).status_code == 200
    items = c.get("/api/admin/tracked-users/connexions", headers=h(tok)).json()["items"]
    assert items["tu-caisse"]["ip"] == IP_A and items["tu-caisse"]["ip_statut"] == "bloquee"


# ---------------------------------------------------------------------------
# 5. Autorisation : accès rétabli, IP de confiance
# ---------------------------------------------------------------------------
def test_autorisation_retablit_l_acces(env):
    c, tok = env.client, jeton("adm2", "admin")
    connexion_code_email(env, "caisse", IP_A)
    c.post("/api/admin/tracked-users/tu-caisse/connexions/bloquer", json={"ip": IP_A}, headers=h(tok))
    assert connexion_code_email(env, "caisse", IP_A).status_code == 403
    r = c.post("/api/admin/tracked-users/tu-caisse/connexions/autoriser", json={"ip": IP_A}, headers=h(tok))
    assert r.status_code == 200 and r.json()["confiance"] is True and r.json()["portee"] == "compte"
    r = connexion_code_email(env, "caisse", IP_A)
    assert r.status_code == 200
    assert c.get("/api/donnees", headers=h(r.json()["access_token"], ip=IP_A)).status_code == 200
    assert connexion_whatsapp(env, IP_A).status_code == 200
    items = c.get("/api/admin/tracked-users/connexions", headers=h(tok)).json()["items"]
    assert items["tu-caisse"]["ip_statut"] == "confiance"
    hist = c.get("/api/admin/tracked-users/tu-caisse/connexions", headers=h(tok)).json()
    assert hist["bloquees"] == [] and [x["ip"] for x in hist["confiance"]] == [IP_A]
    assert [a["action"] for a in hist["actions"]] == ["AUTORISER", "BLOQUER"]
    # IP invalide
    assert c.post("/api/admin/tracked-users/tu-caisse/connexions/autoriser", json={"ip": "pas-une-ip"},
                  headers=h(tok)).status_code == 400


# ---------------------------------------------------------------------------
# 6. Blocage global réservé au super-admin
# ---------------------------------------------------------------------------
def test_blocage_global_reserve_au_super_admin(env):
    c = env.client
    tok_compta = connexion_code_email(env, "compta", IP_A).json()["access_token"]
    r = c.post("/api/admin/tracked-users/tu-caisse/connexions/bloquer", json={"ip": IP_A, "globale": True},
               headers=h(jeton("adm2", "admin")))
    assert r.status_code == 403
    assert c.post("/api/admin/tracked-users/tu-caisse/connexions/bloquer", json={"ip": IP_A, "globale": True},
                  headers=h(jeton("sup", "superviseur"))).status_code == 403
    assert c.get("/api/admin/tracked-users/tu-caisse/connexions",
                 headers=h(jeton("super", "admin"))).json()["peut_bloquer_global"] is True
    r = c.post("/api/admin/tracked-users/tu-caisse/connexions/bloquer", json={"ip": IP_A, "globale": True},
               headers=h(jeton("super", "admin")))
    assert r.status_code == 200 and r.json()["portee"] == "globale"
    # Toute la plateforme : un autre compte (Comptable) depuis IP_A est refusé et sa session fermée
    assert c.get("/api/donnees", headers=h(tok_compta, ip=IP_A)).status_code == 401
    assert connexion_code_email(env, "compta", IP_A).status_code == 403
    # … sauf le super-admin, jamais bloqué
    sup = env.run(env.db.users.find_one({"id": "super"}, {"_id": 0}))
    tok_super = env.run(auth.create_session_token(sup, SimpleNamespace(headers={"x-forwarded-for": IP_A}, client=None),
                                                  methode="code_email"))
    assert c.get("/api/donnees", headers=h(tok_super, ip=IP_A)).status_code == 200
    # Lever un blocage global : réservé au super-admin
    assert c.post("/api/admin/tracked-users/tu-compta/connexions/autoriser", json={"ip": IP_A},
                  headers=h(jeton("adm2", "admin"))).status_code == 403
    r = c.post("/api/admin/tracked-users/tu-compta/connexions/autoriser", json={"ip": IP_A},
               headers=h(jeton("super", "admin")))
    assert r.status_code == 200 and r.json()["portee"] == "globale"
    assert connexion_code_email(env, "compta", IP_A).status_code == 200
    assert connexion_code_email(env, "caisse", IP_A).status_code == 200
    act = env.run(env.db.connexions_ip_actions.find({}, {"_id": 0}).sort("date", 1).to_list(10))
    assert [(a["action"], a["portee"]) for a in act] == [("BLOQUER", "globale"), ("AUTORISER", "globale")]


# ---------------------------------------------------------------------------
# 7. Garde-fous
# ---------------------------------------------------------------------------
def test_garde_fous_propre_ip_et_super_admin(env):
    c, tok = env.client, jeton("adm2", "admin")
    # Sa propre IP (celle de la session en cours de l'Admin)
    r = c.post("/api/admin/tracked-users/tu-caisse/connexions/bloquer", json={"ip": IP_ADMIN}, headers=h(tok))
    assert r.status_code == 400 and "propre session" in r.json()["detail"]
    r = c.post("/api/admin/tracked-users/tu-caisse/connexions/bloquer", json={"ip": IP_ADMIN, "globale": True},
               headers=h(jeton("super", "admin")))
    assert r.status_code == 400
    # Le super-admin ne peut jamais être bloqué (même par lui-même)
    for qui in ("adm2", "super"):
        r = c.post("/api/admin/tracked-users/tu-super/connexions/bloquer", json={"ip": IP_A}, headers=h(jeton(qui, "admin")))
        assert r.status_code == 403 and "super-administrateur" in r.json()["detail"]
    assert env.run(env.db.connexions_ip_regles.count_documents({})) == 0
    # Fiche sans compte de connexion
    assert c.post("/api/admin/tracked-users/tu-sans-compte/connexions/bloquer", json={"ip": IP_A},
                  headers=h(tok)).status_code == 404


# ---------------------------------------------------------------------------
# 8. Droits
# ---------------------------------------------------------------------------
def test_droits_client_403_admin_et_superviseur_autorises(env):
    c = env.client
    for tok in (jeton("pharma"), jeton("caisse")):
        assert c.get("/api/admin/tracked-users/connexions", headers=h(tok)).status_code == 403
        assert c.get("/api/admin/tracked-users/tu-caisse/connexions", headers=h(tok)).status_code == 403
        assert c.post("/api/admin/tracked-users/tu-caisse/connexions/bloquer", json={"ip": IP_A},
                      headers=h(tok)).status_code == 403
        assert c.post("/api/admin/tracked-users/tu-caisse/connexions/autoriser", json={"ip": IP_A},
                      headers=h(tok)).status_code == 403
    assert c.get("/api/admin/tracked-users/connexions", headers=h(jeton("sup", "superviseur"))).status_code == 200
    r = c.post("/api/admin/tracked-users/tu-caisse/connexions/bloquer", json={"ip": IP_A},
               headers=h(jeton("sup", "superviseur")))
    assert r.status_code == 200
    # Superviseur rattaché à un autre client : la fiche n'est pas dans son périmètre
    env.run(env.db.users.insert_one({"id": "sup-autre", "email": "sup@autre.bf", "role": "superviseur",
                                     "client_id": "autre-client", "account_status": "active"}))
    tok = jeton("sup-autre", "superviseur")
    assert c.get("/api/admin/tracked-users/tu-caisse/connexions", headers=h(tok)).status_code == 404
    assert c.post("/api/admin/tracked-users/tu-caisse/connexions/autoriser", json={"ip": IP_A},
                  headers=h(tok)).status_code == 404
    assert c.get("/api/admin/tracked-users/connexions", headers=h(tok)).json()["items"] == {}


def test_voir_en_tant_que_non_concerne_par_le_blocage(env):
    """Une session « Voir en tant que » vient de l'IP de l'Admin : jamais refusée par un blocage du compte."""
    c = env.client
    c.post("/api/admin/tracked-users/tu-caisse/connexions/bloquer", json={"ip": IP_A}, headers=h(jeton("adm2", "admin")))
    now = int(time.time())
    imp = jwt.encode({"sub": "caisse", "role": "client", "iat": now, "exp": now + 600, "imp": "adm2", "ro": True},
                     auth.JWT_SECRET, algorithm=auth.JWT_ALGORITHM)
    assert c.get("/api/donnees", headers=h(imp, ip=IP_A)).status_code == 200
    # Jeton d'avant le lot 50 (sans session) : l'IP bloquée est quand même refusée
    assert c.get("/api/donnees", headers=h(jeton("caisse"), ip=IP_A)).status_code == 401


# ---------------------------------------------------------------------------
# 9. « C'est un site que je veux bloquer » : libellé du site, sites bloqués (super-admin)
# ---------------------------------------------------------------------------
FRONT = RACINE.parent / "frontend" / "src" / "pages" / "admin"


def test_libelle_du_site_au_blocage_et_a_l_autorisation(env):
    c, tok = env.client, jeton("adm2", "admin")
    connexion_code_email(env, "caisse", IP_A)
    r = c.post("/api/admin/tracked-users/tu-caisse/connexions/bloquer",
               json={"ip": IP_A, "libelle": "  Pharmacie X — Wi-Fi accueil  "}, headers=h(tok))
    assert r.status_code == 200 and r.json()["libelle"] == "Pharmacie X — Wi-Fi accueil"
    hist = c.get("/api/admin/tracked-users/tu-caisse/connexions", headers=h(tok)).json()
    assert hist["bloquees"][0]["libelle"] == "Pharmacie X — Wi-Fi accueil"
    assert hist["actions"][0]["libelle"] == "Pharmacie X — Wi-Fi accueil"
    # Bulle du badge sur la page : libellé et portée renvoyés avec le statut de l'IP
    item = c.get("/api/admin/tracked-users/connexions", headers=h(tok)).json()["items"]["tu-caisse"]
    assert item["ip_statut"] == "bloquee" and item["ip_libelle"] == "Pharmacie X — Wi-Fi accueil"
    assert item["ip_portee"] == "compte"
    # Libellé facultatif : sans libellé, l'autorisation garde celui connu ; un nouveau libellé le remplace
    r = c.post("/api/admin/tracked-users/tu-caisse/connexions/autoriser", json={"ip": IP_A}, headers=h(tok))
    assert r.status_code == 200 and r.json()["libelle"] is None
    hist = c.get("/api/admin/tracked-users/tu-caisse/connexions", headers=h(tok)).json()
    assert hist["confiance"][0]["libelle"] == "Pharmacie X — Wi-Fi accueil"
    c.post("/api/admin/tracked-users/tu-caisse/connexions/autoriser", json={"ip": IP_A, "libelle": "Box du dépôt"},
           headers=h(tok))
    item = c.get("/api/admin/tracked-users/connexions", headers=h(tok)).json()["items"]["tu-caisse"]
    assert item["ip_statut"] == "confiance" and item["ip_libelle"] == "Box du dépôt"
    # Libellé borné à 120 caractères
    assert c.post("/api/admin/tracked-users/tu-caisse/connexions/bloquer", json={"ip": IP_B, "libelle": "x" * 121},
                  headers=h(tok)).status_code == 422


def test_sites_bloques_liste_super_admin_avec_tentatives_refusees(env):
    c, tok_super = env.client, jeton("super", "admin")
    r = c.post("/api/admin/tracked-users/tu-caisse/connexions/bloquer",
               json={"ip": IP_A, "globale": True, "libelle": "Cybercafé Gounghin"}, headers=h(tok_super))
    assert r.status_code == 200 and r.json()["portee"] == "globale"
    # Blocage limité à un compte : n'apparaît pas dans les sites bloqués de la plateforme
    c.post("/api/admin/tracked-users/tu-caisse/connexions/bloquer", json={"ip": IP_B}, headers=h(jeton("adm2", "admin")))
    # Tentatives refusées depuis le blocage (deux comptes différents, deux méthodes)
    assert connexion_code_email(env, "caisse", IP_A).status_code == 403
    assert connexion_code_email(env, "compta", IP_A).status_code == 403
    assert connexion_whatsapp(env, IP_A).status_code == 403
    items = c.get("/api/admin/connexions/sites-bloques", headers=h(tok_super)).json()["items"]
    assert len(items) == 1
    site = items[0]
    assert site["ip"] == IP_A and site["libelle"] == "Cybercafé Gounghin" and site["par"] == SUPER
    assert site["date"] and site["tentatives_refusees"] == 3
    # Badge de la page : bulle avec le libellé et la portée globale
    connexion_code_email(env, "compta", IP_B)
    hist = c.get("/api/admin/tracked-users/tu-compta/connexions", headers=h(tok_super)).json()
    assert [(b["ip"], b["portee"], b["libelle"]) for b in hist["bloquees"]] == [(IP_A, "globale", "Cybercafé Gounghin")]
    # Réservé au super-admin
    for tok in (jeton("adm2", "admin"), jeton("sup", "superviseur"), jeton("pharma")):
        assert c.get("/api/admin/connexions/sites-bloques", headers=h(tok)).status_code == 403
        assert c.post("/api/admin/connexions/sites-bloques/autoriser", json={"ip": IP_A}, headers=h(tok)).status_code == 403
    # « Autoriser » depuis la liste : blocage global levé, accès rétabli, action journalisée
    r = c.post("/api/admin/connexions/sites-bloques/autoriser", json={"ip": IP_A}, headers=h(tok_super))
    assert r.status_code == 200 and r.json()["libelle"] == "Cybercafé Gounghin"
    assert c.get("/api/admin/connexions/sites-bloques", headers=h(tok_super)).json()["items"] == []
    assert connexion_code_email(env, "compta", IP_A).status_code == 200
    assert c.post("/api/admin/connexions/sites-bloques/autoriser", json={"ip": IP_A}, headers=h(tok_super)).status_code == 404
    act = env.run(env.db.connexions_ip_actions.find_one({"action": "AUTORISER", "portee": "globale"}, {"_id": 0}))
    assert act["par"]["email"] == SUPER and act["ip"] == IP_A and act["user_id"] is None
    # Le blocage du compte (IP_B) reste en place
    assert connexion_code_email(env, "caisse", IP_B).status_code == 403


def test_fenetre_case_globale_cochee_par_defaut_et_aide_lieu():
    """Interface : case « pour tous les comptes » cochée par défaut pour le super-admin seulement,
    champ « Libellé du site », texte d'aide, bouton « Sites bloqués » en haut de la page."""
    fen = (FRONT / "sections" / "HistoriqueConnexionsDialog.jsx").read_text(encoding="utf-8")
    assert "setGlobale(!!donnees.peut_bloquer_global)" in fen
    assert "Une adresse IP correspond à un lieu ou à un réseau (Wi-Fi, box), pas à une personne." in fen
    assert "Libellé du site (facultatif)" in fen and "libelle: libelle.trim() || null" in fen
    assert "Sites bloqués (toute la plateforme)" in fen and "tentatives_refusees" in fen
    page = (FRONT / "AdminTrackedUsers.jsx").read_text(encoding="utf-8")
    assert "btn-sites-bloques" in page and "/admin/connexions/sites-bloques" in page
    assert "ip_libelle" in page
