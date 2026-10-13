# profils_wa.py — Lot 138 : NOM DE PROFIL WHATSAPP d'un numéro, lu par une plateforme (ZandGo…).
#
# Demande du propriétaire (13/10/2026) : le registre des inscrits de ZandGo affiche le « nom WhatsApp affiché » de chaque
# compte. SAWALI le connaît seulement pour les personnes qui ont ÉCRIT au numéro WhatsApp de SAWALI : Meta ne le donne
# que dans un message reçu (champ `from_profile_name` de db.whatsapp_messages, direction « inbound »).
#
# En résumé (pour un développeur WinDev) :
#   POST /api/webhook/plateforme-profils-wa   {"telephones": ["+22670000001", ...]}   (200 numéros au plus)
#   → {"profils": {"22670000001": {"nom": "Awa", "vu_le": "2026-10-13T…"}}}   (seuls les numéros CONNUS figurent)
# Requête signée comme la transmission universelle : X-Emetteur, X-Timestamp, X-Signature = HMAC-SHA256(clé, "<ts>.<corps>")
# avec la clé d'émetteur de la plateforme (aucune nouvelle clé). Ne renvoie que les numéros demandés, jamais de liste.
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, List

from fastapi import HTTPException, Request  # au niveau du module : l'annotation de la route doit être résolue

from routes.contrats_plateformes import signature_valide

MAX_NUMEROS = 200


def chiffres(texte) -> str:
    """« +226 70 00 00 01 » → « 22670000001 » (forme utilisée par db.whatsapp_messages.phone_digits)."""
    return "".join(c for c in str(texte or "") if c.isdigit())


def setup_profils_wa_routes(*, db, api) -> None:
    """Branche la route des profils WhatsApp sur le routeur /api."""

    @api.post("/webhook/plateforme-profils-wa", tags=["Plateformes — profils WhatsApp"])
    async def profils_wa(request: Request):
        """Nom de profil WhatsApp des numéros demandés (ceux qui ont déjà écrit à SAWALI)."""
        code = (request.headers.get("X-Emetteur") or "").strip().lower()
        emetteur = await db.liluvine_emetteurs.find_one({"code": code}, {"_id": 0}) if code else None
        if not emetteur or not emetteur.get("actif", True):
            raise HTTPException(status_code=401, detail="Émetteur inconnu ou désactivé")
        corps = await request.body()
        if not signature_valide(emetteur.get("secret") or "", request.headers.get("X-Timestamp") or "", corps,
                                request.headers.get("X-Signature") or "", datetime.now(timezone.utc)):
            raise HTTPException(status_code=401, detail="Signature refusée")
        try:
            demandes = json.loads(corps.decode("utf-8") or "{}").get("telephones") or []
            if not isinstance(demandes, list):
                raise ValueError
        except (ValueError, AttributeError):
            raise HTTPException(status_code=422, detail="corps attendu : {\"telephones\": [...]}")
        numeros: List[str] = sorted({chiffres(t) for t in demandes if chiffres(t)})[:MAX_NUMEROS]
        profils: Dict[str, Dict[str, str]] = {}
        if numeros:
            # Dernier message reçu avec un nom de profil, pour chacun des numéros demandés
            async for x in db.whatsapp_messages.find(
                    {"direction": "inbound", "phone_digits": {"$in": numeros}, "from_profile_name": {"$nin": [None, ""]}},
                    {"_id": 0, "phone_digits": 1, "from_profile_name": 1, "received_at": 1, "created_at": 1}
            ).sort("created_at", -1):
                profils.setdefault(x["phone_digits"], {"nom": str(x["from_profile_name"]).strip()[:80],
                                                       "vu_le": x.get("received_at") or x.get("created_at") or ""})
        return {"profils": profils}
