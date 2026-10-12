"""Lot 132 — Facebook animé par Liluvine pour ZandGo, adLyn et bfmobility (en plus de beAuthentik) :
configuration par plateforme, migration douce des réglages de beAuthentik, préparation par plateforme
(plateforme simulée), modération produit (IA simulée + garde-fous fixes), publication sur la page PROPRE,
planificateur multi-plateformes et kit de lancement par plateforme.
Plateformes, IA et Facebook simulés ; MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_lot132_facebook_plateformes.py -q
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.facebook_animation as fa  # noqa: E402
import routes.facebook_kit as kit  # noqa: E402

ORIGINAL_PUBLIER = fa.publier_sur_facebook

# Candidats renvoyés par ZandGo : le 1er a une photo relative (refusé : Facebook ne pourrait pas la lire),
# le 2e est refusé par l'IA, le 3e est accepté
CANDIDATS_ZANDGO = [
    {"element_id": "p0", "nom": "Lampe", "photo_url": "/api/images/p0.jpg", "prix_fcfa": 5000, "lien": "https://zandgo.shop/produit/p0"},
    {"element_id": "p1", "nom": "Montre", "description": "Appelez le 70 12 34 56", "photo_url": "https://cdn/p1.jpg",
     "prix_fcfa": 9000, "lien": "https://zandgo.shop/produit/p1"},
    {"element_id": "p2", "nom": "sac a dos", "description": "sac solide pour l ecole", "photo_url": "https://cdn/p2.jpg",
     "prix_fcfa": 12500, "lien": "https://zandgo.shop/produit/p2"},
]
CANDIDATS_BFM = [
    {"element_id": "v1", "nom": "Toyota Corolla", "classe": "Confort", "description": "Berline climatisée",
     "photo_url": "https://api.bfm/api/public/photos-vehicules/ph1", "tarif_txt": "250 F CFA / km · 35 000 F CFA / jour",
     "lien": "https://bfm/vehicule/v1"},
]


@pytest.fixture
def env(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_fb132"]
    appels, posts = [], []

    async def plateforme(emetteur, corps):
        appels.append((emetteur["code"], corps))
        if corps["type"] != "facebook_candidats":
            return {"ok": True}
        return {"candidats": {"zandgo": CANDIDATS_ZANDGO, "bfmobility": CANDIDATS_BFM}.get(emetteur["code"], [])}

    async def moderer_produit(nom, description, contenu, nom_plateforme):
        if "70 12" in description:
            return {"conforme": False, "nom": "", "description": "", "raison": "numéro de téléphone"}
        return {"conforme": True, "nom": nom.capitalize().replace("a dos", "à dos"),
                "description": description.replace("l ecole", "l'école").capitalize(), "raison": ""}

    async def facebook(db_, texte, image_url, plateforme=None):
        posts.append({"texte": texte, "image_url": image_url, "plateforme": plateforme})
        return f"post_{len(posts)}"

    monkeypatch.setattr(fa, "appel_plateforme", plateforme)
    monkeypatch.setattr(fa, "moderer_produit", moderer_produit)
    monkeypatch.setattr(fa, "publier_sur_facebook", facebook)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.exemple.test")

    async def admin(request: Request):
        return {"id": "a", "role": "admin", "email": "admin@sawali"}

    api = APIRouter(prefix="/api")
    fa.attach_facebook_animation_routes(api=api, db=db, get_current_admin=admin)
    kit.attach_facebook_kit_routes(api=api, db=db, get_current_admin=admin)
    app = FastAPI()
    app.include_router(api)
    client = TestClient(app).__enter__()
    for code in ("beauthentik", "zandgo", "adlyn", "bfmobility"):
        client.portal.call(db.liluvine_emetteurs.insert_one, {"code": code, "secret": "s", "url_retour": f"https://{code}/x"})
    yield client, db, appels, posts
    client.__exit__(None, None, None)


def _settings(client, db):
    return client.portal.call(db.settings.find_one, {"_id": "global"}) or {}


def test_configuration_par_plateforme(env):
    client, db, _, _ = env
    etat = client.get("/api/admin/facebook/animation").json()
    codes = [c["code"] for c in etat["configurations"]]
    assert codes[:4] == ["beauthentik", "zandgo", "adlyn", "bfmobility"]
    par_code = {c["code"]: c for c in etat["configurations"]}
    assert par_code["zandgo"]["reglages"]["contenu"] == "produit" and par_code["bfmobility"]["reglages"]["contenu"] == "vehicule"
    assert par_code["beauthentik"]["reglages"]["contenu"] == "membre"
    # Légendes par défaut adaptées : hashtags et lien
    assert "#ZandGo" in par_code["zandgo"]["reglages"]["legende"] and "{lien_article}" in par_code["zandgo"]["reglages"]["legende"]
    assert "#adLyn" in par_code["adlyn"]["reglages"]["legende"] and "{boutique_txt}" in par_code["adlyn"]["reglages"]["legende"]
    assert "{tarif_txt}" in par_code["bfmobility"]["reglages"]["legende"]
    # Une plateforme sans page propre n'a PAS la page de SAWALI
    assert par_code["zandgo"]["page"] == {"connectee": False, "nom": "", "propre": False}

    # Réglages de ZandGo : rangés à part, beAuthentik inchangé
    r = client.put("/api/admin/facebook/animation/reglages", json={
        "plateforme": "zandgo", "actif": True, "jours": [0, 2], "heure": "09:30", "nombre": 3, "lien": "https://zandgo.shop",
        "legende": "Nouveau : {nom} à {prix_txt} {lien_article}"})
    assert r.status_code == 200 and r.json()["plateforme"] == "zandgo" and r.json()["heure"] == "09:30"
    s = _settings(client, db)
    assert s["fb_animation_plateformes"]["zandgo"]["jours"] == [0, 2]
    assert "fb_animation" not in s                      # beAuthentik : anciens réglages non touchés
    beau = client.get("/api/admin/facebook/animation", params={"plateforme": "beauthentik"}).json()["reglages"]
    assert beau["actif"] is False and beau["legende"] == fa.LEGENDE_DEFAUT
    # Code de plateforme invalide refusé
    assert client.put("/api/admin/facebook/animation/reglages", json={"plateforme": "../x"}).status_code == 422


def test_migration_douce_de_beauthentik(env):
    client, db, _, _ = env
    # Configuration telle qu'enregistrée par les lots 96-97
    client.portal.call(lambda: db.settings.update_one({"_id": "global"}, {"$set": {
        "fb_animation": {"actif": True, "plateforme": "beauthentik", "jours": [4], "heure": "18:00", "nombre": 2,
                         "validation_manuelle": False, "legende": "{prenom} : {bio}", "lien": "https://beauthentik.net",
                         "dernier_jour": "2026-10-09"},
        "fb_animation_page": {"id": "p_beauth", "nom": "beAuthentik", "jeton": "j-beauth"}}}, upsert=True))
    etat = client.get("/api/admin/facebook/animation").json()
    r = etat["reglages"]
    assert (r["plateforme"], r["actif"], r["jours"], r["heure"], r["nombre"], r["validation_manuelle"], r["legende"]) == \
        ("beauthentik", True, [4], "18:00", 2, False, "{prenom} : {bio}")
    assert r["dernier_jour"] == "2026-10-09" and r["contenu"] == "membre"
    assert etat["page"] == {"connectee": True, "nom": "beAuthentik", "propre": True}
    assert "jeton" not in str(etat)                     # le jeton ne sort jamais du serveur

    # Une modification de beAuthentik est recopiée à l'ancien emplacement (retour arrière possible)
    client.put("/api/admin/facebook/animation/reglages", json={"heure": "19:15"})
    s = _settings(client, db)
    assert s["fb_animation"]["heure"] == "19:15" and s["fb_animation_plateformes"]["beauthentik"]["heure"] == "19:15"
    assert s["fb_animation"]["legende"] == "{prenom} : {bio}"


def test_preparer_zandgo_moderer_publier(env):
    client, db, appels, posts = env
    r = client.post("/api/admin/facebook/animation/preparer", params={"plateforme": "zandgo"}).json()
    assert r["plateforme"] == "zandgo" and r["crees"] == 2          # p0 sauté (photo non publique)
    assert appels[0] == ("zandgo", {"type": "facebook_candidats", "nombre": 3})
    file_ = client.get("/api/admin/facebook/animation", params={"filtre": "zandgo"}).json()["publications"]
    assert {p["element_id"] for p in file_} == {"p1", "p2"}
    ok = next(p for p in file_ if p["element_id"] == "p2")
    ko = next(p for p in file_ if p["element_id"] == "p1")
    assert ko["statut"] == "refuse_ia" and ko["avis_ia"]["raison"] == "numéro de téléphone" and not ko["texte"]
    assert ok["statut"] == "a_valider" and ok["type"] == "produit"
    assert "Sac à dos" in ok["texte"] and "Sac solide pour l'école" in ok["texte"]
    assert "12 500 F CFA" in ok["texte"] and "https://zandgo.shop/produit/p2" in ok["texte"] and "#ZandGo" in ok["texte"]
    assert not posts

    # Filtre par plateforme : rien pour bfmobility
    assert client.get("/api/admin/facebook/animation", params={"filtre": "bfmobility"}).json()["publications"] == []

    # Validation : publication sur la page de ZANDGO, plateforme prévenue avec l'identifiant du produit
    v = client.post(f"/api/admin/facebook/animation/publications/{ok['id']}/valider").json()
    assert v["statut"] == "publie" and posts[0]["plateforme"] == "zandgo" and posts[0]["image_url"] == "https://cdn/p2.jpg"
    assert appels[-1] == ("zandgo", {"type": "facebook_publie", "element_id": "p2", "post_id": "post_1"})
    # Préparation suivante : p1 (refusé) n'est pas reproposé ; p2 publié est écarté par la plateforme elle-même
    r2 = client.post("/api/admin/facebook/animation/preparer", params={"plateforme": "zandgo"}).json()
    assert "p1" not in [p["element_id"] for p in r2["publications"]]


def test_preparer_bfmobility_vehicule(env):
    client, _, _, _ = env
    r = client.post("/api/admin/facebook/animation/preparer", params={"plateforme": "bfmobility"}).json()
    assert r["crees"] == 1
    texte = r["publications"][0]["texte"]
    assert "Toyota corolla (Confort)" in texte and "35 000 F CFA / jour" in texte and "https://bfm/vehicule/v1" in texte
    assert "#bfmobility" in texte


def test_publication_sans_page_propre_jamais_sur_sawali(env, monkeypatch):
    client, db, _, _ = env
    import routes.facebook as fb
    vus = []

    async def poster(page_id, jeton, texte, image):
        vus.append(page_id)
        return {"post_id": "123"}

    monkeypatch.setattr(fb, "_post_to_page", poster)
    monkeypatch.setattr(fa, "publier_sur_facebook", ORIGINAL_PUBLIER)
    client.portal.call(lambda: db.settings.update_one({"_id": "global"}, {"$set": {
        "facebook_page_id": "p_sawali", "facebook_page_access_token": "jeton-sawali"}}, upsert=True))
    # ZandGo sans page propre : échec clair, rien sur la page de SAWALI
    with pytest.raises(RuntimeError, match="ZandGo"):
        client.portal.call(lambda: fa.publier_sur_facebook(db, "Bonjour", "https://x/p.jpg", "zandgo"))
    assert vus == []

    # Page de ZandGo choisie : la publication y part
    async def pages(db_):
        return [{"id": "p_zandgo", "nom": "ZandGo", "jeton": "jeton-zandgo"}]
    monkeypatch.setattr(fa, "pages_du_compte", pages)
    assert client.put("/api/admin/facebook/animation/page", json={"page_id": "p_zandgo", "plateforme": "zandgo"}).status_code == 200
    assert client.portal.call(lambda: fa.publier_sur_facebook(db, "Bonjour", "https://x/p.jpg", "zandgo")) == "123"
    assert vus == ["p_zandgo"]
    s = _settings(client, db)
    assert "fb_animation_page" not in s                     # la page de beAuthentik n'est pas touchée
    # beAuthentik garde la page active de SAWALI en secours (comportement des lots 96-97)
    assert client.portal.call(lambda: fa.publier_sur_facebook(db, "Bonjour", "https://x/m.jpg")) == "123"
    assert vus[-1] == "p_sawali"
    # Retrait de la page de ZandGo
    client.put("/api/admin/facebook/animation/page", json={"page_id": "", "plateforme": "zandgo"})
    assert client.get("/api/admin/facebook/animation", params={"plateforme": "zandgo"}).json()["page"]["propre"] is False


def test_planificateur_par_plateforme(env, monkeypatch):
    client, db, appels, _ = env
    jeudi_11h = datetime(2026, 10, 8, 11, 0, tzinfo=timezone.utc)    # jeudi = 3
    monkeypatch.setattr(fa, "_maintenant", lambda: jeudi_11h)
    client.put("/api/admin/facebook/animation/reglages", json={"plateforme": "zandgo", "actif": True, "jours": [3], "heure": "10:00"})
    client.put("/api/admin/facebook/animation/reglages", json={"plateforme": "bfmobility", "actif": True, "jours": [3], "heure": "12:00"})
    client.portal.call(fa.tick, db)
    demandees = [code for code, corps in appels if corps["type"] == "facebook_candidats"]
    assert demandees == ["zandgo"]                         # bfmobility : pas encore l'heure ; beAuthentik inactive
    s = _settings(client, db)
    assert s["fb_animation_plateformes"]["zandgo"]["dernier_jour"] == "2026-10-08"
    client.portal.call(fa.tick, db)                        # une seule préparation par jour
    assert [c for c, corps in appels if corps["type"] == "facebook_candidats"] == ["zandgo"]


def test_moderation_produit_garde_fous():
    # Avis correct : orthographe corrigée, aucun prix ajouté
    ok = fa.lire_avis_produit('{"conforme": true, "nom": "Sac à dos", "description": "Sac solide.", "raison": ""}',
                              "sac a dos", "sac solide")
    assert ok == {"conforme": True, "nom": "Sac à dos", "description": "Sac solide.", "raison": ""}
    # L'IA a inventé un prix : refus
    prix = fa.lire_avis_produit('{"conforme": true, "nom": "Sac", "description": "Seulement 5 000 F CFA !"}', "Sac", "Sac solide")
    assert prix["conforme"] is False and "prix" in prix["raison"]
    # Un prix déjà présent dans la fiche d'origine reste admis
    garde = fa.lire_avis_produit('{"conforme": true, "nom": "Sac", "description": "Promo à 5000 FCFA."}', "Sac", "promo a 5000 FCFA")
    assert garde["conforme"] is True
    # Coordonnées laissées par l'IA : refus quand même
    tel = fa.lire_avis_produit('{"conforme": true, "nom": "Sac", "description": "Infos au 70 12 34 56"}', "Sac", "")
    assert tel["conforme"] is False and "téléphone" in tel["raison"]
    assert fa.lire_avis_produit("illisible", "Sac", "")["conforme"] is False
    # Garde-fous fixes
    assert fa.coordonnees_detectees("Écrivez à awa@exemple.com") == "adresse e-mail dans le texte"
    assert fa.coordonnees_detectees("voir www.exemple.com") == "lien dans le texte"
    assert fa.coordonnees_detectees("+226 70 12 34 56") and fa.coordonnees_detectees("70123456")
    assert fa.coordonnees_detectees("Écran 1920 1080, batterie 10000 mAh") == ""
    # Légende : variable inconnue vide, prix de la plateforme jamais inventé
    cand = {"nom": "Sac", "prix_fcfa": None, "lien": "https://z/p"}
    t = fa.legende_element("{nom} {inconnue}- {prix_txt} {lien_article}", fa.LEGENDE_ZANDGO, cand, {"nom": "Sac"}, "https://z")
    assert t == "Sac - Prix sur demande https://z/p"


def test_kit_de_lancement_par_plateforme(env):
    client, db, appels, posts = env
    # Visuels publics de chaque nouvelle plateforme (liste blanche)
    for code in ("zandgo", "adlyn", "bfmobility"):
        for f in ["photo-profil.jpg", "couverture.jpg"] + [f"publication-{i}.jpg" for i in range(1, 7)]:
            r = client.get(f"/api/facebook/kit/{code}/{f}")
            assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg", (code, f)
        k = kit.KITS[code]
        assert len(k["a_propos"]["presentation"]) <= 101
        assert all(k["a_propos"]["site_web"] in p["texte"] and "#" in p["texte"] for p in k["publications"])
        # Aucune promesse chiffrée : aucun prix dans les annonces
        assert not any(fa._montants(p["texte"]) for p in k["publications"])
    assert client.get("/api/facebook/kit/zandgo/publication-7.jpg").status_code == 404
    assert client.get("/api/admin/facebook/animation/kit", params={"plateforme": "inconnue"}).status_code == 404

    # Ton propre à chaque plateforme
    assert "livr" in kit.KITS["zandgo"]["publications"][0]["texte"]
    assert "commerçants" in kit.KITS["adlyn"]["publications"][0]["texte"]
    assert "Location de véhicules" in kit.KITS["bfmobility"]["publications"][0]["texte"]

    # Chargement : exige la page propre d'adLyn (la page de beAuthentik ne suffit pas)
    client.portal.call(lambda: db.settings.update_one({"_id": "global"}, {"$set": {
        "fb_animation_page": {"id": "p_beauth", "nom": "beAuthentik", "jeton": "j"}}}, upsert=True))
    r = client.post("/api/admin/facebook/animation/kit/charger", params={"plateforme": "adlyn"})
    assert r.status_code == 400 and "adLyn" in r.json()["detail"]
    client.portal.call(lambda: db.settings.update_one({"_id": "global"}, {"$set": {
        "fb_animation_plateformes.adlyn.page": {"id": "p_adlyn", "nom": "adLyn", "jeton": "j2"}}}))
    assert client.post("/api/admin/facebook/animation/kit/charger", params={"plateforme": "adlyn"}).json() == {"crees": 6, "total": 6}
    etat = client.get("/api/admin/facebook/animation/kit", params={"plateforme": "adlyn"}).json()
    assert etat["charges"] == 6 and etat["nom"] == "adLyn" and etat["couverture"].endswith("/api/facebook/kit/adlyn/couverture.jpg")
    pubs = client.get("/api/admin/facebook/animation", params={"filtre": "adlyn"}).json()["publications"]
    assert [p["rang"] for p in pubs] == list(range(1, 7)) and pubs[0]["total_kit"] == 6
    v = client.post(f"/api/admin/facebook/animation/publications/{pubs[0]['id']}/valider").json()
    assert v["statut"] == "publie" and posts[-1]["plateforme"] == "adlyn"
    assert appels == []                                     # kit : la plateforme n'est pas prévenue
    # Le kit de beAuthentik reste celui des lots 105 (8 publications)
    assert client.get("/api/admin/facebook/animation/kit").json()["total"] == 8
