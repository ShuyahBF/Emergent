# liste_noire_wa.py — LISTE NOIRE WhatsApp (lot 453), toutes lignes confondues.
#
# Un contact inscrit ici ne reçoit PLUS AUCUN message WhatsApp de SAWALI, par aucune ligne :
#   - aucun message sortant (texte, modèle, média, boutons, accord d'appel, réponses de Liluvine, tickets, automatisations, transmission universelle) :
#     rien ne part vers Meta, donc aucun accusé « distribué » ni « lu » ;
#   - les messages qu'il écrit sont enregistrés (traçabilité) mais RETENUS : pas de non-lu, pas de notification, AUCUNE réponse d'agent IA ;
#   - les statuts « distribué / lu » de messages envoyés avant le blocage ne sont plus relayés aux plateformes.
# Gestion : on BLOQUE depuis le Centre de Messagerie (administrateur) ; la liste n'est VISIBLE et modifiable que dans Paramètres → « ⛔ Liste noire WhatsApp ».
# Stockage : UNE seule fiche de `settings` (`_id = "wa_liste_noire"`, champ `entrees`) — aucune nouvelle collection (règle du cluster MongoDB plein).
# Un numéro est reconnu par ses 8 derniers chiffres (« +226 70 12 34 56 » = « 70123456 »).
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

ID_FICHE = "wa_liste_noire"
MAX_ENTREES = 2000
DUREE_CACHE_S = 10.0                      # la liste est relue au plus toutes les 10 s par processus (chaque envoi la consulte)
_cache: Dict[str, Any] = {"jusqua": 0.0, "cles": frozenset()}


def chiffres(valeur: Any) -> str:
    """Garde uniquement les chiffres d'un numéro."""
    return re.sub(r"\D", "", str(valeur or ""))


def cle_numero(valeur: Any) -> str:
    """Clé de comparaison : 8 derniers chiffres ; vide si le numéro est trop court pour être fiable."""
    c = chiffres(valeur)
    return c[-8:] if len(c) >= 8 else ""


def vider_cache() -> None:
    _cache["jusqua"] = 0.0
    _cache["cles"] = frozenset()


async def _charger(db) -> List[Dict[str, Any]]:
    fiche = await db.settings.find_one({"_id": ID_FICHE}) or {}
    return [e for e in (fiche.get("entrees") or []) if isinstance(e, dict) and e.get("cle")]


async def cles_bloquees(db) -> frozenset:
    """Ensemble des clés bloquées (mis en cache 10 s)."""
    if time.monotonic() < _cache["jusqua"]:
        return _cache["cles"]
    cles = frozenset(e["cle"] for e in await _charger(db))
    _cache["cles"], _cache["jusqua"] = cles, time.monotonic() + DUREE_CACHE_S
    return cles


async def est_bloque(db, numero: Any) -> bool:
    """Vrai si ce numéro est en liste noire. Ne lève jamais d'exception : une base indisponible ne bloque pas l'envoi des autres."""
    cle = cle_numero(numero)
    if not cle:
        return False
    try:
        return cle in await cles_bloquees(db)
    except Exception:  # noqa: BLE001
        return False


async def sans_bloques(db, contacts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Retire d'une liste de contacts (fiches du Centre de Messagerie) ceux dont le numéro WhatsApp ou téléphone est en liste noire :
    un contact bloqué disparaît de la liste des conversations jusqu'à son déblocage. Ne lève jamais d'exception (liste intacte si la lecture échoue)."""
    try:
        cles = await cles_bloquees(db)
    except Exception:  # noqa: BLE001
        return contacts
    if not cles:
        return contacts
    return [c for c in contacts if not ({cle_numero(c.get("whatsapp")), cle_numero(c.get("phone"))} & cles)]


async def lister(db) -> List[Dict[str, Any]]:
    return sorted(await _charger(db), key=lambda e: e.get("bloque_le") or "", reverse=True)


async def bloquer(db, numero: str, *, nom: str = "", contact_id: Optional[str] = None, motif: str = "", par: str = "") -> Dict[str, Any]:
    """Inscrit un numéro (idempotent : déjà présent = fiche mise à jour). Lève ValueError si le numéro est trop court ou la liste pleine."""
    cle = cle_numero(numero)
    if not cle:
        raise ValueError("Numéro invalide : au moins 8 chiffres sont nécessaires.")
    entrees = await _charger(db)
    if len(entrees) >= MAX_ENTREES and not any(e["cle"] == cle for e in entrees):
        raise ValueError(f"La liste noire est pleine ({MAX_ENTREES} numéros au plus).")
    entree = {"cle": cle, "numero": "+" + chiffres(numero), "nom": (nom or "").strip()[:120], "contact_id": contact_id or None,
              "motif": (motif or "").strip()[:300], "bloque_le": datetime.now(timezone.utc).isoformat(), "par": (par or "")[:120]}
    entrees = [e for e in entrees if e["cle"] != cle] + [entree]
    await db.settings.update_one({"_id": ID_FICHE}, {"$set": {"entrees": entrees}}, upsert=True)
    vider_cache()
    return entree


async def debloquer(db, cle: str) -> bool:
    """Retire une entrée (par sa clé de 8 chiffres). Rend vrai si elle existait."""
    entrees = await _charger(db)
    restantes = [e for e in entrees if e["cle"] != cle_numero(cle) and e["cle"] != cle]
    if len(restantes) == len(entrees):
        return False
    await db.settings.update_one({"_id": ID_FICHE}, {"$set": {"entrees": restantes}}, upsert=True)
    vider_cache()
    return True


REPONSE_BLOQUEE = {"ok": False, "status": None, "message_id": None, "raw": None, "bloque": True,
                   "error": "Contact en liste noire : aucun message WhatsApp n'est envoyé à ce numéro."}


def reponse_bloquee() -> Dict[str, Any]:
    """Réponse type des fonctions d'envoi quand le destinataire est en liste noire (même forme qu'un échec d'envoi)."""
    return dict(REPONSE_BLOQUEE)
