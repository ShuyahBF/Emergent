"""Lot "Gestion Stocks" (2026-09) — espace documentaire des Pharmaciens
suivis (tracked_role == "Pharmacien"), nouveau lien de sidebar.

Deux blocs prévus au schéma fourni par l'utilisateur :
  1. "Explorateur BD MongoDB Atlas" — Analyseur Inventaires/Stocks/Ruptures
     + zone de prompt libre (IA conversationnelle). Les 3 collections
     (stock_products, stock_inventory_snapshots, stock_sales_history) sont
     alimentées par un outil externe (partie technique discutée séparément)
     — ce module ne fait QUE les lire, jamais les écrire. Tant qu'elles
     sont vides, les analyseurs répondent avec des agrégats à zéro (pas
     d'erreur) et le LLM le signale.
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

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, File, HTTPException, Query, UploadFile

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


# ======================================================================
# Explorateur BD MongoDB Atlas — agrégations (lecture seule, jamais de
# requête générée par le LLM : il ne reçoit que ces agrégats en contexte).
# ======================================================================

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
        "Identifie les ruptures de stock actuelles et les risques de "
        "rupture imminente (sous le seuil d'alerte ou d'après la vitesse "
        "de vente récente)."
    ),
}


async def _latest_inventory_by_sku(db, client_code: str) -> List[Dict[str, Any]]:
    """Pour chaque SKU, le relevé d'inventaire le plus récent (les imports
    successifs de l'outil externe s'accumulent — on ne garde que le
    dernier état connu par produit)."""
    pipeline = [
        {"$match": {"client_code": client_code}},
        {"$sort": {"date_inventaire": -1}},
        {"$group": {
            "_id": "$sku",
            "designation": {"$first": "$designation"},
            "quantite": {"$first": "$quantite"},
            "date_inventaire": {"$first": "$date_inventaire"},
        }},
    ]
    return await db.stock_inventory_snapshots.aggregate(pipeline).to_list(length=5000)


async def _aggregate_inventory_state(db, client_code: str) -> Dict[str, Any]:
    rows = await _latest_inventory_by_sku(db, client_code)
    top = sorted(rows, key=lambda r: r.get("quantite") or 0, reverse=True)[:10]
    zero_stock = [r for r in rows if (r.get("quantite") or 0) == 0]
    dates = [r.get("date_inventaire") for r in rows if r.get("date_inventaire")]
    return {
        "total_skus_suivis": len(rows),
        "quantite_totale": sum(r.get("quantite") or 0 for r in rows),
        "top_produits_par_quantite": [
            {"sku": r["_id"], "designation": r.get("designation") or r["_id"], "quantite": r.get("quantite") or 0}
            for r in top
        ],
        "nb_produits_stock_zero": len(zero_stock),
        "date_dernier_releve": max(dates) if dates else None,
    }


async def _aggregate_sales_trends(db, client_code: str, days: int = 30) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()
    prev_since = (now - timedelta(days=2 * days)).isoformat()

    pipeline_current = [
        {"$match": {"client_code": client_code, "date_vente": {"$gte": since}}},
        {"$group": {
            "_id": "$sku",
            "designation": {"$first": "$designation"},
            "quantite_vendue": {"$sum": "$quantite_vendue"},
            "montant": {"$sum": "$montant"},
        }},
    ]
    rows = await db.stock_sales_history.aggregate(pipeline_current).to_list(length=5000)
    total_amount = sum(r.get("montant") or 0 for r in rows)
    total_qty = sum(r.get("quantite_vendue") or 0 for r in rows)
    top = sorted(rows, key=lambda r: r.get("quantite_vendue") or 0, reverse=True)[:10]

    pipeline_prev = [
        {"$match": {"client_code": client_code, "date_vente": {"$gte": prev_since, "$lt": since}}},
        {"$group": {"_id": None, "montant": {"$sum": "$montant"}}},
    ]
    prev_rows = await db.stock_sales_history.aggregate(pipeline_prev).to_list(length=1)
    prev_amount = (prev_rows[0].get("montant") if prev_rows else 0) or 0
    variation_pct = round(((total_amount - prev_amount) / prev_amount) * 100, 1) if prev_amount else None

    return {
        "periode_jours": days,
        "montant_total": total_amount,
        "quantite_totale_vendue": total_qty,
        "top_produits_par_ventes": [
            {"sku": r["_id"], "designation": r.get("designation") or r["_id"], "quantite_vendue": r.get("quantite_vendue") or 0}
            for r in top
        ],
        "montant_periode_precedente": prev_amount,
        "variation_pct_vs_periode_precedente": variation_pct,
    }


async def _aggregate_stockout_risks(
    db, client_code: str, velocity_days: int = 30, horizon_days: int = 7,
) -> Dict[str, Any]:
    inventory_rows = await _latest_inventory_by_sku(db, client_code)
    inv_by_sku = {r["_id"]: r for r in inventory_rows}

    product_rows = await db.stock_products.find(
        {"client_code": client_code}, {"_id": 0, "sku": 1, "seuil_alerte": 1},
    ).to_list(length=5000)
    seuils = {p["sku"]: p.get("seuil_alerte") for p in product_rows if p.get("seuil_alerte") is not None}

    since = (datetime.now(timezone.utc) - timedelta(days=velocity_days)).isoformat()
    pipeline = [
        {"$match": {"client_code": client_code, "date_vente": {"$gte": since}}},
        {"$group": {"_id": "$sku", "quantite_vendue": {"$sum": "$quantite_vendue"}}},
    ]
    sales_rows = await db.stock_sales_history.aggregate(pipeline).to_list(length=5000)
    velocity = {r["_id"]: (r.get("quantite_vendue") or 0) / velocity_days for r in sales_rows}

    ruptures_actuelles: List[Dict[str, Any]] = []
    produits_a_risque: List[Dict[str, Any]] = []
    for sku, inv in inv_by_sku.items():
        qty = inv.get("quantite") or 0
        seuil = seuils.get(sku)
        if seuil is not None and qty <= seuil:
            ruptures_actuelles.append({
                "sku": sku, "designation": inv.get("designation") or sku,
                "quantite": qty, "seuil_alerte": seuil,
            })
            continue
        v = velocity.get(sku)
        if v and v > 0:
            jours_restants = qty / v
            if jours_restants <= horizon_days:
                produits_a_risque.append({
                    "sku": sku, "designation": inv.get("designation") or sku,
                    "quantite": qty, "jours_restants_estimes": round(jours_restants, 1),
                })
    produits_a_risque.sort(key=lambda r: r["jours_restants_estimes"])
    return {
        "ruptures_actuelles": ruptures_actuelles[:20],
        "horizon_risque_jours": horizon_days,
        "produits_a_risque_bientot": produits_a_risque[:20],
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

    @api.get("/gestion-stocks/context", tags=["Portail — Gestion Stocks"])
    async def gestion_stocks_context(user: dict = Depends(get_current_user)):
        """Renvoie le client_code résolu + la liste des dossiers — le
        frontend s'en sert pour savoir quoi afficher avant tout listing."""
        if not _can_access_own_stocks(user):
            raise HTTPException(status_code=403, detail="Accès réservé aux comptes Pharmacien suivis (et admin/superviseur).")
        from r2_stocks_client import is_configured
        client_code = None
        if (user.get("role") or "") in ("admin", "superviseur"):
            client_code = None  # l'admin choisit un client_code explicitement (voir endpoints /admin/*)
        else:
            client_code = await _resolve_own_client_code(db, user)
        return {
            "client_code": client_code,
            "folders": DEFAULT_FOLDERS,
            "r2_configured": is_configured(),
            "is_admin": (user.get("role") or "") in ("admin", "superviseur"),
        }

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
        if folder not in DEFAULT_FOLDERS:
            raise HTTPException(status_code=404, detail="Dossier inconnu.")
        is_admin = (user.get("role") or "") in ("admin", "superviseur")
        code = (client_code or "").strip().upper() if is_admin else await _resolve_own_client_code(db, user)
        if not code:
            raise HTTPException(status_code=409, detail="Aucun code client (client_code) configuré pour ce tenant — voir AdminClients.")
        from r2_stocks_client import is_configured, list_objects
        import asyncio
        if not is_configured():
            raise HTTPException(status_code=503, detail="Stockage R2 Gestion Stocks non configuré (variables R2_STOCKS_* manquantes).")
        prefix = f"{code}/{folder}/"
        try:
            objects = await asyncio.to_thread(list_objects, prefix)
        except Exception:
            logger.exception("[gestion_stocks] list_objects failed prefix=%s", prefix)
            raise HTTPException(status_code=502, detail="Erreur de lecture du stockage R2.")
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
    async def admin_gestion_stocks_clients(_: dict = Depends(get_current_admin)):
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
        _: dict = Depends(get_current_admin),
    ):
        if folder not in DEFAULT_FOLDERS:
            raise HTTPException(status_code=404, detail="Dossier inconnu.")
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
        filename = _safe_filename(file.filename or "fichier")
        key = f"{code}/{folder}/{filename}"
        try:
            await asyncio.to_thread(put_bytes, key, data, file.content_type or "application/octet-stream")
        except Exception:
            logger.exception("[gestion_stocks] upload failed key=%s", key)
            raise HTTPException(status_code=502, detail="Échec de l'envoi vers R2.")
        return {"ok": True, "key": key, "size": len(data)}

    @api.delete("/admin/gestion-stocks/file", tags=["Admin — Gestion Stocks"])
    async def admin_gestion_stocks_delete(
        key: str = Query(...),
        _: dict = Depends(get_current_admin),
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
        return {"ok": True}

    logger.info("[gestion_stocks] routes mounted under /api/gestion-stocks and /api/admin/gestion-stocks")


__all__ = ["attach_gestion_stocks_routes", "DEFAULT_FOLDERS"]
