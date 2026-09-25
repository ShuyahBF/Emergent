"""Lot 23 — Explorateur Stockage R2 : suppression depuis l'écran, création de
dossier, renommage/fusion de tag, recherche dans le texte intégral.

Réutilise l'environnement simulé du lot 22 (MongoDB, R2 et IA simulés).
Lancer : cd backend && python -m pytest tests/test_gestion_stocks_lot23.py -q
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gestion_stocks_tags_lot22 import _drain, _files, _h, _upload, env  # noqa: E402,F401 — fixture réutilisée


def _pdf_bytes(text: str) -> bytes:
    """Petit PDF avec couche texte (PyMuPDF)."""
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _docx_bytes(text: str) -> bytes:
    """Petit .docx minimal (seule la partie texte compte pour l'extraction)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml",
                   f'<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    return buf.getvalue()


def _post(env, name, data, ctype, folder="Factures", who="suivi"):
    url = (f"/api/gestion-stocks/folders/{folder}/upload" if who == "suivi"
           else f"/api/admin/gestion-stocks/PDP/{folder}/upload")
    return env.client.post(url, headers=_h(who), files={"file": (name, data, ctype)})


def _search(env, q, who="suivi"):
    params = {"q": q} if who == "suivi" else {"q": q, "client_code": "PDP"}
    return env.client.get("/api/gestion-stocks/search", headers=_h(who), params=params).json()["results"]


# ---------------------------------------------------------------- 1. suppression
def test_tracked_user_deletes_only_own_files(env):
    _upload(env, name="a-moi.pdf")
    key = "PDP/Factures/a-moi.pdf"
    files = {f["name"]: f for f in _files(env, "Factures")}
    assert files["a-moi.pdf"]["can_delete"] is True
    assert _files(env, "Inventaires")[0]["can_delete"] is False  # ancien.xlsx, déposé hors Sawali
    # Pas le fichier d'un autre, ni hors de son tenant, ni sans autorisation de dépôt.
    assert env.client.delete("/api/gestion-stocks/files", headers=_h("suivi"),
                             params={"key": "PDP/Inventaires/ancien.xlsx"}).status_code == 403
    assert env.client.delete("/api/gestion-stocks/files", headers=_h("suivi"),
                             params={"key": "AUTRE/Factures/secret.pdf"}).status_code == 403
    assert env.client.delete("/api/gestion-stocks/files", headers=_h("lecteur"), params={"key": key}).status_code == 403
    r = env.client.delete("/api/gestion-stocks/files", headers=_h("suivi"), params={"key": key})
    assert r.status_code == 200 and key not in env.objects
    assert env.client.portal.call(env.db.stock_files.find_one, {"key": key}) is None


def test_staff_deletes_any_file_and_missing_file_is_404(env):
    assert env.client.delete("/api/gestion-stocks/files", headers=_h("sup"),
                             params={"key": "PDP/Inventaires/ancien.xlsx"}).status_code == 200
    assert "PDP/Inventaires/ancien.xlsx" not in env.objects
    assert env.client.delete("/api/gestion-stocks/files", headers=_h("sup"),
                             params={"key": "PDP/Inventaires/inexistant.pdf"}).status_code == 404


# ---------------------------------------------------------------- 2. création de dossier
def test_create_folder(env):
    r = env.client.post("/api/gestion-stocks/folders", headers=_h("suivi"), json={"name": "  Bons de commande 2025 "})
    assert r.status_code == 200 and r.json()["folder"] == "Bons de commande 2025"
    assert env.objects["PDP/Bons de commande 2025/"] == b""
    got = env.client.get("/api/gestion-stocks/folders", headers=_h("suivi")).json()
    assert "Bons de commande 2025" in got["extra_folders"]
    # Doublon, dossier standard, nom invalide, compte non autorisé
    assert env.client.post("/api/gestion-stocks/folders", headers=_h("suivi"), json={"name": "Bons de commande 2025"}).status_code == 409
    assert env.client.post("/api/gestion-stocks/folders", headers=_h("suivi"), json={"name": "factures"}).status_code == 409
    assert env.client.post("/api/gestion-stocks/folders", headers=_h("suivi"), json={"name": "../.."}).status_code == 400
    assert env.client.post("/api/gestion-stocks/folders", headers=_h("lecteur"), json={"name": "X"}).status_code == 403
    # L'administration choisit le client ; un code inconnu est refusé.
    assert env.client.post("/api/gestion-stocks/folders", headers=_h("admin"),
                           json={"name": "Audit", "client_code": "PDP"}).status_code == 200
    assert env.client.post("/api/gestion-stocks/folders", headers=_h("admin"),
                           json={"name": "Audit", "client_code": "XYZ"}).status_code == 404
    # Un dossier créé accepte ensuite les dépôts.
    assert _upload(env, name="bc.pdf", folder="Bons de commande 2025").status_code == 200


# ---------------------------------------------------------------- 3. renommer / fusionner un tag
def test_rename_and_merge_tags(env):
    _upload(env, name="a.pdf", tags="factures, copharmed")
    _upload(env, name="b.pdf", tags="facture")
    _upload(env, name="c.pdf", tags="factures, facture")
    # Réservé à l'administration
    assert env.client.put("/api/gestion-stocks/tags/rename", headers=_h("suivi"),
                          json={"from": "factures", "to": "facture"}).status_code == 403
    r = env.client.put("/api/gestion-stocks/tags/rename", headers=_h("sup"),
                       json={"from": "Factures", "to": "facture", "client_code": "PDP"})
    assert r.status_code == 200 and r.json()["files_changed"] == 2
    assert r.json()["tags"] == [{"tag": "facture", "count": 3}, {"tag": "copharmed", "count": 1}]
    doc = env.client.portal.call(env.db.stock_files.find_one, {"key": "PDP/Factures/c.pdf"})
    assert doc["tags"] == ["facture"]  # fusion sans doublon
    # `to` vide : le tag est retiré partout
    r = env.client.put("/api/gestion-stocks/tags/rename", headers=_h("admin"),
                       json={"from": "copharmed", "to": "", "client_code": "PDP"})
    assert r.json()["files_changed"] == 1 and r.json()["tags"] == [{"tag": "facture", "count": 3}]


# ---------------------------------------------------------------- 4. texte intégral
def test_full_text_search_pdf_and_docx(env):
    assert _post(env, "livraison.pdf", _pdf_bytes("Bon de livraison DOLIPRANE 1000 mg lot 45871"), "application/pdf").status_code == 200
    assert _post(env, "note.docx", _docx_bytes("Rappel : controle de temperature du frigo"),
                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document").status_code == 200
    res = _search(env, "doliprane 45871")
    assert [r["name"] for r in res] == ["livraison.pdf"]
    assert "DOLIPRANE" in res[0]["match_snippet"]
    # Accents ignorés : « température » trouve « temperature »
    assert [r["name"] for r in _search(env, "température frigo")] == ["note.docx"]
    # Trouvé par le nom : pas d'extrait
    assert _search(env, "livraison")[0]["match_snippet"] == ""


def test_old_files_are_indexed_in_background_and_reindex(env):
    env.objects["PDP/Rapports/ancien.txt"] = "Inventaire annuel : 12 boites de paracetamol".encode()
    _files(env, "Rapports")  # ouverture du dossier → indexation en arrière-plan
    _drain(env)
    assert [r["name"] for r in _search(env, "paracetamol")] == ["ancien.txt"]
    # Réindexation par l'administration (fichiers jamais indexés du client)
    env.objects["PDP/Autres/memo.csv"] = "produit;quantite\nAMOXICILLINE;40".encode()
    r = env.client.post("/api/gestion-stocks/reindex", headers=_h("admin"), json={"client_code": "PDP"})
    assert r.status_code == 200 and r.json()["queued"] >= 1
    _drain(env)
    assert [x["name"] for x in _search(env, "amoxicilline")] == ["memo.csv"]
    assert env.client.post("/api/gestion-stocks/reindex", headers=_h("suivi"), json={}).status_code == 403


def test_ai_text_makes_scans_searchable(env):
    env.client.put("/api/admin/gestion-stocks/tenants/t-pdp/storage", headers=_h("admin"), json={"ai_tags": True})
    _upload(env, name="scan.pdf")  # contenu non textuel ; l'IA simulée lit « COPHARMED »
    _drain(env)
    res = _search(env, "copharmed")
    assert [r["name"] for r in res] == ["scan.pdf"] and "COPHARMED" in res[0]["match_snippet"]


def test_extract_text_helpers():
    from routes.gestion_stocks_tags import clean_folder_name, extract_text, snippet
    assert extract_text(b"\x89PNG....", "photo.png", "image/png") == ""
    assert extract_text(b"not a zip", "x.docx") == ""  # fichier corrompu : pas d'erreur
    assert "AMOXICILLINE" in extract_text(_docx_bytes("AMOXICILLINE 500"), "a.docx")
    assert snippet("aaa " * 40 + "Le lot DOLIPRANE est arrivé", ["doliprane"]).startswith("…")
    assert clean_folder_name(" Bons/de:commande ") == "Bonsdecommande"
    assert clean_folder_name("..") == "" and clean_folder_name(".cache") == ""
