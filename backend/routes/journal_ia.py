"""Lot 98 — Tableau de synthèse de la consommation de l'IA (requêtes à Claude et aux autres modèles).

Demande du propriétaire (10/10/2026) : « Y a-t-il un tableau de synthèse de ces requêtes à Claude ? Le projet étant
vaste avec beaucoup de paramètres, je dois souvent poser des questions pour m'en rappeler… »

Pour un développeur WinDev :
  - chaque appel à l'IA (ia_client.LlmChat, ou appel direct qui appelle ia_client.noter_usage) écrit une ligne dans
    la collection « journal_ia » : date, fonction, fournisseur, modèle, jetons d'entrée et de sortie ;
  - CATALOGUE ci-dessous = aide-mémoire : pour chaque fonction de SAWALI qui utilise l'IA, son nom en clair, ce
    qu'elle fait et où elle se règle (rubrique des Paramètres) ;
  - GET /api/admin/ia/consommation?jours=30 regroupe le journal par fonction et par modèle, avec un COÛT ESTIMÉ en
    dollars (tarifs publics au million de jetons, TARIFS) — la facture réelle reste celle de console.anthropic.com ;
  - le journal se vide tout seul après 400 jours (index TTL sur le_dt).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Depends

import ia_client

logger = logging.getLogger("sawali.journal_ia")

# ---------------------------------------------------------------------------
# Catalogue : préfixe du session_id → (nom en clair, à quoi ça sert, où ça se règle)
# Le plus long préfixe qui correspond gagne (ex. « avis-claude-analyse » avant « avis-claude »).
# ---------------------------------------------------------------------------
CATALOGUE: Dict[str, Tuple[str, str, str]] = {
    "support-loois": ("Liluvine — Support Loois", "Réponses de Liluvine aux postes Loois en attente, suggestions pour "
                      "l'agent et résumé « Détails du Support ».", "Support Loois"),
    "assistance-claude": ("Claude — assistance de Liluvine", "Quand Liluvine ne sait pas répondre au support, Claude "
                          "répond à sa place (sans lire le code).", "🧠 Avis Claude sur les demandes"),
    "avis-claude-analyse": ("Claude — analyse des demandes (code)", "Analyse de faisabilité d'une demande d'ajout ou "
                            "de correction, avec lecture du dépôt GitHub (modèle le plus coûteux).",
                            "🧠 Avis Claude sur les demandes"),
    "avis-claude": ("Claude — tri des demandes", "Petit modèle qui décide si un message du support est une demande de "
                    "fonctionnalité.", "🧠 Avis Claude sur les demandes"),
    "wa": ("Liluvine — WhatsApp automatique", "Réponses automatiques de Liluvine aux messages WhatsApp.",
           "Liluvine — réponses automatiques WhatsApp"),
    "sms": ("Liluvine — SMS automatique", "Réponses automatiques de Liluvine aux SMS (Bird).", "SMS"),
    "liluvine-pro": ("Liluvine PRO — chat du portail", "Conversations des clients avec Liluvine PRO dans leur portail.",
                     "Liluvine PRO"),
    "appel": ("Liluvine — appels WhatsApp", "Liluvine décroche et converse pendant les appels WhatsApp.",
              "📞 Liluvine décroche les appels"),
    "agenda": ("Liluvine — agenda d'appels", "Appels programmés (anniversaires, formulaires) et leur personnalisation.",
               "📅 Agenda d'appels de Liluvine et anniversaires"),
    "fb-moderation": ("Page Facebook — relecture des bios", "Relecture par l'IA des bios des membres avant publication.",
                      "📣 Page Facebook animée par Liluvine"),
    "synthese-cron": ("Synthèse quotidienne", "Rapport quotidien rédigé par Liluvine.", "Synthèse quotidienne"),
    "linkedin-autopost": ("Post LinkedIn", "Brouillon du post LinkedIn hebdomadaire.", "LinkedIn"),
    "gestion-stocks": ("Analyse des stocks", "Analyse de la gestion des stocks d'une pharmacie.", "Gestion des stocks"),
    "bilan": ("Bilan du portefeuille", "Bilan de facturation rédigé par l'IA.", "Facturation"),
    "classement": ("Formulaires — classement", "Classement des réponses aux formulaires de Liluvine.", "Formulaires"),
    "handler-gen": ("Commandes « ! »", "Génération du traitement d'une commande « ! » WhatsApp.", "Commandes WhatsApp"),
    "liluvine-kb-ocr": ("Base de connaissances — lecture", "Lecture des documents ajoutés à la base de connaissances.",
                        "Base de connaissances de Liluvine"),
    "ocr-core": ("OCR des pièces", "Lecture des pièces scannées (listes de pointage…).", "OCR"),
    "import-formulaire": ("Import de formulaires", "Lecture d'un formulaire importé.", "Formulaires"),
    "qdrant-img": ("Mémoire — images", "Description d'images pour la mémoire Qdrant.", "Mémoire Qdrant"),
    "i18n": ("Traductions", "Traduction des textes du site.", "Langues"),
    "content-translate": ("Traductions — contenu", "Traduction des pages de contenu.", "Langues"),
    "ad-plan": ("Bandeaux publicitaires", "Plan de diffusion des bandeaux.", "Bandeaux publicitaires"),
    "ai-media": ("Médias IA", "Génération d'images et de médias.", "Médias IA"),
    "health-probe": ("Contrôle de l'IA", "Vérification que la clé IA fonctionne.", "Santé applicative"),
}
# Préfixes connus transmis à ia_client (le plus long d'abord) pour nommer chaque appel
ia_client.PREFIXES_CONNUS = sorted(CATALOGUE, key=len, reverse=True)

# Tarifs publics estimés en dollars par MILLION de jetons (entrée, sortie) — le premier motif trouvé dans le nom du
# modèle gagne. À ajuster si les tarifs changent ; la facture réelle est sur console.anthropic.com.
TARIFS: List[Tuple[str, float, float]] = [
    ("claude-haiku-4", 1.0, 5.0),
    ("claude-3-5-haiku", 0.8, 4.0),
    ("claude-sonnet", 3.0, 15.0),
    ("claude-3-7-sonnet", 3.0, 15.0),
    ("claude-opus-4-5", 5.0, 25.0),
    ("claude-opus", 15.0, 75.0),
    ("gpt-4o-mini", 0.15, 0.6),
    ("gpt-4o", 2.5, 10.0),
]


def tarif(modele: str) -> Optional[Tuple[float, float]]:
    """Tarif (entrée, sortie) au million de jetons, ou None si le modèle n'est pas connu."""
    m = (modele or "").lower()
    for motif, entree, sortie in TARIFS:
        if motif in m:
            return entree, sortie
    return None


def cout_estime(modele: str, entree: int, sortie: int) -> Optional[float]:
    """Coût estimé en dollars (None si tarif inconnu)."""
    t = tarif(modele)
    if not t:
        return None
    return round((entree * t[0] + sortie * t[1]) / 1_000_000, 4)


async def synthese(db, jours: int = 30) -> Dict[str, Any]:
    """Regroupement du journal par fonction et modèle sur les N derniers jours + totaux + catalogue."""
    jours = max(1, min(int(jours or 30), 400))
    depuis = (datetime.now(timezone.utc) - timedelta(days=jours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    pipeline = [
        {"$match": {"le": {"$gte": depuis}}},
        {"$group": {"_id": {"fonction": "$fonction", "modele": "$modele"}, "appels": {"$sum": 1},
                    "entree": {"$sum": "$entree"}, "sortie": {"$sum": "$sortie"}, "dernier": {"$max": "$le"}}},
    ]
    lignes: Dict[str, Dict[str, Any]] = {}
    async for g in db.journal_ia.aggregate(pipeline):
        f = g["_id"]["fonction"] or "autre"
        nom, desc, ou = CATALOGUE.get(f, (f, "Fonction non répertoriée.", ""))
        l = lignes.setdefault(f, {"fonction": f, "nom": nom, "description": desc, "ou": ou, "appels": 0,
                                  "entree": 0, "sortie": 0, "cout": 0.0, "cout_partiel": False, "modeles": [],
                                  "dernier": ""})
        cout = cout_estime(g["_id"]["modele"], g["entree"], g["sortie"])
        l["appels"] += g["appels"]
        l["entree"] += g["entree"]
        l["sortie"] += g["sortie"]
        l["cout"] = round(l["cout"] + (cout or 0), 4)
        l["cout_partiel"] = l["cout_partiel"] or cout is None
        l["modeles"].append(g["_id"]["modele"])
        l["dernier"] = max(l["dernier"], g["dernier"] or "")
    tableau = sorted(lignes.values(), key=lambda x: (-x["cout"], -x["appels"]))
    # Fonctions du catalogue sans appel sur la période : listées aussi (aide-mémoire complet)
    inutilisees = [{"fonction": k, "nom": v[0], "description": v[1], "ou": v[2]} for k, v in CATALOGUE.items()
                   if k not in lignes]
    return {"jours": jours, "lignes": tableau, "inutilisees": inutilisees,
            "total": {"appels": sum(l["appels"] for l in tableau), "entree": sum(l["entree"] for l in tableau),
                      "sortie": sum(l["sortie"] for l in tableau), "cout": round(sum(l["cout"] for l in tableau), 2)}}


def installer(*, api, db, get_current_admin) -> None:
    """Branche l'enregistreur du journal sur ia_client et monte la route de la synthèse."""

    async def enregistrer(doc: Dict[str, Any]) -> None:
        try:
            await db.journal_ia.insert_one({**doc, "le_dt": datetime.now(timezone.utc)})
        except Exception:  # noqa: BLE001 — le journal ne fait jamais échouer un appel à l'IA
            logger.debug("[journal_ia] écriture impossible", exc_info=True)

    ia_client.ENREGISTREUR_USAGE = enregistrer

    @api.get("/admin/ia/consommation", tags=["Admin — IA"])
    async def consommation(jours: int = 30, _: dict = Depends(get_current_admin)):
        return await synthese(db, jours)


async def creer_index(db) -> None:
    """Index de lecture par date et nettoyage automatique après 400 jours."""
    try:
        await db.journal_ia.create_index("le")
        await db.journal_ia.create_index("le_dt", expireAfterSeconds=400 * 24 * 3600)
    except Exception:  # noqa: BLE001
        logger.debug("[journal_ia] index non créés", exc_info=True)
