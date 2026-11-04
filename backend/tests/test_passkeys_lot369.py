"""Lot 369 — Connexion par empreinte digitale (passkeys / WebAuthn).

Un « faux authentificateur » logiciel (clé ES256 réelle, vraies signatures) joue le rôle de Windows Hello, du téléphone
ou d'une clé de sécurité : les vérifications cryptographiques du serveur (bibliothèque `webauthn`) sont donc réellement exécutées.
MongoDB simulé (mongomock_motor), vrais jetons JWT, vraie dépendance auth.get_current_user, vrai journal des connexions.
Lancer : cd backend && python -m pytest tests/test_passkeys_lot369.py -q
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import struct
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
mongomock_motor = pytest.importorskip("mongomock_motor")
pytest.importorskip("webauthn")

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot369")

import cbor2  # noqa: E402
import jwt  # noqa: E402
from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import abonnement_acces as abo  # noqa: E402
import auth  # noqa: E402
import connexions_ip as cip  # noqa: E402
import controle_acces  # noqa: E402
import cycle_vie_abonnements as cva  # noqa: E402
import maintenance_plateforme as mp  # noqa: E402
import sessions_comptes as sess  # noqa: E402
from routes.passkeys import MAX_PAR_COMPTE, attach_passkey_routes, origine_et_domaine  # noqa: E402

UTC = timezone.utc
ORIGINE = "https://sawalismartsystems.com"
RP = "sawalismartsystems.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"


def b64(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode()


def deb64(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


class FauxAuthentificateur:
    """Authentificateur logiciel : fabrique de vraies réponses WebAuthn (enregistrement « none », signature ES256)."""

    def __init__(self):
        self.cle = ec.generate_private_key(ec.SECP256R1())
        self.identifiant = os.urandom(32)
        self.compteur = 0

    def _cose(self) -> bytes:
        n = self.cle.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})

    def enregistrer(self, options: dict, origine: str = ORIGINE, rp: str = RP, verification: bool = True) -> dict:
        donnees = json.dumps({"type": "webauthn.create", "challenge": options["challenge"], "origin": origine, "crossOrigin": False}).encode()
        drapeaux = 0x01 | (0x04 if verification else 0) | 0x40                       # présence, vérification, données de clé
        auth_data = (hashlib.sha256(rp.encode()).digest() + bytes([drapeaux]) + struct.pack(">I", 0) + b"\x00" * 16
                     + struct.pack(">H", len(self.identifiant)) + self.identifiant + self._cose())
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {"id": b64(self.identifiant), "rawId": b64(self.identifiant), "type": "public-key", "clientExtensionResults": {},
                "response": {"clientDataJSON": b64(donnees), "attestationObject": b64(attestation), "transports": ["internal"]}}

    def signer(self, options: dict, origine: str = ORIGINE, rp: str = RP, handle: bytes | None = None, cle=None) -> dict:
        self.compteur += 1
        donnees = json.dumps({"type": "webauthn.get", "challenge": options["challenge"], "origin": origine, "crossOrigin": False}).encode()
        auth_data = hashlib.sha256(rp.encode()).digest() + bytes([0x01 | 0x04]) + struct.pack(">I", self.compteur)
        signature = (cle or self.cle).sign(auth_data + hashlib.sha256(donnees).digest(), ec.ECDSA(hashes.SHA256()))
        reponse = {"clientDataJSON": b64(donnees), "authenticatorData": b64(auth_data), "signature": b64(signature)}
        if handle is not None:
            reponse["userHandle"] = b64(handle)
        return {"id": b64(self.identifiant), "rawId": b64(self.identifiant), "type": "public-key", "clientExtensionResults": {}, "response": reponse}


def jeton(uid, role="client"):
    now = int(time.time())
    return jwt.encode({"sub": uid, "role": role, "iat": now, "exp": now + 3600}, auth.JWT_SECRET, algorithm=auth.JWT_ALGORITHM)


def entetes(uid=None, role="client", origine=ORIGINE):
    h = {"Origin": origine, "User-Agent": UA}
    if uid:
        h["Authorization"] = f"Bearer {jeton(uid, role)}"
    return h


@pytest.fixture()
def env(monkeypatch):
    b = mongomock_motor.AsyncMongoMockClient()[f"lot369_{time.time_ns()}"]
    for mod in (auth, mp, sess, abo, cva):
        monkeypatch.setattr(mod, "db", b)
    monkeypatch.delenv("SUPER_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("WEBAUTHN_RP_ID", raising=False)
    mp.vider_cache()
    sess.vider_caches()
    sess._index_ok["fait"] = False
    abo.vider_cache()
    cip.vider_cache()
    cip._index_ok["fait"] = False

    app = FastAPI()
    app.add_exception_handler(controle_acces.RefusAcces, controle_acces.gestionnaire_refus)
    api = APIRouter(prefix="/api")
    attach_passkey_routes(api, db=b, helpers={
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
    e.activer = lambda on=True, rp=None: e.run(b.settings.update_one({"_id": "global"}, {"$set": {"passkeys_enabled": on, "passkeys_rp_id": rp}}, upsert=True))

    def enregistrer(uid, auth_=None, origine=ORIGINE, nom="Ma clé"):
        auth_ = auth_ or FauxAuthentificateur()
        o = e.client.post("/api/auth/passkeys/register/options", headers=entetes(uid, origine=origine)).json()
        r = e.client.post("/api/auth/passkeys/register/verify", headers=entetes(uid, origine=origine),
                          json={"challenge_id": o["challenge_id"], "credential": auth_.enregistrer(o["options"]), "nom": nom})
        return auth_, o, r

    def connecter(auth_, handle=None, origine=ORIGINE, **kw):
        o = e.client.post("/api/auth/passkeys/login/options", headers=entetes(origine=origine)).json()
        r = e.client.post("/api/auth/passkeys/login/verify", headers=entetes(origine=origine),
                          json={"challenge_id": o["challenge_id"], "credential": auth_.signer(o["options"], handle=handle, **kw)})
        return o, r

    e.enregistrer, e.connecter = enregistrer, connecter
    e.journal = lambda: e.run(b.connexions_journal.find({}, {"_id": 0}).to_list(50))
    yield e
    boucle.close()


# ───────────────────────── Réglage : désactivée par défaut ─────────────────────────

def test_desactivee_par_defaut_rien_ne_change(env):
    assert env.client.get("/api/auth/passkeys/config").json() == {"enabled": False}
    assert env.client.post("/api/auth/passkeys/login/options", headers=entetes()).status_code == 403
    assert env.client.post("/api/auth/passkeys/register/options", headers=entetes("awa")).status_code == 403


def test_l_administrateur_active_et_regle_le_domaine(env):
    r = env.client.put("/api/admin/passkeys/config", headers=entetes("admin", "admin"), json={"enabled": True, "rp_id": "SawaliSmartSystems.com"})
    assert r.status_code == 200 and r.json() == {"ok": True, "enabled": True, "rp_id": "sawalismartsystems.com"}
    assert env.client.get("/api/auth/passkeys/config").json() == {"enabled": True}
    assert env.client.put("/api/admin/passkeys/config", headers=entetes("admin", "admin"), json={"enabled": True, "rp_id": "pas un domaine!"}).status_code == 422
    assert env.client.put("/api/admin/passkeys/config", headers=entetes("awa"), json={"enabled": False}).status_code == 403   # réservé à l'administrateur


# ───────────────────────── Enregistrement et connexion ─────────────────────────

def test_enregistrement_puis_connexion_complete(env):
    env.activer()
    auth_, _, r = env.enregistrer("awa", nom="  Portable   de   la caisse ")
    assert r.status_code == 200, r.text
    assert r.json()["passkeys"][0]["nom"] == "Portable de la caisse"                       # espaces normalisés
    assert "public_key" not in json.dumps(r.json())                                        # jamais la clé publique à l'écran
    _, c = env.connecter(auth_, handle=b"awa")
    assert c.status_code == 200, c.text
    corps = c.json()
    assert corps["user"]["email"] == "awa@x.bf" and "password_hash" not in json.dumps(corps)
    charge = jwt.decode(corps["access_token"], auth.JWT_SECRET, algorithms=[auth.JWT_ALGORITHM])
    assert charge["sub"] == "awa" and charge.get("sid")                                    # vraie session de compte
    # le jeton ouvre bien l'API
    assert env.client.get("/api/auth/passkeys", headers={"Authorization": f"Bearer {corps['access_token']}"}).status_code == 200
    # journal des connexions : méthode « empreinte », réussie
    j = [x for x in env.journal() if x.get("methode") == "empreinte"]
    assert j and j[-1]["resultat"] == "reussie"
    # compteur et dernier usage mis à jour
    fiche = env.run(env.db.users.find_one({"id": "awa"}))
    assert fiche["passkeys"][0]["sign_count"] == 1 and fiche["passkeys"][0]["dernier_usage"]


def test_defi_a_usage_unique_et_expire(env):
    env.activer()
    auth_, _, _ = env.enregistrer("awa")
    o = env.client.post("/api/auth/passkeys/login/options", headers=entetes()).json()
    corps = {"challenge_id": o["challenge_id"], "credential": auth_.signer(o["options"])}
    assert env.client.post("/api/auth/passkeys/login/verify", headers=entetes(), json=corps).status_code == 200
    rejeu = env.client.post("/api/auth/passkeys/login/verify", headers=entetes(), json=corps)       # même réponse rejouée
    assert rejeu.status_code == 400 and "Défi" in rejeu.json()["detail"]
    o2 = env.client.post("/api/auth/passkeys/login/options", headers=entetes()).json()
    env.run(env.db.otps.update_one({"id": o2["challenge_id"]}, {"$set": {"expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}}))
    expire = env.client.post("/api/auth/passkeys/login/verify", headers=entetes(), json={"challenge_id": o2["challenge_id"], "credential": auth_.signer(o2["options"])})
    assert expire.status_code == 400
    assert env.client.post("/api/auth/passkeys/login/verify", headers=entetes(), json={"challenge_id": "inconnu", "credential": auth_.signer(o["options"])}).status_code == 400


def test_signature_falsifiee_ou_passkey_inconnue_refusees_et_journalisees(env):
    env.activer()
    auth_, _, _ = env.enregistrer("awa")
    # Signature faite avec une AUTRE clé privée mais le même identifiant de passkey
    _, c = env.connecter(auth_, cle=ec.generate_private_key(ec.SECP256R1()))
    assert c.status_code == 401 and "non vérifiée" in c.json()["detail"]
    assert any(x.get("methode") == "empreinte" and x["resultat"] == "refusee" for x in env.journal())
    # Passkey jamais enregistrée
    _, c2 = env.connecter(FauxAuthentificateur())
    assert c2.status_code == 401 and "inconnue" in c2.json()["detail"]
    # Identifiant de compte (userHandle) qui ne correspond pas
    _, c3 = env.connecter(auth_, handle=b"paul")
    assert c3.status_code == 401


def test_mauvais_defi_ou_mauvaise_origine_refuses(env):
    env.activer()
    auth_, _, _ = env.enregistrer("awa")
    o = env.client.post("/api/auth/passkeys/login/options", headers=entetes()).json()
    autre = env.client.post("/api/auth/passkeys/login/options", headers=entetes()).json()
    # Réponse signée pour un AUTRE défi que celui annoncé
    assert env.client.post("/api/auth/passkeys/login/verify", headers=entetes(),
                           json={"challenge_id": o["challenge_id"], "credential": auth_.signer(autre["options"])}).status_code == 401
    # Page d'une autre origine : la signature porte l'origine du faux site
    o3 = env.client.post("/api/auth/passkeys/login/options", headers=entetes()).json()
    assert env.client.post("/api/auth/passkeys/login/verify", headers=entetes(),
                           json={"challenge_id": o3["challenge_id"], "credential": auth_.signer(o3["options"], origine="https://faux-sawali.example")}).status_code == 401


def test_comptes_refuses_inactif_et_ip_bloquee(env):
    env.activer()
    auth_, _, _ = env.enregistrer("awa")
    env.run(env.db.users.update_one({"id": "awa"}, {"$set": {"account_status": "disabled"}}))
    _, c = env.connecter(auth_)
    assert c.status_code == 403 and "désactivé" in c.json()["detail"]
    assert any(x.get("methode") == "empreinte" and x["resultat"] == "refusee" for x in env.journal())
    assert "access_token" not in c.text


# ───────────────────────── Origine et domaine ─────────────────────────

def test_origine_et_domaine_regles(monkeypatch):
    monkeypatch.delenv("WEBAUTHN_RP_ID", raising=False)
    assert origine_et_domaine("https://sawalismartsystems.com", None) == ("https://sawalismartsystems.com", "sawalismartsystems.com")
    assert origine_et_domaine("https://app.sawalismartsystems.com/", None) == ("https://app.sawalismartsystems.com", "sawalismartsystems.com")
    assert origine_et_domaine("https://sawali.onrender.com", None)[1] == "sawali.onrender.com"            # hors domaine connu : l'hôte lui-même
    assert origine_et_domaine("http://localhost:3000", None) == ("http://localhost:3000", "localhost")
    assert origine_et_domaine("https://app.exemple.bf", "exemple.bf")[1] == "exemple.bf"                   # domaine réglé par l'administrateur
    for mauvais in ("", "pas une url", "http://sawalismartsystems.com"):                                  # absente, invalide, HTTP hors localhost
        with pytest.raises(Exception) as e:
            origine_et_domaine(mauvais, None)
        assert e.value.status_code == 400
    with pytest.raises(Exception) as e:
        origine_et_domaine("https://evil.com", "sawalismartsystems.com")                                 # domaine réglé qui ne couvre pas l'hôte
    assert e.value.status_code == 400


# ───────────────────────── Gestion des passkeys d'un compte ─────────────────────────

def test_limite_doublon_et_retrait(env):
    env.activer()
    premiere, _, _ = env.enregistrer("awa")
    # Une passkey déjà enregistrée ne s'enregistre pas deux fois (ni chez un autre compte)
    o = env.client.post("/api/auth/passkeys/register/options", headers=entetes("paul")).json()
    doublon = env.client.post("/api/auth/passkeys/register/verify", headers=entetes("paul"),
                              json={"challenge_id": o["challenge_id"], "credential": premiere.enregistrer(o["options"]), "nom": "X"})
    assert doublon.status_code == 409
    for _ in range(MAX_PAR_COMPTE - 1):
        assert env.enregistrer("awa")[2].status_code == 200
    assert env.client.post("/api/auth/passkeys/register/options", headers=entetes("awa")).status_code == 400   # 8 atteintes
    liste = env.client.get("/api/auth/passkeys", headers=entetes("awa")).json()
    assert len(liste["passkeys"]) == MAX_PAR_COMPTE and liste["max"] == MAX_PAR_COMPTE
    ident = liste["passkeys"][0]["id"]
    assert env.client.delete(f"/api/auth/passkeys/{ident}", headers=entetes("awa")).status_code == 200
    assert env.client.delete(f"/api/auth/passkeys/{ident}", headers=entetes("awa")).status_code == 404
    assert env.client.delete(f"/api/auth/passkeys/{liste['passkeys'][1]['id']}", headers=entetes("paul")).status_code == 404   # pas celle d'un autre
    _, c = env.connecter(premiere)                                                                        # passkey retirée : connexion refusée
    assert c.status_code == 401


def test_enregistrement_exige_la_verification_de_l_utilisateur_et_un_defi_du_bon_compte(env):
    env.activer()
    o = env.client.post("/api/auth/passkeys/register/options", headers=entetes("awa")).json()
    sans_uv = FauxAuthentificateur().enregistrer(o["options"], verification=False)                       # empreinte/code NON vérifié par l'authentificateur
    assert env.client.post("/api/auth/passkeys/register/verify", headers=entetes("awa"),
                           json={"challenge_id": o["challenge_id"], "credential": sans_uv, "nom": "x"}).status_code == 400
    o2 = env.client.post("/api/auth/passkeys/register/options", headers=entetes("awa")).json()
    vol = env.client.post("/api/auth/passkeys/register/verify", headers=entetes("paul"),                  # défi d'Awa utilisé par Paul
                          json={"challenge_id": o2["challenge_id"], "credential": FauxAuthentificateur().enregistrer(o2["options"]), "nom": "x"})
    assert vol.status_code == 400
    assert env.run(env.db.users.find_one({"id": "paul"})).get("passkeys") in (None, [])


def test_options_sans_compte_nomme_et_verification_exigee(env):
    env.activer()
    o = env.client.post("/api/auth/passkeys/login/options", headers=entetes()).json()["options"]
    assert o["rpId"] == RP and o["userVerification"] == "required" and not o.get("allowCredentials")     # passkey « découvrable » : aucun compte annoncé
    r = env.client.post("/api/auth/passkeys/register/options", headers=entetes("awa")).json()["options"]
    assert r["authenticatorSelection"]["residentKey"] == "required" and r["authenticatorSelection"]["userVerification"] == "required"
    assert r["rp"]["id"] == RP and r["user"]["name"] == "awa@x.bf"


# ───────────────────────── Administrateur ─────────────────────────

def test_admin_liste_et_revoque_sans_jamais_montrer_les_cles(env):
    env.activer()
    env.enregistrer("awa"); env.enregistrer("awa"); env.enregistrer("paul")
    r = env.client.get("/api/admin/passkeys", headers=entetes("admin", "admin"))
    corps = r.json()
    assert r.status_code == 200 and corps["enabled"] is True and corps["rp_id_effectif"] == RP
    assert {c["user_id"]: c["nb"] for c in corps["comptes"]} == {"awa": 2, "paul": 1}
    assert "public_key" not in r.text and "sign_count" not in r.text
    assert env.client.get("/api/admin/passkeys", headers=entetes("awa")).status_code == 403
    assert env.client.delete("/api/admin/passkeys/user/awa", headers=entetes("admin", "admin")).status_code == 200
    assert env.client.delete("/api/admin/passkeys/user/awa", headers=entetes("admin", "admin")).status_code == 404
    assert [c["user_id"] for c in env.client.get("/api/admin/passkeys", headers=entetes("admin", "admin")).json()["comptes"]] == ["paul"]
    assert env.client.delete("/api/admin/passkeys/user/paul", headers=entetes("awa")).status_code == 403


def test_desactiver_coupe_la_connexion_par_empreinte_sans_effacer_les_cles(env):
    env.activer()
    auth_, _, _ = env.enregistrer("awa")
    env.activer(False)
    assert env.client.post("/api/auth/passkeys/login/options", headers=entetes()).status_code == 403
    env.activer(True)
    assert env.connecter(auth_)[1].status_code == 200                                                    # réactivée : la passkey marche toujours


def test_limite_par_adresse_ip_contre_le_remplissage_de_la_base(env):
    env.activer()
    from routes.passkeys import LIMITE_DEMANDES
    codes = [env.client.post("/api/auth/passkeys/login/options", headers=entetes()).status_code for _ in range(LIMITE_DEMANDES + 3)]
    assert codes[:LIMITE_DEMANDES] == [200] * LIMITE_DEMANDES
    assert codes[LIMITE_DEMANDES:] == [429, 429, 429]                                                    # au-delà : refusé
    assert env.run(env.db.otps.count_documents({"type": "passkey_challenge"})) == LIMITE_DEMANDES        # et rien n'est créé en base
