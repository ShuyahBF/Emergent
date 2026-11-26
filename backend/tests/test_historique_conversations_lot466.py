"""Lot 466 — Liluvine → « Historique Conversation » : choix des messages (sans les bloqués), tri décroissant, CSV sûr, PDF (date/heure, pastille, « Liluvine » vertical), routes et droits.
Aucun accès réseau (Mongo simulé)."""
import asyncio
import os
import shutil
import subprocess
from datetime import datetime, timezone

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot466")

import mongomock_motor
import pytest

import historique_conversations as hc
import liste_noire_wa


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ------------------------------------------------------------------------------------------------------------------ fonctions pures
def test_message_bloque_est_ignore():
    assert hc.message_ignore({"barriere_retenu": True}, set()) and hc.message_ignore({"liste_noire": True}, set())
    assert hc.message_ignore({"phone_digits": "22670111111", "created_at": "2026-11-20"}, {"70111111": "2026-11-01"})
    assert not hc.message_ignore({"phone_digits": "22670111111", "created_at": "2026-10-20"}, {"70111111": "2026-11-01"})   # avant le blocage
    assert hc.message_ignore({"phone_digits": "22670111111"}, {"70111111"})                 # numéro encore en liste noire
    assert not hc.message_ignore({"phone_digits": "22670111111"}, {"70222222"})
    assert not hc.message_ignore({"phone_digits": "22670111111"}, set())


def test_rattachement_par_id_puis_par_numero():
    awa, ben = {"id": "c1", "name": "Awa"}, {"id": "c2", "name": "Ben"}
    par_id, par_cle = {"c1": awa, "c2": ben}, {"70111111": awa, "70222222": ben}
    assert hc.rattacher({"contact_id": "c2", "phone_digits": "22670111111"}, par_id, par_cle) is ben          # le contact_id prime
    assert hc.rattacher({"contact_id": None, "phone_digits": "+226 70 11 11 11"}, par_id, par_cle) is awa     # sinon le numéro (8 derniers chiffres)
    assert hc.rattacher({"contact_id": None, "phone_digits": "22699999999"}, par_id, par_cle) is None


def test_texte_type_et_ligne():
    assert hc.texte_message({"body": " Bonjour "}) == "Bonjour"
    assert hc.texte_message({"message_type": "image"}) == "[image]"
    assert hc.texte_message({"template_name": "information_rdv", "template_rendered_body": "Bonjour Awa"}) == "Bonjour Awa"
    assert hc.texte_message({"template_name": "information_rdv"}) == "[modèle information_rdv]"
    x = hc.ligne({"id": "m1", "created_at": "2026-11-26T09:41:07+00:00", "direction": "inbound", "body": "Salut", "status": "read"}, {"id": "c1", "name": "Awa", "whatsapp": "+22670111111"}, "AMY")
    assert x["quand"] == "26/11/2026 09:41:07" and x["sens"] == "Reçu" and x["contact"] == "Awa" and x["client"] == "AMY" and x["statut"] == "read"
    assert hc.date_fr("n'importe quoi") == "—"


def test_tri_decroissant_la_plus_recente_d_abord():
    l = [{"quand_iso": "2026-11-24T08:00:00+00:00"}, {"quand_iso": "2026-11-26T09:00:00+00:00"}, {"quand_iso": "2026-11-25T10:00:00+00:00"}]
    assert [x["quand_iso"][:10] for x in hc.trier(l)] == ["2026-11-26", "2026-11-25", "2026-11-24"]


def test_csv_excel_francais_et_protection_des_formules():
    lignes = [{"quand": "26/11/2026 09:41:07", "client": "AMY", "contact": "Awa", "telephone": "+226 70 11 11 11", "sens": "Reçu", "type": "texte", "statut": "", "message": "=HYPERLINK(\"http://x\")"},
              {"quand": "25/11/2026 10:00:00", "client": "AMY", "contact": "Ben", "telephone": "", "sens": "Envoyé", "type": "texte", "statut": "sent", "message": "Ligne 1\nLigne 2; avec point-virgule"}]
    brut = hc.construire_csv(lignes)
    assert brut.startswith("﻿".encode("utf-8"))                                           # BOM : accents lus correctement par Excel
    texte = brut.decode("utf-8-sig")
    assert texte.splitlines()[0] == "Date et heure;Client;Contact;Téléphone;Sens;Type;Statut;Message"
    assert "'=HYPERLINK" in texte and ";=HYPERLINK" not in texte                               # formule neutralisée
    assert '"Ligne 1\nLigne 2; avec point-virgule"' in texte                                    # saut de ligne et « ; » protégés par des guillemets
    assert hc.neutraliser("+226") == "'+226" and hc.neutraliser("normal") == "normal"


def test_texte_pdf_emojis_et_balises():
    assert hc.texte_pdf("Merci 😀 à bientôt") == "Merci · à bientôt"                          # accents gardés, émoji remplacé
    assert hc.texte_pdf("a < b & c > d") == "a &lt; b &amp; c &gt; d"
    assert hc.texte_pdf("l1\nl2") == "l1<br/>l2"


# -------------------------------------------------------------------------------------------------------------------------- collecte
@pytest.fixture()
def db():
    d = mongomock_motor.AsyncMongoMockClient()["test_lot466"]
    liste_noire_wa.vider_cache()
    msgs = [
        {"id": "m1", "client_id": "t1", "contact_id": "c1", "phone_digits": "22670111111", "direction": "inbound", "body": "Bonjour", "created_at": "2026-11-24T08:00:00+00:00"},
        {"id": "m2", "client_id": "t1", "contact_id": None, "phone_digits": "22670111111", "direction": "outbound", "body": "Réponse", "created_at": "2026-11-26T09:00:00+00:00"},
        {"id": "m3", "client_id": "t1", "contact_id": "c2", "phone_digits": "22670222222", "direction": "inbound", "body": "Salut", "created_at": "2026-11-25T10:00:00+00:00"},
        {"id": "m4", "client_id": "t1", "contact_id": "c1", "phone_digits": "22670111111", "direction": "inbound", "body": "retenu", "created_at": "2026-11-26T10:00:00+00:00", "barriere_retenu": True},
        {"id": "m5", "client_id": "t1", "contact_id": "c1", "phone_digits": "22670111111", "direction": "inbound", "body": "bloqué", "created_at": "2026-11-26T11:00:00+00:00", "liste_noire": True},
        {"id": "m6", "client_id": "t-autre", "contact_id": "c1", "phone_digits": "22670111111", "direction": "inbound", "body": "autre tenant", "created_at": "2026-11-26T12:00:00+00:00"},
        {"id": "m7", "client_id": "t1", "contact_id": "c3", "phone_digits": "22670333333", "direction": "inbound", "body": "non choisi", "created_at": "2026-11-26T13:00:00+00:00"},
    ]
    run(d.whatsapp_messages.insert_many(msgs))
    return d


CONTACTS = [{"id": "c1", "name": "Awa", "whatsapp": "+226 70 11 11 11"}, {"id": "c2", "name": "Ben", "phone": "70 22 22 22"}]


def test_collecte_sans_messages_bloques_ni_autre_tenant_du_plus_recent_au_plus_ancien(db):
    lignes, tronque = run(hc.collecter(db, contacts_visibles=CONTACTS, visible_scope=["t1"], client="AMY"))
    assert [x["id"] for x in lignes] == ["m2", "m3", "m1"] and tronque is False                 # m4 retenu, m5 liste noire, m6 autre tenant, m7 non choisi : absents
    assert [x["contact"] for x in lignes] == ["Awa", "Ben", "Awa"] and lignes[0]["sens"] == "Envoyé"


def test_contact_bloque_garde_ses_messages_d_avant_le_blocage(db):
    # Lot 466.1 : seuls les messages écrits À PARTIR de la date de blocage disparaissent ; ceux d'avant restent visibles
    run(db["settings"].update_one({"_id": liste_noire_wa.ID_FICHE}, {"$set": {"entrees": [
        {"cle": "70222222", "numero": "+22670222222", "bloque_le": "2026-11-26T00:00:00+00:00"}]}}, upsert=True))
    liste_noire_wa.vider_cache()
    lignes, _ = run(hc.collecter(db, contacts_visibles=CONTACTS, visible_scope=["t1"]))
    assert "m3" in [x["id"] for x in lignes]                                                    # Ben bloqué le 26/11 : son message du 25/11 reste
    run(db["settings"].update_one({"_id": liste_noire_wa.ID_FICHE}, {"$set": {"entrees": [
        {"cle": "70222222", "numero": "+22670222222", "bloque_le": "2026-11-24T00:00:00+00:00"}]}}, upsert=True))
    liste_noire_wa.vider_cache()
    lignes, _ = run(hc.collecter(db, contacts_visibles=CONTACTS, visible_scope=["t1"]))
    assert "m3" not in [x["id"] for x in lignes]                                                # bloqué le 24/11 : message du 25/11 = période de blocage
    contacts = run(liste_noire_wa.annoter_bloques(db, [dict(c) for c in CONTACTS]))
    assert "bloque_le" in contacts[1] and "bloque_le" not in contacts[0]                        # le contact bloqué reste listé, marqué
    liste_noire_wa.vider_cache()


def test_periode_et_troncature(db):
    lignes, _ = run(hc.collecter(db, contacts_visibles=CONTACTS, visible_scope=["t1"], du="2026-11-25", au="2026-11-25"))
    assert [x["id"] for x in lignes] == ["m3"]
    lignes, tronque = run(hc.collecter(db, contacts_visibles=CONTACTS, visible_scope=["t1"], limite=2))
    assert tronque is True and len(lignes) == 2 and lignes[0]["id"] == "m2"                    # les plus récents d'abord


def test_restriction_communications_anonymisees(db):
    run(db.whatsapp_messages.update_one({"id": "m2"}, {"$set": {"sender_id": "u1"}}))
    lignes, _ = run(hc.collecter(db, contacts_visibles=CONTACTS, visible_scope=["t1"], seulement_utilisateur="u1"))
    assert [x["id"] for x in lignes] == ["m2"]


# ------------------------------------------------------------------------------------------------------------------------------ PDF
def _texte_pdf(pdf: bytes) -> str:
    if not shutil.which("pdftotext"):
        pytest.skip("pdftotext absent")
    return subprocess.run(["pdftotext", "-layout", "-", "-"], input=pdf, capture_output=True).stdout.decode("utf-8", "ignore")


def test_pdf_date_heure_pastille_et_liluvine_sur_chaque_page():
    lignes = [{"quand": f"26/11/2026 09:{i % 60:02d}:00", "contact": "Awa Ouédraogo", "sens": "Reçu", "message": f"Message numéro {i} " + "texte long " * 12} for i in range(160)]
    pdf = hc.construire_pdf(lignes, client="AMY — Pharmacie AMITIE MIYOUGOU", contacts=["Awa Ouédraogo", "Ben"], du="", au="", genere_le=datetime(2026, 11, 26, 9, 41, tzinfo=timezone.utc))
    assert pdf.startswith(b"%PDF")
    texte = _texte_pdf(pdf)
    pages = texte.count("\f")
    assert pages >= 3                                                                          # plusieurs pages
    assert "Édité le 26/11/2026 à 09:41" in texte and "AMY — Pharmacie AMITIE MIYOUGOU" in texte
    assert texte.count("Page ") >= pages and f"/ {pages}" in texte                              # « Page n / N » sur chaque page
    # « Liluvine » écrit verticalement : pdftotext le restitue lettre par lettre ou en un mot selon la rotation, mais il doit figurer sur CHAQUE page
    for page in texte.split("\f")[:pages]:
        assert "Liluvine" in page or all(c in page for c in "Liluvine")


def test_pdf_sans_message():
    pdf = hc.construire_pdf([], client="AMY", contacts=[], du="2026-11-01", au="2026-11-26", genere_le=datetime(2026, 11, 26, 9, 41, tzinfo=timezone.utc))
    assert pdf.startswith(b"%PDF") and "Aucun message" in _texte_pdf(pdf) and "du 01/11/2026 au 26/11/2026" in _texte_pdf(pdf)


# ---------------------------------------------------------------------------------------------------------- routes et droits d'accès
@pytest.fixture()
def client_http(db):
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    from routes.historique_conversations import setup_historique_conversations_routes

    run(db.directory_contacts.insert_many([{"id": "c1", "client_id": "t1", "name": "Awa", "whatsapp": "+226 70 11 11 11"}, {"id": "c2", "client_id": "t1", "name": "Ben", "phone": "70 22 22 22"},
                                          {"id": "c9", "client_id": "t-autre", "name": "Hors périmètre", "whatsapp": "+226 70 99 99 99"}]))
    etat = {"user": {"id": "u1", "role": "admin", "email": "a@x.bf"}}
    app = FastAPI()
    api = APIRouter(prefix="/api")

    async def utilisateur():
        return etat["user"]

    async def perimetre(user):
        return ["t1"]

    async def restrictions(user):
        return {}
    setup_historique_conversations_routes(db=db, api=api, get_current_user=utilisateur, resolve_visible_client_ids=perimetre, resolve_content_restrictions=restrictions)
    app.include_router(api)
    return TestClient(app), etat, db


def test_route_json_pdf_csv_et_perimetre(client_http):
    c, _, _ = client_http
    r = c.post("/api/me/liluvine-historique", json={"contact_ids": ["c1", "c2", "c9"], "client": "AMY"})
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 3 and [m["id"] for m in d["messages"]] == ["m2", "m3", "m1"] and d["contacts"] == ["Awa", "Ben"] and d["ignores"] == 1       # c9 : hors périmètre
    pdf = c.post("/api/me/liluvine-historique/pdf", json={"contact_ids": ["c1", "c2"], "client": "AMY"})
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF") and "inline" in pdf.headers["content-disposition"]
    csv = c.post("/api/me/liluvine-historique/csv", json={"contact_ids": ["c1"], "client": "AMY"})
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv") and csv.content.startswith(b"\xef\xbb\xbf") and "attachment" in csv.headers["content-disposition"]
    assert c.post("/api/me/liluvine-historique", json={"contact_ids": []}).status_code == 422


def test_droits_superviseur_partage_et_client_refuse(client_http):
    c, etat, db = client_http
    etat["user"] = {"id": "u2", "role": "client", "email": "client@x.bf"}
    assert c.post("/api/me/liluvine-historique", json={"contact_ids": ["c1"]}).status_code == 403            # ni admin ni superviseur
    etat["user"] = {"id": "u3", "role": "superviseur", "email": "sup@x.bf"}
    assert c.post("/api/me/liluvine-historique", json={"contact_ids": ["c1"]}).status_code == 200            # superviseur absent du réglage : voit tout, comme avant
    run(db["settings"].update_one({"_id": "global"}, {"$set": {"liluvine_partage": {"sup@x.bf": ["agenda"]}}}, upsert=True))
    assert c.post("/api/me/liluvine-historique", json={"contact_ids": ["c1"]}).status_code == 403            # réglage présent, élément non partagé
    run(db["settings"].update_one({"_id": "global"}, {"$set": {"liluvine_partage": {"sup@x.bf": ["historique_conversations"]}}}, upsert=True))
    assert c.post("/api/me/liluvine-historique", json={"contact_ids": ["c1"]}).status_code == 200            # élément partagé


# ------------------------------------------------------------------------------------------------------------------------ menu et routes
def test_element_partageable_menu_et_routes_du_site():
    from pathlib import Path
    from routes.liluvine_partage import ELEMENTS
    assert "historique_conversations" in ELEMENTS
    racine = Path(__file__).resolve().parents[2] / "frontend" / "src"
    menu = (racine / "components" / "PortalLayout.jsx").read_text(encoding="utf-8")
    assert menu.count('partage: "historique_conversations"') == 2                                 # menu du portail (superviseurs) et de l'administration
    assert menu.count('label: "Historique Conversation"') == 2                                    # règle 18 : majuscule à chaque mot
    app = (racine / "App.js").read_text(encoding="utf-8")
    assert app.count('path="liluvine-historique-conversations"') == 2


def test_pdf_message_tres_long_ne_fait_plus_echouer_la_generation():
    # Lot 466.2 : un message énorme (ou plein de retours à la ligne) rendait une ligne plus haute que la page -> LayoutError « génération PDF impossible »
    from datetime import datetime, timezone
    lignes = [{"id": f"m{i}", "quand": "26/11/2026 09:00:00", "quand_iso": "2026-11-26T09:00:00+00:00", "contact": "Awa", "telephone": "+22670111111", "sens": "Reçu",
               "type": "texte", "statut": "", "message": msg, "client": "AMY"}
              for i, msg in enumerate(["x" * 20000, "ligne\n" * 400, "mot " * 5000, "Bonjour"])]
    pdf = hc.construire_pdf(lignes, client="AMY", contacts=["Awa"], du="", au="", genere_le=datetime.now(timezone.utc))
    assert pdf.startswith(b"%PDF")
