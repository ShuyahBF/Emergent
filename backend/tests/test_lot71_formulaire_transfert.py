"""Lot 71 — appels de Liluvine basés sur un formulaire, et transfert de messages WhatsApp.

Partie 1 (formulaire) : champ → question orale selon le type, choix lus sans numérotation, champs non
vocaux « à compléter », contrôle des valeurs extraites (sortie de l'IA abîmée ou hors choix), création de
la réponse au formulaire (source « appel Liluvine », statut incomplète), lien WhatsApp, routes.
Partie 2 (transfert) : droits et visibilité, fenêtre de 24 h ouverte / fermée, modèle de repli, média
renvoyé depuis la copie stockée (API Graph imitée, aucun téléchargement chez Meta), résultat par
destinataire, préfixe d'origine, journal.
MongoDB simulé, API Graph et IA factices : aucun appel réseau.
Lancer : cd backend && python -m pytest tests/test_lot71_formulaire_transfert.py -q
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.appel_proprietaire as ap  # noqa: E402
import routes.liluvine_agenda as la  # noqa: E402
import routes.liluvine_agenda_formulaire as fm  # noqa: E402
import routes.liluvine_decroche as ld  # noqa: E402
import routes.wa_transfert as wt  # noqa: E402

# Mardi 6 octobre 2026, 10 h 00 à Ouagadougou (UTC)
MATIN = datetime(2026, 10, 6, 10, 0, tzinfo=timezone.utc)


def lancer(coro):
    """Exécute une coroutine dans une boucle neuve."""
    return asyncio.new_event_loop().run_until_complete(coro)


# Formulaire d'exemple : tous les types utiles, dont deux champs impossibles à remplir à la voix
FORMULAIRE = {
    "id": "form-1", "client_id": "sawali", "number": 12, "title": "Enquête de satisfaction", "is_public": True,
    "pages": [{"id": "p1", "title": "Page", "fields": [
        {"id": "nom", "type": "text", "label": "1. Nom complet", "required": True},
        {"id": "age", "type": "number", "label": "Âge"},
        {"id": "visite", "type": "date", "label": "Date de la dernière visite", "required": True},
        {"id": "rdv", "type": "datetime", "label": "Prochain rendez-vous"},
        {"id": "satisfait", "type": "boolean", "label": "Êtes-vous satisfait ?"},
        {"id": "service", "type": "select", "label": "Service utilisé", "options": ["Pharmacie", "Laboratoire", "Consultation"]},
        {"id": "canaux", "type": "multiselect", "label": "Comment nous avez-vous connus ?", "options": ["Radio", "Ami", "Internet"]},
        {"id": "email", "type": "email", "label": "E-mail"},
        {"id": "tel", "type": "tel", "label": "Téléphone"},
        {"id": "site", "type": "url", "label": "Site web"},
        {"id": "photo", "type": "file", "label": "Photo de l'ordonnance", "required": True},
        {"id": "signature", "type": "signature", "label": "Signature"},
    ]}],
}


# ---------------------------------------------------------------------------
# Partie 1 — fonctions pures : questions, choix, plan, contrôle des valeurs
# ---------------------------------------------------------------------------

def test_question_par_type_et_choix_sans_numerotation():
    plan = fm.plan_formulaire(FORMULAIRE)
    q = {c["id"]: c["question"] for c in plan["champs"]}
    # Numérotation du libellé retirée, question naturelle selon le type
    assert q["nom"] == "Concernant nom complet, que dois-je noter ?"
    assert q["age"].endswith("quel nombre dois-je noter ?")
    assert q["visite"].endswith("quelle date dois-je noter ?")
    assert q["rdv"].endswith("quelle date et quelle heure dois-je noter ?")
    assert q["satisfait"] == "Êtes-vous satisfait ?"
    assert q["service"] == "Concernant service utilisé, plutôt Pharmacie, Laboratoire ou Consultation ?"
    assert "Radio, Ami et Internet" in q["canaux"] and q["canaux"].endswith("Lesquelles retenez-vous ?")
    assert q["email"].endswith("quelle adresse e-mail dois-je noter ?")
    assert q["tel"].endswith("quel numéro de téléphone dois-je noter ?")
    # Jamais de numéro de liste dans ce que Liluvine dit
    for texte in q.values():
        assert not any(m in texte for m in ("1.", "2.", "1)", "•", " - "))
    # Lecture des choix : « ou », sans numéros ; liste trop longue → « par exemple »
    assert fm.lire_choix(["1. Bonne", "2) Moyenne", "Mauvaise"]) == "Bonne, Moyenne ou Mauvaise"
    assert fm.lire_choix([f"Choix {i}" for i in range(12)]).startswith("par exemple Choix 0, Choix 1 ou Choix 2")
    # Consignes de vérification : épeler l'e-mail, relire la date, épeler un nom propre
    conf = {c["id"]: c["confirmation"] for c in plan["champs"]}
    assert "épeler" in conf["email"] and "date" in conf["visite"] and "épeler" in conf["nom"]
    assert conf["age"].startswith("répète le nombre")


def test_champs_non_vocaux_a_completer_et_resume():
    plan = fm.plan_formulaire(FORMULAIRE)
    assert [c["id"] for c in plan["a_completer"]] == ["photo", "signature"]
    assert "photo" not in [c["id"] for c in plan["champs"]] and plan["nb_champs"] == 12
    r = fm.resume_formulaire(FORMULAIRE)
    assert (r["nb_champs"], r["nb_vocaux"], r["nb_a_completer"]) == (12, 10, 2)
    # Liste de choix vide → réponse libre ; type inconnu → texte
    p2 = fm.plan_formulaire({"id": "f", "pages": [{"fields": [
        {"id": "a", "type": "select", "label": "Choix", "options": []},
        {"id": "b", "type": "bizarre", "label": "Autre"}]}]})
    assert [c["type"] for c in p2["champs"]] == ["text", "text"]
    # Bloc du prompt : ordre, obligatoire, champs à ne pas demander, annonce du lien
    bloc = fm.bloc_prompt(plan, lien_prevu=True)
    assert bloc.index("nom complet") < bloc.index("service utilisé")
    assert "[obligatoire]" in bloc and "Ne demande PAS au téléphone : Photo de l'ordonnance, Signature" in bloc
    assert "lien lui sera envoyé par WhatsApp" in bloc and ld.MARQUEUR_FIN in bloc


def test_controle_des_valeurs_extraites():
    plan = fm.plan_formulaire(FORMULAIRE)
    c = {x["id"]: x for x in plan["champs"]}
    assert fm.valider_valeur("25 000", c["age"]) == (25000, None)
    assert fm.valider_valeur("beaucoup", c["age"])[0] is None and fm.valider_valeur("beaucoup", c["age"])[1]
    assert fm.valider_valeur("06/10/2026", c["visite"]) == ("2026-10-06", None)
    assert fm.valider_valeur("2026-02-30", c["visite"])[0] is None          # date impossible
    assert fm.valider_valeur("2026-10-20 14h30", c["rdv"]) == ("2026-10-20T14:30", None)
    assert fm.valider_valeur("2026-10-20", c["rdv"])[1]                    # heure manquante → invalide
    assert fm.valider_valeur("oui", c["satisfait"]) == (True, None)
    assert fm.valider_valeur("laboratoire", c["service"]) == ("Laboratoire", None)   # casse corrigée
    assert fm.valider_valeur("La pharmacie", c["service"]) == ("Pharmacie", None)
    assert fm.valider_valeur("Hôpital", c["service"])[0] is None
    assert fm.valider_valeur(["Radio", "ami"], c["canaux"]) == (["Radio", "Ami"], None)
    assert fm.valider_valeur("Radio et télévision", c["canaux"])[0] is None   # un choix inconnu → vide + motif
    assert fm.valider_valeur("awa point kabore arobase gmail point com", c["email"]) == ("awa.kabore@gmail.com", None)
    assert fm.valider_valeur("awa@", c["email"])[0] is None
    assert fm.valider_valeur("+226 70 00 00 01", c["tel"]) == ("+22670000001", None)
    assert fm.valider_valeur("123", c["tel"])[0] is None
    assert fm.valider_valeur("www.sawali.bf", c["site"]) == ("https://www.sawali.bf", None)
    assert fm.valider_valeur("null", c["nom"]) == (None, None)


def test_analyse_sortie_ia_abimee_et_partielle():
    plan = fm.plan_formulaire(FORMULAIRE)
    # Sortie de l'IA en partie fausse : valeurs hors choix, e-mail invalide, champ inconnu ignoré
    donnees = {"reponses": {"nom": {"valeur": "Awa KABORÉ", "confiance": 0.9}, "service": {"valeur": "Hôpital"},
                            "email": "pas un email", "inconnu": "x", "age": {"valeur": "34", "confiance": 7}}}
    a = fm.analyser_reponses(donnees, plan)
    par_id = {r["id"]: r for r in a["reponses"]}
    assert a["data"] == {"nom": "Awa KABORÉ", "age": 34}
    assert par_id["service"]["statut"] == "invalide" and par_id["email"]["statut"] == "invalide"
    assert par_id["age"]["confiance"] == 1.0                              # confiance ramenée entre 0 et 1
    assert par_id["photo"]["statut"] == "a_completer"
    assert set(a["obligatoires_manquants"]) == {"visite", "photo"} and a["complet"] is False
    assert sorted(a["invalides"]) == ["email", "service"]
    # JSON totalement illisible : tout est vide, jamais d'exception
    vide = fm.analyser_reponses({}, plan)
    assert vide["data"] == {} and all(r["valeur"] is None for r in vide["reponses"])
    # Lien : automatique s'il reste des champs à compléter ; jamais si réglé ainsi
    plan["lien"] = "https://sawali.test/f/form-1"
    assert fm.envoyer_lien_voulu("auto", plan, a) is True and fm.envoyer_lien_voulu("jamais", plan, a) is False
    plan_sans = {**plan, "a_completer": []}
    assert fm.envoyer_lien_voulu("auto", plan_sans, {"complet": True}) is False
    assert fm.lien_public({"id": "x", "is_public": False}, "https://s") is None


# ---------------------------------------------------------------------------
# Partie 1 — parcours complet : appel → extraction → réponse au formulaire
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(monkeypatch):
    base = mongomock_motor.AsyncMongoMockClient()["sawali_lot71"]
    lancer(base.settings.insert_one({"_id": "global", "wa_phone_number_id": "PN-STANDARD",
                                     "wa_access_token": "jeton-factice", "public_base_url": "https://sawali.test"}))
    lancer(base.users.insert_one({"id": "sawali", "role": "superviseur", "company": "SAWALI"}))
    lancer(base.forms.insert_one(dict(FORMULAIRE)))
    monkeypatch.setattr(ap, "_maintenant", lambda: MATIN)
    la._derniere_generation = None
    la._index_ok = False
    ld._actifs.clear()
    return base


class FauxGraph:
    """API Graph factice : appels autorisés, messages mémorisés, échec au choix pour un numéro."""

    def __init__(self, echec_pour=None):
        self.messages = []
        self.get_appels = []
        self.echec_pour = echec_pour

    async def get(self, s, numero_id, chemin, params):
        self.get_appels.append(chemin)
        return {"ok": True, "donnees": {"permission": {"status": "permanent"}, "actions": [
            {"action_name": "start_call", "can_perform_action": True}]}, "erreur": None}

    async def post(self, s, numero_id, chemin, corps):
        self.messages.append({"numero_id": numero_id, **corps})
        if self.echec_pour and corps.get("to") == self.echec_pour and corps.get("type") == "image":
            return {"ok": False, "donnees": {}, "erreur": "Meta : (#131053) Media upload error"}
        return {"ok": True, "donnees": {"messages": [{"id": f"wamid.{len(self.messages)}"}]}, "erreur": None}


def _evenement_formulaire(db, **autres):
    p = {"date_heure": "2026-10-06T09:30", "type": "suivi_client", "mode": "formulaire",
         "formulaire": {"id": "form-1"}, "questions": [{"libelle": "ignorée", "type": "texte"}],
         "contact": {"source": "libre", "nom": "Awa KABORÉ", "telephone": "+226 70 00 00 01"}}
    p.update(autres)
    champs = la.valider_evenement(p, la.reglages_agenda({}))
    champs["client_id"] = "sawali"
    doc = la._nouvel_evenement(champs, par="Test", maintenant=MATIN)
    lancer(db.liluvine_agenda.insert_one(dict(doc)))
    return doc


def test_validation_mode_formulaire_et_prompt_inchange():
    cfga = la.reglages_agenda({})
    base = {"date_heure": "2026-10-06T09:30", "type": "relance", "contact": {"telephone": "+22670000001"}}
    # Mode prompt (lot 70) : par défaut, questions gardées
    c = la.valider_evenement({**base, "questions": [{"libelle": "Q ?", "type": "texte"}]}, cfga)
    assert c["mode"] == "prompt" and c["formulaire"] is None and len(c["questions"]) == 1
    # Mode formulaire : formulaire obligatoire, questions libres ignorées
    with pytest.raises(ValueError):
        la.valider_evenement({**base, "mode": "formulaire"}, cfga)
    with pytest.raises(ValueError):
        la.valider_evenement({**base, "mode": "autre"}, cfga)
    c = la.valider_evenement({**base, "mode": "formulaire", "formulaire": {"id": "form-1"},
                              "questions": [{"libelle": "Q ?", "type": "texte"}], "lien_formulaire": "bizarre"}, cfga)
    assert c["questions"] == [] and c["formulaire"] == {"id": "form-1"} and c["lien_formulaire"] == "auto"


def test_appel_formulaire_cree_une_reponse_incomplete(db, monkeypatch):
    g = FauxGraph()
    monkeypatch.setattr(ap, "_graph_get", g.get)
    monkeypatch.setattr(ap, "_graph_post", g.post)
    vu = {}

    async def conversation(db_, s, cfga, ev, **kw):
        # Le prompt de l'appel contient les champs du formulaire ; l'ouverture annonce le formulaire
        vu["prompt"] = await la.prompt_de_l_evenement(db_, s, ev, la.texte_ouverture(ev))
        vu["ouverture"] = la.texte_ouverture(ev)
        await db_.wa_appels.insert_one({"id": "wacid.F", "direction": "sortant", "statut": "en_cours",
                                        "agenda_id": ev["id"]})
        return {"resultat": "decroche", "call_id": "wacid.F", "fin": "au revoir", "duree_s": 90, "transfert": False,
                "transcription": [{"qui": "liluvine", "texte": "Bonjour", "t": 0},
                                  {"qui": "appelant", "texte": "Awa Kaboré, K A B O R É. Laboratoire.", "t": 5}],
                "mesures": {"tours": 3}}
    monkeypatch.setattr(la, "appeler_et_converser", conversation)

    async def extraction(systeme, texte, max_jetons=900):
        assert systeme == fm.SYSTEME_EXTRACTION_FORMULAIRE
        assert "id=service ; type=choix ; champ : Service utilisé (choix : Pharmacie | Laboratoire | Consultation)" in texte
        assert "id=photo" not in texte                                       # champ non vocal : pas extrait
        return {"texte": "```json\n" + json.dumps({"resume": "Formulaire rempli en partie.", "reponses": {
            "nom": {"valeur": "Awa KABORÉ", "confiance": 0.95}, "service": {"valeur": "laboratoire", "confiance": 0.8},
            "email": {"valeur": "pas-un-email", "confiance": 0.3}, "satisfait": {"valeur": "oui", "confiance": 0.9}},
            "action_suivante": {"type": "aucune"}}) + "\n```", "entree": 400, "sortie": 80}
    monkeypatch.setattr(la, "llm_texte", extraction)

    ev = _evenement_formulaire(db)
    lancer(la.executer_echeances(db, lancer_en_fond=False))
    doc = lancer(db.liluvine_agenda.find_one({"id": ev["id"]}, {"_id": 0}))
    assert doc["statut"] == "termine"
    # Prompt et ouverture
    assert "Formulaire à remplir pendant l'appel : « Enquête de satisfaction »" in vu["prompt"]
    assert "plutôt Pharmacie, Laboratoire ou Consultation ?" in vu["prompt"]
    assert "Ne demande PAS au téléphone" in vu["prompt"]
    assert "formulaire Enquête de satisfaction" in vu["ouverture"]
    # Résultat : réponses champ par champ, soumission créée, lien envoyé (champs à compléter)
    f = doc["resultat"]["formulaire"]
    assert f["soumission_id"] and f["statut"] == "incomplete" and f["complet"] is False
    assert f["lien_soumission"] == "/admin/forms/form-1/analytics#submissions"
    par_id = {r["id"]: r for r in f["reponses"]}
    assert par_id["service"]["valeur"] == "Laboratoire" and par_id["email"]["statut"] == "invalide"
    assert par_id["photo"]["statut"] == "a_completer"
    assert [i["valeur"] for i in doc["resultat"]["informations"]][:1] == ["Awa KABORÉ"]
    sub = lancer(db.form_submissions.find_one({"id": f["soumission_id"]}, {"_id": 0}))
    assert sub["form_id"] == "form-1" and sub["client_id"] == "sawali" and sub["via"] == "appel_liluvine"
    assert sub["source"] == "appel Liluvine" and sub["statut"] == "incomplete"
    assert sub["data"] == {"nom": "Awa KABORÉ", "satisfait": True, "service": "Laboratoire"}
    assert sub["appel"]["call_id"] == "wacid.F" and sub["appel"]["agenda_id"] == ev["id"]
    assert sub["appel"]["confiances"]["nom"] == 0.95 and "email" in sub["appel"]["invalides"]
    assert sub["user_id"].startswith("appel-")
    assert lancer(db.forms.find_one({"id": "form-1"}))["uses_count"] == 1
    # Lien du formulaire envoyé par WhatsApp (formulaire public, champs à compléter)
    assert f["lien_envoye"]["ok"] is True
    texte = [m for m in g.messages if m.get("type") in ("text", "template")][-1]
    contenu = json.dumps(texte, ensure_ascii=False)
    assert "https://sawali.test/f/form-1" in contenu


def test_formulaire_sans_reponse_pas_de_soumission_et_formulaire_supprime(db, monkeypatch):
    g = FauxGraph()
    monkeypatch.setattr(ap, "_graph_get", g.get)
    monkeypatch.setattr(ap, "_graph_post", g.post)

    async def conversation(db_, s, cfga, ev, **kw):
        await db_.wa_appels.insert_one({"id": "wacid.V", "direction": "sortant", "statut": "en_cours"})
        return {"resultat": "decroche", "call_id": "wacid.V", "fin": "raccroché", "duree_s": 5,
                "transcription": [{"qui": "liluvine", "texte": "Bonjour", "t": 0}], "mesures": {}}
    monkeypatch.setattr(la, "appeler_et_converser", conversation)
    ev = _evenement_formulaire(db, lien_formulaire="jamais")
    lancer(la.executer_echeances(db, lancer_en_fond=False))
    f = lancer(db.liluvine_agenda.find_one({"id": ev["id"]}))["resultat"]["formulaire"]
    assert f["soumission_id"] is None and f["lien_envoye"] is None          # rien de rempli, lien « jamais »
    assert lancer(db.form_submissions.count_documents({})) == 0
    # Formulaire supprimé avant l'appel : pas d'appel, évènement en échec avec le motif
    lancer(db.forms.delete_one({"id": "form-1"}))
    ev2 = _evenement_formulaire(db)
    lancer(la.executer_echeances(db, lancer_en_fond=False))
    d2 = lancer(db.liluvine_agenda.find_one({"id": ev2["id"]}))
    assert d2["statut"] == "echec" and "formulaire introuvable" in d2["raison"]


def _client_agenda(db):
    utilisateurs = {"sup": {"id": "sup1", "role": "superviseur", "client_id": "autre", "full_name": "Sup"},
                    "admin": {"id": "a1", "role": "admin", "full_name": "Admin"}}

    async def utilisateur(request: Request):
        uid = request.headers.get("X-User")
        if uid not in utilisateurs:
            raise HTTPException(status_code=401)
        return utilisateurs[uid]
    api = APIRouter(prefix="/api")
    la.setup_liluvine_agenda_routes(db=db, api=api, get_current_user=utilisateur)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app)


def test_routes_formulaires_de_l_agenda(db):
    lancer(db.forms.insert_many([
        {"id": "prive", "client_id": "sawali", "title": "Privé", "is_public": False, "pages": [
            {"fields": [{"id": "x", "type": "text", "label": "X"}]}]},
        {"id": "fichiers", "client_id": "autre", "title": "Pièces", "pages": [
            {"fields": [{"id": "f", "type": "file", "label": "Pièce"}]}]}]))
    c = _client_agenda(db)
    # Superviseur d'un autre compte : formulaires de son compte + publics (pas le privé de SAWALI)
    r = c.get("/api/admin/liluvine-agenda/formulaires", headers={"X-User": "sup"}).json()["formulaires"]
    assert {f["id"] for f in r} == {"form-1", "fichiers"}
    assert next(f for f in r if f["id"] == "form-1")["nb_champs"] == 12
    assert len(c.get("/api/admin/liluvine-agenda/formulaires", headers={"X-User": "admin"}).json()["formulaires"]) == 3
    apercu = c.get("/api/admin/liluvine-agenda/formulaires/form-1/apercu", headers={"X-User": "sup"}).json()
    assert len(apercu["champs"]) == 10
    base = {"date_heure": "2026-10-07T09:30", "type": "relance", "mode": "formulaire",
            "contact": {"telephone": "+22670000001"}}
    # Formulaire privé d'un autre compte : refusé ; formulaire sans champ vocal : refusé
    assert c.post("/api/admin/liluvine-agenda", json={**base, "formulaire": {"id": "prive"}},
                  headers={"X-User": "sup"}).status_code == 422
    r = c.post("/api/admin/liluvine-agenda", json={**base, "formulaire": {"id": "fichiers"}}, headers={"X-User": "sup"})
    assert r.status_code == 422 and "aucun champ" in r.json()["detail"]
    r = c.post("/api/admin/liluvine-agenda", json={**base, "formulaire": {"id": "form-1"}}, headers={"X-User": "sup"})
    assert r.status_code == 200 and r.json()["formulaire"]["titre"] == "Enquête de satisfaction"
    # Copie : le mode et le formulaire sont repris
    copie = c.post(f"/api/admin/liluvine-agenda/{r.json()['id']}/dupliquer", json={}, headers={"X-User": "sup"}).json()
    assert copie["mode"] == "formulaire" and copie["formulaire"]["id"] == "form-1"


# ---------------------------------------------------------------------------
# Partie 2 — transfert de messages : fonctions pures
# ---------------------------------------------------------------------------

def test_corps_des_messages_transferes():
    texte = {"id": "m1", "direction": "inbound", "body": "Bonjour, voici ma commande", "message_type": "text"}
    assert wt.construire_envois(texte, base_url="", origine="Awa")[0]["text"]["body"] == \
        "Transféré de Awa : Bonjour, voici ma commande"
    assert wt.construire_envois(texte, base_url="", origine=None)[0]["text"]["body"] == "Bonjour, voici ma commande"
    image = {"id": "m2", "direction": "inbound", "body": "[image reçu]", "media_url": "/api/files/abc.jpg",
             "media_kind": "image", "media_mime_type": "image/jpeg", "media_caption": "Ordonnance", "media_size_bytes": 1000}
    corps = wt.construire_envois(image, base_url="https://sawali.test/", origine="Awa")
    assert corps == [{"type": "image", "image": {"link": "https://sawali.test/api/files/abc.jpg",
                                                  "caption": "Transféré de Awa : Ordonnance"}}]
    # Image WebP (non acceptée par Meta en image) → document ; trop lourde → refus
    webp = {**image, "media_mime_type": "image/webp", "media_filename": "photo.webp"}
    assert wt.construire_envois(webp, base_url="https://s", origine=None)[0]["type"] == "document"
    with pytest.raises(ValueError, match="trop volumineux"):
        wt.construire_envois({**image, "media_size_bytes": 6 * 1024 * 1024}, base_url="https://s", origine=None)
    # Audio : pas de légende → origine dans un court texte AVANT
    audio = {**image, "media_kind": "audio", "media_mime_type": "audio/ogg; codecs=opus", "media_url": "/api/files/a.ogg"}
    c_audio = wt.construire_envois(audio, base_url="https://s", origine="Awa")
    assert [c["type"] for c in c_audio] == ["text", "audio"] and "caption" not in c_audio[1]["audio"]
    # Position et carte de contact
    pos = wt.construire_envois({"body": "[position 12.37,-1.52]", "message_type": "location"}, base_url="", origine=None)
    assert pos == [{"type": "location", "location": {"latitude": 12.37, "longitude": -1.52}}]
    with pytest.raises(ValueError, match="carte de contact"):
        wt.construire_envois({"body": "[carte de contact reçue]", "message_type": "contacts"}, base_url="", origine=None)
    # Média dont la copie n'a pas été conservée : jamais de téléchargement chez Meta → refus
    with pytest.raises(ValueError):
        wt.construire_envois({"body": "[image reçu]", "message_type": "image"}, base_url="https://s", origine=None)
    # Origine : contact pour un message reçu, agent pour un message envoyé
    assert wt.nom_origine({"direction": "inbound", "phone_digits": "22670000001"}) == "+22670000001"
    assert wt.nom_origine({"direction": "outbound", "sender_label": "Issa"}) == "Issa"


def test_modele_de_repli():
    composants = [{"type": "HEADER", "format": "IMAGE"}, {"type": "BODY", "text": "Bonjour, {{1}} — {{2}}"}]
    assert wt.analyser_modele(composants) == {"nb_variables": 2, "entete": "IMAGE", "entete_variables": 0}
    corps = wt.corps_modele({"name": "relais", "language": "fr", "components": composants}, texte="Ligne 1\nLigne 2",
                            lien_media="https://s/api/files/x.jpg", nature_media="image", nom="Awa")
    assert corps["template"]["components"][0]["parameters"][0]["image"]["link"] == "https://s/api/files/x.jpg"
    assert [p["text"] for p in corps["template"]["components"][1]["parameters"]] == ["Ligne 1 Ligne 2", "—"]
    with pytest.raises(ValueError, match="en-tête image"):
        wt.corps_modele({"name": "relais", "components": composants}, texte="t", lien_media=None, nature_media=None, nom="A")


# ---------------------------------------------------------------------------
# Partie 2 — parcours complet par la route (droits, fenêtres, résultats, journal)
# ---------------------------------------------------------------------------

def _iso(dt):
    return dt.isoformat()


@pytest.fixture()
def db_wa(monkeypatch):
    base = mongomock_motor.AsyncMongoMockClient()["sawali_lot71_wa"]
    lancer(base.settings.insert_one({"_id": "global", "wa_phone_number_id": "PN-STANDARD",
                                     "wa_access_token": "jeton-factice",
                                     "wa_numeros": [{"id": "PN-VIP", "libelle": "Liluvine VIP"}]}))
    lancer(base.directory_contacts.insert_many([
        {"id": "c-origine", "client_id": "sawali", "name": "Awa KABORÉ", "whatsapp": "+22670000001"},
        {"id": "c-ouvert", "client_id": "sawali", "name": "Issa OUÉDRAOGO", "whatsapp": "+22670000002"},
        {"id": "c-ferme", "client_id": "sawali", "name": "Mariam SANOU", "whatsapp": "+22670000003"},
        {"id": "c-ferme2", "client_id": "sawali", "name": "Paul ZONGO", "whatsapp": "+22670000004"},
        {"id": "c-autre", "client_id": "autre-compte", "name": "Invisible", "whatsapp": "+22670000009"},
        {"id": "c-vip", "client_id": "sawali", "name": "Client VIP", "whatsapp": "+22670000005", "wa_ligne": "PN-VIP"},
    ]))
    recent = _iso(datetime(2026, 10, 6, 8, 0, tzinfo=timezone.utc))
    ancien = _iso(datetime(2026, 10, 4, 8, 0, tzinfo=timezone.utc))
    lancer(base.whatsapp_messages.insert_many([
        # Messages de la conversation d'origine (reçus d'Awa)
        {"id": "m-texte", "client_id": "sawali", "direction": "inbound", "contact_id": "c-origine",
         "phone_digits": "22670000001", "body": "Voici ma commande", "message_type": "text", "created_at": recent,
         "wa_numero_id": "PN-STANDARD"},
        {"id": "m-image", "client_id": "sawali", "direction": "inbound", "contact_id": "c-origine",
         "phone_digits": "22670000001", "body": "[image reçu]", "message_type": "image", "created_at": recent,
         "media_url": "/api/files/img1.jpg", "media_id": "img1", "media_kind": "image",
         "media_mime_type": "image/jpeg", "media_caption": "Ordonnance", "wa_numero_id": "PN-STANDARD"},
        # Fenêtres : Issa a écrit il y a 2 h (ouverte), Mariam et Paul il y a 2 jours (fermée)
        {"id": "w1", "client_id": "sawali", "direction": "inbound", "phone_digits": "22670000002", "body": "salut",
         "created_at": recent, "wa_numero_id": "PN-STANDARD"},
        {"id": "w2", "client_id": "sawali", "direction": "inbound", "phone_digits": "22670000003", "body": "salut",
         "created_at": ancien, "wa_numero_id": "PN-STANDARD"},
        {"id": "w3", "client_id": "sawali", "direction": "inbound", "phone_digits": "22670000004", "body": "salut",
         "created_at": ancien, "wa_numero_id": "PN-STANDARD"},
        # Message d'un autre compte (non visible)
        {"id": "m-cache", "client_id": "autre-compte", "direction": "inbound", "phone_digits": "22670000009",
         "body": "secret", "message_type": "text", "created_at": recent},
    ]))
    lancer(base.files.insert_one({"id": "img1", "size": 2048}))
    monkeypatch.setattr(ap, "_maintenant", lambda: MATIN)
    return base


def _client_wa(db, monkeypatch, g):
    monkeypatch.setattr(ap, "_graph_post", g.post)
    monkeypatch.setattr(ap, "_graph_get", g.get)
    utilisateurs = {
        "agent": {"id": "u1", "role": "client", "client_id": "sawali", "full_name": "Agent Ali"},
        "restreint": {"id": "u2", "role": "client", "client_id": "sawali", "full_name": "Agent VIP",
                      "wa_lignes_autorisees": ["principal"]},
        "visiteur": {"id": "u3", "role": "visiteur"},
    }

    async def utilisateur(request: Request):
        return utilisateurs[request.headers.get("X-User")]

    async def visibles(user):
        return [user.get("client_id")] if user.get("client_id") else []
    api = APIRouter(prefix="/api")
    wt.setup_wa_transfert_routes(db=db, api=api, get_current_user=utilisateur, visibles_fn=visibles,
                                 base_url_fn=lambda req: "https://sawali.test",
                                 peut_envoyer_fn=lambda u: u.get("role") in ("client", "admin"))
    app = FastAPI()
    app.include_router(api)
    return TestClient(app)


def test_transfert_complet_fenetres_modele_resultats_journal(db_wa, monkeypatch):
    g = FauxGraph()
    c = _client_wa(db_wa, monkeypatch, g)
    h = {"X-User": "agent"}
    # Recherche : fenêtre affichée avant l'envoi, contact d'un autre compte absent
    dest = c.get("/api/me/wa-transfert/destinataires", params={"q": ""}, headers=h).json()["destinataires"]
    par_id = {d["id"]: d for d in dest}
    assert "c-autre" not in par_id
    assert par_id["c-ouvert"]["fenetre_ouverte"] is True and par_id["c-ferme"]["fenetre_ouverte"] is False
    assert par_id["c-vip"]["ligne_libelle"] == "Liluvine VIP"
    # Transfert de 2 messages à 3 destinataires : ouvert, fermé + modèle, fermé sans choix
    modele = {"name": "relais_message", "language": "fr", "components": [{"type": "BODY", "text": "Message : {{1}}"}]}
    r = c.post("/api/me/wa-transfert", headers=h, json={
        "message_ids": ["m-texte", "m-image"], "commentaire": "Pour info",
        "destinataires": [{"id": "c-ouvert"}, {"id": "c-ferme"}, {"id": "c-ferme2"}],
        "repli": {"c-ferme": "modele"}, "modele": modele}).json()
    res = {x["id"]: x for x in r["resultats"]}
    assert res["c-ouvert"]["statut"] == "envoye" and res["c-ouvert"]["envoyes"] == 3   # commentaire + texte + image
    assert res["c-ferme"]["statut"] == "envoye" and res["c-ferme"]["mode"] == "modele"
    assert res["c-ferme2"]["statut"] == "refuse" and "fenêtre de 24 h fermée" in res["c-ferme2"]["raison"]
    # Corps envoyés à Meta : origine en préfixe, image par LIEN vers notre copie stockée
    vers_ouvert = [m for m in g.messages if m["to"] == "22670000002"]
    assert vers_ouvert[0]["text"]["body"] == "Pour info"
    assert vers_ouvert[1]["text"]["body"] == "Transféré de Awa KABORÉ : Voici ma commande"
    assert vers_ouvert[2]["image"] == {"link": "https://sawali.test/api/files/img1.jpg",
                                       "caption": "Transféré de Awa KABORÉ : Ordonnance"}
    assert all(m["numero_id"] == "PN-STANDARD" for m in vers_ouvert)
    assert g.get_appels == []                                     # aucun téléchargement chez Meta
    modele_envoye = next(m for m in g.messages if m["to"] == "22670000003")
    assert modele_envoye["type"] == "template"
    assert "Transféré de Awa KABORÉ : Voici ma commande / Ordonnance" in \
        modele_envoye["template"]["components"][0]["parameters"][0]["text"]
    assert not any(m["to"] == "22670000004" for m in g.messages)
    # Conversation du destinataire : messages marqués « transféré »
    traces = lancer(db_wa.whatsapp_messages.find({"phone_digits": "22670000002", "transfere": True}, {"_id": 0}).to_list(10))
    assert len(traces) == 3 and traces[2]["media_url"] == "/api/files/img1.jpg"
    assert traces[1]["transfere_de"]["nom"] == "Awa KABORÉ" and traces[0]["contact_id"] == "c-ouvert"
    # Journal : qui, quoi, à qui, résultat
    j = c.get("/api/me/wa-transfert/journal", headers=h).json()["transferts"]
    assert len(j) == 1 and j[0]["par_nom"] == "Agent Ali" and len(j[0]["messages"]) == 2
    assert {d["id"]: d["statut"] for d in j[0]["destinataires"]} == {"c-ouvert": "envoye", "c-ferme": "envoye",
                                                                     "c-ferme2": "refuse"}


def test_transfert_droits_visibilite_et_echec_partiel(db_wa, monkeypatch):
    g = FauxGraph(echec_pour="22670000002")
    c = _client_wa(db_wa, monkeypatch, g)
    h = {"X-User": "agent"}
    # Rôle non autorisé
    assert c.post("/api/me/wa-transfert", headers={"X-User": "visiteur"},
                  json={"message_ids": ["m-texte"], "destinataires": [{"id": "c-ouvert"}]}).status_code == 403
    # Message d'une conversation non visible : refusé
    assert c.post("/api/me/wa-transfert", headers=h,
                  json={"message_ids": ["m-cache"], "destinataires": [{"id": "c-ouvert"}]}).status_code == 404
    # Plus de 10 destinataires : refusé
    assert c.post("/api/me/wa-transfert", headers=h, json={"message_ids": ["m-texte"], "destinataires": [
        {"id": f"x{i}"} for i in range(11)]}).status_code == 422
    # Destinataire invisible + client (réservé à l'encadrement) + échec Meta sur l'image → partiel
    r = c.post("/api/me/wa-transfert", headers=h, json={
        "message_ids": ["m-image", "m-texte"], "indiquer_origine": False,
        "destinataires": [{"id": "c-autre"}, {"id": "sawali", "source": "client"}, {"id": "c-ouvert"}]}).json()
    res = {x["id"]: x for x in r["resultats"]}
    assert res["c-autre"]["statut"] == "refuse" and "non visible" in res["c-autre"]["raison"]
    assert res["sawali"]["statut"] == "refuse"
    assert res["c-ouvert"]["statut"] == "partiel" and res["c-ouvert"]["envoyes"] == 1
    assert "Media upload error" in res["c-ouvert"]["raison"]
    # Origine non indiquée : texte transféré tel quel
    assert any(m.get("text", {}).get("body") == "Voici ma commande" for m in g.messages)
    echec = lancer(db_wa.whatsapp_messages.find_one({"phone_digits": "22670000002", "transfere": True,
                                                     "message_type": "image"}, {"_id": 0}))
    assert echec["ok"] is False and echec["wa_status"] == "failed"
    # Utilisateur limité à la ligne principale : la ligne VIP lui est refusée, et le contact VIP invisible
    hr = {"X-User": "restreint"}
    r = c.post("/api/me/wa-transfert", headers=hr, json={"message_ids": ["m-texte"], "ligne_cle": "PN-VIP",
                                                         "destinataires": [{"id": "c-ouvert"}, {"id": "c-vip"}]}).json()
    res = {x["id"]: x for x in r["resultats"]}
    assert "non attribuée" in res["c-ouvert"]["raison"] and "non visible" in res["c-vip"]["raison"]
    assert [x["cle"] for x in c.get("/api/me/wa-transfert/lignes", headers=hr).json()["lignes"]] == ["principal"]
