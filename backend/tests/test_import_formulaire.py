"""Lot 33 — « Créer depuis un document » (formulaires et sondages WhatsApp).

Tests autonomes : fichiers Word / Excel / PDF construits dans le test, MongoDB
simulé (mongomock-motor), appel IA remplacé par une doublure — aucun réseau,
aucune clé. Lancer : cd backend && python -m pytest tests/test_import_formulaire.py -q
"""
from __future__ import annotations

import io
import json
import sys
import time
import types
import zipfile
from itertools import count
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import import_formulaire as imp  # noqa: E402

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


# --- Fichiers de test -----------------------------------------------------------
def _docx(corps: str) -> bytes:
    """Document Word minimal (seul word/document.xml est lu)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<w:document {W}><w:body>{corps}</w:body></w:document>')
    return buf.getvalue()


def _p(texte: str, liste: bool = False, case: bool = False) -> str:
    num = "<w:pPr><w:numPr><w:numId w:val=\"1\"/></w:numPr></w:pPr>" if liste else ""
    sym = '<w:r><w:sym w:font="Wingdings" w:char="F06F"/></w:r>' if case else ""
    return f"<w:p>{num}{sym}<w:r><w:t xml:space=\"preserve\">{texte}</w:t></w:r></w:p>"


def _tableau(lignes) -> str:
    return "<w:tbl>" + "".join(
        "<w:tr>" + "".join(f"<w:tc>{_p(c)}</w:tc>" for c in l) + "</w:tr>" for l in lignes) + "</w:tbl>"


def _xlsx() -> bytes:
    """Classeur Excel minimal : 2 feuilles, textes partagés, texte en ligne et nombres."""
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {ns} {rel}><sheets>'
                   '<sheet name="Enquête" sheetId="1" r:id="rId1"/><sheet name="Vide" sheetId="2" r:id="rId2"/>'
                   '</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
                   '<Relationship Id="rId2" Target="/xl/worksheets/sheet2.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", f'<sst {ns}><si><t>Question</t></si><si><t>Réponse</t></si>'
                   '<si><t>Nombre d\'employés ?</t></si></sst>')
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet {ns}><sheetData>'
                   '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="s"><v>1</v></c></row>'
                   '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>12</v></c></row>'
                   '<row r="3"><c r="A3" t="inlineStr"><is><t>Signature</t></is></c></row>'
                   '</sheetData></worksheet>')
        z.writestr("xl/worksheets/sheet2.xml", f'<worksheet {ns}><sheetData/></worksheet>')
    return buf.getvalue()


def _pdf_texte() -> bytes:
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "QUESTIONNAIRE CLIENT\n" + "\n".join(f"{i}. Question numero {i} ?" for i in range(1, 15)))
    return doc.tobytes()


def _png() -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (800, 1000), "white").save(b, format="PNG")
    return b.getvalue()


# --- 1. Lecture des fichiers ----------------------------------------------------
def test_lecture_word_dans_l_ordre():
    t = imp.lire_word(_docx(
        _p("FICHE DE RENSEIGNEMENT") + _p("Avez-vous des observations ?", liste=True)
        + _tableau([["N°", "Nom / prénoms", "Salaire"], ["1", "AYIKI", "258 700"]])
        + _p(" Oui", case=True) + _p("Le responsable")))
    lignes = t.splitlines()
    assert lignes[0] == "FICHE DE RENSEIGNEMENT"
    assert lignes[1] == "• Avez-vous des observations ?"                  # liste numérotée
    assert lignes[2:6] == ["[TABLEAU]", "| N° | Nom / prénoms | Salaire |", "| 1 | AYIKI | 258 700 |",
                           "[FIN DU TABLEAU]"]
    assert lignes[6] == "☐ Oui" and lignes[7] == "Le responsable"          # case à cocher reprise


def test_lecture_excel_toutes_feuilles():
    t = imp.lire_excel(_xlsx())
    assert t.splitlines() == ["[FEUILLE « Enquête »]", "| Question |  | Réponse |",
                              "| Nombre d'employés ? | 12 |", "| Signature |"]   # feuille vide ignorée


def test_lecture_pdf_texte_ou_scanne():
    texte, images = imp.lire_pdf(_pdf_texte())
    assert "QUESTIONNAIRE CLIENT" in texte and images == []
    import fitz
    doc = fitz.open()
    doc.new_page().insert_image(fitz.Rect(0, 0, 595, 842), stream=_png())   # page scannée, sans texte
    texte, images = imp.lire_pdf(doc.tobytes())
    assert texte == "" and len(images) == 1


def test_preparer_melange_et_refus():
    texte, images, remarques = imp.preparer([("q.docx", _docx(_p("Question 1 ?"))), ("p1.png", _png())])
    assert "===== FICHIER « q.docx » =====" in texte and len(images) == 1 and remarques == []
    for nom, attendu in (("vieux.doc", "enregistrez-le en .docx"), ("vieux.xls", "enregistrez-le en .xlsx"),
                         ("notes.txt", "format non pris en charge")):
        with pytest.raises(ValueError, match=attendu):
            imp.preparer([(nom, b"x")])
    with pytest.raises(ValueError, match="image illisible"):
        imp.preparer([("IMG_0001.jpg", b"ftypheic pas une image")])
    with pytest.raises(ValueError, match="Word illisible"):
        imp.preparer([("abime.docx", b"pas un zip")])


# --- 2. Contrôle de la réponse de l'IA ------------------------------------------
def _ids():
    n = count(1)
    return lambda: f"id{next(n)}"


def test_normaliser_formulaire():
    brut = {"titre": "Fiche RH", "description": "SARL", "pages": [
        {"titre": "Rubrique paie", "champs": [
            {"type": "table", "libelle": "Liste du personnel",
             "colonnes": [{"libelle": "N°", "type": "number"}, {"libelle": "Nom / prénoms", "type": "texte"},
                          {"libelle": "Nom / prénoms"}],
             "lignes": [{"N°": 1, "Nom / prénoms": "AYIKI"}]},                     # données : jamais reprises
            {"type": "boolean", "libelle": "Des modifications ce mois ?", "largeur": 4},
            {"type": "textarea", "libelle": "Si oui, précisez", "largeur": 7},
            {"type": "select", "libelle": "Contrat", "options": ["CDI"]},          # 1 seul choix
            {"type": "radio", "libelle": "Sexe"},                                  # type inconnu
            {"type": "file", "libelle": "Copie des quittances"},
            {"type": "signature", "libelle": "La responsable"},
            {"type": "signature", "libelle": "Le gérant"},                          # 2e signature
        ]},
        {"titre": "Vide", "champs": [{"type": "text", "libelle": ""}]},              # page vide ignorée
        {"titre": "", "champs": [{"type": "multiselect", "libelle": "Services", "options": ["A", "B", "A"]}]},
    ]}
    f, notes = imp.normaliser_formulaire(brut, _ids())
    assert f["title"] == "Fiche RH" and [p["title"] for p in f["pages"]] == ["Rubrique paie", "Page 3"]
    table, oui, prec, contrat, sexe, fichier, sig, sig2 = f["pages"][0]["fields"]
    assert table["type"] == "table" and "default_value" not in table and "lignes" not in table
    assert table["columns"] == [{"key": "n", "label": "N°", "type": "number"},
                                {"key": "nom_prenoms", "label": "Nom / prénoms", "type": "text"},
                                {"key": "nom_prenoms_2", "label": "Nom / prénoms", "type": "text"}]
    assert (oui["col_span"], prec["col_span"]) == (4, 8)                           # largeurs de l'éditeur
    assert contrat["type"] == "text" and sexe["type"] == "text"
    assert fichier["accept"] == ".pdf,.jpg,.jpeg,.png"
    assert (sig["type"], sig2["type"]) == ("signature", "text")                    # une seule signature
    assert f["pages"][1]["fields"][0]["options"] == ["A", "B"]
    assert [c["row"] for c in f["pages"][0]["fields"]] == list(range(8))
    assert len({c["id"] for p in f["pages"] for c in p["fields"]}) == 9            # identifiants uniques
    assert len(notes) == 3 and any("une seule signature" in n for n in notes)


def test_tableau_avec_donnees_au_choix():
    brut = {"titre": "Fiche RH", "pages": [{"titre": "Paie", "champs": [
        {"type": "table", "libelle": "Liste du personnel",
         "colonnes": [{"libelle": "N°", "type": "number"}, {"libelle": "Nom/ prénoms", "type": "text"},
                      {"libelle": "Salaire de base", "type": "number"}, {"libelle": "Date d'entrée", "type": "date"},
                      {"libelle": "Catégorie", "type": "number"}],
         "lignes": [{"N°": 1, "Nom/ prénoms": "AYIKI SAMIRAT", "Salaire de base": "258 700",
                     "Date d'entrée": "05/03/2021", "Catégorie": "B2", "Inconnue": "x"},
                    {"n°": "2", "nom/ prénoms": "BAYIRI", "Salaire de base": "96 230,5", "Date d'entrée": "2020-01-15",
                     "Catégorie": "3"},
                    {"Salaire de base": ""}]}]}]}                                   # ligne vide ignorée
    # Sans données (choix par défaut) : colonnes seulement, types d'origine.
    f, notes = imp.normaliser_formulaire(brut, _ids())
    table = f["pages"][0]["fields"][0]
    assert "default_value" not in table and notes == []
    # Avec données : lignes converties au format des champs.
    f, notes = imp.normaliser_formulaire(brut, _ids(), avec_donnees=True)
    table = f["pages"][0]["fields"][0]
    assert table["default_value"] == [
        {"n": 1, "nom_prenoms": "AYIKI SAMIRAT", "salaire_de_base": 258700, "date_d_entree": "2021-03-05",
         "categorie": "B2"},
        {"n": 2, "nom_prenoms": "BAYIRI", "salaire_de_base": 96230.5, "date_d_entree": "2020-01-15",
         "categorie": "3"}]
    assert [c["type"] for c in table["columns"]] == ["number", "text", "number", "date", "text"]   # « B2 » : texte
    assert notes == ["Tableau « Liste du personnel », colonne « Catégorie » : valeurs qui ne sont pas toutes des "
                     "nombres, colonne passée en texte.",
                     "Tableau « Liste du personnel » : 2 ligne(s) reprise(s) du document, à vérifier "
                     "(elles pré-remplissent le tableau)."]
    # Plus de 100 lignes : les 100 premières.
    brut["pages"][0]["champs"][0]["lignes"] = [{"N°": i} for i in range(1, 131)]
    f, notes = imp.normaliser_formulaire(brut, _ids(), avec_donnees=True)
    assert len(f["pages"][0]["fields"][0]["default_value"]) == 100 and "130 lignes lues" in notes[0]
    # Consignes données à l'IA selon le choix.
    assert "Ne reprends JAMAIS les lignes" in imp.consignes_formulaire(False)
    assert "ET ses lignes dans « lignes »" in imp.consignes_formulaire(True)
    assert "{TABLEAUX}" not in imp.consignes_formulaire(True)


def test_doublons_signales():
    q = "Quelles sont vos observations sur les tableaux de bord mensuel passé que vous avez reçus ?"
    brut = {"titre": "Compta", "pages": [{"titre": "P", "champs": [
        {"type": "textarea", "libelle": q}, {"type": "boolean", "libelle": "Paiements d'impôts ?"},
        {"type": "textarea", "libelle": q.replace("les tableaux", "le tableau")}]}]}
    _, notes = imp.normaliser_formulaire(brut, _ids())
    assert notes == [f"Question posée deux fois (presque à l'identique) : « {q[:90]} ». Gardez-en une seule si "
                     "c'est un doublon."]


def test_normaliser_sondage():
    brut = {"titre": "Satisfaction", "questions": [
        {"type": "single", "libelle": "Canal préféré", "options": ["WhatsApp", "SMS"]},
        {"type": "multi", "libelle": "Un seul choix lu", "options": ["X"]},
        {"type": "table", "libelle": "Tableau"},
    ] + [{"type": "yesno", "libelle": f"Question {i}"} for i in range(40)]}
    s, notes = imp.normaliser_sondage(brut, _ids())
    assert len(s["questions"]) == imp.MAX_QUESTIONS
    assert [q["type"] for q in s["questions"][:3]] == ["single", "text", "text"]
    assert any("30 au plus" in n for n in notes) and len(notes) == 3


def test_reponse_sans_question_refusee():
    with pytest.raises(ValueError, match="Aucune question"):
        imp.normaliser_formulaire({"titre": "X", "pages": []}, _ids())


# --- 3. Parcours par l'API ------------------------------------------------------
USERS = {
    "admin": {"id": "admin", "role": "admin", "full_name": "Admin"},
    "pharma_a": {"id": "pharma_a", "role": "pharmacien", "company": "Pharmacie A", "client_code": "PA"},
    "suivi_a": {"id": "suivi_a", "role": "client", "client_id": "pharma_a", "parent_client_id": "pharma_a"},
    "pharma_b": {"id": "pharma_b", "role": "pharmacien", "company": "Pharmacie B", "client_code": "PB"},
}
REPONSE_FORMULAIRE = {"titre": "Fiche de renseignement", "description": "Mars", "pages": [
    {"titre": "Questions", "champs": [{"type": "boolean", "libelle": "Des grossistes sans factures ?", "largeur": 4},
                                      {"type": "textarea", "libelle": "Lesquels ?", "largeur": 8},
                                      {"type": "signature", "libelle": "Le responsable"}]}],
    "remarques": ["« Il ya » corrigé en « Il y a »."]}
REPONSE_SONDAGE = {"titre": "Avis clients", "questions": [
    {"type": "rating", "libelle": "Votre note ?"}, {"type": "text", "libelle": "Commentaire", "obligatoire": False}]}


@pytest.fixture()
def env(monkeypatch):
    pytest.importorskip("mongomock_motor")
    from fastapi import APIRouter, FastAPI, Header, HTTPException
    from fastapi.testclient import TestClient
    from mongomock_motor import AsyncMongoMockClient

    appels = []
    reponses = {"formulaire": json.dumps(REPONSE_FORMULAIRE), "sondage": json.dumps(REPONSE_SONDAGE)}

    async def fake_ia(model_id, system, texte, images):
        cible = "sondage" if "SONDAGE" in system else "formulaire"
        appels.append((cible, texte, len(images), "ET ses lignes" in system))
        return reponses[cible], 3000, 900

    monkeypatch.setattr(imp, "appeler_ia", fake_ia)
    db = AsyncMongoMockClient()["sawali_test"]
    compteurs: dict = {}

    async def next_form_number(code):
        compteurs[code] = compteurs.get(code, 0) + 1
        return compteurs[code]

    async def get_current_user(x_user: str = Header(...)):
        if x_user not in USERS:
            raise HTTPException(status_code=401)
        return USERS[x_user]

    from routes.import_formulaire import attach_import_formulaire_routes
    n = count(1)
    api = APIRouter(prefix="/api")
    attach_import_formulaire_routes(api=api, db=db, get_current_user=get_current_user, uuid_fn=lambda: f"u{next(n)}",
                                    next_form_number=next_form_number, slugify_code=lambda s: s[:3].upper(),
                                    is_admin_like=lambda u: u.get("role") in ("admin", "superviseur"))
    app = FastAPI()
    app.include_router(api)
    with TestClient(app) as client:
        client.portal.call(db.users.insert_many, [dict(u) for u in USERS.values()])
        yield types.SimpleNamespace(client=client, db=db, appels=appels, reponses=reponses)


def _h(user):
    return {"X-User": user}


def _deposer(env, user, fichiers, cible="formulaire", **form):
    return env.client.post("/api/me/form-imports", headers=_h(user), data={"cible": cible, **form},
                           files=[("fichiers", f) for f in fichiers])


def _attendre(env, user, job_id):
    for _ in range(200):
        j = env.client.get(f"/api/me/form-imports/{job_id}", headers=_h(user)).json()
        if j["statut"] != "en_cours":
            return j
        time.sleep(0.02)
    raise AssertionError("analyse jamais terminée")


def test_parcours_formulaire_depuis_word(env):
    # Un formulaire du même titre existe déjà chez ce client : le brouillon prend « (import) ».
    env.client.portal.call(env.db.forms.insert_one, {"id": "old", "client_id": "pharma_a", "title": "Fiche de renseignement"})
    word = ("questionnaire.docx", _docx(_p("Il ya des grossistes sans factures ? lesquels ?") + _p("Le responsable")))
    r = _deposer(env, "pharma_a", [word])
    assert r.status_code == 202, r.text
    job = _attendre(env, "pharma_a", r.json()["id"])
    assert job["statut"] == "termine", job
    assert "usage" not in job                                   # coût et modèle : administration seulement
    assert job["compte_rendu"].startswith("Formulaire créé en brouillon : 3 champ(s) sur 1 page(s) "
                                          "(1 Oui/Non, 1 réponse longue, 1 signature).")
    assert "• « Il ya » corrigé en « Il y a »." in job["compte_rendu"]
    form = env.client.portal.call(env.db.forms.find_one, {"id": job["objet_id"]}, {"_id": 0})
    assert form["title"] == "Fiche de renseignement (import)" and job["titre"] == form["title"]
    assert form["client_id"] == "pharma_a" and form["number"] == "FORM-PA-0001" and form["is_public"] is False
    assert form["imported_from_document"]["fichiers"] == ["questionnaire.docx"]
    assert [c["type"] for c in form["pages"][0]["fields"]] == ["boolean", "textarea", "signature"]
    cible, texte, nb_images, avec_lignes = env.appels[0]
    assert cible == "formulaire" and "Il ya des grossistes" in texte and nb_images == 0
    assert avec_lignes is False and job["avec_donnees"] is False               # colonnes seulement par défaut
    # L'administration voit le coût ; une autre pharmacie ne voit pas l'analyse.
    assert env.client.get(f"/api/me/form-imports/{job['id']}", headers=_h("admin")).json()["usage"]["input_tokens"] == 3000
    assert env.client.get(f"/api/me/form-imports/{job['id']}", headers=_h("pharma_b")).status_code == 404


def test_parcours_sondage_depuis_excel_et_photo(env):
    r = _deposer(env, "suivi_a", [("enquete.xlsx", _xlsx()), ("page2.png", _png())], cible="sondage")
    job = _attendre(env, "suivi_a", r.json()["id"])
    assert job["statut"] == "termine", job
    s = env.client.portal.call(env.db.wa_surveys.find_one, {"id": job["objet_id"]}, {"_id": 0})
    assert s["status"] == "draft" and s["client_id"] == "pharma_a"            # rattaché au client parent
    assert [(q["type"], q["required"]) for q in s["questions"]] == [("rating", True), ("text", False)]
    assert env.appels[0][0] == "sondage" and env.appels[0][2] == 1            # texte Excel + 1 image


def test_option_donnees_des_tableaux(env):
    env.reponses["formulaire"] = json.dumps({"titre": "Personnel", "pages": [{"titre": "Paie", "champs": [
        {"type": "table", "libelle": "Liste", "colonnes": [{"libelle": "Nom", "type": "text"},
                                                             {"libelle": "Salaire", "type": "number"}],
         "lignes": [{"Nom": "AYIKI", "Salaire": "258 700"}]}]}]})
    word = ("rh.docx", _docx(_tableau([["Nom", "Salaire"], ["AYIKI", "258 700"]])))
    job = _attendre(env, "pharma_a", _deposer(env, "pharma_a", [word], avec_donnees="true").json()["id"])
    assert job["statut"] == "termine" and job["avec_donnees"] is True and env.appels[-1][3] is True
    form = env.client.portal.call(env.db.forms.find_one, {"id": job["objet_id"]}, {"_id": 0})
    assert form["pages"][0]["fields"][0]["default_value"] == [{"nom": "AYIKI", "salaire": 258700}]
    # Même option pour un sondage : sans objet (pas de tableau), ignorée.
    job = _attendre(env, "pharma_a", _deposer(env, "pharma_a", [word], cible="sondage", avec_donnees="true").json()["id"])
    assert job["avec_donnees"] is False and env.appels[-1][3] is False


def test_refus_avant_tout_appel_ia(env):
    assert _deposer(env, "pharma_a", [("vieux.doc", b"x")]).status_code == 400
    assert _deposer(env, "pharma_a", [("q.docx", _docx(_p("Q ?")))], cible="enquete").status_code == 400
    r = env.client.post("/api/me/form-imports", headers=_h("pharma_a"), data={"cible": "formulaire"})
    assert r.status_code == 422                                                # aucun fichier
    # Une analyse déjà en cours pour cet utilisateur : la 2e est refusée.
    from datetime import datetime, timezone
    env.client.portal.call(env.db.form_imports.insert_one, {"id": "j0", "user_id": "pharma_a", "statut": "en_cours",
                                                            "cree_le": datetime.now(timezone.utc).isoformat()})
    assert _deposer(env, "pharma_a", [("q.docx", _docx(_p("Q ?")))]).status_code == 409
    assert env.appels == []


def test_reponse_illisible_ou_vide(env):
    env.reponses["formulaire"] = "désolé, je ne peux pas"
    job = _attendre(env, "pharma_a", _deposer(env, "pharma_a", [("q.docx", _docx(_p("Q ?")))]).json()["id"])
    assert job["statut"] == "erreur" and "n'a pas pu être lue" in job["erreur"]
    env.reponses["formulaire"] = json.dumps({"titre": "X", "pages": []})
    job = _attendre(env, "pharma_a", _deposer(env, "pharma_a", [("q.docx", _docx(_p("Q ?")))]).json()["id"])
    assert job["statut"] == "erreur" and "Aucune question" in job["erreur"]
    assert env.client.portal.call(env.db.forms.count_documents, {}) == 0      # rien de créé
