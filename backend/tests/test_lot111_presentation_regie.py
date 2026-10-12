"""Lot 111 — page de présentation de tout un carrousel WhatsApp (une position #carte-n par carte) et carrousel
SPONSORISÉ piloté par la régie publicitaire (ad_banners, placement « carrousel_wa ») : clics facturés au coût par
clic avec déduplication 24 h par appareil, budget épuisé, exclusion de la rotation des bannières, rapport public.
MongoDB simulé, envoi WhatsApp simulé.
Lancer : cd backend && python -m pytest tests/test_lot111_presentation_regie.py -q
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.carrousel_regie as regie  # noqa: E402
import routes.carrousel_whatsapp as cw  # noqa: E402
from routes.ad_banners import setup_ad_banners_routes  # noqa: E402
from tests.test_carrousel_whatsapp import BASE, CONTACTS, PRODUITS, USERS, h  # noqa: E402

IMAGE = f"{BASE}/api/files/c/1.png"
CARTES = [
    # Carte 1 : présentation (description détaillée en markdown simple)
    {"source": "libre", "image_url": IMAGE, "titre": "Journée santé", "texte": "Samedi 9h",
     "description_detaillee": "**Dépistage gratuit**\n- tension\n- glycémie", "bouton": "presentation"},
    # Carte 2 : un lien est saisi mais le mode « presentation » est choisi : la page de présentation l'emporte
    {"source": "libre", "image_url": IMAGE, "titre": "Promo", "texte": "-20 %", "lien": "https://boutique.bf/promo",
     "bouton": "presentation"},
    # Carte 3 : lien personnalisé (comportement d'avant le lot 111)
    {"source": "libre", "image_url": IMAGE, "titre": "Boutique", "lien": "https://boutique.bf", "bouton": "lien"},
]


@pytest.fixture()
def env():
    """Application de test : routes du carrousel ET de la régie publicitaire sur la même base simulée."""
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot111"]
    envois = []

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
        # Envoi WhatsApp simulé : toujours accepté par « Meta »
        envois.append({"to": to, "modele": nom, "composants": comps})
        return {"ok": True, "status": 200, "message_id": f"wamid.{len(envois)}", "error": None}

    async def creds(tenant_id):
        return {"access_token": "t", "phone_number_id": "1", "source": "global", "tenant_id": None}

    api = APIRouter(prefix="/api")
    cw.attach_carrousel_whatsapp_routes(
        api=api, db=db, get_current_user=get_user, get_current_admin=get_admin, fonction_active=fonction_active,
        visible_client_ids=visibles, wa_send_template=envoyer, resolve_wa_credentials=creds,
        base_publique=lambda: BASE)
    setup_ad_banners_routes(app=api, db=db, get_current_user=get_user)
    app = FastAPI()
    app.include_router(api)
    client = TestClient(app).__enter__()
    client.portal.call(db.users.insert_many, [dict(u) for u in USERS.values()])
    client.portal.call(db.products.insert_many, [dict(p) for p in PRODUITS])
    client.portal.call(db.directory_contacts.insert_many, [dict(c) for c in CONTACTS])
    client.portal.call(db.settings.insert_one, {"_id": "global", "wa_carrousel_modele": "sawali_carrousel",
                                                "company_whatsapp": "+226 25 00 00 00"})
    yield client, db, envois
    client.__exit__(None, None, None)


def appareil(n: int) -> dict:
    """En-têtes d'un « appareil » : même IP et même navigateur = même empreinte."""
    return {"x-forwarded-for": f"10.0.0.{n}", "user-agent": f"WhatsApp/2.{n}"}


def envoi_portail(client) -> dict:
    """Carrousel du portail (Pharmacie A) envoyé à Awa : renvoie la campagne lue par le portail."""
    client.put("/api/me/whatsapp/carrousel/consentements", headers=h("cli_a"), json={"ids": ["c1"], "accepte": True})
    r = client.post("/api/me/whatsapp/carrousel/envoyer", headers=h("cli_a"),
                    json={"message": "Nos nouveautés", "cartes": CARTES, "ids": ["c1"]})
    assert r.status_code == 202, r.text
    return client.get(f"/api/me/whatsapp/carrousel/campagnes/{r.json()['id']}", headers=h("cli_a")).json()


def creer_regie(client, **kw) -> dict:
    """Campagne de régie « Carrousel WhatsApp » (annonceur) créée par l'administration."""
    corps = {"name": "Annonceur Lait", "advertiser_name": "Laiterie", "placement": "carrousel_wa",
             "budget_amount": 200, "cost_per_click": 100, "cost_per_impression": 0, "active": True}
    corps.update(kw)
    r = client.post("/api/admin/ad-banners", headers=h("admin"), json=corps)
    assert r.status_code == 200, r.text
    return r.json()["item"]


def envoi_admin(client, regie_id=None):
    """Carrousel de l'administration envoyé au client cli_a (consentant), sponsorisé si regie_id."""
    client.put("/api/admin/whatsapp/carrousel/consentements", headers=h("admin"), json={"ids": ["cli_a"], "accepte": True})
    return client.post("/api/admin/whatsapp/carrousel/envoyer", headers=h("admin"),
                       json={"message": "Offre partenaire", "cartes": CARTES[:2], "ids": ["cli_a"], "regie_id": regie_id})


# ---------------------------------------------------------------------------
# A. Page de présentation
# ---------------------------------------------------------------------------
def test_fonctions_pures():
    assert regie.chemin_presentation("AbC", "k1", 3) == "/presentation/c/AbC?depuis=k1#carte-3"
    assert regie.empreinte("1.2.3.4", "UA") == regie.empreinte("1.2.3.4", "UA") != regie.empreinte("1.2.3.5", "UA")
    assert "1.2.3.4" not in regie.empreinte("1.2.3.4", "UA")       # jamais l'IP en clair
    assert len(regie.nouvel_id_public()) >= 16


def test_redirection_302_vers_la_carte(env):
    client, db, envois = env
    camp = envoi_portail(client)
    codes = [c["code_lien"] for c in camp["cartes"]]
    assert camp["id_public"] and camp["id_public"] != camp["id"]   # identifiant public distinct de l'id interne
    assert [c["bouton"] for c in camp["cartes"]] == ["presentation", "presentation", "lien"]
    for n, code in enumerate(codes[:2], 1):
        r = client.get(f"/api/public/carrousel/l/{code}", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == f"{BASE}/presentation/c/{camp['id_public']}?depuis={code}#carte-{n}"
    # Mode « lien » : le lien personnalisé est conservé
    r = client.get(f"/api/public/carrousel/l/{codes[2]}", follow_redirects=False)
    assert r.headers["location"] == "https://boutique.bf"
    # Le clic reste compté
    liste = client.get("/api/me/whatsapp/carrousel/campagnes", headers=h("cli_a")).json()["campagnes"]
    assert [c["clics"] for c in liste[0]["cartes"]] == [1, 1, 1]


def test_pas_de_diese_dans_le_modele_meta(env):
    client, db, envois = env
    envoi_portail(client)
    # Variable du bouton = code court seul ; l'adresse du modèle Meta reste inchangée
    for carte in envois[0]["composants"][1]["cards"]:
        variable = carte["components"][2]["parameters"][0]["text"]
        assert "#" not in variable and "/" not in variable and "?" not in variable
    etat = client.get("/api/me/whatsapp/carrousel", headers=h("cli_a")).json()
    assert etat["url_bouton_modele"] == f"{BASE}/l/{{{{1}}}}"   # lot 117 : page du site


def test_ancien_lien_et_ancienne_campagne(env):
    client, db, _ = env
    camp = envoi_portail(client)
    code = camp["cartes"][1]["code_lien"]
    # Campagne envoyée avant le lot 111 : pas d'identifiant public, il est créé au premier clic
    client.portal.call(db.carrousel_campagnes.update_one, {"id": camp["id"]}, {"$unset": {"id_public": ""}})
    client.portal.call(db.carrousel_liens.update_one, {"code": code}, {"$unset": {"bouton": ""}, "$set": {"cible": ""}})
    r = client.get(f"/api/public/carrousel/l/{code}", follow_redirects=False)
    nouveau = client.portal.call(db.carrousel_campagnes.find_one, {"id": camp["id"]})["id_public"]
    assert nouveau and r.headers["location"] == f"{BASE}/presentation/c/{nouveau}?depuis={code}#carte-2"
    # L'ancienne page /presentation/{code} sait où rediriger
    p = client.get(f"/api/public/carrousel/carte/{code}").json()
    assert p["id_public"] == nouveau and p["n"] == 2


def test_route_publique_sans_donnees_personnelles(env):
    client, db, _ = env
    camp = envoi_portail(client)
    r = client.get(f"/api/public/carrousel/presentation/{camp['id_public']}")
    assert r.status_code == 200
    p = r.json()
    assert p["expediteur"] == "Pharmacie A" and p["contact_whatsapp"] == "22670000001"
    assert [c["n"] for c in p["cartes"]] == [1, 2, 3]
    assert p["cartes"][0]["description_detaillee"].startswith("**Dépistage gratuit**")
    assert p["cartes"][1]["lien"] == "https://boutique.bf/promo"
    brut = json.dumps(p, ensure_ascii=False)
    # Ni destinataire, ni numéro de destinataire, ni identifiant interne
    for interdit in ("destinataires", "Awa", "22676111111", camp["id"], "cree_par", "tenant_id"):
        assert interdit not in brut
    # L'identifiant interne ne donne pas accès à la page
    assert client.get(f"/api/public/carrousel/presentation/{camp['id']}").status_code == 404


def test_evenements_dedupliques(env):
    client, db, _ = env
    camp = envoi_portail(client)
    corps = {"campagne": camp["id_public"], "carte": 2, "type": "vue"}
    assert client.post("/api/public/carrousel/evenement", json=corps, headers=appareil(1)).json()["compte"] is True
    assert client.post("/api/public/carrousel/evenement", json=corps, headers=appareil(1)).json()["compte"] is False
    assert client.post("/api/public/carrousel/evenement", json=corps, headers=appareil(2)).json()["compte"] is True
    interet = {"code": camp["cartes"][1]["code_lien"], "carte": 2, "type": "interesse"}
    assert client.post("/api/public/carrousel/evenement", json=interet, headers=appareil(1)).json()["compte"] is True
    assert client.post("/api/public/carrousel/evenement", json=interet, headers=appareil(1)).json()["compte"] is False
    # Carte hors du carrousel, campagne inconnue, type inconnu : refusés
    assert client.post("/api/public/carrousel/evenement", json={**corps, "carte": 9}).status_code == 400
    assert client.post("/api/public/carrousel/evenement", json={**corps, "campagne": "inconnue"}).status_code == 404
    assert client.post("/api/public/carrousel/evenement", json={**corps, "type": "achat"}).status_code == 422
    # Chiffres par carte dans l'écran du carrousel
    carte = client.get("/api/me/whatsapp/carrousel/campagnes", headers=h("cli_a")).json()["campagnes"][0]["cartes"][1]
    assert carte["vues"] == 2 and carte["interesses"] == 1


# ---------------------------------------------------------------------------
# B. Régie publicitaire
# ---------------------------------------------------------------------------
def test_facturation_par_clic_dedupliquee_et_budget_epuise(env):
    client, db, _ = env
    b = creer_regie(client)                       # 100 XOF par clic, budget 200
    r = envoi_admin(client, b["id"])
    assert r.status_code == 202, r.text
    camp = client.portal.call(db.carrousel_campagnes.find_one, {"id": r.json()["id"]})
    assert camp["regie_id"] == b["id"]
    code = camp["cartes"][0]["code_lien"]
    ouvrir = lambda n: client.get(f"/api/public/carrousel/l/{code}", follow_redirects=False, headers=appareil(n))  # noqa: E731
    assert ouvrir(1).status_code == 302
    assert ouvrir(1).status_code == 302           # même appareil, même carte, moins de 24 h : pas refacturé
    fiche = client.portal.call(db.ad_banners.find_one, {"id": b["id"]})
    assert fiche["total_clicks"] == 1 and fiche["amount_spent"] == 100 and fiche["carrousel_clics_bruts"] == 2
    jour = fiche["daily_stats"][-1]
    assert jour["clicks"] == 1 and jour["clics_bruts"] == 2 and jour["spent"] == 100
    ouvrir(2)                                     # 2e appareil : facturé, budget atteint (200/200)
    fiche = client.portal.call(db.ad_banners.find_one, {"id": b["id"]})
    assert fiche["total_clicks"] == 2 and fiche["amount_spent"] == 200 and fiche["active"] is False
    # Budget épuisé : le lien fonctionne toujours, le clic est compté à part mais n'est plus facturé
    r3 = ouvrir(3)
    assert r3.status_code == 302 and "/presentation/c/" in r3.headers["location"]
    fiche = client.portal.call(db.ad_banners.find_one, {"id": b["id"]})
    assert fiche["total_clicks"] == 2 and fiche["amount_spent"] == 200
    assert fiche["carrousel_clics_bruts"] == 4 and fiche["carrousel_clics_hors_budget"] == 1
    # … et le carrousel sponsorisé n'est plus envoyable
    refus = envoi_admin(client, b["id"])
    assert refus.status_code == 400 and "budget épuisé" in refus.json()["detail"]
    # Écran du carrousel : clics facturés par carte et nom de la régie
    liste = client.get("/api/admin/whatsapp/carrousel/campagnes", headers=h("admin")).json()["campagnes"]
    assert liste[0]["regie_nom"] == "Annonceur Lait" and liste[0]["cartes"][0]["clics_factures"] == 2


def test_campagne_expiree_non_envoyable_et_cout_par_envoi(env):
    client, db, _ = env
    hier = (date.today() - timedelta(days=1)).isoformat()
    expiree = creer_regie(client, expiration_date=hier)
    r = envoi_admin(client, expiree["id"])
    assert r.status_code == 400 and "expirée" in r.json()["detail"]
    # Coût par envoi : chaque message accepté par Meta est compté et facturé
    b = creer_regie(client, name="Envoi payant", cost_per_impression=10, budget_amount=1000)
    assert envoi_admin(client, b["id"]).status_code == 202
    fiche = client.portal.call(db.ad_banners.find_one, {"id": b["id"]})
    assert fiche["total_impressions"] == 1 and fiche["carrousel_envois"] == 1 and fiche["amount_spent"] == 10
    # Le portail ne peut pas sponsoriser : le regie_id est ignoré
    client.put("/api/me/whatsapp/carrousel/consentements", headers=h("cli_a"), json={"ids": ["c1"], "accepte": True})
    rp = client.post("/api/me/whatsapp/carrousel/envoyer", headers=h("cli_a"),
                     json={"message": "x", "cartes": CARTES[:2], "ids": ["c1"], "regie_id": b["id"]})
    assert client.portal.call(db.carrousel_campagnes.find_one, {"id": rp.json()["id"]})["regie_id"] is None


def test_carrousel_exclu_de_la_rotation_des_bannieres(env):
    client, db, _ = env
    b = creer_regie(client, budget_amount=0)
    # Seule campagne active : la rotation ne sert rien
    for placement in ("public", "portal", "public_modal"):
        assert client.get(f"/api/public/ad-banners/active?placement={placement}").json()["banner"] is None
    # Même rangée par erreur en « both », elle reste exclue
    client.portal.call(db.ad_banners.update_one, {"id": b["id"]}, {"$set": {"placement": "both"}})
    client.portal.call(db.ad_banners.update_one, {"id": b["id"]}, {"$set": {"placement": "carrousel_wa"}})
    banniere = client.post("/api/admin/ad-banners", headers=h("admin"), json={
        "name": "Bannière", "image_url": "https://x.bf/b.jpg", "target_url": "https://x.bf", "placement": "both"}).json()["item"]
    for _ in range(10):
        assert client.get("/api/public/ad-banners/active?placement=public").json()["banner"]["id"] == banniere["id"]
    # Les routes impression / clic des bannières refusent une campagne de carrousel
    assert client.post(f"/api/public/ad-banners/{b['id']}/click").json()["ok"] is False
    assert client.post(f"/api/public/ad-banners/{b['id']}/impression").json()["ok"] is False
    assert client.portal.call(db.ad_banners.find_one, {"id": b["id"]})["total_clicks"] == 0
    # Une bannière ordinaire garde son image et son lien obligatoires
    assert client.post("/api/admin/ad-banners", headers=h("admin"), json={"name": "Sans image"}).status_code == 422


def test_rapport_public_annonceur(env):
    client, db, _ = env
    b = creer_regie(client, budget_amount=1000)
    cid = envoi_admin(client, b["id"]).json()["id"]
    camp = client.portal.call(db.carrousel_campagnes.find_one, {"id": cid})
    client.get(f"/api/public/carrousel/l/{camp['cartes'][1]['code_lien']}", follow_redirects=False, headers=appareil(1))
    client.post("/api/public/carrousel/evenement", json={"campagne": camp["id_public"], "carte": 2, "type": "vue"},
                headers=appareil(1))
    client.post("/api/public/carrousel/evenement", json={"campagne": camp["id_public"], "carte": 2, "type": "interesse"},
                headers=appareil(1))
    fiche = client.portal.call(db.ad_banners.find_one, {"id": b["id"]})
    assert fiche["image_url"] == IMAGE                # aperçu repris de la 1re carte
    r = client.get(f"/api/public/ads-report/{fiche['slug']}", params={"token": fiche["share_token"]})
    assert r.status_code == 200
    rap = r.json()
    assert rap["type"] == "carrousel_wa" and rap["budget"]["remaining"] == 900
    c = rap["carrousel"]
    assert (c["envois"], c["clics_bruts"], c["clics_facturables"], c["vues"], c["interesses"]) == (1, 1, 1, 1, 1)
    carte2 = c["campagnes"][0]["cartes"][1]
    assert carte2 == {"n": 2, "titre": "Promo", "clics": 1, "clics_factures": 1, "vues": 1, "interesses": 1}
    jour = rap["daily"][-1]
    assert jour["impressions"] == 1 and jour["clicks"] == 1 and jour["vues"] == 1 and jour["interesses"] == 1
    brut = json.dumps(rap, ensure_ascii=False)
    assert "destinataires" not in brut and "22670000001" not in brut
    # Mauvais jeton : refusé
    assert client.get(f"/api/public/ads-report/{fiche['slug']}", params={"token": "x"}).status_code == 403


def test_rattachement_depuis_la_regie_et_le_carrousel(env):
    client, db, _ = env
    cid = envoi_admin(client).json()["id"]           # envoi non sponsorisé
    b = creer_regie(client)
    # Depuis l'écran du carrousel
    assert client.get("/api/admin/whatsapp/carrousel/regies", headers=h("admin")).json()["regies"][0]["motif"] is None
    r = client.put(f"/api/admin/whatsapp/carrousel/campagnes/{cid}/regie", headers=h("admin"), json={"regie_id": b["id"]})
    assert r.status_code == 200
    assert client.portal.call(db.ad_banners.find_one, {"id": b["id"]})["carrousel_campagne_ids"] == [cid]
    # Depuis la régie : liste complète (vide = détaché)
    lignes = client.get("/api/admin/ad-banners/carrousels", headers=h("admin")).json()["items"]
    assert lignes[0]["regie_nom"] == "Annonceur Lait" and "destinataires" not in lignes[0]
    client.put(f"/api/admin/ad-banners/{b['id']}", headers=h("admin"), json={"carrousel_campagne_ids": []})
    assert "regie_id" not in client.portal.call(db.carrousel_campagnes.find_one, {"id": cid})
    # Une campagne de régie qui n'est pas « Carrousel WhatsApp » est refusée
    autre = client.post("/api/admin/ad-banners", headers=h("admin"), json={
        "name": "Bannière", "image_url": "https://x.bf/b.jpg", "target_url": "https://x.bf"}).json()["item"]
    assert client.put(f"/api/admin/whatsapp/carrousel/campagnes/{cid}/regie", headers=h("admin"),
                      json={"regie_id": autre["id"]}).status_code == 400
    etat = client.get("/api/admin/whatsapp/carrousel/regie/etat", headers=h("admin")).json()
    assert etat["dedup_heures"] == 24 and etat["campagnes_regie"] == 1
