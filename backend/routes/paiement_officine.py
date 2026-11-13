# paiement_officine.py — Lot 386 : PAIEMENT MOBILE AU COMPTOIR des officines (QR code + séquence USSD).
#
# Décision du propriétaire (13/11/2026) : pour les ordonnances le QR code reste le moyen principal (pas de nouvel équipement,
# tout le monde n'a pas un téléphone NFC) ; pour le PAIEMENT, le client scanne un QR code au comptoir et obtient la séquence
# USSD de l'opérateur (Orange Money, Moov Money, Telecel Money) avec le code marchand de la pharmacie. Les séquences sont celles
# du catalogue de « mobile-payments-web » (dépôt Claude), confirmées par le propriétaire le 13/11/2026 :
#     Orange        *144*10*{code}*{montant}#
#     Moov Africa   *555*2*{code}*{montant}#
#     Telecel Faso  *133*3*{code}*{montant}#
#
# En résumé (pour un développeur WinDev) :
#   - la pharmacie (portail officines) saisit son code marchand par opérateur ; SAWALI lui attribue un jeton public aléatoire
#     et lui fournit le QR à imprimer (adresse publique /officine/payer/<jeton>) ;
#   - le client scanne le QR, choisit l'opérateur dans une liste, saisit le montant : SAWALI construit la séquence et le lien
#     « tel: » (le « # » est encodé %23). Sur iPhone le lien ne pré-remplit pas les codes contenant * ou # : la page propose
#     alors de COPIER la séquence ;
#   - AUCUNE nouvelle collection (cluster MongoDB plein) : champs `paiement_mobile` et `paiement_jeton` du document de l'officine
#     (db.officines) ; AUCUN paiement ne transite par SAWALI : le client compose la séquence sur son téléphone.
from __future__ import annotations

import io
import os
import re
import uuid
from typing import Any, Dict, List
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request  # noqa: F401  (Request au niveau du module : annotations résolues)
from fastapi.responses import Response
from pydantic import BaseModel, Field

# Catalogue des paiements marchands (clé = nom affiché dans la liste déroulante).
# ATTENTION — COPIE : la SOURCE DE RÉFÉRENCE de ces séquences est la plateforme auRor (= mobile-payments, dépôt ShuyahBF/Claude,
# fichier mobile-payments-web/backend/catalogue_defaut.py). Si un opérateur change une séquence, la corriger À LA FOIS dans auRor et ici
# (précisé par le propriétaire le 14/11/2026). Le test test_sequences_validees_par_le_proprietaire garde les valeurs actuelles.
CATALOGUE = {
    "Orange": "*144*10*{code}*{montant}#",
    "Moov Africa": "*555*2*{code}*{montant}#",
    "Telecel Faso": "*133*3*{code}*{montant}#",
}
OPERATEURS = list(CATALOGUE)
MONTANT_MAX = 10_000_000       # FCFA : garde-fou contre une faute de frappe
_CODE_RE = re.compile(r"^\d{3,12}$")


# =====================================================================================
# Logique pure (testée : tests/test_lot386_paiement_officine.py)
# =====================================================================================

def nettoyer_codes(brut: Any) -> List[Dict[str, str]]:
    """[{operateur, code}] validé : opérateur du catalogue (sans doublon), code marchand de 3 à 12 chiffres ; ValueError sinon.
    Une ligne dont le code est vide est ignorée (opérateur non utilisé)."""
    sortie: List[Dict[str, str]] = []
    vus = set()
    for ligne in brut or []:
        if not isinstance(ligne, dict):
            raise ValueError("Format invalide")
        operateur = str(ligne.get("operateur") or "").strip()
        code = re.sub(r"\s+", "", str(ligne.get("code") or ""))
        if not code:
            continue
        if operateur not in CATALOGUE:
            raise ValueError(f"Opérateur inconnu : {operateur or '(vide)'}")
        if operateur in vus:
            raise ValueError(f"{operateur} : une seule ligne par opérateur")
        if not _CODE_RE.match(code):
            raise ValueError(f"{operateur} : le code marchand doit contenir de 3 à 12 chiffres")
        vus.add(operateur)
        sortie.append({"operateur": operateur, "code": code})
    return sortie


def montant_valide(brut: Any) -> int:
    """Montant entier en FCFA, > 0 et <= MONTANT_MAX ; ValueError (message lisible) sinon."""
    texte = re.sub(r"\s+", "", str(brut if brut is not None else ""))
    if not texte.isdigit():
        raise ValueError("Le montant doit être un nombre entier de francs CFA")
    montant = int(texte)
    if montant <= 0:
        raise ValueError("Le montant doit être supérieur à 0")
    if montant > MONTANT_MAX:
        raise ValueError("Montant trop élevé : vérifiez la saisie")
    return montant


def construire_code(operateur: str, code_marchand: str, montant: int) -> str:
    """Séquence USSD du paiement marchand (ex. « *144*10*123456*5000# »)."""
    return CATALOGUE[operateur].replace("{code}", code_marchand).replace("{montant}", str(montant))


def lien_tel(code_ussd: str) -> str:
    """Lien « tel: » : le « # » est encodé en %23 (sinon il serait lu comme une ancre)."""
    return "tel:" + quote(code_ussd, safe="*")


def adresse_publique(jeton: str) -> str:
    """Adresse imprimée dans le QR du comptoir : page publique de paiement."""
    site = (os.environ.get("FRONTEND_PUBLIC_URL") or "https://sawalismartsystems.com").rstrip("/")
    return f"{site}/officine/payer/{jeton}"


def png_qr(adresse: str) -> bytes:
    """QR code (PNG, correction d'erreur moyenne) de l'adresse, prêt à imprimer."""
    import qrcode
    img = qrcode.make(adresse, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    tampon = io.BytesIO()
    img.save(tampon, format="PNG")
    return tampon.getvalue()


class CodesCorps(BaseModel):
    operateurs: List[Dict[str, Any]] = Field(default_factory=list)


class UssdCorps(BaseModel):
    operateur: str
    montant: Any


# =====================================================================================
# Routes
# =====================================================================================

def setup_paiement_officine_routes(*, db, api, get_current_officine, get_current_user) -> None:
    """Branche les routes du lot 386 (appelée depuis server_parts/p20)."""

    def _vue(officine: Dict[str, Any]) -> Dict[str, Any]:
        jeton = officine.get("paiement_jeton")
        return {"operateurs": officine.get("paiement_mobile") or [], "catalogue": OPERATEURS,
                "jeton": jeton, "url_publique": adresse_publique(jeton) if jeton else None}

    @api.get("/officines-portal/me/paiement", tags=["Officines — paiement au comptoir"])
    async def lire(officine: dict = Depends(get_current_officine)):
        return _vue(officine)

    @api.put("/officines-portal/me/paiement", tags=["Officines — paiement au comptoir"])
    async def enregistrer(corps: CodesCorps, officine: dict = Depends(get_current_officine)):
        """Enregistre les codes marchands (un par opérateur) ; crée le jeton public du QR à la première configuration."""
        try:
            codes = nettoyer_codes(corps.operateurs)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        jeton = officine.get("paiement_jeton") or uuid.uuid4().hex
        await db.officines.update_one({"id": officine["id"]}, {"$set": {"paiement_mobile": codes, "paiement_jeton": jeton}})
        return _vue({**officine, "paiement_mobile": codes, "paiement_jeton": jeton})

    @api.get("/officines-portal/me/paiement/qr.png", tags=["Officines — paiement au comptoir"])
    async def qr(officine: dict = Depends(get_current_officine)):
        """QR code à imprimer et à poser au comptoir (renvoie 404 tant qu'aucun code marchand n'est enregistré)."""
        if not officine.get("paiement_jeton") or not officine.get("paiement_mobile"):
            raise HTTPException(status_code=404, detail="Enregistrez d'abord au moins un code marchand")
        return Response(content=png_qr(adresse_publique(officine["paiement_jeton"])), media_type="image/png",
                        headers={"Cache-Control": "no-store"})

    async def _officine_publique(jeton: str) -> Dict[str, Any]:
        doc = await db.officines.find_one({"paiement_jeton": jeton, "status": "active"}, {"_id": 0}) if re.fullmatch(r"[0-9a-f]{32}", jeton or "") else None
        if not doc or not doc.get("paiement_mobile"):
            raise HTTPException(status_code=404, detail="Paiement indisponible")
        return doc

    @api.get("/officine-paiement/{jeton}", tags=["Officines — paiement au comptoir (public)"])
    async def page_publique(jeton: str):
        """Page publique : nom de la pharmacie et opérateurs acceptés (jamais les autres données de la pharmacie)."""
        doc = await _officine_publique(jeton)
        return {"nom": doc.get("name") or "Pharmacie", "operateurs": [c["operateur"] for c in doc["paiement_mobile"]]}

    @api.post("/officine-paiement/{jeton}/ussd", tags=["Officines — paiement au comptoir (public)"])
    async def ussd(jeton: str, corps: UssdCorps):
        """Séquence USSD et lien « tel: » pour l'opérateur et le montant choisis. Rien n'est enregistré ni payé ici."""
        doc = await _officine_publique(jeton)
        ligne = next((c for c in doc["paiement_mobile"] if c["operateur"] == corps.operateur), None)
        if not ligne:
            raise HTTPException(status_code=422, detail="Cet opérateur n'est pas accepté par cette pharmacie")
        try:
            montant = montant_valide(corps.montant)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        code = construire_code(corps.operateur, ligne["code"], montant)
        return {"nom": doc.get("name") or "Pharmacie", "operateur": corps.operateur, "montant": montant, "code_ussd": code, "lien_tel": lien_tel(code)}

    @api.get("/admin/officines-paiement", tags=["Officines — paiement au comptoir"])
    async def resume_admin(user: dict = Depends(get_current_user)):
        """Rubrique des Paramètres : combien de pharmacies ont activé le paiement au comptoir, avec leurs opérateurs (jamais les codes)."""
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        lignes = []
        async for o in db.officines.find({"paiement_mobile.0": {"$exists": True}}, {"_id": 0, "name": 1, "city": 1, "paiement_mobile": 1}).limit(500):
            lignes.append({"nom": o.get("name"), "ville": o.get("city"), "operateurs": [c["operateur"] for c in o["paiement_mobile"]]})
        total = await db.officines.count_documents({})
        return {"catalogue": CATALOGUE, "configurees": len(lignes), "total": total, "officines": lignes}
