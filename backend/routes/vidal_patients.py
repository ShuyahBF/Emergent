"""Historique patient — Sécurisation VIDAL (portage site-meetafrican, lot 11).

Porte le comportement documenté sur la capture de référence "Sécuriser une
prescription" : *"Le manuel VIDAL impose de transmettre, en plus de la
nouvelle prescription, les traitements en cours du patient. Si le patient
est enregistré (bouton « Enregistrer » en haut de page), cette liste sera
préremplie automatiquement à sa prochaine consultation"*.

Un patient est enregistré PAR médecin/pharmacien (scope `user_id`) — jamais
partagé entre praticiens. Le nom est un usage interne uniquement (jamais
transmis à VIDAL, voir `vidal_securisation.py`) ; le n° WhatsApp, optionnel,
sert à la fois de clé de dédoublonnage et à l'envoi de l'ordonnance
(`vidal_ordonnance.py`).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    doc = dict(doc)
    doc.pop("_id", None)
    doc.pop("user_id", None)  # implicite (scope de la requête) — jamais renvoyé au frontend
    return doc


def attach_vidal_patients_routes(*, api, db, get_current_user):
    from fastapi import Body, Depends, HTTPException, Query
    from pydantic import BaseModel

    class PatientProfilePayload(BaseModel):
        dateOfBirth: Optional[str] = None
        gender: Optional[str] = None
        height: Optional[str] = None
        weight: Optional[str] = None
        creatinine: Optional[str] = None
        hepaticInsufficiency: Optional[str] = None
        allergies: List[Dict[str, Any]] = []
        pathologies: List[Dict[str, Any]] = []
        molecules: List[Dict[str, Any]] = []

    class SavePatientPayload(BaseModel):
        patient_id: Optional[str] = None
        whatsapp_number: Optional[str] = None
        name: Optional[str] = None
        patient: PatientProfilePayload = PatientProfilePayload()

    @api.post("/vidal/patients", tags=["VIDAL"])
    async def save_patient(payload: SavePatientPayload = Body(...), user: dict = Depends(get_current_user)):
        name = (payload.name or "").strip()
        whatsapp = (payload.whatsapp_number or "").strip()
        if not name and not whatsapp:
            raise HTTPException(status_code=400, detail="Nom du patient ou n° WhatsApp requis pour enregistrer.")
        now = _now()
        update_fields = {
            "name": name or None,
            "whatsapp_number": whatsapp or None,
            "profile": payload.patient.model_dump(),
            "updated_at": now,
        }
        existing = None
        if payload.patient_id:
            existing = await db.vidal_patients.find_one({"id": payload.patient_id, "user_id": user["id"]})
            if not existing:
                raise HTTPException(status_code=404, detail="Patient introuvable")
        elif whatsapp:
            # Dédoublonnage par n° WhatsApp au sein des patients DU MÊME praticien.
            existing = await db.vidal_patients.find_one({"user_id": user["id"], "whatsapp_number": whatsapp})
        if existing:
            await db.vidal_patients.update_one({"id": existing["id"]}, {"$set": update_fields})
            pid = existing["id"]
        else:
            pid = str(uuid.uuid4())
            await db.vidal_patients.insert_one({
                "id": pid, "user_id": user["id"], "current_treatments": [],
                "created_at": now, "last_consultation_at": None,
                **update_fields,
            })
        doc = await db.vidal_patients.find_one({"id": pid}, {"_id": 0})
        return _serialize(doc)

    @api.get("/vidal/patients", tags=["VIDAL"])
    async def search_patients(
        q: Optional[str] = Query(None, min_length=1),
        user: dict = Depends(get_current_user),
    ):
        """Liste des patients enregistrés par CE praticien — alimente le
        bouton "Historique" (recherche par nom ou n° WhatsApp)."""
        filt: Dict[str, Any] = {"user_id": user["id"]}
        if q:
            filt["$or"] = [
                {"name": {"$regex": q, "$options": "i"}},
                {"whatsapp_number": {"$regex": q, "$options": "i"}},
            ]
        cursor = db.vidal_patients.find(filt, {"_id": 0}).sort("updated_at", -1).limit(50)
        return {"results": [_serialize(d) for d in await cursor.to_list(length=50)]}

    @api.get("/vidal/patients/{patient_id}", tags=["VIDAL"])
    async def get_patient(patient_id: str, user: dict = Depends(get_current_user)):
        doc = await db.vidal_patients.find_one({"id": patient_id, "user_id": user["id"]}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Patient introuvable")
        return _serialize(doc)


async def record_consultation(db, *, patient_id: str, user_id: str, new_prescription_lines: List[Dict[str, Any]]) -> None:
    """Appelé par `vidal_securisation.py` après une analyse réussie : les
    lignes de LA NOUVELLE prescription deviennent les "traitements en cours"
    présentés au praticien à la prochaine consultation de ce patient (le
    manuel VIDAL considère un traitement fraîchement prescrit comme non
    terminé). Best-effort — n'échoue jamais l'analyse elle-même."""
    try:
        await db.vidal_patients.update_one(
            {"id": patient_id, "user_id": user_id},
            {"$set": {"current_treatments": new_prescription_lines, "last_consultation_at": _now()}},
        )
    except Exception:  # noqa: BLE001
        pass
