# wa_main_humaine.py — Lot 343 : « laisser la main aux humains » avant toute réponse automatique de l'agent IA.
#
# Règle du propriétaire (29/10/2026) : les réponses automatiques de l'agent IA (Liluvine et les autres)
#   1. ne partent qu'AU BOUT DE 15 SECONDES, et seulement si aucun humain n'a encore répondu à ce message ;
#   2. ne se mêlent pas d'une conversation EN COURS menée par un humain, sauf si plus aucun humain n'est
#      présent dans le centre de messagerie.
#
# Fonctionnement : le message est reçu et affiché tout de suite ; la réponse automatique est planifiée en
# ARRIÈRE-PLAN (règle 7 : la requête du webhook n'attend jamais). Après le délai, on contrôle :
#   - « humain a répondu »   : un message sortant envoyé par un utilisateur de SAWALI (sender_id, ni IA ni
#                              réponse automatique) existe pour ce numéro depuis la réception du message ;
#   - « conversation humaine » : le dernier message sortant d'un humain à ce numéro date de moins de N minutes ;
#   - « humain présent »     : au moins un compte de l'équipe de ce client a une session ouverte avec une
#                              interaction il y a 5 minutes au plus (pastille verte des « Utilisateurs suivis »).
# Les commandes « ! » et « / » (ex. !Garde) sont déterministes et gardent leur réponse immédiate.
#
# Réglages (Administration → Paramètres → « 🤝 Réponses automatiques : laisser la main aux humains ») :
#   wa_main_humaine_active (bool, actif par défaut), wa_main_humaine_delai_s (défaut 15, 0 = immédiat),
#   wa_main_humaine_fenetre_min (défaut 30).
# Limite connue : un redémarrage du serveur pendant les 15 s annule la réponse planifiée (le message reste
# dans la boîte pour les agents).
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger("sawali.main_humaine")

DELAI_DEFAUT_S = 15
DELAI_MAX_S = 120
FENETRE_DEFAUT_MIN = 30
ROLES_EQUIPE = ("admin", "superviseur", "moderateur")

# Références fortes sur les tâches planifiées (sinon le ramasse-miettes peut les arrêter en route)
_TACHES: set = set()


def reglages_main_humaine(s: Dict[str, Any]) -> Dict[str, Any]:
    """Réglages lus dans `settings` : actif par défaut, délai 15 s (0 à 120), fenêtre de conversation 30 min. Fonction pure."""
    def _entier(cle: str, defaut: int, mini: int, maxi: int) -> int:
        v = s.get(cle)
        if v is None or str(v).strip() == "":
            return defaut
        try:
            return max(mini, min(int(float(str(v).strip())), maxi))
        except (TypeError, ValueError):
            return defaut
    actif = s.get("wa_main_humaine_active")
    return {
        "actif": True if actif is None else bool(actif),
        "delai": _entier("wa_main_humaine_delai_s", DELAI_DEFAUT_S, 0, DELAI_MAX_S),
        "fenetre_min": _entier("wa_main_humaine_fenetre_min", FENETRE_DEFAUT_MIN, 1, 24 * 60),
    }


def est_commande(texte: str) -> bool:
    """Commande « ! » ou « / » : réponse déterministe, jamais retardée."""
    return (texte or "").strip().startswith(("!", "/"))


def decider(*, humain_a_repondu: bool, conversation_humaine: bool, humain_present: bool) -> Dict[str, Any]:
    """Décision après le délai. Fonction pure : {"ok": bool, "reason": str}."""
    if humain_a_repondu:
        return {"ok": False, "reason": "humain_a_repondu"}
    if conversation_humaine and humain_present:
        return {"ok": False, "reason": "conversation_humaine_en_cours"}
    return {"ok": True, "reason": "personne_n_a_repondu" if not conversation_humaine else "aucun_humain_present"}


def _fin(chiffres: Any) -> str:
    return re.sub(r"\D", "", str(chiffres or ""))[-8:]


def _filtre_humain(fin: str) -> Dict[str, Any]:
    """Message sortant envoyé par un utilisateur de SAWALI (même critère que la barrière anti-rafale, lot 64.2)."""
    return {
        "direction": "outbound",
        "sender_id": {"$nin": [None, ""]},
        "ai_generated": {"$ne": True},
        "auto_reply": {"$ne": True},
        "barriere_auto": {"$ne": True},
        "$or": [{"phone_digits": {"$regex": re.escape(fin) + "$"}}, {"to": {"$regex": re.escape(fin) + "$"}},
                {"to_number": {"$regex": re.escape(fin) + "$"}}],
    }


async def dernier_message_humain(db, chiffres: str) -> Optional[str]:
    """Date (ISO) du dernier message qu'un humain a envoyé à ce numéro, ou None."""
    fin = _fin(chiffres)
    if not fin:
        return None
    doc = await db.whatsapp_messages.find_one(_filtre_humain(fin), {"_id": 0, "created_at": 1}, sort=[("created_at", -1)])
    return (doc or {}).get("created_at")


async def humain_present(db, scope_uid: Optional[str]) -> bool:
    """Un humain de l'équipe est-il présent (session ouverte, interaction il y a 5 min au plus) ? Jamais d'exception : en cas
    d'erreur on répond « oui » (présent), donc l'IA reste prudente et ne parle pas par-dessus l'équipe."""
    try:
        from routes.presence_utilisateurs import presence
        critere = [{"role": {"$in": list(ROLES_EQUIPE)}}]
        if scope_uid:
            critere += [{"id": scope_uid}, {"client_id": scope_uid}, {"parent_client_id": scope_uid}]
        ids = [u["id"] async for u in db.users.find({"$or": critere}, {"_id": 0, "id": 1}) if u.get("id")]
        etats = await presence(ids)
        return any(p.get("etat") == "vert" for p in etats.values())
    except Exception:  # noqa: BLE001
        logger.warning("[main_humaine] présence illisible : l'IA reste prudente", exc_info=True)
        return True


def _iso(valeur: Any) -> Optional[datetime]:
    if isinstance(valeur, datetime):
        return valeur if valeur.tzinfo else valeur.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(valeur).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


async def controler(db, *, chiffres: str, recu_le: Any, scope_uid: Optional[str], fenetre_min: int) -> Dict[str, Any]:
    """Après le délai : l'IA a-t-elle le droit de répondre ? Retourne {"ok", "reason"}."""
    dernier = _iso(await dernier_message_humain(db, chiffres))
    recu = _iso(recu_le) or datetime.now(timezone.utc)
    a_repondu = bool(dernier and dernier >= recu - timedelta(seconds=1))
    en_cours = bool(dernier and dernier >= datetime.now(timezone.utc) - timedelta(minutes=fenetre_min))
    present = await humain_present(db, scope_uid) if (en_cours and not a_repondu) else False
    return decider(humain_a_repondu=a_repondu, conversation_humaine=en_cours, humain_present=present)


async def _apres_delai(db, *, delai: int, inbound_doc: Dict[str, Any], scope_uid: Optional[str], fenetre_min: int,
                       executer: Callable[[], Awaitable[Dict[str, Any]]]) -> None:
    """Tâche d'arrière-plan : attend, contrôle, répond ou s'abstient, puis journalise le résultat final."""
    chiffres = inbound_doc.get("phone_digits") or inbound_doc.get("from") or ""
    try:
        await asyncio.sleep(delai)
        verdict = await controler(db, chiffres=chiffres, recu_le=inbound_doc.get("created_at"), scope_uid=scope_uid, fenetre_min=fenetre_min)
        resultat = await executer() if verdict["ok"] else verdict
    except Exception as exc:  # noqa: BLE001 — jamais d'exception non rattrapée dans une tâche d'arrière-plan
        logger.warning("[main_humaine] réponse différée échouée : %s", exc, exc_info=True)
        resultat = {"ok": False, "reason": f"crash_differe: {str(exc)[:140]}"}
    try:
        await db.liluvine_wa_autoreply_log.insert_one({
            "id": uuid.uuid4().hex, "at": datetime.now(timezone.utc).isoformat(), "tenant_id": scope_uid,
            "phone_digits": re.sub(r"\D", "", str(chiffres)), "contact_id": None, "contact_name": None,
            "message_type": inbound_doc.get("message_type") or "text", "text": (inbound_doc.get("body") or "")[:160],
            "ok": bool(resultat.get("ok")), "reason": "differe_" + str(resultat.get("reason") or ("sent" if resultat.get("ok") else "unknown"))[:190],
            "command": resultat.get("command"), "differe_s": delai,
        })
    except Exception:  # noqa: BLE001
        pass


async def appliquer(db, *, inbound_doc: Dict[str, Any], settings_doc: Dict[str, Any], scope_uid: Optional[str],
                    executer: Callable[[], Awaitable[Dict[str, Any]]]) -> Dict[str, Any]:
    """Point d'entrée du webhook. Réponse immédiate pour les commandes (ou si le réglage est coupé / à 0 s) ; sinon la réponse de
    l'IA est planifiée en arrière-plan et la fonction rend tout de suite {"ok": False, "reason": "differe_15s"}."""
    r = reglages_main_humaine(settings_doc or {})
    if not r["actif"] or r["delai"] <= 0 or est_commande(inbound_doc.get("body") or ""):
        return await executer()
    tache = asyncio.create_task(_apres_delai(db, delai=r["delai"], inbound_doc=inbound_doc, scope_uid=scope_uid,
                                             fenetre_min=r["fenetre_min"], executer=executer))
    _TACHES.add(tache)
    tache.add_done_callback(_TACHES.discard)
    return {"ok": False, "reason": f"differe_{r['delai']}s"}
