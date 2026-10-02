"""Lot 51 — Cycle de vie du non-renouvellement (spécification commune, point C) et contrôle du statut
du compte à la connexion par code WhatsApp.
MongoDB simulé (mongomock_motor), R2 simulé, vrais jetons JWT, vraie dépendance auth.get_current_user,
vrai chiffrement (format du lot 49).
Lancer : cd backend && python -m pytest tests/test_lot51_cycle_vie_abonnements.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot51")

import jwt  # noqa: E402
from fastapi import APIRouter, Depends, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import abonnement_acces as abo  # noqa: E402
import auth  # noqa: E402
import controle_acces  # noqa: E402
import cycle_vie_abonnements as cv  # noqa: E402
import maintenance_plateforme as mp  # noqa: E402
import routes.abonnements_sessions as ras  # noqa: E402
import routes.cycle_vie_abonnements as rcv  # noqa: E402
import routes.sauvegarde_complete as sc  # noqa: E402
import sauvegarde_format as sf  # noqa: E402
import sessions_comptes as sess  # noqa: E402
from routes.auth import attach_auth_routes  # noqa: E402
from routes.wa_otp_login_9o import setup_wa_otp_routes  # noqa: E402

UTC = timezone.utc
SUPER = "admin@sawalismartsystems.com"
PHRASE = "phrase-archive-tests-0123"
JWT = "secret-tests-0123456789-abcdef"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"


class FauxR2:
    def __init__(self, alterer=False):
        self.objets = {}
        self.supprimees = []
        self.alterer = alterer

    def upload_file(self, chemin, bucket, cle, ExtraArgs=None):  # noqa: N803
        self.objets[cle] = Path(chemin).read_bytes()

    def head_object(self, Bucket, Key):  # noqa: N803
        return {"ContentLength": len(self.objets[Key])}

    def download_file(self, bucket, cle, chemin):
        data = bytearray(self.objets[cle])
        if self.alterer:  # copie abîmée pendant le transfert
            data[len(data) // 2] ^= 0xFF
        Path(chemin).write_bytes(bytes(data))

    def delete_objects(self, Bucket, Delete):  # noqa: N803
        for o in Delete["Objects"]:
            self.supprimees.append(o["Key"])
            self.objets.pop(o["Key"], None)
        return {}


def paye_pour_j(aujourdhui, j):
    """Date du dernier règlement (mensuel) qui place aujourd'hui à J+j après l'échéance."""
    return (aujourdhui - timedelta(days=30 + j)).isoformat()


def _users(aujourdhui):
    return [
        {"id": "super", "email": SUPER, "full_name": "Super Admin", "role": "admin", "account_status": "active"},
        {"id": "adm2", "email": "admin.client@isis.bf", "full_name": "Admin client", "role": "admin",
         "account_status": "active"},
        # Client à J+103
        {"id": "c103", "email": "c103@x.bf", "full_name": "Awa 103", "company": "Pharmacie 103", "role": "client",
         "account_status": "active", "contract_billing_period": "monthly", "last_payment_at": paye_pour_j(aujourdhui, 103),
         "contract_number": "C-103", "whatsapp_number": "+22670000103"},
        # Client à J+110 (principal + utilisateur suivi rattaché)
        {"id": "c110", "email": "c110@x.bf", "full_name": "Ali 110", "company": "Pharmacie 110", "role": "client",
         "account_status": "active", "contract_billing_period": "monthly", "last_payment_at": paye_pour_j(aujourdhui, 110),
         "contract_number": "C-110", "phone": "+22670000110"},
        {"id": "c110-suivi", "email": "caisse@c110.bf", "full_name": "Caissier 110", "role": "client",
         "tracked_role": "Caissier", "parent_client_id": "c110", "client_id": "c110", "account_status": "active",
         "whatsapp": "+22670000999", "phone_digits": "22670000999", "tracked_user_id": "t110"},
        # Client à J+113 (sera préparé « suspendu » par les tests d'archivage)
        {"id": "c113", "email": "c113@x.bf", "full_name": "Issa 113", "company": "Pharmacie 113", "role": "client",
         "account_status": "active", "contract_billing_period": "monthly", "last_payment_at": paye_pour_j(aujourdhui, 113),
         "contract_number": "C-113", "contract_amount": 25000, "contract_currency": "XOF", "phone": "+22670000113"},
        {"id": "c113-suivi", "email": "rh@c113.bf", "full_name": "RH 113", "role": "client", "tracked_role": "RH",
         "parent_client_id": "c113", "client_id": "c113", "account_status": "active"},
        # Client à jour, client sans échéance, clients exclus (test, interne) très en retard
        {"id": "ok", "email": "ok@x.bf", "full_name": "OK", "role": "client", "account_status": "active",
         "contract_billing_period": "monthly", "last_payment_at": paye_pour_j(aujourdhui, -10)},
        {"id": "libre", "email": "libre@x.bf", "full_name": "Libre", "role": "client", "account_status": "active",
         "last_payment_at": paye_pour_j(aujourdhui, 400)},
        {"id": "test", "email": "test@x.bf", "full_name": "TEST SAWALI", "role": "client", "account_status": "active",
         "est_test": True, "contract_billing_period": "monthly", "last_payment_at": paye_pour_j(aujourdhui, 200)},
        {"id": "interne", "email": "compta@sawalismartsystems.com", "full_name": "Interne", "role": "client",
         "account_status": "active", "contract_billing_period": "monthly", "last_payment_at": paye_pour_j(aujourdhui, 200)},
    ]


def _donnees_c113():
    """Données rattachées au client c113 (et à un autre client, qui ne doit jamais être touché)."""
    return {
        "tracked_users": [{"id": "t113", "client_id": "c113", "name": "Suivi 113"},
                          {"id": "t-ok", "client_id": "ok", "name": "Suivi OK"}],
        "documents": [{"id": "d1", "client_id": "c113", "title": "Contrat"},
                      {"id": "d2", "uploaded_by_user_id": "c113-suivi", "title": "Pièce"},
                      {"id": "d-ok", "client_id": "ok", "title": "Autre"}],
        "appointments": [{"id": "rdv1", "client_id": "c113", "subject": "RDV"}],
        "contacts": [{"id": "ct1", "tenant_id": "c113", "full_name": "Contact"},
                     {"id": "ct-ok", "tenant_id": "ok", "full_name": "Contact OK"}],
        "forms": [{"id": "f1", "client_id": "c113", "title": "Formulaire"}],
        "form_submissions": [{"id": "fs1", "form_id": "f1", "answers": {"q": 1}},
                             {"id": "fs-autre", "form_id": "f-ok"}],
        "wa_surveys": [{"id": "s1", "owner_id": "c113", "title": "Sondage"}],
        "wa_survey_responses": [{"id": "sr1", "survey_id": "s1", "contact_id": "ct1"}],
        "officines": [{"id": "o1", "linked_client_id": "c113", "name": "Officine liée"}],
        "officine_inventory_items": [{"id": "i1", "officine_id": "o1", "qte": 3},
                                     {"id": "i2", "officine_id": "o1", "qte": 5}],
        "tasks": [{"id": "tk1", "tracked_user_id": "t113", "title": "Tâche"}],
        "tenant_payments": [{"id": "p1", "tenant_id": "c113", "amount_paid": 25000}],
        "activity_events": [{"id": "ae1", "client_id": "c113", "action": "login"}],
    }


@pytest.fixture()
def env(monkeypatch, tmp_path):
    b = mongomock_motor.AsyncMongoMockClient()[f"lot51_{time.time_ns()}"]
    for mod in (auth, mp, sess, abo, ras, cv, rcv, sc):
        monkeypatch.setattr(mod, "db", b)
    monkeypatch.setattr(cv, "EXPORTS_DIR", tmp_path)
    monkeypatch.setattr(sc, "EXPORTS_DIR", tmp_path)
    monkeypatch.delenv("SUPER_ADMIN_EMAIL", raising=False)
    monkeypatch.setenv("JWT_SECRET", JWT)
    monkeypatch.setenv("SAUVEGARDE_AUTO_PHRASE", PHRASE)
    for nom, val in (("ACCOUNT_ID", "compte"), ("ACCESS_KEY_ID", "cle"), ("SECRET_ACCESS_KEY", "secret")):
        monkeypatch.setenv(f"R2_SAUVEGARDES_{nom}", val)
    monkeypatch.delenv("R2_SAUVEGARDES_BUCKET", raising=False)
    r2 = FauxR2()
    monkeypatch.setitem(sc._FABRIQUE_R2, "client", lambda cfg: r2)
    envois = {"email": [], "wa": []}

    async def faux_email(to, sujet, html, texte=""):
        envois["email"].append({"to": to, "sujet": sujet, "texte": texte})
        return True

    async def faux_wa(numero, texte):
        envois["wa"].append({"to": numero, "texte": texte})
        return {"ok": True}
    monkeypatch.setitem(cv._ENVOIS, "email", faux_email)
    monkeypatch.setitem(cv._ENVOIS, "wa", faux_wa)
    monkeypatch.setitem(cv._ENVOIS, "email_admin", SUPER)
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

    async def _verify_recaptcha(*a, **k):
        return {"success": True, "reason": ""}

    async def _send_otp(*a, **k):
        return True

    attach_auth_routes(api, db=b, helpers={
        "verify_password": lambda p, h: bool(h) and p == "bon-mdp", "hash_password": lambda p: "h",
        "verify_recaptcha": _verify_recaptcha,
        "generate_otp": lambda: "123456", "generate_session_token": lambda: f"s-{time.time_ns()}",
        "send_otp_email": _send_otp, "create_access_token": auth.create_access_token,
        "get_current_user": auth.get_current_user,
        "_to_user_public": lambda u: {k: u.get(k) for k in ("id", "email", "full_name", "role", "created_at")},
        "_uuid": lambda: str(time.time_ns()), "_now": lambda: datetime.now(UTC).isoformat(),
        "refuser_si_maintenance": mp.refuser_si_maintenance, "create_session_token": auth.create_session_token,
        "refuser_si_cycle_vie": cv.refuser_connexion,
    })

    async def _jeton_wa(u, request=None):
        return await auth.create_session_token(u, request)
    setup_wa_otp_routes(app=api, db=b, get_current_user=auth.get_current_user, create_jwt_token=_jeton_wa,
                        hash_password=lambda p: "h")
    api.include_router(rcv.router)
    app.include_router(api)

    class Env:
        pass
    e = Env()
    e.db, e.client, e.r2, e.envois, e.tmp = b, TestClient(app), r2, envois, tmp_path
    e.aujourdhui = datetime.now(UTC).date()
    boucle = asyncio.new_event_loop()
    e.run = boucle.run_until_complete
    e.run(b.users.insert_many([{**u, "password_hash": "h", "created_at": "2026-01-01"} for u in _users(e.aujourdhui)]))
    yield e
    boucle.close()


def jeton(uid, role="client", **extra):
    now = int(time.time())
    return jwt.encode({"sub": uid, "role": role, "iat": now, "exp": now + 3600, **extra},
                      auth.JWT_SECRET, algorithm=auth.JWT_ALGORITHM)


def h(tok):
    return {"Authorization": f"Bearer {tok}", "User-Agent": UA}


def H_SUPER():
    return h(jeton("super", "admin"))


def activer(env, simulation=False):
    env.run(cv.definir_reglages(actif=True, simulation=simulation))


def il_y_a(jours):
    return (datetime.now(UTC) - timedelta(days=jours)).isoformat()


def avertir(env, cid, etape, jours_avant):
    """Avertissement déjà envoyé il y a `jours_avant` jours (pour l'échéance actuelle)."""
    client = env.run(env.db.users.find_one({"id": cid}, {"_id": 0}))
    ech = abo.etat_client(client)["echeance"]
    env.run(env.db[cv.AVERTISSEMENTS].insert_one({"cle": f"{cid}::{ech}::{etape}", "client_id": cid,
                                                  "echeance": ech, "etape": etape, "le": il_y_a(jours_avant)}))
    return ech


def preparer_c113_a_archiver(env):
    """c113 : suspendu depuis 3 jours, avertissements J+103, J+110 et J+112 déjà envoyés."""
    ech = avertir(env, "c113", "J103", 10)
    avertir(env, "c113", "J110", 3)
    avertir(env, "c113", "J112", 1)
    env.run(env.db.users.update_one({"id": "c113"}, {"$set": {"cycle_vie": {
        "statut": cv.SUSPENDU, "echeance": ech, "suspendu_le": il_y_a(3), "jours_a_la_suspension": 110}}}))
    for nom, docs in _donnees_c113().items():
        env.run(env.db[nom].insert_many([dict(d) for d in docs]))
    abo.vider_cache()
    return ech


def actions_de(rapport, cid):
    return [a["action"] for a in rapport["actions"] if a["client_id"] == cid]


def compter(env, nom, filtre=None):
    return env.run(env.db[nom].count_documents(filtre or {}))


# ===========================================================================
# 1. Réglages : interrupteur désactivé par défaut, simulation, conservation
# ===========================================================================
def test_interrupteur_desactive_par_defaut(env):
    reg = env.run(cv.reglages())
    assert reg["actif"] is False and reg["simulation"] is True
    assert reg["conservation_jours"] == 365 and reg["frais_reouverture"] == {"montant": 0.0, "devise": "XOF"}
    # Désactivé : la tâche ne fait rien, même pour un client à J+110 ou plus
    res = env.run(cv.executer("test"))
    assert res["statut"] == "DESACTIVE" and res["actions"] == []
    assert compter(env, cv.AVERTISSEMENTS) == 0 and env.envois == {"email": [], "wa": []}
    assert env.run(env.db.users.find_one({"id": "c110"}, {"_id": 0})).get("cycle_vie") is None
    # « Lancer maintenant » refusé tant que l'interrupteur est désactivé
    assert env.client.post("/api/admin/cycle-vie/lancer", headers=H_SUPER()).status_code == 409
    assert env.client.get("/api/donnees", headers=h(jeton("c110"))).status_code == 200


def test_reglages_bornes_et_reserves_au_super_admin(env):
    c = env.client
    assert c.get("/api/admin/cycle-vie", headers=h(jeton("adm2", "admin"))).status_code == 403
    assert c.get("/api/admin/cycle-vie", headers=h(jeton("c110"))).status_code == 403
    assert c.put("/api/admin/cycle-vie/reglages", json={"conservation_jours": 10}, headers=H_SUPER()).status_code == 422
    r = c.put("/api/admin/cycle-vie/reglages", json={"actif": True, "simulation": False, "conservation_jours": 730,
                                                      "frais_montant": 50000, "frais_devise": "xof"}, headers=H_SUPER())
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["actif"] and not d["simulation"] and d["conservation_jours"] == 730
    assert d["frais_reouverture"] == {"montant": 50000.0, "devise": "XOF"}
    assert cv.borner_conservation(5) == 30 and cv.borner_conservation(99999) == 3650
    assert cv.borner_conservation("x") == 365
    j = c.get("/api/admin/cycle-vie/journal", headers=H_SUPER()).json()["journal"]
    assert j[0]["action"] == "REGLAGES" and j[0]["par"]["email"] == SUPER


# ===========================================================================
# 2. Calendrier
# ===========================================================================
def test_calendrier_des_etapes(env):
    a = datetime.now(UTC)
    dom = ["sawalismartsystems.com"]
    lire = lambda cid: env.run(env.db.users.find_one({"id": cid}, {"_id": 0}))  # noqa: E731
    # J+103 : avertissement « suspension dans 7 jours »
    p = env.run(cv.planifier(lire("c103"), a, dom, 365))
    assert p["jours"] == 103 and p["actions"] == ["AVERTISSEMENT_J103"]
    ech = datetime.fromisoformat(p["echeance"]).date()
    assert p["calendrier"]["suspension"] == (ech + timedelta(days=110)).isoformat()
    assert p["calendrier"]["archivage"] == (ech + timedelta(days=113)).isoformat()
    # J+110 sans avertissement préalable : d'abord l'avertissement (jamais de suspension sans préavis)
    p = env.run(cv.planifier(lire("c110"), a, dom, 365))
    assert p["jours"] == 110 and p["actions"] == ["AVERTISSEMENT_J103"]
    # J+110, avertissement envoyé aujourd'hui seulement : suspension dans 7 jours
    avertir(env, "c110", "J103", 0)
    p = env.run(cv.planifier(lire("c110"), a, dom, 365))
    assert p["actions"] == [] and p["calendrier"]["suspension"] == (a.date() + timedelta(days=7)).isoformat()
    # J+110, avertissement envoyé il y a 7 jours (J+103) : suspension + avertissement du jour
    env.run(env.db[cv.AVERTISSEMENTS].delete_many({}))
    avertir(env, "c110", "J103", 7)
    p = env.run(cv.planifier(lire("c110"), a, dom, 365))
    assert p["actions"] == ["SUSPENSION", "AVERTISSEMENT_J110"]
    # Client à jour, sans échéance, de test, interne : jamais concernés
    assert env.run(cv.planifier(lire("ok"), a, dom, 365))["actions"] == []
    assert env.run(cv.planifier(lire("libre"), a, dom, 365)).get("sans_echeance") is True
    assert env.run(cv.planifier(lire("test"), a, dom, 365))["exclu"] == "client de test"
    assert env.run(cv.planifier(lire("interne"), a, dom, 365))["exclu"] == "compte interne"


def test_simulation_liste_sans_effet(env):
    # Simulation forcée (bouton « Simuler maintenant ») même interrupteur désactivé
    r = env.client.post("/api/admin/cycle-vie/simuler", headers=H_SUPER())
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["simulation"] is True and d["statut"] == "SIMULATION"
    assert actions_de(d, "c103") == ["AVERTISSEMENT_J103"] and actions_de(d, "c110") == ["AVERTISSEMENT_J103"]
    assert not [a for a in d["actions"] if a["client_id"] in ("test", "interne", "ok", "libre")]
    assert all(a["effectuee"] is False for a in d["actions"])
    # Rien n'a été fait : aucun avertissement enregistré ni envoyé au client, aucune suspension
    assert compter(env, cv.AVERTISSEMENTS) == 0 and env.envois["wa"] == []
    assert all("SIMULATION" in m["sujet"] for m in env.envois["email"]) and env.envois["email"][0]["to"] == SUPER
    # Interrupteur activé en mode simulation (réglage par défaut) : idem
    env.run(cv.definir_reglages(actif=True))
    res = env.run(cv.executer("cron"))
    assert res["simulation"] is True and compter(env, cv.AVERTISSEMENTS) == 0
    assert env.run(env.db.users.count_documents({"cycle_vie": {"$exists": True}})) == 0


# ===========================================================================
# 3. Avertissements (uniques) et suspension
# ===========================================================================
def test_avertissements_envoyes_une_seule_fois(env):
    activer(env)
    r1 = env.run(cv.executer("cron"))
    assert actions_de(r1, "c103") == ["AVERTISSEMENT_J103"]
    wa = [m for m in env.envois["wa"] if m["to"] == "+22670000103"]
    mails = [m for m in env.envois["email"] if m["to"] == "c103@x.bf"]
    assert len(wa) == 1 and len(mails) == 1
    assert "SUSPENDU" in wa[0]["texte"] and "Pharmacie 103" in wa[0]["texte"]
    # Deuxième passage le même jour (ou appel concurrent) : rien de plus
    r2 = env.run(cv.executer("cron"))
    assert actions_de(r2, "c103") == []
    assert len([m for m in env.envois["wa"] if m["to"] == "+22670000103"]) == 1
    assert compter(env, cv.AVERTISSEMENTS, {"client_id": "c103"}) == 1
    client = env.run(env.db.users.find_one({"id": "c103"}, {"_id": 0}))
    ech = abo.etat_client(client)["echeance"]
    res = env.run(cv.envoyer_avertissement("J103", client, ech, {}, env.run(cv.reglages())))
    assert res.get("deja_envoye") is True
    j = env.run(cv.journal("c103"))
    assert [x["action"] for x in j] == ["AVERTISSEMENT_J103"]
    # Le rapport quotidien part au super-admin
    assert any(m["to"] == SUPER and "Cycle de vie" in m["sujet"] for m in env.envois["email"])


def test_suspension_bloque_tous_les_comptes_sauf_super_admin_et_voir_en_tant_que(env):
    c = env.client
    # Sessions ouvertes avant la suspension (principal et suivi)
    r = c.post("/api/auth/login", json={"email": "caisse@c110.bf", "password": "bon-mdp", "captcha_token": "x"})
    assert r.status_code == 200, r.text
    tok_suivi = c.post("/api/auth/verify-otp", json={"session_token": r.json()["session_token"],
                                                     "code": "123456"}).json()["access_token"]
    assert c.get("/api/donnees", headers=h(tok_suivi)).status_code == 200
    avertir(env, "c110", "J103", 7)
    activer(env)
    rap = env.run(cv.executer("cron"))
    assert actions_de(rap, "c110") == ["SUSPENSION", "AVERTISSEMENT_J110"]
    fiche = env.run(env.db.users.find_one({"id": "c110"}, {"_id": 0}))
    assert fiche["cycle_vie"]["statut"] == cv.SUSPENDU and fiche["account_status"] == "active"
    assert any("SUSPENDU depuis aujourd'hui" in m["texte"] for m in env.envois["wa"] if m["to"] == "+22670000110")
    # La session ouverte est fermée (motif lisible), tout autre jeton est refusé (403 abonnement_suspendu)
    r = c.get("/api/donnees", headers=h(tok_suivi))
    assert r.status_code == 401 and r.json()["code"] == "session_abonnement_suspendu"
    for uid in ("c110", "c110-suivi"):
        r = c.get("/api/donnees", headers=h(jeton(uid)))
        assert r.status_code == 403 and r.json()["code"] == "abonnement_suspendu", r.text
        assert "Accès suspendu" in r.json()["detail"]
    r = c.get("/api/auth/me", headers=h(jeton("c110")))
    assert r.status_code == 403
    # Connexion refusée : mot de passe et code WhatsApp
    r = c.post("/api/auth/login", json={"email": "c110@x.bf", "password": "bon-mdp", "captcha_token": "x"})
    assert r.status_code == 403 and "suspendu" in r.json()["detail"]
    env.run(env.db.wa_otp_requests.insert_one({"msisdn": "22670000999", "code": "654321",
                                               "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()}))
    r = c.post("/api/auth/wa-otp/verify", json={"msisdn": "22670000999", "code": "654321"})
    assert r.status_code == 403 and "suspendu" in r.json()["detail"]
    # « Voir en tant que » (Admin) et super-admin : toujours possibles
    assert c.get("/api/donnees", headers=h(jeton("c110", imp="super", ro=True))).status_code == 200
    assert c.get("/api/donnees", headers=H_SUPER()).status_code == 200
    # Les autres clients ne sont pas touchés
    assert c.get("/api/donnees", headers=h(jeton("c103"))).status_code == 200


def test_reglement_saisi_leve_la_suspension(env):
    avertir(env, "c110", "J103", 7)
    activer(env)
    env.run(cv.executer("cron"))
    assert env.client.get("/api/donnees", headers=h(jeton("c110-suivi"))).status_code == 403
    # L'Admin saisit le règlement (Admin → Clients) : l'échéance change, l'accès revient aussitôt
    env.run(env.db.users.update_one({"id": "c110"}, {"$set": {"last_payment_at": env.aujourdhui.isoformat()}}))
    abo.vider_cache()
    assert env.client.get("/api/donnees", headers=h(jeton("c110-suivi"))).status_code == 200
    rap = env.run(cv.executer("cron"))
    assert actions_de(rap, "c110") == ["LEVEE_PAIEMENT"]
    assert env.run(env.db.users.find_one({"id": "c110"}, {"_id": 0}))["cycle_vie"]["statut"] == cv.ACTIF


def test_levee_manuelle_par_le_super_admin(env):
    avertir(env, "c110", "J103", 7)
    activer(env)
    env.run(cv.executer("cron"))
    r = env.client.post("/api/admin/cycle-vie/c110/lever-suspension", headers=H_SUPER())
    assert r.status_code == 200, r.text
    abo.vider_cache()
    assert env.client.get("/api/donnees", headers=h(jeton("c110"))).status_code == 200
    # Pas de nouvelle suspension pour cette échéance
    assert actions_de(env.run(cv.executer("cron")), "c110") == []
    assert env.client.post("/api/admin/cycle-vie/c103/lever-suspension", headers=H_SUPER()).status_code == 409


# ===========================================================================
# 4. Archive vérifiée puis suppression ; échec → rien supprimé + alerte
# ===========================================================================
def test_avertissement_veille_puis_archivage(env):
    """J+112 : avertissement « suppression demain » ; l'archivage n'a lieu que le lendemain."""
    ech = avertir(env, "c113", "J103", 10)
    avertir(env, "c113", "J110", 3)
    env.run(env.db.users.update_one({"id": "c113"}, {"$set": {"cycle_vie": {
        "statut": cv.SUSPENDU, "echeance": ech, "suspendu_le": il_y_a(3)}}}))
    activer(env)
    rap = env.run(cv.executer("cron"))
    assert actions_de(rap, "c113") == ["AVERTISSEMENT_J112"]
    assert any("Dernier avis" in m["sujet"] for m in env.envois["email"] if m["to"] == "c113@x.bf")
    assert env.run(env.db.users.find_one({"id": "c113"}, {"_id": 0}))["cycle_vie"]["statut"] == cv.SUSPENDU


def test_archive_verifiee_puis_suppression(env):
    preparer_c113_a_archiver(env)
    activer(env)
    avant_ok = {n: compter(env, n) for n in ("documents", "contacts", "tracked_users", "form_submissions")}
    rap = env.run(cv.executer("cron"))
    act = [a for a in rap["actions"] if a["client_id"] == "c113"]
    assert [a["action"] for a in act] == ["ARCHIVAGE"] and act[0]["effectuee"], act
    assert rap["alertes"] == []
    # Archive dans R2, sous archives-locataires/
    cles = list(env.r2.objets)
    assert len(cles) == 1 and cles[0].startswith("archives-locataires/c113/") and cv.RE_CLE_ARCHIVE.fullmatch(cles[0])
    # Données du client supprimées (comptes rattachés compris), celles des autres intactes
    for nom, filtre in (("documents", {"id": {"$in": ["d1", "d2"]}}), ("appointments", {}), ("contacts", {"id": "ct1"}),
                        ("forms", {}), ("form_submissions", {"id": "fs1"}), ("wa_surveys", {}),
                        ("wa_survey_responses", {}), ("officines", {}), ("officine_inventory_items", {}),
                        ("tasks", {}), ("tracked_users", {"id": "t113"}), ("users", {"id": "c113-suivi"})):
        assert compter(env, nom, filtre) == 0, nom
    assert compter(env, "documents") == avant_ok["documents"] - 2
    assert compter(env, "contacts", {"id": "ct-ok"}) == 1 and compter(env, "tracked_users", {"id": "t-ok"}) == 1
    assert compter(env, "form_submissions", {"id": "fs-autre"}) == 1
    # Conservés : règlements reçus par SAWALI et journal d'activité
    assert compter(env, "tenant_payments", {"tenant_id": "c113"}) == 1
    assert compter(env, "activity_events", {"client_id": "c113"}) == 1
    # Fiche du client conservée, réduite, au statut ARCHIVE avec la référence de l'archive
    fiche = env.run(env.db.users.find_one({"id": "c113"}, {"_id": 0}))
    assert fiche["account_status"] == "archive" and fiche["password_hash"] == ""
    arch = fiche["cycle_vie"]["archive"]
    assert fiche["cycle_vie"]["statut"] == cv.ARCHIVE and arch["cle"] == cles[0]
    assert arch["comptes"]["users"] == 2 and arch["comptes"]["officine_inventory_items"] == 2
    assert arch["documents"] == sum(arch["comptes"].values()) == 15
    assert fiche["company"] == "Pharmacie 113" and fiche["contract_number"] == "C-113"
    assert "contract_amount" in fiche and "tracked_role" not in fiche
    # L'archive se déchiffre avec SAUVEGARDE_AUTO_PHRASE et contient les données
    chemin = env.tmp / "verif.sawali"
    chemin.write_bytes(env.r2.objets[cles[0]])
    relu = cv.relire_archive(chemin, PHRASE, sc._cle_signature(), avec_documents=True)
    assert relu["signature"] == "valide" and relu["manifeste"]["client_id"] == "c113"
    assert {d["id"] for d in relu["documents"]["documents"]} == {"d1", "d2"}
    assert {d["id"] for d in relu["documents"]["users"]} == {"c113", "c113-suivi"}
    with pytest.raises(sf.PhraseIncorrecte):
        cv.relire_archive(chemin, "mauvaise-phrase-0000", None)
    # Aucun fichier en clair ni temporaire laissé sur le disque
    assert not list(env.tmp.glob("archive-client-*"))
    # Accès et connexion refusés
    assert env.client.post("/api/auth/login", json={"email": "c113@x.bf", "password": "bon-mdp",
                                                    "captcha_token": "x"}).status_code == 401
    j = [x["action"] for x in env.run(cv.journal("c113"))]
    assert "ARCHIVAGE" in j


def test_echec_de_verification_rien_supprime_et_alerte(env, monkeypatch):
    preparer_c113_a_archiver(env)
    activer(env)
    env.r2.alterer = True  # la copie relue depuis R2 est abîmée
    avant = {n: compter(env, n) for n in _donnees_c113()}
    avant["users"] = compter(env, "users")
    rap = env.run(cv.executer("cron"))
    act = [a for a in rap["actions"] if a["client_id"] == "c113"][0]
    assert act["action"] == "ARCHIVAGE" and act["effectuee"] is False and "rien n'a été supprimé" in act["erreur"]
    assert rap["alertes"] and "Pharmacie 113" in rap["alertes"][0]
    for n, v in avant.items():
        assert compter(env, n) == v, n
    fiche = env.run(env.db.users.find_one({"id": "c113"}, {"_id": 0}))
    assert fiche["cycle_vie"]["statut"] == cv.SUSPENDU and fiche["account_status"] == "active"
    alertes = [m for m in env.envois["email"] if m["to"] == SUPER and "ALERTE" in m["sujet"]]
    assert len(alertes) >= 2  # alerte immédiate + rapport quotidien marqué ALERTE
    assert any("AUCUNE donnée n'a été supprimée" in m["texte"] for m in alertes)
    assert "ARCHIVAGE_ECHEC" in [x["action"] for x in env.run(cv.journal("c113"))]
    # Sans phrase de chiffrement : rien n'est archivé ni supprimé non plus
    env.r2.alterer = False
    monkeypatch.delenv("SAUVEGARDE_AUTO_PHRASE")
    rap = env.run(cv.executer("cron"))
    act = [a for a in rap["actions"] if a["client_id"] == "c113"][0]
    assert act["effectuee"] is False and "SAUVEGARDE_AUTO_PHRASE" in act["erreur"]
    assert compter(env, "documents") == avant["documents"]


# ===========================================================================
# 5. Conservation et réouverture
# ===========================================================================
def test_conservation_puis_effacement_de_l_archive(env):
    preparer_c113_a_archiver(env)
    activer(env)
    env.run(cv.executer("cron"))
    cle = list(env.r2.objets)[0]
    # Archive vieille de 366 jours : effacée avec la conservation par défaut (365 j)…
    env.run(env.db.users.update_one({"id": "c113"}, {"$set": {"cycle_vie.archive.le": il_y_a(366)}}))
    env.run(cv.definir_reglages(conservation_jours=730))
    assert actions_de(env.run(cv.executer("cron")), "c113") == []      # … mais pas avec 730 j
    assert cle in env.r2.objets
    env.run(cv.definir_reglages(conservation_jours=365))
    rap = env.run(cv.executer("cron"))
    assert actions_de(rap, "c113") == ["EFFACEMENT_ARCHIVE"]
    assert cle not in env.r2.objets and env.r2.supprimees == [cle]
    fiche = env.run(env.db.users.find_one({"id": "c113"}, {"_id": 0}))
    assert fiche["cycle_vie"]["archive"]["effacee_le"]
    # Une clé qui ne suit pas le format n'est jamais effacée
    res = env.run(cv.effacer_archive({"id": "x", "cycle_vie": {"archive": {"cle": "sauvegardes-completes/sawali-x"}}}))
    assert res["ok"] is False
    # Archive effacée : réouverture impossible
    r = env.client.post("/api/admin/cycle-vie/c113/reouvrir", json={
        "confirmation": "REOUVRIR", "mot_de_passe": "bon-mdp"}, headers=H_SUPER())
    assert r.status_code in (400, 403, 409)


def test_reouverture_avec_frais(env, monkeypatch):
    monkeypatch.setattr(rcv, "verify_password", lambda p, h: p == "bon-mdp")
    preparer_c113_a_archiver(env)
    activer(env)
    env.run(cv.executer("cron"))
    assert env.run(env.db.users.find_one({"id": "c113"}, {"_id": 0}))["cycle_vie"]["statut"] == cv.ARCHIVE
    env.run(cv.definir_reglages(frais_montant=50000, frais_devise="XOF"))
    c = env.client
    url = "/api/admin/cycle-vie/c113/reouvrir"
    assert c.post(url, json={"confirmation": "oui", "mot_de_passe": "bon-mdp", "frais_encaisses": True},
                  headers=H_SUPER()).status_code == 400
    assert c.post(url, json={"confirmation": "REOUVRIR", "mot_de_passe": "faux", "frais_encaisses": True},
                  headers=H_SUPER()).status_code == 403
    r = c.post(url, json={"confirmation": "REOUVRIR", "mot_de_passe": "bon-mdp"}, headers=H_SUPER())
    assert r.status_code == 400 and "50000 XOF" in r.json()["detail"]
    assert c.post(url, json={"confirmation": "REOUVRIR", "mot_de_passe": "bon-mdp", "frais_encaisses": True},
                  headers=h(jeton("adm2", "admin"))).status_code == 403
    r = c.post(url, json={"confirmation": "REOUVRIR", "mot_de_passe": "bon-mdp", "frais_encaisses": True,
                          "reference": "REC-2026-001"}, headers=H_SUPER())
    assert r.status_code == 200, r.text
    assert r.json()["documents"] == 15
    # Données restaurées à l'identique
    for nom, docs in _donnees_c113().items():
        if nom in ("tenant_payments", "activity_events"):
            continue
        for d in docs:
            if d["id"].endswith("ok") or d["id"] == "fs-autre":
                continue
            lu = env.run(env.db[nom].find_one({"id": d["id"]}, {"_id": 0}))
            assert lu == d, (nom, d["id"])
    suivi = env.run(env.db.users.find_one({"id": "c113-suivi"}, {"_id": 0}))
    assert suivi["tracked_role"] == "RH" and suivi["password_hash"] == "h"
    fiche = env.run(env.db.users.find_one({"id": "c113"}, {"_id": 0}))
    assert fiche["cycle_vie"]["statut"] == cv.ACTIF and fiche["account_status"] == "active"
    assert fiche["last_payment_at"] == env.aujourdhui.isoformat() and fiche["password_hash"] == "h"
    assert abo.etat_client(fiche)["statut"] == abo.A_JOUR
    # Frais enregistrés comme règlement, réouverture journalisée
    p = env.run(env.db.tenant_payments.find_one({"type": "frais_reouverture"}, {"_id": 0}))
    assert p["amount_paid"] == 50000 and p["currency"] == "XOF" and p["invoice_ref"] == "REC-2026-001"
    assert "REOUVERTURE" in [x["action"] for x in env.run(cv.journal("c113"))]
    # Le client se reconnecte
    abo.vider_cache()
    assert c.get("/api/donnees", headers=h(jeton("c113-suivi"))).status_code == 200
    r = c.post("/api/auth/login", json={"email": "c113@x.bf", "password": "bon-mdp", "captcha_token": "x"})
    assert r.status_code == 200, r.text
    # Une deuxième réouverture est refusée
    assert c.post(url, json={"confirmation": "REOUVRIR", "mot_de_passe": "bon-mdp", "frais_encaisses": True},
                  headers=H_SUPER()).status_code == 409


def test_vue_admin_liste_retard_suspendus_archives(env):
    preparer_c113_a_archiver(env)
    d = env.client.get("/api/admin/cycle-vie", headers=H_SUPER()).json()
    ids = [x["client_id"] for x in d["clients"]]
    assert ids[0] == "c113" and "c110" in ids and "c103" in ids and "ok" not in ids and "libre" not in ids
    exclus = {x["client_id"]: x.get("exclu") for x in d["clients"] if x.get("exclu")}
    assert exclus == {"test": "client de test", "interne": "compte interne"}
    assert d["reglages"]["actif"] is False and d["archive_impossible"] is None
    assert d["calendrier"] == {"avertissement_suspension": 103, "suspension": 110,
                               "avertissement_suppression": 112, "archivage": 113}


# ===========================================================================
# 6. Connexion par code WhatsApp : statut du compte contrôlé (correction signalée au lot 50)
# ===========================================================================
@pytest.mark.parametrize("statut,attendu", [("suspended", "Compte suspendu"), ("disabled", "Compte désactivé"),
                                            ("expired", "Compte désactivé"), ("archive", "Compte désactivé")])
def test_otp_whatsapp_refuse_un_compte_inactif(env, statut, attendu):
    env.run(env.db.users.update_one({"id": "c110-suivi"}, {"$set": {"account_status": statut}}))
    env.run(env.db.wa_otp_requests.insert_one({"msisdn": "22670000999", "code": "654321",
                                               "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()}))
    r = env.client.post("/api/auth/wa-otp/verify", json={"msisdn": "22670000999", "code": "654321"})
    assert r.status_code == 403 and attendu in r.json()["detail"], r.text
    assert compter(env, "sessions_comptes") == 0


def test_otp_whatsapp_compte_actif_accepte_et_code_email_controle(env):
    env.run(env.db.wa_otp_requests.insert_one({"msisdn": "22670000999", "code": "654321",
                                               "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()}))
    r = env.client.post("/api/auth/wa-otp/verify", json={"msisdn": "22670000999", "code": "654321"})
    assert r.status_code == 200 and r.json()["user"]["id"] == "c110-suivi"
    # Code e-mail : compte désactivé entre le mot de passe et le code → refusé
    r = env.client.post("/api/auth/login", json={"email": "ok@x.bf", "password": "bon-mdp", "captcha_token": "x"})
    assert r.status_code == 200
    env.run(env.db.users.update_one({"id": "ok"}, {"$set": {"account_status": "disabled"}}))
    r2 = env.client.post("/api/auth/verify-otp", json={"session_token": r.json()["session_token"], "code": "123456"})
    assert r2.status_code == 403 and r2.json()["detail"] == "Compte désactivé"


def test_routes_branchees_et_planificateur():
    """Branchement dans server.py, tâche quotidienne dans le planificateur (DISABLE_SCHEDULER respecté)."""
    serveur = (RACINE / "server.py").read_text(encoding="utf-8")
    assert "api.include_router(_cycle_vie_router)" in serveur and "_cycle_vie.configurer(" in serveur
    p17 = (RACINE / "server_parts" / "p17_demarrage_planificateur.py").read_text(encoding="utf-8")
    debut = p17.index("async def _start_scheduler")
    assert p17.index('DISABLE_SCHEDULER") == "1"', debut) < p17.index("cycle_vie_abonnements_quotidien")
    p01 = (RACINE / "server_parts" / "p01_sante_auth_public.py").read_text(encoding="utf-8")
    assert '"refuser_si_cycle_vie": _cycle_vie_abonnements.refuser_connexion' in p01
    assert zipfile and sf.MAGIC  # format du lot 49 réutilisé
