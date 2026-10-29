# paiement_formulaires.py — Lot 361 : moyens de paiement des formulaires et sondages (Liluvine « !formulaire »).
#
# Le propriétaire choisit, dans les Paramètres, les moyens ACTIFS sur le lien de paiement de ces documents :
#   ORANGE, MOOV, TELECEL (opérateurs Mobile Money, encaissés PAR PawaPay), PAWAPAY (le canal Mobile Money lui-même),
#   PISPI (virement instantané bancaire : aucun accès API aujourd'hui, le paiement est DÉCLARÉ par le client puis CONFIRMÉ à la main).
# Règle permanente du propriétaire : PawaPay est TOUJOURS actif par défaut.
#
# Sens des cases :
#   - PAWAPAY seul coché (défaut)         → Mobile Money avec les trois opérateurs Orange, Moov, Telecel ;
#   - un ou plusieurs opérateurs cochés  → Mobile Money limité à ces opérateurs (PawaPay est le canal, implicitement actif) ;
#   - PISPI coché                         → le lien propose aussi « PI-SPI » (instructions bancaires + « J'ai payé »).
# État : champs du document `settings` « global » (aucune nouvelle collection MongoDB, le cluster est plein).
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.paiement_formulaires")

# code → libellé affiché (écran de réglage)
METHODES: Dict[str, str] = {
    "PAWAPAY": "PawaPay (Mobile Money)",
    "ORANGE": "Orange Money",
    "MOOV": "Moov Money",
    "TELECEL": "Telecel Money",
    "PISPI": "PI-SPI (virement instantané bancaire)",
}
OPERATEURS = ("ORANGE", "MOOV", "TELECEL")
DEFAUT = ["PAWAPAY"]                       # règle : PawaPay actif par défaut
TEXTE_PISPI_DEFAUT = ("Effectuez un virement instantané PI-SPI vers notre compte, en indiquant la référence ci-dessous, "
                      "puis appuyez sur « J'ai effectué le virement ». Votre formulaire est mis en ligne dès que nous "
                      "avons confirmé la réception.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def moyens_actifs(settings: Optional[Dict[str, Any]]) -> List[str]:
    """Moyens actifs (fonction pure) : codes connus uniquement, sans doublon ; vide ou absent → PawaPay."""
    brut = (settings or {}).get("paiement_formulaires_moyens")
    if not isinstance(brut, list):
        return list(DEFAUT)
    vus: List[str] = []
    for c in brut:
        code = str(c or "").strip().upper()
        if code in METHODES and code not in vus:
            vus.append(code)
    return vus or list(DEFAUT)


def operateurs_autorises(actifs: List[str], defaut: List[str]) -> List[str]:
    """Opérateurs Mobile Money offerts : ceux cochés ; aucun coché mais PawaPay actif → les opérateurs par défaut ; PI-SPI seul → aucun."""
    cochés = [o for o in OPERATEURS if o in actifs]
    if cochés:
        return cochés
    return list(defaut) if "PAWAPAY" in actifs else []


def libelle_moyens(actifs: List[str], defaut: List[str]) -> str:
    """Texte « Orange, Moov, Telecel ou PI-SPI » pour le message WhatsApp (fonction pure)."""
    noms = [METHODES[o].split(" ")[0] for o in operateurs_autorises(actifs, defaut)]
    if "PISPI" in actifs:
        noms.append("PI-SPI")
    return ", ".join(noms[:-1]) + (" ou " if len(noms) > 1 else "") + noms[-1] if noms else "PawaPay"


def methodes_du_lien(actifs: List[str], defaut: List[str]) -> List[str]:
    """Codes enregistrés sur le lien : « MOBILE » (via PawaPay) et / ou « PISPI »."""
    sortie = []
    if operateurs_autorises(actifs, defaut):
        sortie.append("MOBILE")
    if "PISPI" in actifs:
        sortie.append("PISPI")
    return sortie or ["MOBILE"]


class Reglage(BaseModel):
    moyens: List[str] = Field(default_factory=list, max_length=10)
    pispi_texte: Optional[str] = Field(default=None, max_length=1500)


class Declaration(BaseModel):
    payer_name: Optional[str] = Field(default=None, max_length=80)


def make_router(*, db, get_current_user, send_email, hooks_apres_paiement: List[Any]):
    from routes.llm_health import SUPER_ADMIN_EMAIL
    router = APIRouter(tags=["Paiement des formulaires et sondages (lot 361)"])

    def _gate(user: dict):
        if user.get("role") not in ("admin", "superviseur") and user.get("tracked_role") not in ("Administrateur", "Superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs et superviseurs")

    async def _s() -> Dict[str, Any]:
        return await db.settings.find_one({"_id": "global"}) or {}

    @router.get("/admin/paiement-formulaires")
    async def lire(user: dict = Depends(get_current_user)):
        """Réglage actuel + liste des paiements PI-SPI déclarés en attente de confirmation."""
        _gate(user)
        s = await _s()
        attente = await db.payment_links.find(
            {"pispi_declare_le": {"$ne": None}, "pispi_confirme_le": None},
            {"_id": 0, "slug": 1, "label": 1, "amount": 1, "currency": 1, "pispi_declare_le": 1, "pispi_payeur": 1,
             "prefill_phone": 1}).sort("pispi_declare_le", -1).to_list(100)
        return {"methodes": [{"code": c, "libelle": l} for c, l in METHODES.items()], "actifs": moyens_actifs(s),
                "pispi_texte": s.get("paiement_formulaires_pispi_texte") or TEXTE_PISPI_DEFAUT, "pispi_en_attente": attente}

    @router.put("/admin/paiement-formulaires")
    async def ecrire(corps: Reglage, user: dict = Depends(get_current_user)):
        """Enregistre les moyens actifs (PawaPay si rien n'est coché) et le texte PI-SPI."""
        _gate(user)
        actifs = moyens_actifs({"paiement_formulaires_moyens": corps.moyens})
        maj = {"paiement_formulaires_moyens": actifs}
        if corps.pispi_texte is not None:
            maj["paiement_formulaires_pispi_texte"] = corps.pispi_texte.strip()[:1500]
        await db.settings.update_one({"_id": "global"}, {"$set": maj}, upsert=True)
        return {"ok": True, "actifs": actifs}

    # --- Côté client (page publique /pay/<slug>) : déclaration d'un virement PI-SPI --------------------------------
    @router.post("/public/pay/{slug}/pispi")
    async def declarer(slug: str, corps: Declaration):
        """Le client indique qu'il a effectué le virement PI-SPI : l'administrateur est prévenu par e-mail et confirme à la main."""
        lien = await db.payment_links.find_one({"slug": slug}, {"_id": 0})
        if not lien:
            raise HTTPException(status_code=404, detail="Lien de paiement introuvable")
        if "PISPI" not in (lien.get("methodes") or []):
            raise HTTPException(status_code=409, detail="PI-SPI n'est pas proposé sur ce lien")
        if lien.get("disabled") or lien.get("pispi_confirme_le"):
            raise HTTPException(status_code=409, detail="Ce lien n'est plus utilisable")
        await db.payment_links.update_one({"slug": slug}, {"$set": {
            "pispi_declare_le": _now(), "pispi_payeur": (corps.payer_name or "").strip()[:80] or None, "updated_at": _now()}})
        try:
            await send_email(to_email=SUPER_ADMIN_EMAIL, subject="PI-SPI : un paiement attend votre confirmation", html_body=
                             f"<p>Un client déclare avoir payé par PI-SPI : <b>{lien.get('label') or slug}</b> "
                             f"({lien.get('amount')} {lien.get('currency') or 'XOF'}), référence <b>{slug}</b>.</p>"
                             "<p>Vérifiez la réception sur le compte bancaire, puis confirmez dans Paramètres → « Paiement des formulaires et sondages ».</p>")
        except Exception:  # noqa: BLE001 — la déclaration reste enregistrée même si l'e-mail échoue
            logger.warning("[pispi] e-mail de déclaration impossible", exc_info=True)
        return {"ok": True}

    @router.post("/admin/paiement-formulaires/pispi/{slug}/confirmer")
    async def confirmer(slug: str, user: dict = Depends(get_current_user)):
        """L'administrateur a vu l'argent arriver : le paiement est « complété » et la mise en ligne du formulaire se lance."""
        _gate(user)
        lien = await db.payment_links.find_one({"slug": slug}, {"_id": 0})
        if not lien or "PISPI" not in (lien.get("methodes") or []):
            raise HTTPException(status_code=404, detail="Paiement PI-SPI introuvable")
        if lien.get("pispi_confirme_le"):
            return {"ok": True, "deja": True}
        await db.payment_links.update_one({"slug": slug}, {"$set": {
            "pispi_confirme_le": _now(), "pispi_confirme_par": user.get("email"), "uses_count": 1, "updated_at": _now()}})
        paiement = {"deposit_id": f"pispi-{slug}", "status": "completed", "payment_link_id": lien["id"], "client_id": lien.get("client_id"),
                    "amount": lien.get("amount"), "mno": "PISPI", "created_at": _now()}
        await db.payments.update_one({"deposit_id": paiement["deposit_id"]}, {"$set": paiement}, upsert=True)
        for hook in list(hooks_apres_paiement):
            try:
                await hook(paiement)
            except Exception:  # noqa: BLE001
                logger.warning("[pispi] action après paiement en échec (%s)", slug, exc_info=True)
        return {"ok": True}

    return router
