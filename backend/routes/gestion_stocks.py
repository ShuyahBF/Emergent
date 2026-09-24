"""Lot "Gestion Stocks" (2026-09) — espace documentaire des Pharmaciens
suivis (tracked_role == "Pharmacien"), nouveau lien de sidebar.

Deux blocs prévus au schéma fourni par l'utilisateur :
  1. "Explorateur BD MongoDB Atlas" — Analyseur Inventaires/Stocks/Ruptures
     + zone de prompt libre (IA conversationnelle), sur le vrai schéma
     HFSQL synchronisé par un outil externe (Produit, AAcheté, ...) — voir
     le commentaire détaillé juste avant les fonctions d'agrégation plus
     bas. Ce module ne fait QUE lire ces collections, jamais les écrire.
  2. "Explorateur Stockage R2" (PDFs, Excel, Word, Images — inventaires,
     contrôle d'analyse qualité, etc).

Organisation des documents dans R2 (voir r2_stocks_client.py) et des
documents Mongo : même préfixe/champ `client_code` (ex "PMT") pour
cloisonner par tenant partout dans ce module. Un pharmacien suivi ne voit
jamais que son propre `client_code` (résolu côté serveur depuis sa
session, jamais depuis un paramètre client) ; l'admin peut choisir
n'importe quel client_code.

Sécurité IA : le LLM ne reçoit QUE des agrégats déjà calculés côté serveur
par des pipelines Mongo scopés au `client_code` résolu — il ne génère
jamais de requête Mongo lui-même et n'a aucun accès direct à la base
(décision explicite de l'utilisateur, plus sûr qu'un LLM texte-vers-requête).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, File, Form, HTTPException, Query, UploadFile

logger = logging.getLogger("sawali.gestion_stocks")

# Sous-dossiers fixes, identiques pour chaque client — correspond aux 6
# dossiers du schéma fourni par l'utilisateur.
DEFAULT_FOLDERS: List[str] = [
    "Inventaires",
    "Rapports",
    "Analyses",
    "Controle qualite",
    "Factures",
    "Autres",
]

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 Mo par fichier

# Lot 20 — pseudo-dossier désignant la racine du code client (fichiers posés
# directement sous `<client_code>/`, hors de tout sous-dossier, par exemple
# via le tableau de bord Cloudflare). Lecture seule : on n'y dépose pas.
ROOT_FOLDER = "_racine"

# Lot 20 — dépôts par les utilisateurs suivis et espace alloué par tenant.
# Taille max d'un fichier déposé par un utilisateur suivi autorisé (réglable
# par utilisateur suivi dans Admin → Utilisateurs suivis → « Dépôt R2 »).
DEFAULT_TRACKED_UPLOAD_MAX_MB = 1.5
# Espace R2 alloué à un client/tenant (tous ses dossiers), réglable dans
# Admin → Clients → SMART Communications → « Espace de stockage R2 ».
DEFAULT_TENANT_QUOTA_GB = 2.0
_MB = 1024 * 1024
_GB = 1024 * 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _can_access_own_stocks(user: dict) -> bool:
    """Un pharmacien suivi voit son propre espace. Admin/superviseur voient
    tout (utile pour vérifier/dépanner un client)."""
    if (user.get("role") or "") in ("admin", "superviseur"):
        return True
    return (user.get("tracked_role") or "") == "Pharmacien"


async def _resolve_own_client_code(db, user: dict) -> Optional[str]:
    """Résout le `client_code` du tenant du pharmacien suivi courant.

    Même ordre de résolution que `_resolve_client_lie` (routes/cashier.py) :
    parent_client_id puis client_id pointent vers le tenant canonique
    (db.users). On ne retombe jamais sur `user` lui-même comme tenant ici —
    un compte suivi n'a pas vocation à porter son propre client_code.
    """
    for key in ("parent_client_id", "client_id"):
        ref_id = user.get(key)
        if ref_id and ref_id != user.get("id"):
            doc = await db.users.find_one({"id": ref_id}, {"_id": 0, "client_code": 1})
            if doc:
                code = (doc.get("client_code") or "").strip().upper()
                return code or None
    return None


def _safe_filename(name: str) -> str:
    base = os.path.basename((name or "").strip()) or "fichier"
    return "".join(c for c in base if c.isalnum() or c in (" ", ".", "-", "_")).strip() or "fichier"


# ----------------------------------------------------------------------
# Lot 20 — droits de dépôt des utilisateurs suivis et quota par tenant
# ----------------------------------------------------------------------
def _check_folder(folder: str, *, allow_root: bool) -> None:
    """Nom de dossier accepté : un des 6 dossiers standard, un sous-dossier
    existant (nom simple, sans « / » ni « .. »), ou la racine si autorisée.
    Le préfixe `<client_code>/` est toujours ajouté par le serveur : un nom de
    dossier ne peut jamais sortir de l'espace du tenant."""
    if folder == ROOT_FOLDER:
        if allow_root:
            return
        raise HTTPException(status_code=400, detail="Déposez vos fichiers dans un dossier, pas à la racine.")
    if folder in DEFAULT_FOLDERS:
        return
    if not folder or len(folder) > 100 or "/" in folder or "\\" in folder or folder in (".", "..") or folder.startswith("."):
        raise HTTPException(status_code=404, detail="Dossier inconnu.")


def _discover_folders(objects: List[dict], code: str) -> Dict[str, Any]:
    """Dossiers réellement présents sous `<code>/` (1er niveau) et nombre de
    fichiers posés directement à la racine."""
    prefix = f"{code}/"
    extra, root_files = set(), 0
    for o in objects:
        rest = o["key"][len(prefix):]
        if "/" in rest:
            extra.add(rest.split("/", 1)[0])
        elif rest:
            root_files += 1
    others = sorted(f for f in extra if f and f not in DEFAULT_FOLDERS)
    return {"folders": DEFAULT_FOLDERS + others, "extra_folders": others, "root_files": root_files,
            "present": sorted(f for f in extra if f)}


def _is_staff(user: dict) -> bool:
    """Administrateur ou superviseur SAWALI : accès complet au module."""
    return (user.get("role") or "") in ("admin", "superviseur")


def _fmt_mb(n_bytes: float) -> str:
    """Taille lisible en Mo, virgule décimale française (« 1,5 Mo »)."""
    return f"{n_bytes / _MB:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " Mo"


def _fmt_gb(n_bytes: float) -> str:
    return f"{n_bytes / _GB:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " Go"


def _clean_max_mb(value) -> float:
    """Taille max par fichier d'un utilisateur suivi : nombre > 0, sinon défaut."""
    try:
        v = float(value)
        return v if v > 0 else DEFAULT_TRACKED_UPLOAD_MAX_MB
    except (TypeError, ValueError):
        return DEFAULT_TRACKED_UPLOAD_MAX_MB


def _clean_quota_gb(value) -> float:
    """Espace alloué au tenant : nombre > 0, sinon défaut (2 Go)."""
    try:
        v = float(value)
        return v if v > 0 else DEFAULT_TENANT_QUOTA_GB
    except (TypeError, ValueError):
        return DEFAULT_TENANT_QUOTA_GB


async def _tracked_upload_rights(db, user: dict) -> Dict[str, Any]:
    """Droit de dépôt d'un utilisateur suivi, lu sur sa fiche `tracked_users`
    (liée au compte de connexion par `tracked_user_id`) — jamais depuis la requête."""
    tu_id = user.get("tracked_user_id")
    tu = await db.tracked_users.find_one(
        {"id": tu_id}, {"_id": 0, "r2_upload_allowed": 1, "r2_upload_max_mb": 1},
    ) if tu_id else None
    tu = tu or {}
    return {
        "allowed": bool(tu.get("r2_upload_allowed")),
        "max_mb": _clean_max_mb(tu.get("r2_upload_max_mb", DEFAULT_TRACKED_UPLOAD_MAX_MB)),
    }


async def _tenant_by_code(db, code: str) -> Optional[dict]:
    """Fiche du client/tenant (compte principal, pas un utilisateur suivi) qui porte ce client_code."""
    return await db.users.find_one(
        {"client_code": {"$in": [code, code.lower()]}, "tracked_user_id": {"$in": [None, ""]},
         "tracked_role": {"$in": [None, ""]}},
        {"_id": 0, "id": 1, "client_code": 1, "company": 1, "full_name": 1, "gestion_stocks_quota_gb": 1},
    )


async def _storage_usage(db, code: str) -> Dict[str, Any]:
    """Espace occupé par tous les fichiers du tenant (préfixe `<client_code>/`) et espace alloué."""
    from r2_stocks_client import list_objects
    import asyncio
    objects = await asyncio.to_thread(list_objects, f"{code}/")
    used = sum(int(o.get("size") or 0) for o in objects)
    tenant = await _tenant_by_code(db, code) or {}
    quota_gb = _clean_quota_gb(tenant.get("gestion_stocks_quota_gb", DEFAULT_TENANT_QUOTA_GB))
    return {
        "client_code": code,
        "files": len(objects),
        "used_bytes": used,
        "quota_gb": quota_gb,
        "quota_bytes": int(quota_gb * _GB),
    }


def _quota_refusal(usage: Dict[str, Any], size: int) -> Optional[str]:
    """Motif de refus si le fichier ferait dépasser l'espace alloué au tenant, sinon None."""
    if usage["used_bytes"] + size <= usage["quota_bytes"]:
        return None
    return (
        f"Fichier refusé : espace de stockage insuffisant. {_fmt_gb(usage['used_bytes'])} "
        f"déjà utilisés sur {_fmt_gb(usage['quota_bytes'])} alloués ; ce fichier fait {_fmt_mb(size)}. "
        "Libérez de l'espace ou demandez à votre administrateur SAWALI d'augmenter l'espace alloué."
    )


# ======================================================================
# Explorateur BD MongoDB Atlas — agrégations sur le VRAI schéma HFSQL
# (fourni par l'utilisateur le 2026-09, "Structure_des_fichiers_HFSQL.zip"),
# synchronisé vers MongoDB par l'outil externe (partie technique de la
# synchro discutée séparément). 5 entités métier / 6 collections
# (Inventory + DInventaire = en-tête + détail d'un même inventaire) :
#
#   - Produit      : base produits — porte le stock EN DIRECT (voir plus
#                    bas), pas besoin d'une collection "snapshot" séparée.
#   - AAcheté      : DÉTAIL DES VENTES (une ligne par produit vendu, malgré
#                    son nom — confirmé explicitement par l'utilisateur).
#   - Vente        : en-tête de vente (client, montant, date) — pas utilisé
#                    par les 3 analyseurs actuels.
#   - Inventory / DInventaire : en-tête + détail des inventaires physiques
#                    ponctuels (lots, péremption, écarts) — pas utilisé
#                    par les 3 analyseurs actuels ; réservé à une future
#                    évolution (écarts d'inventaire, alertes péremption).
#   - ClientPharma : clients de la pharmacie — hors périmètre (décision
#                    explicite de l'utilisateur).
#
# Stock d'un produit = Stock Ouaga (Principal) + Stock Bobo (Secondaire) +
# sUG (Unités Gratuites) — répartition confirmée par l'utilisateur, qui
# veut voir le total ET le détail des 3 composantes.
#
# RÈGLE TECHNIQUE MULTI-TENANT (à retenir pour tout futur projet de
# gestion de stocks HFSQL→MongoDB — voir aussi
# /home/user/Claude/TECHNICAL_RULES.md) : HFSQL est mono-pharmacie, donc
# aucune des tables n'a de notion de tenant. L'outil externe de synchro
# doit AJOUTER un champ d'identification du tenant sur CHAQUE document
# importé, dans CHAQUE collection, et tout affichage se filtre dessus.
# `client_code` (même valeur que AdminClients.client_code côté SAWALI) est
# le nom retenu ici — À CONFIRMER avec le développeur de l'outil externe,
# pas encore figé.
#
# Les champs HFSQL sont conservés TELS QUELS (espaces/accents compris),
# décision explicite de l'utilisateur — ne jamais les renommer en
# snake_case dans ce module.
# ======================================================================

PRODUIT_COLLECTION = "Produit"
VENTES_DETAIL_COLLECTION = "AAcheté"

# Modèle unique de LlmChat/emergentintegrations, comme LILUVINE_MODEL dans
# liluvine_pro.py — un seul endroit à changer pour un futur rollback.
GESTION_STOCKS_MODEL = "claude-sonnet-5"

GESTION_STOCKS_SYSTEM_PROMPT = (
    "Tu es l'assistant d'analyse de stocks du module \"Gestion Stocks\" d'une "
    "officine pharmaceutique sur SAWALI. Tu réponds UNIQUEMENT à partir des "
    "données agrégées fournies dans le message (format JSON) — n'invente "
    "jamais de chiffre. Si une donnée manque ou que les collections semblent "
    "vides (import pas encore fait), dis-le explicitement plutôt que de "
    "deviner. Réponds toujours en français, de façon concise et actionnable, "
    "en privilégiant les listes à puces pour les produits. Précise toujours "
    "les unités et la période concernée."
)

ANALYSE_QUESTIONS: Dict[str, str] = {
    "inventaires": (
        "Fais un état des lieux de l'inventaire actuel : niveau de stock "
        "global, produits les plus stockés, produits à stock nul."
    ),
    "stocks": (
        "Analyse les mouvements de stock/ventes sur la période récente : "
        "tendance, produits les plus vendus, évolution par rapport à la "
        "période précédente."
    ),
    "ruptures": (
        "Identifie les ruptures de stock : celles survenues récemment lors "
        "d'une vente (stock devenu nul ou négatif après la vente) et celles "
        "actuellement en cours (stock à zéro maintenant). Signale les "
        "produits qui tombent le plus souvent en rupture."
    ),
}


def _produit_stock_total(p: Dict[str, Any]) -> Dict[str, Any]:
    """Décompose + additionne les 3 composantes du stock d'un produit."""
    principal = p.get("Stock Ouaga") or 0
    secondaire = p.get("Stock Bobo") or 0
    ug = p.get("sUG") or 0
    return {
        "stock_principal_ouaga": principal,
        "stock_secondaire_bobo": secondaire,
        "stock_unites_gratuites": ug,
        "stock_total": principal + secondaire + ug,
    }


async def _aggregate_inventory_state(db, client_code: str) -> Dict[str, Any]:
    cursor = db[PRODUIT_COLLECTION].find(
        {"client_code": client_code},
        {"_id": 0, "Code Produit": 1, "Libellé": 1, "Stock Ouaga": 1, "Stock Bobo": 1, "sUG": 1},
    )
    rows = await cursor.to_list(length=10000)
    produits = [
        {
            "code_produit": r.get("Code Produit"),
            "designation": r.get("Libellé") or r.get("Code Produit"),
            **_produit_stock_total(r),
        }
        for r in rows
    ]
    top = sorted(produits, key=lambda p: p["stock_total"], reverse=True)[:10]
    zero_stock = [p for p in produits if p["stock_total"] == 0]
    return {
        "total_produits_suivis": len(produits),
        "stock_total_cumule": sum(p["stock_total"] for p in produits),
        "top_produits_par_stock": top,
        "nb_produits_stock_zero": len(zero_stock),
    }


async def _designations_by_code(db, client_code: str, codes: List[str]) -> Dict[str, str]:
    """AAcheté (détail des ventes) ne porte pas le libellé produit — on le
    récupère depuis Produit pour les codes qui nous intéressent."""
    if not codes:
        return {}
    rows = await db[PRODUIT_COLLECTION].find(
        {"client_code": client_code, "Code Produit": {"$in": codes}},
        {"_id": 0, "Code Produit": 1, "Libellé": 1},
    ).to_list(length=len(codes))
    return {r["Code Produit"]: (r.get("Libellé") or r["Code Produit"]) for r in rows}


async def _aggregate_sales_trends(db, client_code: str, days: int = 30) -> Dict[str, Any]:
    """Basé sur AAcheté (détail des ventes). `Qte Livrée` = quantité
    effectivement sortie du stock. Le montant est une ESTIMATION
    (Qte Livrée × Prix Public) faute d'un champ "montant ligne" explicite
    dans cette table — à valider une fois de vraies données disponibles
    (voir le prompt de livraison)."""
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()
    prev_since = (now - timedelta(days=2 * days)).isoformat()

    pipeline_current = [
        {"$match": {"client_code": client_code, "DateHeure_Création": {"$gte": since}}},
        {"$group": {
            "_id": "$Code Produit",
            "quantite_vendue": {"$sum": "$Qte Livrée"},
            "montant_estime": {"$sum": {"$multiply": [
                {"$ifNull": ["$Qte Livrée", 0]}, {"$ifNull": ["$Prix Public", 0]},
            ]}},
        }},
    ]
    rows = await db[VENTES_DETAIL_COLLECTION].aggregate(pipeline_current).to_list(length=10000)
    total_amount = sum(r.get("montant_estime") or 0 for r in rows)
    total_qty = sum(r.get("quantite_vendue") or 0 for r in rows)
    top_rows = sorted(rows, key=lambda r: r.get("quantite_vendue") or 0, reverse=True)[:10]
    designations = await _designations_by_code(db, client_code, [r["_id"] for r in top_rows])

    pipeline_prev = [
        {"$match": {"client_code": client_code, "DateHeure_Création": {"$gte": prev_since, "$lt": since}}},
        {"$group": {"_id": None, "montant_estime": {"$sum": {"$multiply": [
            {"$ifNull": ["$Qte Livrée", 0]}, {"$ifNull": ["$Prix Public", 0]},
        ]}}}},
    ]
    prev_rows = await db[VENTES_DETAIL_COLLECTION].aggregate(pipeline_prev).to_list(length=1)
    prev_amount = (prev_rows[0].get("montant_estime") if prev_rows else 0) or 0
    variation_pct = round(((total_amount - prev_amount) / prev_amount) * 100, 1) if prev_amount else None

    return {
        "periode_jours": days,
        "montant_total_estime": total_amount,
        "quantite_totale_vendue": total_qty,
        "top_produits_par_ventes": [
            {
                "code_produit": r["_id"],
                "designation": designations.get(r["_id"], r["_id"]),
                "quantite_vendue": r.get("quantite_vendue") or 0,
            }
            for r in top_rows
        ],
        "montant_periode_precedente_estime": prev_amount,
        "variation_pct_vs_periode_precedente": variation_pct,
    }


async def _aggregate_stockout_risks(db, client_code: str, historique_jours: int = 30) -> Dict[str, Any]:
    """Règle de détection confirmée par l'utilisateur (pas de `Seuil` — ce
    champ n'est quasiment jamais renseigné dans les données réelles) :
    pour chaque ligne de vente (`AAcheté`), `stock_apres_vente` =
    `Stock Avant` - `Qte Livrée`. <= 0 => rupture survenue à la date de
    cette vente. Exemple donné par l'utilisateur : 1 en stock, 2 servis =>
    -1, rupture. `AAcheté` et `Vente` sont liées par `Référence`, mais la
    date déjà présente sur la ligne (`DateHeure_Création`) suffit ici —
    pas besoin de joindre `Vente`.

    En complément (pas demandé mais utile et cohérent avec la même règle
    du seuil 0) : `ruptures_actuelles` = stock en direct (`Produit`,
    Ouaga+Bobo+sUG) déjà à 0 ou moins, à l'instant présent.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=historique_jours)).isoformat()
    cursor = db[VENTES_DETAIL_COLLECTION].find(
        {"client_code": client_code, "DateHeure_Création": {"$gte": since}},
        {"_id": 0, "Code Produit": 1, "Stock Avant": 1, "Qte Livrée": 1, "DateHeure_Création": 1, "Référence": 1},
    )
    lignes = await cursor.to_list(length=20000)

    evenements: List[Dict[str, Any]] = []
    for l in lignes:
        stock_avant = l.get("Stock Avant")
        qte = l.get("Qte Livrée")
        if stock_avant is None or qte is None:
            continue
        stock_apres = stock_avant - qte
        if stock_apres <= 0:
            evenements.append({
                "code_produit": l.get("Code Produit"),
                "date": l.get("DateHeure_Création"),
                "stock_avant": stock_avant,
                "quantite_vendue": qte,
                "stock_apres_vente": stock_apres,
                "reference_vente": l.get("Référence"),
            })

    codes = list({e["code_produit"] for e in evenements if e.get("code_produit")})
    designations = await _designations_by_code(db, client_code, codes)
    for e in evenements:
        e["designation"] = designations.get(e["code_produit"], e["code_produit"])
    evenements.sort(key=lambda e: e.get("date") or "", reverse=True)

    freq: Dict[str, int] = {}
    for e in evenements:
        freq[e["code_produit"]] = freq.get(e["code_produit"], 0) + 1
    produits_frequents = sorted(
        (
            {"code_produit": k, "designation": designations.get(k, k), "nb_ruptures": v}
            for k, v in freq.items()
        ),
        key=lambda r: r["nb_ruptures"], reverse=True,
    )[:10]

    produit_rows = await db[PRODUIT_COLLECTION].find(
        {"client_code": client_code},
        {"_id": 0, "Code Produit": 1, "Libellé": 1, "Stock Ouaga": 1, "Stock Bobo": 1, "sUG": 1},
    ).to_list(length=10000)
    ruptures_actuelles = [
        {
            "code_produit": p.get("Code Produit"),
            "designation": p.get("Libellé") or p.get("Code Produit"),
            "stock_total": _produit_stock_total(p)["stock_total"],
        }
        for p in produit_rows
        if _produit_stock_total(p)["stock_total"] <= 0
    ]

    return {
        "historique_jours": historique_jours,
        "nb_ruptures_survenues": len(evenements),
        "ruptures_recentes": evenements[:20],
        "produits_les_plus_souvent_en_rupture": produits_frequents,
        "ruptures_actuelles": ruptures_actuelles[:20],
    }


async def _analyse_llm_send(session_id: str, system_text: str, user_text: str) -> Dict[str, Any]:
    """Même pattern que liluvine_pro.py::_llm_send — LlmChat/emergentintegrations
    (pas le SDK Anthropic brut : cette appli appelle Claude via la clé
    universelle EMERGENT_LLM_KEY, jamais via ANTHROPIC_API_KEY)."""
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"Bibliothèque IA absente : {exc}") from exc
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="EMERGENT_LLM_KEY manquant côté serveur.")
    chat = LlmChat(
        api_key=api_key, session_id=session_id, system_message=system_text,
    ).with_model("anthropic", GESTION_STOCKS_MODEL)
    try:
        reply = await chat.send_message(UserMessage(text=user_text))
    except Exception as exc:  # noqa: BLE001
        logger.exception("[gestion_stocks] LLM call failed session=%s", session_id)
        raise HTTPException(status_code=502, detail=f"Erreur du service IA : {exc}") from exc
    tokens = max(int((len(system_text) + len(user_text) + len(reply or "")) / 4), 1)
    return {"reply": reply or "", "tokens": tokens}


def attach_gestion_stocks_routes(*, api, db, get_current_user, get_current_admin):
    # Lot 20 — les routes « admin » du module sont ouvertes au superviseur
    # (demande explicite) : admin OU superviseur, jamais un autre rôle.
    # `get_current_admin` reste accepté dans la signature (appel de server.py inchangé).
    async def staff_user(user: dict = Depends(get_current_user)) -> dict:
        if not _is_staff(user):
            raise HTTPException(status_code=403, detail="Accès réservé à l'administrateur ou au superviseur SAWALI.")
        return user


    @api.get("/gestion-stocks/context", tags=["Portail — Gestion Stocks"])
    async def gestion_stocks_context(user: dict = Depends(get_current_user)):
        """Renvoie le client_code résolu + la liste des dossiers — le
        frontend s'en sert pour savoir quoi afficher avant tout listing."""
        if not _can_access_own_stocks(user):
            raise HTTPException(status_code=403, detail="Accès réservé aux comptes Pharmacien suivis (et admin/superviseur).")
        from r2_stocks_client import _bucket, is_configured
        client_code = None
        if (user.get("role") or "") in ("admin", "superviseur"):
            client_code = None  # l'admin choisit un client_code explicitement (voir endpoints /admin/*)
        else:
            client_code = await _resolve_own_client_code(db, user)
        return {
            "client_code": client_code,
            "folders": DEFAULT_FOLDERS,
            "r2_configured": is_configured(),
            # Lot 20 — nom du compartiment R2 affiché dans le fil d'Ariane de
            # l'explorateur (information non sensible : ni clé ni compte).
            "bucket": _bucket() if is_configured() else None,
            "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
            "is_admin": (user.get("role") or "") in ("admin", "superviseur"),
            # Droit de dépôt de l'utilisateur courant : admin/superviseur
            # toujours (25 Mo) ; utilisateur suivi selon sa fiche (défaut 1,5 Mo).
            **(await _upload_rights_for(user)),
        }

    async def _upload_rights_for(user: dict) -> Dict[str, Any]:
        if _is_staff(user):
            return {"can_upload": True, "upload_max_mb": MAX_UPLOAD_BYTES // _MB}
        rights = await _tracked_upload_rights(db, user)
        return {"can_upload": rights["allowed"], "upload_max_mb": rights["max_mb"] if rights["allowed"] else None}

    async def _after_upload(*, code: str, key: str, data: bytes, content_type: Optional[str], user: dict,
                            tags: Optional[str], description: Optional[str]) -> Dict[str, Any]:
        """Lot 22 — après un dépôt réussi dans R2 : fiche Mongo `stock_files`
        (tags, description, auteur) et, si le client les a activées,
        suggestions IA de tags lancées en arrière-plan."""
        from routes import gestion_stocks_tags as gt
        doc = await gt.index_upload(db, code=code, key=key, size=len(data),
                                    content_type=content_type or "application/octet-stream",
                                    user=user, tags=tags, description=description)
        ai_started = False
        try:
            ai_started = await gt.maybe_schedule_after_upload(db, code=code, key=key, data=data,
                                                              content_type=content_type or "")
        except Exception:  # noqa: BLE001 — le dépôt est réussi quoi qu'il arrive à l'IA
            logger.exception("[gestion_stocks] lancement des suggestions IA échoué key=%s", key)
        return {"ok": True, "key": key, "size": len(data), "tags": doc.get("tags") or [],
                "description": doc.get("description") or "", "ai_tags_started": ai_started}

    @api.get("/gestion-stocks/folders", tags=["Portail — Gestion Stocks"])
    async def gestion_stocks_folders(
        client_code: Optional[str] = Query(None, description="Admin/superviseur uniquement — ignoré pour un utilisateur suivi."),
        user: dict = Depends(get_current_user),
    ):
        """Dossiers à afficher pour un tenant : les 6 dossiers standard, les
        autres sous-dossiers réellement présents dans R2, et le nombre de
        fichiers posés à la racine du code client (pseudo-dossier `_racine`).

        Les 6 dossiers standard manquants sont CRÉÉS dans R2 à la première
        ouverture (objet marqueur vide `<code>/<dossier>/`, comme le bouton
        « Ajouter un dossier » de Cloudflare), pour que la page et le tableau
        de bord Cloudflare affichent la même chose."""
        if not _can_access_own_stocks(user):
            raise HTTPException(status_code=403, detail="Accès réservé aux comptes Pharmacien suivis (et admin/superviseur).")
        code = (client_code or "").strip().upper() if _is_staff(user) else await _resolve_own_client_code(db, user)
        if not code:
            raise HTTPException(status_code=409, detail="Aucun code client (client_code) configuré pour ce tenant.")
        from r2_stocks_client import is_configured, list_folder_markers, put_bytes
        from r2_stocks_client import list_objects
        import asyncio
        if not is_configured():
            raise HTTPException(status_code=503, detail="Stockage R2 Gestion Stocks non configuré.")
        try:
            objects = await asyncio.to_thread(list_objects, f"{code}/")
            markers = await asyncio.to_thread(list_folder_markers, f"{code}/")
        except Exception:
            logger.exception("[gestion_stocks] folder discovery failed code=%s", code)
            raise HTTPException(status_code=502, detail="Erreur de lecture du stockage R2.")
        # Les marqueurs de dossier vides comptent comme dossiers existants.
        found = _discover_folders(objects + [{"key": m} for m in markers], code)
        present = set(found.pop("present"))
        # Création des dossiers standard manquants — seulement pour un vrai
        # client (un code saisi par l'administration qui ne correspond à aucun
        # client ne crée rien).
        missing = [f for f in DEFAULT_FOLDERS if f not in present]
        created: List[str] = []
        if missing and (not _is_staff(user) or await _tenant_by_code(db, code)):
            for folder in missing:
                try:
                    await asyncio.to_thread(put_bytes, f"{code}/{folder}/", b"", "application/x-directory")
                    created.append(folder)
                except Exception:  # noqa: BLE001 — l'affichage ne doit pas échouer pour autant
                    logger.exception("[gestion_stocks] folder marker creation failed %s/%s", code, folder)
        from routes.gestion_stocks_tags import tenant_ai_enabled
        # Lot 22 — l'écran affiche le bouton « Suggérer des tags (IA) » seulement si activé pour ce client.
        return {"client_code": code, "root_folder": ROOT_FOLDER, "created_folders": created,
                "ai_tags_enabled": await tenant_ai_enabled(db, code), **found}

    @api.get("/gestion-stocks/storage", tags=["Portail — Gestion Stocks"])
    async def gestion_stocks_storage(
        client_code: Optional[str] = Query(None, description="Admin/superviseur uniquement — ignoré pour un utilisateur suivi."),
        user: dict = Depends(get_current_user),
    ):
        """Espace occupé par les fichiers du tenant sur l'espace alloué (tableau
        de bord de l'utilisateur suivi, jauge de l'explorateur R2)."""
        if not _can_access_own_stocks(user):
            raise HTTPException(status_code=403, detail="Accès réservé aux comptes Pharmacien suivis (et admin/superviseur).")
        code = (client_code or "").strip().upper() if _is_staff(user) else await _resolve_own_client_code(db, user)
        if not code:
            raise HTTPException(status_code=409, detail="Aucun code client (client_code) configuré pour ce tenant.")
        from r2_stocks_client import is_configured
        if not is_configured():
            raise HTTPException(status_code=503, detail="Stockage R2 Gestion Stocks non configuré.")
        try:
            return await _storage_usage(db, code)
        except Exception:
            logger.exception("[gestion_stocks] storage usage failed code=%s", code)
            raise HTTPException(status_code=502, detail="Erreur de lecture du stockage R2.")

    @api.post("/gestion-stocks/folders/{folder}/upload", tags=["Portail — Gestion Stocks"])
    async def gestion_stocks_tracked_upload(
        folder: str,
        file: UploadFile = File(...),
        tags: Optional[str] = Form(None, description="Lot 22 — tags séparés par des virgules"),
        description: Optional[str] = Form(None, description="Lot 22 — description facultative"),
        user: dict = Depends(get_current_user),
    ):
        """Dépôt par un utilisateur suivi AUTORISÉ, dans les dossiers de SON
        tenant uniquement (client_code résolu côté serveur). Refus motivé si
        la taille max de son compte ou l'espace alloué au tenant est dépassé."""
        if _is_staff(user) or (user.get("tracked_role") or "") != "Pharmacien":
            raise HTTPException(status_code=403, detail="Dépôt réservé aux utilisateurs suivis autorisés (l'administration utilise son propre espace de dépôt).")
        rights = await _tracked_upload_rights(db, user)
        if not rights["allowed"]:
            raise HTTPException(status_code=403, detail="Dépôt refusé : votre compte n'est pas autorisé à déposer des fichiers. Demandez l'autorisation à votre administrateur SAWALI.")
        _check_folder(folder, allow_root=False)
        code = await _resolve_own_client_code(db, user)
        if not code:
            raise HTTPException(status_code=409, detail="Aucun code client configuré pour votre société — contactez votre administrateur SAWALI.")
        from r2_stocks_client import is_configured, put_bytes
        import asyncio
        if not is_configured():
            raise HTTPException(status_code=503, detail="Stockage R2 Gestion Stocks non configuré.")
        data = await file.read()
        max_bytes = int(rights["max_mb"] * _MB)
        if len(data) > max_bytes:
            raise HTTPException(status_code=413, detail=(
                f"Fichier refusé : « {file.filename} » fait {_fmt_mb(len(data))}, au-delà de la taille maximale "
                f"autorisée pour votre compte ({_fmt_mb(max_bytes)} par fichier)."
            ))
        usage = await _storage_usage(db, code)
        refusal = _quota_refusal(usage, len(data))
        if refusal:
            raise HTTPException(status_code=413, detail=refusal)
        filename = _safe_filename(file.filename or "fichier")
        key = f"{code}/{folder}/{filename}"
        try:
            await asyncio.to_thread(put_bytes, key, data, file.content_type or "application/octet-stream")
        except Exception:
            logger.exception("[gestion_stocks] tracked upload failed key=%s", key)
            raise HTTPException(status_code=502, detail="Échec de l'envoi vers R2.")
        return await _after_upload(code=code, key=key, data=data, content_type=file.content_type,
                                   user=user, tags=tags, description=description)

    @api.post("/gestion-stocks/analyse", tags=["Portail — Gestion Stocks"])
    async def gestion_stocks_analyse(
        payload: Dict[str, Any] = Body(...),
        client_code: Optional[str] = Query(None, description="Admin uniquement — ignoré pour un pharmacien suivi."),
        user: dict = Depends(get_current_user),
    ):
        """Explorateur BD MongoDB Atlas — les 3 boutons Analyseur et la zone
        de prompt libre passent tous par ici. `mode` fixe la question posée
        au LLM ; `question` n'est utilisé que pour mode="libre"."""
        if not _can_access_own_stocks(user):
            raise HTTPException(status_code=403, detail="Accès réservé aux comptes Pharmacien suivis (et admin/superviseur).")
        mode = (payload.get("mode") or "").strip().lower()
        if mode not in ("inventaires", "stocks", "ruptures", "libre"):
            raise HTTPException(status_code=400, detail="mode invalide (attendu: inventaires, stocks, ruptures ou libre).")
        is_admin = (user.get("role") or "") in ("admin", "superviseur")
        code = (client_code or "").strip().upper() if is_admin else await _resolve_own_client_code(db, user)
        if not code:
            raise HTTPException(status_code=409, detail="Aucun code client (client_code) configuré pour ce tenant — voir AdminClients.")

        question = ANALYSE_QUESTIONS.get(mode) or (payload.get("question") or "").strip()
        if not question:
            raise HTTPException(status_code=400, detail="question manquante pour le mode 'libre'.")

        # Agrégats — toujours calculés côté serveur, jamais par le LLM.
        # mode="libre" calcule les 3 pour couvrir une question qui déborde
        # d'une seule catégorie.
        data: Dict[str, Any] = {}
        try:
            if mode in ("inventaires", "libre"):
                data["inventaires"] = await _aggregate_inventory_state(db, code)
            if mode in ("stocks", "libre"):
                data["stocks"] = await _aggregate_sales_trends(db, code)
            if mode in ("ruptures", "libre"):
                data["ruptures"] = await _aggregate_stockout_risks(db, code)
        except Exception:
            logger.exception("[gestion_stocks] aggregation failed client_code=%s mode=%s", code, mode)
            raise HTTPException(status_code=502, detail="Erreur de lecture des données Mongo.")

        # Quota/coût IA — même helper que Liluvine PRO (routes/ai_quotas.py),
        # pré-check avant l'appel puis suivi réel après.
        try:
            from routes.ai_quotas import track_ai_usage
            pre = await track_ai_usage(
                db, user=user, resource="gestion_stocks_analyse", units=800,
                model=GESTION_STOCKS_MODEL, pre_check=True,
            )
            if not pre.get("allowed", True):
                raise HTTPException(status_code=429, detail=pre.get("reason") or "Quota IA dépassé pour ce mois.")
        except ImportError:
            pass

        user_text = (
            f"Question : {question}\n\n"
            f"Données agrégées pour le client {code} (JSON) :\n"
            f"{json.dumps(data, ensure_ascii=False, default=str)}"
        )
        session_id = f"gestion-stocks:{code}:{mode}"
        result = await _analyse_llm_send(session_id, GESTION_STOCKS_SYSTEM_PROMPT, user_text)

        try:
            from routes.ai_quotas import track_ai_usage
            await track_ai_usage(
                db, user=user, resource="gestion_stocks_analyse", units=result["tokens"],
                model=GESTION_STOCKS_MODEL,
            )
        except ImportError:
            pass

        return {"mode": mode, "answer": result["reply"], "data": data}

    @api.get("/gestion-stocks/folders/{folder}/files", tags=["Portail — Gestion Stocks"])
    async def gestion_stocks_list_files(
        folder: str,
        client_code: Optional[str] = Query(None, description="Admin uniquement — ignoré pour un pharmacien suivi."),
        user: dict = Depends(get_current_user),
    ):
        if not _can_access_own_stocks(user):
            raise HTTPException(status_code=403, detail="Accès réservé aux comptes Pharmacien suivis (et admin/superviseur).")
        _check_folder(folder, allow_root=True)
        is_admin = (user.get("role") or "") in ("admin", "superviseur")
        code = (client_code or "").strip().upper() if is_admin else await _resolve_own_client_code(db, user)
        if not code:
            raise HTTPException(status_code=409, detail="Aucun code client (client_code) configuré pour ce tenant — voir AdminClients.")
        from r2_stocks_client import is_configured, list_objects
        import asyncio
        if not is_configured():
            raise HTTPException(status_code=503, detail="Stockage R2 Gestion Stocks non configuré (variables R2_STOCKS_* manquantes).")
        # Racine : fichiers posés directement sous `<code>/` (pas ceux des sous-dossiers).
        prefix = f"{code}/" if folder == ROOT_FOLDER else f"{code}/{folder}/"
        try:
            objects = await asyncio.to_thread(list_objects, prefix)
        except Exception:
            logger.exception("[gestion_stocks] list_objects failed prefix=%s", prefix)
            raise HTTPException(status_code=502, detail="Erreur de lecture du stockage R2.")
        if folder == ROOT_FOLDER:
            objects = [o for o in objects if "/" not in o["key"][len(prefix):]]
        files = [
            {
                "key": o["key"],
                "name": o["key"][len(prefix):],
                "size": o["size"],
                "last_modified": o["last_modified"],
            }
            for o in objects
        ]
        files.sort(key=lambda f: f["last_modified"], reverse=True)
        # Lot 22 — fiches Mongo (créées au passage pour les fichiers qui n'en
        # ont pas encore) : tags, description, suggestions IA, droit de modifier.
        from routes import gestion_stocks_tags as gt
        docs = await gt.ensure_docs(db, code, files)
        upload_allowed = is_admin or (await _tracked_upload_rights(db, user))["allowed"]
        for f in files:
            doc = docs.get(f["key"])
            f.update(gt.public_meta(doc))
            f["can_edit"] = gt.can_edit(user, doc, is_staff=is_admin, upload_allowed=upload_allowed)
        return {"client_code": code, "folder": folder, "files": files}

    @api.get("/gestion-stocks/files/view-url", tags=["Portail — Gestion Stocks"])
    async def gestion_stocks_view_url(
        key: str = Query(...),
        user: dict = Depends(get_current_user),
    ):
        """URL de lecture temporaire (5 min) pour un fichier — le frontend
        l'ouvre dans un nouvel onglet au double-clic."""
        if not _can_access_own_stocks(user):
            raise HTTPException(status_code=403, detail="Accès réservé aux comptes Pharmacien suivis (et admin/superviseur).")
        is_admin = (user.get("role") or "") in ("admin", "superviseur")
        if not is_admin:
            code = await _resolve_own_client_code(db, user)
            if not code or not key.startswith(f"{code}/"):
                # Un pharmacien suivi ne peut jamais obtenir d'URL en dehors
                # de son propre préfixe, même en devinant une clé.
                raise HTTPException(status_code=403, detail="Ce document n'appartient pas à votre espace.")
        from r2_stocks_client import is_configured, get_presigned_url
        import asyncio
        if not is_configured():
            raise HTTPException(status_code=503, detail="Stockage R2 Gestion Stocks non configuré.")
        try:
            url = await asyncio.to_thread(get_presigned_url, key, 300)
        except Exception:
            logger.exception("[gestion_stocks] get_presigned_url failed key=%s", key)
            raise HTTPException(status_code=502, detail="Erreur de génération du lien de lecture.")
        return {"url": url, "expires_in": 300}

    # ------------------------------------------------------------------
    # Admin — alimentation des dossiers (l'outil externe n'a pas encore été
    # discuté ; en attendant, l'admin peut déposer des documents à la main).
    # ------------------------------------------------------------------
    @api.get("/admin/gestion-stocks/clients", tags=["Admin — Gestion Stocks"])
    async def admin_gestion_stocks_clients(_: dict = Depends(staff_user)):
        cursor = db.users.find(
            {"client_code": {"$exists": True, "$nin": [None, ""]}},
            {"_id": 0, "id": 1, "client_code": 1, "company": 1, "full_name": 1},
        )
        items = await cursor.to_list(length=500)
        return [
            {
                "client_code": (it.get("client_code") or "").upper(),
                "label": it.get("company") or it.get("full_name") or it.get("client_code"),
            }
            for it in items
        ]

    @api.post("/admin/gestion-stocks/{client_code}/{folder}/upload", tags=["Admin — Gestion Stocks"])
    async def admin_gestion_stocks_upload(
        client_code: str,
        folder: str,
        file: UploadFile = File(...),
        tags: Optional[str] = Form(None, description="Lot 22 — tags séparés par des virgules"),
        description: Optional[str] = Form(None, description="Lot 22 — description facultative"),
        user: dict = Depends(staff_user),
    ):
        _check_folder(folder, allow_root=False)
        code = (client_code or "").strip().upper()
        if not code:
            raise HTTPException(status_code=400, detail="client_code manquant.")
        from r2_stocks_client import is_configured, put_bytes
        import asyncio
        if not is_configured():
            raise HTTPException(status_code=503, detail="Stockage R2 Gestion Stocks non configuré.")
        data = await file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"Fichier trop volumineux (max {MAX_UPLOAD_BYTES // (1024*1024)} Mo).")
        # Lot 20 — l'espace alloué au tenant vaut aussi pour les dépôts de l'administration.
        refusal = _quota_refusal(await _storage_usage(db, code), len(data))
        if refusal:
            raise HTTPException(status_code=413, detail=refusal)
        filename = _safe_filename(file.filename or "fichier")
        key = f"{code}/{folder}/{filename}"
        try:
            await asyncio.to_thread(put_bytes, key, data, file.content_type or "application/octet-stream")
        except Exception:
            logger.exception("[gestion_stocks] upload failed key=%s", key)
            raise HTTPException(status_code=502, detail="Échec de l'envoi vers R2.")
        return await _after_upload(code=code, key=key, data=data, content_type=file.content_type,
                                   user=user, tags=tags, description=description)

    @api.delete("/admin/gestion-stocks/file", tags=["Admin — Gestion Stocks"])
    async def admin_gestion_stocks_delete(
        key: str = Query(...),
        _: dict = Depends(staff_user),
    ):
        from r2_stocks_client import is_configured, delete_object
        import asyncio
        if not is_configured():
            raise HTTPException(status_code=503, detail="Stockage R2 Gestion Stocks non configuré.")
        try:
            await asyncio.to_thread(delete_object, key)
        except Exception:
            logger.exception("[gestion_stocks] delete failed key=%s", key)
            raise HTTPException(status_code=502, detail="Échec de la suppression.")
        await db.stock_files.delete_one({"key": key})  # Lot 22 — la fiche (tags) part avec le fichier
        return {"ok": True}

    # ------------------------------------------------------------------
    # Lot 20 — réglages : droit de dépôt par utilisateur suivi, espace alloué par tenant
    # ------------------------------------------------------------------
    @api.get("/admin/gestion-stocks/tracked-users/{tu_id}/upload-rights", tags=["Admin — Gestion Stocks"])
    async def admin_get_upload_rights(tu_id: str, _: dict = Depends(staff_user)):
        tu = await db.tracked_users.find_one({"id": tu_id}, {"_id": 0, "id": 1, "r2_upload_allowed": 1, "r2_upload_max_mb": 1})
        if not tu:
            raise HTTPException(status_code=404, detail="Utilisateur suivi introuvable.")
        return {
            "tracked_user_id": tu_id,
            "allowed": bool(tu.get("r2_upload_allowed")),
            "max_mb": _clean_max_mb(tu.get("r2_upload_max_mb", DEFAULT_TRACKED_UPLOAD_MAX_MB)),
            "default_max_mb": DEFAULT_TRACKED_UPLOAD_MAX_MB,
        }

    @api.put("/admin/gestion-stocks/tracked-users/{tu_id}/upload-rights", tags=["Admin — Gestion Stocks"])
    async def admin_set_upload_rights(tu_id: str, payload: Dict[str, Any] = Body(...), user: dict = Depends(staff_user)):
        tu = await db.tracked_users.find_one({"id": tu_id}, {"_id": 0, "id": 1})
        if not tu:
            raise HTTPException(status_code=404, detail="Utilisateur suivi introuvable.")
        try:
            max_mb = float(payload.get("max_mb", DEFAULT_TRACKED_UPLOAD_MAX_MB))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Taille maximale invalide.")
        if not 0 < max_mb <= MAX_UPLOAD_BYTES / _MB:
            raise HTTPException(status_code=400, detail=f"La taille maximale doit être comprise entre 0 et {MAX_UPLOAD_BYTES // _MB} Mo.")
        doc = {"r2_upload_allowed": bool(payload.get("allowed")), "r2_upload_max_mb": max_mb,
               "r2_upload_updated_at": _now(), "r2_upload_updated_by": user["id"]}
        await db.tracked_users.update_one({"id": tu_id}, {"$set": doc})
        return {"tracked_user_id": tu_id, "allowed": doc["r2_upload_allowed"], "max_mb": max_mb}

    @api.get("/admin/gestion-stocks/tenants/{client_id}/storage", tags=["Admin — Gestion Stocks"])
    async def admin_get_tenant_storage(client_id: str, _: dict = Depends(staff_user)):
        tenant = await db.users.find_one({"id": client_id}, {"_id": 0, "id": 1, "client_code": 1, "gestion_stocks_quota_gb": 1,
                                                             "gestion_stocks_ai_tags": 1})
        if not tenant:
            raise HTTPException(status_code=404, detail="Client introuvable.")
        code = (tenant.get("client_code") or "").strip().upper()
        out = {
            "client_id": client_id, "client_code": code or None,
            "quota_gb": _clean_quota_gb(tenant.get("gestion_stocks_quota_gb", DEFAULT_TENANT_QUOTA_GB)),
            "default_quota_gb": DEFAULT_TENANT_QUOTA_GB, "used_bytes": None, "files": None,
            # Lot 22 — suggestions IA de tags (désactivées par défaut)
            "ai_tags": bool(tenant.get("gestion_stocks_ai_tags")),
        }
        from r2_stocks_client import is_configured
        if code and is_configured():
            try:
                usage = await _storage_usage(db, code)
                out.update(used_bytes=usage["used_bytes"], files=usage["files"])
            except Exception:  # noqa: BLE001 — l'affichage du réglage ne doit pas échouer
                logger.exception("[gestion_stocks] storage usage failed code=%s", code)
        return out

    @api.put("/admin/gestion-stocks/tenants/{client_id}/storage", tags=["Admin — Gestion Stocks"])
    async def admin_set_tenant_storage(client_id: str, payload: Dict[str, Any] = Body(...), _: dict = Depends(staff_user)):
        tenant = await db.users.find_one({"id": client_id}, {"_id": 0, "id": 1})
        if not tenant:
            raise HTTPException(status_code=404, detail="Client introuvable.")
        update: Dict[str, Any] = {}
        # Lot 22 — `quota_gb` et `ai_tags` sont chacun facultatifs (au moins un des deux).
        if "quota_gb" in payload:
            try:
                quota_gb = float(payload.get("quota_gb"))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Espace alloué invalide.")
            if not 0 < quota_gb <= 10000:
                raise HTTPException(status_code=400, detail="L'espace alloué doit être compris entre 0 et 10 000 Go.")
            update["gestion_stocks_quota_gb"] = quota_gb
        if "ai_tags" in payload:
            update["gestion_stocks_ai_tags"] = bool(payload.get("ai_tags"))
        if not update:
            raise HTTPException(status_code=400, detail="Rien à enregistrer.")
        await db.users.update_one({"id": client_id}, {"$set": update})
        return {"client_id": client_id, "quota_gb": update.get("gestion_stocks_quota_gb"),
                "ai_tags": update.get("gestion_stocks_ai_tags")}

    # ------------------------------------------------------------------
    # Lot 22 — tags et recherche des documents (index Mongo `stock_files`)
    # ------------------------------------------------------------------
    async def _code_for(user: dict, client_code: Optional[str]) -> str:
        """Tenant de la requête : choisi par l'administration, résolu côté
        serveur pour un utilisateur suivi (jamais depuis la requête)."""
        if not _can_access_own_stocks(user):
            raise HTTPException(status_code=403, detail="Accès réservé aux comptes Pharmacien suivis (et admin/superviseur).")
        code = (client_code or "").strip().upper() if _is_staff(user) else await _resolve_own_client_code(db, user)
        if not code:
            raise HTTPException(status_code=409, detail="Aucun code client (client_code) configuré pour ce tenant.")
        return code

    async def _code_for_key(user: dict, key: str) -> str:
        """Tenant d'un fichier désigné par sa clé R2 : un utilisateur suivi ne
        peut jamais viser une clé hors de son propre préfixe."""
        if not key or ".." in key.split("/") or "/" not in key:
            raise HTTPException(status_code=400, detail="Fichier invalide.")
        if _is_staff(user):
            return key.split("/", 1)[0]
        code = await _code_for(user, None)
        if not key.startswith(f"{code}/"):
            raise HTTPException(status_code=403, detail="Ce document n'appartient pas à votre espace.")
        return code

    async def _editable_doc(user: dict, key: str) -> Dict[str, Any]:
        """Fiche d'un fichier que l'utilisateur a le droit de taguer (403 sinon)."""
        from routes import gestion_stocks_tags as gt
        code = await _code_for_key(user, key)
        doc = await db.stock_files.find_one({"key": key}, {"_id": 0})
        if doc is None:
            # Fichier sans fiche (posé hors Sawali) : on vérifie qu'il existe dans R2.
            from r2_stocks_client import list_objects
            objects = [o for o in await asyncio.to_thread(list_objects, key) if o["key"] == key]
            if not objects:
                raise HTTPException(status_code=404, detail="Fichier introuvable.")
            doc = (await gt.ensure_docs(db, code, objects))[key]
        allowed = _is_staff(user) or (await _tracked_upload_rights(db, user))["allowed"]
        if not gt.can_edit(user, doc, is_staff=_is_staff(user), upload_allowed=allowed):
            raise HTTPException(status_code=403, detail=(
                "Vous ne pouvez modifier les tags que des fichiers que vous avez déposés vous-même "
                "(et si votre compte est autorisé à déposer)."))
        return {"code": code, "doc": doc}

    @api.get("/gestion-stocks/tags", tags=["Portail — Gestion Stocks"])
    async def gestion_stocks_tags(
        client_code: Optional[str] = Query(None, description="Admin/superviseur uniquement."),
        user: dict = Depends(get_current_user),
    ):
        """Tags utilisés par le client, avec leur nombre de fichiers."""
        from routes import gestion_stocks_tags as gt
        code = await _code_for(user, client_code)
        return {"client_code": code, "tags": await gt.tag_counts(db, code)}

    @api.get("/gestion-stocks/search", tags=["Portail — Gestion Stocks"])
    async def gestion_stocks_search(
        q: str = Query("", max_length=200),
        tags: str = Query("", description="Tags obligatoires, séparés par des virgules"),
        client_code: Optional[str] = Query(None, description="Admin/superviseur uniquement."),
        user: dict = Depends(get_current_user),
    ):
        """Recherche dans tous les dossiers du client : nom, tags, description."""
        from routes import gestion_stocks_tags as gt
        from r2_stocks_client import is_configured, list_objects
        code = await _code_for(user, client_code)
        if not is_configured():
            raise HTTPException(status_code=503, detail="Stockage R2 Gestion Stocks non configuré.")
        try:
            objects = await asyncio.to_thread(list_objects, f"{code}/")
        except Exception:
            logger.exception("[gestion_stocks] search list_objects failed code=%s", code)
            raise HTTPException(status_code=502, detail="Erreur de lecture du stockage R2.")
        docs = {d["key"]: d async for d in db.stock_files.find({"client_code": code}, {"_id": 0})}
        results = gt.search(objects, docs, code, q=q, tags=gt.clean_tags(tags))
        upload_allowed = _is_staff(user) or (await _tracked_upload_rights(db, user))["allowed"]
        for r in results:
            r["can_edit"] = gt.can_edit(user, docs.get(r["key"]), is_staff=_is_staff(user), upload_allowed=upload_allowed)
        return {"client_code": code, "q": q, "tags": gt.clean_tags(tags), "results": results,
                "truncated": len(results) >= gt.MAX_SEARCH_RESULTS}

    @api.put("/gestion-stocks/files/meta", tags=["Portail — Gestion Stocks"])
    async def gestion_stocks_set_meta(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        """Tags et description d'un fichier (remplacent les précédents)."""
        from routes import gestion_stocks_tags as gt
        key = str(payload.get("key") or "")
        ctx = await _editable_doc(user, key)
        update: Dict[str, Any] = {"updated_at": _now()}
        if "tags" in payload:
            update["tags"] = gt.clean_tags(payload.get("tags"))
        if "description" in payload:
            update["description"] = gt.clean_description(payload.get("description"))
        await db.stock_files.update_one({"key": key}, {"$set": update})
        doc = await db.stock_files.find_one({"key": key}, {"_id": 0})
        return {"key": key, **gt.public_meta(doc), "can_edit": True, "client_code": ctx["code"]}

    @api.post("/gestion-stocks/files/suggest-tags", tags=["Portail — Gestion Stocks"])
    async def gestion_stocks_suggest_tags(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        """Suggestions IA de tags pour un fichier déjà déposé (à la demande).
        Réservé aux clients pour lesquels l'administration a activé l'option."""
        from routes import gestion_stocks_tags as gt
        from r2_stocks_client import get_bytes, is_configured
        key = str(payload.get("key") or "")
        ctx = await _editable_doc(user, key)
        if not await gt.tenant_ai_enabled(db, ctx["code"]):
            raise HTTPException(status_code=403, detail=(
                "Les suggestions de tags par l'IA ne sont pas activées pour ce client "
                "(Admin → Clients → SMART Communications → Espace de stockage R2)."))
        name = ctx["doc"].get("name") or key.rsplit("/", 1)[-1]
        if not gt.is_ai_taggable(name, ctx["doc"].get("size")):
            raise HTTPException(status_code=400, detail=(
                "Ce type de fichier ne peut pas être analysé par l'IA (PDF, images, .txt et .csv "
                "de 10 Mo au plus uniquement)."))
        if not is_configured():
            raise HTTPException(status_code=503, detail="Stockage R2 Gestion Stocks non configuré.")
        try:
            data = await asyncio.to_thread(get_bytes, key)
        except Exception:
            logger.exception("[gestion_stocks] get_bytes failed key=%s", key)
            raise HTTPException(status_code=502, detail="Erreur de lecture du stockage R2.")
        out = await gt.suggest_tags(db, code=ctx["code"], key=key, data=data,
                                    content_type=ctx["doc"].get("content_type") or gt.guess_content_type(name),
                                    filename=name)
        doc = await db.stock_files.find_one({"key": key}, {"_id": 0})
        return {"key": key, **gt.public_meta(doc), "cost_xof": out["cost_xof"]}

    logger.info("[gestion_stocks] routes mounted under /api/gestion-stocks and /api/admin/gestion-stocks")


__all__ = ["attach_gestion_stocks_routes", "DEFAULT_FOLDERS"]
