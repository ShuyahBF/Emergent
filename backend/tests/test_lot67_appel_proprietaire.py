"""Lot 67 — Liluvine prévient le propriétaire : relais WhatsApp puis appel vocal.

Logique de décision (autorisation par défaut sur la fiche, anti-répétition 30 min, heures calmes,
exclusions), mise en forme des messages et des dates (Africa/Ouagadougou = UTC), relais (texte
libre ou modèle), autorisation d'appel, journal ; puis un appel complet de bout en bout entre
deux interlocuteurs WebRTC LOCAUX (aiortc) : « Meta » simulé répond à l'offre et reçoit la voix.
MongoDB simulé, API Graph factice : aucun appel réseau.
Lancer : cd backend && python -m pytest tests/test_lot67_appel_proprietaire.py -q
"""
from __future__ import annotations

import asyncio
import math
import struct
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
REGLAGES = {
    "_id": "global", "wa_phone_number_id": "PN-STANDARD", "wa_access_token": "jeton-factice",
    "wa_numeros": [{"id": "PN-VIP", "libelle": "Liluvine VIP", "telephone": "+226 73 88 49 99"}],
    "appel_proprio_numeros": "+226 70 99 99 99",
}


def lancer(coro):
    """Exécute une coroutine dans une boucle neuve."""
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def env(monkeypatch):
    """Base simulée, horloge fixe, API Graph factice (requêtes mémorisées), appel vocal simulé."""
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot67"]
    lancer(db.settings.insert_one(dict(REGLAGES)))
    lancer(db.users.insert_one({"id": "sawali", "role": "superviseur", "phone": "+22671111111"}))
    lancer(db.directory_contacts.insert_one(
        {"id": "c1", "client_id": "sawali", "name": "Awa Kaboré", "whatsapp": f"+{CLIENT}"}))
    horloge = {"t": INSTANT}
    monkeypatch.setattr(ap, "_maintenant", lambda: horloge["t"])
    monkeypatch.delenv("NUMERO_APPEL_PROPRIETAIRE", raising=False)
    requetes = []
    permission = {"status": "temporary"}

    async def faux_post(s, numero_id, chemin, corps):
        requetes.append((numero_id, chemin, corps))
        if chemin == "messages":
            return {"ok": True, "donnees": {"messages": [{"id": f"wamid.{len(requetes)}"}]}, "erreur": None}
        return {"ok": True, "donnees": {"success": True}, "erreur": None}

    async def faux_get(s, numero_id, chemin, params):
        return {"ok": True, "donnees": {"permission": dict(permission), "actions": [
            {"action_name": "start_call", "can_perform_action": permission["status"] != "no_permission"},
            {"action_name": "send_call_permission_request", "can_perform_action": True}]}, "erreur": None}

    appels = []

    async def faux_appel(db_, s, cfg, *, numero_id, ligne_cle, proprio, texte_voix, alerte):
        # Appel simulé : ligne de journal comme le vrai, résultat « décroché »
        appels.append({"proprio": proprio, "texte": texte_voix, "numero_id": numero_id})
        await db_.wa_appels.insert_one({"id": f"wacid.{len(appels)}", "direction": "sortant", "motif": ap.MOTIF,
                                        "telephone": proprio, "created_at": ap._maintenant().isoformat(),
                                        "resultat": "décroché", **alerte})
        return {"resultat": "décroché"}

    monkeypatch.setattr(ap, "_graph_post", faux_post)
    monkeypatch.setattr(ap, "_graph_get", faux_get)
    monkeypatch.setattr(ap, "appeler_et_parler", faux_appel)
    ap._verrous_clients.clear()
    ap._verrou_appel = None
    return {"db": db, "horloge": horloge, "requetes": requetes, "appels": appels, "permission": permission}


def message(db, texte="Bonjour, ma commande ?", de=CLIENT, mtype="text", contact=None):
    """Traite un message reçu (comme le webhook, mais en attendant le résultat)."""
    if contact is None:
        contact = {"id": "c1", "name": "Awa Kaboré", "client_id": "sawali"}
    return lancer(ap.traiter_message(db, chiffres=de, mtype=mtype, texte=texte, contact=contact,
                                     recu_le=INSTANT.isoformat(), client_id="sawali"))


def relais_envoyes(requetes):
    """Messages relayés (texte ou modèle) envoyés au propriétaire."""
    return [c for (_, chemin, c) in requetes if chemin == "messages" and c.get("type") in ("text", "template")]


# ---------------------------------------------------------------------------
# Mise en forme
# ---------------------------------------------------------------------------

def test_dates_et_textes():
    assert ap.formater_date(INSTANT) == "06/10/2026 14:05"
    # Sans fuseau = UTC ; Ouagadougou = UTC toute l'année
    assert ap.formater_date(datetime(2026, 1, 1, 0, 0)) == "01/01/2026 00:00"
    assert ap.date_parlee(INSTANT) == ("6 octobre 2026", "14 heures 05")
    assert ap.date_parlee(datetime(2026, 8, 1, 1, 0, tzinfo=timezone.utc)) == ("1er août 2026", "1 heure")
    assert ap.texte_relais("Awa Kaboré (+22670000001)", "Bonjour\n  ma commande ?", INSTANT) == \
        '📩 Awa Kaboré (+22670000001) écrit au support : "Bonjour ma commande ?" — 06/10/2026 14:05'
    assert ap.texte_parle("Awa Kaboré", INSTANT) == (
        "Bonjour, ici Liluvine. Awa Kaboré écrit au support. "
        "Son dernier message date du 6 octobre 2026 à 14 heures 05.")
    # Sans nom (ou nom = numéro) : numéro affiché / prononcé par paires
    assert ap.nom_affiche({"name": "+226 70 00 00 01"}, None, CLIENT) == "+22670000001"
    assert ap.nom_parle(None, None, CLIENT) == "le numéro 70 00 00 01"
    assert ap.nom_parle(None, "Awa", CLIENT) == "Awa"
    assert len(ap.extrait("x" * 500)) == 200
    # Découpage pour la voix Google (moins de 200 caractères par morceau)
    morceaux = ap.decouper_texte("Bonjour. " * 60)
    assert all(len(m) <= 180 for m in morceaux) and "".join(morceaux).count("Bonjour") == 60


def test_heures_calmes():
    cfg = {"calme_actif": True, "calme_debut": "22:00", "calme_fin": "06:00"}
    a = lambda h, m: datetime(2026, 10, 6, h, m, tzinfo=timezone.utc)  # noqa: E731
    assert ap.en_heures_calmes(cfg, a(23, 0)) and ap.en_heures_calmes(cfg, a(5, 59))
    assert not ap.en_heures_calmes(cfg, a(6, 0)) and not ap.en_heures_calmes(cfg, a(12, 0))
    assert not ap.en_heures_calmes({**cfg, "calme_actif": False}, a(23, 0))
    jour = {"calme_actif": True, "calme_debut": "12:00", "calme_fin": "14:00"}
    assert ap.en_heures_calmes(jour, a(13, 0)) and not ap.en_heures_calmes(jour, a(14, 0))


def test_reglages_par_defaut_et_numero(monkeypatch):
    monkeypatch.delenv("NUMERO_APPEL_PROPRIETAIRE", raising=False)
    cfg = ap.reglages({})
    assert cfg["actif"] and cfg["fenetre_min"] == 30 and not cfg["calme_actif"] and cfg["numeros"] == []
    assert cfg["repetitions"] == 2 and cfg["sonnerie_s"] == 30 and cfg["ligne"] == "principal"
    # Numéro lu dans la variable d'environnement si le réglage est vide
    monkeypatch.setenv("NUMERO_APPEL_PROPRIETAIRE", "+226 70 99 99 99; +33 6 11 22 33 44")
    assert ap.reglages({})["numeros"] == ["22670999999", "33611223344"]
    assert ap.reglages({"appel_proprio_numeros": "+22655555555"})["numeros"] == ["22655555555"]


def test_autorisation_fiche_par_defaut():
    assert ap.contact_autorise(None) and ap.contact_autorise({}) and ap.contact_autorise({"appel_proprietaire": None})
    assert ap.contact_autorise({"appel_proprietaire": True})
    assert not ap.contact_autorise({"appel_proprietaire": False})


# ---------------------------------------------------------------------------
# Exclusions
# ---------------------------------------------------------------------------

def test_exclusions(env):
    db = env["db"]
    s = lancer(db.settings.find_one({"_id": "global"}))

    def dec(**k):
        k.setdefault("chiffres", CLIENT)
        k.setdefault("mtype", "text")
        k.setdefault("texte", "Bonjour")
        k.setdefault("contact", None)
        return lancer(ap.decision_relais(db, s, **k))

    assert dec() == (True, "ok")
    assert dec(chiffres=PROPRIO)[1] == "message du propriétaire lui-même"
    assert dec(texte="!aide")[1] == "commande Liluvine"
    assert dec(mtype="interactive")[0] is False and dec(mtype="reaction")[0] is False
    assert dec(contact={"appel_proprietaire": False})[1] == "alerte désactivée sur la fiche du client"
    assert dec(chiffres="22673884999")[1] == "numéro exclu"           # numéro de la ligne VIP elle-même
    assert dec(chiffres="22671111111")[1] == "numéro du personnel SAWALI"
    lancer(db.liluvine_commandes_bloquees.insert_one({"actif": True, "chiffres": "22670000002"}))
    assert dec(chiffres="22670000002")[1] == "numéro en liste noire"
    assert lancer(ap.decision_relais(db, {**s, "appel_proprio_exclus": "+226 70 00 00 03"},
                                     chiffres="22670000003", mtype="text", texte="x", contact=None))[1] == "numéro exclu"
    assert lancer(ap.decision_relais(db, {**s, "appel_proprio_actif": False}, chiffres=CLIENT, mtype="text",
                                     texte="x", contact=None))[1] == "alerte désactivée"
    assert lancer(ap.decision_relais(db, {k: v for k, v in s.items() if k != "appel_proprio_numeros"},
                                     chiffres=CLIENT, mtype="text", texte="x", contact=None))[0] is False


def test_fiche_client_desactivee_rien_ne_part(env):
    db = env["db"]
    lancer(db.directory_contacts.update_one({"id": "c1"}, {"$set": {"appel_proprietaire": False}}))
    r = message(db)          # la fiche est relue : le webhook ne transmet pas ce champ
    assert r["raison"] == "alerte désactivée sur la fiche du client"
    assert env["requetes"] == [] and env["appels"] == []


# ---------------------------------------------------------------------------
# Relais + appel, anti-répétition, heures calmes
# ---------------------------------------------------------------------------

def test_relais_puis_appel_et_anti_repetition(env):
    db, req, appels, horloge = env["db"], env["requetes"], env["appels"], env["horloge"]
    # Le propriétaire a écrit il y a 2 h : fenêtre de 24 h ouverte → texte libre
    lancer(db.whatsapp_messages.insert_one({"direction": "inbound", "phone_digits": PROPRIO, "wa_numero_id": "PN-STANDARD",
                                            "created_at": (INSTANT - timedelta(hours=2)).isoformat()}))
    r = message(db)
    relais = relais_envoyes(req)
    assert len(relais) == 1 and relais[0]["type"] == "text" and relais[0]["to"] == PROPRIO
    assert relais[0]["text"]["body"] == \
        '📩 Awa Kaboré (+22670000001) écrit au support : "Bonjour, ma commande ?" — 06/10/2026 14:05'
    assert r["appel"]["resultat"] == "décroché" and len(appels) == 1
    assert appels[0]["numero_id"] == "PN-STANDARD"
    assert appels[0]["texte"].startswith("Bonjour, ici Liluvine. Awa Kaboré écrit au support.")
    # Trace du relais dans la conversation du propriétaire
    assert lancer(db.whatsapp_messages.count_documents({"alerte_proprietaire": True})) == 1
    # 10 min plus tard : relais oui, appel non (au plus un appel par client / 30 min)
    horloge["t"] = INSTANT + timedelta(minutes=10)
    r2 = message(db, "Vous êtes là ?")
    assert len(relais_envoyes(req)) == 2 and len(appels) == 1
    assert "moins de 30 min" in r2["raison"]
    # Un AUTRE client dans la même période : il est appelé
    message(db, "Bonjour", de="22670000009", contact={"id": None, "name": "Moussa"})
    assert len(appels) == 2
    # 31 min après le premier appel : nouvel appel
    horloge["t"] = INSTANT + timedelta(minutes=31)
    message(db, "Toujours là ?")
    assert len(appels) == 3


def test_heures_calmes_relais_seul(env):
    db = env["db"]
    lancer(db.settings.update_one({"_id": "global"}, {"$set": {"appel_proprio_calme_actif": True}}))
    env["horloge"]["t"] = datetime(2026, 10, 6, 23, 30, tzinfo=timezone.utc)
    r = message(db)
    assert r["raison"] == "heures calmes : relais seul"
    assert len(relais_envoyes(env["requetes"])) == 1 and env["appels"] == []


def test_relais_hors_fenetre_modele_ou_texte(env):
    db, req = env["db"], env["requetes"]
    # Pas de modèle déclaré : texte libre tenté (Meta refusera hors fenêtre) — réponse simulée OK ici
    message(db)
    assert relais_envoyes(req)[0]["type"] == "text"
    # Modèle déclaré : envoyé hors fenêtre avec 3 variables (qui, extrait, date)
    lancer(db.settings.update_one({"_id": "global"}, {"$set": {"appel_proprio_modele": "alerte_support"}}))
    env["horloge"]["t"] = INSTANT + timedelta(minutes=5)
    message(db)
    modele = relais_envoyes(req)[-1]
    assert modele["type"] == "template" and modele["template"]["name"] == "alerte_support"
    valeurs = [p["text"] for p in modele["template"]["components"][0]["parameters"]]
    assert valeurs == ["Awa Kaboré (+22670000001)", "Bonjour, ma commande ?", "06/10/2026 14:05"]


def test_relais_echec_hors_fenetre_message_explicite(env, monkeypatch):
    db = env["db"]

    async def refus(s, numero_id, chemin, corps):
        return {"ok": False, "donnees": {}, "erreur": "Meta : Re-engagement message"}
    monkeypatch.setattr(ap, "_graph_post", refus)
    r = message(db)
    assert "fenêtre de 24 h fermée" in r["relais"][0]["erreur"]
    assert env["appels"]       # l'appel est tenté quand même


def test_autorisation_en_attente_demande_envoyee_une_fois(env):
    db, req = env["db"], env["requetes"]
    env["permission"]["status"] = "no_permission"
    r = message(db)
    assert r["raison"] == "autorisation d'appel du propriétaire en attente" and env["appels"] == []
    demandes = [c for (_, ch, c) in req if c.get("type") == "interactive"]
    assert len(demandes) == 1 and demandes[0]["interactive"]["type"] == "call_permission_request"
    # Message suivant d'un autre client : pas de nouvelle demande (au plus une fois / 7 jours)
    message(db, de="22670000009", contact={"id": None, "name": "Moussa"})
    assert len([c for (_, ch, c) in req if c.get("type") == "interactive"]) == 1
    etat = lancer(ap.etat_permission(db, {}, "PN-STANDARD", PROPRIO))
    assert etat["etat"] in ("en_attente", "inconnue") and etat["demande_le"]


def test_ligne_choisie_et_appel_desactive(env):
    db = env["db"]
    lancer(db.settings.update_one({"_id": "global"}, {"$set": {"appel_proprio_ligne": "PN-VIP",
                                                               "appel_proprio_appel_actif": False}}))
    r = message(db)
    assert env["requetes"][0][0] == "PN-VIP"            # relais envoyé depuis la ligne VIP
    assert r["raison"] == "appel vocal désactivé (relais seul)" and env["appels"] == []


def test_planifier_ne_leve_jamais(env, monkeypatch):
    async def casse(*a, **k):
        raise RuntimeError("panne")
    monkeypatch.setattr(ap, "traiter_message", casse)

    async def scenario():
        ap.planifier(env["db"], chiffres=CLIENT, mtype="text", texte="x")
        await asyncio.sleep(0.05)
    lancer(scenario())           # aucune exception ne remonte
    ap.planifier(env["db"], chiffres=CLIENT)   # hors boucle : ignoré sans erreur


# ---------------------------------------------------------------------------
# Appel réel (aiortc) : repli et appel de bout en bout en local
# ---------------------------------------------------------------------------

def test_moteur_absent_echec_journalise(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot67b"]
    monkeypatch.setattr(ap, "moteur_disponible", lambda: (False, "aiortc indisponible : test"))
    r = lancer(ap.appeler_et_parler(db, {}, ap.reglages({}), numero_id="PN", ligne_cle="principal", proprio=PROPRIO,
                                    texte_voix="Bonjour", alerte={"alerte_client_telephone": CLIENT}))
    assert r["resultat"] == "échec"
    doc = lancer(db.wa_appels.find_one({"motif": ap.MOTIF}))
    assert doc["statut"] == "echec" and doc["direction"] == "sortant" and "aiortc" in doc["raison"]


def _wav_sinus(secondes=0.6, frequence=440):
    """Petit fichier WAV (sinus 16 kHz) pour simuler la voix de Liluvine."""
    n = int(16000 * secondes)
    pcm = b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * frequence * i / 16000))) for i in range(n))
    entete = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack(
        "<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16) + b"data" + struct.pack("<I", len(pcm))
    return entete + pcm


def test_decodage_pcm_48k():
    pytest.importorskip("av")
    pcm = ap.decoder_pcm(_wav_sinus(0.5))
    # 0,5 s à 48 kHz, 16 bits mono ≈ 48 000 octets (tolérance du rééchantillonnage)
    assert abs(len(pcm) - 48000) < 4000


def test_appel_de_bout_en_bout_local(monkeypatch):
    """Le serveur appelle ; « Meta » (2e interlocuteur aiortc local) répond via le webhook,
    reçoit la voix, puis l'appel est terminé et journalisé « décroché »."""
    pytest.importorskip("aiortc")
    from aiortc import RTCPeerConnection, RTCSessionDescription

    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot67c"]
    monkeypatch.setattr(ap, "serveurs_ice", lambda: [])          # pas de STUN : tout reste local

    async def voix(texte, s, cfg):
        return _wav_sinus(0.6), "test"
    monkeypatch.setattr(ap, "synthetiser", voix)
    actions = []
    recu = {"trames": 0, "son": 0}

    async def scenario():
        meta = RTCPeerConnection()

        @meta.on("track")
        def sur_piste(piste):
            async def lire():
                while True:
                    try:
                        trame = await piste.recv()
                    except Exception:  # noqa: BLE001 — fin de l'appel
                        return
                    recu["trames"] += 1
                    if any(bytes(trame.planes[0])[:200]):
                        recu["son"] += 1
            asyncio.ensure_future(lire())

        async def faux_post(s, numero_id, chemin, corps):
            actions.append(corps.get("action"))
            if corps.get("action") == "connect":
                # « Meta » prépare sa réponse SDP puis l'envoie par le webhook « calls » (après 0,5 s)
                await meta.setRemoteDescription(RTCSessionDescription(sdp=corps["session"]["sdp"], type="offer"))
                await meta.setLocalDescription(await meta.createAnswer())

                async def webhook():
                    await asyncio.sleep(0.5)
                    await aw.traiter_webhook_appels(db, {"calls": [{
                        "id": "wacid.LOCAL", "event": "connect", "direction": "BUSINESS_INITIATED",
                        "session": {"sdp_type": "answer", "sdp": meta.localDescription.sdp}}]})
                asyncio.ensure_future(webhook())
                return {"ok": True, "donnees": {"calls": [{"id": "wacid.LOCAL"}]}, "erreur": None}
            return {"ok": True, "donnees": {"success": True}, "erreur": None}
        monkeypatch.setattr(ap, "_graph_post", faux_post)
        cfg = {**ap.reglages({}), "repetitions": 1, "sonnerie_s": 10}
        res = await ap.appeler_et_parler(db, {}, cfg, numero_id="PN", ligne_cle="principal", proprio=PROPRIO,
                                         texte_voix="Bonjour", alerte={"alerte_client_telephone": CLIENT,
                                                                       "alerte_client_nom": "Awa"})
        await meta.close()
        return res

    res = asyncio.run(asyncio.wait_for(scenario(), 40))
    assert res["resultat"] == "décroché", res
    assert actions == ["connect", "terminate"]
    assert recu["trames"] > 20 and recu["son"] > 5            # la voix a bien été reçue par « Meta »
    # Lot 67.1 — mesures pour l'historique : voix, caractères, conversation mesurée par le serveur
    m = res["mesures"]
    assert m["voix"] == "test" and m["tts_caracteres"] == len("Bonjour") and m["conversation_s"] >= 1
    doc = lancer(db.wa_appels.find_one({"id": "wacid.LOCAL"}))
    assert doc["motif"] == ap.MOTIF and doc["resultat"] == "décroché" and doc["direction"] == "sortant"


def test_routes_reglages_et_journal(env):
    """Réglages (lecture, enregistrement contrôlé, droits) et journal du portail avec le motif."""
    db = env["db"]
    utilisateurs = {"sup": {"id": "sawali", "role": "superviseur", "client_id": "sawali", "full_name": "Sup"},
                    "client": {"id": "x", "role": "client", "client_id": "x"}}

    async def utilisateur(request: Request):
        uid = request.headers.get("X-User")
        if uid not in utilisateurs:
            raise HTTPException(status_code=401)
        return utilisateurs[uid]

    async def perimetre(user):
        return [user.get("client_id") or user["id"]]

    api = APIRouter(prefix="/api")
    ap.setup_appel_proprietaire_routes(db=db, api=api, get_current_user=utilisateur)
    aw.setup_appels_wa_routes(db=db, api=api, get_current_user=utilisateur, resolve_visible_client_ids=perimetre)
    app = FastAPI()
    app.include_router(api)
    c = TestClient(app)
    assert c.get("/api/admin/appel-proprietaire", headers={"X-User": "client"}).status_code == 403
    r = c.get("/api/admin/appel-proprietaire", headers={"X-User": "sup"}).json()
    assert r["effectif"]["numeros"] == [PROPRIO] and r["permissions"][0]["etat"] == "accordee"
    assert [li["libelle"] for li in r["lignes"]] == ["Liluvine Standard", "Liluvine VIP"]
    assert c.put("/api/admin/appel-proprietaire", json={"appel_proprio_calme_debut": "25h"},
                 headers={"X-User": "sup"}).status_code == 422
    assert c.put("/api/admin/appel-proprietaire", json={"appel_proprio_fenetre_min": "45", "appel_proprio_calme_actif": True,
                                                        "champ_inconnu": "x"}, headers={"X-User": "sup"}).status_code == 200
    s = lancer(db.settings.find_one({"_id": "global"}))
    assert s["appel_proprio_fenetre_min"] == 45 and s["appel_proprio_calme_actif"] is True and "champ_inconnu" not in s
    # Une alerte apparaît dans le journal du portail avec son motif et son résultat
    message(db)
    j = c.get("/api/me/wa-appels", headers={"X-User": "sup"}).json()["items"]
    assert j[0]["motif"] == "alerte message" and j[0]["resultat"] == "décroché"
    assert j[0]["alerte_client_nom"] == "Awa Kaboré (+22670000001)"
