"""Lots 166-167 — envoi en un clic du modèle de demande d'accord (lien personnel par contact) : garde-fous (modèle approuvé,
jamais à ceux qui ont accepté ou refusé, pas deux fois en 7 jours), composants envoyés (prénom, jeton signé, bouton NON).
Envoi WhatsApp et Meta simulés, MongoDB simulé. Lancer : cd backend && python -m pytest tests/test_lot166_envoi_modele_accord.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.accord_modele_meta as amm  # noqa: E402
import routes.accord_page as ap  # noqa: E402
import routes.carrousel_whatsapp as cw  # noqa: E402
from test_carrousel_whatsapp import BASE, USERS, h  # noqa: E402


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "secret-de-test")
    statut = {"valeur": "APPROVED"}

    async def faux_statut(**kw):
        return {"statut": statut["valeur"], "motif": None, "erreur": None}
    monkeypatch.setattr(amm, "lire_statut", faux_statut)

    db = mongomock_motor.AsyncMongoMockClient()["sawali_l166"]
    envois = []

    async def get_admin(request: Request):
        u = USERS.get(request.headers.get("X-User", ""))
        if not u or u["role"] != "admin":
            raise HTTPException(status_code=403)
        return u

    async def get_user(request: Request):
        return await get_admin(request)

    async def envoyer(to, nom, langue, comps, tenant_id=None):
        envois.append({"to": to, "modele": nom, "langue": langue, "composants": comps})
        return {"ok": True, "status": 200, "message_id": f"wamid.{len(envois)}", "error": None}

    async def creds(tenant_id):
        return {"access_token": "t", "phone_number_id": "1", "waba_id": "W", "source": "global", "tenant_id": None}

    async def active(user, cle):
        return True

    async def visibles(user):
        return [user["id"]]

    api = APIRouter(prefix="/api")
    moteur = cw.attach_carrousel_whatsapp_routes(
        api=api, db=db, get_current_user=get_user, get_current_admin=get_admin, fonction_active=active,
        visible_client_ids=visibles, wa_send_template=envoyer, resolve_wa_credentials=creds, base_publique=lambda: BASE)
    app = FastAPI()
    app.include_router(api)
    client = TestClient(app).__enter__()
    client.moteur = moteur                       # lot 167 : planificateur des demandes programmées
    client.portal.call(db.users.insert_many, [dict(u) for u in USERS.values()])
    yield client, db, envois, statut
    client.__exit__(None, None, None)


URL = "/api/admin/whatsapp/carrousel/demande-accord-modele"


def enregistrer_modele(client, db):
    client.portal.call(db.settings.replace_one, {"_id": "global"}, {"_id": "global", "wa_accord_modele": "sawali_accord_lien",
                                                                     "wa_accord_modele_langue": "fr"}, True)   # True = upsert


def test_refuse_sans_modele_ou_non_approuve(env):
    client, db, envois, statut = env
    r = client.post(URL, headers=h("admin"), json={"ids": ["cli_a"]})
    assert r.status_code == 409 and "Créez d'abord" in r.json()["detail"]
    enregistrer_modele(client, db)
    statut["valeur"] = "PENDING"
    r = client.post(URL, headers=h("admin"), json={"ids": ["cli_a"]})
    assert r.status_code == 409 and "pas encore approuvé" in r.json()["detail"] and envois == []


def test_envoi_avec_lien_personnel_et_bouton_non(env):
    client, db, envois, _ = env
    enregistrer_modele(client, db)
    r = client.post(URL, headers=h("admin"), json={"ids": ["cli_a", "cli_b"]})
    assert r.status_code == 200, r.text
    assert r.json()["envoyees"] == 2 and r.json()["nb_echecs"] == 0
    e = next(x for x in envois if "".join(c for c in x["to"] if c.isdigit()).endswith("0001"))
    assert e["modele"] == "sawali_accord_lien" and e["langue"] == "fr"
    corps, oui, non = e["composants"]
    assert corps["parameters"] == [{"type": "text", "text": "Pharmacie"}]                        # UNE variable : le prénom
    assert ap.lire_jeton(oui["parameters"][0]["text"]) == "cli_a"                                # SON lien personnel (jeton signé)
    assert non["sub_type"] == "quick_reply" and non["parameters"][0]["payload"] == amm.PAYLOAD_NON
    assert client.portal.call(db.users.find_one, {"id": "cli_a"})["accord_demande_le"]           # demande datée


def test_garde_fous_accepte_refuse_recent(env):
    client, db, envois, _ = env
    enregistrer_modele(client, db)
    client.portal.call(db.users.update_one, {"id": "cli_b"}, {"$set": {"accepte_whatsapp": False}})   # a refusé : jamais sollicité
    r = client.post(URL, headers=h("admin"), json={"ids": ["cli_a", "cli_b"]}).json()
    assert r["envoyees"] == 1 and r["ignores"]["refus"] == 1
    # Deuxième clic : cli_a vient d'être sollicité (moins de 7 jours)
    r = client.post(URL, headers=h("admin"), json={"ids": ["cli_a", "cli_b"]}).json()
    assert r["envoyees"] == 0 and r["ignores"]["demande_recente"] == 1 and r["ignores"]["refus"] == 1
    # Une personne qui a déjà accepté n'est jamais sollicitée
    client.portal.call(db.users.update_one, {"id": "cli_a"}, {"$set": {"accepte_whatsapp": True, "accord_demande_le": None}})
    r = client.post(URL, headers=h("admin"), json={"ids": ["cli_a"]}).json()
    assert r["envoyees"] == 0 and r["ignores"]["deja_accepte"] == 1 and len(envois) == 1


def test_reserve_a_l_administration_et_plafonnee(env):
    client, _, _, _ = env
    assert client.post(URL, headers=h("cli_a"), json={"ids": ["cli_a"]}).status_code == 403
    assert client.post(URL, headers=h("admin"), json={"ids": [f"x{i}" for i in range(cw.DESTINATAIRES_MAX + 1)]}).status_code in (400, 422)   # plafond du modèle de requête


# --- Lot 167 : demande d'accord PROGRAMMÉE (« demain 8 h 30 ») ----------------------------------------------------
from datetime import datetime, timedelta, timezone  # noqa: E402


def quand(dans: timedelta) -> str:
    """« AAAA-MM-JJTHH:MM » en heure de Ouagadougou (UTC+0), comme le champ datetime-local du site."""
    return (datetime.now(timezone.utc) + dans).strftime("%Y-%m-%dT%H:%M")


def rendre_echue(client, db):
    """Simule l'arrivée de l'heure : la date programmée passe dans le passé (la saisie d'une date passée est refusée)."""
    doc = client.portal.call(db.settings.find_one, {"_id": "accord_programmations"})
    for it in doc["items"]:
        it["programme_le"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    client.portal.call(db.settings.replace_one, {"_id": "accord_programmations"}, doc)


def test_programmation_future_puis_envoi_a_l_heure(env):
    client, db, envois, _ = env
    enregistrer_modele(client, db)
    r = client.post(URL, headers=h("admin"), json={"ids": ["cli_a", "cli_b"], "programme_le": quand(timedelta(hours=9))})
    assert r.status_code == 200, r.text
    assert r.json()["programmee"] is True and r.json()["statut"] == "PROGRAMMEE" and r.json()["nb"] == 2
    assert "ids" not in r.json() and envois == []                                    # rien ne part avant l'heure
    liste = client.get(URL + "/programmations", headers=h("admin")).json()["programmations"]
    assert len(liste) == 1 and liste[0]["statut"] == "PROGRAMMEE"
    assert client.portal.call(client.moteur["accords_echus"]) == 0                   # l'heure n'est pas venue
    rendre_echue(client, db)
    assert client.portal.call(client.moteur["accords_echus"]) == 1
    assert len(envois) == 2                                                          # une demande par personne, avec son lien
    fin = client.get(URL + "/programmations", headers=h("admin")).json()["programmations"][0]
    assert fin["statut"] == "TERMINEE" and fin["resultat"]["envoyees"] == 2
    assert client.portal.call(client.moteur["accords_echus"]) == 0                   # jamais renvoyée


def test_date_passee_refusee_et_modele_obligatoire(env):
    client, db, envois, _ = env
    r = client.post(URL, headers=h("admin"), json={"ids": ["cli_a"], "programme_le": quand(timedelta(hours=1))})
    assert r.status_code == 409 and "Créez d'abord" in r.json()["detail"]            # pas de modèle : refus tout de suite
    enregistrer_modele(client, db)
    r = client.post(URL, headers=h("admin"), json={"ids": ["cli_a"], "programme_le": quand(-timedelta(days=1))})
    assert r.status_code == 400 and envois == []


def test_annulation_avant_l_heure(env):
    client, db, envois, _ = env
    enregistrer_modele(client, db)
    pid = client.post(URL, headers=h("admin"), json={"ids": ["cli_a"], "programme_le": quand(timedelta(hours=2))}).json()["id"]
    assert client.post(f"{URL}/programmations/{pid}/annuler", headers=h("admin")).json()["statut"] == "ANNULEE"
    rendre_echue(client, db)
    assert client.portal.call(client.moteur["accords_echus"]) == 0 and envois == []
    assert client.post(f"{URL}/programmations/{pid}/annuler", headers=h("admin")).status_code == 409   # déjà annulée


def test_modele_plus_approuve_a_l_heure_dite_rien_n_est_envoye(env):
    client, db, envois, statut = env
    enregistrer_modele(client, db)
    client.post(URL, headers=h("admin"), json={"ids": ["cli_a"], "programme_le": quand(timedelta(hours=2))})
    statut["valeur"] = "REJECTED"                                                    # Meta change d'avis entre-temps
    rendre_echue(client, db)
    assert client.portal.call(client.moteur["accords_echus"]) == 1
    fin = client.get(URL + "/programmations", headers=h("admin")).json()["programmations"][0]
    assert fin["statut"] == "ECHEC" and "approuvé" in fin["motif"] and envois == []
