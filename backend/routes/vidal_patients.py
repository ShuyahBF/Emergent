"""Historique patient — Sécurisation VIDAL (portage site-meetafrican, lot 11 ;
profil clinique et historique clinique ajoutés au lot 56 depuis Ster).

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

Lot 56 (Sécurisation VIDAL v2, portée depuis Ster) :
  - PROFIL CLINIQUE : sous-document `profil_clinique` du patient (date de
    naissance, sexe, poids/taille datés, fonction rénale complète,
    grossesse/allaitement, insuffisance hépatique, allergies, molécules,
    pathologies, groupe de référence du DFG). L'ancien sous-document
    `profile` reste lu pour les patients enregistrés avant ce lot.
  - HISTORIQUE CLINIQUE : chaque enregistrement du profil ajoute une
    VERSION datée (`vidal_historique_profil_clinique`) si au moins un champ
    a changé — jamais d'écrasement ; chaque sécurisation garde son
    instantané (`vidal_prescription_audit`, voir vidal_securisation.py).
  - Lecture : GET /vidal/patients/{id}/historique-clinique, détail d'une
    sécurisation, export PDF.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    doc = dict(doc)
    doc.pop("_id", None)
    doc.pop("user_id", None)  # implicite (scope de la requête) — jamais renvoyé au frontend
    return doc


# 2026-09-15 fix — Modèles Pydantic définis au scope MODULE (et pas dans la
# closure `attach_vidal_patients_routes`) : combiné à `from __future__ import
# annotations`, une classe locale devient une ForwardRef que Pydantic v2 ne
# peut résoudre, d'où le 500 « PydanticUserError » sur POST /vidal/patients.
class PatientProfilePayload(BaseModel):
    """Ancien profil (avant le lot 56) — toujours accepté pour compatibilité."""
    dateOfBirth: Optional[str] = None
    gender: Optional[str] = None
    height: Optional[str] = None
    weight: Optional[str] = None
    creatinine: Optional[str] = None
    hepaticInsufficiency: Optional[str] = None
    allergies: List[Dict[str, Any]] = []
    pathologies: List[Dict[str, Any]] = []
    molecules: List[Dict[str, Any]] = []


class ProfilCliniqueVidal(BaseModel):
    """Profil clinique VIDAL (lot 56, repris de `ProfilCliniqueVidal` de Ster).

    Mise à jour PARTIELLE : un champ absent du corps n'est pas touché ; les
    listes vides sont enregistrées (pour pouvoir RETIRER une allergie) ;
    un `null` explicite efface la valeur pour les champs effaçables (voir
    `_CHAMPS_PROFIL_EFFACABLES`)."""
    date_naissance: Optional[date] = None
    # MALE / FEMALE / UNKNOWN (indéterminé) ; vide = non renseigné.
    sexe: Optional[Literal["MALE", "FEMALE", "UNKNOWN"]] = None
    poids_kg: Optional[float] = None
    taille_cm: Optional[float] = None
    date_saisie_poids_taille: Optional[date] = None
    insuffisance_hepatique: Optional[Literal["NONE", "MODERATE", "SEVERE"]] = None
    derniere_creatininemie_umol_l: Optional[float] = None
    clairance_creatinine_ml_min: Optional[float] = None
    dfg_ml_min_173: Optional[float] = None
    date_bilan_renal: Optional[date] = None
    date_dernieres_regles: Optional[date] = None
    allaitement: Optional[Literal["NONE", "LESS_THAN_ONE_MONTH", "MORE_THAN_ONE_MONTH", "ALL"]] = None
    date_debut_allaitement: Optional[date] = None
    allergies: List[Dict[str, Any]] = Field(default_factory=list)
    pathologies: List[Dict[str, Any]] = Field(default_factory=list)
    molecules_a_eviter: List[Dict[str, Any]] = Field(default_factory=list)
    # § aide d'interprétation LOCALE (identifiant d'un groupe de /vidal/groupes-dfg), jamais transmise à VIDAL.
    groupe_reference_dfg: Optional[str] = None


class SavePatientPayload(BaseModel):
    patient_id: Optional[str] = None
    whatsapp_number: Optional[str] = None
    name: Optional[str] = None
    patient: PatientProfilePayload = PatientProfilePayload()
    # Lot 56 — profil clinique v2 (facultatif) : s'il est fourni, il est
    # enregistré et une version d'historique est créée si quelque chose a changé.
    profil_clinique: Optional[ProfilCliniqueVidal] = None


# Champs qu'un `null` explicite EFFACE (grossesse terminée, allaitement arrêté,
# bilan rénal invalidé, sexe ou date de naissance corrigés...) ; pour les
# autres, un null est ignoré (comportement de Ster).
_CHAMPS_PROFIL_EFFACABLES = (
    "date_naissance", "sexe", "poids_kg", "taille_cm", "date_saisie_poids_taille", "insuffisance_hepatique",
    "date_dernieres_regles", "allaitement", "date_debut_allaitement",
    "derniere_creatininemie_umol_l", "clairance_creatinine_ml_min", "dfg_ml_min_173", "date_bilan_renal",
    "groupe_reference_dfg",
)
_ORIGINES_PROFIL = {"securisation", "posologie", "fiche", "validation_vidal"}


def _valeur_stockee(valeur: Any) -> Any:
    """Dates en texte AAAA-MM-JJ (lisibles dans MongoDB et en JSON), le reste tel quel."""
    return valeur.isoformat() if isinstance(valeur, date) else valeur


def maj_profil_depuis_modele(profil: ProfilCliniqueVidal) -> Dict[str, Any]:
    """Champs à écrire dans `profil_clinique` (mise à jour partielle)."""
    maj: Dict[str, Any] = {}
    for nom in profil.model_fields_set:
        valeur = getattr(profil, nom)
        if valeur is None and nom not in _CHAMPS_PROFIL_EFFACABLES:
            continue
        maj[nom] = _valeur_stockee(valeur)
    return maj


def profil_depuis_ancien_format(ancien: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Ancien `profile` (avant le lot 56) -> `profil_clinique` (aucune valeur inventée)."""
    ancien = ancien or {}

    def nombre(v):
        try:
            return float(str(v).replace(",", ".")) if v not in (None, "") else None
        except ValueError:
            return None

    sexe = ancien.get("gender") if ancien.get("gender") in ("MALE", "FEMALE", "UNKNOWN") else None
    return {
        "date_naissance": ancien.get("dateOfBirth") or None, "sexe": sexe,
        "poids_kg": nombre(ancien.get("weight")), "taille_cm": nombre(ancien.get("height")),
        "derniere_creatininemie_umol_l": nombre(ancien.get("creatinine")),
        "insuffisance_hepatique": ancien.get("hepaticInsufficiency") or None,
        "allergies": ancien.get("allergies") or [], "molecules_a_eviter": ancien.get("molecules") or [],
        "pathologies": ancien.get("pathologies") or [],
    }


def instantane_depuis_audit(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Sécurisation (`vidal_prescription_audit`) -> instantané au format de l'écran d'historique clinique."""
    return {
        "numero_enreg": doc.get("id"), "date_creation": doc.get("created_at"), "login": doc.get("user_email"),
        "ordonnance_reference": f"SEC-{(doc.get('id') or '')[:6].upper()}",
        "lignes_envoyees": doc.get("lignes_envoyees") or [], "resume_gravites": doc.get("resume_gravites") or {},
        "patient_envoye": doc.get("patient_envoye") or {}, "groupe_reference_dfg_local": doc.get("groupe_reference_dfg_local"),
        "severite_max": doc.get("top_severity"), "mode_validation": doc.get("mode_validation"),
        **({"analyse": doc.get("parsed")} if "parsed" in doc else {}),
    }


async def groupes_dfg_etablissement(db, user: Dict[str, Any]) -> List[Dict[str, Any]]:
    from routes.vidal_appels import portee_etablissement
    from vidal_v2.groupes_dfg import configuration_dfg_par_defaut
    doc = await db.vidal_config_groupes_dfg.find_one({"scope_uid": await portee_etablissement(db, user)}, {"_id": 0, "groupes": 1})
    return (doc or {}).get("groupes") or configuration_dfg_par_defaut()["groupes"]


async def enregistrer_version_profil_clinique(db, patient: Dict[str, Any], user: Dict[str, Any], origine: str) -> Optional[Dict[str, Any]]:
    """§ historique du profil clinique : ajoute une VERSION datée (jamais un
    remplacement) si au moins un champ suivi a changé depuis la dernière
    version — None sinon. Chaque version porte toutes les valeurs, la liste
    des champs modifiés, l'auteur et l'origine de la saisie."""
    from vidal_v2.historique_clinique import champs_modifies, valeurs_depuis_patient
    valeurs = valeurs_depuis_patient(patient.get("profil_clinique") or {}, groupes_dfg=await groupes_dfg_etablissement(db, user))
    precedente = await db.vidal_historique_profil_clinique.find_one({"patient_id": patient["id"]}, sort=[("date", -1)])
    modifies = champs_modifies((precedente or {}).get("valeurs"), valeurs)
    if precedente and not modifies:
        return None
    version = {
        "id": str(uuid.uuid4()), "patient_id": patient["id"], "user_id": user["id"], "date": _now(),
        "login": user.get("email"), "origine": origine, "valeurs": valeurs, "champs_modifies": modifies,
        "numero_version": int((precedente or {}).get("numero_version") or 0) + 1,
    }
    await db.vidal_historique_profil_clinique.insert_one(version)
    version.pop("_id", None)
    return version


async def appliquer_profil_clinique(db, patient: Dict[str, Any], profil: ProfilCliniqueVidal, user: Dict[str, Any], origine: str) -> Optional[Dict[str, Any]]:
    """Écrit la mise à jour partielle du profil clinique puis crée la version d'historique si besoin."""
    maj = maj_profil_depuis_modele(profil)
    actuel = dict(patient.get("profil_clinique") or profil_depuis_ancien_format(patient.get("profile")))
    actuel.update(maj)
    await db.vidal_patients.update_one({"id": patient["id"]}, {"$set": {"profil_clinique": actuel, "profil_clinique_maj_le": _now()}})
    patient = {**patient, "profil_clinique": actuel}
    return await enregistrer_version_profil_clinique(db, patient, user, origine if origine in _ORIGINES_PROFIL else "securisation")


def attach_vidal_patients_routes(*, api, db, get_current_user):
    from fastapi import Body, Depends, HTTPException, Query, Response

    async def _patient(patient_id: str, user: dict) -> dict:
        doc = await db.vidal_patients.find_one({"id": patient_id, "user_id": user["id"]}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Patient introuvable")
        return doc

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
            if existing.get("est_fictif"):
                # Un patient fictif de validation garde son nom « FICTIF – … » et n'a jamais de n° WhatsApp.
                update_fields.update({"name": existing.get("name"), "whatsapp_number": None})
            await db.vidal_patients.update_one({"id": existing["id"]}, {"$set": update_fields})
            pid = existing["id"]
        else:
            pid = str(uuid.uuid4())
            await db.vidal_patients.insert_one({
                "id": pid, "user_id": user["id"], "current_treatments": [],
                "created_at": now, "last_consultation_at": None,
                **update_fields,
            })
        version = None
        if payload.profil_clinique is not None:
            doc = await db.vidal_patients.find_one({"id": pid}, {"_id": 0})
            version = await appliquer_profil_clinique(db, doc, payload.profil_clinique, user, "securisation")
        doc = await db.vidal_patients.find_one({"id": pid}, {"_id": 0})
        return {**_serialize(doc), "version_creee": version is not None,
                "champs_modifies": (version or {}).get("champs_modifies", [])}

    @api.get("/vidal/patients", tags=["VIDAL"])
    async def search_patients(
        q: Optional[str] = Query(None, min_length=1),
        fictifs: Optional[bool] = Query(None, description="true : patients fictifs de validation seulement ; false : les exclure"),
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
        if fictifs is True:
            filt["est_fictif"] = True
        elif fictifs is False:
            filt["est_fictif"] = {"$ne": True}
        cursor = db.vidal_patients.find(filt, {"_id": 0}).sort("updated_at", -1).limit(100 if fictifs else 50)
        return {"results": [_serialize(d) for d in await cursor.to_list(length=100)]}

    @api.get("/vidal/patients/{patient_id}", tags=["VIDAL"])
    async def get_patient(patient_id: str, user: dict = Depends(get_current_user)):
        return _serialize(await _patient(patient_id, user))

    # ---- Lot 56 : profil clinique et historique clinique ----
    @api.put("/vidal/patients/{patient_id}/profil-clinique", tags=["VIDAL"])
    async def enregistrer_profil_clinique(
        patient_id: str, profil: ProfilCliniqueVidal, origine: str = "securisation",
        user: dict = Depends(get_current_user),
    ):
        """Enregistre le profil clinique (mise à jour partielle) pour que la
        PROCHAINE consultation l'importe ; une version d'historique est créée
        si au moins un champ suivi a changé."""
        from routes.vidal_appels import assurer_index
        await assurer_index(db)
        patient = await _patient(patient_id, user)
        version = await appliquer_profil_clinique(db, patient, profil, user, origine)
        return {"statut": "profil clinique enregistré", "version_creee": version is not None,
                "champs_modifies": (version or {}).get("champs_modifies", [])}

    async def _historique(patient_id: str, user: dict):
        patient = await _patient(patient_id, user)
        versions = await db.vidal_historique_profil_clinique.find(
            {"patient_id": patient_id}, {"_id": 0, "user_id": 0},
        ).sort("date", 1).to_list(length=1000)
        audits = await db.vidal_prescription_audit.find(
            {"patient_id": patient_id, "user_id": user["id"], "source": "securisation_v2"}, {"_id": 0, "parsed": 0, "request_xml": 0},
        ).sort("created_at", -1).to_list(length=500)
        return patient, versions, [instantane_depuis_audit(a) for a in audits]

    @api.get("/vidal/patients/{patient_id}/historique-clinique", tags=["VIDAL"])
    async def historique_clinique_patient(patient_id: str, user: dict = Depends(get_current_user)):
        """Versions du profil clinique (de la plus ancienne à la plus récente) et
        sécurisations du patient avec leur instantané (sans le détail des alertes)."""
        from vidal_v2.historique_clinique import LIBELLES_CHAMPS
        _, versions, securisations = await _historique(patient_id, user)
        return {"versions": versions, "securisations": securisations, "libelles": LIBELLES_CHAMPS}

    @api.get("/vidal/patients/{patient_id}/historique-clinique/securisations/{analysis_id}", tags=["VIDAL"])
    async def detail_securisation_patient(patient_id: str, analysis_id: str, user: dict = Depends(get_current_user)):
        """Instantané complet d'une sécurisation (données envoyées, lignes, alertes) — patient et praticien vérifiés."""
        doc = await db.vidal_prescription_audit.find_one(
            {"id": analysis_id, "patient_id": patient_id, "user_id": user["id"]}, {"_id": 0},
        )
        if not doc:
            raise HTTPException(status_code=404, detail="Sécurisation introuvable pour ce patient.")
        return instantane_depuis_audit(doc)

    @api.get("/vidal/patients/{patient_id}/historique-clinique/pdf", tags=["VIDAL"])
    async def historique_clinique_pdf(patient_id: str, user: dict = Depends(get_current_user)):
        """Export PDF de l'historique des données cliniques (ReportLab)."""
        from vidal_v2.pdf_historique_clinique import generer_pdf_historique_clinique
        patient, versions, securisations = await _historique(patient_id, user)
        pdf = generer_pdf_historique_clinique(patient, versions, securisations)
        return Response(content=pdf, media_type="application/pdf", headers={
            "Content-Disposition": f'inline; filename="historique_clinique_{patient_id[:8]}.pdf"',
        })


async def record_consultation(db, *, patient_id: str, user_id: str, new_prescription_lines: List[Dict[str, Any]]) -> None:
    """Appelé par `vidal_securisation.py` après une analyse réussie : les
    lignes de LA NOUVELLE prescription deviennent les "traitements en cours"
    présentés au praticien à la prochaine consultation de ce patient (le
    manuel VIDAL considère un traitement fraîchement prescrit comme non
    terminé). Best-effort — n'échoue jamais l'analyse elle-même.

    Lot 56 : la liste des traitements en cours est désormais recalculée à
    partir des instantanés de sécurisation (dates et durées structurées) ;
    ce champ reste écrit pour la compatibilité."""
    try:
        await db.vidal_patients.update_one(
            {"id": patient_id, "user_id": user_id},
            {"$set": {"current_treatments": new_prescription_lines, "last_consultation_at": _now()}},
        )
    except Exception:  # noqa: BLE001
        pass
