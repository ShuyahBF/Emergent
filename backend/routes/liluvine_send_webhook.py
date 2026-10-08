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

Lot 57.5 (protocole v3, voir routes/liluvine_relais.py) :
  - MÉDIAS et DOCUMENTS : champ « media » {type, url | contenu_base64, nom_fichier,
    mime, legende} ; envoi direct, sinon par le modèle média, sinon lien de
    téléchargement temporaire (7 jours) dans le message ;
  - DÉSINSCRIPTION : un numéro qui a répondu STOP n'est plus joignable par cette
    plateforme (409) ;
  - INCIDENTS (signature refusée, envoi en échec) notés -> alerte e-mail.

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

from routes.liluvine_relais import (est_desinscrit, lien_fichier, noter_incident, recuperer_media,
                                    stocker_fichier)

logger = logging.getLogger("sawali.liluvine_send_webhook")

QUOTA_JOUR_DEFAUT = 500          # envois par jour et par émetteur (modifiable par émetteur)
QUOTA_HEURE_DESTINATAIRE = 20    # envois par heure vers un même numéro (anti-boucle / anti-spam)
LONGUEUR_MAX_TEXTE = 4096        # message texte libre
LONGUEUR_MAX_MODELE = 900        # message passé en variable du modèle (limite Meta ~1 024 avec le gabarit)



def _aide_reponse(source: str, transmises: bool = True) -> str:
    """Lot 83 : rappel ajouté sous les messages des plateformes — seule une réponse faite avec
    « Répondre » sur CE message est transmise à la plateforme (les autres messages restent à SAWALI).
    Lot 84 : plateforme réglée sur « réponses non transmises » → message automatique, ne pas répondre."""
    if not transmises:
        return f"\n\nℹ️ Message automatique de {source} : merci de ne pas y répondre."
    return f"\n\n↩️ Pour répondre à {source}, faites « Répondre » sur ce message."

class LiluvineSendPayload(BaseModel):
    message: str
    to: Optional[str] = None       # numéro WhatsApp du destinataire (facultatif en ancien mode)
    source: Optional[str] = None   # libellé lisible de l'émetteur (facultatif)
    id: Optional[str] = None       # identifiant unique du message (idempotence)
    media: Optional[dict] = None   # média / document joint (protocole v3)


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


def attach_liluvine_send_webhook_routes(*, api, db, wa_send_text, wa_send_template=None, wa_send_media=None):

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
             "liluvine_transmission_modele": 1, "liluvine_transmission_langue": 1,
             "liluvine_transmission_modele_media": 1},
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
            if code:
                await noter_incident(db, code, "signature_refusee")
            raise HTTPException(status_code=401, detail="Signature HMAC invalide")

        nom_emetteur = (emetteur or {}).get("nom") or code or "liluvine"
        source = (payload.source or "").strip()[:60] or nom_emetteur
        transmises = (emetteur or {}).get("reponses_transmises") is not False   # lot 84 : ligne d'aide adaptée
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

        # 6 bis) Désinscription : le destinataire a répondu STOP à cette plateforme
        if code and await est_desinscrit(db, code, destinataire):
            raise HTTPException(status_code=409, detail="Destinataire désinscrit")

        # 7) Envoi WhatsApp (avec média éventuel)
        quand = date_heure_affichee(maintenant)
        media_mode = None
        result = None
        if payload.media:
            octets, mime, nom_fichier = await recuperer_media(payload.media)
            lien = await lien_fichier(db, await stocker_fichier(db, octets, mime, nom_fichier, code or "liluvine"))
            if not lien.startswith("https://"):
                raise HTTPException(status_code=503, detail="Adresse publique de SAWALI non configurée (public_base_url)")
            type_media = payload.media.get("type")
            legende = (payload.media.get("legende") or message)[:1024]
            # a) média direct (dans la fenêtre de 24 h)
            if wa_send_media:
                result = await wa_send_media(destinataire, type_media, public_url=lien,
                                             caption=f"📨 {source} — {quand}\n{legende}{_aide_reponse(source, transmises)}" if code else legende,
                                             filename=nom_fichier if type_media == "document" else None)
                if result.get("ok"):
                    media_mode = "direct"
            # b) modèle média (en-tête document/image/vidéo + 3 variables), valable hors fenêtre
            modele_media = (reglages.get("liluvine_transmission_modele_media") or "").strip()
            if media_mode is None and modele_media and wa_send_template and type_media in ("document", "image", "video"):
                objet = {"link": lien, **({"filename": nom_fichier} if type_media == "document" else {})}
                composants = [
                    {"type": "header", "parameters": [{"type": type_media, type_media: objet}]},
                    {"type": "body", "parameters": [{"type": "text", "text": quand}, {"type": "text", "text": source},
                                                    {"type": "text", "text": message[:LONGUEUR_MAX_MODELE]}]},
                ]
                result = await wa_send_template(destinataire, modele_media, langue, composants)
                if result.get("ok"):
                    media_mode = "modele"
            # c) sinon : message avec lien de téléchargement temporaire (7 jours)
            if media_mode is None:
                media_mode = "lien"
                suffixe = f"\n📎 {nom_fichier} : {lien}"
                place = (LONGUEUR_MAX_MODELE if mode == "modele" else LONGUEUR_MAX_TEXTE) - len(suffixe)
                # Le texte est raccourci si besoin pour que le lien tienne toujours en entier
                message = (message if len(message) <= place else message[:max(0, place - 1)] + "…") + suffixe
                result = None
        if result is not None and media_mode in ("direct", "modele"):
            pass  # déjà envoyé avec le média
        elif mode == "modele":
            composants = [{"type": "body", "parameters": [
                {"type": "text", "text": quand},
                {"type": "text", "text": source},
                {"type": "text", "text": message},
            ]}]
            result = await wa_send_template(destinataire, modele, langue, composants)
        else:
            result = await wa_send_text(destinataire, f"📨 {source} — {quand}\n\n{message}{_aide_reponse(source, transmises)}"
                                        if code else message)

        # 8) Journal (sans le texte du message)
        try:
            await db.liluvine_transmissions.insert_one({
                "date": maintenant.isoformat(), "emetteur": code or "liluvine", "source": source,
                "id_externe": id_externe, "to": destinataire, "mode": mode,
                "ok": bool(result.get("ok")), "message_id": result.get("message_id"),
                "erreur": None if result.get("ok") else str(result.get("error") or "inconnu")[:300],
                "longueur": len(message), "media_mode": media_mode,
            })
            if code:
                await db.liluvine_emetteurs.update_one({"code": code}, {"$set": {"dernier_envoi": maintenant.isoformat()}})
                if not result.get("ok"):
                    await noter_incident(db, code, "envoi_echoue")
        except Exception:  # noqa: BLE001 — le journal ne bloque jamais l'envoi
            logger.exception("[liluvine_send_webhook] journal indisponible")
        if not result.get("ok"):
            logger.warning("[liluvine_send_webhook] échec envoi WA (émetteur %s) vers %s: %s",
                           code or "liluvine", destinataire, result.get("error"))
            raise HTTPException(status_code=502, detail=f"Échec envoi WhatsApp : {result.get('error') or 'inconnu'}")
        return {"ok": True, "id": id_externe, "to": destinataire, "source": source, "mode": mode,
                "media_mode": media_mode, "message_id": result.get("message_id"), "doublon": False}

    logger.info("[liluvine_send_webhook] route mounted at POST /api/webhook/liluvine-send")


__all__ = ["attach_liluvine_send_webhook_routes", "LiluvineSendPayload", "normaliser_numero",
           "date_heure_affichee"]
