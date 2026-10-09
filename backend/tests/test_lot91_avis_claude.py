"""Lot 91 — avis de Claude sur les demandes de fonctionnalités reçues au support (Liluvine fait patienter, transmet,
rend la réponse ; le propriétaire décide des demandes approuvées) + liste déroulante du chat réduite aux applis.
Lancer : cd backend && python -m pytest tests/test_lot91_avis_claude.py -q
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "test_lot91")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.avis_claude as ac  # noqa: E402
import routes.internal_chat as ic  # noqa: E402

ADMIN = {"id": "adm1", "role": "admin", "full_name": "Jean-François", "email": "admin@sawali.test", "account_status": "active"}
CLIENT = {"id": "cli1", "role": "client", "company": "Pharmacie X", "account_status": "active",
          "features": {"internal_chat": True}}
SECRET = "secret-de-ster"
H_ADMIN = {"X-User": "adm1"}
UTILISATEUR = {"id": "u-42", "nom": "Awa Traoré", "role": "dentiste", "contexte": "Cabinet du Centre"}


def signe(corps: dict) -> tuple:
    """Corps JSON + en-têtes signés comme le fait la plateforme."""
    brut = json.dumps(corps)
    ts = str(int(time.time()))
    sig = hmac.new(SECRET.encode(), f"{ts}.{brut}".encode(), hashlib.sha256).hexdigest()
    return brut, {"X-Emetteur": "ster", "X-Timestamp": ts, "X-Signature": sig, "Content-Type": "application/json"}


def poster(c, chemin, corps):
    brut, h = signe(corps)
    return c.post(chemin, content=brut, headers=h)


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("LOOIS_SUPPORT_CLE", "cle-de-test")
    monkeypatch.delenv("LOOIS_SUPPORT_ADMIN_EMAIL", raising=False)
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot91"]
    utilisateurs = {"adm1": ADMIN, "cli1": CLIENT}
    appels = {"classement": 0, "analyse": [], "emails": []}

    # Modèles et e-mail factices : aucun appel réseau
    async def faux_classement(systeme, texte, modele, max_tokens=400):
        appels["classement"] += 1
        return json.dumps({"fonctionnelle": "ajout" in texte.lower() or "module" in texte.lower(), "resume": "Ajout d'un module"})

    async def fausse_analyse(systeme, texte, modele, depot):
        appels["analyse"].append({"texte": texte, "depot": depot})
        verdict = "approuve" if "Précisions" in texte or "rappel" in texte else "a_preciser"
        return ("J'ai lu le code.\n<avis>" + json.dumps({
            "verdict": verdict, "complexite": "moyenne", "duree_estimee": "1 à 2 jours", "resume": "Rappels SMS",
            "analyse_technique": "routes/rdv.py", "questions": ["Par SMS ou WhatsApp ?"],
            "reponse_client": "C'est faisable : le responsable va décider." if verdict == "approuve"
            else "Pouvez-vous préciser : par SMS ou WhatsApp ?"}) + "</avis>")

    async def faux_email(to, sujet, html, *a, **k):
        appels["emails"].append({"to": to, "sujet": sujet})
        return True

    monkeypatch.setattr(ac, "appeler_texte", faux_classement)
    monkeypatch.setattr(ac, "appeler_analyse", fausse_analyse)
    monkeypatch.setattr(ac, "cle_ia_presente", lambda: True)
    import email_service
    monkeypatch.setattr(email_service, "send_email", faux_email)

    async def get_user(request: Request):
        u = utilisateurs.get(request.headers.get("X-User", ""))
        if not u:
            raise HTTPException(status_code=401)
        return u

    api = APIRouter(prefix="/api")
    api.include_router(ic.make_router(db=db, get_current_user=get_user, decode_token=lambda t: {}))
    app = FastAPI()
    app.include_router(api)
    with TestClient(app) as client:
        client.portal.call(db.users.insert_many, [dict(ADMIN), dict(CLIENT)])
        client.portal.call(db.liluvine_emetteurs.insert_one,
                           {"code": "ster", "nom": "sTer", "secret": SECRET, "actif": True, "support_actif": True})
        yield client, db, appels


def attendre(fonction, essais=80):
    """Attend qu'une condition soit vraie (tâches de fond de l'analyse)."""
    for _ in range(essais):
        v = fonction()
        if v:
            return v
        time.sleep(0.05)
    return fonction()


def fil(c):
    return poster(c, "/api/support-plateforme/fil", {"utilisateur": UTILISATEUR}).json()["messages"]


def test_filtre_mots_cles():
    """Le filtre sans IA retient les demandes de fonctionnalités, pas les salutations."""
    assert ac.semble_demande_fonctionnelle("Pouvez-vous ajouter un module de rappel des rendez-vous ?")
    assert ac.semble_demande_fonctionnelle("Il y a un bug sur l'écran des factures")
    assert not ac.semble_demande_fonctionnelle("Bonjour, merci beaucoup")
    assert not ac.semble_demande_fonctionnelle("ok")


def test_normaliser_avis():
    """Verdict inconnu → « à préciser » ; réponse client toujours présente."""
    a = ac.normaliser_avis('<avis>{"verdict": "peut-etre", "questions": ["Quel écran ?"]}</avis>')
    assert a["verdict"] == "a_preciser" and "Quel écran ?" in a["reponse_client"]
    assert ac.normaliser_avis("pas de json")["verdict"] == "a_preciser"


def test_demande_approuvee_plateforme(env):
    """Demande de module : Liluvine fait patienter, Claude lit le dépôt de sTer, réponse au client, propriétaire prévenu."""
    c, db, appels = env
    assert poster(c, "/api/support-plateforme/messages",
                  {"utilisateur": UTILISATEUR, "texte": "Pouvez-vous ajouter un module de rappel des rendez-vous ?"}).status_code == 200
    msgs = attendre(lambda: (m := fil(c)) and len([x for x in m if x["auteur"] == ac.LILUVINE_NOM]) >= 2 and m)
    liluvine = [m["texte"] for m in msgs if m["auteur"] == ac.LILUVINE_NOM]
    assert "Patientez" in liluvine[0] and "faisable" in liluvine[1]
    assert appels["analyse"][0]["depot"] == "ShuyahBF/dentalcare"
    assert attendre(lambda: appels["emails"]) and "DEM-" in appels["emails"][0]["sujet"]
    r = c.get("/api/admin/avis-claude", headers=H_ADMIN).json()
    assert r["a_decider"] == 1 and r["cle_ia"] is True
    d = r["demandes"][0]
    assert d["statut"] == "a_decider" and d["avis"]["duree_estimee"] == "1 à 2 jours"
    # Décision du propriétaire : message transmis au client par Liluvine
    assert c.post(f"/api/admin/avis-claude/demandes/{d['id']}/decision", headers={"X-User": "cli1"},
                  json={"decision": "acceptee"}).status_code == 403
    v = c.post(f"/api/admin/avis-claude/demandes/{d['id']}/decision", headers=H_ADMIN,
               json={"decision": "acceptee", "message_client": "Bonne nouvelle : votre demande est acceptée."}).json()
    assert v["statut"] == "acceptee"
    assert any("acceptée" in m["texte"] for m in fil(c))


def test_message_ordinaire_ignore(env):
    """Une simple question n'appelle ni le classement ni l'analyse."""
    c, db, appels = env
    poster(c, "/api/support-plateforme/messages", {"utilisateur": UTILISATEUR, "texte": "Bonjour, merci"})
    time.sleep(0.2)
    assert appels["classement"] == 0 and not appels["analyse"]
    assert not [m for m in fil(c) if m["auteur"] == ac.LILUVINE_NOM]


def test_a_preciser_puis_complement(env):
    """« À préciser » : Liluvine pose la question ; la réponse du client relance l'analyse avec les précisions."""
    c, db, appels = env
    poster(c, "/api/support-plateforme/messages",
           {"utilisateur": UTILISATEUR, "texte": "Il faudrait ajouter des notifications aux patients"})
    attendre(lambda: len(appels["analyse"]) >= 1 and
             c.get("/api/admin/avis-claude", headers=H_ADMIN).json()["demandes"][0]["statut"] == "a_preciser")
    poster(c, "/api/support-plateforme/messages", {"utilisateur": UTILISATEUR, "texte": "Par WhatsApp de préférence svp"})
    attendre(lambda: len(appels["analyse"]) >= 2)
    assert "Précisions du client : Par WhatsApp" in appels["analyse"][1]["texte"]
    r = attendre(lambda: (x := c.get("/api/admin/avis-claude", headers=H_ADMIN).json())["a_decider"] == 1 and x)
    assert len(r["demandes"]) == 1


def test_reglages_admin(env):
    """Réglages : dépôt invalide refusé, jeton jamais renvoyé."""
    c, db, _ = env
    assert c.put("/api/admin/avis-claude/reglages", headers=H_ADMIN, json={"depots": {"ster": "pas un depot"}}).status_code == 422
    r = c.put("/api/admin/avis-claude/reglages", headers=H_ADMIN, json={"depots": {"sTer": "ShuyahBF/autre"}, "actif": True}).json()
    assert r["depots"]["ster"] == "ShuyahBF/autre"
    assert "token" not in json.dumps(c.get("/api/admin/avis-claude", headers=H_ADMIN).json()).lower().replace("jeton_github", "")


def test_liste_deroulante_applis_seulement(env):
    """Administrateur : seulement les applis (Support Loois, sTer - Support), plus les clients / tenants."""
    c, db, _ = env
    ids = [e["id"] for e in c.get("/api/me/chat/clients", headers=H_ADMIN).json()]
    assert "support-plat-ster" in ids and "cli1" not in ids
    # Aucune appli active : les clients restent proposés (le chat ne disparaît pas)
    c.portal.call(db.liluvine_emetteurs.update_one, {"code": "ster"}, {"$set": {"support_actif": False}})
    os.environ.pop("LOOIS_SUPPORT_CLE", None)
    ids = [e["id"] for e in c.get("/api/me/chat/clients", headers=H_ADMIN).json()]
    assert "cli1" in ids


def test_boucle_outils_github(monkeypatch):
    """Claude appelle un outil (lecture du dépôt) puis conclut : le résultat de l'outil lui est bien renvoyé."""
    import asyncio
    import types
    import anthropic

    vus = []

    class FauxMessages:
        def __init__(self):
            self.tour = 0

        async def create(self, **params):
            vus.append(params)
            self.tour += 1
            if self.tour == 1:
                return types.SimpleNamespace(content=[
                    types.SimpleNamespace(type="text", text="Je regarde."),
                    types.SimpleNamespace(type="tool_use", id="t1", name="lister_fichiers", input={"chemin": ""})])
            return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text='<avis>{"verdict": "approuve"}</avis>')])

    class FauxClient:
        def __init__(self, **k):
            self.messages = FauxMessages()

    async def faux_outil(depot, nom, entree):
        return f"📄 README.md ({depot}, {nom})"

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FauxClient)
    monkeypatch.setattr(ac, "executer_outil", faux_outil)
    sortie = asyncio.run(ac.appeler_analyse("sys", "demande", "modele", "ShuyahBF/dentalcare"))
    assert ac.normaliser_avis(sortie)["verdict"] == "approuve"
    retour = vus[1]["messages"][-1]["content"][0]
    assert retour["type"] == "tool_result" and "README.md" in retour["content"]
    assert vus[1]["messages"][1]["content"][1] == {"type": "tool_use", "id": "t1", "name": "lister_fichiers", "input": {"chemin": ""}}
