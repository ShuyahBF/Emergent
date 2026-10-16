"""Lot 210 — rappels d'échéance des produits et services d'un client : calcul de l'échéance, paliers, reconduction,
décisionnaires, jamais deux fois le même rappel, interrupteur général, simulation.
Lancer : cd backend && python -m pytest tests/test_lot210_rappels_offre_client.py -q
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.offre_client as oc  # noqa: E402
import routes.offre_client_rappels as rr  # noqa: E402


def lancer(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def ligne(**kw):
    base = {"id": "L1", "type": "service", "nom": "Contrôle à distance", "actif": True, "date_debut": "2026-10-01",
            "duree_jours": 30, "rappel_jours": [3], "reconduction": True, "alerte_active": True, "rappels_envoyes": []}
    return oc.normaliser_offre([{**base, **kw}])[0]


# ---------------------------------------------------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------------------------------------------------
def test_normalisation_des_champs_d_echeance():
    l = ligne(date_debut="2026-13-45", duree_jours="abc", rappel_jours="7, 3 ; 3 ; 400 ; x", alerte_active="oui")
    assert l["date_debut"] == "" and l["duree_jours"] == 0
    assert l["rappel_jours"] == [7, 3]                       # sans doublon, hors bornes écartés, du plus lointain au plus proche
    assert l["alerte_active"] is False                       # seule la valeur vraie autorise l'alerte
    assert l["reconduction"] is True                         # reconduction par défaut


def test_copie_vers_un_autre_client_remet_a_zero_le_suivi():
    src = [ligne(rappels_envoyes=["2026-10-31|3"])]
    copie, nb = oc.fusionner_offre([], src, "remplacer")
    assert nb == 1 and copie[0]["date_debut"] == "" and copie[0]["rappels_envoyes"] == []
    assert copie[0]["duree_jours"] == 30 and copie[0]["rappel_jours"] == [3]     # la configuration, elle, est reprise


# ---------------------------------------------------------------------------------------------------------------------
# Échéance et paliers
# ---------------------------------------------------------------------------------------------------------------------
def test_echeance_debut_plus_duree_puis_reconduction():
    assert rr.echeance_ligne(ligne(), date(2026, 10, 16)) == date(2026, 10, 31)
    # Avec reconduction, la période suivante commence à l'échéance : 31/10 + 30 j = 30/11
    assert rr.echeance_ligne(ligne(), date(2026, 11, 5)) == date(2026, 11, 30)
    # Sans reconduction, l'échéance passée reste passée
    assert rr.echeance_ligne(ligne(reconduction=False), date(2026, 11, 5)) == date(2026, 10, 31)
    # Sans début ou sans durée : pas d'échéance
    assert rr.echeance_ligne(ligne(date_debut=""), date(2026, 10, 16)) is None
    assert rr.echeance_ligne(ligne(duree_jours=0), date(2026, 10, 16)) is None


def test_palier_du_jour_exact():
    # Échéance le 31/10, rappel 3 j avant = le 28/10
    assert rr.a_rappeler(ligne(), date(2026, 10, 28))["jours"] == 3
    assert rr.a_rappeler(ligne(), date(2026, 10, 27)) is None
    assert rr.a_rappeler(ligne(), date(2026, 10, 15)) is None


def test_rattrapage_un_jour_apres_un_envoi_rate():
    d = rr.a_rappeler(ligne(), date(2026, 10, 29))            # la veille (28/10) n'a rien envoyé
    assert d and d["jours"] == 2 and d["cles"] == ["2026-10-31|3"]
    assert rr.a_rappeler(ligne(), date(2026, 10, 30)) is None  # au-delà d'un jour de rattrapage : plus de rappel


def test_jamais_deux_fois_le_meme_rappel():
    l = ligne(rappels_envoyes=["2026-10-31|3"])
    assert rr.a_rappeler(l, date(2026, 10, 28)) is None
    assert rr.a_rappeler(l, date(2026, 10, 29)) is None
    # Après reconduction, l'échéance change : un nouveau rappel est possible
    assert rr.a_rappeler(l, date(2026, 11, 27))["jours"] == 3


def test_conditions_pour_etre_rappele():
    jour = date(2026, 10, 28)
    assert rr.a_rappeler(ligne(alerte_active=False), jour) is None      # alerte non autorisée
    assert rr.a_rappeler(ligne(actif=False), jour) is None              # ligne inactive
    assert rr.a_rappeler(ligne(rappel_jours=[]), jour) is None          # aucun palier réglé


def test_plusieurs_paliers_un_seul_message():
    l = ligne(rappel_jours=[7, 3])
    assert rr.a_rappeler(l, date(2026, 10, 24))["paliers"] == [7]
    assert rr.a_rappeler(l, date(2026, 10, 28))["paliers"] == [3]


# ---------------------------------------------------------------------------------------------------------------------
# Textes
# ---------------------------------------------------------------------------------------------------------------------
def test_phrases_et_variables_du_modele():
    assert rr.phrase_echeance("SAWALI CRM", 3, date(2026, 10, 31)) == "SAWALI CRM : dans 3 jours (le 31/10/2026)"
    assert rr.phrase_echeance("SAWALI CRM", 0, date(2026, 10, 31)).startswith("SAWALI CRM : aujourd'hui")
    v = rr.variables_modele("Awa", "Pharmacie X", ["A : dans 3 jours", "B : demain"])
    assert v == ["Awa", "Pharmacie X", "A : dans 3 jours ; B : demain"]    # une seule ligne : WhatsApp refuse les retours à la ligne
    assert "\n" not in "".join(rr.variables_modele("A\nB", "C", ["x\ny"]))
    txt = rr.texte_message("", "Awa", "Pharmacie X", ["A", "B"])
    assert "Awa" in txt and "• A" in txt and "• B" in txt


def test_reglages_desactives_par_defaut():
    assert rr.reglages({})["actif"] is False and rr.reglages({})["langue"] == "fr"


# ---------------------------------------------------------------------------------------------------------------------
# Passage de Liluvine (MongoDB simulé, envoi simulé)
# ---------------------------------------------------------------------------------------------------------------------
MAINTENANT = datetime(2026, 10, 28, 7, 30, tzinfo=timezone.utc)


def base(actif=True, decideurs=True):
    db = mongomock_motor.AsyncMongoMockClient()["t"]
    lancer(db.settings.insert_one({"_id": "global", "offre_rappel_actif": actif}))
    lancer(db.users.insert_many([
        {"id": "C1", "company": "Pharmacie X", "offre_client": [ligne(), ligne(id="L2", nom="Autre", alerte_active=False)]},
        {"id": "C2", "company": "Sans alerte", "offre_client": [ligne(alerte_active=False)]},
    ]))
    if decideurs:
        lancer(db.directory_contacts.insert_many([
            {"client_id": "C1", "name": "Awa", "whatsapp": "+226 70 00 00 01", "is_decision_maker": True},
            {"client_id": "C1", "name": "Moussa", "phone": "22670000002", "is_decision_maker": True},
            {"client_id": "C1", "name": "Simple contact", "whatsapp": "22670000003", "is_decision_maker": False},
        ]))
    return db


def faux_envoi(journal, ok=True):
    async def envoyer(regl, tel, nom, client, liste):
        journal.append((tel, nom, client, liste))
        return {"ok": ok, "erreur": None if ok else "hors fenêtre"}
    return envoyer


def test_tous_les_decisionnaires_sont_prevenus_et_seulement_eux():
    db, envois = base(), []
    bilan = lancer(rr.rappeler(db, MAINTENANT, faux_envoi(envois)))
    assert bilan["envoyes"] == 2 and bilan["echecs"] == 0 and bilan["clients"] == 1
    assert sorted(e[0] for e in envois) == ["22670000001", "22670000002"]         # numéros réduits aux chiffres
    assert all(e[2] == "Pharmacie X" and len(e[3]) == 1 for e in envois)            # une seule ligne : l'autre n'a pas d'alerte


def test_le_rappel_n_est_pas_renvoye_le_lendemain():
    db, envois = base(), []
    lancer(rr.rappeler(db, MAINTENANT, faux_envoi(envois)))
    lancer(rr.rappeler(db, MAINTENANT.replace(day=29), faux_envoi(envois)))
    assert len(envois) == 2                                                          # rien de plus le 29/10 (rattrapage inutile)


def test_envoi_rate_reessaye_le_lendemain():
    db, envois = base(), []
    b1 = lancer(rr.rappeler(db, MAINTENANT, faux_envoi(envois, ok=False)))
    assert b1["envoyes"] == 0 and b1["echecs"] == 2
    b2 = lancer(rr.rappeler(db, MAINTENANT.replace(day=29), faux_envoi(envois, ok=True)))
    assert b2["envoyes"] == 2                                                        # rattrapage d'un jour


def test_interrupteur_general_eteint_rien_ne_part():
    db, envois = base(actif=False), []
    bilan = lancer(rr.rappeler(db, MAINTENANT, faux_envoi(envois)))
    assert envois == [] and bilan["actif"] is False


def test_simulation_n_envoie_ni_ne_marque_rien():
    db, envois = base(actif=False), []
    bilan = lancer(rr.rappeler(db, MAINTENANT, faux_envoi(envois), simuler=True))
    assert envois == [] and bilan["messages"] == 2 and bilan["details"][0]["destinataires"][0]["ok"] is None
    u = lancer(db.users.find_one({"id": "C1"}))
    assert u["offre_client"][0]["rappels_envoyes"] == []


def test_client_sans_decisionnaire_est_signale_et_reessaye():
    db, envois = base(decideurs=False), []
    bilan = lancer(rr.rappeler(db, MAINTENANT, faux_envoi(envois)))
    assert bilan["sans_decisionnaire"] == 1 and envois == []
    assert lancer(db.users.find_one({"id": "C1"}))["offre_client"][0]["rappels_envoyes"] == []   # rien n'est marqué : réessayé


def test_la_tache_ne_leve_jamais():
    class Casse:
        settings = None
    bilan = lancer(rr.rappeler(Casse(), MAINTENANT, faux_envoi([])))
    assert "erreur" in bilan


# ---------------------------------------------------------------------------------------------------------------------
# Lot 210.1 — fin de mois calendaire
# ---------------------------------------------------------------------------------------------------------------------
def test_fin_de_mois_calendaire():
    l = ligne(fin_de_mois=True, duree_jours=0, date_debut="")
    assert rr.echeance_ligne(l, date(2026, 10, 16)) == date(2026, 10, 31)       # mois de 31 jours
    assert rr.echeance_ligne(l, date(2026, 11, 2)) == date(2026, 11, 30)        # le mois suivant : reconduction mensuelle
    assert rr.echeance_ligne(l, date(2028, 2, 10)) == date(2028, 2, 29)         # année bissextile
    assert rr.echeance_ligne(l, date(2027, 2, 10)) == date(2027, 2, 28)
    # Sans reconduction, il faut une date de début ; l'échéance passée reste passée
    assert rr.echeance_ligne(ligne(fin_de_mois=True, reconduction=False, date_debut=""), date(2026, 10, 16)) is None
    assert rr.echeance_ligne(ligne(fin_de_mois=True, reconduction=False, date_debut="2026-09-10"), date(2026, 10, 16)) == date(2026, 9, 30)


def test_rappel_trois_jours_avant_la_fin_du_mois():
    l = ligne(fin_de_mois=True, duree_jours=0, date_debut="", rappel_jours=[3])
    assert rr.a_rappeler(l, date(2026, 10, 28))["jours"] == 3                   # 28/10 pour une échéance au 31/10
    assert rr.a_rappeler(l, date(2026, 11, 27))["jours"] == 3                   # 27/11 pour le 30/11
    assert rr.a_rappeler(l, date(2026, 10, 27)) is None
    # Le suivi est par échéance : le rappel d'octobre n'empêche pas celui de novembre
    envoye = ligne(fin_de_mois=True, duree_jours=0, date_debut="", rappel_jours=[3], rappels_envoyes=["2026-10-31|3"])
    assert rr.a_rappeler(envoye, date(2026, 10, 28)) is None
    assert rr.a_rappeler(envoye, date(2026, 11, 27))["cles"] == ["2026-11-30|3"]


def test_fin_de_mois_normalisee_et_copiee():
    assert ligne(fin_de_mois=True)["fin_de_mois"] is True
    assert ligne(fin_de_mois="oui")["fin_de_mois"] is False
    copie, _ = oc.fusionner_offre([], [ligne(fin_de_mois=True)], "remplacer")
    assert copie[0]["fin_de_mois"] is True


# ---------------------------------------------------------------------------------------------------------------------
# Lot 210.2 — message paramétrable et modèle Meta associé
# ---------------------------------------------------------------------------------------------------------------------
def test_corps_du_modele_deduit_du_texte_libre():
    corps = rr.corps_modele("Bonjour {contact}, pour {client} : {liste}. Merci de renouveler.")
    assert corps == "Bonjour {{1}}, pour {{2}} : {{3}}. Merci de renouveler."
    assert "{{" in rr.corps_modele("")                                       # texte par défaut
    assert rr.verifier_message("") is None and rr.verifier_message(rr.MESSAGE_DEFAUT) is None   # le texte par défaut est valable chez Meta


def test_regles_meta_sur_le_texte():
    assert "{liste}" in rr.verifier_message("Bonjour {contact}, votre offre expire bientôt.")           # {liste} obligatoire
    assert "inconnue" in rr.verifier_message("Bonjour {contact}, {produit} : {liste} merci").lower()    # variable inconnue
    assert rr.verifier_message("{contact}, voici {liste} merci") is not None                            # variable au tout début
    assert rr.verifier_message("Bonjour, voici {liste}") is not None                                    # variable à la toute fin
    assert rr.verifier_message("Bonjour {contact}{client} voici {liste} merci") is not None             # deux variables collées
    assert rr.verifier_message("Bonjour {contact}, voici {liste} merci.") is None


def test_definition_envoyee_a_meta():
    d = rr.definition_modele("rappel_echeance_produits", "fr", "")
    assert d["name"] == "rappel_echeance_produits" and d["language"] == "fr" and d["category"] == "UTILITY"
    corps = d["components"][0]
    assert corps["type"] == "BODY" and corps["text"] == rr.corps_modele("")
    assert len(corps["example"]["body_text"][0]) == 3                          # un exemple par variable (exigé par Meta)
    assert rr.RE_NOM_MODELE.match("rappel_echeance_produits") and not rr.RE_NOM_MODELE.match("Rappel-1")


def test_hors_fenetre_modele_dans_la_fenetre_texte_libre(monkeypatch):
    # Faux module « server » : on observe quel canal est utilisé
    import types
    from datetime import timedelta
    envois = []

    async def texte(to, message, **kw):
        envois.append(("texte", to)); return {"ok": True}

    async def modele(to, nom, langue, composants):
        envois.append(("modele", to, nom, [p["text"] for p in composants[0]["parameters"]])); return {"ok": True}

    dernier = {"v": None}

    async def dernier_entrant(scope, **kw):
        return dernier["v"]

    faux = types.SimpleNamespace(_wa_send_text=texte, _wa_send_template=modele, _wa_last_inbound_iso=dernier_entrant)
    monkeypatch.setitem(sys.modules, "server", faux)
    regl = {"actif": True, "modele": "rappel_x", "langue": "fr", "message": rr.MESSAGE_DEFAUT}

    # Le décisionnaire n'a jamais écrit : hors fenêtre → modèle Meta
    r = lancer(rr.envoyer_whatsapp(regl, "22670000001", "Awa", "Pharmacie X", ["A : demain"]))
    assert r["ok"] and r["canal"] == "modèle Meta" and envois[-1][0] == "modele" and envois[-1][3][0] == "Awa"
    # Il a écrit il y a 2 h : fenêtre ouverte → texte libre
    dernier["v"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    r = lancer(rr.envoyer_whatsapp(regl, "22670000001", "Awa", "Pharmacie X", ["A : demain"]))
    assert r["canal"] == "texte libre" and envois[-1][0] == "texte"
    # Il a écrit il y a 30 h : hors fenêtre → modèle
    dernier["v"] = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    assert lancer(rr.envoyer_whatsapp(regl, "22670000001", "Awa", "X", ["A"]))["canal"] == "modèle Meta"
    # Sans modèle réglé et hors fenêtre : texte libre tenté, l'erreur explique quoi faire
    async def refus(to, message, **kw):
        return {"ok": False, "error": "Re-engagement message"}
    faux._wa_send_text = refus
    r = lancer(rr.envoyer_whatsapp({**regl, "modele": ""}, "22670000001", "Awa", "X", ["A"]))
    assert not r["ok"] and "modèle Meta" in r["erreur"]


def test_routes_modele_et_reglages_valides():
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    db = mongomock_motor.AsyncMongoMockClient()["t2"]
    app, api = FastAPI(), APIRouter(prefix="/api")
    rr.setup_offre_client_rappels_routes(db=db, api=api, get_current_admin=lambda: {"role": "admin"})
    app.include_router(api)
    c = TestClient(app)
    # Texte invalide refusé avec un message clair
    r = c.put("/api/admin/offre-client/rappels", json={"actif": False, "modele": "", "langue": "fr", "message": "Bonjour sans liste"})
    assert r.status_code == 422 and "{liste}" in r.json()["detail"]
    r = c.put("/api/admin/offre-client/rappels", json={"actif": False, "modele": "Nom Invalide", "langue": "fr", "message": ""})
    assert r.status_code == 422
    # Réglages valides : aperçu et corps du modèle renvoyés
    r = c.put("/api/admin/offre-client/rappels", json={"actif": True, "modele": "rappel_x", "langue": "fr",
                                                       "message": "Bonjour {contact}, pour {client} : {liste} à renouveler."})
    assert r.status_code == 200 and r.json()["corps_modele"] == "Bonjour {{1}}, pour {{2}} : {{3}} à renouveler."
    assert "Awa" in r.json()["apercu"]
    # Sans WhatsApp configuré, la création du modèle est refusée clairement (rien n'est envoyé à Meta)
    r = c.post("/api/admin/offre-client/rappels/modele")
    assert r.status_code == 400 and "WhatsApp non configuré" in r.json()["detail"]
