"""Lot 227 — formules (abonnements) et parrainage des plateformes : catalogue, achat PawaPay, activation cumulée, parrainage.
MongoDB simulé, PawaPay simulé (httpx.MockTransport). Lancer : cd backend && python -m pytest tests/test_lot227_formules_plateformes.py -q"""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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
