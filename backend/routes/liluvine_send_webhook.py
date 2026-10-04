"""« Transmission WA Universelle Liluvine » — webhook entrant HMAC-signé qui
permet aux autres plateformes (Ster, adLyn, ALBARKA, beAuthentik…) d'envoyer un
message WhatsApp par la ligne de SAWALI / Liluvine, sans compte utilisateur.

Lot 57.3 : destinataire « to » dans le corps signé, journal des envois.
Lot 57.4 (protocole v2) :
  - une CLÉ PROPRE À CHAQUE PLATEFORME (« émetteur ») : en-tête X-Emetteur ;
    une clé volée ne compromet qu'une plateforme, qu'on peut désactiver ou
    dont on régénère la clé sans toucher aux autres ; le nom affiché au
    destinataire vient de la fiche émetteur (pas falsifiable) ;
  - IDEMPOTENCE : champ « id » du corps ; le même id renvoyé (nouvel essai
    réseau) ne repart pas une deuxième fois ;
  - QUOTAS : par émetteur et par jour, et par destinataire et par heure ;
  - MODÈLE WhatsApp à 3 variables (Date/Heure, Émetteur, Message) s'il est
    paramétré : le message arrive même hors de la fenêtre de 24 h ; sinon
    message texte libre.

Requête :
    POST /api/webhook/liluvine-send
    X-Emetteur:  code de la plateforme (ster, adlyn, albarka, beauthentik…)
                 — absent : ancien mode, clé unique des Paramètres
    X-Timestamp: secondes epoch (±5 min)
    X-Signature: hex HMAC-SHA256(clé, f"{timestamp}.{corps brut}")
    {"id": "uuid", "to": "+22670000000", "message": "texte", "source": "Ster — Cabinet X"}

Le texte des messages n'est jamais conservé : le journal
`liluvine_transmissions` ne garde que date, émetteur, destinataire, mode,
résultat et longueur.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Body, Header, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("sawali.liluvine_send_webhook")

QUOTA_JOUR_DEFAUT = 500          # envois par jour et par émetteur (modifiable par émetteur)
QUOTA_HEURE_DESTINATAIRE = 20    # envois par heure vers un même numéro (anti-boucle / anti-spam)
LONGUEUR_MAX_TEXTE = 4096        # message texte libre
LONGUEUR_MAX_MODELE = 900        # message passé en variable du modèle (limite Meta ~1 024 avec le gabarit)


class LiluvineSendPayload(BaseModel):
    message: str
    to: Optional[str] = None       # numéro WhatsApp du destinataire (facultatif en ancien mode)
    source: Optional[str] = None   # libellé lisible de l'émetteur (facultatif)
    id: Optional[str] = None       # identifiant unique du message (idempotence)


def normaliser_numero(brut: str) -> Optional[str]:
    """« +226 70 00 00 00 » -> « +22670000000 » ; None si ce n'est pas un numéro
    international plausible (8 à 15 chiffres, préfixe + ou 00 accepté)."""
    chiffres = re.sub(r"[\s.\-()]", "", brut or "")
    if chiffres.startswith("00"):
        chiffres = "+" + chiffres[2:]
    if not re.fullmatch(r"\+?\d{8,15}", chiffres):
        return None
    return chiffres if chiffres.startswith("+") else "+" + chiffres


def date_heure_affichee(maintenant: datetime) -> str:
    """Date/heure lisible pour le destinataire, heure de Ouagadougou (UTC) : « 04/10/2026 21:10 »."""
    return maintenant.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M")


def attach_liluvine_send_webhook_routes(*, api, db, wa_send_text, wa_send_template=None):

    @api.post("/webhook/liluvine-send", tags=["Liluvine — Webhook"])
    async def liluvine_send(
        request: Request,
        payload: LiluvineSendPayload = Body(...),
        x_signature: str = Header(..., alias="X-Signature"),
        x_timestamp: str = Header(..., alias="X-Timestamp"),
        x_emetteur: Optional[str] = Header(None, alias="X-Emetteur"),
    ):
        reglages = await db.settings.find_one(
            {"_id": "global"},
            {"_id": 0, "liluvine_send_webhook_hmac_secret": 1, "liluvine_send_webhook_target_number": 1,
             "liluvine_transmission_modele": 1, "liluvine_transmission_langue": 1},
        ) or {}

        # 1) Qui envoie ? Émetteur déclaré (clé propre) ou ancien mode (clé unique des Paramètres)
        code = (x_emetteur or "").strip().lower()
        emetteur = None
        if code:
            emetteur = await db.liluvine_emetteurs.find_one({"code": code}, {"_id": 0})
            if not emetteur or not emetteur.get("secret"):
                raise HTTPException(status_code=401, detail="Émetteur inconnu")
            if not emetteur.get("actif", True):
                raise HTTPException(status_code=401, detail="Émetteur désactivé")
            secret = emetteur["secret"].encode()
        else:
            secret = (reglages.get("liluvine_send_webhook_hmac_secret") or "").encode()
            if not secret:
                raise HTTPException(status_code=503, detail="Webhook Liluvine désactivé (secret HMAC non configuré).")

        # 2) Fenêtre anti-rejeu (±300 s) puis signature sur le corps brut
        try:
            ts = int(x_timestamp)
        except ValueError:
            raise HTTPException(status_code=400, detail="X-Timestamp invalide")
        maintenant = datetime.now(timezone.utc)
        if abs(int(maintenant.timestamp()) - ts) > 300:
            raise HTTPException(status_code=401, detail="Timestamp expiré (±5 min)")
        raw_body = await request.body()
        msg = f"{ts}.{raw_body.decode('utf-8', errors='replace')}".encode()
        expected = hmac.new(secret, msg, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, x_signature or ""):
            raise HTTPException(status_code=401, detail="Signature HMAC invalide")

        nom_emetteur = (emetteur or {}).get("nom") or code or "liluvine"
        source = (payload.source or "").strip()[:60] or nom_emetteur
        id_externe = (payload.id or "").strip()[:80] or None

        # 3) Idempotence : même émetteur + même id déjà envoyé avec succès -> pas de nouvel envoi
        if id_externe:
            deja = await db.liluvine_transmissions.find_one(
                {"emetteur": code or "liluvine", "id_externe": id_externe, "ok": True}, {"_id": 0})
            if deja:
                return {"ok": True, "id": id_externe, "to": deja.get("to"), "mode": deja.get("mode"),
                        "message_id": deja.get("message_id"), "doublon": True}

        # 4) Destinataire : « to » du corps signé, sinon (ancien mode) le numéro par défaut
        if payload.to:
            destinataire = normaliser_numero(payload.to)
            if not destinataire:
                raise HTTPException(status_code=422, detail="Numéro « to » invalide (format international attendu, ex. +22670000000)")
        elif not code:
            destinataire = normaliser_numero(reglages.get("liluvine_send_webhook_target_number") or "")
            if not destinataire:
                raise HTTPException(status_code=422, detail="Aucun destinataire : champ « to » absent et pas de numéro par défaut configuré.")
        else:
            raise HTTPException(status_code=422, detail="Champ « to » obligatoire")

        # 5) Message et mode d'envoi (modèle à 3 variables s'il est paramétré, sinon texte libre)
        message = (payload.message or "").strip()
        if not message:
            raise HTTPException(status_code=422, detail="Message vide")
        modele = (reglages.get("liluvine_transmission_modele") or "").strip()
        langue = (reglages.get("liluvine_transmission_langue") or "fr").strip() or "fr"
        mode = "modele" if (modele and wa_send_template) else "texte"
        limite = LONGUEUR_MAX_MODELE if mode == "modele" else LONGUEUR_MAX_TEXTE
        if len(message) > limite:
            raise HTTPException(status_code=422, detail=f"Message trop long ({limite} caractères au plus)")

        # 6) Quotas : par émetteur et par jour, par destinataire et par heure
        debut_jour = maintenant.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        quota_jour = int((emetteur or {}).get("quota_jour") or QUOTA_JOUR_DEFAUT)
        if await db.liluvine_transmissions.count_documents(
                {"emetteur": code or "liluvine", "ok": True, "date": {"$gte": debut_jour}}) >= quota_jour:
            raise HTTPException(status_code=429, detail=f"Quota du jour atteint ({quota_jour} envois)")
        il_y_a_une_heure = (maintenant - timedelta(hours=1)).isoformat()
        if await db.liluvine_transmissions.count_documents(
                {"to": destinataire, "ok": True, "date": {"$gte": il_y_a_une_heure}}) >= QUOTA_HEURE_DESTINATAIRE:
            raise HTTPException(status_code=429, detail="Trop d'envois vers ce numéro dans l'heure")

        # 7) Envoi WhatsApp
        quand = date_heure_affichee(maintenant)
        if mode == "modele":
            composants = [{"type": "body", "parameters": [
                {"type": "text", "text": quand},
                {"type": "text", "text": source},
                {"type": "text", "text": message},
            ]}]
            result = await wa_send_template(destinataire, modele, langue, composants)
        else:
            result = await wa_send_text(destinataire, f"📨 {source} — {quand}\n\n{message}" if code else message)

        # 8) Journal (sans le texte du message)
        try:
            await db.liluvine_transmissions.insert_one({
                "date": maintenant.isoformat(), "emetteur": code or "liluvine", "source": source,
                "id_externe": id_externe, "to": destinataire, "mode": mode,
                "ok": bool(result.get("ok")), "message_id": result.get("message_id"),
                "erreur": None if result.get("ok") else str(result.get("error") or "inconnu")[:300],
                "longueur": len(message),
            })
            if code:
                await db.liluvine_emetteurs.update_one({"code": code}, {"$set": {"dernier_envoi": maintenant.isoformat()}})
        except Exception:  # noqa: BLE001 — le journal ne bloque jamais l'envoi
            logger.exception("[liluvine_send_webhook] journal indisponible")
        if not result.get("ok"):
            logger.warning("[liluvine_send_webhook] échec envoi WA (émetteur %s) vers %s: %s",
                           code or "liluvine", destinataire, result.get("error"))
            raise HTTPException(status_code=502, detail=f"Échec envoi WhatsApp : {result.get('error') or 'inconnu'}")
        return {"ok": True, "id": id_externe, "to": destinataire, "source": source, "mode": mode,
                "message_id": result.get("message_id"), "doublon": False}

    logger.info("[liluvine_send_webhook] route mounted at POST /api/webhook/liluvine-send")


__all__ = ["attach_liluvine_send_webhook_routes", "LiluvineSendPayload", "normaliser_numero",
           "date_heure_affichee"]
