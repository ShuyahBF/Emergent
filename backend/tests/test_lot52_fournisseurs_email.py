"""Lot 52 — Choix du service d'envoi des e-mails (Resend, ZeptoMail, Brevo, SMTP).
httpx simulé (aucun appel réseau), MongoDB simulé (mongomock_motor), vrai chiffrement, vraies
dépendances get_current_admin / get_super_admin (seul l'utilisateur courant est fourni par le test).
Clés fictives uniquement.
Lancer : cd backend && python -m pytest tests/test_lot52_fournisseurs_email.py -q
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot52")

import httpx  # noqa: E402
from fastapi import APIRouter, FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import email_fournisseurs as ef  # noqa: E402
import email_service  # noqa: E402
import routes.fournisseurs_email as rfe  # noqa: E402

SUPER = "admin@sawalismartsystems.com"
JWT = "secret-tests-0123456789-abcdef"
CLE = "cle_test_resend_0001"
VARIABLES = ("RESEND_API_KEY", "RESEND_EXPEDITEUR", "BREVO_API_KEY", "ZEPTOMAIL_API_KEY", "ZEPTOMAIL_HOTE",
             "EMAIL_EXPEDITEUR", "EMAIL_NOM", "SUPER_ADMIN_EMAIL")
SMTP_ENV = ("HOST", "HOTE", "PORT", "USER", "UTILISATEUR", "USERNAME", "PASSWORD", "MOT_DE_PASSE", "PASS",
            "FROM_EMAIL", "FROM", "EXPEDITEUR", "FROM_NAME", "NOM", "USE_TLS", "STARTTLS")


# ---------------------------------------------------------------------------
# httpx simulé : enregistre chaque appel et renvoie la réponse programmée
# ---------------------------------------------------------------------------
class FauxHttpx:
    def __init__(self):
        self.appels = []
        self.reponse = (200, {"id": "msg-1"})
        self.exception = None

    def fabrique(self):
        faux = self

        class Client:
            def __init__(self, *a, timeout=None, **k):
                faux.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, json=None, headers=None):  # noqa: A002
                faux.appels.append({"url": url, "json": json, "headers": headers})
                if faux.exception:
                    raise faux.exception
                code, corps = faux.reponse
                if isinstance(corps, (dict, list)):
                    return httpx.Response(code, json=corps)
                return httpx.Response(code, text=corps)
        return Client


@pytest.fixture()
def env(monkeypatch):
    b = mongomock_motor.AsyncMongoMockClient()[f"lot52_{time.time_ns()}"]
    for mod in (ef, email_service, auth):
        monkeypatch.setattr(mod, "db", b)
    monkeypatch.setenv("JWT_SECRET", JWT)
    for nom in VARIABLES:
        monkeypatch.delenv(nom, raising=False)
    for suffixe in SMTP_ENV:
        monkeypatch.delenv(f"SMTP_{suffixe}", raising=False)
        monkeypatch.delenv(f"PLATEFORME_SMTP_{suffixe}", raising=False)
    faux = FauxHttpx()
    monkeypatch.setattr(ef.httpx, "AsyncClient", faux.fabrique())
    smtp_envois = []

    def faux_smtp(cfg, to, sujet, html, texte, pieces=None):
        smtp_envois.append({"cfg": dict(cfg), "to": to, "sujet": sujet})
        return True
    monkeypatch.setattr(email_service, "_send_email_sync", faux_smtp)

    utilisateurs = {
        "super": {"id": "super", "email": SUPER, "role": "admin"},
        "adm2": {"id": "adm2", "email": "admin.client@isis.bf", "role": "admin"},
        "cli": {"id": "cli", "email": "client@x.bf", "role": "client"},
    }

    async def utilisateur_courant(request: Request):
        return utilisateurs[request.headers.get("x-test-user", "cli")]

    app = FastAPI()
    api = APIRouter(prefix="/api")
    api.include_router(rfe.router)
    app.include_router(api)
    app.dependency_overrides[auth.get_current_user] = utilisateur_courant

    class Env:
        pass
    e = Env()
    e.db, e.http, e.smtp, e.client = b, faux, smtp_envois, TestClient(app)
    boucle = asyncio.new_event_loop()
    e.run = boucle.run_until_complete
    yield e
    boucle.close()


SUP = {"x-test-user": "super"}


def cfg(four, **extra):
    base = {"fournisseur": four, "cle": "cle_test", "expediteur": "no-reply@sawali.test", "nom": "SAWALI"}
    base.update(extra)
    return base


def tout_le_contenu(env, nom):
    return json.dumps(env.run(env.db[nom].find({}).to_list(1000)), default=str)


# ===========================================================================
# 1. Forme exacte des appels : URL, en-têtes, JSON
# ===========================================================================
def test_resend_url_entetes_json(env):
    res = env.run(ef.envoyer_http(cfg("resend"), "dest@x.bf", "Sujet", "Corps", reply_to="rep@x.bf"))
    assert res["ok"] and res["id"] == "msg-1"
    a = env.http.appels[-1]
    assert a["url"] == "https://api.resend.com/emails"
    assert a["headers"] == {"Authorization": "Bearer cle_test"}
    assert a["json"] == {"from": "SAWALI <no-reply@sawali.test>", "to": ["dest@x.bf"], "subject": "Sujet",
                         "text": "Corps", "reply_to": "rep@x.bf"}
    assert env.http.timeout == 20.0
    # Sans nom ni reply-to : adresse seule, pas de clé reply_to
    env.run(ef.envoyer_http(cfg("resend", nom=""), "dest@x.bf", "S", "C"))
    assert env.http.appels[-1]["json"] == {"from": "no-reply@sawali.test", "to": ["dest@x.bf"], "subject": "S", "text": "C"}


def test_brevo_url_entetes_json(env):
    env.http.reponse = (201, {"messageId": "<abc@brevo>"})
    res = env.run(ef.envoyer_http(cfg("brevo"), "dest@x.bf", "Sujet", "Corps", reply_to="rep@x.bf"))
    assert res["id"] == "<abc@brevo>"
    a = env.http.appels[-1]
    assert a["url"] == "https://api.brevo.com/v3/smtp/email"
    assert a["headers"] == {"api-key": "cle_test", "accept": "application/json"}
    assert a["json"] == {"sender": {"name": "SAWALI", "email": "no-reply@sawali.test"}, "to": [{"email": "dest@x.bf"}],
                         "subject": "Sujet", "textContent": "Corps", "replyTo": {"email": "rep@x.bf"}}


@pytest.mark.parametrize("cle_collee", ["cle_test", "Zoho-enczapikey cle_test", "zoho-enczapikey   cle_test"])
def test_zeptomail_url_entetes_json_prefixe_non_double(env, cle_collee):
    env.http.reponse = (201, {"data": [], "request_id": "r-1"})
    env.run(ef.envoyer_http(cfg("zeptomail", cle=cle_collee, zeptomail_hote="api.zeptomail.eu"),
                            "dest@x.bf", "Sujet", "Corps", reply_to="rep@x.bf"))
    a = env.http.appels[-1]
    assert a["url"] == "https://api.zeptomail.eu/v1.1/email"
    assert a["headers"] == {"Authorization": "Zoho-enczapikey cle_test"}
    assert a["json"] == {"from": {"address": "no-reply@sawali.test", "name": "SAWALI"},
                         "to": [{"email_address": {"address": "dest@x.bf"}}], "subject": "Sujet",
                         "textbody": "Corps", "reply_to": [{"address": "rep@x.bf"}]}


def test_zeptomail_hote_par_defaut_et_html_et_pieces(env):
    env.http.reponse = (201, {"data": []})
    env.run(ef.envoyer_http(cfg("zeptomail", zeptomail_hote="inconnu"), "d@x.bf", "S", "T", html="<p>T</p>",
                            pieces=[{"filename": "a.txt", "content": b"abc", "mime_type": "text/plain"}]))
    a = env.http.appels[-1]
    assert a["url"] == "https://api.zeptomail.com/v1.1/email"
    assert a["json"]["htmlbody"] == "<p>T</p>"
    assert a["json"]["attachments"] == [{"name": "a.txt", "content": "YWJj", "mime_type": "text/plain"}]


# ===========================================================================
# 2. Erreurs du fournisseur remontées avec leur message (jamais la clé)
# ===========================================================================
def test_erreurs_des_fournisseurs(env):
    env.http.reponse = (422, {"name": "validation_error", "message": "The from domain is not verified"})
    with pytest.raises(ef.ErreurEnvoi) as e1:
        env.run(ef.envoyer_http(cfg("resend"), "d@x.bf", "S", "T"))
    assert str(e1.value) == "Resend 422 : The from domain is not verified"

    env.http.reponse = (401, {"code": "unauthorized", "message": "Key not found"})
    with pytest.raises(ef.ErreurEnvoi) as e2:
        env.run(ef.envoyer_http(cfg("brevo"), "d@x.bf", "S", "T"))
    assert str(e2.value) == "Brevo 401 : Key not found"

    env.http.reponse = (500, {"error": {"code": "TM_3201", "message": "Mandatory Field 'from' was not set",
                                        "details": [{"message": "Invalid sender"}]}})
    with pytest.raises(ef.ErreurEnvoi) as e3:
        env.run(ef.envoyer_http(cfg("zeptomail"), "d@x.bf", "S", "T"))
    assert str(e3.value) == "ZeptoMail 500 : Mandatory Field 'from' was not set (Invalid sender)"

    # Message long : tronqué à 250 caractères ; la clé n'apparaît jamais
    env.http.reponse = (400, {"message": "Clé cle_test refusée " + "x" * 400})
    with pytest.raises(ef.ErreurEnvoi) as e4:
        env.run(ef.envoyer_http(cfg("resend"), "d@x.bf", "S", "T"))
    assert len(str(e4.value)) == 250 and "cle_test" not in str(e4.value)

    env.http.exception = httpx.ConnectTimeout("délai")
    with pytest.raises(ef.ErreurEnvoi, match="Brevo : délai dépassé"):
        env.run(ef.envoyer_http(cfg("brevo"), "d@x.bf", "S", "T"))


def test_nom_affiche_nettoye(env):
    assert ef.nettoyer_nom("Pharma <Evil>\r\nBcc: x@y") == "Pharma Evil Bcc: x@y"
    assert len(ef.nettoyer_nom("A" * 100)) == 60
    env.run(ef.envoyer_http(cfg("resend", nom="<Nom>\nlong"), "d@x.bf", "S", "T"))
    assert env.http.appels[-1]["json"]["from"] == "Nom long <no-reply@sawali.test>"


# ===========================================================================
# 3. Écran du super-admin : clé jamais renvoyée, chiffrée en base, journal
# ===========================================================================
def test_reserve_au_super_admin(env):
    c = env.client
    assert c.get("/api/admin/email-fournisseur", headers={"x-test-user": "adm2"}).status_code == 403
    assert c.get("/api/admin/email-fournisseur", headers={"x-test-user": "cli"}).status_code == 403
    assert c.put("/api/admin/email-fournisseur", json={"fournisseur": "resend"}, headers={"x-test-user": "adm2"}).status_code == 403
    assert c.post("/api/admin/email-fournisseur/essai", json={}, headers={"x-test-user": "adm2"}).status_code == 403
    v = c.get("/api/admin/email-fournisseur", headers=SUP).json()
    # Rien de réglé : ancien comportement « smtp », aucun envoi possible, aides et avertissement présents
    assert v["fournisseur"] == "smtp" and v["effectif"]["fournisseur"] is None
    assert [x["valeur"] for x in v["choix"]] == ["resend", "zeptomail", "brevo", "smtp", "desactive"]
    assert "Starter" in v["avertissement_smtp"] and "3 000" in v["aides"]["resend"]["texte"]
    assert "300/jour" in v["aides"]["brevo"]["texte"] and "2,50 $" in v["aides"]["zeptomail"]["texte"]


def test_cle_jamais_renvoyee_et_chiffree_en_base(env):
    c = env.client
    r = c.put("/api/admin/email-fournisseur", headers=SUP, json={
        "fournisseur": "resend", "actif": True, "expediteur": "no-reply@sawali.test", "nom_affiche": "SAWALI <x>", "cle": CLE})
    assert r.status_code == 200, r.text
    assert CLE not in r.text
    d = r.json()
    assert d["fournisseur"] == "resend" and d["a_cle"] is True and d["cles"]["resend"] == {"a_cle": True}
    assert d["cles"]["brevo"] == {"a_cle": False} and d["nom_affiche"] == "SAWALI x"
    assert d["effectif"] == {"fournisseur": "resend", "source": "ecran", "raison": None, "expediteur": "no-reply@sawali.test"}
    g = c.get("/api/admin/email-fournisseur", headers=SUP)
    assert CLE not in g.text and g.json()["a_cle"] is True
    # En base : chiffrée (jamais en clair), déchiffrable par le serveur
    brut = tout_le_contenu(env, ef.REGLAGES) + tout_le_contenu(env, ef.JOURNAL_REGLAGES) + tout_le_contenu(env, "settings")
    assert CLE not in brut
    doc = env.run(env.db[ef.REGLAGES].find_one({"_id": "plateforme"}))
    assert ef.dechiffrer(doc["cle_resend_chiffree"]) == CLE
    # Champ secret vide = conservé
    c.put("/api/admin/email-fournisseur", headers=SUP, json={"fournisseur": "resend", "cle": "", "nom_affiche": "SAWALI"})
    doc2 = env.run(env.db[ef.REGLAGES].find_one({"_id": "plateforme"}))
    assert ef.dechiffrer(doc2["cle_resend_chiffree"]) == CLE
    # Journal : qui, quand, quel fournisseur, quels champs ; jamais la clé
    j = c.get("/api/admin/email-fournisseur/journal", headers=SUP)
    assert CLE not in j.text
    modifs = j.json()["modifications"]
    assert modifs[-1]["par"]["email"] == SUPER and modifs[-1]["fournisseur"] == "resend"
    assert "cle_resend" in modifs[-1]["champs"] and modifs[-1]["le"]
    assert modifs[0]["champs"] == ["nom_affiche"]


def test_valeurs_refusees(env):
    c = env.client
    assert c.put("/api/admin/email-fournisseur", headers=SUP, json={"fournisseur": "mailgun"}).status_code == 400
    assert c.put("/api/admin/email-fournisseur", headers=SUP, json={"expediteur": "pas-une-adresse"}).status_code == 400
    assert c.put("/api/admin/email-fournisseur", headers=SUP, json={"fournisseur": "zeptomail", "zeptomail_hote": "api.zeptomail.us"}).status_code == 400
    assert c.put("/api/admin/email-fournisseur", headers=SUP, json={"fournisseur": "smtp", "cle": "cle_test"}).status_code == 400


def test_essai_utilise_les_reglages_enregistres_et_affiche_l_erreur(env):
    c = env.client
    c.put("/api/admin/email-fournisseur", headers=SUP, json={
        "fournisseur": "brevo", "expediteur": "no-reply@sawali.test", "nom_affiche": "SAWALI", "cle": "cle_test_brevo"})
    env.http.reponse = (201, {"messageId": "m-1"})
    r = c.post("/api/admin/email-fournisseur/essai", headers=SUP, json={"destinataire": "moi@x.bf"}).json()
    assert r["ok"] and r["fournisseur"] == "brevo" and r["destinataire"] == "moi@x.bf"
    assert env.http.appels[-1]["headers"]["api-key"] == "cle_test_brevo"
    # Destinataire par défaut : le super-admin ; erreur du fournisseur affichée
    env.http.reponse = (400, {"code": "invalid_parameter", "message": "sender is not valid"})
    r = c.post("/api/admin/email-fournisseur/essai", headers=SUP, json={})
    assert r.json() == {"ok": False, "fournisseur": "brevo", "source": "ecran", "destinataire": SUPER,
                        "erreur": "Brevo 400 : sender is not valid"}
    assert "cle_test_brevo" not in r.text
    envois = c.get("/api/admin/email-fournisseur/journal", headers=SUP).json()["envois"]
    assert [e["statut"] for e in envois] == ["ECHEC", "ENVOYE"]
    assert envois[0]["erreur"] == "Brevo 400 : sender is not valid"


# ===========================================================================
# 4. send_email : signature inchangée, journal ENVOYE / ECHEC / NON_CONFIGURE
# ===========================================================================
def test_send_email_par_le_fournisseur_choisi(env):
    env.run(ef.enregistrer({"fournisseur": "zeptomail", "expediteur": "no-reply@sawali.test", "nom_affiche": "SAWALI",
                            "cle": "Zoho-enczapikey cle_test_zepto", "zeptomail_hote": "api.zeptomail.in"},
                           {"id": "super", "email": SUPER}))
    env.http.reponse = (201, {"data": []})
    ok = env.run(email_service.send_email("dest@x.bf", "Code 123456", "<p>Votre code : <b>123456</b></p>"))
    assert ok is True
    a = env.http.appels[-1]
    assert a["url"] == "https://api.zeptomail.in/v1.1/email"
    assert a["headers"]["Authorization"] == "Zoho-enczapikey cle_test_zepto"
    assert a["json"]["textbody"] == "Votre code : 123456" and a["json"]["htmlbody"].startswith("<p>")
    # Pièce jointe (rapports, sauvegardes) : transmise en base 64
    env.run(email_service.send_email("dest@x.bf", "Rapport", "<p>R</p>", "R",
                                     attachment={"filename": "r.pdf", "content": b"%PDF", "mime_type": "application/pdf"}))
    assert env.http.appels[-1]["json"]["attachments"][0]["name"] == "r.pdf"
    # Échec : False, jamais d'exception
    env.http.reponse = (401, {"error": {"message": "Invalid API Token found"}})
    assert env.run(email_service.send_email("dest@x.bf", "Code", "<p>x</p>", "x")) is False
    statuts = [e["statut"] for e in env.run(env.db[ef.JOURNAL_ENVOIS].find({}).sort("le", 1).to_list(10))]
    assert statuts == ["ENVOYE", "ENVOYE", "ECHEC"]


def test_send_email_desactive_ou_non_configure(env, monkeypatch):
    assert env.run(email_service.send_email("d@x.bf", "S", "<p>x</p>")) is False
    # « Désactivé » dans l'écran : pas de repli sur les variables d'environnement
    env.run(ef.enregistrer({"fournisseur": "desactive"}, {"id": "super", "email": SUPER}))
    monkeypatch.setenv("RESEND_API_KEY", "cle_test")
    monkeypatch.setenv("RESEND_EXPEDITEUR", "no-reply@sawali.test")
    assert env.run(email_service.send_email("d@x.bf", "S", "<p>x</p>")) is False
    assert env.http.appels == []
    journal = env.run(env.db[ef.JOURNAL_ENVOIS].find({}).to_list(10))
    assert {e["statut"] for e in journal} == {"NON_CONFIGURE"}
    # Interrupteur « actif » coupé : aucun envoi non plus
    env.run(ef.enregistrer({"fournisseur": "resend", "actif": False, "expediteur": "a@sawali.test", "cle": "cle_test"},
                           {"id": "super", "email": SUPER}))
    assert env.run(email_service.send_email("d@x.bf", "S", "<p>x</p>")) is False and env.http.appels == []


# ===========================================================================
# 5. Compatibilité : anciens réglages SMTP et repli sur les variables d'environnement
# ===========================================================================
def _ancien_smtp(env, mdp="mdp_test_smtp"):
    env.run(env.db.settings.insert_one({"_id": "global", "smtp_host": "smtp.exemple.test", "smtp_port": 587,
                                        "smtp_user": "u@exemple.test", "smtp_password": mdp,
                                        "smtp_from_email": "no-reply@exemple.test", "smtp_from_name": "SAWALI",
                                        "smtp_use_tls": True}))


def test_anciens_reglages_smtp_restent_valables_puis_mot_de_passe_chiffre(env):
    _ancien_smtp(env)
    eff = env.run(ef.configuration_effective())
    assert eff["fournisseur"] == "smtp" and eff["source"] == "ancien_smtp" and eff["password"] == "mdp_test_smtp"
    assert env.run(email_service.send_email("d@x.bf", "Code", "<p>1</p>", "1")) is True
    envoi = env.smtp[-1]
    assert envoi["cfg"]["host"] == "smtp.exemple.test" and envoi["cfg"]["from_email"] == "no-reply@exemple.test"
    assert env.http.appels == []
    # Migration au démarrage : chiffré, plus jamais en clair ; l'envoi continue
    assert env.run(ef.migrer_ancien_mot_de_passe_smtp()) is True
    assert "mdp_test_smtp" not in tout_le_contenu(env, "settings") + tout_le_contenu(env, ef.REGLAGES)
    assert env.run(ef.configuration_effective())["password"] == "mdp_test_smtp"
    assert env.run(email_service.send_email("d@x.bf", "Code", "<p>1</p>", "1")) is True
    v = env.client.get("/api/admin/email-fournisseur", headers=SUP)
    assert "mdp_test_smtp" not in v.text
    assert v.json()["fournisseur"] == "smtp" and v.json()["smtp"]["a_mot_de_passe"] is True
    assert v.json()["smtp"]["hote"] == "smtp.exemple.test"


def test_ecran_smtp_mot_de_passe_chiffre_et_avertissement(env):
    c = env.client
    r = c.put("/api/admin/email-fournisseur", headers=SUP, json={
        "fournisseur": "smtp", "expediteur": "no-reply@sawali.test", "nom_affiche": "SAWALI",
        "smtp": {"hote": "smtp.sawali.test", "port": 465, "utilisateur": "u", "mot_de_passe": "mdp_test", "starttls": False}})
    assert r.status_code == 200 and "mdp_test" not in r.text
    assert "Render" in r.json()["avertissement_smtp"]
    assert "mdp_test" not in tout_le_contenu(env, "settings") + tout_le_contenu(env, ef.REGLAGES)
    g = env.run(env.db.settings.find_one({"_id": "global"}))
    assert g["smtp_host"] == "smtp.sawali.test" and g["smtp_port"] == 465 and g["smtp_use_tls"] is False
    assert g["smtp_from_email"] == "no-reply@sawali.test"
    assert env.run(email_service.send_email("d@x.bf", "S", "<p>x</p>")) is True
    assert env.smtp[-1]["cfg"]["password"] == "mdp_test" and env.smtp[-1]["cfg"]["use_tls"] is False


def test_repli_sur_les_variables_d_environnement(env, monkeypatch):
    # 1. Resend (adLyn) prioritaire
    monkeypatch.setenv("RESEND_API_KEY", "cle_test_env")
    monkeypatch.setenv("RESEND_EXPEDITEUR", "SAWALI <no-reply@sawali.test>")
    monkeypatch.setenv("SMTP_HOST", "smtp.env.test")
    monkeypatch.setenv("SMTP_USER", "u@env.test")
    monkeypatch.setenv("SMTP_PASSWORD", "mdp_env")
    eff = env.run(ef.configuration_effective())
    assert (eff["fournisseur"], eff["source"], eff["expediteur"], eff["nom"]) == ("resend", "env:RESEND_API_KEY", "no-reply@sawali.test", "SAWALI")
    assert env.run(email_service.send_email("d@x.bf", "S", "<p>x</p>")) is True
    assert env.http.appels[-1]["headers"] == {"Authorization": "Bearer cle_test_env"}
    # 2. Puis PLATEFORME_SMTP_* / SMTP_*
    monkeypatch.delenv("RESEND_API_KEY")
    eff = env.run(ef.configuration_effective())
    assert (eff["fournisseur"], eff["source"], eff["host"], eff["from_email"]) == ("smtp", "env:SMTP", "smtp.env.test", "u@env.test")
    monkeypatch.setenv("PLATEFORME_SMTP_HOST", "smtp.plateforme.test")
    assert env.run(ef.configuration_effective())["host"] == "smtp.plateforme.test"
    # 3. Brevo puis ZeptoMail (en option) avec EMAIL_EXPEDITEUR
    for nom in ("SMTP_HOST", "PLATEFORME_SMTP_HOST"):
        monkeypatch.delenv(nom)
    monkeypatch.setenv("EMAIL_EXPEDITEUR", "no-reply@sawali.test")
    monkeypatch.setenv("ZEPTOMAIL_API_KEY", "cle_test_zepto")
    monkeypatch.setenv("ZEPTOMAIL_HOTE", "api.zeptomail.eu")
    monkeypatch.setenv("BREVO_API_KEY", "cle_test_brevo")
    assert env.run(ef.configuration_effective())["fournisseur"] == "brevo"
    monkeypatch.delenv("BREVO_API_KEY")
    eff = env.run(ef.configuration_effective())
    assert (eff["fournisseur"], eff["zeptomail_hote"]) == ("zeptomail", "api.zeptomail.eu")
    # 4. Un réglage d'écran l'emporte sur les variables d'environnement
    _ancien_smtp(env)
    assert env.run(ef.configuration_effective())["source"] == "ancien_smtp"
    # Aucune valeur de variable dans la vue (noms seulement)
    v = env.client.get("/api/admin/email-fournisseur", headers=SUP)
    assert "cle_test_zepto" not in v.text and v.json()["env_repli"]["ZEPTOMAIL_API_KEY"] is True


def test_cle_d_ecran_absente_reprend_la_cle_d_environnement(env, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "cle_test_env")
    env.run(ef.enregistrer({"fournisseur": "resend", "expediteur": "no-reply@sawali.test"}, {"id": "super", "email": SUPER}))
    eff = env.run(ef.configuration_effective())
    assert eff["fournisseur"] == "resend" and eff["cle"] == "cle_test_env" and eff["source"] == "ecran"


def test_parametres_generiques_smtp_reserves_au_super_admin(env):
    _ancien_smtp(env, mdp="ancien")

    def est_super(u):
        return u.get("email") == SUPER
    # Admin d'un client : champs smtp_* ignorés
    reste = env.run(ef.filtrer_maj_parametres_generiques(
        {"smtp_host": "pirate.test", "smtp_password": "x", "site_name": "A"}, {"id": "adm2", "email": "a@b.bf"}, est_super))
    assert reste == {"site_name": "A"}
    # Super-admin : mot de passe chiffré, jamais en clair, champ retiré de la mise à jour générale
    reste = env.run(ef.filtrer_maj_parametres_generiques(
        {"smtp_from_name": "Nom", "smtp_password": "nouveau_mdp"}, {"id": "super", "email": SUPER}, est_super))
    assert reste == {"smtp_from_name": "Nom"}
    assert "nouveau_mdp" not in tout_le_contenu(env, "settings") + tout_le_contenu(env, ef.REGLAGES)
    assert env.run(ef.configuration_effective())["password"] == "nouveau_mdp"
    p09 = (RACINE / "server_parts" / "p09_supervision_parametres.py").read_text(encoding="utf-8")
    assert "_email_fournisseurs.filtrer_maj_parametres_generiques(update, user, _is_super_admin)" in p09


def test_cle_illisible_si_jwt_secret_change(env, monkeypatch):
    env.run(ef.enregistrer({"fournisseur": "brevo", "expediteur": "no-reply@sawali.test", "cle": "cle_test"},
                           {"id": "super", "email": SUPER}))
    monkeypatch.setenv("JWT_SECRET", "un-autre-secret-0123456789")
    eff = env.run(ef.configuration_effective())
    assert eff["fournisseur"] is None and "Clé API Brevo absente" in eff["raison"]


# ===========================================================================
# 6. Branchements : server.py, signature de send_email, écran Paramètres
# ===========================================================================
def test_branchements_et_signature():
    import inspect
    params = list(inspect.signature(email_service.send_email).parameters)
    assert params == ["to_email", "subject", "html_body", "text_body", "attachment", "attachments", "timeout_s"]
    serveur = (RACINE / "server.py").read_text(encoding="utf-8")
    assert "api.include_router(_email_fournisseur_router)" in serveur
    assert "_email_fournisseurs.migrer_ancien_mot_de_passe_smtp()" in serveur
    req = (RACINE / "requirements.txt").read_text(encoding="utf-8")
    assert "httpx==" in req
    front = RACINE.parent / "frontend" / "src" / "pages" / "admin"
    assert "<EmailFournisseurSection />" in (front / "AdminSettings.jsx").read_text(encoding="utf-8")
    section = (front / "sections" / "EmailFournisseurSection.jsx").read_text(encoding="utf-8")
    assert "/admin/email-fournisseur/essai" in section and "avertissement_smtp" in section
