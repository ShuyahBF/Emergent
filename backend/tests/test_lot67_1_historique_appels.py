"""Lot 67.1 — Historique des appels automatiques de Liluvine : durées, coûts, synthèse par période.

Calcul des durées (mesure du serveur, durée Meta préférée), coût et arrondi (tranches de 6 s comme
Meta, minute entamée, seconde), coût figé au moment de l'appel, regroupement par jour / semaine /
mois / année (Africa/Ouagadougou = UTC), routes (droits, filtres, pagination, synthèse, CSV).
MongoDB simulé, API Graph factice, appel vocal simulé : aucun appel réseau.
Lancer : cd backend && python -m pytest tests/test_lot67_1_historique_appels.py -q
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.appel_proprietaire as ap  # noqa: E402
import routes.appels_wa as aw  # noqa: E402

PROPRIO = "22670999999"
CLIENT = "22670000001"
INSTANT = datetime(2026, 10, 6, 14, 5, tzinfo=timezone.utc)
# Réglages de base : ligne Standard + VIP, numéro du propriétaire, tarifs (100 FCFA la minute,
# 25 FCFA le message modèle, 10 FCFA les 1000 caractères de voix)
REGLAGES = {
    "_id": "global", "wa_phone_number_id": "PN-STANDARD", "wa_access_token": "jeton-factice",
    "wa_numeros": [{"id": "PN-VIP", "libelle": "Liluvine VIP", "telephone": "+226 73 88 49 99"}],
    "appel_proprio_numeros": "+226 70 99 99 99",
    "appel_proprio_tarif_appel_minute": 100, "appel_proprio_tarif_relais_modele": 25,
    "appel_proprio_tarif_tts_1000": 10,
}


def lancer(coro):
    """Exécute une coroutine dans une boucle neuve."""
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def env(monkeypatch):
    """Base simulée, horloge réglable, API Graph factice, appel vocal simulé avec mesures réglables."""
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot67_1"]
    lancer(db.settings.insert_one(dict(REGLAGES)))
    lancer(db.users.insert_one({"id": "sawali", "role": "superviseur", "phone": "+22671111111"}))
    horloge = {"t": INSTANT}
    monkeypatch.setattr(ap, "_maintenant", lambda: horloge["t"])
    monkeypatch.delenv("NUMERO_APPEL_PROPRIETAIRE", raising=False)
    permission = {"status": "temporary"}
    # Résultat et mesures du prochain appel simulé
    prochain = {"resultat": "décroché", "mesures": {"voix": "openai", "tts_caracteres": 500,
                                                    "sonnerie_s": 7, "conversation_s": 56}}

    async def faux_post(s, numero_id, chemin, corps):
        return {"ok": True, "donnees": {"messages": [{"id": "wamid.1"}]}, "erreur": None}

    async def faux_get(s, numero_id, chemin, params):
        return {"ok": True, "donnees": {"permission": dict(permission), "actions": [
            {"action_name": "start_call", "can_perform_action": permission["status"] != "no_permission"},
            {"action_name": "send_call_permission_request", "can_perform_action": True}]}, "erreur": None}

    compteur = {"n": 0}

    async def faux_appel(db_, s, cfg, *, numero_id, ligne_cle, proprio, texte_voix, alerte):
        # Appel simulé : ligne de journal comme le vrai, résultat et mesures choisis par le test
        compteur["n"] += 1
        call_id = f"wacid.{compteur['n']}"
        await db_.wa_appels.insert_one({"id": call_id, "direction": "sortant", "motif": ap.MOTIF,
                                        "telephone": proprio, "created_at": ap._maintenant().isoformat(),
                                        "resultat": prochain["resultat"], **alerte})
        return {"resultat": prochain["resultat"], "raison": None, "call_id": call_id,
                "mesures": dict(prochain["mesures"])}

    monkeypatch.setattr(ap, "_graph_post", faux_post)
    monkeypatch.setattr(ap, "_graph_get", faux_get)
    monkeypatch.setattr(ap, "appeler_et_parler", faux_appel)
    ap._verrous_clients.clear()
    ap._verrou_appel = None
    return {"db": db, "horloge": horloge, "permission": permission, "prochain": prochain}


def message(db, de=CLIENT, nom="Awa Kaboré"):
    """Traite un message reçu d'un client (comme le webhook, en attendant le résultat)."""
    return lancer(ap.traiter_message(db, chiffres=de, mtype="text", texte="Bonjour, ma commande ?",
                                     contact={"id": "c1", "name": nom, "client_id": "sawali"},
                                     recu_le=INSTANT.isoformat(), client_id="sawali"))


def historique(db):
    """Lignes de l'historique, de la plus ancienne à la plus récente."""
    return lancer(db[ap.COLLECTION_HISTORIQUE].find({}, {"_id": 0}).sort("created_at", 1).to_list(None))


# ---------------------------------------------------------------------------
# Durée facturée et coût
# ---------------------------------------------------------------------------

def test_arrondi_tranches_de_6_secondes_comme_meta():
    # Exemple de la documentation Meta : 56 s = 9,33 tranches → 10 tranches = 60 s
    assert ap.secondes_facturees(56) == 60
    assert ap.secondes_facturees(0) == 0 and ap.secondes_facturees(None) == 0 and ap.secondes_facturees(-3) == 0
    assert ap.secondes_facturees(1) == 6 and ap.secondes_facturees(6) == 6 and ap.secondes_facturees(7) == 12
    # Minute entamée / à la seconde
    assert ap.secondes_facturees(61, "minute") == 120 and ap.secondes_facturees(60, "minute") == 60
    assert ap.secondes_facturees(61, "seconde") == 61
    assert ap.secondes_facturees("abc") == 0


def test_tarif_par_defaut_et_lecture():
    t = ap.tarif_actuel({})
    assert t == {"minute": 0.0, "devise": "FCFA", "arrondi": "pulse6", "relais_modele": 0.0, "tts_1000": 0.0}
    t = ap.tarif_actuel({"appel_proprio_tarif_appel_minute": "12,5", "appel_proprio_tarif_devise": "usd",
                         "appel_proprio_tarif_arrondi": "inconnu"})
    assert t["minute"] == 12.5 and t["devise"] == "USD" and t["arrondi"] == "pulse6"


def test_calcul_du_cout():
    tarif = {"minute": 100, "arrondi": "pulse6", "relais_modele": 25, "tts_1000": 10}
    c = ap.calculer_cout(tarif, conversation_s=56, relais_modele=True, tts_caracteres=500, voix="openai")
    # 60 s facturées × 100/min = 100 ; modèle 25 ; 500 caractères × 10/1000 = 5
    assert c == {"secondes_facturees": 60, "cout_appel": 100.0, "cout_relais": 25.0, "cout_tts": 5.0,
                 "cout_total": 130.0}
    # Texte libre (pas de modèle), voix Google gratuite, minute entamée
    c = ap.calculer_cout({**tarif, "arrondi": "minute"}, conversation_s=61, relais_modele=False,
                         tts_caracteres=500, voix="google")
    assert c["cout_appel"] == 200.0 and c["cout_relais"] == 0 and c["cout_tts"] == 0 and c["cout_total"] == 200.0
    # Non décroché : aucune durée, aucun coût d'appel
    assert ap.calculer_cout(tarif, conversation_s=0, relais_modele=False, tts_caracteres=0, voix=None)["cout_total"] == 0


# ---------------------------------------------------------------------------
# Ligne d'historique écrite à chaque alerte
# ---------------------------------------------------------------------------

def test_ligne_historique_appel_decroche(env):
    db = env["db"]
    message(db)
    [h] = historique(db)
    assert h["created_at"] == INSTANT.isoformat() and h["client_nom"] == "Awa Kaboré (+22670000001)"
    assert h["client_telephone"] == CLIENT and h["destinataire"] == PROPRIO
    assert h["ligne_cle"] == "principal" and h["ligne_libelle"] == "Liluvine Standard"
    assert h["resultat"] == "décroché" and h["categorie"] == "decroche" and h["call_id"] == "wacid.1"
    assert h["sonnerie_s"] == 7 and h["conversation_s"] == 56 and h["duree_source"] == "serveur"
    # Relais en texte libre (pas de modèle déclaré) : pas de coût de relais
    assert h["relais_envoye"] is True and h["relais_mode"] == "texte" and h["relais_modele"] is None
    assert h["voix"] == "openai" and h["tts_caracteres"] == 500
    assert h["cout_appel"] == 100.0 and h["cout_relais"] == 0 and h["cout_tts"] == 5.0 and h["cout_total"] == 105.0
    assert h["tarif"]["minute"] == 100 and h["devise"] == "FCFA"


def test_relais_par_modele_compte(env):
    db = env["db"]
    lancer(db.settings.update_one({"_id": "global"}, {"$set": {"appel_proprio_modele": "alerte_support"}}))
    env["prochain"]["resultat"] = "sans réponse"
    env["prochain"]["mesures"] = {"voix": "google", "tts_caracteres": 90, "sonnerie_s": 30, "conversation_s": 0}
    message(db)
    [h] = historique(db)
    assert h["relais_mode"] == "modele" and h["relais_modele"] == "alerte_support"
    assert h["categorie"] == "sans_reponse" and h["sonnerie_s"] == 30
    # Sans réponse : seul le message modèle est payé ; voix Google gratuite
    assert h["cout_appel"] == 0 and h["cout_relais"] == 25.0 and h["cout_tts"] == 0 and h["cout_total"] == 25.0


def test_relais_seul_heures_calmes_et_autorisation(env):
    db = env["db"]
    lancer(db.settings.update_one({"_id": "global"}, {"$set": {
        "appel_proprio_calme_actif": True, "appel_proprio_calme_debut": "12:00", "appel_proprio_calme_fin": "15:00"}}))
    message(db)
    [h] = historique(db)
    assert h["categorie"] == "relais_seul" and h["resultat"] == "relais seul" and "heures calmes" in h["raison"]
    assert h["call_id"] is None and h["conversation_s"] == 0 and h["cout_total"] == 0
    # Autorisation d'appel en attente : relais seul aussi
    lancer(db.settings.update_one({"_id": "global"}, {"$set": {"appel_proprio_calme_actif": False}}))
    env["permission"]["status"] = "no_permission"
    message(db, de="22670000002", nom="Issa")
    h2 = historique(db)[-1]
    assert h2["categorie"] == "relais_seul" and "autorisation" in h2["raison"]


def test_cout_fige_au_moment_de_l_appel_et_duree_meta(env):
    """La durée Meta (webhook terminate) remplace la mesure du serveur ; le coût est recalculé
    avec le tarif de l'appel, même si le tarif a changé entre-temps."""
    db = env["db"]
    env["prochain"]["mesures"] = {"voix": "openai", "tts_caracteres": 0, "sonnerie_s": 5, "conversation_s": 20}
    message(db)
    assert historique(db)[0]["cout_appel"] == 40.0          # 24 s facturées × 100/min
    # Le propriétaire passe le tarif à 1000 FCFA la minute
    lancer(db.settings.update_one({"_id": "global"}, {"$set": {"appel_proprio_tarif_appel_minute": 1000}}))
    # Webhook terminate de Meta : 56 s de conversation
    lancer(aw.traiter_webhook_appels(db, {"calls": [{"id": "wacid.1", "event": "terminate", "status": "COMPLETED",
                                                      "duration": 56, "start_time": "1791295500",
                                                      "end_time": "1791295556"}]}))
    h = historique(db)[0]
    assert h["conversation_s"] == 56 and h["duree_source"] == "meta"
    assert h["cout_appel"] == 100.0 and h["tarif"]["minute"] == 100   # ancien tarif conservé
    # Un nouvel appel (plus tard) utilise le nouveau tarif
    env["horloge"]["t"] = INSTANT + timedelta(hours=2)
    message(db)
    assert historique(db)[-1]["cout_appel"] == 400.0         # 24 s × 1000/min


def test_duree_meta_arrivee_avant_la_ligne(env, monkeypatch):
    """Le webhook terminate arrive avant l'écriture de la ligne : la durée Meta est lue au journal."""
    db = env["db"]
    appel_simule = ap.appeler_et_parler

    async def appel_puis_webhook(*a, **k):
        res = await appel_simule(*a, **k)
        await aw.traiter_webhook_appels(db, {"calls": [{"id": res["call_id"], "event": "terminate",
                                                          "status": "COMPLETED", "duration": 13}]})
        return res
    monkeypatch.setattr(ap, "appeler_et_parler", appel_puis_webhook)
    message(db)
    h = historique(db)[0]
    assert h["conversation_s"] == 13 and h["duree_source"] == "meta" and h["secondes_facturees"] == 18
    assert lancer(ap.noter_duree_meta(db, "inconnu", 10)) is False


def test_mesures_renvoyees_meme_en_echec(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot67_1b"]
    monkeypatch.setattr(ap, "moteur_disponible", lambda: (False, "aiortc indisponible : test"))
    r = lancer(ap.appeler_et_parler(db, {}, ap.reglages({}), numero_id="PN", ligne_cle="principal", proprio=PROPRIO,
                                    texte_voix="Bonjour", alerte={"alerte_client_telephone": CLIENT}))
    assert r["resultat"] == "échec" and r["mesures"]["conversation_s"] == 0 and r["mesures"]["voix"] is None
    assert ap.categorie_resultat("échec") == "echec" and ap.categorie_resultat("refusé") == "sans_reponse"
    assert ap.categorie_resultat(None) == "relais_seul"


# ---------------------------------------------------------------------------
# Regroupement par période (UTC = heure de Ouagadougou)
# ---------------------------------------------------------------------------

def _doc(iso, categorie="decroche", conversation=30, cout=50.0, devise="FCFA"):
    """Ligne d'historique minimale pour la synthèse."""
    return {"created_at": iso, "categorie": categorie, "conversation_s": conversation, "sonnerie_s": 5,
            "cout_total": cout, "devise": devise}


def test_periodes_jour_semaine_mois_annee():
    a = lambda *x: datetime(*x, tzinfo=timezone.utc)  # noqa: E731
    # Fin de journée / début de mois
    assert ap.cle_periode(a(2026, 9, 30, 23, 59, 59), "jour")[0] == "2026-09-30"
    assert ap.cle_periode(a(2026, 10, 1, 0, 0, 0), "jour") == ("2026-10-01", "01/10/2026")
    assert ap.cle_periode(a(2026, 9, 30, 23, 59), "mois")[0] == "2026-09"
    assert ap.cle_periode(a(2026, 10, 1, 0, 0), "mois") == ("2026-10", "Octobre 2026")
    # Semaine du lundi : dimanche 04/10 et lundi 05/10/2026 dans deux semaines différentes
    assert ap.cle_periode(a(2026, 10, 4, 23, 59), "semaine")[0] == "2026-09-28"
    assert ap.cle_periode(a(2026, 10, 5, 0, 0), "semaine") == ("2026-10-05", "Semaine du 05/10/2026")
    # Changement d'année : même semaine (lundi 29/12/2025), années différentes
    assert ap.cle_periode(a(2025, 12, 31, 12, 0), "semaine")[0] == ap.cle_periode(a(2026, 1, 1, 12, 0), "semaine")[0]
    assert ap.cle_periode(a(2025, 12, 31, 23, 59), "annee")[0] == "2025"
    assert ap.cle_periode(a(2026, 1, 1, 0, 0), "annee")[0] == "2026"


def test_synthese_cumuls():
    docs = [_doc("2026-09-30T23:59:59+00:00", conversation=40, cout=70),
            _doc("2026-10-01T00:00:00+00:00", conversation=20, cout=40),
            _doc("2026-10-01T08:00:00+00:00", "sans_reponse", 0, 0),
            _doc("2026-10-01T09:00:00+00:00", "echec", 0, 0),
            _doc("2026-10-02T09:00:00+00:00", "relais_seul", 0, 25)]
    jour = ap.synthese_par_periode(docs, "jour")
    assert [li["cle"] for li in jour["lignes"]] == ["2026-10-02", "2026-10-01", "2026-09-30"]
    j1 = jour["lignes"][1]
    assert (j1["appels"], j1["decroches"], j1["sans_reponse"], j1["echecs"]) == (3, 1, 1, 1)
    t = jour["totaux"]
    assert t["alertes"] == 5 and t["appels"] == 4 and t["relais_seuls"] == 1
    assert t["duree_totale_s"] == 60 and t["duree_moyenne_s"] == 30 and t["cout_total"] == 135 and t["devise"] == "FCFA"
    mois = ap.synthese_par_periode(docs, "mois")
    assert [(li["cle"], li["alertes"]) for li in mois["lignes"]] == [("2026-10", 4), ("2026-09", 1)]
    # Devises mélangées (changement de devise) : cumul par devise, pas de total unique
    m = ap.totaliser(docs + [_doc("2026-10-03T00:00:00+00:00", cout=1.5, devise="USD")])
    assert m["devise"] == "mixte" and m["cout_total"] is None and m["couts"] == {"FCFA": 135, "USD": 1.5}
    assert ap.totaliser([])["cout_total"] == 0 and ap.totaliser([])["duree_moyenne_s"] == 0


def test_filtre_dates_incluses():
    f = ap.filtre_historique("2026-10-01", "2026-10-06", "awa", "decroche")
    assert f["created_at"] == {"$gte": "2026-10-01T00:00:00+00:00", "$lt": "2026-10-07T00:00:00+00:00"}
    assert f["categorie"] == "decroche" and f["$or"][0]["client_nom"]["$options"] == "i"
    with pytest.raises(ValueError):
        ap.filtre_historique("06/10/2026", None)
    with pytest.raises(ValueError):
        ap.filtre_historique(None, None, None, "inconnu")


# ---------------------------------------------------------------------------
# Routes : droits, réglages des tarifs, historique, synthèse, CSV
# ---------------------------------------------------------------------------

def _client(db):
    """Application de test : « sup » (superviseur) et « client » (sans droit)."""
    utilisateurs = {"sup": {"id": "sawali", "role": "superviseur", "client_id": "sawali", "full_name": "Sup"},
                    "client": {"id": "x", "role": "client", "client_id": "x"}}

    async def utilisateur(request: Request):
        uid = request.headers.get("X-User")
        if uid not in utilisateurs:
            raise HTTPException(status_code=401)
        return utilisateurs[uid]

    api = APIRouter(prefix="/api")
    ap.setup_appel_proprietaire_routes(db=db, api=api, get_current_user=utilisateur)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app)


def test_routes_historique_synthese_csv(env):
    db = env["db"]
    c = _client(db)
    message(db)                                              # 06/10 14:05 : décroché
    env["horloge"]["t"] = INSTANT + timedelta(days=1)
    env["prochain"]["resultat"] = "sans réponse"
    env["prochain"]["mesures"] = {"voix": "openai", "tts_caracteres": 0, "sonnerie_s": 30, "conversation_s": 0}
    message(db, de="22670000002", nom="Issa Ouédraogo")      # 07/10 : sans réponse
    base = "/api/admin/appel-proprietaire"
    sup = {"X-User": "sup"}
    # Droits : réservé aux administrateurs et superviseurs
    for chemin in ("/historique", "/historique.csv", "/synthese"):
        assert c.get(base + chemin, headers={"X-User": "client"}).status_code == 403
        assert c.get(base + chemin).status_code == 401
    r = c.get(base + "/historique", headers=sup).json()
    assert r["total"] == 2 and r["items"][0]["client_nom"].startswith("Issa")       # plus récent d'abord
    assert r["totaux"]["appels"] == 2 and r["totaux"]["decroches"] == 1 and r["totaux"]["cout_total"] == 105.0
    # Filtres et pagination
    assert c.get(base + "/historique", params={"client": "awa"}, headers=sup).json()["total"] == 1
    assert c.get(base + "/historique", params={"client": "70000002"}, headers=sup).json()["total"] == 1
    assert c.get(base + "/historique", params={"resultat": "sans_reponse"}, headers=sup).json()["total"] == 1
    assert c.get(base + "/historique", params={"du": "2026-10-07", "au": "2026-10-07"}, headers=sup).json()["total"] == 1
    p2 = c.get(base + "/historique", params={"par_page": 1, "page": 2}, headers=sup).json()
    assert p2["pages"] == 2 and len(p2["items"]) == 1 and p2["items"][0]["client_nom"].startswith("Awa")
    assert c.get(base + "/historique", params={"du": "07-10-2026"}, headers=sup).status_code == 422
    # Synthèse : par jour (2 lignes) et par mois (1 ligne) ; dates par défaut
    s = c.get(base + "/synthese", params={"periode": "jour", "du": "2026-10-01", "au": "2026-10-31"}, headers=sup).json()
    assert [li["cle"] for li in s["lignes"]] == ["2026-10-07", "2026-10-06"] and s["totaux"]["appels"] == 2
    s = c.get(base + "/synthese", params={"periode": "mois"}, headers=sup).json()
    assert [li["cle"] for li in s["lignes"]] == ["2026-10"] and s["totaux"]["duree_totale_s"] == 56
    assert c.get(base + "/synthese", params={"periode": "siecle"}, headers=sup).status_code == 422
    # Export CSV : BOM, séparateur « ; », une ligne par appel
    r = c.get(base + "/historique.csv", headers=sup)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    texte = r.content.decode("utf-8")
    assert texte.startswith("﻿Date/Heure;Client;")
    lignes = texte.strip().splitlines()
    assert len(lignes) == 3 and "06/10/2026 14:05:00" in lignes[2] and ";105,0;FCFA;" in lignes[2]
    assert "00:00:56" in lignes[2] and ";écrit;" in lignes[2]


def test_reglages_des_tarifs(env):
    db = env["db"]
    c = _client(db)
    base = "/api/admin/appel-proprietaire"
    sup = {"X-User": "sup"}
    assert c.put(base, json={"appel_proprio_tarif_devise": "EUR"}, headers=sup).status_code == 422
    assert c.put(base, json={"appel_proprio_tarif_arrondi": "heure"}, headers=sup).status_code == 422
    assert c.put(base, json={"appel_proprio_tarif_appel_minute": "abc"}, headers=sup).status_code == 422
    assert c.put(base, json={"appel_proprio_tarif_appel_minute": "12,5", "appel_proprio_tarif_devise": "usd",
                             "appel_proprio_tarif_arrondi": "minute", "appel_proprio_tarif_relais_modele": "0,03",
                             "appel_proprio_tarif_tts_1000": 0.015}, headers=sup).status_code == 200
    r = c.get(base, headers=sup).json()
    assert r["tarif"] == {"minute": 12.5, "devise": "USD", "arrondi": "minute", "relais_modele": 0.03, "tts_1000": 0.015}
    assert r["reglages"]["appel_proprio_tarif_appel_minute"] == 12.5
