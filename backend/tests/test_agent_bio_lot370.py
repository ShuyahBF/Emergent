"""Lot 370 — Connexion par l'agent biométrique Loois.

Un « faux agent » logiciel (clé ECDSA P-256 réelle, signature brute r‖s comme l'agent .NET) joue le rôle de LooisBioAgent :
les vérifications du serveur (signature, défi, site, durée, compte lié, refus de compte) sont réellement exécutées.
MongoDB simulé (mongomock_motor), vrais jetons JWT, vrai journal des connexions.
Lancer : cd backend && python -m pytest tests/test_agent_bio_lot370.py -q
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
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
os.environ.setdefault("DB_NAME", "sawali_test_lot370")

import jwt  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature  # noqa: E402
from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import abonnement_acces as abo  # noqa: E402
import auth  # noqa: E402
import connexions_ip as cip  # noqa: E402
import controle_acces  # noqa: E402
import cycle_vie_abonnements as cva  # noqa: E402
import maintenance_plateforme as mp  # noqa: E402
import sessions_comptes as sess  # noqa: E402
from routes.agent_biometrique import (  # noqa: E402
    attach_agent_bio_routes, cle_personne, cle_publique_depuis_texte, origine_page, valider_attestation, verifier_signature)

UTC = timezone.utc
SITE = "https://sawalismartsystems.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"


def b64u(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode()


class FauxAgent:
    """Même format que LooisBioAgent : charge JSON + signature brute r‖s (64 octets), Base64 URL, séparées par un point."""

    def __init__(self, cle=None):
        self.cle = cle or ec.generate_private_key(ec.SECP256R1())
        self.der = self.cle.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        self.id = hashlib.sha256(self.der).hexdigest()[:16]
        self.cle_b64 = base64.b64encode(self.der).decode()

    def attester(self, defi: str, personne: str, site: str = SITE, ecart: int = 0, duree: int = 120, version: int = 1, agent_id: str | None = None) -> str:
        now = int(time.time()) + ecart
        charge = json.dumps({"v": version, "agent": agent_id or self.id, "site": site, "defi": defi, "personne": personne, "score": 90,
                             "emis": now, "expire": now + duree}, separators=(",", ":")).encode()
        r, s = decode_dss_signature(self.cle.sign(charge, ec.ECDSA(hashes.SHA256())))
        return b64u(charge) + "." + b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def jeton(uid, role="client"):
    now = int(time.time())
    return jwt.encode({"sub": uid, "role": role, "iat": now, "exp": now + 3600}, auth.JWT_SECRET, algorithm=auth.JWT_ALGORITHM)


def entetes(uid=None, role="client", origine=SITE):
    h = {"Origin": origine, "User-Agent": UA}
    if uid:
        h["Authorization"] = f"Bearer {jeton(uid, role)}"
    return h


@pytest.fixture()
def env(monkeypatch):
    b = mongomock_motor.AsyncMongoMockClient()[f"lot370_{time.time_ns()}"]
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
    attach_agent_bio_routes(api, db=b, helpers={
        "get_current_user": auth.get_current_user, "create_session_token": auth.create_session_token,
        "_to_user_public": lambda u: {k: u.get(k) for k in ("id", "email", "full_name", "role", "created_at")},
        "_uuid": lambda: f"id-{time.time_ns()}",
        "refuser_si_maintenance": mp.refuser_si_maintenance, "refuser_si_cycle_vie": cva.refuser_connexion,
    })
    app.include_router(api)
    e = SimpleNamespace(db=b, client=TestClient(app))
    boucle = asyncio.new_event_loop()
    e.run = boucle.run_until_complete
    e.run(b.users.insert_many([
        {"id": "admin", "email": "admin@sawali.bf", "full_name": "Admin", "role": "admin", "account_status": "active", "password_hash": "h", "created_at": "2026-01-01"},
        {"id": "awa", "email": "awa@x.bf", "full_name": "Awa Kaboré", "role": "client", "account_status": "active", "password_hash": "h", "created_at": "2026-01-01"},
        {"id": "paul", "email": "paul@x.bf", "full_name": "Paul Ouédraogo", "role": "client", "account_status": "active", "password_hash": "h", "created_at": "2026-01-01"},
    ]))
    adm = entetes("admin", "admin")

    def preparer(agent: FauxAgent | None = None, lier=(("awa", "Awa"),)):
        """Active la fonction, enregistre un agent et lie des comptes à des personnes."""
        agent = agent or FauxAgent()
        assert e.client.put("/api/admin/agent-bio/config", headers=adm, json={"enabled": True}).status_code == 200
        assert e.client.post("/api/admin/agent-bio/agents", headers=adm, json={"nom": "Accueil", "cle_publique": agent.cle_b64}).status_code == 200
        for uid, personne in lier:
            assert e.client.put(f"/api/admin/agent-bio/user/{uid}", headers=adm, json={"personne": personne}).status_code == 200
        return agent

    def connecter(agent, personne, origine=SITE, **kw):
        d = e.client.post("/api/auth/agent-bio/defi", headers=entetes(origine=origine)).json()
        r = e.client.post("/api/auth/agent-bio/connexion", headers=entetes(origine=origine),
                          json={"challenge_id": d["challenge_id"], "attestation": agent.attester(d["defi"], personne, **kw)})
        return d, r

    e.preparer, e.connecter, e.adm = preparer, connecter, adm
    e.journal = lambda: e.run(b.connexions_journal.find({}, {"_id": 0}).to_list(50))
    yield e
    boucle.close()


# ───────────────────────── Logique pure ─────────────────────────

def test_signature_au_format_de_l_agent_dotnet_et_alterations():
    a = FauxAgent()
    j = a.attester("defi-0123456789abcdef", "awa")
    assert verifier_signature(j, a.der)["personne"] == "awa"
    charge, sig = j.split(".")
    faux = b64u(base64.urlsafe_b64decode(charge + "==").replace(b"awa", b"bob")) + "." + sig
    assert verifier_signature(faux, a.der) is None                                  # charge modifiée
    assert verifier_signature(j, FauxAgent().der) is None                           # autre agent
    assert verifier_signature("n'importe quoi", a.der) is None
    assert verifier_signature(charge + "." + b64u(b"\x00" * 10), a.der) is None     # signature de mauvaise taille


def test_validation_site_defi_duree_horloge():
    att = {"v": 1, "site": SITE, "defi": "d" * 20, "personne": "awa", "emis": 1000, "expire": 1120}
    assert valider_attestation(att, SITE, "d" * 20, 1050) == ""
    assert "autre site" in valider_attestation(att, "https://autre.example", "d" * 20, 1050)
    assert "Défi" in valider_attestation(att, SITE, "x" * 20, 1050)
    assert "expirée" in valider_attestation(att, SITE, "d" * 20, 1121)
    assert "futur" in valider_attestation(att, SITE, "d" * 20, 900)
    assert "Version" in valider_attestation({**att, "v": 2}, SITE, "d" * 20, 1050)
    assert valider_attestation({**att, "personne": " "}, SITE, "d" * 20, 1050)
    assert valider_attestation({"v": 1, "site": SITE, "defi": "d" * 20, "personne": "a"}, SITE, "d" * 20, 1050)   # dates absentes


def test_cle_publique_acceptee_seulement_p256():
    a = FauxAgent()
    der, ident = cle_publique_depuis_texte("  " + a.cle_b64[:20] + "\n" + a.cle_b64[20:] + "  ")    # retours à la ligne tolérés
    assert der == a.der and ident == a.id
    autre = ec.generate_private_key(ec.SECP384R1()).public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    for mauvais in ("pas du base64 !", base64.b64encode(b"abc").decode(), base64.b64encode(autre).decode()):
        with pytest.raises(Exception) as ex:
            cle_publique_depuis_texte(mauvais)
        assert getattr(ex.value, "status_code", None) == 422


def test_origine_page_et_cle_personne():
    assert origine_page("https://SawaliSmartSystems.com/") == SITE
    assert origine_page("http://localhost:3000") == "http://localhost:3000"
    for mauvais in ("", "http://sawalismartsystems.com", "ftp://x", "null"):
        with pytest.raises(Exception):
            origine_page(mauvais)
    assert cle_personne("  AwA ") == "awa"


# ───────────────────────── Réglage ─────────────────────────

def test_desactivee_par_defaut_rien_ne_change(env):
    assert env.client.get("/api/auth/agent-bio/config").json() == {"enabled": False}
    assert env.client.post("/api/auth/agent-bio/defi", headers=entetes()).status_code == 403
    assert env.client.post("/api/auth/agent-bio/connexion", headers=entetes(), json={"challenge_id": "x", "attestation": "y"}).status_code == 403


def test_le_bouton_n_apparait_qu_avec_un_agent_enregistre(env):
    env.client.put("/api/admin/agent-bio/config", headers=env.adm, json={"enabled": True})
    assert env.client.get("/api/auth/agent-bio/config").json() == {"enabled": False}          # activée mais aucun agent
    env.preparer()
    assert env.client.get("/api/auth/agent-bio/config").json() == {"enabled": True}


def test_administration_reservee_a_l_administrateur(env):
    a = FauxAgent()
    h = entetes("awa")
    assert env.client.get("/api/admin/agent-bio", headers=h).status_code == 403
    assert env.client.put("/api/admin/agent-bio/config", headers=h, json={"enabled": True}).status_code == 403
    assert env.client.post("/api/admin/agent-bio/agents", headers=h, json={"nom": "x", "cle_publique": a.cle_b64}).status_code == 403
    assert env.client.put("/api/admin/agent-bio/user/awa", headers=h, json={"personne": "Awa"}).status_code == 403
    assert env.client.delete("/api/admin/agent-bio/agents/abc", headers=h).status_code == 403


def test_enregistrement_des_agents_et_des_liens(env):
    a = env.preparer()
    etat = env.client.get("/api/admin/agent-bio", headers=env.adm).json()
    assert etat["enabled"] and etat["agents"][0]["id"] == a.id and "cle_publique" not in json.dumps(etat)
    assert etat["comptes"][0]["personne"] == "Awa"
    # même agent deux fois → 409 ; clé invalide → 422
    assert env.client.post("/api/admin/agent-bio/agents", headers=env.adm, json={"nom": "bis", "cle_publique": a.cle_b64}).status_code == 409
    assert env.client.post("/api/admin/agent-bio/agents", headers=env.adm, json={"nom": "bis", "cle_publique": "x" * 30}).status_code == 422
    # une personne = un seul compte (casse ignorée)
    assert env.client.put("/api/admin/agent-bio/user/paul", headers=env.adm, json={"personne": " awa "}).status_code == 409
    assert env.client.put("/api/admin/agent-bio/user/paul", headers=env.adm, json={"personne": "Paul"}).status_code == 200
    assert env.client.put("/api/admin/agent-bio/user/inconnu", headers=env.adm, json={"personne": "Zoé"}).status_code == 404
    # délier, retirer l'agent
    assert env.client.delete("/api/admin/agent-bio/user/paul", headers=env.adm).status_code == 200
    assert env.client.delete("/api/admin/agent-bio/user/paul", headers=env.adm).status_code == 404
    assert env.client.delete(f"/api/admin/agent-bio/agents/{a.id}", headers=env.adm).status_code == 200
    assert env.client.get("/api/auth/agent-bio/config").json() == {"enabled": False}


def test_lien_par_adresse_email(env):
    env.client.put("/api/admin/agent-bio/config", headers=env.adm, json={"enabled": True})
    assert env.client.post("/api/admin/agent-bio/lier", headers=env.adm, json={"email": "PAUL@x.bf", "personne": "Paul"}).status_code == 200   # casse ignorée
    assert env.run(env.db.users.find_one({"id": "paul"}))["agent_bio"]["cle"] == "paul"
    assert env.client.post("/api/admin/agent-bio/lier", headers=env.adm, json={"email": "nul@x.bf", "personne": "Zoé"}).status_code == 404
    assert env.client.post("/api/admin/agent-bio/lier", headers=env.adm, json={"email": "awa@x.bf", "personne": "paul"}).status_code == 409
    assert env.client.post("/api/admin/agent-bio/lier", headers=entetes("awa"), json={"email": "awa@x.bf", "personne": "Awa"}).status_code == 403


def test_plafond_du_nombre_d_agents(env):
    env.client.put("/api/admin/agent-bio/config", headers=env.adm, json={"enabled": True})
    for i in range(20):
        assert env.client.post("/api/admin/agent-bio/agents", headers=env.adm, json={"nom": f"Poste {i}", "cle_publique": FauxAgent().cle_b64}).status_code == 200
    assert env.client.post("/api/admin/agent-bio/agents", headers=env.adm, json={"nom": "21e", "cle_publique": FauxAgent().cle_b64}).status_code == 400


# ───────────────────────── Connexion ─────────────────────────

def test_connexion_complete_par_l_agent(env):
    a = env.preparer()
    d, r = env.connecter(a, "awa")                                                   # casse différente du lien « Awa » : acceptée
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["user"]["email"] == "awa@x.bf" and "password_hash" not in json.dumps(corps)
    charge = jwt.decode(corps["access_token"], auth.JWT_SECRET, algorithms=[auth.JWT_ALGORITHM])
    assert charge["sub"] == "awa" and charge.get("sid")
    j = [x for x in env.journal() if x.get("methode") == "empreinte"]
    assert j and j[-1]["resultat"] == "reussie"
    fiche = env.run(env.db.users.find_one({"id": "awa"}))
    assert fiche["agent_bio"]["dernier_usage"] and fiche["agent_bio"]["agent"] == a.id


def test_defi_a_usage_unique_et_expire(env):
    a = env.preparer()
    d = env.client.post("/api/auth/agent-bio/defi", headers=entetes()).json()
    corps = {"challenge_id": d["challenge_id"], "attestation": a.attester(d["defi"], "Awa")}
    assert env.client.post("/api/auth/agent-bio/connexion", headers=entetes(), json=corps).status_code == 200
    rejeu = env.client.post("/api/auth/agent-bio/connexion", headers=entetes(), json=corps)
    assert rejeu.status_code == 400 and "Défi" in rejeu.json()["detail"]
    d2 = env.client.post("/api/auth/agent-bio/defi", headers=entetes()).json()
    env.run(env.db.otps.update_one({"id": d2["challenge_id"]}, {"$set": {"expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}}))
    assert env.client.post("/api/auth/agent-bio/connexion", headers=entetes(), json={"challenge_id": d2["challenge_id"], "attestation": a.attester(d2["defi"], "Awa")}).status_code == 400
    assert env.client.post("/api/auth/agent-bio/connexion", headers=entetes(), json={"challenge_id": "inconnu", "attestation": a.attester("x" * 20, "Awa")}).status_code == 400


def test_attestation_d_un_autre_defi_refusee_et_defi_consomme(env):
    a = env.preparer()
    d = env.client.post("/api/auth/agent-bio/defi", headers=entetes()).json()
    r = env.client.post("/api/auth/agent-bio/connexion", headers=entetes(), json={"challenge_id": d["challenge_id"], "attestation": a.attester("un-autre-defi-0123456789", "Awa")})
    assert r.status_code == 401
    # le défi est brûlé : même une bonne attestation ensuite est refusée (pas d'essais répétés sur un même défi)
    r2 = env.client.post("/api/auth/agent-bio/connexion", headers=entetes(), json={"challenge_id": d["challenge_id"], "attestation": a.attester(d["defi"], "Awa")})
    assert r2.status_code == 400


def test_refus_faux_agent_autre_site_expiree_future_version(env):
    a = env.preparer()
    for nom, kw, agent in [
        ("faux agent (clé inconnue, même identifiant)", {"agent_id": a.id}, FauxAgent()),
        ("agent non enregistré", {}, FauxAgent()),
        ("autre site", {"site": "https://faux-sawali.example"}, a),
        ("expirée", {"ecart": -600}, a),
        ("datée du futur", {"ecart": 600}, a),
        ("version inconnue", {"version": 2}, a),
    ]:
        d, r = env.connecter(agent, "Awa", **kw)
        assert r.status_code == 401, nom
        assert "access_token" not in r.text, nom


def test_page_d_une_autre_origine_refusee(env):
    a = env.preparer()
    # la page pirate appelle SAWALI avec SON origine : l'attestation (émise pour sawalismartsystems.com) ne vaut pas
    d = env.client.post("/api/auth/agent-bio/defi", headers=entetes(origine="https://pirate.example")).json()
    r = env.client.post("/api/auth/agent-bio/connexion", headers=entetes(origine="https://pirate.example"),
                        json={"challenge_id": d["challenge_id"], "attestation": a.attester(d["defi"], "Awa")})
    assert r.status_code == 401
    assert env.client.post("/api/auth/agent-bio/defi", headers={"User-Agent": UA}).status_code == 400          # sans origine : refusé


def test_personne_non_liee_ou_compte_inactif(env):
    a = env.preparer()
    d, r = env.connecter(a, "Inconnue")
    assert r.status_code == 401 and "aucun compte" in r.json()["detail"]
    env.run(env.db.users.update_one({"id": "awa"}, {"$set": {"account_status": "disabled"}}))
    d, r = env.connecter(a, "Awa")
    assert r.status_code == 403 and "access_token" not in r.text
    assert any(x.get("methode") == "empreinte" and x["resultat"] == "refusee" for x in env.journal())


def test_deux_personnes_deux_comptes(env):
    a = env.preparer(lier=(("awa", "Awa"), ("paul", "Paul")))
    for personne, uid in (("Paul", "paul"), ("Awa", "awa")):
        _, r = env.connecter(a, personne)
        assert jwt.decode(r.json()["access_token"], auth.JWT_SECRET, algorithms=[auth.JWT_ALGORITHM])["sub"] == uid


def test_limite_de_demandes_par_adresse(env):
    env.preparer()
    codes = [env.client.post("/api/auth/agent-bio/defi", headers=entetes()).status_code for _ in range(32)]
    assert codes.count(429) >= 1 and codes[0] == 200
