# barriere_wa.py — Lot 63 : « barrière » anti-rafale sur les messages WhatsApp reçus.
#
# Principe : un correspondant qui écrit plusieurs fois SANS avoir reçu de réponse d'un
# humain de SAWALI est arrêté au bout d'un nombre de messages paramétrable (ex. 2) :
#   - message n° 1 … seuil-1 : reçus normalement ;
#   - message n° seuil      : reçu normalement, PUIS réponse automatique « barrière »
#                              (texte + image facultative, paramétrables) ;
#   - messages suivants     : RETENUS (enregistrés avec la marque barriere_retenu, sans
#                              notification, sans non-lu, sans réponse de Liluvine).
# La barrière se lève dès qu'un utilisateur de SAWALI répond à ce correspondant.
#
# Réglages (Administration → Paramètres → « 🚧 Barrière anti-rafale WhatsApp ») :
#   wa_barriere_active (bool), wa_barriere_seuil (int, défaut 2),
#   wa_barriere_message (texte), wa_barriere_image_url (image facultative),
#   wa_barriere_fenetre_heures (messages pris en compte : dernières N heures, défaut 24),
#   wa_barriere_liluvine_compte (les réponses automatiques de Liluvine lèvent aussi la barrière),
#   wa_barriere_exemptes (numéros jamais bloqués).
# Ne sont jamais concernés : les commandes « ! » / « / », les réponses à des boutons,
# formulaires ou autorisations d'appel.
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

MESSAGE_DEFAUT = ("Sans réponse de votre correspondant, tout autre message de votre part ne sera pas "
                  "transmis. Instructions de l'Administrateur. Attendez une réponse avant de poursuivre SVP.")
# Types de messages concernés (les réponses à des boutons / formulaires restent libres)
TYPES_CONCERNES = {"text", "image", "audio", "video", "document", "sticker", "location", "contacts"}


def _chiffres(valeur: Any) -> str:
    """Garde uniquement les chiffres d'un numéro."""
    return re.sub(r"\D", "", str(valeur or ""))


def reglages_barriere(s: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Réglages de la barrière (None si elle est désactivée)."""
    if not s.get("wa_barriere_active"):
        return None
    try:
        seuil = max(1, int(s.get("wa_barriere_seuil") or 2))
    except (TypeError, ValueError):
        seuil = 2
    try:
        fenetre = max(1, int(s.get("wa_barriere_fenetre_heures") or 24))
    except (TypeError, ValueError):
        fenetre = 24
    exemptes_brut = s.get("wa_barriere_exemptes") or []
    if isinstance(exemptes_brut, str):
        exemptes_brut = re.split(r"[,;\n]+", exemptes_brut)   # « +226 70 00 00 00 » garde ses espaces
    return {
        "seuil": seuil,
        "fenetre_heures": fenetre,
        "message": (s.get("wa_barriere_message") or "").strip() or MESSAGE_DEFAUT,
        "image_url": (s.get("wa_barriere_image_url") or "").strip(),
        "liluvine_compte": bool(s.get("wa_barriere_liluvine_compte")),
        "exemptes": {_chiffres(x)[-8:] for x in exemptes_brut if len(_chiffres(x)) >= 8},
    }


def est_concerne(reglages: Dict[str, Any], chiffres: str, mtype: str, texte: Optional[str]) -> bool:
    """Ce message entre-t-il dans le décompte de la barrière ?"""
    if mtype not in TYPES_CONCERNES:
        return False
    t = (texte or "").strip()
    if mtype == "text" and (t.startswith("!") or t.startswith("/")):
        return False                       # commandes Liluvine : jamais bloquées par la barrière
    return _chiffres(chiffres)[-8:] not in reglages["exemptes"]


async def messages_sans_reponse(db, chiffres: str, reglages: Dict[str, Any]) -> int:
    """Nombre de messages reçus de ce correspondant depuis la dernière réponse de SAWALI
    (dans la fenêtre de temps paramétrée), message en cours NON compris."""
    fin = re.escape(_chiffres(chiffres)[-8:])
    if not fin:
        return 0
    depuis = (datetime.now(timezone.utc) - timedelta(hours=reglages["fenetre_heures"])).isoformat()
    # Dernière réponse : message sortant d'un humain (ou de Liluvine si le réglage l'accepte),
    # sans compter les réponses automatiques de la barrière elle-même
    filtre_reponse: Dict[str, Any] = {
        "direction": "outbound",
        "barriere_auto": {"$ne": True},
        "$or": [{"phone_digits": {"$regex": fin + "$"}}, {"to": {"$regex": fin + "$"}},
                {"to_number": {"$regex": fin + "$"}}],
    }
    if not reglages["liluvine_compte"]:
        filtre_reponse["ai_generated"] = {"$ne": True}
    derniere = await db.whatsapp_messages.find_one(filtre_reponse, {"_id": 0, "created_at": 1},
                                                   sort=[("created_at", -1)])
    borne = max(depuis, (derniere or {}).get("created_at") or "")
    return await db.whatsapp_messages.count_documents({
        "direction": "inbound", "phone_digits": {"$regex": fin + "$"},
        "created_at": {"$gt": borne}, "barriere_exclu": {"$ne": True},
    })


async def decision(db, chiffres: str, mtype: str, texte: Optional[str], s: Dict[str, Any]) -> str:
    """« normal » (laisser passer), « avertir » (laisser passer + réponse barrière)
    ou « retenir » (ne pas transmettre)."""
    reglages = reglages_barriere(s)
    if not reglages or not est_concerne(reglages, chiffres, mtype, texte):
        return "normal"
    rang = await messages_sans_reponse(db, chiffres, reglages) + 1      # rang du message en cours
    if rang < reglages["seuil"]:
        return "normal"
    return "avertir" if rang == reglages["seuil"] else "retenir"
