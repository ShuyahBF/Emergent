"""Lot 451 — recherche plein texte dans les rapports, suivis, notes et tâches (tableau de bord).

Deux séries : la LOGIQUE PURE (motif sans accents, texte lisible, extrait) et les ROUTES, exécutées avec une fausse base (mongomock)
pour prouver surtout que la recherche respecte les DROITS de lecture : elle ne montre jamais le document d'un autre."""
import asyncio
import re
from pathlib import Path

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

import recherche_documents as rd


# ---------------------------------------------------------------- logique pure
def test_requete_trop_courte_ou_trop_longue():
    assert rd.nettoyer_requete(" a ") == ""
    assert rd.nettoyer_requete("  compte   rendu ") == "compte rendu"
    assert len(rd.nettoyer_requete("x" * 500)) == rd.LONGUEUR_MAX


def test_recherche_sans_casse_ni_accents_dans_les_deux_sens():
    assert rd.compiler("reunion").search("Compte rendu de la RÉUNION du lundi")
    assert rd.compiler("Réunion").search("la reunion est reportee")
    assert rd.compiler("garcon").search("le garçon")
    assert not rd.compiler("reunion").search("rendez-vous")


def test_les_caracteres_speciaux_ne_sont_pas_une_expression():
    # « .* » doit être cherché tel quel : il ne doit pas tout trouver
    assert not rd.compiler(".*").search("un texte ordinaire")
    assert rd.compiler("a.b").search("valeur a.b ici") and not rd.compiler("a.b").search("valeur axb ici")
    assert rd.compiler("(test").search("mot (test) entre parenthèses")


def test_texte_brut_retire_la_mise_en_forme():
    html = "<p>Bonjour&nbsp;<b>Awa</b></p><ul><li>Point&amp;un</li><li>Deux</li></ul><script>alert('x')</script>"
    assert rd.texte_brut(html) == "Bonjour Awa Point&un Deux"
    assert rd.texte_brut(None) == ""


def test_un_mot_present_seulement_dans_une_balise_n_est_pas_un_resultat():
    doc = {"title": "Sans rapport", "content_html": '<p class="important">Texte</p>'}
    assert rd.analyser_document(doc, rd.compiler("important")) is None


def test_analyse_compte_les_occurrences_et_donne_un_extrait():
    long = "mot " * 40
    doc = {"title": "Visite du site", "content_html": f"<p>{long}Le groupe électrogène est en panne. {long}Groupe à remplacer.</p>",
           "tags": ["groupe"], "task_items": [{"text": "Appeler le dépanneur du groupe", "done": False}]}
    a = rd.analyser_document(doc, rd.compiler("GROUPE"))
    assert a["occurrences"] == 4                       # 2 dans le contenu, 1 dans la liste de la tâche, 1 dans les étiquettes
    assert a["champ"] == "Contenu"
    assert a["extrait"]["trouve"] == "groupe"
    assert a["extrait"]["avant"].startswith("… ") and a["extrait"]["apres"].endswith(" …")
    assert len(a["extrait"]["avant"]) <= rd.CONTEXTE + 2
    # Le titre passe avant le contenu quand le mot y figure
    assert rd.analyser_document(doc, rd.compiler("visite"))["champ"] == "Titre"


def test_resume_et_document_de_lecture_ne_rendent_ni_ip_ni_images():
    doc = {"id": "d1", "numero": "RPT-1", "title": "T", "content_html": "<p>abc</p>", "created_at": "2026-11-19T10:00:00+00:00",
           "owner_name": "BADINI Awa", "ip": "1.2.3.4", "user_agent": "nav", "images": [{"data": "x"}, {"data": "y"}]}
    ligne = rd.resume_resultat("reports", doc, rd.analyser_document(doc, rd.compiler("abc")))
    assert ligne["type"] == "Rapport" and ligne["auteur"] == "BADINI Awa" and "content_html" not in ligne
    lecture = rd.document_lecture("reports", doc)
    assert "ip" not in lecture and "user_agent" not in lecture and "images" not in lecture and lecture["nb_images"] == 2


# ---------------------------------------------------------------- routes (fausse base)
def _extrait_source() -> str:
    """Code des routes de recherche et du filtre des droits, repris tel quel du serveur (le fichier ne s'importe pas seul)."""
    source = (Path(__file__).resolve().parents[1] / "server_parts/p08_notes_portail_journaux.py").read_text(encoding="utf-8")
    debut = source.index("def _user_notes_collection(kind: str):")
    milieu_a = source.index("async def _base_visibilite_notes(user: dict)")
    milieu_b = source.index('@api.get("/me/notes/{kind}", tags=["Portail Client"])')
    recherche_a = source.index("async def _restreint_aux_siens(kind: str, user: dict)")
    recherche_b = source.index('@api.get("/me/notes/{kind}/authors"')
    return source[debut:milieu_a] + source[milieu_a:milieu_b] + source[recherche_a:recherche_b]


def _application(utilisateur: dict, restrictions: dict | None = None):
    """Mini-serveur : les routes de recherche branchées sur une fausse base, avec `utilisateur` connecté."""
    from typing import Any, Dict, Optional
    db = AsyncMongoMockClient()["essai"]
    api = APIRouter(prefix="/api")

    async def restrictions_contenu(_user):
        return restrictions or {}

    async def clients_visibles(user):
        return [user["id"]]

    espace = {
        "db": db, "api": api, "Depends": Depends, "HTTPException": HTTPException, "Optional": Optional, "Dict": Dict, "Any": Any,
        "asyncio": asyncio, "re": re, "get_current_user": lambda: utilisateur,
        "_is_super_admin": lambda u: u.get("role") == "super_admin",
        "_is_elevated_creator": lambda u: u.get("role") in ("admin", "superviseur", "moderateur"),
        "_resolve_visible_client_ids": clients_visibles, "_resolve_content_restrictions": restrictions_contenu,
    }
    exec(compile(_extrait_source(), "p08_recherche", "exec"), espace)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app), db


def _doc(ident, proprietaire, titre, contenu, date, **plus):
    return {"id": ident, "owner_id": proprietaire, "owner_name": f"Auteur {proprietaire}", "title": titre, "content_html": contenu,
            "created_at": date, "tenant_id": plus.pop("tenant_id", "soc1"), "is_private": plus.pop("is_private", True), "ip": "9.9.9.9", **plus}


@pytest.fixture()
def base_remplie():
    moi = {"id": "u1", "role": "client", "client_id": "soc1", "email": "awa.badini@gmail.com"}
    client, db = _application(moi)
    boucle = asyncio.new_event_loop()
    boucle.run_until_complete(db.user_reports.insert_many([
        _doc("r1", "u1", "Réunion de chantier", "<p>Le <b>générateur</b> est livré.</p>", "2026-11-10T08:00:00+00:00", numero="RPT-1"),
        _doc("r2", "u2", "Réunion privée d'un autre", "<p>générateur secret</p>", "2026-11-11T08:00:00+00:00"),
        _doc("r3", "u2", "Public de ma société", "<p>generateur partagé</p>", "2026-11-12T08:00:00+00:00", is_private=False),
        _doc("r4", "u3", "Public d'une AUTRE société", "<p>générateur ailleurs</p>", "2026-11-13T08:00:00+00:00", is_private=False, tenant_id="soc2"),
        _doc("r5", "u2", "Ciblé pour moi", "<p>Générateur à contrôler</p>", "2026-11-14T08:00:00+00:00", target_user_ids=["u1"]),
    ]))
    boucle.run_until_complete(db.user_tasks_personal.insert_one(
        _doc("t1", "u1", "Courses", "", "2026-11-15T08:00:00+00:00", task_items=[{"id": "i1", "text": "Huile du générateur", "done": False}])))
    boucle.run_until_complete(db.user_notes_personal.insert_one(_doc("n1", "u1", "Divers", "<p>rien à voir</p>", "2026-11-16T08:00:00+00:00")))
    boucle.close()
    return client


def test_la_recherche_ne_montre_que_les_documents_que_j_ai_le_droit_de_voir(base_remplie):
    corps = base_remplie.get("/api/me/recherche-documents", params={"q": "generateur"}).json()
    trouves = [r["id"] for r in corps["resultats"]]
    # Les miens, celui partagé dans ma société, celui qui m'est destiné ; JAMAIS le privé d'un autre ni celui d'une autre société
    assert trouves == ["t1", "r5", "r3", "r1"]                      # du plus récent au plus ancien
    assert "r2" not in trouves and "r4" not in trouves
    assert corps["total"] == 4 and corps["par_type"]["reports"] == 3 and corps["par_type"]["tasks"] == 1 and corps["tronque"] == []
    ligne = next(r for r in corps["resultats"] if r["id"] == "r1")
    assert ligne["type"] == "Rapport" and ligne["auteur"] == "Auteur u1" and ligne["extrait"]["trouve"] == "générateur" and ligne["champ"] == "Contenu"
    assert next(r for r in corps["resultats"] if r["id"] == "t1")["champ"] == "Liste de la tâche"
    assert all("content_html" not in r and "ip" not in r for r in corps["resultats"])


def test_filtre_par_type_et_requete_refusee(base_remplie):
    assert [r["id"] for r in base_remplie.get("/api/me/recherche-documents", params={"q": "générateur", "types": "tasks"}).json()["resultats"]] == ["t1"]
    assert base_remplie.get("/api/me/recherche-documents", params={"q": "a"}).status_code == 400
    assert base_remplie.get("/api/me/recherche-documents", params={"q": "abc", "types": "inconnu"}).status_code == 400
    assert base_remplie.get("/api/me/recherche-documents", params={"q": "introuvablexyz"}).json()["total"] == 0


def test_lecture_d_un_resultat_memes_droits_que_la_liste(base_remplie):
    ok = base_remplie.get("/api/me/recherche-documents/reports/r1")
    assert ok.status_code == 200 and ok.json()["content_html"].startswith("<p>Le") and "ip" not in ok.json()
    assert base_remplie.get("/api/me/recherche-documents/reports/r3").status_code == 200       # partagé dans ma société
    assert base_remplie.get("/api/me/recherche-documents/reports/r2").status_code == 404       # privé d'un autre : identifiant deviné = rien
    assert base_remplie.get("/api/me/recherche-documents/reports/r4").status_code == 404       # autre société
    assert base_remplie.get("/api/me/recherche-documents/inconnu/r1").status_code == 404


def test_restriction_de_contenu_je_ne_vois_que_mes_rapports():
    # Société qui a activé « rapports restreints » : même partagés, les rapports des autres ne sortent pas
    moi = {"id": "u1", "role": "client", "client_id": "soc1"}
    client, db = _application(moi, {"anon_rapports": True})
    boucle = asyncio.new_event_loop()
    boucle.run_until_complete(db.user_reports.insert_many([
        _doc("r1", "u1", "Le mien", "<p>pompe</p>", "2026-11-10T08:00:00+00:00"),
        _doc("r3", "u2", "Partagé", "<p>pompe</p>", "2026-11-12T08:00:00+00:00", is_private=False),
    ]))
    boucle.close()
    assert [r["id"] for r in client.get("/api/me/recherche-documents", params={"q": "pompe"}).json()["resultats"]] == ["r1"]
    assert client.get("/api/me/recherche-documents/reports/r3").status_code == 404


def test_plus_de_cinquante_documents_la_liste_est_coupee_et_le_dit():
    moi = {"id": "u1", "role": "client", "client_id": "soc1"}
    client, db = _application(moi)
    boucle = asyncio.new_event_loop()
    boucle.run_until_complete(db.user_notes_personal.insert_many(
        [_doc(f"n{i}", "u1", f"Note {i}", "<p>facture</p>", f"2026-10-{1 + i % 28:02d}T08:00:{i % 60:02d}+00:00") for i in range(60)]))
    boucle.close()
    corps = client.get("/api/me/recherche-documents", params={"q": "facture", "types": "notes"}).json()
    assert corps["total"] == rd.MAX_PAR_TYPE and corps["tronque"] == ["Note"]
