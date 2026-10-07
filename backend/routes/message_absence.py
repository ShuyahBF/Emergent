# message_absence.py — Lot 74 : message d'absence WhatsApp (répondeur à texte fixe).
#
# Quand un contact écrit en dehors des heures d'ouverture (Paramètres → « Heures ouvrables / RDV » :
# heure d'ouverture, heure de fermeture, jours ouvrés), SAWALI lui répond une seule fois par un texte
# fixe choisi par l'administrateur (ex. « Nous sommes fermés, nous vous répondons dès 8 h »).
# Le contact vient d'écrire : la fenêtre de 24 h est ouverte, un texte libre suffit (pas de modèle Meta).
#
# Réglages (settings.global), modifiables dans Paramètres → « 🌙 Message d'absence WhatsApp » :
#   wa_absence_actif         : bool, désactivé par défaut
#   wa_absence_texte         : texte envoyé (marqueurs {ouverture}, {fermeture}, {nom})
#   wa_absence_mode          : "hors_heures" (défaut) ou "toujours" (congés, fermeture exceptionnelle)
#   wa_absence_intervalle_h  : un seul message par contact pendant ce nombre d'heures (12 par défaut)
#   wa_absence_exclus        : numéros qui ne le reçoivent jamais (équipe, propriétaire), séparés par des virgules
# Heure de référence : UTC, qui est l'heure de Ouagadougou.
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("sawali.message_absence")

TEXTE_DEFAUT = ("Bonjour {nom}, merci pour votre message. Nos bureaux sont fermés pour le moment "
                "(ouverts de {ouverture} à {fermeture}). Nous vous répondrons dès la réouverture.")
JOURS_DEFAUT = [0, 1, 2, 3, 4]          # lundi à vendredi, comme le reste de SAWALI


def _minutes(hhmm: Any, defaut: str) -> int:
    """« 08:30 » -> 510 minutes depuis minuit (valeur par défaut si illisible)."""
    try:
        h, m = (str(hhmm or defaut).strip() + ":0").split(":")[:2]
        return int(h) * 60 + int(m)
    except (TypeError, ValueError):
        h, m = defaut.split(":")
        return int(h) * 60 + int(m)


def est_ouvert(reglages: Dict[str, Any], maintenant: datetime) -> bool:
    """Vrai pendant les heures d'ouverture (jour ouvré ET heure entre ouverture et fermeture).
    Une plage qui passe minuit (ex. 20:00 → 02:00) est acceptée."""
    jours = reglages.get("business_days")
    if not isinstance(jours, list) or not jours:
        jours = JOURS_DEFAUT
    if maintenant.weekday() not in jours:
        return False
    ouverture = _minutes(reglages.get("business_open_time"), "09:00")
    fermeture = _minutes(reglages.get("business_close_time"), "18:00")
    t = maintenant.hour * 60 + maintenant.minute
    if ouverture <= fermeture:
        return ouverture <= t < fermeture
    return t >= ouverture or t < fermeture


def _chiffres(texte: Any) -> str:
    return "".join(c for c in str(texte or "") if c.isdigit())


def decider(reglages: Dict[str, Any], *, numero: str, texte_recu: str, maintenant: datetime,
            dernier_envoi: Optional[str]) -> Tuple[bool, str]:
    """Faut-il envoyer le message d'absence à ce contact ? Renvoie (oui/non, raison)."""
    if not reglages.get("wa_absence_actif"):
        return False, "desactive"
    if (texte_recu or "").strip().startswith(("!", "/")):
        return False, "commande"                     # les commandes ont leur propre réponse
    exclus = {_chiffres(x) for x in str(reglages.get("wa_absence_exclus") or "").split(",") if _chiffres(x)}
    if _chiffres(numero) in exclus:
        return False, "numero_exclu"
    mode = (reglages.get("wa_absence_mode") or "hors_heures").strip()
    if mode != "toujours" and est_ouvert(reglages, maintenant):
        return False, "heures_ouvrables"
    try:
        intervalle = max(1, int(reglages.get("wa_absence_intervalle_h") or 12))
    except (TypeError, ValueError):
        intervalle = 12
    if dernier_envoi:
        try:
            precedent = datetime.fromisoformat(str(dernier_envoi))
            if precedent.tzinfo is None:
                precedent = precedent.replace(tzinfo=timezone.utc)
            if maintenant - precedent < timedelta(hours=intervalle):
                return False, "deja_envoye"
        except ValueError:
            pass
    return True, "envoye"


def composer_texte(reglages: Dict[str, Any], nom: Optional[str]) -> str:
    """Texte final : marqueurs {nom}, {ouverture}, {fermeture} remplacés (marqueur inconnu laissé tel quel)."""
    modele = (reglages.get("wa_absence_texte") or "").strip() or TEXTE_DEFAUT
    valeurs = {
        "nom": (nom or "").strip() or "cher client",
        "ouverture": str(reglages.get("business_open_time") or "09:00"),
        "fermeture": str(reglages.get("business_close_time") or "18:00"),
    }
    sortie = modele
    for cle, val in valeurs.items():
        sortie = sortie.replace("{" + cle + "}", val)
    return sortie[:4000]


async def traiter_message_entrant(db, *, reglages: Dict[str, Any], numero: str, de: str, texte_recu: str,
                                  nom: Optional[str], client_id: Optional[str], contact_id: Optional[str],
                                  send_text, maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Appelé à chaque message WhatsApp reçu. Envoie le message d'absence si les règles le demandent,
    le recopie dans le fil de la conversation et note l'heure d'envoi pour ce contact. Jamais bloquant."""
    maintenant = maintenant or datetime.now(timezone.utc)
    numero = _chiffres(numero or de)
    etat = await db.wa_absence_etat.find_one({"numero": numero}, {"_id": 0, "dernier_envoi": 1}) or {}
    ok, raison = decider(reglages, numero=numero, texte_recu=texte_recu, maintenant=maintenant,
                         dernier_envoi=etat.get("dernier_envoi"))
    if not ok:
        return {"envoye": False, "raison": raison}
    texte = composer_texte(reglages, nom)
    res = await send_text(de, texte)
    envoye = bool((res or {}).get("ok")) if isinstance(res, dict) else False
    if envoye:
        await db.wa_absence_etat.update_one({"numero": numero},
                                            {"$set": {"numero": numero, "dernier_envoi": maintenant.isoformat()}},
                                            upsert=True)
        try:
            # Copie dans le fil de discussion, comme les autres réponses automatiques
            await db.whatsapp_messages.insert_one({
                "id": uuid.uuid4().hex, "direction": "outbound", "to": de, "phone_digits": numero,
                "body": texte, "client_id": client_id, "contact_id": contact_id,
                "wa_message_id": (res or {}).get("message_id"), "auto_reply": True,
                "ai_source": "message_absence", "status": "sent", "wa_status": "sent",
                "sent_at": maintenant.isoformat(), "created_at": maintenant.isoformat(),
            })
        except Exception:  # noqa: BLE001 — le message est parti, la copie est secondaire
            logger.warning("[absence] copie dans le fil impossible", exc_info=True)
    return {"envoye": envoye, "raison": "envoye" if envoye else f"echec: {(res or {}).get('error')}"}
