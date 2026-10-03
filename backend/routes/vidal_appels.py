"""Lot 56 — Point de passage UNIQUE des appels VIDAL de la sécurisation v2.

Porté depuis Ster (app/utils/vidal_client.py, fonction `appeler_vidal`),
mais SANS réécrire de client HTTP : l'appel lui-même est fait par le client
déjà en place dans SAWALI (`routes.vidal._vidal_call` : identifiants
app_id/app_key en paramètres, corps XML en text/xml, mode webhook éventuel).
Ce module ajoute autour de lui, pour tous les endpoints de la sécurisation
v2 (routes/vidal_securisation.py, routes/vidal_patients.py,
routes/vidal_validation.py) :

  1. La configuration prête à l'emploi (`config_prete`) : accès du
     client/établissement au module VIDAL, module actif, identifiants,
     quota journalier — mêmes fonctions que le reste du module VIDAL.
  2. Le MODE « VALIDATION VIDAL » (décision de l'utilisateur dans Ster :
     « vrais appels, pas de sandbox, avec des patients fictifs ; aucune
     donnée de vrai patient n'est transmise à VIDAL ») :
       - réglage PAR ÉTABLISSEMENT (collection `vidal_validation_config`),
         ACTIVÉ PAR DÉFAUT tant qu'un gestionnaire ne l'a pas désactivé ;
       - tous les appels partent alors sur l'URL et les identifiants de
         PRODUCTION configurés dans AdminSettings ;
       - GARDE-FOU : un corps XML contenant un bloc <patient> (sécurisation,
         rapport HTML, calculateurs rénaux) n'est envoyé QUE pour un
         patient marqué fictif (`est_fictif`) appartenant à l'utilisateur ;
         sinon HTTP 403 et AUCUNE requête ne part ;
       - chaque appel est inscrit au JOURNAL DE VALIDATION
         (`vidal_journal_validation`), identifiants masqués.
  3. La trace « Suivi des logs » déjà existante (routes/vidal_audit.py).

Comme dans Ster, cette fonction ne lève jamais d'exception sur une erreur
VIDAL : elle renvoie {"raw": ..., "_erreur": {"statut", "message"}} et c'est
l'appelant qui décide. Elle lève seulement le 403 du garde-fou.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException

from vidal_v2 import journal_validation as jv

logger = logging.getLogger("sawali.vidal.appels")

MESSAGE_PATIENT_NON_FICTIF = "Mode validation VIDAL : seuls les patients fictifs peuvent être envoyés à VIDAL."

# Rôles autorisés à GÉRER le module pour leur établissement (activer /
# désactiver le mode validation, paramétrer les groupes du DFG). Les autres
# rôles ayant accès à VIDAL (médecin, pharmacien...) l'utilisent seulement.
ROLES_GESTIONNAIRES = ("admin", "superviseur", "client")

# En-têtes envoyés par `routes.vidal._vidal_call` (recopiés ici uniquement
# pour les afficher dans le journal de validation, jamais pour l'appel).
_ENTETES_GET = {"Accept": "application/atom+xml, application/xml, application/json;q=0.5"}
_ENTETES_POST_XML = {"Accept": "application/atom+xml, application/xml", "Content-Type": "text/xml; charset=utf-8"}

# Création des index MongoDB une seule fois par processus (voir `assurer_index`).
_index_ok = {"fait": False}


def est_gestionnaire(user: Dict[str, Any]) -> bool:
    return (user or {}).get("role") in ROLES_GESTIONNAIRES


async def assurer_index(db) -> None:
    """Index des collections du lot 56 — créés au premier appel, erreurs ignorées (jamais bloquant)."""
    if _index_ok["fait"]:
        return
    _index_ok["fait"] = True
    try:
        await db.vidal_validation_config.create_index("scope_uid", unique=True)
        await db.vidal_config_groupes_dfg.create_index("scope_uid", unique=True)
        await db.vidal_journal_validation.create_index([("scope_uid", 1), ("date_utc", -1)])
        await db.vidal_journal_validation.create_index([("scope_uid", 1), ("numero", 1)])
        await db.vidal_historique_profil_clinique.create_index([("patient_id", 1), ("date", 1)])
        await db.vidal_prescription_audit.create_index([("patient_id", 1), ("created_at", -1)])
        await db.vidal_patients.create_index([("user_id", 1), ("est_fictif", 1), ("code_fictif", 1)])
    except Exception:  # noqa: BLE001
        logger.warning("[vidal_appels] création des index impossible", exc_info=True)


# ---------------------------------------------------------------------------
# Établissement (portée) et mode validation
# ---------------------------------------------------------------------------

async def portee_etablissement(db, user: Dict[str, Any]) -> str:
    """Identifiant de l'établissement (client « tenant ») de l'utilisateur.

    Même règle que le reste du module VIDAL (`routes.vidal._resolve_tenant_vidal`) :
    un médecin, pharmacien, modérateur... dépend du compte client qui l'a
    créé ; un administrateur de la plateforme est sa propre portée."""
    if user.get("role") in ("admin", "superviseur"):
        return user["id"]
    from routes.vidal import _resolve_tenant_vidal
    return (await _resolve_tenant_vidal(db, user))["scope_uid"]


async def mode_validation_actif(db, scope_uid: Optional[str]) -> bool:
    """Vrai sauf désactivation explicite enregistrée pour cet établissement (vrai par prudence sans établissement)."""
    if not scope_uid:
        return True
    doc = await db.vidal_validation_config.find_one({"scope_uid": scope_uid}, {"_id": 0, "mode_validation": 1})
    return (doc or {}).get("mode_validation", True) is not False


async def patient_fictif(db, user: Dict[str, Any], patient_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Patient de `vidal_patients` s'il est marqué fictif ET appartient à cet utilisateur, sinon None."""
    if not patient_id:
        return None
    return await db.vidal_patients.find_one(
        {"id": patient_id, "user_id": user["id"], "est_fictif": True}, {"_id": 0},
    )


async def _configuration_production(db, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Remplace URL et identifiants par ceux de PRODUCTION (mode validation)."""
    from routes.vidal import _load_config
    production = await _load_config(db, tenant_mode_override="production")
    if not production["app_id"] or not production["app_key"]:
        raise HTTPException(status_code=503, detail="Mode validation VIDAL : identifiants VIDAL de production non configurés (AdminSettings → VIDAL).")
    return {**cfg, **{k: production[k] for k in ("mode", "base_url", "app_id", "app_key")}}


async def config_prete(db, user: Dict[str, Any], *, quota: bool = True) -> Dict[str, Any]:
    """Configuration VIDAL utilisable par un endpoint de la sécurisation v2.

    Lève 403 (module non activé pour l'établissement), 503 (module désactivé
    ou identifiants absents) ou 429 (quota journalier atteint), exactement
    comme les autres pages VIDAL. Ajoute `validation` et `scope_uid` à cfg."""
    from routes.vidal import _ensure_active, _ensure_tenant_can_access, _quota_check_and_increment
    cfg = await _ensure_tenant_can_access(db, user)
    scope_uid = await portee_etablissement(db, user)
    validation = await mode_validation_actif(db, scope_uid)
    if validation:
        if not cfg["enabled"]:
            raise HTTPException(status_code=503, detail="Module VIDAL désactivé (AdminSettings).")
        cfg = await _configuration_production(db, cfg)
    else:
        _ensure_active(cfg)
    cfg = {**cfg, "validation": validation, "scope_uid": scope_uid}
    if quota:
        await _quota_check_and_increment(db, user["id"], cfg)
    return cfg


# ---------------------------------------------------------------------------
# Journal de validation
# ---------------------------------------------------------------------------

async def _journaliser_validation(
    db, *, cfg: Dict[str, Any], user: Dict[str, Any], methode: str, chemin: str, params: Dict[str, Any],
    corps: Optional[str], statut: int, reponse: Optional[str], duree_ms: int, patient: Optional[Dict[str, Any]],
    erreur: Optional[str] = None,
) -> None:
    """Une entrée COMPLÈTE par appel réel (voir vidal_v2/journal_validation.py).

    Les secrets ne sont jamais stockés : masqués dans l'URL et retirés par
    sécurité de tout texte conservé. Ne fait jamais échouer l'appel."""
    try:
        from vidal_v2.historique_clinique import resume_gravites
        from vidal_v2.xml_securisation import parser_reponse_alertes

        secrets = [cfg.get("app_id") or "", cfg.get("app_key") or ""]
        type_ = jv.type_appel(methode, chemin)
        gravites = (resume_gravites(parser_reponse_alertes(reponse).get("alerts"))
                    if type_ == "Sécurisation (alertes structurées)" and 0 < statut < 400 else None)
        reponse_stockee, tronquee, taille = jv.tronquer_reponse(jv.masquer_secrets(reponse, secrets))
        date_utc, date_locale = jv.horodatages()
        compteur = await db.vidal_compteurs.find_one_and_update(
            {"_id": "journal_validation"}, {"$inc": {"valeur": 1}}, upsert=True, return_document=True,
        )
        entetes = _ENTETES_POST_XML if (methode == "POST" and corps is not None) else _ENTETES_GET
        await db.vidal_journal_validation.insert_one({
            "numero": int((compteur or {}).get("valeur", 0)), "scope_uid": cfg.get("scope_uid"),
            "user_id": user.get("id"), "login": user.get("email"),
            "date_utc": date_utc, "date_locale": date_locale, "methode": methode,
            "url": jv.url_masquee(f"{cfg['base_url']}{chemin}", {**(params or {}), "app_id": cfg.get("app_id"), "app_key": cfg.get("app_key")}),
            "entetes": entetes, "corps": jv.masquer_secrets(corps, secrets),
            "statut_http": statut, "reponse": reponse_stockee, "reponse_tronquee": tronquee, "taille_reponse": taille,
            "duree_ms": duree_ms, "type_appel": type_,
            "patient_id": (patient or {}).get("id"), "patient_libelle": (patient or {}).get("name"),
            "profil": (patient or {}).get("profil_fictif"), "resume_gravites": gravites,
            "observations_auto": jv.observations_automatiques(
                statut=statut, reponse=reponse, duree_ms=duree_ms, resume_gravites=gravites,
                alertes_attendues=(patient or {}).get("alertes_attendues_validation") if type_.startswith("Sécurisation") else None,
                erreur=jv.masquer_secrets(erreur, secrets),
            ),
            "observation_manuelle": "",
        })
    except Exception:  # noqa: BLE001
        logger.exception("[vidal_appels] journalisation de validation impossible")


# ---------------------------------------------------------------------------
# Appel VIDAL (garde-fou central du mode validation)
# ---------------------------------------------------------------------------

async def appeler_vidal(
    db, cfg: Dict[str, Any], user: Dict[str, Any], method: str, chemin: str,
    params: Optional[Dict[str, Any]] = None, corps_xml: Optional[str] = None, patient_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Un appel à VIDAL -> {"raw": texte} ou {"raw": texte|None, "_erreur": {"statut", "message"}}.

    `patient_id` (optionnel) : patient de `vidal_patients` concerné par le
    corps XML — indispensable en mode validation pour prouver qu'il est
    fictif. Il n'est JAMAIS transmis à VIDAL (seul `corps_xml` part)."""
    from routes.vidal import _vidal_call
    from routes.vidal_audit import log_call

    methode = method.upper()
    patient = None
    if cfg.get("validation"):
        if corps_xml and "<patient" in corps_xml:
            patient = await patient_fictif(db, user, patient_id)
            if not patient:
                # Rien n'est envoyé : ni requête, ni entrée de journal.
                raise HTTPException(status_code=403, detail=MESSAGE_PATIENT_NON_FICTIF)
        elif patient_id:
            patient = await patient_fictif(db, user, patient_id)

    debut = time.monotonic()
    try:
        data = await _vidal_call(cfg, methode, chemin, params=params, body=corps_xml)
    except HTTPException as exc:  # ex. relais webhook en échec
        data = {"raw": None, "_error": {"status": exc.status_code, "message": str(exc.detail)}}
    duree_ms = int((time.monotonic() - debut) * 1000)

    erreur = (data or {}).get("_error") if isinstance(data, dict) else None
    statut = int((erreur or {}).get("status", 200) if isinstance(erreur, dict) else 200)
    # Statut 0 = VIDAL injoignable : le texte « [Erreur réseau VIDAL] » n'est pas une réponse de VIDAL.
    raw = None if statut == 0 else (data or {}).get("raw") if isinstance(data, dict) else None
    message = (erreur or {}).get("message") if isinstance(erreur, dict) else None

    # Trace « Suivi des logs » existante (tâche de fond, jamais bloquante).
    asyncio.create_task(log_call(
        db, mode=cfg.get("mode", "?"), method=methode, path=chemin,
        status="ok" if not erreur else ("exception" if statut == 0 else "error"),
        elapsed_ms=duree_ms, user_email=user.get("email"), error=message,
    ))
    if cfg.get("validation"):
        await _journaliser_validation(
            db, cfg=cfg, user=user, methode=methode, chemin=chemin, params=params or {}, corps=corps_xml,
            statut=statut, reponse=raw, duree_ms=duree_ms, patient=patient, erreur=message,
        )
    if erreur:
        return {"raw": raw, "_erreur": {"statut": statut, "message": message or f"VIDAL a répondu {statut}"}}
    return {"raw": raw}


def maintenant() -> datetime:
    return datetime.now(timezone.utc)
