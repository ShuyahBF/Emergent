"""Lot 50 — Maintenance de la plateforme (déconnexion de tous les utilisateurs, R8), période de
grâce puis coupure de l'abonnement (A), sessions limitées par compte et inactivité contrôlée par
le serveur (B), date de la dernière sauvegarde (D).
MongoDB simulé (mongomock_motor), vrais jetons JWT, vraie dépendance auth.get_current_user.
Lancer : cd backend && python -m pytest tests/test_lot50_maintenance_sessions_abonnements.py -q
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot50")

import jwt  # noqa: E402
from fastapi import APIRouter, Depends, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import abonnement_acces as abo  # noqa: E402
import auth  # noqa: E402
import controle_acces  # noqa: E402
import maintenance_plateforme as mp  # noqa: E402
import routes.abonnements_sessions as ras  # noqa: E402
import sessions_comptes as sess  # noqa: E402
from routes.auth import attach_auth_routes  # noqa: E402
from routes.maintenance_plateforme import admin as r_maint_admin, public as r_maint_public  # noqa: E402

UTC = timezone.utc
SUPER = "admin@sawalismartsystems.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"


def _users(aujourdhui):
    paye_il_y_a = lambda j: (aujourdhui - timedelta(days=j)).isoformat()  # noqa: E731
    return [
        {"id": "super", "email": SUPER, "full_name": "Super Admin", "role": "admin", "account_status": "active",
         "created_at": "2026-01-01"},
        {"id": "adm2", "email": "admin.client@isis.bf", "full_name": "Admin client", "role": "admin",
         "account_status": "active", "created_at": "2026-01-01"},
        {"id": "sup", "email": "sup@sawali.bf", "full_name": "Superviseur", "role": "superviseur",
         "account_status": "active", "created_at": "2026-01-01"},
        # Client à jour (payé il y a 10 jours, mensuel)
        {"id": "ok", "email": "ok@x.bf", "full_name": "Pharmacie OK", "company": "Pharmacie OK", "role": "client",
         "account_status": "active", "created_at": "2026-01-01", "contract_billing_period": "monthly",
         "last_payment_at": paye_il_y_a(10), "contract_number": "C-OK"},
        # Client expiré : payé il y a 40 jours (échéance il y a 10 jours, grâce 3 j dépassée)
        {"id": "exp", "email": "exp@x.bf", "full_name": "Pharmacie EXP", "company": "Pharmacie EXP", "role": "client",
         "account_status": "active", "created_at": "2026-01-01", "contract_billing_period": "monthly",
         "last_payment_at": paye_il_y_a(40), "contract_number": "C-EXP", "contract_amount": 25000,
         "contract_currency": "XOF"},
        {"id": "exp-suivi", "email": "caisse@exp.bf", "full_name": "Caissier EXP", "role": "client",
         "tracked_role": "Caissier", "parent_client_id": "exp", "client_id": "exp", "account_status": "active",
         "created_at": "2026-01-01"},
        # Client en grâce : échéance hier (payé il y a 31 jours)
        {"id": "gr", "email": "gr@x.bf", "full_name": "Pharmacie GR", "company": "Pharmacie GR", "role": "client",
         "account_status": "active", "created_at": "2026-01-01", "contract_billing_period": "monthly",
         "last_payment_at": paye_il_y_a(31)},
        # Client sans périodicité : jamais coupé
        {"id": "libre", "email": "libre@x.bf", "full_name": "Sans contrat", "role": "client",
         "account_status": "active", "created_at": "2026-01-01", "last_payment_at": paye_il_y_a(400)},
    ]


@pytest.fixture()
def env(monkeypatch):
    b = mongomock_motor.AsyncMongoMockClient()[f"lot50_{time.time_ns()}"]
    for mod in (auth, mp, sess, abo, ras):
        monkeypatch.setattr(mod, "db", b)
    monkeypatch.delenv("SUPER_ADMIN_EMAIL", raising=False)
    mp.vider_cache()
    sess.vider_caches()
    sess._index_ok["fait"] = False
    abo.vider_cache()

    app = FastAPI()
    app.add_exception_handler(controle_acces.RefusAcces, controle_acces.gestionnaire_refus)
    api = APIRouter(prefix="/api")

    @api.get("/donnees")
    async def donnees(user: dict = Depends(auth.get_current_user)):
        return {"ok": True, "user": user["id"]}

    @api.post("/webhooks/test/{secret}")
    async def webhook(secret: str):  # webhook entrant : aucune session de compte
        return {"recu": secret}

    @api.get("/public/test")
    async def public_test():
        return {"public": True}

    async def _verify_recaptcha(*a, **k):
        return {"success": True, "reason": ""}

    async def _send_otp(*a, **k):
        return True

    async def _fermer(jeton):
        charge = auth.decode_token(jeton)
        if charge.get("sid"):
            await sess.fermer(charge["sid"], sess.MOTIF_DECONNEXION)

    attach_auth_routes(api, db=b, helpers={
        "verify_password": lambda p, h: True, "hash_password": lambda p: "h", "verify_recaptcha": _verify_recaptcha,
        "generate_otp": lambda: "123456", "generate_session_token": lambda: f"s-{time.time_ns()}",
        "send_otp_email": _send_otp, "create_access_token": auth.create_access_token,
        "get_current_user": auth.get_current_user,
        "_to_user_public": lambda u: {k: u.get(k) for k in ("id", "email", "full_name", "role", "created_at")},
        "_uuid": lambda: str(time.time_ns()), "_now": lambda: datetime.now(UTC).isoformat(),
        "refuser_si_maintenance": mp.refuser_si_maintenance, "create_session_token": auth.create_session_token,
        "fermer_session_jeton": _fermer,
    })
    api.include_router(r_maint_public)
    api.include_router(r_maint_admin)
    api.include_router(ras.router)
    app.include_router(api)
    client = TestClient(app)

    class Env:
        pass
    e = Env()
    e.db, e.client, e.aujourdhui = b, client, datetime.now(UTC).date()
    import asyncio
    boucle = asyncio.new_event_loop()
    e.run = boucle.run_until_complete
    e.run(b.users.insert_many([{**u, "password_hash": "h"} for u in _users(e.aujourdhui)]))
    yield e
    boucle.close()


def jeton(uid, role="client", iat=None, **extra):
    now = int(time.time()) if iat is None else int(iat)
    return jwt.encode({"sub": uid, "role": role, "iat": now, "exp": now + 3600, **extra},
                      auth.JWT_SECRET, algorithm=auth.JWT_ALGORITHM)


def h(tok, fond=False):
    d = {"Authorization": f"Bearer {tok}", "User-Agent": UA}
    if fond:
        d["X-Requete-Fond"] = "1"
    return d


def session_de(env, uid):
    user = env.run(env.db.users.find_one({"id": uid}, {"_id": 0}))
    return env.run(auth.create_session_token(user, None))


def passer_echeance(env):
    """Place l'échéance de l'annonce en cours dans le passé (maintenance)."""
    passe = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
    env.run(env.db.maintenance_plateforme.update_one({"_id": "etat"}, {"$set": {
        "echeance": passe, "debut_verrouillage": (datetime.now(UTC) - timedelta(seconds=60)).isoformat()}}))
    mp.vider_cache()


# ===========================================================================
# 1. Maintenance de la plateforme (R8)
# ===========================================================================
def test_maintenance_phases_et_calendrier():
    depart = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
    cal = mp.calendrier(5, 80, depart)
    assert cal["debut_verrouillage"] == (depart + timedelta(minutes=1)).isoformat()
    assert cal["echeance"] == (depart + timedelta(minutes=5)).isoformat()
    doc = {"actif": True, **cal}
    assert mp.phase_de(doc, depart + timedelta(seconds=30)) == mp.ANNONCE
    assert mp.phase_de(doc, depart + timedelta(minutes=2)) == mp.VERROUILLAGE
    assert mp.phase_de(doc, depart + timedelta(minutes=5)) == mp.MAINTENANCE
    assert mp.phase_de({**doc, "actif": False}, depart) == mp.AUCUNE
    # 0 % verrouillé : annonce jusqu'à l'échéance ; 100 % : verrouillé tout de suite
    assert mp.calendrier(5, 0, depart)["debut_verrouillage"] == cal["echeance"]
    assert mp.calendrier(5, 100, depart)["debut_verrouillage"] == depart.isoformat()


def test_maintenance_annonce_route_publique_et_validation(env):
    c = env.client
    assert c.get("/api/maintenance/etat").json()["phase"] == "aucune"
    # Bornes du formulaire
    for corps in ({"message": "x", "duree_minutes": 0}, {"message": "x", "duree_minutes": 121},
                  {"message": "  ", "duree_minutes": 5}, {"message": "x", "part_verrouillage": 101}):
        assert c.post("/api/admin/deconnexion-generale", json=corps, headers=h(jeton("super", "admin"))).status_code == 422
    # Un Admin de client (rôle admin, pas le super-admin) ne peut pas annoncer
    assert c.post("/api/admin/deconnexion-generale", json={"message": "Mise à jour"},
                  headers=h(jeton("adm2", "admin"))).status_code == 403
    r = c.post("/api/admin/deconnexion-generale", json={"message": "Mise à jour"}, headers=h(jeton("super", "admin")))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["phase"] == "annonce" and d["duree_minutes"] == 5 and d["part_verrouillage"] == 80
    assert 295 <= d["secondes_restantes"] <= 300 and d["journal"][0]["action"] == "ANNONCE"
    pub = c.get("/api/maintenance/etat").json()
    assert pub["phase"] == "annonce" and pub["message"] == "Mise à jour" and "journal" not in pub
    assert "annonce_par" not in pub and pub["maintenant_serveur"]
    # Une seconde annonce est refusée tant que la première court
    assert c.post("/api/admin/deconnexion-generale", json={"message": "Bis"},
                  headers=h(jeton("super", "admin"))).status_code == 409
    # Pendant l'annonce et le verrouillage, les utilisateurs travaillent encore
    assert c.get("/api/donnees", headers=h(jeton("ok"))).status_code == 200


def test_maintenance_refus_apres_echeance_admin_autorise(env):
    c = env.client
    c.post("/api/admin/deconnexion-generale", json={"message": "Migration", "duree_minutes": 1},
           headers=h(jeton("super", "admin")))
    passer_echeance(env)
    assert c.get("/api/maintenance/etat").json()["phase"] == "maintenance"
    # Utilisateurs : 503 avec le code lisible par le site
    for uid, role in (("ok", "client"), ("exp-suivi", "client"), ("sup", "superviseur")):
        r = c.get("/api/donnees", headers=h(jeton(uid, role)))
        assert r.status_code == 503 and r.json()["code"] == "maintenance_plateforme", (uid, r.text)
    # Admins jamais bloqués (super-admin et Admin de client), ni une session « Voir en tant que »
    assert c.get("/api/donnees", headers=h(jeton("super", "admin"))).status_code == 200
    assert c.get("/api/donnees", headers=h(jeton("adm2", "admin"))).status_code == 200
    imp = jeton("ok", "client", imp="super", imp_session="s1", ro=True)
    assert c.get("/api/donnees", headers=h(imp)).status_code == 200
    # Connexion refusée (code OTP) pour un utilisateur, acceptée pour un Admin
    env.run(env.db.otps.insert_many([
        {"id": "o1", "user_id": "ok", "session_token": "st-ok", "code": "123456", "used": False,
         "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()},
        {"id": "o2", "user_id": "adm2", "session_token": "st-adm", "code": "123456", "used": False,
         "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()}]))
    r = c.post("/api/auth/verify-otp", json={"session_token": "st-ok", "code": "123456"})
    assert r.status_code == 503 and r.json()["code"] == "maintenance_plateforme"
    assert c.post("/api/auth/verify-otp", json={"session_token": "st-adm", "code": "123456"}).status_code == 200
    r = c.post("/api/auth/login", json={"email": "ok@x.bf", "password": "x"})
    assert r.status_code == 503


def test_maintenance_webhooks_et_pages_publiques_non_bloques(env):
    c = env.client
    c.post("/api/admin/deconnexion-generale", json={"message": "Migration"}, headers=h(jeton("super", "admin")))
    passer_echeance(env)
    assert c.post("/api/webhooks/test/abc").json() == {"recu": "abc"}
    assert c.post("/api/webhooks/test/abc", headers=h(jeton("ok"))).status_code == 200
    assert c.get("/api/public/test").status_code == 200
    assert c.get("/api/maintenance/etat").status_code == 200
    assert c.post("/api/auth/logout", headers=h(jeton("ok"))).json() == {"ok": True}


def test_maintenance_reactivation_invalide_les_anciennes_sessions(env):
    c = env.client
    avant = jeton("ok", iat=time.time() - 120)
    ancienne = session_de(env, "gr")
    sid_ancienne = auth.decode_token(ancienne)["sid"]
    env.run(env.db.sessions_comptes.update_one({"id": sid_ancienne}, {"$set": {
        "ouverte_le": (datetime.now(UTC) - timedelta(minutes=10)).isoformat()}}))
    c.post("/api/admin/deconnexion-generale", json={"message": "Migration"}, headers=h(jeton("super", "admin")))
    # Réactiver avant l'échéance : refusé (il faut « Annuler »)
    assert c.post("/api/admin/deconnexion-generale/reactiver", headers=h(jeton("super", "admin"))).status_code == 409
    passer_echeance(env)
    r = c.post("/api/admin/deconnexion-generale/reactiver", headers=h(jeton("super", "admin")))
    assert r.status_code == 200 and r.json()["phase"] == "aucune" and r.json()["sessions_valides_apres"]
    assert r.json()["journal"][0]["action"] == "REACTIVATION"
    # Ancienne session : 401 (reconnexion) ; nouvelle connexion : acceptée
    r = c.get("/api/donnees", headers=h(avant))
    assert r.status_code == 401 and r.json()["code"] == "session_maintenance"
    assert c.get("/api/donnees", headers=h(jeton("ok"))).status_code == 200
    # Une session de compte ouverte avant l'échéance est notée fermée (disparaît de « Mon compte »)
    doc = env.run(env.db.sessions_comptes.find_one({"id": sid_ancienne}))
    assert doc["fermee_le"] and doc["motif"] == "maintenance"
    # L'Admin, lui, n'a jamais été déconnecté
    assert c.get("/api/donnees", headers=h(jeton("super", "admin", iat=time.time() - 120))).status_code == 200


def test_maintenance_annulation_personne_deconnecte(env):
    c = env.client
    avant = jeton("ok", iat=time.time() - 60)
    c.post("/api/admin/deconnexion-generale", json={"message": "Migration"}, headers=h(jeton("super", "admin")))
    r = c.post("/api/admin/deconnexion-generale/annuler", headers=h(jeton("super", "admin")))
    assert r.status_code == 200 and r.json()["phase"] == "aucune"
    assert [j["action"] for j in r.json()["journal"]] == ["ANNULATION", "ANNONCE"]
    assert c.get("/api/donnees", headers=h(avant)).status_code == 200
    assert c.post("/api/admin/deconnexion-generale/annuler", headers=h(jeton("super", "admin"))).status_code == 409
    # Après l'échéance, l'annulation n'est plus possible : il faut réactiver
    c.post("/api/admin/deconnexion-generale", json={"message": "Bis"}, headers=h(jeton("super", "admin")))
    passer_echeance(env)
    assert c.post("/api/admin/deconnexion-generale/annuler", headers=h(jeton("super", "admin"))).status_code == 409


def test_aucun_webhook_ni_route_publique_du_serveur_ne_depend_d_une_session():
    """Serveur complet (processus séparé) : aucune route webhook, publique, de paiement public ou
    de retour OAuth ne passe par auth.get_current_user — donc ni la maintenance, ni la limite de
    sessions, ni la coupure d'abonnement ne peuvent les bloquer."""
    code = r'''
import asyncio, json, re
async def m():
    import server, auth
    def appels(d):
        out = set()
        for s in d.dependencies:
            out.add(s.call); out |= appels(s)
        return out
    motif = re.compile(r"webhook|/callback|^/api/public/|/pawapay/|^/api/officines-portal/|^/api/maintenance/etat$|^/api/auth/logout$")
    vus, fautifs = [], []
    for r in server.app.routes:
        p = getattr(r, "path", "")
        if not hasattr(r, "dependant") or p.startswith("/api/admin") or p.startswith("/api/me/"):
            continue
        if motif.search(p):
            vus.append(p)
            if auth.get_current_user in appels(r.dependant):
                fautifs.append(p)
    print("RESULTAT" + json.dumps({"vus": vus, "fautifs": fautifs}))
asyncio.run(m())
'''
    env_proc = {**os.environ, "DISABLE_SCHEDULER": "1", "MONGO_URL": os.environ.get("MONGO_URL", "mongodb://127.0.0.1:9"),
                "DB_NAME": "sawali_test_lot50_routes"}
    try:
        p = subprocess.run([sys.executable, "-c", code], cwd=str(RACINE), env=env_proc, capture_output=True,
                           text=True, timeout=240)
    except subprocess.TimeoutExpired:
        pytest.skip("import du serveur trop long")
    ligne = next((x for x in p.stdout.splitlines() if x.startswith("RESULTAT")), None)
    if ligne is None:
        pytest.skip(f"serveur non importable ici : {p.stderr[-400:]}")
    res = json.loads(ligne[len("RESULTAT"):])
    vus = set(res["vus"])
    for attendu in ("/api/whatsapp/webhook", "/api/meta/webhook", "/api/webhooks/pawapay/{secret}",
                    "/api/webhooks/agenda/{secret}", "/api/webhooks/planning/{secret}", "/api/webhook/liluvine-send",
                    "/api/webhooks/liluvine-pro/{source}/{secret}", "/api/webhooks/n8n/payroll/{tenant_id}",
                    "/api/maintenance/etat", "/api/auth/logout"):
        assert attendu in vus, attendu
    assert res["fautifs"] == [], res["fautifs"]


# ===========================================================================
# 2. B — Sessions limitées par compte, inactivité contrôlée par le serveur
# ===========================================================================
def test_sixieme_connexion_ferme_la_plus_ancienne(env):
    c = env.client
    jetons = []
    for i in range(5):
        jetons.append(session_de(env, "ok"))
        # dernière activité étalée : la première session est la plus ancienne
        sid = auth.decode_token(jetons[-1])["sid"]
        env.run(env.db.sessions_comptes.update_one({"id": sid}, {"$set": {
            "derniere_activite": (datetime.now(UTC) - timedelta(minutes=50 - i)).isoformat()}}))
    # La 2e session redevient active : c'est la 1re qui sera fermée
    sid2 = auth.decode_token(jetons[1])["sid"]
    env.run(env.db.sessions_comptes.update_one({"id": sid2}, {"$set": {"derniere_activite": datetime.now(UTC).isoformat()}}))
    for t in jetons:
        assert c.get("/api/donnees", headers=h(t, fond=True)).status_code == 200
    sixieme = session_de(env, "ok")
    r = c.get("/api/donnees", headers=h(jetons[0]))
    assert r.status_code == 401 and r.json()["code"] == "session_limite"
    assert r.json()["detail"] == "Session fermée : nombre maximal d'appareils atteint pour ce compte."
    for t in jetons[1:] + [sixieme]:
        assert c.get("/api/donnees", headers=h(t)).status_code == 200
    assert len(c.get("/api/me/sessions", headers=h(sixieme)).json()["sessions"]) == 5
    actions = [j["action"] for j in env.run(env.db.sessions_comptes_journal.find({}, {"_id": 0}).to_list(50))]
    assert actions.count("OUVERTURE") == 6 and actions.count("FERMETURE") == 1


def test_reglage_max_borne_et_applique(env):
    c = env.client
    assert c.put("/api/admin/sessions/reglages", json={"max_par_compte": 25}, headers=h(jeton("super", "admin"))).status_code == 422
    assert c.put("/api/admin/sessions/reglages", json={"max_par_compte": 0}, headers=h(jeton("super", "admin"))).status_code == 422
    assert c.put("/api/admin/sessions/reglages", json={"max_par_compte": 2}, headers=h(jeton("adm2", "admin"))).status_code == 403
    assert c.put("/api/admin/sessions/reglages", json={"max_par_compte": 2},
                 headers=h(jeton("super", "admin"))).json()["max_par_compte"] == 2
    t1, t2, t3 = (session_de(env, "ok") for _ in range(3))
    assert c.get("/api/donnees", headers=h(t1)).status_code == 401
    assert c.get("/api/donnees", headers=h(t2)).status_code == 200 and c.get("/api/donnees", headers=h(t3)).status_code == 200
    assert sess.borner_max("abc") == 5 and sess.borner_max(99) == 20


def test_mon_compte_liste_et_ferme_une_session(env):
    c = env.client
    a, b = session_de(env, "ok"), session_de(env, "ok")
    autre = session_de(env, "gr")
    liste = c.get("/api/me/sessions", headers=h(a)).json()
    assert liste["max_par_compte"] == 5 and len(liste["sessions"]) == 2
    courante = [s for s in liste["sessions"] if s["courante"]]
    assert len(courante) == 1 and courante[0]["id"] == auth.decode_token(a)["sid"]
    sid_a, sid_b = auth.decode_token(a)["sid"], auth.decode_token(b)["sid"]
    assert c.delete(f"/api/me/sessions/{sid_a}", headers=h(a)).status_code == 400   # sa propre session
    assert c.delete(f"/api/me/sessions/{auth.decode_token(autre)['sid']}", headers=h(a)).status_code == 404
    assert c.delete(f"/api/me/sessions/{sid_b}", headers=h(a)).status_code == 200
    r = c.get("/api/donnees", headers=h(b))
    assert r.status_code == 401 and r.json()["code"] == "session_fermee"
    # Déconnexion : la session est fermée côté serveur
    assert c.post("/api/auth/logout", headers=h(a)).json() == {"ok": True}
    assert c.get("/api/donnees", headers=h(a)).status_code == 401


def test_voir_en_tant_que_ne_compte_pas_et_jeton_ancien_accepte(env):
    c = env.client
    c.put("/api/admin/sessions/reglages", json={"max_par_compte": 1}, headers=h(jeton("super", "admin")))
    t = session_de(env, "ok")
    imp = jeton("ok", "client", imp="super", imp_session="s1", ro=True)
    for _ in range(3):
        assert c.get("/api/donnees", headers=h(imp)).status_code == 200
    assert c.get("/api/donnees", headers=h(t)).status_code == 200   # la session du client reste ouverte
    assert c.get("/api/me/sessions", headers=h(imp)).json()["apercu_admin"] is True
    assert env.run(env.db.sessions_comptes.count_documents({})) == 1
    # Jeton émis avant le lot 50 (sans « sid ») : valable jusqu'à son expiration
    assert c.get("/api/donnees", headers=h(jeton("ok"))).status_code == 200


def test_connexion_par_code_otp_ouvre_une_session(env):
    c = env.client
    env.run(env.db.otps.insert_one({"id": "o1", "user_id": "ok", "session_token": "st", "code": "123456", "used": False,
                                    "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()}))
    r = c.post("/api/auth/verify-otp", json={"session_token": "st", "code": "123456"}, headers={"User-Agent": UA})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    sid = auth.decode_token(tok)["sid"]
    doc = env.run(env.db.sessions_comptes.find_one({"id": sid}, {"_id": 0}))
    assert doc["user_id"] == "ok" and doc["appareil"] == "Chrome · Windows" and doc["client_id"] == "ok"


def test_inactivite_controlee_par_le_serveur(env):
    c = env.client
    t = session_de(env, "ok")
    sid = auth.decode_token(t)["sid"]
    vieux = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    env.run(env.db.sessions_comptes.update_one({"id": sid}, {"$set": {"derniere_activite": vieux}}))
    # Réglage désactivé (0) : aucune fermeture ; la requête de fond ne compte pas comme activité
    assert c.get("/api/donnees", headers=h(t, fond=True)).status_code == 200
    assert env.run(env.db.sessions_comptes.find_one({"id": sid}))["derniere_activite"] == vieux
    # Requête normale : activité notée (au plus une écriture par minute)
    assert c.get("/api/donnees", headers=h(t)).status_code == 200
    assert env.run(env.db.sessions_comptes.find_one({"id": sid}))["derniere_activite"] != vieux
    # Délai de 1 minute (unité inchangée : minutes) : 5 minutes sans activité > 1 + 2 de marge
    env.run(env.db.settings.insert_one({"_id": "global", "auto_logout_minutes": 1}))
    sess.vider_caches()
    env.run(env.db.sessions_comptes.update_one({"id": sid}, {"$set": {"derniere_activite": vieux}}))
    r = c.get("/api/donnees", headers=h(t))
    assert r.status_code == 401 and r.json()["code"] == "session_inactive"
    # Activité signalée par le navigateur : la session reste ouverte
    t2 = session_de(env, "ok")
    sid2 = auth.decode_token(t2)["sid"]
    env.run(env.db.sessions_comptes.update_one({"id": sid2}, {"$set": {
        "derniere_activite": (datetime.now(UTC) - timedelta(minutes=2)).isoformat()}}))
    assert c.post("/api/me/activite", headers=h(t2)).status_code == 200
    sess.vider_caches()
    assert c.get("/api/donnees", headers=h(t2, fond=True)).status_code == 200


def test_super_admin_voit_et_ferme_les_sessions_d_un_client(env):
    c = env.client
    session_de(env, "exp")
    session_de(env, "exp-suivi")
    t_suivi = session_de(env, "exp-suivi")
    r = c.get("/api/admin/sessions/client/exp", headers=h(jeton("super", "admin")))
    assert r.status_code == 200
    comptes = {x["id"]: len(x["sessions"]) for x in r.json()["comptes"]}
    assert comptes == {"exp": 1, "exp-suivi": 2}
    assert c.get("/api/admin/sessions/client/exp", headers=h(jeton("adm2", "admin"))).status_code == 403
    r = c.post("/api/admin/sessions/compte/exp-suivi/fermer-tout", headers=h(jeton("super", "admin")))
    assert r.json()["fermees"] == 2
    assert c.get("/api/donnees", headers=h(t_suivi)).json()["code"] == "session_fermee"


# ===========================================================================
# 3. A — Période de grâce puis coupure côté serveur
# ===========================================================================
def test_etat_client_a_jour_grace_expire():
    a = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)
    client = {"contract_billing_period": "monthly", "last_payment_at": "2026-09-01"}   # échéance 2026-10-01
    e = abo.etat_client(client, a)
    assert e["echeance"] == "2026-10-01" and e["statut"] == abo.GRACE
    assert e["impayee_depuis"] == "2026-10-02T00:00:00+00:00" and e["fin_grace"] == "2026-10-05T00:00:00+00:00"
    assert e["jours_restants"] == 3
    assert abo.etat_client(client, datetime(2026, 10, 1, 23, 59, tzinfo=UTC))["statut"] == abo.A_JOUR
    # Coupure à l'heure exacte
    assert abo.etat_client(client, datetime(2026, 10, 4, 23, 59, 59, tzinfo=UTC))["statut"] == abo.GRACE
    assert abo.etat_client(client, datetime(2026, 10, 5, 0, 0, 0, tzinfo=UTC))["statut"] == abo.EXPIRE
    # Grâce réglée par client (0 = coupure dès le lendemain de l'échéance), bornée à 30
    assert abo.etat_client({**client, "abonnement_grace_jours": 0}, a)["statut"] == abo.EXPIRE
    assert abo.etat_client({**client, "abonnement_grace_jours": 99}, a)["grace_jours"] == 30
    # Renouvellements liés à l'échéance : +3 j chacun ; remis à zéro par un paiement
    ren = {**client, "abonnement_grace_renouvellements": {"echeance": "2026-10-01", "nombre": 2}}
    assert abo.etat_client(ren, a)["fin_grace"] == "2026-10-11T00:00:00+00:00"
    paye = {**ren, "last_payment_at": "2026-10-02"}
    e = abo.etat_client(paye, a)
    assert e["statut"] == abo.A_JOUR and e["renouvellements"] == 0 and e["echeance"] == "2026-11-01"
    # Sans périodicité ou sans date : pas d'échéance
    assert abo.etat_client({"last_payment_at": "2020-01-01"}, a)["statut"] == abo.SANS_ECHEANCE
    assert abo.etat_client({"contract_billing_period": "annual"}, a)["statut"] == abo.SANS_ECHEANCE
    # Repli sur la date de signature ; trimestriel = 90 j
    assert abo.etat_client({"contract_billing_period": "quarterly", "contract_signed_at": "2026-07-01"}, a)["echeance"] == "2026-09-29"


def test_coupure_desactivee_par_defaut_puis_active(env):
    c = env.client
    # Interrupteur désactivé : personne n'est coupé, aucun bandeau
    assert c.get("/api/donnees", headers=h(jeton("exp"))).status_code == 200
    assert c.get("/api/me/abonnement", headers=h(jeton("exp"))).json()["actif"] is False
    assert c.put("/api/admin/abonnements/reglages", json={"coupure_active": True},
                 headers=h(jeton("adm2", "admin"))).status_code == 403
    assert c.put("/api/admin/abonnements/reglages", json={"coupure_active": True},
                 headers=h(jeton("super", "admin"))).json() == {"coupure_active": True}
    # Client expiré : compte principal ET utilisateur suivi coupés (402), message clair
    for uid in ("exp", "exp-suivi"):
        r = c.get("/api/donnees", headers=h(jeton(uid)))
        assert r.status_code == 402 and r.json()["code"] == "abonnement_expire", uid
        assert r.json()["detail"].startswith("Abonnement expiré")
    # Routes laissées ouvertes : profil minimal, état de l'abonnement, sessions, déconnexion
    etat = c.get("/api/me/abonnement", headers=h(jeton("exp-suivi"))).json()
    assert etat["actif"] and etat["bloque"] and etat["statut"] == "expire" and etat["contrat"]["numero"] == "C-EXP"
    assert c.get("/api/me/sessions", headers=h(jeton("exp"))).status_code == 200
    assert c.get("/api/me/derniere-sauvegarde", headers=h(jeton("exp"))).status_code == 200
    assert c.post("/api/auth/logout", headers=h(jeton("exp"))).status_code == 200
    # En grâce : accès normal + état « grace » (bandeau) ; à jour et sans échéance : rien
    assert c.get("/api/donnees", headers=h(jeton("gr"))).status_code == 200
    g = c.get("/api/me/abonnement", headers=h(jeton("gr"))).json()
    assert g["statut"] == "grace" and g["jours_restants"] == 3 and not g["bloque"]
    assert c.get("/api/donnees", headers=h(jeton("ok"))).status_code == 200
    assert c.get("/api/donnees", headers=h(jeton("libre"))).status_code == 200
    # Jamais : super-admin, comptes internes sans échéance, « Voir en tant que » (aperçu)
    assert c.get("/api/donnees", headers=h(jeton("super", "admin"))).status_code == 200
    assert c.get("/api/donnees", headers=h(jeton("sup", "superviseur"))).status_code == 200
    imp = jeton("exp", "client", imp="super", imp_session="s1", ro=True)
    assert c.get("/api/donnees", headers=h(imp)).status_code == 200
    ap = c.get("/api/me/abonnement", headers=h(imp)).json()
    assert ap["apercu_admin"] and not ap["bloque"]


def test_coupure_a_l_heure_exacte_pour_un_utilisateur_connecte(env, monkeypatch):
    c = env.client
    c.put("/api/admin/abonnements/reglages", json={"coupure_active": True}, headers=h(jeton("super", "admin")))
    t = jeton("gr")
    fin = datetime.fromisoformat(c.get("/api/me/abonnement", headers=h(t)).json()["fin_grace"])
    monkeypatch.setattr(abo, "maintenant", lambda: fin - timedelta(seconds=1))
    assert c.get("/api/donnees", headers=h(t)).status_code == 200
    monkeypatch.setattr(abo, "maintenant", lambda: fin)
    assert c.get("/api/donnees", headers=h(t)).status_code == 402   # même jeton, sans reconnexion


def test_renouveler_la_grace_trois_fois_et_regler_la_grace(env):
    c = env.client
    c.put("/api/admin/abonnements/reglages", json={"coupure_active": True}, headers=h(jeton("super", "admin")))
    sa = h(jeton("super", "admin"))
    assert c.post("/api/admin/abonnements/ok/renouveler-grace", headers=sa).status_code == 409   # à jour
    assert c.post("/api/admin/abonnements/exp/renouveler-grace", headers=h(jeton("adm2", "admin"))).status_code == 403
    fins = []
    for i in range(3):
        r = c.post("/api/admin/abonnements/exp/renouveler-grace", headers=sa)
        assert r.status_code == 200 and r.json()["renouvellements"] == i + 1
        fins.append(r.json()["fin_grace"])
    assert c.post("/api/admin/abonnements/exp/renouveler-grace", headers=sa).status_code == 409
    # Payé il y a 40 j : échéance il y a 10 j ; grâce 3 + 9 = 12 j après l'échéance -> accès rétabli
    assert c.get("/api/donnees", headers=h(jeton("exp"))).status_code == 200
    # Délai de grâce du client : 0 à 30 j
    assert c.put("/api/admin/abonnements/exp/grace", json={"jours": 31}, headers=sa).status_code == 422
    r = c.put("/api/admin/abonnements/exp/grace", json={"jours": 0}, headers=sa)
    assert r.status_code == 200 and r.json()["grace_jours"] == 0
    assert c.get("/api/donnees", headers=h(jeton("exp"))).status_code == 402
    # Paiement enregistré (nouvelle échéance) : accès rétabli, compteur remis à zéro
    env.run(env.db.users.update_one({"id": "exp"}, {"$set": {"last_payment_at": env.aujourdhui.isoformat()}}))
    abo.vider_cache()
    assert c.get("/api/donnees", headers=h(jeton("exp-suivi"))).status_code == 200
    ligne = next(x for x in c.get("/api/admin/abonnements", headers=sa).json()["clients"] if x["client_id"] == "exp")
    assert ligne["statut"] == "a_jour" and ligne["renouvellements"] == 0 and ligne["comptes"] == 2
    actions = [j["action"] for j in c.get("/api/admin/abonnements/journal", headers=sa).json()["journal"]]
    assert actions.count("GRACE_RENOUVELEE") == 3 and "GRACE_REGLEE" in actions and "COUPURE_ACTIVEE" in actions


def test_liste_des_abonnements_super_admin(env):
    c = env.client
    r = c.get("/api/admin/abonnements", headers=h(jeton("super", "admin")))
    assert r.status_code == 200
    d = r.json()
    ids = [x["client_id"] for x in d["clients"]]
    assert "super" not in ids and "exp-suivi" not in ids   # ni le super-admin, ni un utilisateur suivi
    assert ids[0] == "exp" and {"ok", "gr", "libre"} <= set(ids)
    assert d["reglages"]["coupure_active"] is False and d["reglages"]["grace_defaut"] == 3
    assert c.get("/api/admin/abonnements", headers=h(jeton("adm2", "admin"))).status_code == 403


# ===========================================================================
# 4. D — Date de la dernière sauvegarde
# ===========================================================================
def test_derniere_sauvegarde(env):
    c = env.client
    assert c.get("/api/me/derniere-sauvegarde", headers=h(jeton("ok"))).json() == {"generale": None, "propre": None}
    env.run(env.db.sauvegardes_completes.insert_one({"_id": "etat_auto", "derniere_reussite": {
        "le": "2026-10-02T03:00:12+00:00", "cle": "sauvegardes-completes/sawali-20261002-030012.sawali"}}))
    r = c.get("/api/me/derniere-sauvegarde", headers=h(jeton("exp-suivi"))).json()
    assert r == {"generale": {"le": "2026-10-02T03:00:12+00:00"}, "propre": None}   # sans la clé R2
    assert c.get("/api/me/derniere-sauvegarde").status_code == 401


def test_appareil_lisible():
    assert sess.appareil_de(UA) == "Chrome · Windows"
    assert sess.appareil_de("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit Version/17.0 Mobile Safari/604.1") == "Safari · iPhone"
    assert sess.appareil_de("Mozilla/5.0 (Linux; Android 14) Chrome/128 Mobile Safari/537.36") == "Chrome · Android"
    assert sess.appareil_de("") == "Navigateur · appareil inconnu"


def test_sauvegardes_et_migration_n_emportent_ni_maintenance_ni_sessions():
    """Un site restauré ou migré ne démarre pas « en maintenance » ; un import « Remplacer » ne
    ferme pas la session de l'Admin qui le suit (collections exclues de l'export et de l'import)."""
    pytest.importorskip("cryptography")
    import routes.sauvegarde_complete as sc
    assert {"maintenance_plateforme", "sessions_comptes"} <= set(sc.EXCLUES)
    texte = (RACINE / "routes" / "migration_render.py").read_text(encoding="utf-8")
    assert '"maintenance_plateforme", "sessions_comptes"}' in texte
