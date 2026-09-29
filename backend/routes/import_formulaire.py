"""Lot 33 — « Créer depuis un document » (Formulaires et Sondages WhatsApp).

  POST /api/me/form-imports        fichiers[] + cible (formulaire | sondage)
                                    + avec_donnees (formulaire : reprendre les lignes des tableaux)
       → 202 {id} : l'analyse IA tourne en arrière-plan (elle peut prendre une minute) ;
  GET  /api/me/form-imports/{id}   suivi : en_cours → termine (objet_id, compte_rendu)
                                            ou erreur (message clair).

À la fin, le formulaire (collection `forms`) ou le sondage (`wa_surveys`) est créé en
BROUILLON, exactement comme par « Nouveau formulaire » / « Nouveau sondage » (même
rattachement au client, même numérotation FORM-<code>-NNNN), puis ouvert dans
l'éditeur habituel. Les fichiers déposés ne sont PAS conservés : seuls leurs noms le
sont, dans le suivi (collection `form_imports`) et sur le brouillon créé.
Accès : tout utilisateur connecté, comme la création de formulaires et de sondages.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional

from fastapi import Depends, File, Form, HTTPException, UploadFile

import import_formulaire as imp
from routes.wa_surveys import normalize_questions

logger = logging.getLogger("sawali.import_formulaire")

MAX_OCTETS_FICHIER = 20 * 1024 * 1024       # 20 Mo par fichier
MAX_OCTETS_TOTAL = 60 * 1024 * 1024         # 60 Mo par dépôt
DUREE_MAX = timedelta(minutes=10)           # au-delà, une analyse « en cours » est considérée perdue
TAG = "Formulaires"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def attach_import_formulaire_routes(*, api, db, get_current_user, uuid_fn: Callable[[], str],
                                    next_form_number, slugify_code, is_admin_like) -> None:
    # Références fortes vers les tâches de fond (asyncio ne garde qu'une référence faible).
    taches: set = set()

    def _scope_formulaire(user: dict) -> str:
        """Même rattachement que POST /me/forms."""
        return (user.get("client_id") or user.get("id")) if user.get("role") != "admin" else user["id"]

    def _scope_sondage(user: dict) -> str:
        """Même rattachement que POST /me/wa-surveys."""
        return user.get("parent_client_id") or user.get("client_id") or user["id"]

    async def _titre_libre(client_id: str, titre: str) -> str:
        """Titre unique chez ce client (règle de POST /me/forms) : « … (import 2) » si déjà pris."""
        candidat, n = titre, 1
        while await db.forms.find_one({"client_id": client_id,
                                       "title": {"$regex": f"^\\s*{re.escape(candidat)}\\s*$", "$options": "i"}},
                                      {"_id": 1}):
            n += 1
            candidat = f"{titre} (import {n})" if n > 2 else f"{titre} (import)"
        return candidat

    async def _creer_formulaire(user: dict, structure: dict, origine: dict) -> dict:
        client_scope = _scope_formulaire(user)
        client = await db.users.find_one({"id": client_scope}, {"_id": 0, "client_code": 1, "company": 1, "full_name": 1})
        code = (client or {}).get("client_code") or slugify_code((client or {}).get("company")
                                                                 or (client or {}).get("full_name") or "X")
        numero = await next_form_number(code)
        doc = {
            "id": uuid_fn(), "client_id": client_scope, "client_code": code, "number": f"FORM-{code}-{numero:04d}",
            "title": await _titre_libre(client_scope, structure["title"]),
            "description": structure.get("description") or "", "is_public": False, "category_id": None,
            "access_client_ids": [], "pages": structure["pages"],
            "created_by_id": user["id"], "created_by_label": user.get("full_name") or user.get("email"),
            "created_at": _now(), "updated_at": _now(), "uses_count": 0,
            "imported_from_document": origine,
        }
        await db.forms.insert_one(doc.copy())
        return doc

    async def _creer_sondage(user: dict, structure: dict, origine: dict) -> dict:
        doc = {
            "id": uuid_fn(), "title": structure["title"], "description": structure.get("description") or "",
            "thank_you": "", "questions": normalize_questions(structure["questions"], uuid_fn),
            "status": "draft", "anonymous": False, "closes_at": None, "message_text": None,
            "client_id": _scope_sondage(user),
            "created_by_id": user["id"], "created_by_label": user.get("full_name") or user.get("email"),
            "created_at": _now(), "updated_at": _now(),
            "imported_from_document": origine,
        }
        await db.wa_surveys.insert_one(doc.copy())
        return doc

    async def _executer(job_id: str, user: dict, fichiers: List[tuple], cible: str, avec_donnees: bool) -> None:
        try:
            res = await imp.analyser(fichiers, cible, None, uuid_fn, avec_donnees=avec_donnees)
            origine = {"fichiers": [n for n, _ in fichiers], "import_id": job_id, "le": _now()}
            creer = _creer_formulaire if cible == "formulaire" else _creer_sondage
            doc = await creer(user, res["structure"], origine)
            await db.form_imports.update_one({"id": job_id}, {"$set": {
                "statut": "termine", "fini_le": _now(), "objet_id": doc["id"], "titre": doc["title"],
                "compte_rendu": res["compte_rendu"], "usage": res["usage"]}})
        except ValueError as exc:
            await db.form_imports.update_one({"id": job_id}, {"$set": {
                "statut": "erreur", "fini_le": _now(), "erreur": str(exc)}})
        except Exception as exc:  # noqa: BLE001
            logger.exception("[import-formulaire] échec %s", job_id)
            await db.form_imports.update_one({"id": job_id}, {"$set": {
                "statut": "erreur", "fini_le": _now(),
                "erreur": f"Analyse impossible pour le moment ({str(exc)[:150]}). Réessayez dans quelques minutes."}})

    @api.post("/me/form-imports", tags=[TAG], status_code=202)
    async def importer_document(
        fichiers: List[UploadFile] = File(...),
        cible: str = Form("formulaire"),
        avec_donnees: bool = Form(False),
        user: dict = Depends(get_current_user),
    ):
        if cible not in ("formulaire", "sondage"):
            raise HTTPException(status_code=400, detail="Cible inconnue (formulaire ou sondage)")
        fichiers = [f for f in fichiers if f and f.filename]
        if not fichiers:
            raise HTTPException(status_code=400, detail="Aucun fichier déposé")
        if len(fichiers) > imp.MAX_FICHIERS:
            raise HTTPException(status_code=400, detail=f"{len(fichiers)} fichiers : {imp.MAX_FICHIERS} au maximum")
        # Contrôles avant toute lecture coûteuse et tout appel IA.
        contenus, total = [], 0
        for f in fichiers:
            try:
                imp.verifier_fichier(f.filename)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            data = await f.read()
            if len(data) > MAX_OCTETS_FICHIER:
                raise HTTPException(status_code=413, detail=f"« {f.filename} » trop volumineux (max 20 Mo)")
            total += len(data)
            if total > MAX_OCTETS_TOTAL:
                raise HTTPException(status_code=413, detail="Dépôt trop volumineux (60 Mo au total)")
            contenus.append((f.filename, data))
        # Une analyse à la fois par utilisateur (coût IA maîtrisé).
        limite = (datetime.now(timezone.utc) - DUREE_MAX).isoformat()
        if await db.form_imports.find_one({"user_id": user["id"], "statut": "en_cours", "cree_le": {"$gt": limite}},
                                          {"_id": 1}):
            raise HTTPException(status_code=409, detail="Une analyse de document est déjà en cours, patientez.")
        avec_donnees = bool(avec_donnees) and cible == "formulaire"      # pas de tableau dans un sondage
        job = {"id": uuid_fn(), "user_id": user["id"], "cible": cible, "avec_donnees": avec_donnees,
               "fichiers": [n for n, _ in contenus], "statut": "en_cours", "cree_le": _now()}
        await db.form_imports.insert_one(job.copy())
        tache = asyncio.create_task(_executer(job["id"], user, contenus, cible, avec_donnees))
        taches.add(tache)
        tache.add_done_callback(taches.discard)
        return {"id": job["id"], "statut": "en_cours"}

    @api.get("/me/form-imports/{job_id}", tags=[TAG])
    async def suivi_import(job_id: str, user: dict = Depends(get_current_user)):
        job = await db.form_imports.find_one({"id": job_id}, {"_id": 0})
        if not job or (job["user_id"] != user["id"] and not is_admin_like(user)):
            raise HTTPException(status_code=404, detail="Analyse introuvable")
        # Serveur redémarré pendant l'analyse : la tâche est perdue, on le dit.
        if job["statut"] == "en_cours" and job["cree_le"] < (datetime.now(timezone.utc) - DUREE_MAX).isoformat():
            job.update(statut="erreur", erreur="L'analyse a été interrompue. Déposez à nouveau le document.")
            await db.form_imports.update_one({"id": job_id}, {"$set": {"statut": "erreur", "erreur": job["erreur"]}})
        if not is_admin_like(user):
            job.pop("usage", None)                   # modèle et coût : administration seulement
        return job
