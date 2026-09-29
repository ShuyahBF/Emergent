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
    envoyes = []
    analyse = {"erreur": None}
    n = count(1)

    async def wa_send_text(numero, texte):
        envoyes.append((numero, texte))
        return {"ok": True}

    async def analyser(fichiers, cible, model_id, new_id, avec_donnees=False):
        assert cible == "formulaire" and avec_donnees is False
        if analyse["erreur"]:
            raise ValueError(analyse["erreur"])
        return {"structure": STRUCTURE, "compte_rendu": "Formulaire créé…\n\nPoints à vérifier :\n• « Il ya » corrigé.",
                "usage": {"cost_xof": 12.5}}

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
        secret=SECRET, analyser=analyser)
    app = FastAPI()
    app.include_router(api)
    client = TestClient(app).__enter__()
    run = client.portal.call
    run(db.users.insert_many, [
        {"id": "sawali", "role": "superviseur", "client_code": "SAW"},
        {"id": "pharma_a", "role": "pharmacien", "company": "Pharmacie A", "client_code": "PHA", "phone": "+226 70 11 22 33"},
    ])

    def commander(numero="22655000001", mtype="document", mime=DOCX, nom="questionnaire.docx", texte="!formulaire"):
        async def go():
            r = await outils["commande"](from_num=numero, profile_name="Awa", mtype=mtype,
                                         media_info={"mime_type": mime, "stored_name": "x"} if mtype != "text" else None,
                                         nom_fichier=nom, compte_par_defaut="sawali")
            if r.get("tache"):
                await r["tache"]
            return r
        return run(go)

    yield types.SimpleNamespace(client=client, db=db, run=run, outils=outils, envoyes=envoyes, analyse=analyse,
                                commander=commander)
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
    accuse, tarif = env.envoyes[0][1], env.envoyes[1][1]
    assert accuse.startswith("📄 Document reçu")
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
    assert len(env.envoyes) == 3
    saisie, resultats = _liens(env.envoyes[2][1])
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
    assert env.envoyes[-1][1].startswith("❌ Je n'ai pas pu créer le formulaire : Aucune question")
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
