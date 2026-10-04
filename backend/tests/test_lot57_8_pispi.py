"""Lot 57.8 — Encaissement PI-SPI : paramètres, QR, bloc sur les factures, connecteurs, notification.
MongoDB simulé (mongomock_motor) ; aucun appel réseau ni API bancaire.
Lancer : cd backend && MONGO_URL=mongodb://localhost:1 DB_NAME=test python -m pytest tests/test_lot57_8_pispi.py -q
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "sawali_test_lot57_8")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
from routes import pispi  # noqa: E402
from routes import pispi_connecteur as conn  # noqa: E402
from routes.cashier import build_invoice_pdf  # noqa: E402

ADMIN = {"id": "u-admin", "email": "admin@sawalismartsystems.com", "role": "admin"}
TEXTE_QR = "  PISPI|alias:sawali.uba@bf | ligne 2\n fin  "   # espaces et saut de ligne à garder tels quels


def _png(taille_min: int = 0) -> bytes:
    """Petite image PNG valide, gonflée au besoin (chunk de texte) pour dépasser une taille."""
    from PIL import Image, PngImagePlugin
    buf = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    if taille_min:
        info.add_text("bourrage", "x" * taille_min)
    Image.new("RGB", (40, 40), "white").save(buf, format="PNG", pnginfo=info)
    return buf.getvalue()


@pytest.fixture()
def base(monkeypatch):
    b = mongomock_motor.AsyncMongoMockClient()[f"lot57_8_{time.time_ns()}"]
    monkeypatch.setattr(pispi, "db", b)
    monkeypatch.setattr(auth, "db", b)
    monkeypatch.delenv("PISPI_FOURNISSEUR", raising=False)
    return b


@pytest.fixture()
def client(base):
    app = FastAPI()
    app.include_router(pispi.router, prefix="/api")
    app.dependency_overrides[auth.get_super_admin] = lambda: ADMIN
    return TestClient(app)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Paramètres
# ---------------------------------------------------------------------------
def test_parametres_par_defaut_inactifs(client):
    r = client.get("/api/admin/pispi/parametres")
    assert r.status_code == 200
    v = r.json()
    assert v["actif"] is False and v["qr_apercu"] is None
    assert {b["libelle"] for b in v["banques"]} == {"UBA", "BSIC", "IB Bank", "Ecobank", "Autre"}
    assert "qr_image_b64" not in v


def test_activation_refusee_sans_adresse_ni_qr(client):
    r = client.put("/api/admin/pispi/parametres", json={"actif": True})
    assert r.status_code == 400 and "Adresse" in r.json()["detail"]
    r = client.put("/api/admin/pispi/parametres", json={"actif": True, "adresse_paiement": "sawali.uba"})
    assert r.status_code == 400 and "QR" in r.json()["detail"]


def test_banque_inconnue_refusee(client):
    r = client.put("/api/admin/pispi/parametres", json={"banque": "banque_x"})
    assert r.status_code == 400


def test_image_trop_lourde_refusee(client):
    lourde = _png(taille_min=pispi.IMAGE_MAX_OCTETS + 10)
    assert len(lourde) > pispi.IMAGE_MAX_OCTETS
    r = client.post("/api/admin/pispi/parametres/qr-image", files={"fichier": ("qr.png", lourde, "image/png")})
    assert r.status_code == 400 and "1 Mo" in r.json()["detail"]


def test_image_non_png_refusee(client):
    r = client.post("/api/admin/pispi/parametres/qr-image", files={"fichier": ("qr.gif", b"GIF89a....", "image/gif")})
    assert r.status_code == 400


def test_image_valide_acceptee_et_prioritaire(client):
    png = _png()
    r = client.post("/api/admin/pispi/parametres/qr-image", files={"fichier": ("qr.png", png, "image/png")})
    assert r.status_code == 200
    v = r.json()
    assert v["qr_image_presente"] is True and v["source_qr"] == "image"
    assert v["qr_apercu"].startswith("data:image/png;base64,")


# ---------------------------------------------------------------------------
# QR refait à partir du texte de la banque : contenu inchangé
# ---------------------------------------------------------------------------
def test_qr_texte_inchange(client, base):
    r = client.put("/api/admin/pispi/parametres", json={
        "actif": True, "banque": "uba", "titulaire": "SAWALI", "adresse_paiement": "sawali.uba@bf", "qr_contenu": TEXTE_QR})
    assert r.status_code == 200, r.text
    p = run(pispi.lire_parametres())
    assert p["qr_contenu"] == TEXTE_QR                      # enregistré sans retouche
    qr = pispi.qr_objet(p["qr_contenu"])
    assert qr.data_list[0].data == TEXTE_QR.encode("utf-8")  # QR codé avec exactement ce texte
    octets, mime = pispi.qr_image(p)
    assert mime == "image/png" and octets.startswith(b"\x89PNG")
    # Décodage réel de l'image si OpenCV est installé (sinon la vérification ci-dessus suffit)
    try:
        import cv2
        import numpy as np
    except ImportError:
        return
    img = cv2.imdecode(np.frombuffer(octets, np.uint8), cv2.IMREAD_GRAYSCALE)
    texte, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
    assert texte == TEXTE_QR


# ---------------------------------------------------------------------------
# Bloc « Payer par PI-SPI » : seulement si actif et facture non soldée
# ---------------------------------------------------------------------------
P_ACTIF = {**pispi.parametres_par_defaut(), "actif": True, "banque": "bsic", "titulaire": "SAWALI SMART SYSTEMS",
           "adresse_paiement": "sawali.bsic@bf", "qr_contenu": "QR-BANQUE-123", "caisse_tenant_id": "t-sawali"}


def _facture_caisse(**k):
    f = {"id": "f1", "number": "F-2026-0007", "kind": "invoice", "status": "issued", "net_to_pay": 125000,
         "tenant_id": "t-sawali", "items": [], "subtotal_ht": 125000, "total_tva": 0, "discount_amount": 0}
    f.update(k)
    return f


def test_bloc_absent_si_inactif():
    p = {**P_ACTIF, "actif": False}
    assert run(pispi.bloc_facture_caisse(_facture_caisse(), p))["afficher"] is False


def test_bloc_present_si_actif_et_non_solde():
    b = run(pispi.bloc_facture_caisse(_facture_caisse(), P_ACTIF))
    assert b["afficher"] is True
    assert b["reference"] == "F-2026-0007" and b["montant"] == 125000
    assert b["montant_texte"] == "125 000 FCFA"
    assert b["adresse_paiement"] == "sawali.bsic@bf" and b["banque"] == "BSIC"
    assert b["consigne"].startswith("Payez avec l'application")
    assert "_qr_octets" not in pispi.sans_octets(b)


def test_bloc_absent_si_facture_soldee_annulee_ou_proforma():
    for f in (_facture_caisse(status="paid"), _facture_caisse(status="cancelled"), _facture_caisse(kind="proforma")):
        assert run(pispi.bloc_facture_caisse(f, P_ACTIF))["afficher"] is False


def test_bloc_absent_sur_facture_d_un_client():
    # Une facture émise par un client avec sa propre Caisse ne porte jamais l'adresse de SAWALI
    assert run(pispi.bloc_facture_caisse(_facture_caisse(tenant_id="t-autre"), P_ACTIF))["afficher"] is False
    assert run(pispi.bloc_facture_caisse(_facture_caisse(), {**P_ACTIF, "caisse_tenant_id": ""}))["afficher"] is False


def test_bloc_facture_intervention():
    f = {"id": "i1", "invoice_number": "FI-2026-0003", "total_xof": 50000, "status": "draft", "paid_at": None}
    b = run(pispi.bloc_facture_intervention(f, P_ACTIF))
    assert b["afficher"] and b["reference"] == "FI-2026-0003" and b["montant"] == 50000
    assert run(pispi.bloc_facture_intervention({**f, "paid_at": "2026-10-04T10:00:00+00:00"}, P_ACTIF))["afficher"] is False


def test_pdf_facture_contient_le_bloc_seulement_si_affiche():
    b = run(pispi.bloc_facture_caisse(_facture_caisse(), P_ACTIF))
    avec = build_invoice_pdf(_facture_caisse(), pispi_bloc=b)
    sans = build_invoice_pdf(_facture_caisse(), pispi_bloc={"afficher": False})
    assert avec.startswith(b"%PDF") and sans.startswith(b"%PDF")
    from pypdf import PdfReader
    texte = lambda pdf: "".join(pg.extract_text() for pg in PdfReader(io.BytesIO(pdf)).pages)  # noqa: E731
    t_avec, t_sans = texte(avec), texte(sans)
    assert "Payer par PI-SPI" in t_avec and "Payer par PI-SPI" not in t_sans
    assert "125 000 FCFA" in t_avec and "sawali.bsic@bf" in t_avec and "F-2026-0007" in t_avec


# ---------------------------------------------------------------------------
# Connecteurs et notification
# ---------------------------------------------------------------------------
def test_connecteur_manuel_par_defaut(monkeypatch):
    monkeypatch.delenv("PISPI_FOURNISSEUR", raising=False)
    c = conn.connecteur_actif()
    assert isinstance(c, conn.ConnecteurManuel)
    d = run(c.demander_paiement(reference="F-1", montant=1000))
    assert d["statut"] == "attendu" and d["reference"] == "F-1"
    assert conn.notifications_actives() is False


@pytest.mark.parametrize("code", ["ecobank", "uba", "bsic", "ib_bank"])
def test_connecteurs_bancaires_non_disponibles(monkeypatch, code):
    monkeypatch.setenv("PISPI_FOURNISSEUR", code)
    c = conn.connecteur_actif()
    assert c.code == code
    with pytest.raises(conn.ConnecteurIndisponible, match="non disponible"):
        run(c.demander_paiement(reference="F-1", montant=1000))
    assert conn.notifications_actives() is False


def test_notification_desactivee(client):
    r = client.post("/api/pispi/notification", json={"reference": "F-1"})
    assert r.status_code == 503 and "désactivées" in r.json()["detail"]


def test_connecteur_n_expose_aucune_valeur(client, monkeypatch):
    monkeypatch.setenv("PISPI_CLIENT_SECRET", "valeur-fictive-de-test")
    v = client.get("/api/admin/pispi/connecteur").json()
    assert v["code"] == "manuel" and v["variables"]["PISPI_CLIENT_SECRET"] is True
    assert "valeur-fictive-de-test" not in str(v)


# ---------------------------------------------------------------------------
# Saisie manuelle d'un encaissement (pispi_transactions)
# ---------------------------------------------------------------------------
def test_saisie_manuelle_rapproche_facture_intervention(client, base):
    run(base.interventions_invoices.insert_one({"id": "i1", "invoice_number": "FI-2026-0003", "total_xof": 50000,
                                                "status": "draft", "paid_at": None}))
    r = client.post("/api/admin/pispi/encaissements",
                    json={"reference": "FI-2026-0003", "montant": 50000, "reference_bancaire": "UBA-OP-77"})
    assert r.status_code == 200, r.text
    assert r.json()["transaction"]["statut"] == "rapproche"
    f = run(base.interventions_invoices.find_one({"id": "i1"}))
    assert f["paid_mode"] == "PISPI" and f["paid_reference"] == "UBA-OP-77" and f["paid_at"]
    tx = client.get("/api/admin/pispi/transactions").json()
    assert len(tx) == 1 and tx[0]["document"]["type"] == "intervention"


def test_saisie_manuelle_sans_reference_bancaire_refusee(client):
    r = client.post("/api/admin/pispi/encaissements", json={"reference": "F-1", "montant": 10, "reference_bancaire": " "})
    assert r.status_code == 400


def test_mode_pispi_reconnu():
    assert pispi.est_mode_pispi({"kind": "pispi"}) and not pispi.est_mode_pispi({"kind": "electronic"})
