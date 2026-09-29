"""Lot 36 — Commande WhatsApp « !formulaire » (Liluvine).

Parcours complet avec WhatsApp, IA et PawaPay simulés (mongomock-motor) :
document reçu → analyse → formulaire privé « FORM_<numéro>_<date> » → tarif selon le
type de client + lien de paiement → paiement confirmé → mise en ligne → liens cryptés
(saisie par n'importe qui, réponses en privé, CSV) ; refus avec motif ; expiration.
Lancer : cd backend && python -m pytest tests/test_liluvine_formulaire.py -q
"""
from __future__ import annotations

import asyncio
import re
import sys
import types
from datetime import datetime, timedelta, timezone
from itertools import count
from pathlib import Path

import pytest

pytest.importorskip("mongomock_motor")
jwt = pytest.importorskip("jwt")
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import routes.liluvine_formulaire as lf  # noqa: E402

SECRET = "secret-de-test-assez-long-pour-hs256-0123456789"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
STRUCTURE = {"title": "Fiche de renseignement", "description": "", "pages": [{"id": "p1", "title": "Questions", "fields": [
    {"id": "q1", "type": "boolean", "label": "Des grossistes sans factures ?", "required": False, "col_span": 4},
    {"id": "q2", "type": "textarea", "label": "Lesquels ?", "required": False, "col_span": 8},
    {"id": "q3", "type": "table", "label": "Personnel", "columns": [{"key": "nom", "label": "Nom", "type": "text"}]}]}]}


@pytest.fixture()
def env():
    db = AsyncMongoMockClient()["sawali_lil"]
    envoyes, sms = [], []
    analyse = {"erreur": None, "panne": False}
    wa = {"ok": True}                                   # lot 37 : WhatsApp peut refuser (fenêtre fermée)
    n = count(1)

    async def wa_send_text(numero, texte):
        envoyes.append((numero, texte))
        return {"ok": wa["ok"], "error": None if wa["ok"] else "fenêtre de 24 h fermée"}

    async def sms_send(numero, texte):
        sms.append((numero, texte))
        return {"ok": True, "status": "sent"}

    async def analyser(fichiers, cible, model_id, new_id, avec_donnees=False):
        assert cible == "formulaire" and avec_donnees is False
        if analyse["panne"]:
            raise RuntimeError("proxy IA indisponible")
        if analyse["erreur"]:
            raise ValueError(analyse["erreur"])
        return {"structure": STRUCTURE, "compte_rendu": "Formulaire créé…\n\nPoints à vérifier :\n• « Il ya » corrigé.",
                "usage": {"cost_xof": 12.5}}

    photo = {"document": True, "categorie": "questionnaire", "motif": ""}
    activite = []

    async def classer(data):
        return dict(photo)

    async def journal_activite(**kw):
        activite.append(kw)

    async def next_form_number(code):
        return next(n)

    async def admin(x_user: str = Header("")):
        if x_user != "admin":
            raise HTTPException(status_code=403)
        return {"id": "admin", "role": "admin"}

    async def admin_ou_sup(x_user: str = Header("")):
        if x_user not in ("admin", "sup"):
            raise HTTPException(status_code=403)
        return {"id": x_user, "role": "admin" if x_user == "admin" else "superviseur"}

    api = APIRouter(prefix="/api")
    outils = lf.attach_liluvine_formulaire_routes(
        api=api, db=db, uuid_fn=lambda: f"id{next(n):04d}", get_admin_or_supervisor=admin_ou_sup,
        get_current_admin=admin, wa_send_text=wa_send_text, lire_media=lambda info: b"PK contenu docx",
        public_base_url=lambda req: "https://sawali.bf", next_form_number=next_form_number,
        slugify_code=lambda s: s[:3].upper(), gen_slug=lambda k=8: f"slug{next(n)}", mnos=["ORANGE", "MOOV"],
        secret=SECRET, analyser=analyser, sms_send=sms_send,
        # Lot 41 : code de confirmation fixe et classement des photos simulé
        otp_fn=lambda: "123456", classer_image=classer, journal_activite=journal_activite)
    app = FastAPI()
    app.include_router(api)
    client = TestClient(app).__enter__()
    run = client.portal.call
    run(db.users.insert_many, [
        {"id": "sawali", "role": "superviseur", "client_code": "SAW"},
        {"id": "pharma_a", "role": "pharmacien", "company": "Pharmacie A", "client_code": "PHA", "phone": "+226 70 11 22 33"},
    ])

    def commander(numero="22655000001", mtype="document", mime=DOCX, nom="questionnaire.docx", texte="!formulaire",
                  code="123456"):
        """Lot 41 : la pièce jointe déclenche un code ; `code` (None = pas de réponse) est renvoyé
        par le contact, puis l'analyse lancée est attendue."""
        async def go():
            r = await outils["commande"](from_num=numero, profile_name="Awa", mtype=mtype,
                                         media_info={"mime_type": mime, "stored_name": "x",
                                                     "public_url": f"/api/files/{numero}.bin"} if mtype != "text" else None,
                                         nom_fichier=nom, compte_par_defaut="sawali", texte=texte)
            if r.get("etape") == "attente_otp" and code:
                outils["derniere_tache"].clear()
                await outils["reponse_otp"](from_num=numero, texte=code)
                if outils["derniere_tache"].get("tache"):
                    await outils["derniere_tache"]["tache"]
            return r
        return run(go)

    yield types.SimpleNamespace(client=client, db=db, run=run, outils=outils, envoyes=envoyes, analyse=analyse,
                                commander=commander, wa=wa, sms=sms, photo=photo, activite=activite)
    client.__exit__(None, None, None)


def _liens(texte):
    return re.findall(r"https://sawali\.bf(/\S+)", texte)


def test_parcours_complet_numero_inconnu(env):
    env.commander()
    cmd = env.run(env.db.liluvine_formulaires.find_one, {}, {"_id": 0})
    assert cmd["type_client"] == "inconnu" and cmd["compte_id"] == "sawali" and cmd["prix_xof"] == 3000
    assert re.fullmatch(r"FORM_22655000001_\d{8}-\d{4}", cmd["titre"])
    form = env.run(env.db.forms.find_one, {"id": cmd["form_id"]}, {"_id": 0})
    assert form["is_public"] is False and form["liluvine_statut"] == "en_attente_paiement" and form["title"] == cmd["titre"]
    # Réponses envoyées : accusé de réception, puis tarif + lien de paiement
    # Lot 41 : code de confirmation, puis accusé après le code, puis tarif
    code, accuse, tarif = env.envoyes[0][1], env.envoyes[1][1], env.envoyes[2][1]
    assert code.startswith("📄 Document reçu") and "*123456*" in code
    assert accuse.startswith("✅ Code confirmé")
    assert "3 question(s) sur 1 page(s)" in tarif and "*3 000 FCFA*" in tarif and "« Il ya » corrigé." in tarif
    lien_paiement = env.run(env.db.payment_links.find_one, {"liluvine_formulaire_id": cmd["id"]}, {"_id": 0})
    assert f"/pay/{lien_paiement['slug']}" in tarif and lien_paiement["amount"] == 3000.0
    assert lien_paiement["max_uses"] == 1 and lien_paiement["prefill_phone"] == "22655000001"
    # Tant que ce n'est pas payé : aucun lien de saisie
    assert "/fr/" not in tarif

    # Paiement confirmé (même appel que le webhook PawaPay) → mise en ligne + liens cryptés
    paiement = {"status": "completed", "payment_link_id": lien_paiement["id"]}
    env.run(env.outils["apres_paiement"], paiement)
    env.run(env.outils["apres_paiement"], paiement)                       # 2e confirmation : rien de plus
    assert len(env.envoyes) == 4
    saisie, resultats = _liens(env.envoyes[3][1])
    assert saisie.startswith("/fr/") and resultats.startswith("/fr-resultats/")
    assert cmd["form_id"] not in saisie                                    # pas d'identifiant en clair
    jeton_saisie, jeton_res = saisie.split("/")[-1], resultats.split("/")[-1]
    c = env.client
    # N'importe qui remplit par le lien crypté (le formulaire reste privé)
    f = c.get(f"/api/public/forms/jeton/{jeton_saisie}")
    assert f.status_code == 200 and f.json()["title"] == "Fiche de renseignement" and "id" not in f.json()
    assert "22655000001" not in str(f.json())                             # numéro du demandeur jamais exposé
    r = c.post(f"/api/public/forms/jeton/{jeton_saisie}/submission",
               json={"data": {"q1": True, "q2": "Grossiste X", "q3": [{"nom": "Awa"}]}, "respondent_name": "Brice"})
    assert r.status_code == 200
    # Le jeton de saisie ne donne pas les réponses, et inversement
    assert c.get(f"/api/public/forms/resultats/{jeton_saisie}").status_code == 404
    assert c.get(f"/api/public/forms/jeton/{jeton_res}").status_code == 404
    res = c.get(f"/api/public/forms/resultats/{jeton_res}").json()
    assert [x["user_label"] for x in res["reponses"]] == ["Brice"] and len(res["champs"]) == 3
    csv = c.get(f"/api/public/forms/resultats/{jeton_res}/export.csv").content.decode("utf-8-sig").splitlines()
    assert csv[0] == "Date;Répondant;Des grossistes sans factures ?;Lesquels ?;Personnel"
    assert csv[1].endswith(";Brice;Oui;Grossiste X;nom: Awa")
    # Suivi (Admin / Superviseur)
    suivi = c.get("/api/supervision/liluvine-formulaire", headers={"X-User": "sup"}).json()
    assert suivi["commandes"][0]["statut"] == "publie" and suivi["tarifs"] == {"client": 2000, "inconnu": 3000}


def test_client_enregistre_tarif_et_rattachement(env):
    # Tarifs modifiables par l'Admin seulement
    c = env.client
    assert c.put("/api/supervision/liluvine-formulaire/tarifs", headers={"X-User": "sup"},
                 json={"prix_client_xof": 1500, "prix_inconnu_xof": 4000}).status_code == 403
    assert c.put("/api/supervision/liluvine-formulaire/tarifs", headers={"X-User": "admin"},
                 json={"prix_client_xof": 1500, "prix_inconnu_xof": 4000}).json() == {"client": 1500, "inconnu": 4000}
    env.commander(numero="22670112233")                                    # numéro de la Pharmacie A
    cmd = env.run(env.db.liluvine_formulaires.find_one, {}, {"_id": 0})
    assert (cmd["type_client"], cmd["compte_id"], cmd["prix_xof"]) == ("client", "pharma_a", 1500)
    form = env.run(env.db.forms.find_one, {"id": cmd["form_id"]}, {"_id": 0})
    assert form["client_id"] == "pharma_a" and form["number"].startswith("FORM-PHA-")
    assert "*1 500 FCFA*" in env.envoyes[-1][1]


def test_gratuit_publie_sans_paiement(env):
    env.client.put("/api/supervision/liluvine-formulaire/tarifs", headers={"X-User": "admin"},
                   json={"prix_client_xof": 0, "prix_inconnu_xof": 0})
    env.commander()
    assert env.run(env.db.payment_links.count_documents, {}) == 0
    assert "/fr/" in env.envoyes[-1][1] and env.envoyes[-1][1].startswith("🎉")


def test_refus_avec_motif(env):
    # Texte seul : mode d'emploi
    env.commander(mtype="text")
    assert "légende *!formulaire*" in env.envoyes[-1][1]
    # Ancien format Word : motif clair, rien de créé
    env.commander(mime="application/msword", nom="vieux.doc")
    assert "❌ Impossible de traiter votre document" in env.envoyes[-1][1] and ".docx" in env.envoyes[-1][1]
    # Audio : non pris en charge
    env.commander(mtype="audio", mime="audio/ogg", nom=None)
    assert "seuls les documents Word, Excel, PDF et les photos" in env.envoyes[-1][1]
    # L'IA ne trouve aucune question : motif renvoyé au contact
    env.analyse["erreur"] = "Aucune question n'a pu être reconnue dans le document."
    env.commander()
    assert env.envoyes[-2][1].startswith("❌ Je n'ai pas pu créer le formulaire : Aucune question")
    # Lot 41 : 3e demande non valable -> numéro en liste noire, prévenu
    assert env.envoyes[-1][1].startswith("⛔ Après plusieurs demandes non valables")
    assert env.run(env.db.forms.count_documents, {}) == 0
    assert env.run(env.db.liluvine_formulaires.find_one, {"statut": "erreur"}, {"_id": 0})["erreur"].startswith("Aucune")


def test_photo_sans_nom_de_fichier(env):
    env.commander(mtype="image", mime="image/jpeg", nom=None)
    cmd = env.run(env.db.liluvine_formulaires.find_one, {}, {"_id": 0})
    assert cmd["fichier"] == "document.jpg" and cmd["statut"] == "en_attente_paiement"


def test_liens_expires_ou_falsifies(env):
    passe = datetime.now(timezone.utc) - timedelta(days=1)
    expire = jwt.encode({"action": "form_fill", "target_id": "x", "exp": int(passe.timestamp())}, SECRET, algorithm="HS256")
    assert env.client.get(f"/api/public/forms/jeton/{expire}").json()["detail"] == "Ce lien a expiré."
    faux = jwt.encode({"action": "form_fill", "target_id": "x"}, "autre-secret-assez-long-pour-hs256-0123456789", algorithm="HS256")
    assert env.client.get(f"/api/public/forms/jeton/{faux}").status_code == 404
    # Formulaire non payé : même un jeton valide ne l'ouvre pas
    env.commander()
    cmd = env.run(env.db.liluvine_formulaires.find_one, {}, {"_id": 0})
    ok = jwt.encode({"action": "form_fill", "target_id": cmd["form_id"],
                     "exp": int((datetime.now(timezone.utc) + timedelta(days=1)).timestamp())}, SECRET, algorithm="HS256")
    assert env.client.get(f"/api/public/forms/jeton/{ok}").status_code == 404


# --- Lot 37 : journal, interventions humaines, sondage de satisfaction et relances -------
SUP, ADMIN = {"X-User": "sup"}, {"X-User": "admin"}


def _payer(env):
    cmd = env.run(env.db.liluvine_formulaires.find_one, {"statut": "en_attente_paiement"}, {"_id": 0})
    env.run(env.outils["apres_paiement"], {"status": "completed", "payment_link_id": cmd["payment_link_id"]})
    return cmd["id"]


def test_journal_complet_et_filtres(env):
    env.commander(mtype="text")                                           # mode d'emploi
    env.commander(mime="application/msword", nom="vieux.doc")             # refus
    env.commander()                                                        # formulaire créé
    j = env.client.get("/api/supervision/liluvine-formulaire", headers=SUP).json()
    statuts = sorted(c["statut"] for c in j["commandes"])
    assert statuts == ["en_attente_paiement", "mode_emploi", "refuse"]
    c = next(x for x in j["commandes"] if x["statut"] == "en_attente_paiement")
    # Référence du formulaire, livré ou non, étapes horodatées
    assert c["reference"].startswith("FORM-SAW-") and c["livre"] is False and c["nom_contact"] == "Awa"
    assert [e["etape"] for e in c["journal"]] == ["reçu", "code de confirmation envoyé", "code confirmé",
                                                   "accusé de réception", "formulaire créé",
                                                   "tarif 3 000 FCFA + lien de paiement"]
    refus = next(x for x in j["commandes"] if x["statut"] == "refuse")
    assert ".docx" in refus["erreur"] and refus["intervention_requise"] is False
    assert [x["statut"] for x in env.client.get("/api/supervision/liluvine-formulaire?filtre=erreurs",
                                                headers=SUP).json()["commandes"]] == ["refuse"]
    _payer(env)
    c = env.client.get("/api/supervision/liluvine-formulaire", headers=ADMIN).json()["commandes"][0]
    assert c["statut"] == "publie" and c["livre"] is True and c["journal"][-1]["etape"] == "liens envoyés"
    assert env.client.get("/api/supervision/liluvine-formulaire", headers={"X-User": "pharma"}).status_code == 403


def test_liens_non_delivres_intervention_et_renvoi(env):
    env.commander()
    env.wa["ok"] = False                                                   # WhatsApp refuse au moment du paiement
    cid = _payer(env)
    j = env.client.get("/api/supervision/liluvine-formulaire?filtre=intervention", headers=SUP).json()
    assert j["a_traiter"] == 1 and [c["id"] for c in j["commandes"]] == [cid]
    c = j["commandes"][0]
    assert c["livre"] is False and "Renvoyer les liens" in c["intervention_motif"]
    assert [c["id"] for c in env.client.get("/api/supervision/liluvine-formulaire?filtre=non_livres",
                                            headers=SUP).json()["commandes"]] == [cid]
    # Le Superviseur renvoie les liens : livré, intervention close
    env.wa["ok"] = True
    r = env.client.post(f"/api/supervision/liluvine-formulaire/{cid}/renvoyer-liens", headers=SUP).json()
    assert r["ok"] is True and env.envoyes[-1][1].startswith("🔁 Voici à nouveau les liens")
    c = env.client.get("/api/supervision/liluvine-formulaire", headers=SUP).json()["commandes"][0]
    assert c["livre"] is True and c["intervention_faite_le"] and c["intervention_par"] == "sup"
    assert env.client.get("/api/supervision/liluvine-formulaire", headers=SUP).json()["a_traiter"] == 0


def test_erreur_technique_intervention_marquee_traitee(env):
    env.analyse["panne"] = True
    env.commander()
    c = env.client.get("/api/supervision/liluvine-formulaire?filtre=intervention", headers=SUP).json()["commandes"][0]
    assert c["statut"] == "erreur" and c["intervention_motif"].startswith("Erreur technique")
    assert env.envoyes[-1][1].startswith("❌ Je n'ai pas pu créer le formulaire : le service d'analyse")
    r = env.client.post(f"/api/supervision/liluvine-formulaire/{c['id']}/intervention", headers=ADMIN,
                        json={"note": "Formulaire créé à la main et envoyé"})
    assert r.status_code == 200
    c = env.client.get("/api/supervision/liluvine-formulaire", headers=SUP).json()["commandes"][0]
    assert c["intervention_note"] == "Formulaire créé à la main et envoyé" and c["journal"][-1]["etape"] == "intervention faite"
    # Un document refusé (faute du contact, prévenu) ne demande pas d'intervention
    env.analyse["panne"] = False
    env.analyse["erreur"] = "Aucune question n'a pu être reconnue dans le document."
    env.commander()
    assert env.client.get("/api/supervision/liluvine-formulaire", headers=SUP).json()["a_traiter"] == 0


def test_sondage_de_satisfaction_et_relances(env):
    c, run, db = env.client, env.run, env.db
    run(db.wa_surveys.insert_one, {"id": "s1", "title": "Satisfaction !formulaire", "status": "draft",
                                   "client_id": "sawali", "questions": [{"id": "q", "type": "rating", "label": "Note"}]})
    # Choisi par le Superviseur : relance après 24 h, 2 relances au plus
    r = c.put("/api/supervision/liluvine-formulaire/sondage", headers=SUP,
              json={"sondage_id": "s1", "relance_heures": 24, "relances_max": 2})
    assert r.json()["sondage_titre"] == "Satisfaction !formulaire"
    assert [x["id"] for x in c.get("/api/supervision/liluvine-formulaire/sondages", headers=SUP).json()] == ["s1"]
    env.commander()
    cid = _payer(env)
    # Juste après les liens : le sondage, avec un lien personnel
    inv = run(db.wa_survey_invites.find_one, {"survey_id": "s1"}, {"_id": 0})
    assert inv["contact_id"] == "liluvine:22655000001" and inv["status"] == "sent"
    assert env.envoyes[-1][1].startswith("🙏 Merci d'avoir utilisé !formulaire") and f"/s/{inv['token']}" in env.envoyes[-1][1]
    assert run(db.wa_surveys.find_one, {"id": "s1"})["status"] == "active"
    # Pas encore l'heure : aucune relance
    assert run(env.outils["relancer_sondages"]) == 0

    def avancer():
        run(db.liluvine_formulaires.update_one, {"id": cid}, {"$set": {"sondage.prochaine_relance": "2000-01-01T00:00:00+00:00"}})

    # 1re relance par WhatsApp ; 2e relance : WhatsApp refuse → SMS
    avancer()
    assert run(env.outils["relancer_sondages"]) == 1 and env.envoyes[-1][1].startswith("⏰ Petit rappel")
    env.wa["ok"] = False
    avancer()
    assert run(env.outils["relancer_sondages"]) == 1 and env.sms[-1][1].startswith("⏰ Petit rappel")
    # Maximum atteint : plus de relance
    avancer()
    assert run(env.outils["relancer_sondages"]) == 0
    cmd = run(db.liluvine_formulaires.find_one, {"id": cid}, {"_id": 0})
    assert cmd["sondage"]["relances"] == 2 and cmd["sondage"]["prochaine_relance"] is None
    assert [e["detail"] for e in cmd["journal"] if e["etape"] == "relance sondage"] == [
        "relance n°1 par whatsapp", "relance n°2 par sms"]


def test_sondage_repondu_plus_de_relance(env):
    c, run, db = env.client, env.run, env.db
    run(db.wa_surveys.insert_one, {"id": "s1", "title": "Avis", "status": "active", "client_id": "sawali"})
    c.put("/api/supervision/liluvine-formulaire/sondage", headers=ADMIN, json={"sondage_id": "s1"})
    env.commander()
    cid = _payer(env)
    run(db.wa_survey_invites.update_one, {"survey_id": "s1"}, {"$set": {"answered_at": "2026-09-29T16:00:00Z"}})
    run(db.liluvine_formulaires.update_one, {"id": cid}, {"$set": {"sondage.prochaine_relance": "2000-01-01T00:00:00+00:00"}})
    avant = len(env.envoyes)
    assert run(env.outils["relancer_sondages"]) == 0 and len(env.envoyes) == avant
    assert run(db.liluvine_formulaires.find_one, {"id": cid})["sondage"]["repondu"] is True
    # Sans sondage choisi : rien n'est envoyé après la livraison
    c.put("/api/supervision/liluvine-formulaire/sondage", headers=ADMIN, json={"sondage_id": None})
    env.commander(numero="22655000002")
    _payer(env)
    assert env.envoyes[-1][1].startswith("🎉")
    assert c.put("/api/supervision/liluvine-formulaire/sondage", headers=SUP,
                 json={"sondage_id": "inconnu"}).status_code == 404


# ---------------------------------------------------------------------------
# Lot 41 — réalisation forcée par l'Admin (badge « forcé » / « auto »)
# ---------------------------------------------------------------------------
def test_forcage_en_attente_de_paiement(env):
    env.commander()
    c = env.client.get("/api/supervision/liluvine-formulaire", headers=SUP).json()["commandes"][0]
    assert c["statut"] == "en_attente_paiement" and c["forcable"] is True and "media_info" not in c
    # Réservé à l'Admin
    assert env.client.post(f"/api/supervision/liluvine-formulaire/{c['id']}/forcer", headers=SUP, json={}).status_code == 403
    r = env.client.post(f"/api/supervision/liluvine-formulaire/{c['id']}/forcer", headers=ADMIN,
                        json={"motif": "Paiement reçu en espèces"})
    assert r.status_code == 200 and r.json() == {"ok": True, "etape": "mis_en_ligne"}
    liens = env.envoyes[-1][1]
    assert "/fr/" in liens and "Paiement reçu" not in liens                 # jamais « payé » quand c'est forcé
    c = env.client.get("/api/supervision/liluvine-formulaire", headers=SUP).json()["commandes"][0]
    assert c["statut"] == "publie" and c["mode_realisation"] == "force" and c["force_par"] == "admin"
    assert c["force_motif"] == "Paiement reçu en espèces" and c["forcable"] is False
    assert any(e["etape"] == "mis en ligne (FORCÉ)" for e in c["journal"])
    lien = env.run(env.db.payment_links.find_one, {"liluvine_formulaire_id": c["id"]}, {"_id": 0})
    assert lien["disabled"] is True                                         # plus de paiement possible
    form = env.run(env.db.forms.find_one, {"id": c["form_id"]}, {"_id": 0})
    assert form["liluvine_mode"] == "force" and form["liluvine_statut"] == "publie"
    # Un paiement tardif ne change rien ; un 2e forçage est refusé
    env.run(env.outils["apres_paiement"], {"status": "completed", "payment_link_id": lien["id"]})
    assert env.run(env.db.liluvine_formulaires.find_one, {"id": c["id"]}, {"_id": 0})["mode_realisation"] == "force"
    assert env.client.post(f"/api/supervision/liluvine-formulaire/{c['id']}/forcer", headers=ADMIN,
                           json={}).status_code == 400


def test_forcage_apres_erreur_technique_et_mode_auto(env):
    env.analyse["panne"] = True
    env.commander()
    c = env.client.get("/api/supervision/liluvine-formulaire", headers=SUP).json()["commandes"][0]
    assert c["statut"] == "erreur" and c["forcable"] is True
    env.analyse["panne"] = False
    r = env.client.post(f"/api/supervision/liluvine-formulaire/{c['id']}/forcer", headers=ADMIN, json={})
    assert r.status_code == 200 and r.json()["etape"] == "analyse_et_mis_en_ligne"
    c = env.client.get("/api/supervision/liluvine-formulaire", headers=SUP).json()["commandes"][0]
    assert c["statut"] == "publie" and c["mode_realisation"] == "force" and c["form_id"]
    assert c["intervention_faite_le"] and c["intervention_note"] == "Réalisation forcée"
    assert env.run(env.db.payment_links.count_documents, {}) == 0          # jamais de lien de paiement
    # Une commande payée normalement est « auto »
    env.commander(numero="22655000009")
    lien = env.run(env.db.payment_links.find_one, {}, {"_id": 0})
    env.run(env.outils["apres_paiement"], {"status": "completed", "payment_link_id": lien["id"]})
    modes = {x["telephone"]: x.get("mode_realisation") for x in
             env.client.get("/api/supervision/liluvine-formulaire", headers=SUP).json()["commandes"]}
    assert modes == {"22655000001": "force", "22655000009": "auto"}
    # Refus (document jamais conservé) : rien à forcer
    env.commander(mtype="document", mime="application/zip", nom="a.zip")
    refus = env.client.get("/api/supervision/liluvine-formulaire", headers=SUP).json()["commandes"][0]
    assert refus["statut"] == "refuse" and refus["forcable"] is False
    assert env.client.post(f"/api/supervision/liluvine-formulaire/{refus['id']}/forcer", headers=ADMIN,
                           json={}).status_code == 400


# ---------------------------------------------------------------------------
# Lot 41 — code de confirmation, photos refusées, liste noire
# ---------------------------------------------------------------------------
def test_code_de_confirmation(env):
    # Sans réponse au code : rien n'est analysé ni facturé
    env.commander(code=None)
    cmd = env.run(env.db.liluvine_formulaires.find_one, {}, {"_id": 0})
    assert cmd["statut"] == "attente_otp" and "otp_hash" in cmd and "123456" not in str(cmd["otp_hash"])
    assert env.run(env.db.forms.count_documents, {}) == 0 and env.run(env.db.payment_links.count_documents, {}) == 0
    # Un message sans code n'est pas intercepté (les autres commandes restent possibles)
    assert env.run(lambda: env.outils["reponse_otp"](from_num="22655000001", texte="bonjour")) is False
    # Mauvais code : 2 essais restants, puis 1
    assert env.run(lambda: env.outils["reponse_otp"](from_num="22655000001", texte="111111")) is True
    assert "Il vous reste 2 essai(s)" in env.envoyes[-1][1]
    # Bon code (même écrit « !formulaire 123456 ») → analyse, tarif
    async def go():
        env.outils["derniere_tache"].clear()
        r = await env.outils["commande"](from_num="22655000001", profile_name="Awa", mtype="text", media_info=None,
                                         nom_fichier=None, compte_par_defaut="sawali", texte="!formulaire 123456")
        await env.outils["derniere_tache"]["tache"]
        return r
    assert env.run(go)["etape"] == "otp"
    cmd = env.run(env.db.liluvine_formulaires.find_one, {}, {"_id": 0})
    assert cmd["statut"] == "en_attente_paiement" and cmd["otp_confirme_le"]
    assert "*3 000 FCFA*" in env.envoyes[-1][1]
    # Code expiré : demande annulée, compte comme un échec du contact
    env.commander(numero="22655000002", code=None)
    env.run(env.db.liluvine_formulaires.update_one, {"chiffres": "22655000002"},
            {"$set": {"otp_expire_le": "2020-01-01T00:00:00+00:00"}})
    env.run(lambda: env.outils["reponse_otp"](from_num="22655000002", texte="123456"))
    c2 = env.run(env.db.liluvine_formulaires.find_one, {"chiffres": "22655000002"}, {"_id": 0})
    assert c2["statut"] == "erreur" and c2["echec_contact"] is True and "expiré" in env.envoyes[-1][1]
    # L'Admin peut forcer une commande restée en attente du code
    env.commander(numero="22655000003", code=None)
    c3 = env.run(env.db.liluvine_formulaires.find_one, {"chiffres": "22655000003"}, {"_id": 0})
    r = env.client.post(f"/api/supervision/liluvine-formulaire/{c3['id']}/forcer", headers=ADMIN, json={})
    assert r.status_code == 200 and r.json()["etape"] == "analyse_et_mis_en_ligne"


def test_photo_refusee_puis_liste_noire(env):
    env.photo.update({"document": False, "categorie": "selfie", "motif": "visage en gros plan"})
    for _ in range(2):
        env.commander(mtype="image", mime="image/jpeg", nom="moi.jpg")
    assert "ne montre pas un questionnaire (selfie : visage en gros plan)" in env.envoyes[-1][1]
    assert env.run(env.db.liluvine_liste_noire.count_documents, {}) == 0
    assert env.run(env.db.forms.count_documents, {}) == 0                  # jamais analysé
    env.commander(mtype="image", mime="image/jpeg", nom="moi.jpg")          # 3e : le contact insiste
    ln = env.client.get("/api/supervision/liluvine-formulaire/liste-noire", headers=SUP).json()
    assert len(ln) == 1 and ln[0]["chiffres"] == "22655000001" and len(ln[0]["pieces"]) == 3
    assert ln[0]["pieces"][0]["url"] == "/api/files/22655000001.bin"      # copie de la pièce jointe
    assert env.activite and "mis en liste noire" in env.activite[0]["label"]
    j = env.client.get("/api/supervision/liluvine-formulaire", headers=SUP).json()["commandes"]
    assert j[0]["piece_url"] == "/api/files/22655000001.bin" and "otp_hash" not in j[0]
    # Numéro bloqué : même un bon document est refusé sans analyse
    env.photo.update({"document": True})
    env.commander()
    assert env.envoyes[-1][1].startswith("⛔ Votre numéro n'est plus autorisé")
    assert env.run(env.db.forms.count_documents, {}) == 0
    # Déblocage par l'Admin (pas le Superviseur) : le contact repart de zéro
    assert env.client.delete("/api/supervision/liluvine-formulaire/liste-noire/22655000001", headers=SUP).status_code == 403
    assert env.client.delete("/api/supervision/liluvine-formulaire/liste-noire/22655000001", headers=ADMIN).status_code == 200
    env.commander()
    assert env.run(env.db.liluvine_formulaires.find_one, {"statut": "en_attente_paiement"}, {"_id": 0})
    # Une panne de notre côté ne compte jamais comme un échec du contact
    env.analyse["panne"] = True
    for n in range(3):
        env.commander(numero=f"2265600000{n}")
        env.commander(numero="22657000000")
    assert env.run(env.db.liluvine_liste_noire.count_documents, {"chiffres": "22657000000"}) == 0
