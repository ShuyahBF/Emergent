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


# ---------------------------------------------------------------------------
# Lot 122 (12/10/2026) — jauge de TAILLE du cluster de COPIE (Clusterbkp, offre gratuite M0 : 512 Mo au plus).
# Demande du propriétaire : « Oui fais les jauges et l'alerte à 90 % ». Une fois plein, un cluster gratuit refuse
# toute écriture : les sauvegardes programmées échoueraient. Son adresse est celle, CHIFFRÉE, des sauvegardes
# programmées (Paramètres → sauvegardes programmées) : elle n'est jamais affichée ni renvoyée au navigateur.
# Taille mesurée = données + index de chaque base (commande dbStats), comme la « Data size » affichée par Atlas.
# Réglages (db.settings {_id: "global"}) : atlas_secours_limite_mo (défaut 512), atlas_secours_seuil_pct (défaut 90).
# ---------------------------------------------------------------------------
LIMITE_SECOURS_MO = 512
SEUIL_SECOURS_PCT = 90


def reglages_secours(s: Dict[str, Any]) -> Dict[str, float]:
    """Limite (Mo) du cluster de copie et seuil d'alerte (% de la limite)."""
    def _nombre(v: Any, defaut: float, maxi: float) -> float:
        try:
            n = float(v)
            return n if 0 < n <= maxi else defaut
        except (TypeError, ValueError):
            return defaut
    return {"limite_mo": _nombre((s or {}).get("atlas_secours_limite_mo"), LIMITE_SECOURS_MO, 1_000_000),
            "seuil_pct": _nombre((s or {}).get("atlas_secours_seuil_pct"), SEUIL_SECOURS_PCT, 100)}


async def taille_cluster(client) -> Dict[str, Any]:
    """Taille (Mo) de chaque base du cluster = dataSize + indexSize. → {"total_mo", "bases": [{"nom", "mo"}]}."""
    bases: List[Dict[str, Any]] = []
    noms = [n for n in await client.list_database_names() if n not in BASES_IGNOREES | {"admin"}]
    for nom in sorted(noms):
        try:
            st = await client[nom].command("dbStats")
            mo = (float(st.get("dataSize") or 0) + float(st.get("indexSize") or 0)) / (1024 * 1024)
        except Exception:  # noqa: BLE001 — une base illisible n'empêche pas de mesurer les autres
            mo = 0.0
        bases.append({"nom": nom, "mo": round(mo, 2)})
    bases.sort(key=lambda b: -b["mo"])
    return {"total_mo": round(sum(b["mo"] for b in bases), 2), "bases": bases}


def mesure_secours(taille: Dict[str, Any], cfg: Dict[str, float]) -> Dict[str, Any]:
    """Ajoute pourcentage, place restante, niveau de couleur et dépassement du seuil d'alerte."""
    limite = cfg["limite_mo"]
    pct = round(100 * taille["total_mo"] / limite, 1) if limite else 0
    return {**taille, "limite_mo": limite, "seuil_pct": cfg["seuil_pct"], "pourcentage": pct,
            "restant_mo": round(max(0.0, limite - taille["total_mo"]), 1),
            "niveau": niveau(int(round(taille["total_mo"])), int(limite)), "alerte": pct >= cfg["seuil_pct"]}


async def mesurer_secours(db) -> Dict[str, Any]:
    """Mesure du cluster de copie. {"configure": False} si aucune adresse n'est enregistrée. Ne lève jamais."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    cfg = reglages_secours(s)
    try:
        from routes import migration_programmation as mp
        from routes import migration_render as mr
        ids = await mp.charger_identifiants()
    except Exception:  # noqa: BLE001 — aucun identifiant enregistré (ou illisible)
        return {"configure": False, **cfg}
    uri = ids.get("mongo_uri") or ""
    if len(uri) < 10:
        return {"configure": False, **cfg}
    client = None
    try:
        client = mr._client_cible(uri)
        m = mesure_secours(await taille_cluster(client), cfg)
        m.update({"configure": True, "hote": mr._hote(uri), "le": datetime.now(timezone.utc).isoformat()})
    except Exception as exc:  # noqa: BLE001 — cluster injoignable : on le dit, sans l'adresse
        m = {"configure": True, "erreur": f"cluster de copie injoignable ({type(exc).__name__})", **cfg,
             "le": datetime.now(timezone.utc).isoformat()}
    finally:
        if client is not None:
            client.close()
    await db.settings.update_one({"_id": DOC_ID}, {"$set": {"derniere_mesure_secours": m}}, upsert=True)
    return m


def texte_alerte_secours(m: Dict[str, Any]) -> str:
    """Message d'alerte (une ligne) : cluster de copie presque plein."""
    return (f"🗄️ Cluster de copie ({m.get('hote') or 'sauvegardes'}) : {m['total_mo']} Mo sur {m['limite_mo']:.0f} Mo "
            f"({m['pourcentage']} %) — plus que {m['restant_mo']} Mo. Purgez les anciennes copies (🧹 Libérer l'Espace) "
            f"avant que les sauvegardes programmées ne soient refusées.")


async def _envoyer_alerte(db, texte: str, maintenant: datetime) -> bool:
    """WhatsApp au super-admin par le relais de Liluvine (même canal que l'alerte des collections)."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    proprio = "".join(c for c in str(s.get("super_admin_phone") or "") if c.isdigit())
    if not proprio:
        return False
    try:
        from routes import appel_proprietaire as ap
        cfg = ap.reglages(s)
        numero_id, _ligne = ap.ligne_appelante(s, cfg)
        r = await ap.envoyer_relais(db, s, cfg, numero_id, proprio, texte,
                                    ["Liluvine — base Atlas", texte, ap.formater_date(maintenant)], maintenant)
        return bool(r.get("ok"))
    except Exception:  # noqa: BLE001 — l'alerte ne doit jamais casser la tâche
        logger.warning("[quota_atlas] alerte WhatsApp non envoyée", exc_info=True)
        return False


async def surveiller_secours(db, maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Tâche horaire (lot 122) : au-delà de 90 % du cluster de copie, WhatsApp UNE fois par jour."""
    m = await mesurer_secours(db)
    if not m.get("configure") or m.get("erreur") or not m.get("alerte"):
        return {"mesure": m, "alerte": False}
    logger.warning("[quota_atlas] cluster de copie : %s Mo / %s Mo", m["total_mo"], m["limite_mo"])
    maintenant = maintenant or datetime.now(timezone.utc)
    jour = maintenant.date().isoformat()
    suivi = await db.settings.find_one({"_id": DOC_ID}) or {}
    if suivi.get("alerte_secours_jour") == jour:
        return {"mesure": m, "alerte": False, "raison": "alerte déjà envoyée aujourd'hui"}
    envoye = await _envoyer_alerte(db, texte_alerte_secours(m), maintenant)
    await db.settings.update_one({"_id": DOC_ID}, {"$set": {"alerte_secours_jour": jour,
                                                             "alerte_secours_envoyee": envoye}}, upsert=True)
    return {"mesure": m, "alerte": envoye}


# Lot 85 (08/10/2026) — purge d'une base OBSOLÈTE du cluster pour libérer des collections (ex. « smartsystems »,
# créée par erreur lors du passage de SAWALI sur Render). Les bases en service sont PROTÉGÉES : jamais supprimables.
BASES_PROTEGEES = {"sawali", "albarka", "sawali_dentalcare", "telecom_boutique", "site_meetafrican",
                   "admin", "local", "config"}


def base_protegee(nom: str, base_courante: str, autres: Optional[List[str]] = None) -> bool:
    """Vrai si la base ne doit jamais être supprimée (base de SAWALI, bases des plateformes, bases internes)."""
    return nom in BASES_PROTEGEES or nom == base_courante or nom in set(autres or [])


# Lot 113 — fonctions partagées avec « 🧹 Libérer l'Espace » (routes/liberer_espace.py). Elles reprennent À L'IDENTIQUE
# le code des routes du lot 85 ci-dessous, qui les appellent désormais (aucun changement de comportement).
async def bases_protegees_reglage(db) -> List[str]:
    """Bases protégées en plus de la liste fixe (réglage atlas_bases_protegees, séparées par des virgules)."""
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "atlas_bases_protegees": 1}) or {}
    return [x.strip() for x in str(s.get("atlas_bases_protegees") or "").split(",") if x.strip()]


async def vider_base(client, nom: str) -> tuple:
    """Supprime les collections de la base une à une → (nombre supprimées, [refus « collection (code) »]).
    Lot 85.1 : le compte Atlas de SAWALI n'a pas le droit « dropDatabase » (constaté le 08/10/2026) mais peut
    supprimer les collections une à une ; une base sans collection disparaît d'elle-même.
    ATTENTION : aucun contrôle de protection ici — l'appelant DOIT avoir vérifié base_protegee() avant."""
    noms = await client[nom].list_collection_names()
    supprimees, refusees = 0, []
    for c in noms:
        try:
            await client[nom].drop_collection(c)
            supprimees += 1
        except Exception as exc:  # noqa: BLE001 — on continue avec les autres, refus listés à la fin
            refusees.append(f"{c} ({getattr(exc, 'code', None) or type(exc).__name__})")
    return supprimees, refusees


async def noter_purge(db, nom: str, collections: int, par: Optional[str]) -> None:
    """Trace de la purge d'une base dans db.settings {_id: "quota_atlas"} (aucune nouvelle collection)."""
    await db.settings.update_one({"_id": DOC_ID}, {"$push": {"purges": {
        "base": nom, "collections": collections, "par": par, "le": datetime.now(timezone.utc).isoformat()}}},
        upsert=True)


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

    @api.get("/admin/atlas/secours", tags=["Admin — Santé"])
    async def quota_secours(recente: bool = False, user: dict = Depends(get_current_user)):
        """Lot 122 — taille du cluster de COPIE (Clusterbkp) par rapport à sa limite (512 Mo en offre gratuite).
        `recente=true` : la dernière mesure si elle a moins de 15 minutes. L'adresse du cluster n'est jamais renvoyée."""
        if user.get("role") not in ("admin", "super_admin") and user.get("tracked_role") != "Administrateur":
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs")
        if recente:
            m = (await db.settings.find_one({"_id": DOC_ID}) or {}).get("derniere_mesure_secours") or {}
            try:
                if (datetime.now(timezone.utc) - datetime.fromisoformat(m.get("le"))).total_seconds() < 15 * 60:
                    return m
            except (TypeError, ValueError):
                pass
        return await mesurer_secours(db)


    def _admin_strict(user: dict) -> None:
        """Lot 85 : contenu et suppression d'une base — administrateur SAWALI seulement."""
        if user.get("role") not in ("admin", "super_admin"):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")

    async def _protegees() -> List[str]:
        """Bases protégées en plus de la liste fixe (réglage atlas_bases_protegees, séparées par des virgules)."""
        return await bases_protegees_reglage(db)

    @api.get("/admin/atlas/bases/{nom}", tags=["Admin — Santé"])
    async def contenu_base(nom: str, user: dict = Depends(get_current_user)):
        """Lot 85 : collections d'une base avec leur nombre de documents (pour juger si elle est encore utile)."""
        _admin_strict(user)
        if nom in BASES_IGNOREES or nom not in await client.list_database_names():
            raise HTTPException(status_code=404, detail="Base introuvable")
        lignes, total = [], 0
        for c in sorted(await client[nom].list_collection_names()):
            try:
                n = await client[nom][c].estimated_document_count()
            except Exception:  # noqa: BLE001
                n = None
            total += n or 0
            lignes.append({"nom": c, "documents": n})
        lignes.sort(key=lambda x: -(x["documents"] or 0))
        return {"base": nom, "collections": lignes, "documents": total,
                "protegee": base_protegee(nom, base_courante, await _protegees())}

    @api.post("/admin/atlas/bases/{nom}/supprimer", tags=["Admin — Santé"])
    async def supprimer_base(nom: str, corps: dict, user: dict = Depends(get_current_user)):
        """Lot 85 : supprime une base OBSOLÈTE (le nom doit être retapé ; bases en service refusées)."""
        _admin_strict(user)
        if base_protegee(nom, base_courante, await _protegees()):
            raise HTTPException(status_code=409, detail=f"La base « {nom} » est en service : suppression refusée")
        if (corps or {}).get("confirmation") != nom:
            raise HTTPException(status_code=422, detail="Retapez exactement le nom de la base pour confirmer")
        if nom not in await client.list_database_names():
            raise HTTPException(status_code=404, detail="Base introuvable")
        # Lot 85.1 : suppression collection par collection (pas de droit « dropDatabase ») — lot 113 : fonction partagée
        supprimees, refusees = await vider_base(client, nom)
        nb = supprimees
        logger.warning("[quota_atlas] base %s purgée par %s : %s collections supprimées, %s refusées",
                       nom, user.get("email"), supprimees, len(refusees))
        if refusees and not supprimees:
            raise HTTPException(status_code=403, detail=(
                "Le compte Atlas de SAWALI n'a pas le droit de supprimer ces collections. Supprimez la base depuis "
                f"le site MongoDB Atlas (Browse Collections → {nom} → Drop Database)."))
        await noter_purge(db, nom, nb, user.get("email"))
        return {"ok": True, "base": nom, "collections_liberees": nb, "refusees": refusees,
                "mesure": await mesurer(db, client, base_courante)}
