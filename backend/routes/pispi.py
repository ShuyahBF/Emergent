"""Lot 57.8 — Encaissement PI-SPI : bloc « Payer par PI-SPI » sur les factures émises par SAWALI.

PI-SPI = Plateforme Interopérable du Système de Paiement Instantané (BCEAO, UEMOA).
Le QR code PI-SPI est fourni par la banque de SAWALI (UBA, BSIC, IB Bank, Ecobank…) ; il contient
l'« adresse de paiement » (alias), jamais un numéro de téléphone. SAWALI n'invente aucun QR :
  - soit l'administrateur colle le TEXTE décodé du QR de la banque -> on refait l'image du QR
    à partir de ce texte, tel quel (aucune modification) ;
  - soit il téléverse l'IMAGE du QR (PNG/JPG, 1 Mo maximum) -> imprimée telle quelle.
Le QR est statique : il ne contient pas le montant. Le montant restant dû et la référence à
indiquer (n° de facture) sont donc écrits en texte à côté du QR.

Paramètres GLOBAUX (une seule configuration pour SAWALI), réservés au super-administrateur :
  document db.settings {_id: "pispi_encaissement"}.

Factures concernées (émises par SAWALI) :
  - factures d'interventions (db.interventions_invoices, PDF /me/invoices/from-interventions/{id}/pdf) ;
  - factures de la Caisse de SAWALI (db.invoices) : uniquement celles de l'entité choisie dans les
    paramètres (caisse_tenant_id), pour ne JAMAIS imprimer l'adresse de paiement de SAWALI sur les
    factures que les clients émettent avec leur propre Caisse. Les proformas et reçus ne sont pas concernés.

Routes :
  GET    /api/admin/pispi/parametres            réglages + aperçu (super-admin)
  PUT    /api/admin/pispi/parametres            enregistre les réglages (super-admin)
  POST   /api/admin/pispi/parametres/qr-image   téléverse l'image du QR (PNG/JPG ≤ 1 Mo)
  DELETE /api/admin/pispi/parametres/qr-image   retire l'image du QR
  GET    /api/admin/pispi/transactions          derniers encaissements PI-SPI (collection pispi_transactions)
  POST   /api/admin/pispi/encaissements         saisie manuelle d'un encaissement (référence bancaire)
  GET    /api/admin/pispi/connecteur            connecteur actif (jamais de valeur secrète)
  POST   /api/pispi/notification                prévue pour les banques, DÉSACTIVÉE (503) tant
                                                qu'aucun connecteur bancaire n'est branché.
"""
from __future__ import annotations

import base64
import io
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import qrcode
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from auth import get_super_admin
from db import db
from routes import pispi_connecteur as connecteurs

log = logging.getLogger("sawali.pispi")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
ID_PARAMETRES = "pispi_encaissement"          # _id du document dans db.settings
IMAGE_MAX_OCTETS = 1024 * 1024                # 1 Mo maximum pour l'image du QR
BANQUES = {"uba": "UBA", "bsic": "BSIC", "ib_bank": "IB Bank", "ecobank": "Ecobank", "autre": "Autre"}
CONSIGNE_DEFAUT = ("Payez avec l'application de votre banque ou de votre mobile money (PI-SPI). "
                   "Indiquez la référence ci-dessous.")
STATUTS_TRANSACTION = ("attendu", "recu", "rapproche", "rejete")
MODE_PISPI = "PISPI"                          # code du mode de règlement PI-SPI


class ParametresInvalides(ValueError):
    """Saisie refusée (message affiché tel quel à l'administrateur)."""


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def montant_fcfa(n: Any) -> str:
    """Montant au format français, sans décimale (ex. 125 000)."""
    try:
        return f"{round(float(n or 0)):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


# ---------------------------------------------------------------------------
# Paramètres : valeurs par défaut, lecture, validation, enregistrement
# ---------------------------------------------------------------------------
def parametres_par_defaut() -> Dict[str, Any]:
    return {
        "actif": False,
        "banque": "uba",
        "banque_autre": "",          # libellé libre quand banque = « autre »
        "titulaire": "",
        "adresse_paiement": "",
        "qr_contenu": "",            # texte décodé du QR fourni par la banque
        "qr_image_b64": "",          # image du QR téléversée (base64)
        "qr_image_type": "",         # image/png ou image/jpeg
        "consigne": CONSIGNE_DEFAUT,
        "caisse_tenant_id": "",      # entité de la Caisse dont les factures portent le bloc
        "caisse_tenant_nom": "",
    }


async def lire_parametres() -> Dict[str, Any]:
    """Réglages enregistrés, complétés par les valeurs par défaut."""
    doc = await db.settings.find_one({"_id": ID_PARAMETRES}, {"_id": 0}) or {}
    p = parametres_par_defaut()
    p.update({k: v for k, v in doc.items() if k in p or k in ("modifie_le", "modifie_par")})
    return p


def libelle_banque(p: Dict[str, Any]) -> str:
    """Nom de la banque affiché (« Autre » remplacé par le libellé saisi)."""
    if p.get("banque") == "autre":
        return (p.get("banque_autre") or "").strip() or "Autre"
    return BANQUES.get(p.get("banque") or "", "")


def valider_parametres(corps: Dict[str, Any], actuels: Dict[str, Any]) -> Dict[str, Any]:
    """Contrôle la saisie et renvoie les champs à enregistrer (les champs absents sont conservés)."""
    maj: Dict[str, Any] = {}
    if corps.get("actif") is not None:
        maj["actif"] = bool(corps["actif"])
    if corps.get("banque") is not None:
        b = str(corps["banque"]).strip().lower()
        if b not in BANQUES:
            raise ParametresInvalides("Banque inconnue : choisir UBA, BSIC, IB Bank, Ecobank ou Autre.")
        maj["banque"] = b
    # Champs texte : espaces de début/fin retirés (sauf le contenu du QR, gardé tel quel)
    for champ, maxi in (("banque_autre", 80), ("titulaire", 160), ("adresse_paiement", 160),
                        ("consigne", 400), ("caisse_tenant_id", 80), ("caisse_tenant_nom", 200)):
        if corps.get(champ) is not None:
            v = str(corps[champ]).strip()
            if len(v) > maxi:
                raise ParametresInvalides(f"Champ « {champ} » trop long ({maxi} caractères maximum).")
            maj[champ] = v
    if corps.get("qr_contenu") is not None:
        texte = str(corps["qr_contenu"])
        # Le texte du QR n'est JAMAIS modifié : on refuse seulement un texte trop long pour un QR.
        if len(texte.encode("utf-8")) > 2000:
            raise ParametresInvalides("Texte du QR trop long (2 000 octets maximum).")
        maj["qr_contenu"] = "" if not texte.strip() else texte
    # Contrôle d'ensemble : on ne peut pas activer sans adresse de paiement ni QR
    final = {**actuels, **maj}
    if final.get("banque") == "autre" and final.get("actif") and not (final.get("banque_autre") or "").strip():
        raise ParametresInvalides("Indiquez le nom de la banque (choix « Autre »).")
    if final.get("actif"):
        if not (final.get("adresse_paiement") or "").strip():
            raise ParametresInvalides("Adresse de paiement PI-SPI obligatoire pour activer l'encaissement.")
        if not (final.get("qr_contenu") or final.get("qr_image_b64")):
            raise ParametresInvalides("QR de la banque obligatoire (texte décodé ou image) pour activer l'encaissement.")
    if "consigne" in maj and not maj["consigne"]:
        maj["consigne"] = CONSIGNE_DEFAUT
    return maj


def valider_image(contenu: bytes) -> str:
    """Contrôle l'image du QR (PNG ou JPEG, 1 Mo maximum) et renvoie son type MIME."""
    if not contenu:
        raise ParametresInvalides("Fichier vide.")
    if len(contenu) > IMAGE_MAX_OCTETS:
        raise ParametresInvalides("Image trop lourde : 1 Mo maximum.")
    # Type reconnu par sa signature (pas par l'extension, qui peut mentir)
    if contenu.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif contenu[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    else:
        raise ParametresInvalides("Format refusé : PNG ou JPG uniquement.")
    # Vérifie que l'image s'ouvre vraiment (fichier non corrompu)
    try:
        from PIL import Image
        Image.open(io.BytesIO(contenu)).verify()
    except Exception as exc:  # noqa: BLE001
        raise ParametresInvalides("Image illisible ou corrompue.") from exc
    return mime


async def enregistrer_parametres(corps: Dict[str, Any], admin: Dict[str, Any]) -> Dict[str, Any]:
    actuels = await lire_parametres()
    maj = valider_parametres(corps, actuels)
    maj.update({"modifie_le": _maintenant(), "modifie_par": admin.get("email")})
    await db.settings.update_one({"_id": ID_PARAMETRES}, {"$set": maj}, upsert=True)
    return await lire_parametres()


async def enregistrer_image(contenu: bytes, admin: Dict[str, Any]) -> Dict[str, Any]:
    mime = valider_image(contenu)
    await db.settings.update_one(
        {"_id": ID_PARAMETRES},
        {"$set": {"qr_image_b64": base64.b64encode(contenu).decode("ascii"), "qr_image_type": mime,
                  "modifie_le": _maintenant(), "modifie_par": admin.get("email")}},
        upsert=True,
    )
    return await lire_parametres()


# ---------------------------------------------------------------------------
# QR : image téléversée telle quelle, ou QR refait à partir du texte de la banque
# ---------------------------------------------------------------------------
def qr_objet(texte: str) -> qrcode.QRCode:
    """QR construit à partir du texte EXACT fourni par la banque (aucune transformation)."""
    qr = qrcode.QRCode(version=None, box_size=8, border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(texte, optimize=0)
    qr.make(fit=True)
    return qr


def qr_png_depuis_texte(texte: str) -> bytes:
    img = qr_objet(texte).make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def qr_image(p: Dict[str, Any]) -> Optional[tuple]:
    """(octets, type MIME) du QR à imprimer, ou None. L'image de la banque est prioritaire."""
    if p.get("qr_image_b64"):
        try:
            return base64.b64decode(p["qr_image_b64"]), p.get("qr_image_type") or "image/png"
        except Exception:  # noqa: BLE001
            log.warning("[pispi] image du QR illisible en base")
    if p.get("qr_contenu"):
        return qr_png_depuis_texte(p["qr_contenu"]), "image/png"
    return None


# ---------------------------------------------------------------------------
# Bloc « Payer par PI-SPI » : décide s'il s'affiche et prépare son contenu
# ---------------------------------------------------------------------------
def doit_afficher(p: Dict[str, Any], reste_du: float) -> bool:
    """Bloc affiché si : encaissement actif, QR présent, adresse renseignée et facture non soldée."""
    return bool(
        p.get("actif")
        and (p.get("qr_contenu") or p.get("qr_image_b64"))
        and (p.get("adresse_paiement") or "").strip()
        and float(reste_du or 0) > 0
    )


def bloc(p: Dict[str, Any], *, reference: str, reste_du: float) -> Dict[str, Any]:
    """Contenu du bloc (pour le PDF et pour la page d'impression)."""
    if not doit_afficher(p, reste_du):
        return {"afficher": False}
    img = qr_image(p)
    if not img:
        return {"afficher": False}
    octets, mime = img
    return {
        "afficher": True,
        "titre": "Payer par PI-SPI",
        "banque": libelle_banque(p),
        "titulaire": p.get("titulaire") or "",
        "adresse_paiement": p.get("adresse_paiement") or "",
        "montant": float(reste_du),
        "montant_texte": f"{montant_fcfa(reste_du)} FCFA",
        "reference": reference or "",
        "consigne": p.get("consigne") or CONSIGNE_DEFAUT,
        "qr_data_url": f"data:{mime};base64,{base64.b64encode(octets).decode('ascii')}",
        "_qr_octets": octets,   # usage interne (PDF) : retiré avant envoi au navigateur
    }


def sans_octets(b: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in b.items() if not k.startswith("_")}


def reste_du_facture_caisse(inv: Dict[str, Any]) -> float:
    """Facture de la Caisse : reste dû = net à payer tant qu'elle n'est ni réglée ni annulée.
    Les proformas ne sont pas des factures : rien à payer."""
    if (inv.get("kind") or "invoice") != "invoice":
        return 0.0
    if inv.get("status") in ("paid", "cancelled") or inv.get("paid_at") or inv.get("deleted_at"):
        return 0.0
    return max(0.0, float(inv.get("net_to_pay") or 0))


def reste_du_facture_intervention(inv: Dict[str, Any]) -> float:
    """Facture d'interventions : reste dû = total tant qu'elle n'est ni payée ni annulée."""
    if inv.get("status") == "cancelled" or inv.get("paid_at"):
        return 0.0
    return max(0.0, float(inv.get("total_xof") or 0))


async def bloc_facture_caisse(inv: Optional[Dict[str, Any]], p: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Bloc pour une facture de la Caisse : seulement pour l'entité choisie (Caisse de SAWALI)."""
    if not inv:
        return {"afficher": False}
    p = p if p is not None else await lire_parametres()
    cible = (p.get("caisse_tenant_id") or "").strip()
    if not cible or inv.get("tenant_id") != cible:
        return {"afficher": False}
    return bloc(p, reference=inv.get("number") or "", reste_du=reste_du_facture_caisse(inv))


async def bloc_facture_intervention(inv: Optional[Dict[str, Any]], p: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Bloc pour une facture d'interventions (toujours émise par SAWALI)."""
    if not inv:
        return {"afficher": False}
    p = p if p is not None else await lire_parametres()
    return bloc(p, reference=inv.get("invoice_number") or "", reste_du=reste_du_facture_intervention(inv))


def flowables_pdf(b: Dict[str, Any]) -> List[Any]:
    """Bloc « Payer par PI-SPI » pour un PDF ReportLab : QR à gauche, informations à droite,
    dans un cadre. Liste vide si le bloc ne doit pas s'afficher."""
    if not b or not b.get("afficher") or not b.get("_qr_octets"):
        return []
    from xml.sax.saxutils import escape
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import Image as RLImage, KeepTogether, Paragraph, Spacer, Table, TableStyle

    st = getSampleStyleSheet()
    titre = ParagraphStyle("PispiTitre", parent=st["Normal"], fontName="Helvetica-Bold", fontSize=11,
                           textColor=colors.HexColor("#0F766E"), spaceAfter=3)
    corps = ParagraphStyle("PispiCorps", parent=st["Normal"], fontSize=9, leading=12)
    petit = ParagraphStyle("PispiPetit", parent=st["Normal"], fontSize=8, leading=10,
                           textColor=colors.HexColor("#475569"))
    e = lambda t: escape(str(t or ""))  # noqa: E731 — échappement du texte saisi
    lignes = [
        Paragraph(e(b["titre"]), titre),
        Paragraph(f"<b>Montant à payer :</b> {e(b['montant_texte'])}", corps),
        Paragraph(f"<b>Référence à indiquer :</b> {e(b['reference'])}", corps),
        Paragraph(f"<b>Adresse de paiement :</b> {e(b['adresse_paiement'])}", corps),
    ]
    if b.get("titulaire") or b.get("banque"):
        lignes.append(Paragraph(f"<b>Bénéficiaire :</b> {e(b.get('titulaire'))}"
                                f"{' — ' + e(b.get('banque')) if b.get('banque') else ''}", corps))
    lignes.append(Spacer(1, 3))
    lignes.append(Paragraph(e(b.get("consigne")), petit))
    image = RLImage(io.BytesIO(b["_qr_octets"]), width=92, height=92)
    t = Table([[image, lignes]], colWidths=[104, 400])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#0F766E")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F0FDFA")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    t.hAlign = "LEFT"
    return [Spacer(1, 10), KeepTogether([t])]


# ---------------------------------------------------------------------------
# Transactions PI-SPI (collection pispi_transactions)
# ---------------------------------------------------------------------------
async def enregistrer_transaction(*, reference: str, montant: float, statut: str = "recu",
                                  source: str = "manuel", reference_bancaire: Optional[str] = None,
                                  document: Optional[Dict[str, Any]] = None,
                                  saisi_par: Optional[str] = None) -> Dict[str, Any]:
    """Ajoute un encaissement PI-SPI : référence = n° de facture, statut attendu|recu|rapproche|rejete."""
    if statut not in STATUTS_TRANSACTION:
        raise ParametresInvalides("Statut de transaction inconnu.")
    if source not in ("manuel", "api"):
        raise ParametresInvalides("Source de transaction inconnue.")
    doc = {
        "id": str(uuid.uuid4()),
        "reference": (reference or "").strip(),
        "montant": float(montant or 0),
        "devise": "XOF",
        "statut": statut,
        "source": source,
        "reference_bancaire": (reference_bancaire or "").strip() or None,
        "document": document or None,          # {type: caisse|intervention, id, numero}
        "date": _maintenant(),
        "saisi_par": saisi_par,
    }
    await db.pispi_transactions.insert_one(doc.copy())
    return doc


async def saisie_manuelle(*, reference: str, montant: float, reference_bancaire: str,
                          admin: Dict[str, Any]) -> Dict[str, Any]:
    """Saisie manuelle d'un encaissement PI-SPI et rapprochement de la facture correspondante.
    - facture d'interventions : marquée payée (mode PI-SPI + référence bancaire) si le montant
      couvre le reste dû ;
    - facture de la Caisse : enregistrée « reçue » ; le règlement (et le reçu) se fait dans la
      Caisse avec le mode de paiement PI-SPI, ce qui rapproche la facture."""
    reference = (reference or "").strip()
    reference_bancaire = (reference_bancaire or "").strip()
    if not reference:
        raise ParametresInvalides("Référence (n° de facture) obligatoire.")
    if not reference_bancaire:
        raise ParametresInvalides("Référence bancaire de l'opération PI-SPI obligatoire.")
    if float(montant or 0) <= 0:
        raise ParametresInvalides("Montant invalide.")
    qui = admin.get("email")

    # 1) Facture d'interventions (émise par SAWALI)
    fi = await db.interventions_invoices.find_one({"invoice_number": reference}, {"_id": 0})
    if fi:
        reste = reste_du_facture_intervention(fi)
        doc_lie = {"type": "intervention", "id": fi.get("id"), "numero": reference}
        if reste > 0 and float(montant) >= reste:
            await db.interventions_invoices.update_one({"id": fi["id"]}, {"$set": {
                "paid_at": _maintenant(), "paid_mode": MODE_PISPI, "paid_reference": reference_bancaire,
                "updated_at": _maintenant()}})
            tx = await enregistrer_transaction(reference=reference, montant=montant, statut="rapproche",
                                               reference_bancaire=reference_bancaire, document=doc_lie, saisi_par=qui)
            return {"transaction": tx, "message": "Facture d'interventions marquée payée (PI-SPI)."}
        tx = await enregistrer_transaction(reference=reference, montant=montant, statut="recu",
                                           reference_bancaire=reference_bancaire, document=doc_lie, saisi_par=qui)
        msg = ("Facture déjà soldée : encaissement enregistré sans rapprochement." if reste <= 0
               else f"Montant inférieur au reste dû ({montant_fcfa(reste)} FCFA) : encaissement enregistré, facture non soldée.")
        return {"transaction": tx, "message": msg}

    # 2) Facture de la Caisse
    fc = await db.invoices.find_one({"number": reference, "kind": "invoice"}, {"_id": 0, "id": 1, "number": 1})
    if fc:
        tx = await enregistrer_transaction(reference=reference, montant=montant, statut="recu",
                                           reference_bancaire=reference_bancaire,
                                           document={"type": "caisse", "id": fc.get("id"), "numero": reference},
                                           saisi_par=qui)
        return {"transaction": tx, "message": "Encaissement enregistré. Réglez la facture dans la Caisse avec le "
                                              "mode de paiement « PI-SPI » et cette référence bancaire."}

    # 3) Aucune facture trouvée : gardé pour rapprochement ultérieur
    tx = await enregistrer_transaction(reference=reference, montant=montant, statut="recu",
                                       reference_bancaire=reference_bancaire, saisi_par=qui)
    return {"transaction": tx, "message": "Aucune facture ne porte cette référence : encaissement gardé à rapprocher."}


def est_mode_pispi(mode: Optional[Dict[str, Any]]) -> bool:
    """Mode de paiement de la Caisse reconnu comme PI-SPI (catégorie « pispi »)."""
    return bool(mode) and str(mode.get("kind") or "").lower() == "pispi"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
class ParametresIn(BaseModel):
    actif: Optional[bool] = None
    banque: Optional[str] = Field(None, max_length=20)
    banque_autre: Optional[str] = Field(None, max_length=200)
    titulaire: Optional[str] = Field(None, max_length=400)
    adresse_paiement: Optional[str] = Field(None, max_length=400)
    qr_contenu: Optional[str] = Field(None, max_length=4000)
    consigne: Optional[str] = Field(None, max_length=1000)
    caisse_tenant_id: Optional[str] = Field(None, max_length=200)
    caisse_tenant_nom: Optional[str] = Field(None, max_length=400)


class EncaissementIn(BaseModel):
    reference: str = Field(..., min_length=1, max_length=80)
    montant: float = Field(..., gt=0)
    reference_bancaire: str = Field(..., min_length=1, max_length=120)


def _vue(p: Dict[str, Any]) -> Dict[str, Any]:
    """Réglages renvoyés à l'écran, avec un aperçu du bloc (montant d'exemple)."""
    v = {k: val for k, val in p.items() if k != "qr_image_b64"}
    v["qr_image_presente"] = bool(p.get("qr_image_b64"))
    v["banques"] = [{"valeur": k, "libelle": lib} for k, lib in BANQUES.items()]
    v["consigne_defaut"] = CONSIGNE_DEFAUT
    v["image_max_octets"] = IMAGE_MAX_OCTETS
    img = qr_image(p)
    v["qr_apercu"] = (f"data:{img[1]};base64,{base64.b64encode(img[0]).decode('ascii')}" if img else None)
    v["source_qr"] = "image" if p.get("qr_image_b64") else ("texte" if p.get("qr_contenu") else None)
    return v


router = APIRouter(tags=["Encaissement PI-SPI (lot 57.8)"])


@router.get("/admin/pispi/parametres")
async def route_lire(_: dict = Depends(get_super_admin)):
    return _vue(await lire_parametres())


@router.put("/admin/pispi/parametres")
async def route_enregistrer(corps: ParametresIn, adm: dict = Depends(get_super_admin)):
    try:
        return _vue(await enregistrer_parametres(corps.model_dump(), adm))
    except ParametresInvalides as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/admin/pispi/parametres/qr-image")
async def route_image(fichier: UploadFile = File(...), adm: dict = Depends(get_super_admin)):
    contenu = await fichier.read(IMAGE_MAX_OCTETS + 1)   # lecture bornée : jamais plus de 1 Mo + 1 octet
    try:
        return _vue(await enregistrer_image(contenu, adm))
    except ParametresInvalides as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/admin/pispi/parametres/qr-image")
async def route_retirer_image(adm: dict = Depends(get_super_admin)):
    p = await lire_parametres()
    if p.get("actif") and not p.get("qr_contenu"):
        raise HTTPException(status_code=400, detail="Désactivez d'abord l'encaissement ou saisissez le texte du QR.")
    await db.settings.update_one({"_id": ID_PARAMETRES}, {"$set": {
        "qr_image_b64": "", "qr_image_type": "", "modifie_le": _maintenant(), "modifie_par": adm.get("email")}},
        upsert=True)
    return _vue(await lire_parametres())


@router.get("/admin/pispi/transactions")
async def route_transactions(limite: int = 50, _: dict = Depends(get_super_admin)):
    limite = max(1, min(int(limite or 50), 500))
    return await db.pispi_transactions.find({}, {"_id": 0}).sort("date", -1).limit(limite).to_list(limite)


@router.post("/admin/pispi/encaissements")
async def route_encaissement(corps: EncaissementIn, adm: dict = Depends(get_super_admin)):
    try:
        return await saisie_manuelle(reference=corps.reference, montant=corps.montant,
                                     reference_bancaire=corps.reference_bancaire, admin=adm)
    except ParametresInvalides as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/admin/pispi/connecteur")
async def route_connecteur(_: dict = Depends(get_super_admin)):
    c = connecteurs.connecteur_actif()
    return {
        "code": c.code,
        "libelle": c.libelle,
        "automatique": c.automatique,
        "notifications_actives": connecteurs.notifications_actives(),
        # Présence des variables seulement (jamais leur valeur)
        "variables": {k: bool(os.environ.get(k)) for k in
                      ("PISPI_FOURNISSEUR", "PISPI_API_URL", "PISPI_CLIENT_ID", "PISPI_CLIENT_SECRET")},
    }


@router.post("/pispi/notification")
async def route_notification(request: Request):
    """Notification de paiement envoyée par une banque : DÉSACTIVÉE tant qu'aucun connecteur
    bancaire automatique n'est branché (aucune API Business homologuée obtenue)."""
    if not connecteurs.notifications_actives():
        raise HTTPException(status_code=503, detail="Notifications PI-SPI désactivées : aucun connecteur bancaire "
                                                    "configuré (encaissements saisis manuellement).")
    c = connecteurs.connecteur_actif()
    try:
        return await c.notification(corps=await request.body(), entetes=dict(request.headers))
    except connecteurs.ConnecteurIndisponible as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
