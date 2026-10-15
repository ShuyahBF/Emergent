"""Lot 193 — publicité à carrousel Click-to-WhatsApp : budget, ciblage, cartes, créatif, création EN PAUSE, nettoyage en cas
d'échec, statut limité aux campagnes de l'envoi. API de Meta simulée, MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_lot193_carrousel_publicite.py -q
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.carrousel_publicite as cp  # noqa: E402
from fastapi import HTTPException  # noqa: E402


def lancer(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


CARTES = [
    {"titre": "Paracétamol 500 mg — boîte de vingt comprimés pelliculés", "texte": "Boîte de 20", "image_url": "https://x.test/a.jpg"},
    {"titre": "Vitamine C", "texte": "", "image_url": "/api/files/b.jpg"},           # image non publique : ignorée
    {"titre": "", "texte": "Sirop", "image_url": "https://x.test/c.png"},
]


def test_budget_selon_la_devise():
    assert cp.budget_en_unites_meta("5000", "XOF") == 5000            # franc CFA : pas de centimes
    assert cp.budget_en_unites_meta("3,5", "EUR") == 350              # euro : centimes
    assert cp.budget_en_unites_meta(10, "usd") == 1000
    for mauvais in ("0", "-2", "abc", None):
        with pytest.raises(HTTPException):
            cp.budget_en_unites_meta(mauvais, "XOF")


def test_ciblage():
    assert cp.ciblage("bf, ci", 18, 45) == {"geo_locations": {"countries": ["BF", "CI"]}, "age_min": 18, "age_max": 45}
    assert cp.ciblage(["BF"], None, None)["age_max"] == 65
    for pays, a, b in [("", 18, 30), ("BFA", 18, 30), ("BF", 40, 20), ("BF", 10, 30), ("BF", "x", 30)]:
        with pytest.raises(HTTPException):
            cp.ciblage(pays, a, b)


def test_cartes_et_creatif():
    lien = cp.lien_whatsapp("+226 70 00 00 01")
    assert lien == "https://api.whatsapp.com/send?phone=22670000001" and cp.lien_whatsapp("") == "https://api.whatsapp.com/send"
    cartes = cp.cartes_publicitaires(CARTES, [None, "https://y.test/new.jpg", None], lien)
    assert [c["picture"] for c in cartes] == ["https://x.test/a.jpg", "https://y.test/new.jpg", "https://x.test/c.png"]
    assert len(cartes[0]["name"]) == 40 and cartes[2]["name"] == "Découvrir"          # titre tronqué ; titre vide → libellé
    assert cartes[0]["call_to_action"] == {"type": "WHATSAPP_MESSAGE", "value": {"app_destination": "WHATSAPP"}}
    with pytest.raises(HTTPException):       # une seule image publique : pas un carrousel
        cp.cartes_publicitaires(CARTES[:2], None, lien)
    ld = cp.histoire_creative("P1", "Bonjour", cartes, lien)["link_data"]
    assert ld["child_attachments"] == cartes and ld["call_to_action"]["type"] == "WHATSAPP_MESSAGE" and ld["message"] == "Bonjour"
    assert "act=123" in cp.lien_gestionnaire("act_123", "C9") and "selected_campaign_ids=C9" in cp.lien_gestionnaire("act_123", "C9")


@pytest.fixture()
def env(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["t193"]
    lancer(db.carrousel_campagnes.insert_one({"id": "camp1", "cartes": CARTES + [{"titre": "Quatre", "image_url": "https://x.test/d.jpg"}], "message": "Bonjour"}))
    lancer(db.meta_integrations.insert_one({
        "tenant_id": "adm", "meta_user": {"long_lived_user_access_token": "JETON_SECRET"},
        "pages": [{"page_id": "P1", "name": "Page SAWALI", "page_access_token": "JETON_PAGE"}],
        "ads_accounts": [{"id": "act_123", "name": "Compte pub", "currency": "XOF", "status": 1}]}))
    appels, echec_sur = [], {"etape": None}

    async def faux_graph(_db, chemin, jeton, donnees):
        appels.append((chemin, dict(donnees), jeton))
        if echec_sur["etape"] and chemin.endswith(echec_sur["etape"]):
            raise HTTPException(status_code=502, detail="Meta : budget trop bas")
        return {"id": f"id{len(appels)}"}

    monkeypatch.setattr(cp, "_graph", faux_graph)
    return db, appels, echec_sur


CORPS = {"compte_id": "act_123", "page_id": "P1", "budget": "5000", "pays": "BF", "age_min": 18, "age_max": 50,
         "jours": 7, "whatsapp": "+226 70 00 00 01", "nom": "Test carrousel", "message": "Promo", "images": [None]}
USER = {"id": "u1", "client_id": "adm", "email": "admin@x"}


def test_creation_en_pause_dans_l_ordre(env):
    db, appels, _ = env
    c = lancer(db.carrousel_campagnes.find_one({"id": "camp1"}))
    res = lancer(cp.creer_publicite(db, USER, c, CORPS))
    assert [a[0] for a in appels] == ["act_123/campaigns", "act_123/adsets", "act_123/adcreatives", "act_123/ads"]
    camp, ens, crea, pub = [a[1] for a in appels]
    assert camp["status"] == ens["status"] == pub["status"] == "PAUSED" and camp["objective"] == "OUTCOME_ENGAGEMENT"
    assert ens["destination_type"] == "WHATSAPP" and ens["optimization_goal"] == "CONVERSATIONS" and ens["daily_budget"] == 5000
    assert json.loads(ens["promoted_object"]) == {"page_id": "P1", "whatsapp_phone_number": "+22670000001"} and "end_time" in ens
    assert len(json.loads(crea["object_story_spec"])["link_data"]["child_attachments"]) == 3     # carte à image non publique ignorée
    assert json.loads(pub["creative"]) == {"creative_id": res["creatif_meta"]}
    assert res["statut"] == "PAUSED" and res["gestionnaire"].startswith("https://adsmanager.facebook.com/")
    trace = lancer(db.carrousel_campagnes.find_one({"id": "camp1"}))["publicites_facebook"]
    assert len(trace) == 1 and "JETON" not in json.dumps(trace)                                   # jamais de jeton sur l'envoi


def test_echec_supprime_la_campagne_creee(env):
    db, appels, echec = env
    echec["etape"] = "/adcreatives"
    c = lancer(db.carrousel_campagnes.find_one({"id": "camp1"}))
    with pytest.raises(HTTPException) as e:
        lancer(cp.creer_publicite(db, USER, c, CORPS))
    assert e.value.status_code == 502 and "budget trop bas" in e.value.detail
    assert appels[-1][0].startswith("id1") and appels[-1][1] == {"status": "DELETED"}           # campagne supprimée (rien d'orphelin)
    assert "publicites_facebook" not in lancer(db.carrousel_campagnes.find_one({"id": "camp1"}))


def test_refus_comptes_et_pages_inconnus(env):
    db, appels, _ = env
    c = lancer(db.carrousel_campagnes.find_one({"id": "camp1"}))
    for modif, code in [({"compte_id": "act_999"}, 404), ({"page_id": "PX"}, 404), ({"budget": "0"}, 422), ({"pays": ""}, 422)]:
        with pytest.raises(HTTPException) as e:
            lancer(cp.creer_publicite(db, USER, c, {**CORPS, **modif}))
        assert e.value.status_code == code
    assert appels == []                                                                         # rien n'est envoyé à Meta
    with pytest.raises(HTTPException) as e:                                                     # Meta non connecté
        lancer(cp.creer_publicite(db, {"id": "autre"}, c, CORPS))
    assert e.value.status_code == 400


# --- Lot 194 : message prérempli et réponse automatique de Liluvine ---------------------------------------------------
def test_message_prerempli_et_reponse():
    assert cp.message_prerempli("  Bonjour,   je suis  intéressé ", True, "PUB-AB12") == "Bonjour, je suis intéressé (réf. PUB-AB12)"
    assert cp.message_prerempli("Bonjour", False, "PUB-AB12") == "Bonjour" and cp.message_prerempli("  ", True, "PUB-AB12") == ""
    assert len(cp.message_prerempli("x" * 500, False, "R")) == 200
    w = json.loads(cp.page_welcome_message("Bonjour (réf. PUB-AB12)"))
    assert w["text_format"]["customer_action_type"] == "autofill_message"
    assert w["text_format"]["message"]["autofill_message"]["content"] == "Bonjour (réf. PUB-AB12)"
    cartes = [{"name": "A"}, {"name": "B"}]
    assert "page_welcome_message" in cp.histoire_creative("P1", "m", cartes, "https://api.whatsapp.com/send", "Bonjour")["link_data"]
    assert "page_welcome_message" not in cp.histoire_creative("P1", "m", cartes, "https://api.whatsapp.com/send")["link_data"]
    assert cp.texte_reponse("Voici : {lien}", "https://s.test/p/abc") == "Voici : https://s.test/p/abc"
    assert cp.texte_reponse("Bonjour {lien}", "") == "Bonjour" and cp.texte_reponse(None, "x") == ""


CORPS_MSG = {**CORPS, "prerempli": "Bonjour, je veux en savoir plus", "avec_ref": True,
             "reponse_liluvine": "Merci ! Tout le catalogue : {lien}", "lien_presentation": "https://s.test/p/pub1"}


def test_creation_avec_message_prerempli_et_modele_liluvine(env):
    db, appels, _ = env
    c = lancer(db.carrousel_campagnes.find_one({"id": "camp1"}))
    res = lancer(cp.creer_publicite(db, USER, c, CORPS_MSG))
    crea = [a[1] for a in appels if a[0].endswith("/adcreatives")][0]
    ld = json.loads(crea["object_story_spec"])["link_data"]
    contenu = json.loads(ld["page_welcome_message"])["text_format"]["message"]["autofill_message"]["content"]
    assert contenu == res["prerempli"] and contenu.startswith("Bonjour, je veux en savoir plus (réf. PUB-") and res["prerempli_erreur"] == ""
    modele = lancer(db.liluvine_ad_templates.find_one({"id": res["modele_liluvine"]}))
    assert modele["trigger_text"] == contenu and modele["active"] is True                      # Liluvine répond à CE texte
    assert modele["response_text"] == "Merci ! Tout le catalogue : https://s.test/p/pub1" and modele["response_media_url"] == "https://x.test/a.jpg"


def test_message_refuse_par_meta_publicite_creee_sans(env, monkeypatch):
    db, appels, _ = env
    ancien = cp._graph

    async def graph_refuse(_db, chemin, jeton, donnees):
        if chemin.endswith("/adcreatives") and "page_welcome_message" in donnees.get("object_story_spec", ""):
            raise HTTPException(status_code=502, detail="Meta : page_welcome_message non pris en charge")
        return await ancien(_db, chemin, jeton, donnees)

    monkeypatch.setattr(cp, "_graph", graph_refuse)
    c = lancer(db.carrousel_campagnes.find_one({"id": "camp1"}))
    res = lancer(cp.creer_publicite(db, USER, c, CORPS_MSG))
    assert res["statut"] == "PAUSED" and res["prerempli"] == "" and "page_welcome_message" in res["prerempli_erreur"]
    assert res["modele_liluvine"] is None and lancer(db.liluvine_ad_templates.count_documents({})) == 0   # pas de réponse sans message prérempli
    creatifs = [a for a in appels if a[0].endswith("/adcreatives")]
    assert len(creatifs) == 1 and "page_welcome_message" not in creatifs[0][1]["object_story_spec"]       # créatif sans, une fois accepté


def test_sans_message_prerempli_rien_de_plus(env):
    db, appels, _ = env
    c = lancer(db.carrousel_campagnes.find_one({"id": "camp1"}))
    res = lancer(cp.creer_publicite(db, USER, c, CORPS))               # corps du lot 193 : aucun message prérempli
    assert res["prerempli"] == "" and res["modele_liluvine"] is None and lancer(db.liluvine_ad_templates.count_documents({})) == 0
    assert "page_welcome_message" not in [a[1] for a in appels if a[0].endswith("/adcreatives")][0]["object_story_spec"]
