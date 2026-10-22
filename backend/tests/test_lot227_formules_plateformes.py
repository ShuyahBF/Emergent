"""Lot 227 — formules (abonnements) et parrainage des plateformes : catalogue, achat PawaPay, activation cumulée, parrainage.
MongoDB simulé, PawaPay simulé (httpx.MockTransport). Lancer : cd backend && python -m pytest tests/test_lot227_formules_plateformes.py -q"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Le module routes.pispi (lot 232, paiement PI-SPI) importe la base globale : adresse factice, aucune connexion réelle n'est ouverte
os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "sawali_test_lot227")
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.formules_plateformes as fp  # noqa: E402

CLE = "cle-de-test"
HOTES = {"sandbox": "https://pp.test", "production": "https://pp.test"}
DEPOSIT_ETAT = {"status": "PROCESSING"}


def entetes(corps: dict, code="paiementmobile"):
    brut = json.dumps(corps, ensure_ascii=False)
    ts = str(int(time.time()))
    return brut, {"Content-Type": "application/json", "X-Emetteur": code, "X-Timestamp": ts,
                  "X-Signature": hmac.new(CLE.encode(), f"{ts}.{brut}".encode(), hashlib.sha256).hexdigest()}


def U(i="u1", tel="70 11 22 33"):
    return {"id": i, "nom": f"Nom {i}", "telephone": tel}


@pytest.fixture()
def env():
    hooks: list = []
    db = mongomock_motor.AsyncMongoMockClient()["test"]

    def pp(requete: httpx.Request) -> httpx.Response:
        if requete.url.path.endswith("/paymentpage"):
            return httpx.Response(200, json={"redirectUrl": "https://pay.pawapay.test/x"})
        return httpx.Response(200, json={"status": "FOUND", "data": {"status": DEPOSIT_ETAT["status"]}})

    fp._transport = httpx.MockTransport(pp)
    api = APIRouter(prefix="/api")
    api.include_router(fp.make_formules_plateformes(
        db=db, get_super_admin=lambda: {"role": "admin"}, hooks_apres_paiement=hooks,
        pawapay={"jeton": lambda s: "jeton", "hotes": HOTES, "devise": lambda pays: "XOF"}))
    app = FastAPI()
    app.include_router(api)
    c = TestClient(app).__enter__()
    c.portal.call(db.liluvine_emetteurs.insert_many, [
        {"code": "paiementmobile", "nom": "Paiement Mobile", "secret": CLE, "actif": True},
        {"code": "autre", "nom": "Autre", "secret": CLE, "actif": True}])
    c.portal.call(db.settings.insert_one, {"_id": "global", "pawapay_enabled": True, "pawapay_environment": "sandbox"})
    DEPOSIT_ETAT["status"] = "PROCESSING"
    c.db, c.hooks = db, hooks
    yield c
    fp._transport = None
    fp._analyser = None
    fp._transcrire = None
    c.__exit__(None, None, None)


def appel(c, chemin, corps, code="paiementmobile", **kw):
    brut, h = entetes(corps, code)
    return c.post(f"/api/{chemin}", content=brut.encode(), headers=h, **kw)


def formule(c, **plus):
    r = c.post("/api/admin/formules-plateformes", json={"plateforme": "paiementmobile", "nom": "OCR Ordonnances", "prix": 1000,
                                                       "fonctions": ["ocr_ordonnances"], **plus})
    assert r.status_code == 201, r.text
    return r.json()


def payer(c, u, f):
    """Achat + confirmation du paiement par le crochet (comme le webhook PawaPay)."""
    r = appel(c, "formules-plateformes/acheter", {"utilisateur": u, "formule_id": f["id"], "retour": "https://site.test/abonnement"})
    assert r.status_code == 200, r.text
    dep = r.json()["deposit_id"]
    c.portal.call(c.db.payments.update_one, {"deposit_id": dep}, {"$set": {"status": "completed"}})
    p = c.portal.call(c.db.payments.find_one, {"deposit_id": dep}, {"_id": 0})
    c.portal.call(c.hooks[0], p)
    return dep


def acces(c, u):
    return appel(c, "formules-plateformes/acces", {"utilisateur": u, "fonction": "ocr_ordonnances"}).json()


def test_signature_obligatoire(env):
    assert env.post("/api/formules-plateformes/catalogue", json={"utilisateur": U()}).status_code == 401
    brut, h = entetes({"utilisateur": U()})
    h["X-Signature"] = "0" * 64
    assert env.post("/api/formules-plateformes/catalogue", content=brut.encode(), headers=h).status_code == 401


def test_catalogue_par_plateforme_et_code_parrainage(env):
    formule(env)
    formule(env, nom="Ancienne", actif=False)
    env.post("/api/admin/formules-plateformes", json={"plateforme": "autre", "nom": "Pour une autre", "prix": 500})
    r = appel(env, "formules-plateformes/catalogue", {"utilisateur": U()}).json()
    assert [f["nom"] for f in r["formules"]] == ["OCR Ordonnances"] and r["formules"][0]["duree_jours"] == 30
    assert r["code_parrainage"].startswith("PA") and len(r["code_parrainage"]) == 8 and r["abonnements"] == []
    assert appel(env, "formules-plateformes/catalogue", {"utilisateur": U()}).json()["code_parrainage"] == r["code_parrainage"]


def test_achat_active_30_jours_et_cumule(env):
    f = formule(env)
    assert acces(env, U())["actif"] is False
    payer(env, U(), f)
    a = acces(env, U())
    assert a["actif"] is True and a["jours_restants"] == 30
    payer(env, U(), f)                                   # payé avant l'expiration : s'ajoute au temps restant
    assert acces(env, U())["jours_restants"] == 60
    assert acces(env, U("u2"))["actif"] is False         # un autre utilisateur n'est pas concerné


def test_activation_unique_meme_si_hook_rejoue(env):
    f = formule(env)
    dep = payer(env, U(), f)
    p = env.portal.call(env.db.payments.find_one, {"deposit_id": dep}, {"_id": 0})
    env.portal.call(env.hooks[0], p)                     # webhook répété
    assert acces(env, U())["jours_restants"] == 30


def test_formule_expiree_et_duree_propre(env):
    f = formule(env, duree_jours=10)
    payer(env, U(), f)
    assert acces(env, U())["jours_restants"] == 10
    passe = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    env.portal.call(env.db.membres_plateformes.update_one, {"utilisateur_id": "u1"}, {"$set": {f"abonnements.{f['id']}.expire_le": passe}})
    assert acces(env, U())["actif"] is False
    payer(env, U(), f)                                    # après expiration : repart de zéro
    assert acces(env, U())["jours_restants"] == 10


def test_adresse_de_retour_porte_le_numero_du_paiement(env):
    corps_recus = []
    ancien = fp._transport

    def espion(requete: httpx.Request) -> httpx.Response:
        if requete.url.path.endswith("/paymentpage"):
            corps_recus.append(json.loads(requete.content))
        return ancien.handle_request(requete)

    fp._transport = httpx.MockTransport(espion)
    f = formule(env)
    dep = appel(env, "formules-plateformes/acheter", {"utilisateur": U(), "formule_id": f["id"], "retour": "https://site.test/abonnement"}).json()["deposit_id"]
    assert corps_recus[0]["returnUrl"] == f"https://site.test/abonnement?depositId={dep}"
    assert corps_recus[0]["amountDetails"] == {"amount": "1000", "currency": "XOF"} and corps_recus[0]["phoneNumber"] == "70112233"
    dep2 = appel(env, "formules-plateformes/acheter", {"utilisateur": U(), "formule_id": f["id"], "retour": "https://site.test/a?x=1"}).json()["deposit_id"]
    assert corps_recus[1]["returnUrl"] == f"https://site.test/a?x=1&depositId={dep2}"


def test_achat_lit_paypay_si_webhook_en_retard(env):
    f = formule(env)
    dep = appel(env, "formules-plateformes/acheter", {"utilisateur": U(), "formule_id": f["id"]}).json()["deposit_id"]
    assert appel(env, "formules-plateformes/achat", {"utilisateur": U(), "deposit_id": dep}).json()["statut"] == "attente"
    DEPOSIT_ETAT["status"] = "COMPLETED"
    assert appel(env, "formules-plateformes/achat", {"utilisateur": U(), "deposit_id": dep}).json()["statut"] == "paye"
    assert acces(env, U())["jours_restants"] == 30
    assert appel(env, "formules-plateformes/achat", {"utilisateur": U("u2"), "deposit_id": dep}).status_code == 404   # pas le sien


def test_achat_sans_pawapay(env):
    f = formule(env)
    env.portal.call(env.db.settings.update_one, {"_id": "global"}, {"$set": {"pawapay_enabled": False}})
    assert appel(env, "formules-plateformes/acheter", {"utilisateur": U(), "formule_id": f["id"]}).status_code == 503
    assert appel(env, "formules-plateformes/acheter", {"utilisateur": U(), "formule_id": "inconnue"}).status_code in (404, 503)


def test_parrainage_jours_offerts_aux_deux(env):
    f = formule(env)
    code = appel(env, "formules-plateformes/catalogue", {"utilisateur": U("parrain")}).json()["code_parrainage"]
    r = appel(env, "formules-plateformes/parrainage", {"utilisateur": U("filleul"), "code": code})
    assert r.status_code == 200 and r.json()["a_un_parrain"] is True
    assert appel(env, "formules-plateformes/parrainage", {"utilisateur": U("filleul"), "code": code}).status_code == 409   # déjà un parrain
    payer(env, U("filleul"), f)
    assert acces(env, U("filleul"))["jours_restants"] == 37                          # 30 + 7 offerts
    assert acces(env, U("parrain"))["jours_restants"] == 7                           # 7 offerts, sans avoir payé
    payer(env, U("filleul"), f)                                                       # 2e paiement : pas de nouvelle récompense
    assert acces(env, U("filleul"))["jours_restants"] == 67 and acces(env, U("parrain"))["jours_restants"] == 7
    s = appel(env, "formules-plateformes/parrainage", {"utilisateur": U("parrain")}).json()
    assert s["filleuls"] == 1 and s["filleuls_payants"] == 1 and s["jours_gagnes"] == 7


def test_parrainage_refus(env):
    formule(env)
    code = appel(env, "formules-plateformes/catalogue", {"utilisateur": U("a")}).json()["code_parrainage"]
    assert appel(env, "formules-plateformes/parrainage", {"utilisateur": U("a"), "code": code}).status_code == 422       # son propre code
    assert appel(env, "formules-plateformes/parrainage", {"utilisateur": U("b"), "code": "XXXXXXXX"}).status_code == 404
    f = env.portal.call(env.db.formules_plateformes.find_one, {}, {"_id": 0})
    payer(env, U("c"), f)
    assert appel(env, "formules-plateformes/parrainage", {"utilisateur": U("c"), "code": code}).status_code == 409       # déjà abonné
    code_c = appel(env, "formules-plateformes/catalogue", {"utilisateur": U("c")}).json()["code_parrainage"]
    appel(env, "formules-plateformes/parrainage", {"utilisateur": U("d"), "code": code_c})                                  # d filleul de c
    assert appel(env, "formules-plateformes/parrainage", {"utilisateur": U("c"), "code": appel(env, "formules-plateformes/catalogue", {"utilisateur": U("d")}).json()["code_parrainage"]}).status_code in (409, 422)


def test_parrainage_a_zero_jour(env):
    f = formule(env)
    env.put("/api/admin/formules-plateformes-reglages", json={"parrainage_jours": 0})
    code = appel(env, "formules-plateformes/catalogue", {"utilisateur": U("p")}).json()["code_parrainage"]
    appel(env, "formules-plateformes/parrainage", {"utilisateur": U("f"), "code": code})
    payer(env, U("f"), f)
    assert acces(env, U("f"))["jours_restants"] == 30 and acces(env, U("p"))["actif"] is False


def test_admin_crud_stats_et_suppression(env):
    f = formule(env)
    assert env.post("/api/admin/formules-plateformes", json={"plateforme": "inconnue", "nom": "X", "prix": 500}).status_code == 422
    assert env.post("/api/admin/formules-plateformes", json={"plateforme": "paiementmobile", "nom": "X", "prix": 500, "fonctions": ["piratage"]}).status_code == 422
    assert env.put(f"/api/admin/formules-plateformes/{f['id']}", json={"plateforme": "paiementmobile", "nom": "OCR Pro", "prix": 1500, "fonctions": ["ocr_ordonnances"]}).json()["nom"] == "OCR Pro"
    payer(env, U(), f)
    liste = env.get("/api/admin/formules-plateformes").json()
    ligne = next(x for x in liste["formules"] if x["id"] == f["id"])
    assert ligne["abonnes_actifs"] == 1 and ligne["ventes"] == 1 and liste["membres"] == 1 and "ocr_ordonnances" in liste["fonctions"]
    assert env.delete(f"/api/admin/formules-plateformes/{f['id']}").json() == {"ok": True, "desactivee": True}     # déjà vendue
    g = formule(env, nom="Jamais vendue")
    assert env.delete(f"/api/admin/formules-plateformes/{g['id']}").json() == {"ok": True, "desactivee": False}
    assert [x["id"] for x in appel(env, "formules-plateformes/catalogue", {"utilisateur": U()}).json()["formules"]] == []   # la vendue est désactivée


# ---------------------------------------------------------------- lot 228 : OCR réservé aux abonnés
IMAGE = "data:image/jpeg;base64," + __import__("base64").b64encode(b"\xff\xd8\xff" + b"0" * 200).decode()


def faux_ocr(champs=None, erreur=None):
    appels = []

    async def analyser(octets, mime, nom, modele, *, system_prompt, default_model):
        appels.append({"mime": mime, "taille": len(octets), "systeme": system_prompt})
        if erreur:
            return {"error": erreur, "extracted_fields": {}}
        return {"extracted_fields": champs or {"operateur": "Orange", "code_marchand": "3366444", "nom_marchand": "Pharmacie"},
                "summary": "Plaque Orange Money", "confidence": 0.9, "uncertain_fields": ["nom_marchand"], "flags": []}

    fp._analyser = analyser
    return appels


def lire_ocr(env, u=None, type="plaque_marchand", image=IMAGE):
    return appel(env, "formules-plateformes/ocr", {"utilisateur": u or U(), "type": type, "image": image})


def test_ocr_refuse_sans_abonnement_avec_le_prix_de_la_formule(env):
    appels = faux_ocr()
    formule(env, prix=2500, nom="OCR Ordonnances")
    formule(env, prix=9000, nom="OCR Pro")
    r = lire_ocr(env)
    assert r.status_code == 402 and not appels                                    # aucune lecture, aucun coût
    d = r.json()["detail"]
    assert d["code"] == "abonnement_requis" and d["formule"]["nom"] == "OCR Ordonnances" and d["formule"]["prix"] == 2500
    assert "OCR Ordonnances" in d["message"] and "2 500 FCFA" in d["message"] and "30 jours" in d["message"]   # la moins chère


def test_ocr_refuse_sans_aucune_formule(env):
    faux_ocr()
    d = lire_ocr(env).json()["detail"]
    assert d["formule"] is None and "aucune formule" in d["message"]


def test_ocr_refuse_si_la_formule_ne_debloque_pas_l_ocr(env):
    faux_ocr()
    env.post("/api/admin/formules-plateformes", json={"plateforme": "paiementmobile", "nom": "Sans OCR", "prix": 500, "fonctions": []})
    assert lire_ocr(env).status_code == 402


def test_ocr_abonne_plaque_et_ordonnance(env):
    appels = faux_ocr()
    f = formule(env)
    payer(env, U(), f)
    r = lire_ocr(env)
    assert r.status_code == 200
    j = r.json()
    assert j["champs"]["code_marchand"] == "3366444" and j["incertains"] == ["nom_marchand"] and j["restant_aujourdhui"] == 29
    assert appels[0]["mime"] == "image/jpeg" and "PLAQUE" in appels[0]["systeme"]
    assert lire_ocr(env, type="ordonnance").status_code == 200 and "ORDONNANCE" in appels[1]["systeme"]
    assert lire_ocr(env, U("autre")).status_code == 402                           # un autre utilisateur n'a pas payé


def test_ocr_expire_apres_l_echeance(env):
    faux_ocr()
    f = formule(env)
    payer(env, U(), f)
    passe = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    env.portal.call(env.db.membres_plateformes.update_one, {"utilisateur_id": "u1"}, {"$set": {f"abonnements.{f['id']}.expire_le": passe}})
    assert lire_ocr(env).status_code == 402


def test_ocr_limite_par_jour(env):
    faux_ocr()
    f = formule(env)
    payer(env, U(), f)
    assert env.put("/api/admin/formules-plateformes-reglages", json={"parrainage_jours": 7, "ocr_par_jour": 2}).json()["ocr_par_jour"] == 2
    assert lire_ocr(env).status_code == 200 and lire_ocr(env).status_code == 200
    r = lire_ocr(env)
    assert r.status_code == 429 and "2 lectures" in r.json()["detail"]


def test_ocr_echec_du_moteur_ne_compte_pas(env):
    faux_ocr(erreur="Erreur d'analyse : réseau")
    f = formule(env)
    payer(env, U(), f)
    assert lire_ocr(env).status_code == 502
    faux_ocr()
    assert lire_ocr(env).json()["restant_aujourdhui"] == 29                       # la lecture ratée n'a rien consommé


@pytest.mark.parametrize("image", ["data:application/pdf;base64,AAAA" + "A" * 200, "pas-une-image" + "x" * 200, "data:image/jpeg;base64,@@@" + "!" * 200])
def test_ocr_image_invalide(env, image):
    faux_ocr()
    f = formule(env)
    payer(env, U(), f)
    assert lire_ocr(env, image=image).status_code == 422


def test_ocr_signature_obligatoire(env):
    faux_ocr()
    assert env.post("/api/formules-plateformes/ocr", json={"utilisateur": U(), "type": "plaque_marchand", "image": IMAGE}).status_code == 401


# ---------------------------------------------------------------- lot 229 : transcription vocale réservée aux abonnés
AUDIO = "data:audio/webm;base64," + __import__("base64").b64encode(b"\x1aE\xdf\xa3" + b"1" * 400).decode()


def faux_stt(texte="Bonjour, je serai en retard.", erreur=False):
    appels = []

    async def stt(octets, extension, langue):
        appels.append((len(octets), extension, langue))
        if erreur:
            raise RuntimeError("panne")
        return texte

    fp._transcrire = stt
    return appels


def voix(env, u=None, audio=AUDIO, duree=12.5):
    return appel(env, "formules-plateformes/transcrire", {"utilisateur": u or U(), "audio": audio, "duree_s": duree})


def abonne_voix(env, u=None, **plus):
    f = formule(env, nom="Voix", prix=1500, fonctions=["transcription_vocale"], **plus)
    payer(env, u or U(), f)
    return f


def test_voix_refusee_sans_abonnement_avec_le_prix(env):
    appels = faux_stt()
    formule(env, nom="Voix", prix=1500, fonctions=["transcription_vocale"])
    formule(env, nom="OCR seul", prix=100000, fonctions=["ocr_ordonnances"])           # ne débloque pas la voix : jamais citée
    r = voix(env)
    assert r.status_code == 402 and not appels
    d = r.json()["detail"]
    assert d["formule"]["nom"] == "Voix" and "1 500 FCFA" in d["message"] and d["message"].startswith("Transcription vocale réservée")


def test_voix_abonne_transcrit(env):
    appels = faux_stt()
    abonne_voix(env)
    r = voix(env)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "texte": "Bonjour, je serai en retard.", "duree_s": 12.5, "restant_aujourdhui": 9}
    assert appels == [(404, ".webm", "fr")]
    assert voix(env, U("autre")).status_code == 402


def test_voix_l_ocr_ne_debloque_pas_la_voix(env):
    faux_stt()
    f = formule(env)                                                                   # fonction OCR seulement
    payer(env, U(), f)
    assert voix(env).status_code == 402


def test_voix_limites_duree_taille_et_jour(env):
    appels = faux_stt()
    abonne_voix(env)
    assert voix(env, duree=45).status_code == 422                                       # plus de 30 s annoncées
    gros = "data:audio/webm;base64," + __import__("base64").b64encode(b"x" * 950_000).decode()
    assert voix(env, audio=gros).status_code == 413 and not appels                      # trop lourd pour 30 s
    assert env.put("/api/admin/formules-plateformes-reglages", json={"parrainage_jours": 7, "voix_par_jour": 2}).json()["voix_par_jour"] == 2
    assert voix(env).status_code == 200 and voix(env).status_code == 200
    r = voix(env)
    assert r.status_code == 429 and "2 notes" in r.json()["detail"]


def test_voix_silence_ou_panne_ne_comptent_pas(env):
    faux_stt(texte="   ")
    abonne_voix(env)
    assert voix(env).status_code == 422                                                 # aucune parole
    faux_stt(erreur=True)
    assert voix(env).status_code == 502
    faux_stt()
    assert voix(env).json()["restant_aujourdhui"] == 9                                  # rien consommé par les échecs


@pytest.mark.parametrize("audio", ["data:image/png;base64,AAAA" + "A" * 200, "pas-audio" + "x" * 200, "data:audio/webm;base64,@@@" + "!" * 200])
def test_voix_audio_invalide(env, audio):
    faux_stt()
    abonne_voix(env)
    assert voix(env, audio=audio).status_code == 422


def test_voix_signature_obligatoire(env):
    faux_stt()
    assert env.post("/api/formules-plateformes/transcrire", json={"utilisateur": U(), "audio": AUDIO, "duree_s": 5}).status_code == 401


# ── Lot 230 : super-administrateur dispensé d'abonnement ─────────────────────────────────────
def test_acces_libre_dispense_d_abonnement_ocr_et_voix(env):
    formule(env, prix=2500, nom="OCR Ordonnances")
    formule(env, nom="Voix", prix=1500, fonctions=["transcription_vocale"])
    faux_ocr()
    faux_stt()
    libre = {**U(), "acces_libre": True}
    assert lire_ocr(env, libre).status_code == 200                                 # sans avoir payé
    assert voix(env, libre).status_code == 200
    assert lire_ocr(env).status_code == 402 and voix(env).status_code == 402        # les autres restent soumis à l'abonnement


def test_acces_libre_garde_la_limite_par_jour(env):
    faux_ocr()
    libre = {**U(), "acces_libre": True}
    r = None
    for _ in range(60):
        r = lire_ocr(env, libre)
        if r.status_code != 200:
            break
    assert r.status_code == 429                                                    # la dispense ne lève pas le plafond de coût


# ── Lot 231 : abonnements actifs de plusieurs comptes ─────────────────────────────────────────
def test_abonnes_liste_les_abonnements_actifs(env):
    f = formule(env, nom="Voix", prix=1500, fonctions=["transcription_vocale"])
    abonne, autre = U(), {**U(), "id": "autre-compte"}
    payer(env, abonne, f)
    r = appel(env, "formules-plateformes/abonnes", {"utilisateurs": [abonne["id"], autre["id"], "inconnu"]})
    assert r.status_code == 200
    ab = r.json()["abonnes"]
    assert list(ab) == [abonne["id"]]                                            # seuls les comptes abonnés apparaissent
    a = ab[abonne["id"]][0]
    assert a["formule"] == "Voix" and a["fonctions"] == ["transcription_vocale"] and a["expire_le"] and a["jours_restants"] > 0


def test_abonnes_limite_de_200_comptes(env):
    assert appel(env, "formules-plateformes/abonnes", {"utilisateurs": ["x"] * 201}).status_code == 422


# ── Lot 232 : paiement PI-SPI manuel des abonnements ─────────────────────────────────────────
@pytest.fixture()
def pispi_actif(env, monkeypatch):
    """Encaissement PI-SPI réglé (banque, QR, adresse) dans la base de test."""
    import routes.pispi as pispi
    monkeypatch.setattr(pispi, "db", env.db)
    env.portal.call(env.db.settings.insert_one, {"_id": pispi.ID_PARAMETRES, "actif": True, "banque": "ecobank", "titulaire": "SAWALI SMART SYSTEMS",
                                                 "adresse_paiement": "sawali@ecobank", "qr_contenu": "00020101PISPI-TEST"})
    return pispi


def demander(env, f, u=None):
    return appel(env, "formules-plateformes/pispi/demander", {"utilisateur": u or U(), "formule_id": f["id"]})


def test_pispi_indisponible_tant_que_non_regle(env, monkeypatch):
    import routes.pispi as pispi
    monkeypatch.setattr(pispi, "db", env.db)
    f = formule(env)
    assert demander(env, f).status_code == 503


def test_pispi_demande_bloc_de_paiement_et_reprise(env, pispi_actif):
    f = formule(env, prix=2500)
    r = demander(env, f)
    assert r.status_code == 200
    d = r.json()
    assert d["reference"].startswith("ABO-") and d["statut"] == "pispi_attente" and d["automatique"] is False
    b = d["bloc"]
    assert b["montant_texte"] == "2 500 FCFA" and b["reference"] == d["reference"] and b["banque"] == "Ecobank"
    assert b["qr_data_url"].startswith("data:image/png;base64,") and "_qr_octets" not in b
    assert demander(env, f).json()["reference"] == d["reference"]                  # même demande reprise : pas de doublon
    assert env.portal.call(env.db.payments.count_documents, {"methode": "pispi"}) == 1


def test_pispi_declaration_puis_confirmation_active_la_formule(env, pispi_actif):
    f = formule(env, prix=1500)
    u = U()
    ref = demander(env, f, u).json()["reference"]
    assert appel(env, "formules-plateformes/achat", {"utilisateur": u, "deposit_id": ref}).json()["statut"] == "pispi_attente"
    # L'utilisateur a payé : il déclare la référence bancaire
    assert appel(env, "formules-plateformes/pispi/declarer", {"utilisateur": u, "reference": ref, "reference_bancaire": "TX-998877"}).json() == {"statut": "pispi_verification"}
    assert appel(env, "formules-plateformes/achat", {"utilisateur": u, "deposit_id": ref}).json()["statut"] == "pispi_verification"
    assert not acces(env, u)["actif"]                                              # pas d'activation avant la confirmation
    # L'administrateur voit la demande « à vérifier » et confirme
    liste = env.get("/api/admin/formules-plateformes/pispi").json()["demandes"]
    assert liste[0]["reference"] == ref and liste[0]["reference_bancaire"] == "TX-998877" and liste[0]["statut"] == "pispi_verification"
    assert env.post(f"/api/admin/formules-plateformes/pispi/{ref}/confirmer", json={}).json() == {"ok": True, "statut": "completed"}
    assert acces(env, u)["actif"]                                                  # formule activée, durée de la formule
    assert appel(env, "formules-plateformes/achat", {"utilisateur": u, "deposit_id": ref}).json()["statut"] == "paye"
    tx = env.portal.call(env.db.pispi_transactions.find_one, {"reference": ref}, {"_id": 0})
    assert tx["statut"] == "rapproche" and tx["reference_bancaire"] == "TX-998877" and tx["montant"] == 1500.0
    # Confirmer deux fois n'ajoute pas de jours
    expire = acces(env, u)["expire_le"]
    assert env.post(f"/api/admin/formules-plateformes/pispi/{ref}/confirmer", json={}).status_code == 200
    assert acces(env, u)["expire_le"] == expire
    assert env.get("/api/admin/formules-plateformes/pispi").json()["demandes"] == []


def test_pispi_refus_de_l_administrateur(env, pispi_actif):
    f = formule(env)
    u = U()
    ref = demander(env, f, u).json()["reference"]
    assert env.post(f"/api/admin/formules-plateformes/pispi/{ref}/refuser").status_code == 200
    assert appel(env, "formules-plateformes/achat", {"utilisateur": u, "deposit_id": ref}).json()["statut"] == "echec"
    assert not acces(env, u)["actif"]
    assert env.post(f"/api/admin/formules-plateformes/pispi/{ref}/confirmer", json={}).status_code == 409   # clôturée : plus confirmable
    assert appel(env, "formules-plateformes/pispi/declarer", {"utilisateur": u, "reference": ref, "reference_bancaire": "TX-1234"}).status_code == 409


def test_pispi_un_utilisateur_ne_declare_pas_la_demande_d_un_autre(env, pispi_actif):
    f = formule(env)
    ref = demander(env, f, U("u1")).json()["reference"]
    r = appel(env, "formules-plateformes/pispi/declarer", {"utilisateur": U("u2", "70 99 99 99"), "reference": ref, "reference_bancaire": "TX-1234"})
    assert r.status_code == 404


# ── Lot 233 : archives en ligne chiffrées ─────────────────────────────────────────────────────
@pytest.fixture()
def archives_stock(env):
    """Stockage R2 simulé : un dictionnaire chemin → octets."""
    boite = {}

    async def ecrire(chemin, octets):
        boite[chemin] = octets

    async def lire(chemin):
        return boite[chemin]

    async def effacer(chemin):
        boite.pop(chemin, None)

    fp._ecrire_archive, fp._lire_archive, fp._effacer_archive = ecrire, lire, effacer
    yield boite
    fp._ecrire_archive = fp._lire_archive = fp._effacer_archive = None


import base64 as _b64

SEL = "A" * 24
VERIF = "B" * 40
META = "M" * 40


def arch(env, action, u=None, **plus):
    return appel(env, f"formules-plateformes/archives/{action}", {"utilisateur": u or U(), **plus})


def abonne_archives(env, u=None):
    f = formule(env, nom="Archives", prix=2000, fonctions=["archives_cloud"])
    payer(env, u or U(), f)
    return f


def test_archives_refusees_sans_abonnement_avec_le_prix(env, archives_stock):
    # Lot 277 : l'espace offert est désactivé ici (0) pour vérifier le refus 402 avec le prix de la formule
    formule(env, nom="Archives", prix=2000, fonctions=["archives_cloud"])
    assert env.put("/api/admin/formules-plateformes-reglages", json={"parrainage_jours": 7, "archives_gratuit_mo": 0, "archives_gratuit_nombre": 0}).status_code == 200
    assert arch(env, "cle", sel=SEL, verif=VERIF).status_code == 200
    r = arch(env, "ajouter", meta=META, contenu=_b64.b64encode(b"x" * 100).decode())
    assert r.status_code == 402 and "2 000 FCFA" in r.json()["detail"]["message"] and not archives_stock


def test_archives_cycle_complet_et_lecture_apres_expiration(env, archives_stock):
    u = U()
    abonne_archives(env, u)
    assert arch(env, "etat", u).json()["abonne"] is True and arch(env, "etat", u).json()["sel"] is None
    # La phrase secrète n'est enregistrée qu'une fois (sel et jeton de contrôle seulement)
    assert arch(env, "cle", u, sel=SEL, verif=VERIF).status_code == 200
    assert arch(env, "cle", u, sel=SEL, verif=VERIF).status_code == 200                 # même sel : sans effet
    assert arch(env, "cle", u, sel="C" * 24, verif=VERIF).status_code == 409             # autre sel : refusé (documents illisibles sinon)
    secret = bytes(range(200))
    r = arch(env, "ajouter", u, meta=META, contenu=_b64.b64encode(secret).decode())
    assert r.status_code == 200
    aid = r.json()["id"]
    assert list(archives_stock.values()) == [secret]                                     # octets gardés tels quels : jamais lus ni modifiés
    liste = arch(env, "liste", u).json()["archives"]
    assert [a["id"] for a in liste] == [aid] and liste[0]["meta"] == META and liste[0]["taille"] == 200
    assert arch(env, "etat", u).json()["utilise_octets"] == 200 and arch(env, "etat", u).json()["nombre"] == 1
    # Fin de l'abonnement : on peut toujours LIRE et SUPPRIMER, plus ajouter
    env.portal.call(env.db.membres_plateformes.update_many, {}, {"$set": {"abonnements": {}}})
    assert arch(env, "etat", u).json()["abonne"] is False
    dl = arch(env, "telecharger", u, id=aid).json()
    assert _b64.b64decode(dl["contenu"]) == secret and dl["meta"] == META
    env.put("/api/admin/formules-plateformes-reglages", json={"parrainage_jours": 7, "archives_gratuit_mo": 0, "archives_gratuit_nombre": 0})   # lot 277 : sans espace offert
    assert arch(env, "ajouter", u, meta=META, contenu=_b64.b64encode(b"y" * 100).decode()).status_code == 402
    assert arch(env, "supprimer", u, id=aid).status_code == 200
    assert arch(env, "liste", u).json()["archives"] == [] and not archives_stock
    assert arch(env, "telecharger", u, id=aid).status_code == 404


def test_archives_cloisonnees_par_utilisateur(env, archives_stock):
    a, b = U("u1"), U("u2", "70 99 99 99")
    abonne_archives(env, a)
    arch(env, "cle", a, sel=SEL, verif=VERIF)
    aid = arch(env, "ajouter", a, meta=META, contenu=_b64.b64encode(b"z" * 100).decode()).json()["id"]
    assert arch(env, "liste", b).json()["archives"] == []
    assert arch(env, "telecharger", b, id=aid).status_code == 404 and arch(env, "supprimer", b, id=aid).status_code == 404


def test_archives_limites_de_taille_et_d_espace(env, archives_stock):
    u = {**U(), "acces_libre": True}                                                      # administrateur : dispensé d'abonnement
    arch(env, "cle", u, sel=SEL, verif=VERIF)
    assert arch(env, "ajouter", u, meta=META, contenu="@@@@" * 20).status_code == 422     # pas du base64
    gros = _b64.b64encode(b"g" * (fp.ARCHIVE_FICHIER_MAX + 1)).decode()
    assert arch(env, "ajouter", u, meta=META, contenu=gros).status_code == 413
    assert env.put("/api/admin/formules-plateformes-reglages", json={"parrainage_jours": 7, "archives_mo": 10}).status_code == 200      # espace : 10 Mo
    un_peu_moins = _b64.b64encode(b"q" * 6_000_000).decode()
    assert arch(env, "ajouter", u, meta=META, contenu=un_peu_moins).status_code == 200
    r = arch(env, "ajouter", u, meta=META, contenu=un_peu_moins)
    assert r.status_code == 413 and "plein" in r.json()["detail"]


def test_archives_phrase_obligatoire_avant_d_ajouter(env, archives_stock):
    u = {**U(), "acces_libre": True}
    r = arch(env, "ajouter", u, meta=META, contenu=_b64.b64encode(b"x" * 100).decode())
    assert r.status_code == 409 and "phrase secrète" in r.json()["detail"]


def test_archives_reglage_admin_de_l_espace(env):
    assert env.get("/api/admin/formules-plateformes").json()["archives_mo"] == 200
    assert env.put("/api/admin/formules-plateformes-reglages", json={"parrainage_jours": 7, "archives_mo": 500}).json()["archives_mo"] == 500
    assert env.get("/api/admin/formules-plateformes").json()["archives_mo"] == 500


def test_archives_modifier_les_informations_chiffrees(env, archives_stock):
    u = U()
    abonne_archives(env, u)
    arch(env, "cle", u, sel=SEL, verif=VERIF)
    aid = arch(env, "ajouter", u, meta=META, contenu=_b64.b64encode(b"d" * 100).decode()).json()["id"]
    nouvelle = "N" * 48
    assert arch(env, "modifier", u, id=aid, meta=nouvelle).status_code == 200
    assert arch(env, "liste", u).json()["archives"][0]["meta"] == nouvelle
    assert list(archives_stock.values()) == [b"d" * 100]                                  # le document lui-même n'a pas bougé
    env.portal.call(env.db.membres_plateformes.update_many, {}, {"$set": {"abonnements": {}}})
    assert arch(env, "modifier", u, id=aid, meta="P" * 48).status_code == 200              # permis sans abonnement
    assert arch(env, "modifier", U("u2", "70 99 99 99"), id=aid, meta=nouvelle).status_code == 404    # jamais le document d'un autre


# ----------------------------------------------------------------------------------------------- lot 244 : achat groupé
def deux_formules(env):
    a = formule(env, nom="OCR", prix=1000, fonctions=["ocr_ordonnances"])
    b = formule(env, nom="Voix", prix=1500, duree_jours=15, fonctions=["transcription_vocale"])
    return a, b


def test_devis_total_de_plusieurs_formules(env):
    a, b = deux_formules(env)
    r = appel(env, "formules-plateformes/devis", {"utilisateur": U(), "formule_ids": [a["id"], b["id"]]})
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 2500 and d["nombre"] == 2 and [x["nom"] for x in d["lignes"]] == ["OCR", "Voix"]
    assert appel(env, "formules-plateformes/devis", {"utilisateur": U(), "formule_ids": [a["id"], "inconnue"]}).status_code == 404
    assert appel(env, "formules-plateformes/devis", {"utilisateur": U(), "formule_ids": []}).status_code == 422


def test_achat_groupe_un_seul_paiement_du_total_active_tout(env):
    a, b = deux_formules(env)
    envoyes = []

    def espion(requete: httpx.Request) -> httpx.Response:
        envoyes.append(json.loads(requete.content))
        return httpx.Response(200, json={"redirectUrl": "https://pay.pawapay.test/x"})

    fp._transport = httpx.MockTransport(espion)
    # Le doublon est ignoré ; le montant envoyé à PawaPay est la SOMME des prix lus en base (jamais un montant venu de la plateforme)
    r = appel(env, "formules-plateformes/acheter", {"utilisateur": U(), "formule_ids": [a["id"], b["id"], a["id"]], "retour": "https://site.test/abonnement"})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 2500 and len(r.json()["lignes"]) == 2
    assert envoyes[0]["amountDetails"]["amount"] == "2500" and len(envoyes) == 1
    dep = r.json()["deposit_id"]
    env.portal.call(env.db.payments.update_one, {"deposit_id": dep}, {"$set": {"status": "completed"}})
    p = env.portal.call(env.db.payments.find_one, {"deposit_id": dep}, {"_id": 0})
    env.portal.call(env.hooks[0], p)
    env.portal.call(env.hooks[0], p)                                       # rejeu du webhook : activation unique
    ab = {x["formule_id"]: x for x in appel(env, "formules-plateformes/catalogue", {"utilisateur": U()}).json()["abonnements"]}
    assert ab[a["id"]]["actif"] and ab[b["id"]]["actif"] and ab[b["id"]]["jours_restants"] == 15
    # État de l'achat et statistiques : une vente et le prix de chaque ligne pour chaque formule
    assert appel(env, "formules-plateformes/achat", {"utilisateur": U(), "deposit_id": dep}).json()["formule_ids"] == [a["id"], b["id"]]
    stats = {f["id"]: f for f in env.get("/api/admin/formules-plateformes").json()["formules"]}
    assert stats[a["id"]]["chiffre"] == 1000 and stats[b["id"]]["chiffre"] == 1500 and stats[b["id"]]["ventes"] == 1


def test_achat_une_seule_formule_ancien_mode_inchange(env):
    a, _ = deux_formules(env)
    r = appel(env, "formules-plateformes/acheter", {"utilisateur": U(), "formule_id": a["id"]})
    assert r.status_code == 200 and r.json()["total"] == 1000


def test_achat_groupe_formule_inconnue_ou_vide(env):
    a, _ = deux_formules(env)
    assert appel(env, "formules-plateformes/acheter", {"utilisateur": U(), "formule_ids": [a["id"], "inconnue"]}).status_code == 404
    assert appel(env, "formules-plateformes/acheter", {"utilisateur": U()}).status_code == 422


def test_pispi_groupe_montant_total_reprise_et_confirmation(env, pispi_actif):
    a, b = deux_formules(env)
    r = appel(env, "formules-plateformes/pispi/demander", {"utilisateur": U(), "formule_ids": [a["id"], b["id"]]})
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 2500 and d["bloc"]["montant_texte"] == "2 500 FCFA"
    # Même sélection (dans un autre ordre) : demande reprise ; autre sélection : nouvelle demande
    assert appel(env, "formules-plateformes/pispi/demander", {"utilisateur": U(), "formule_ids": [b["id"], a["id"]]}).json()["reference"] == d["reference"]
    assert appel(env, "formules-plateformes/pispi/demander", {"utilisateur": U(), "formule_ids": [a["id"]]}).json()["reference"] != d["reference"]
    # Confirmation par l'administrateur : les deux formules s'activent
    appel(env, "formules-plateformes/pispi/declarer", {"utilisateur": U(), "reference": d["reference"], "reference_bancaire": "VIR-0001"})
    assert env.post(f"/api/admin/formules-plateformes/pispi/{d['reference']}/confirmer", json={}).status_code == 200
    ab = {x["formule_id"]: x for x in appel(env, "formules-plateformes/catalogue", {"utilisateur": U()}).json()["abonnements"]}
    assert ab[a["id"]]["actif"] and ab[b["id"]]["actif"]


# ── Lot 277 : espace gratuit, enveloppes de la clé (phrase + code de secours) ─────────────────
def test_archives_espace_gratuit_sans_abonnement(env, archives_stock):
    u = U()
    formule(env, nom="Archives", prix=2000, fonctions=["archives_cloud"])
    e = arch(env, "etat", u).json()
    assert e["abonne"] is False and e["quota_octets"] == 50_000_000 and e["nombre_max"] == 30       # valeurs par défaut offertes
    arch(env, "cle", u, sel=SEL, verif=VERIF)
    assert arch(env, "ajouter", u, meta=META, contenu=_b64.b64encode(b"d" * 100).decode()).status_code == 200   # sans abonnement : permis
    # nombre de documents limité
    env.put("/api/admin/formules-plateformes-reglages", json={"parrainage_jours": 7, "archives_gratuit_nombre": 1})
    r = arch(env, "ajouter", u, meta=META, contenu=_b64.b64encode(b"e" * 100).decode())
    assert r.status_code == 402 and "Espace gratuit atteint" in r.json()["detail"]["message"] and "2 000 FCFA" in r.json()["detail"]["message"]
    # espace en octets limité
    env.put("/api/admin/formules-plateformes-reglages", json={"parrainage_jours": 7, "archives_gratuit_nombre": 30, "archives_gratuit_mo": 1})
    r = arch(env, "ajouter", u, meta=META, contenu=_b64.b64encode(b"f" * 1_500_000).decode())
    assert r.status_code == 402
    # un abonné n'est pas concerné par l'espace offert
    abonne_archives(env, u)
    assert arch(env, "etat", u).json()["quota_octets"] == 200_000_000 and arch(env, "etat", u).json()["nombre_max"] is None
    assert arch(env, "ajouter", u, meta=META, contenu=_b64.b64encode(b"f" * 1_500_000).decode()).status_code == 200


def test_archives_reglage_admin_espace_gratuit(env):
    g = env.get("/api/admin/formules-plateformes").json()
    assert g["archives_gratuit_mo"] == 50 and g["archives_gratuit_nombre"] == 30
    r = env.put("/api/admin/formules-plateformes-reglages", json={"parrainage_jours": 7, "archives_gratuit_mo": 80, "archives_gratuit_nombre": 40}).json()
    assert r["archives_gratuit_mo"] == 80 and r["archives_gratuit_nombre"] == 40


def test_archives_enveloppes_phrase_et_code_de_secours(env, archives_stock):
    u = U()
    ENV1, SEC1, ENV2 = "E" * 40, "S" * 40, "N" * 40
    assert arch(env, "cle", u, sel=SEL, verif=VERIF, enveloppe=ENV1, secours=SEC1).status_code == 200
    e = arch(env, "etat", u).json()
    assert e["enveloppe"] == ENV1 and e["secours"] == SEC1 and e["verif"] == VERIF
    # nouvelle phrase (après usage du code de secours) : exige le jeton de contrôle actuel
    assert arch(env, "enveloppes", u, verif_actuelle="X" * 40, enveloppe=ENV2).status_code == 409
    assert arch(env, "enveloppes", u, verif_actuelle=VERIF, enveloppe=ENV2).status_code == 200
    e = arch(env, "etat", u).json()
    assert e["enveloppe"] == ENV2 and e["secours"] == SEC1                                  # le secours n'a pas bougé
    # ancienne clé sans enveloppe (avant le lot 277) : mise à niveau possible avec le jeton
    v = U("u9", "70 55 55 55")
    arch(env, "cle", v, sel=SEL, verif=VERIF)
    assert arch(env, "etat", v).json()["enveloppe"] is None
    assert arch(env, "enveloppes", v, verif_actuelle=VERIF, enveloppe=ENV1, secours=SEC1).status_code == 200
    assert arch(env, "etat", v).json()["secours"] == SEC1
    # inconnu : pas de clé enregistrée
    assert arch(env, "enveloppes", U("u7", "70 44 44 44"), verif_actuelle=VERIF, enveloppe=ENV1).status_code == 409


# ── Lot 278 : code PIN / phrase courte, essais limités côté serveur ─────────────────────────
PREUVE = "P" * 43 + "="
AUTRE = "Q" * 43 + "="


def test_archives_pin_enregistrer_ouvrir_et_poivre(env):
    u = U()
    r = arch(env, "pin/enregistrer", u, preuve=PREUVE, type_secret="pin")
    assert r.status_code == 200 and len(r.json()["poivre"]) == 44
    poivre = r.json()["poivre"]
    assert arch(env, "etat", u).json()["pin"] == "pin"
    o = arch(env, "pin/ouvrir", u, preuve=PREUVE)
    assert o.status_code == 200 and o.json()["poivre"] == poivre                    # même poivre à chaque bonne ouverture
    # poivre propre à chaque utilisateur, même avec la même preuve (même code)
    v = U("u2", "70 99 99 99")
    assert arch(env, "pin/enregistrer", v, preuve=PREUVE).json()["poivre"] != poivre
    # sans enregistrement : 404
    assert arch(env, "pin/ouvrir", U("u3", "70 33 33 33"), preuve=PREUVE).status_code == 404


def test_archives_pin_pause_apres_cinq_essais_puis_secours_apres_dix(env):
    u = U()
    arch(env, "pin/enregistrer", u, preuve=PREUVE)
    for restant in (4, 3, 2, 1):
        r = arch(env, "pin/ouvrir", u, preuve=AUTRE)
        assert r.status_code == 409 and f"{restant} essai" in r.json()["detail"]
    r = arch(env, "pin/ouvrir", u, preuve=AUTRE)
    assert r.status_code == 429 and "15 min" in r.json()["detail"]                  # 5e échec : pause
    assert arch(env, "pin/ouvrir", u, preuve=PREUVE).status_code == 429             # même la bonne preuve est refusée pendant la pause
    # fin de la pause : la bonne preuve passe et remet les compteurs à zéro
    env.portal.call(env.db.membres_plateformes.update_many, {}, {"$set": {"archives_pin.bloque_jusqu": "2000-01-01T00:00:00+00:00"}})
    assert arch(env, "pin/ouvrir", u, preuve=PREUVE).status_code == 200
    # 10 échecs sans réussite entre deux : code de secours nécessaire, même avec la bonne preuve
    for _ in range(10):
        env.portal.call(env.db.membres_plateformes.update_many, {}, {"$set": {"archives_pin.bloque_jusqu": None}})
        arch(env, "pin/ouvrir", u, preuve=AUTRE)
    r = arch(env, "pin/ouvrir", u, preuve=PREUVE)
    assert r.status_code == 429 and "code de secours" in r.json()["detail"]


def test_archives_pin_remplacement_exige_le_jeton_et_change_le_poivre(env):
    u = U()
    arch(env, "cle", u, sel=SEL, verif=VERIF)
    assert arch(env, "pin/enregistrer", u, preuve=PREUVE).status_code == 409                        # archives existantes : jeton obligatoire
    assert arch(env, "pin/enregistrer", u, preuve=PREUVE, verif_actuelle="X" * 40).status_code == 409
    p1 = arch(env, "pin/enregistrer", u, preuve=PREUVE, verif_actuelle=VERIF).json()["poivre"]
    # après des échecs (récupération par le code de secours) : nouvelle preuve, compteurs remis à zéro, poivre renouvelé
    for _ in range(3):
        arch(env, "pin/ouvrir", u, preuve=AUTRE)
    p2 = arch(env, "pin/enregistrer", u, preuve=AUTRE, type_secret="phrase", verif_actuelle=VERIF).json()["poivre"]
    assert p2 != p1 and arch(env, "etat", u).json()["pin"] == "phrase"
    assert arch(env, "pin/ouvrir", u, preuve=AUTRE).json()["poivre"] == p2
    assert arch(env, "pin/ouvrir", u, preuve=PREUVE).status_code == 409                              # l'ancienne preuve ne passe plus


def test_archives_pin_preuve_jamais_gardee_en_clair(env):
    u = U()
    arch(env, "pin/enregistrer", u, preuve=PREUVE)
    doc = env.portal.call(env.db.membres_plateformes.find_one, {"utilisateur_id": u["id"]}, {"_id": 0})
    assert PREUVE not in json.dumps(doc) and len(doc["archives_pin"]["preuve_hash"]) == 64
    assert arch(env, "pin/enregistrer", u, preuve="trop court").status_code == 422
