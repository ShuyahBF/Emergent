"""Lot 316 — Liluvine et les demandes d'intervention EXPRESS (Niveaux de service, lots 314-315).

Quand un contact demande une intervention, Liluvine :
  1. pose au plus 3 questions courtes (nature du problème, urgence, poste/logiciel concerné) ;
  2. annonce le niveau du contact (contrat valide → engagement du contrat, sinon standard) avec SON délai réglé par le propriétaire ;
  3. propose l'EXPRESS si c'est urgent ou si le contact le demande, avec délai et tarif ;
  4. quand le contact ACCEPTE, prévient le propriétaire par le mécanisme existant `[ESCALATE: …]` (notification WhatsApp à l'administrateur).
Le tarif EXPRESS est le « Forfait par intervention » (flat_rate) de la fiche du client ; à 0 ou inconnu : « à préciser avant l'intervention ».
Rien n'est annoncé tant que la rubrique Paramètres → « Niveaux de service » n'est pas activée avec ses trois délais (aucun engagement par défaut).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from routes.niveaux_service import normaliser_config

logger = logging.getLogger("sawali.niveaux_service_liluvine")

A_PRECISER = "à préciser avant l'intervention"


def texte_forfait(forfait: Any) -> str:
    """« 25 000 FCFA » si le forfait du client est renseigné, sinon « à préciser avant l'intervention »."""
    try:
        n = float(forfait)
    except (TypeError, ValueError):
        return A_PRECISER
    return f"{round(n):,} FCFA".replace(",", " ") if n > 0 else A_PRECISER


def construire_bloc(config: Dict[str, Any], etat_contrat: Optional[str], forfait: Any) -> str:
    """Consignes ajoutées au prompt de Liluvine (chaîne vide si les niveaux ne sont pas configurés)."""
    if not config.get("configure"):
        return ""
    n = config["niveaux"]
    contrat_valide = etat_contrat == "valide"
    lignes = [
        "\n\n[NIVEAUX DE SERVICE — demandes d'intervention]",
        "Voici les engagements de prise en charge annoncés par le propriétaire (n'annonce RIEN d'autre) :",
        f"- {n['contrat']['libelle']} : {n['contrat']['description']} — délai : {n['contrat']['delai']} (réservé aux clients dont le contrat est valide).",
        f"- {n['standard']['libelle']} : {n['standard']['description']} — délai : {n['standard']['delai']}.",
        f"- {n['express']['libelle']} : {n['express']['description']} — délai : {n['express']['delai']} — tarif : {texte_forfait(forfait)}.",
        "Situation de CE contact : " + ("son contrat est valide, le niveau « contrat » lui est applicable."
                                        if contrat_valide else "pas de contrat valide : seul le niveau « standard » s'applique, plus l'EXPRESS s'il le souhaite."),
        "Si le contact demande une intervention, une assistance, ou signale une urgence :",
        "1) pose AU PLUS 3 questions courtes, une à la fois si possible : la nature du problème, son urgence (bloquant ou non), le poste ou le logiciel concerné ;",
        "2) puis termine ta réponse par le marqueur [NIVEAUX] : trois boutons « Avec contrat », « Sans contrat » et « En express » seront affichés "
        "au contact, et SA RÉPONSE aux boutons (niveau, délai, vérification du contrat, tarif) est donnée automatiquement : ne décris donc pas "
        "les niveaux toi-même, invite simplement à choisir un service ;",
        "3) si le contact écrit lui-même « avec contrat », « sans contrat » ou « express » au lieu de toucher un bouton, réponds avec les engagements ci-dessus" + (
            " (tarif EXPRESS « à préciser » : dis-le tel quel, il sera précisé avant l'intervention) ;" if texte_forfait(forfait) == A_PRECISER else " ;"),
        "4) quand le contact ACCEPTE l'EXPRESS, remercie-le, confirme que le propriétaire est prévenu, et termine ta réponse par le marqueur "
        "[ESCALATE: EXPRESS accepté — <résumé de la demande en une phrase>].",
        "N'invente jamais de délai, de tarif ni d'heure de passage. Si le contact ne demande aucune intervention, ne parle pas des niveaux de service.",
    ]
    return "\n".join(lignes)


async def forfait_du_client(db, client: Optional[Dict[str, Any]]) -> Optional[float]:
    """« Forfait par intervention » du client relié au contact (celui du compte, sinon celui du compte principal) ; None si inconnu."""
    if not client or not client.get("id"):
        return None
    fiche = await db.users.find_one({"id": client["id"]}, {"_id": 0, "flat_rate": 1, "parent_client_id": 1}) or {}
    forfait = fiche.get("flat_rate")
    if not forfait and fiche.get("parent_client_id"):
        parent = await db.users.find_one({"id": fiche["parent_client_id"]}, {"_id": 0, "flat_rate": 1}) or {}
        forfait = parent.get("flat_rate")
    try:
        return float(forfait or 0)
    except (TypeError, ValueError):
        return 0.0


async def bloc_pour_prompt(db, client: Optional[Dict[str, Any]], etat_contrat: Optional[str]) -> str:
    """Bloc de prompt prêt à ajouter ; jamais d'exception (Liluvine doit toujours pouvoir répondre)."""
    try:
        s = await db.settings.find_one({"_id": "global"}, {"niveaux_service": 1}) or {}
        config = normaliser_config(s.get("niveaux_service"))
        if not config["configure"]:
            return ""
        return construire_bloc(config, etat_contrat, await forfait_du_client(db, client))
    except Exception:  # noqa: BLE001
        logger.warning("[niveaux_service_liluvine] bloc ignoré", exc_info=True)
        return ""
