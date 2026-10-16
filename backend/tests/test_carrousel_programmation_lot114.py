"""Lot 114 — carrousels WhatsApp PROGRAMMÉS et soumis aux PLAGES HORAIRES d'envoi (portail et administration,
carrousels sponsorisés de la régie compris).

Vérifie :
  - programmation future → PROGRAMMEE, puis démarrage par le planificateur quand l'heure est arrivée ;
  - hors plage horaire → EN_ATTENTE avec la date de reprise, puis envoi à l'ouverture ;
  - reprise après une coupure de plage : les destinataires déjà servis ne sont jamais renvoyés ;
  - annulation (portail : ses propres campagnes ; administration : toutes) ;
  - refus d'une date programmée déjà passée ;
  - verrou : deux exécutions de la même campagne ne tournent jamais en parallèle ;
  - carrousel sponsorisé : contrôle de la régie refait au moment réel de l'envoi.
MongoDB simulé, envoi WhatsApp simulé.
Lancer : cd backend && python -m pytest tests/test_carrousel_programmation_lot114.py -q
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.carrousel_whatsapp as cw  # noqa: E402
from routes.ad_banners import setup_ad_banners_routes  # noqa: E402
from routes.plages_envoi import attach_plages_envoi_routes  # noqa: E402
from tests.test_carrousel_whatsapp import BASE, CONTACTS, PRODUITS, USERS, h  # noqa: E402

CARTES = [{"source": "produit", "produit_id": "p1"}, {"source": "produit", "produit_id": "p2"}]


@pytest.fixture()
def env():
    """Application de test : carrousel + plages horaires (vraies routes) + régie, sur une base simulée.
    `etat["ferme"]` simule une plage horaire fermée (prochaine ouverture dans 2 h) ;
    `etat["fermer_apres"]` referme la plage après N envois (coupure en plein envoi)."""
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot114"]
    envois = []
    etat = {"ferme": False, "fermer_apres": None}

    async def get_user(request: Request):
        u = USERS.get(request.headers.get("X-User", ""))
        if not u:
            raise HTTPException(status_code=401)
        return u

    async def get_admin(request: Request):
        u = await get_user(request)
        if u["role"] != "admin":
            raise HTTPException(status_code=403)
        return u

    async def fonction_active(user, cle):
        if user["role"] == "admin":
            return True
        parent = USERS[user.get("parent_client_id") or user["id"]]
        return bool(parent.get("features", {}).get(cle))

    async def visibles(user):
        return [user.get("parent_client_id") or user["id"]]

    async def envoyer(to, nom, langue, comps, tenant_id=None):
        # Envoi WhatsApp simulé : toujours accepté ; peut refermer la plage après N envois
        envois.append(to)
        if etat["fermer_apres"] is not None and len(envois) >= etat["fermer_apres"]:
            etat["ferme"] = True
        return {"ok": True, "status": 200, "message_id": f"wamid.{len(envois)}", "error": None}

    async def creds(tenant_id):
        return {"access_token": "t", "phone_number_id": "1", "source": "global", "tenant_id": None}

    api = APIRouter(prefix="/api")
    plages = attach_plages_envoi_routes(api=api, db=db, get_current_admin=get_admin, get_current_user=get_user)

    async def attente(maintenant=None):
        # Plage simulée : ouverte, ou fermée avec une ouverture dans 2 heures
        return datetime.now(timezone.utc) + timedelta(hours=2) if etat["ferme"] else None

    plages_test = {**plages, "attente": attente}
    moteur = cw.attach_carrousel_whatsapp_routes(
        api=api, db=db, get_current_user=get_user, get_current_admin=get_admin, fonction_active=fonction_active,
        visible_client_ids=visibles, wa_send_template=envoyer, resolve_wa_credentials=creds,
        base_publique=lambda: BASE, plages=plages_test)
    setup_ad_banners_routes(app=api, db=db, get_current_user=get_user)
    app = FastAPI()
    app.include_router(api)
    client = TestClient(app).__enter__()
    client.portal.call(db.users.insert_many, [dict(u) for u in USERS.values()])
    client.portal.call(db.products.insert_many, [dict(p) for p in PRODUITS])
    client.portal.call(db.directory_contacts.insert_many, [dict(c) for c in CONTACTS])
    client.portal.call(db.settings.insert_one, {"_id": "global", "wa_carrousel_modele": "sawali_carrousel"})
    # Awa (c1) et Boris (c2) ont accepté de recevoir les messages de la Pharmacie A
    client.put("/api/me/whatsapp/carrousel/consentements", headers=h("cli_a"), json={"ids": ["c1", "c2"], "accepte": True})
    yield client, db, envois, etat, moteur
    client.__exit__(None, None, None)


def envoyer_portail(client, **kw):
    corps = {"message": "Nouveautés", "cartes": CARTES, "ids": ["c1", "c2"]}
    corps.update(kw)
    return client.post("/api/me/whatsapp/carrousel/envoyer", headers=h("cli_a"), json=corps)


def campagne(client, cid):
    return client.get(f"/api/me/whatsapp/carrousel/campagnes/{cid}", headers=h("cli_a")).json()


def rendre_echue(client, db, cid):
    """Simule le passage du temps : l'heure de reprise de la campagne est dépassée."""
    passe = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    client.portal.call(db.carrousel_campagnes.update_one, {"id": cid}, {"$set": {"reprise_le": passe}})


def ouagadougou(dans: timedelta) -> str:
    """« AAAA-MM-JJTHH:MM » en heure de Ouagadougou (UTC+0), comme le champ datetime-local du site."""
    return (datetime.now(timezone.utc) + dans).strftime("%Y-%m-%dT%H:%M")


def test_programmation_future_puis_demarrage(env):
    client, db, envois, _, moteur = env
    r = envoyer_portail(client, programme_le=ouagadougou(timedelta(days=1)))
    assert r.status_code == 202, r.text
    res = r.json()
    assert res["statut"] == "PROGRAMMEE" and res["statut_libelle"] == "Programmée" and res["programme_le"]
    assert envois == []                                     # rien ne part avant l'heure
    liste = client.get("/api/me/whatsapp/carrousel/campagnes", headers=h("cli_a")).json()["campagnes"]
    assert liste[0]["statut_libelle"] == "Programmée" and liste[0]["annulable"] is True
    # Le planificateur ne la démarre pas tant que l'heure n'est pas venue…
    assert client.portal.call(moteur["lancer_echus"], True) == 0
    # … puis la démarre une fois échue
    rendre_echue(client, db, res["id"])
    assert client.portal.call(moteur["lancer_echus"], True) == 1
    camp = campagne(client, res["id"])
    assert camp["statut"] == "TERMINEE" and camp["compte"]["envoyes"] == 2
    assert sorted(envois) == ["22676111111", "22676222222"]
    assert camp["verrou_jusqu_a"] is None                   # verrou libéré


def test_hors_plage_en_attente_puis_reprise(env):
    client, db, envois, etat, moteur = env
    etat["ferme"] = True
    r = envoyer_portail(client)
    assert r.status_code == 202 and r.json()["statut"] == "EN_ATTENTE" and r.json()["reprise_le"]
    assert envois == []
    # Toujours fermé à l'échéance : la campagne reste en attente (aucun envoi), nouvelle date de reprise
    rendre_echue(client, db, r.json()["id"])
    client.portal.call(moteur["lancer_echus"], True)
    camp = campagne(client, r.json()["id"])
    assert camp["statut"] == "EN_ATTENTE" and envois == [] and camp["reprise_le"] > datetime.now(timezone.utc).isoformat()
    # Ouverture de la plage : envoi complet
    etat["ferme"] = False
    rendre_echue(client, db, r.json()["id"])
    client.portal.call(moteur["lancer_echus"], True)
    assert campagne(client, r.json()["id"])["statut"] == "TERMINEE" and len(envois) == 2


def test_coupure_de_plage_et_reprise_sans_renvoi(env):
    client, db, envois, etat, moteur = env
    etat["fermer_apres"] = 1                                # la plage se referme après le 1er envoi
    r = envoyer_portail(client)
    assert r.status_code == 202 and r.json()["statut"] == "EN_COURS"
    cid = r.json()["id"]
    camp = campagne(client, cid)
    assert camp["statut"] == "EN_ATTENTE" and camp["compte"]["envoyes"] == 1 and len(envois) == 1
    assert [d["statut"] for d in camp["destinataires"]] == ["ENVOYE", "EN_ATTENTE"]
    premier = envois[0]
    # Réouverture : seul le destinataire restant est servi
    etat.update(ferme=False, fermer_apres=None)
    rendre_echue(client, db, cid)
    client.portal.call(moteur["lancer_echus"], True)
    camp = campagne(client, cid)
    assert camp["statut"] == "TERMINEE" and camp["compte"] == {"total": 2, "envoyes": 2, "echecs": 0}
    assert len(envois) == 2 and envois.count(premier) == 1   # jamais renvoyé au premier destinataire
    # Une nouvelle exécution d'une campagne terminée n'envoie plus rien
    client.portal.call(moteur["executer"], cid)
    assert len(envois) == 2


def test_verrou_empeche_deux_executions(env):
    client, db, envois, etat, moteur = env
    etat["ferme"] = True
    cid = envoyer_portail(client).json()["id"]
    # Campagne EN_COURS dont le verrou est tenu par une autre tâche (encore valable)
    futur = (datetime.now(timezone.utc) + timedelta(minutes=3)).isoformat()
    client.portal.call(db.carrousel_campagnes.update_one, {"id": cid},
                       {"$set": {"statut": "EN_COURS", "verrou_jusqu_a": futur}})
    etat["ferme"] = False
    client.portal.call(moteur["executer"], cid)
    assert envois == []                                     # verrou tenu : aucune seconde exécution
    assert client.portal.call(moteur["lancer_echus"], True) == 0
    # Verrou périmé (serveur arrêté en plein envoi) : le planificateur reprend la campagne
    passe = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    client.portal.call(db.carrousel_campagnes.update_one, {"id": cid}, {"$set": {"verrou_jusqu_a": passe}})
    assert client.portal.call(moteur["lancer_echus"], True) == 1
    assert campagne(client, cid)["statut"] == "TERMINEE" and len(envois) == 2


def test_annulation(env):
    client, db, envois, _, moteur = env
    cid = envoyer_portail(client, programme_le=ouagadougou(timedelta(hours=5))).json()["id"]
    # Un autre client ne peut pas annuler la campagne de la Pharmacie A
    USERS["cli_b"]["features"]["whatsapp_carrousel"] = True
    try:
        r = client.post(f"/api/me/whatsapp/carrousel/campagnes/{cid}/annuler", headers=h("cli_b"))
        assert r.status_code == 404
    finally:
        USERS["cli_b"]["features"].pop("whatsapp_carrousel")
    r = client.post(f"/api/me/whatsapp/carrousel/campagnes/{cid}/annuler", headers=h("suivi_a"))   # même client
    assert r.status_code == 200 and r.json()["statut"] == "ANNULEE"
    camp = campagne(client, cid)
    assert camp["statut"] == "ANNULEE" and camp["annule_le"]
    # Déjà annulée : refus clair ; jamais envoyée, même échue
    assert client.post(f"/api/me/whatsapp/carrousel/campagnes/{cid}/annuler", headers=h("cli_a")).status_code == 409
    rendre_echue(client, db, cid)
    client.portal.call(moteur["lancer_echus"], True)
    assert envois == []
    # L'administration annule toute campagne, y compris celle d'un client
    cid2 = envoyer_portail(client, programme_le=ouagadougou(timedelta(hours=5))).json()["id"]
    assert client.post(f"/api/admin/whatsapp/carrousel/campagnes/{cid2}/annuler", headers=h("cli_a")).status_code == 403
    r = client.post(f"/api/admin/whatsapp/carrousel/campagnes/{cid2}/annuler", headers=h("admin"))
    assert r.status_code == 200 and campagne(client, cid2)["statut"] == "ANNULEE"
    # Une campagne terminée ne s'annule plus
    cid3 = envoyer_portail(client).json()["id"]
    assert campagne(client, cid3)["statut"] == "TERMINEE"
    assert client.post(f"/api/me/whatsapp/carrousel/campagnes/{cid3}/annuler", headers=h("cli_a")).status_code == 409


def test_date_passee_refusee(env):
    client, db, envois, _, _ = env
    r = envoyer_portail(client, programme_le=ouagadougou(-timedelta(days=1)))
    assert r.status_code == 400 and "déjà passée" in r.json()["detail"]
    r = envoyer_portail(client, programme_le="pas une date")
    assert r.status_code == 400 and "invalide" in r.json()["detail"]
    assert client.portal.call(db.carrousel_campagnes.count_documents, {}) == 0 and envois == []


def test_admin_sponsorise_controle_regie_au_moment_envoi(env):
    client, db, envois, _, moteur = env
    client.put("/api/admin/whatsapp/carrousel/consentements", headers=h("admin"), json={"ids": ["cli_a"], "accepte": True})
    r = client.post("/api/admin/ad-banners", headers=h("admin"), json={
        "name": "Annonceur", "advertiser_name": "Laiterie", "placement": "carrousel_wa", "budget_amount": 200,
        "cost_per_click": 100, "cost_per_impression": 0, "active": True})
    regie_id = r.json()["item"]["id"]
    r = client.post("/api/admin/whatsapp/carrousel/envoyer", headers=h("admin"), json={
        "message": "Offre", "cartes": CARTES, "ids": ["cli_a"], "regie_id": regie_id,
        "programme_le": ouagadougou(timedelta(hours=3))})
    assert r.status_code == 202 and r.json()["statut"] == "PROGRAMMEE"
    cid = r.json()["id"]
    etat = client.get("/api/admin/whatsapp/carrousel/programmation/etat", headers=h("admin")).json()
    assert etat["programmees"] == 1 and etat["prochaine_reprise"]
    # Entre-temps, le budget de la régie est épuisé : la campagne n'est PAS envoyée à l'échéance
    client.portal.call(db.ad_banners.update_one, {"id": regie_id}, {"$set": {"amount_spent": 200}})
    rendre_echue(client, db, cid)
    client.portal.call(moteur["lancer_echus"], True)
    camp = client.get(f"/api/admin/whatsapp/carrousel/campagnes/{cid}", headers=h("admin")).json()
    assert camp["statut"] == "ANNULEE" and "budget" in camp["motif_arret"] and envois == []


def test_lot152_suivi_de_remise_dans_la_campagne(env):
    """Lot 152 : « Envoyé » = accepté par WhatsApp ; les accusés (remis / lu / non remis + motif) sont ajoutés
    à chaque destinataire de la campagne, lus dans whatsapp_messages."""
    client, db, envois, _, moteur = env
    res = envoyer_portail(client).json()
    client.portal.call(moteur["lancer_echus"], True)
    camp = campagne(client, res["id"])
    assert all(d["livraison"] == "sent" for d in camp["destinataires"]) and camp["livraison"]["en_attente"] == 2
    # Accusés reçus de WhatsApp : le 1er remis, le 2e en échec (limite de WhatsApp sur les messages marketing)
    client.portal.call(db.whatsapp_messages.update_one, {"message_id": "wamid.1"}, {"$set": {"wa_status": "delivered"}})
    client.portal.call(db.whatsapp_messages.update_one, {"message_id": "wamid.2"}, {"$set": {
        "wa_status": "failed", "wa_error_code": 131049, "wa_error_message": "Message non remis pour préserver la qualité de l'écosystème"}})
    camp = campagne(client, res["id"])
    par_id = {d["message_id"]: d for d in camp["destinataires"]}
    assert par_id["wamid.1"]["livraison"] == "delivered"
    assert par_id["wamid.2"]["livraison"] == "failed" and "131049" in par_id["wamid.2"]["livraison_erreur"]
    assert camp["livraison"] == {"remis": 1, "lus": 0, "non_remis": 1, "en_attente": 0}


def test_lot155_destinataires_jamais_repondus_signales(env):
    """Lot 155 : la liste des destinataires indique qui a déjà écrit à la plateforme (message reçu) et qui ne l'a jamais fait."""
    client, db, _, _, _ = env
    liste = client.get("/api/me/whatsapp/carrousel/destinataires", headers=h("cli_a")).json()["contacts"]
    assert liste and all(c["a_repondu"] is False for c in liste)
    avec_tel = next(c for c in liste if c["telephone"])
    from routes.carrousel_whatsapp import numero_whatsapp
    client.portal.call(db.whatsapp_messages.insert_one, {
        "id": "in1", "direction": "inbound", "phone_digits": numero_whatsapp(avec_tel["telephone"]), "body": "bonjour"})
    apres = {c["id"]: c["a_repondu"] for c in client.get("/api/me/whatsapp/carrousel/destinataires", headers=h("cli_a")).json()["contacts"]}
    assert apres[avec_tel["id"]] is True and sum(apres.values()) >= 1


def test_lot212_erreur_inattendue_jamais_silencieuse(env, monkeypatch):
    """Lot 212 — une erreur inattendue pendant l'envoi ne laisse plus la campagne « En cours » à l'infini : elle passe « En attente »
    avec un motif lisible et une nouvelle tentative automatique dans 10 minutes ; rien n'est envoyé ni renvoyé deux fois."""
    client, db, envois, etat, moteur = env

    def casse(*a, **k):
        raise RuntimeError("panne simulée")
    monkeypatch.setattr(cw, "composants", casse)
    r = envoyer_portail(client)
    assert r.status_code == 202
    camp = campagne(client, r.json()["id"])
    assert camp["statut"] == "EN_ATTENTE" and envois == []
    assert "Erreur technique" in camp["motif_arret"] and "panne simulée" in camp["motif_arret"]
    assert camp["reprise_le"] > datetime.now(timezone.utc).isoformat()
