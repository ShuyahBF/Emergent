# quota_atlas.py — Lot 79.8 : jauge du nombre de collections du cluster Atlas, avec alerte avant le blocage.
#
# Pourquoi : un cluster Atlas « Flex » (ou M0) accepte au plus 500 collections POUR TOUT LE CLUSTER, toutes bases
# confondues (SAWALI, ALBARKA, DentalCare, adLyn… partagent Cluster0). Le 08/10/2026, une copie de secours créée
# sur ce même cluster a atteint 500/500 : plus aucune plateforme ne pouvait créer de collection (erreurs silencieuses).
#
# Ce module :
#   1. COMPTE les collections de toutes les bases visibles du cluster (hors bases internes « local » et « config ») ;
#      si le compte de connexion n'a pas le droit de lister les bases, il compte au moins la base de SAWALI ;
#   2. EXPOSE la jauge : GET /api/admin/atlas/quota (Paramètres → « 🗄️ Base Atlas — collections du cluster ») ;
#   3. SURVEILLE toutes les heures : au-delà du seuil d'alerte (450 par défaut), une ligne d'avertissement au
#      journal et UN message WhatsApp par jour au numéro du super-admin (relais de Liluvine).
# Réglages (db.settings {_id: "global"}) : atlas_limite_collections (défaut 500), atlas_seuil_alerte (défaut 450).
# Dernière mesure gardée dans db.settings {_id: "quota_atlas"} (aucune nouvelle collection).
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sawali.quota_atlas")

LIMITE_DEFAUT = 500
SEUIL_DEFAUT = 450
DOC_ID = "quota_atlas"
BASES_IGNOREES = {"local", "config"}     # bases internes de MongoDB, hors quota utilisateur


def reglages_quota(s: Dict[str, Any]) -> Dict[str, int]:
    """Limite du cluster et seuil d'alerte (entiers positifs, seuil ≤ limite)."""
    def _entier(v: Any, defaut: int) -> int:
        try:
            n = int(v)
            return n if n > 0 else defaut
        except (TypeError, ValueError):
            return defaut
    limite = _entier((s or {}).get("atlas_limite_collections"), LIMITE_DEFAUT)
    seuil = min(_entier((s or {}).get("atlas_seuil_alerte"), SEUIL_DEFAUT), limite)
    return {"limite": limite, "seuil": seuil}


# Lot 79.9 — couleurs de la jauge selon le taux d'occupation (demande du propriétaire) :
#   vert sous 45 % ; orange à partir de 45 % ; rouge quand il ne reste que 10 % ou moins (≥ 90 %).
PART_ORANGE = 0.45
PART_ROUGE = 0.90


def niveau(total: int, limite: int, seuil: int = 0) -> str:
    """Couleur de la jauge : ok (vert), attention (orange, ≥ 45 %), plein (rouge, ≥ 90 % : 10 % ou moins restant).
    `seuil` (alerte WhatsApp) est accepté pour compatibilité ; la couleur dépend du taux d'occupation."""
    part = total / limite if limite else 1
    if part >= PART_ROUGE:
        return "plein"
    if part >= PART_ORANGE:
        return "attention"
    return "ok"


async def compter(client, base_courante: str) -> Dict[str, Any]:
    """Collections par base du cluster. → {"total", "bases": [{"nom", "collections"}], "methode", "erreur"}."""
    bases: List[Dict[str, Any]] = []
    methode, erreur = "cluster", None
    try:
        noms = [n for n in await client.list_database_names() if n not in BASES_IGNOREES]
    except Exception as exc:  # noqa: BLE001 — droit « listDatabases » absent : la base de SAWALI seulement
        noms, methode, erreur = [base_courante], "base seule", f"liste des bases refusée ({type(exc).__name__})"
    for nom in sorted(noms):
        try:
            nb = len(await client[nom].list_collection_names())
        except Exception as exc:  # noqa: BLE001 — une base illisible n'empêche pas de compter les autres
            nb, erreur = 0, f"base {nom} illisible ({type(exc).__name__})"
        bases.append({"nom": nom, "collections": nb, "sawali": nom == base_courante})
    bases.sort(key=lambda b: -b["collections"])
    return {"total": sum(b["collections"] for b in bases), "bases": bases, "methode": methode, "erreur": erreur}


async def mesurer(db, client, base_courante: str) -> Dict[str, Any]:
    """Mesure complète (compte + réglages + niveau), gardée dans db.settings {_id: "quota_atlas"}."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    cfg = reglages_quota(s)
    mesure = await compter(client, base_courante)
    mesure.update(cfg)
    mesure["pourcentage"] = round(100 * mesure["total"] / cfg["limite"], 1) if cfg["limite"] else 0
    mesure["restantes"] = max(0, cfg["limite"] - mesure["total"])
    mesure["niveau"] = niveau(mesure["total"], cfg["limite"], cfg["seuil"])
    mesure["le"] = datetime.now(timezone.utc).isoformat()
    await db.settings.update_one({"_id": DOC_ID}, {"$set": {"derniere_mesure": mesure}}, upsert=True)
    return mesure


def texte_alerte(m: Dict[str, Any]) -> str:
    """Message d'alerte au propriétaire (une seule ligne : utilisable dans un modèle Meta)."""
    principales = ", ".join(f"{b['nom']} {b['collections']}" for b in m["bases"][:4])
    etat = "LIMITE ATTEINTE : plus aucune collection ne peut être créée" if m["total"] >= m["limite"] else \
        f"plus que {m['restantes']} avant le blocage"
    return (f"🗄️ Cluster Atlas : {m['total']} collections sur {m['limite']} ({m['pourcentage']} %) — {etat}. "
            f"Principales bases : {principales}. Supprimez les copies inutiles ou utilisez un autre cluster.")


async def surveiller(db, client, base_courante: str, maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Tâche horaire : mesure, et au-delà du seuil, avertissement au journal + WhatsApp une fois par jour."""
    m = await mesurer(db, client, base_courante)
    if m["total"] < m["seuil"]:                  # alerte WhatsApp seulement au-delà du seuil (450 par défaut)
        return {"mesure": m, "alerte": False}
    logger.warning("[quota_atlas] %s/%s collections sur le cluster (seuil %s)", m["total"], m["limite"], m["seuil"])
    maintenant = maintenant or datetime.now(timezone.utc)
    jour = maintenant.date().isoformat()
    suivi = await db.settings.find_one({"_id": DOC_ID}) or {}
    if suivi.get("alerte_jour") == jour:
        return {"mesure": m, "alerte": False, "raison": "alerte déjà envoyée aujourd'hui"}
    s = await db.settings.find_one({"_id": "global"}) or {}
    proprio = "".join(c for c in str(s.get("super_admin_phone") or "") if c.isdigit())
    envoye = False
    if proprio:
        try:
            from routes import appel_proprietaire as ap
            cfg = ap.reglages(s)
            numero_id, _ligne = ap.ligne_appelante(s, cfg)
            texte = texte_alerte(m)
            r = await ap.envoyer_relais(db, s, cfg, numero_id, proprio, texte,
                                        ["Liluvine — base Atlas", texte, ap.formater_date(maintenant)], maintenant)
            envoye = bool(r.get("ok"))
        except Exception:  # noqa: BLE001 — l'alerte ne doit jamais casser la tâche
            logger.warning("[quota_atlas] alerte WhatsApp non envoyée", exc_info=True)
    await db.settings.update_one({"_id": DOC_ID}, {"$set": {"alerte_jour": jour, "alerte_envoyee": envoye}},
                                 upsert=True)
    return {"mesure": m, "alerte": envoye}


def setup_quota_atlas_routes(*, db, client, api, get_current_user, base_courante: str) -> None:
    """Route de la jauge (administrateurs)."""
    from fastapi import Depends, HTTPException

    @api.get("/admin/atlas/quota", tags=["Admin — Santé"])
    async def quota(recente: bool = False, user: dict = Depends(get_current_user)):
        """Nombre de collections du cluster Atlas par rapport à sa limite (jauge des Paramètres et de la barre latérale).
        Lot 79.9 — `recente=true` (barre latérale) : la dernière mesure si elle a moins de 15 minutes, sans recompter."""
        if user.get("role") not in ("admin", "super_admin") and user.get("tracked_role") != "Administrateur":
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs")
        if recente:
            suivi = await db.settings.find_one({"_id": DOC_ID}) or {}
            m = suivi.get("derniere_mesure") or {}
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(m.get("le"))).total_seconds()
            except (TypeError, ValueError):
                age = None
            if age is not None and age < 15 * 60:
                # Couleur recalculée avec la règle en vigueur (une ancienne mesure peut dater d'avant le lot 79.9)
                m["niveau"] = niveau(int(m.get("total") or 0), int(m.get("limite") or LIMITE_DEFAUT))
                return m
        return await mesurer(db, client, base_courante)
