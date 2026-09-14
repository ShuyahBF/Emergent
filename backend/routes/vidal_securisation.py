"""Sécurisation de prescription — schéma XML réel (portage site-meetafrican).

Remplace, pour la NOUVELLE page "Sécurisation" (`/portal/vidal-securisation`),
le générateur XML "best-effort" historique (`vidal._build_alerts_xml`, qui
sérialise juste les clés du payload telles quelles — jamais vérifié contre
le manuel). Cette version reprend la structure vérifiée ligne à ligne dans
le Manuel d'intégration API REST VIDAL Sécurisation France (MI_APIREST,
REV_03) telle que documentée et exploitée dans la maquette site-meetafrican
(`frontend/src/secure/content/securisation.html::buildXml`).

L'ancien endpoint `/vidal/prescription/analyze` (routes/vidal.py) N'EST PAS
modifié : il reste utilisé tel quel par l'ancienne page `PrescriptionAnalysis.jsx`
(toujours liée depuis l'onglet "Analyse prescription" de Vidal.jsx) — aucune
régression sur du code déjà déployé.

Champ volontairement OMIS de l'XML plutôt qu'inventé :
  - `indication` par ligne de prescription : aucun endpoint de référence,
    même deviné, n'est mentionné nulle part pour ce champ (contrairement aux
    allergies/pathologies/molécules ci-dessous) — jamais envoyé.

Allergies/pathologies/molécules — recherche référentielle réelle mais
NON CONFIRMÉE : `/vidal/referential/search` appelle `/allergies?q=...` et
`/pathologies?q=...`, par analogie avec `/products?q=...` (confirmé) et les
commentaires de la maquette site-meetafrican (`securisation.html`) qui citent
ces chemins sans les avoir testés contre l'API réelle. Si ces chemins
s'avèrent incorrects une fois testés en production, la recherche échoue
proprement (l'utilisateur retombe sur la saisie libre, jamais transmise à
VIDAL) — mais un tag RÉSOLU par cette recherche (avec une vraie référence
`vidal://...` renvoyée par VIDAL) est, lui, bien envoyé dans le XML.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# 18 types d'alerte réels du manuel VIDAL (chip "Alertes à vérifier" de la
# maquette) — les 4 premiers sont cochés par défaut côté UI.
ALERT_TYPES = [
    "CONTRA_INDICATION", "ALLERGY", "DRUG_INTERACTION", "POSOLOGY",
    "PRECAUTION", "WARNING", "SIDE_EFFECT", "PHYSICO_CHEMICAL_INTERACTION",
    "SURVEILLANCE", "REDUNDANT_ACTIVE_INGREDIENT", "SAME_DRUG",
    "FOOD_INTERACTION", "DISPENSING_RISK", "PRESCRIPTION_CONTEXT",
    "EXONERATION", "INDICATOR", "FOCUS", "HAS",
]
DEFAULT_ALERT_TYPES = ["CONTRA_INDICATION", "ALLERGY", "DRUG_INTERACTION", "POSOLOGY"]


def _set_text(parent: ET.Element, tag: str, value: Any) -> None:
    if value in (None, ""):
        return
    ET.SubElement(parent, tag).text = str(value)


def _build_patient(el: ET.Element, patient: Dict[str, Any]) -> None:
    dob = patient.get("dateOfBirth")
    _set_text(el, "dateOfBirth", f"{dob}T00:00:00" if dob else None)
    _set_text(el, "gender", patient.get("gender"))
    _set_text(el, "weight", patient.get("weight"))
    _set_text(el, "height", patient.get("height"))
    if patient.get("gender") == "FEMALE":
        bf = patient.get("breastFeedingStartDate")
        _set_text(el, "breastFeedingStartDate", f"{bf}T00:00:00" if bf else None)
        _set_text(el, "weeksOfAmenorrhea", patient.get("weeksOfAmenorrhea"))
    # `clairance` (mL/min, Cockcroft & Gault) est calculée côté frontend à
    # partir de l'âge/poids/sexe/créatininémie — VIDAL attend la clairance,
    # pas la créatininémie brute (confirmé dans le manuel).
    clairance = patient.get("clairance")
    _set_text(el, "creatin", f"{clairance:.1f}" if isinstance(clairance, (int, float)) else None)
    _set_text(el, "hepaticInsufficiency", patient.get("hepaticInsufficiency"))
    # Allergies/pathologies/molécules : envoyées à VIDAL UNIQUEMENT quand une
    # vraie référence `vidal://...` a été résolue par recherche référentielle
    # (voir /vidal/referential/search, endpoints devinés par analogie avec
    # /products?q=..., jamais confirmés par un appel réel) — un tag saisi en
    # texte libre sans sélection n'a pas de référence et n'est jamais envoyé,
    # plutôt que d'en inventer une. `ref` doit être l'URI complète telle que
    # renvoyée par la recherche (ex. `vidal://cim10/4703` pour une pathologie,
    # `vidal://allergy/12` pour une allergie — le schéma d'URI varie par type,
    # voir la maquette securisation.html, pas de préfixe reconstruit ici).
    _build_ref_block(el, "allergies", "allergy", patient.get("allergies"))
    _build_ref_block(el, "molecules", "molecule", patient.get("molecules"))
    _build_ref_block(el, "pathologies", "pathology", patient.get("pathologies"))


def _build_ref_block(parent: ET.Element, block_tag: str, item_tag: str, items: Any) -> None:
    refs = [it.get("ref") for it in (items or []) if isinstance(it, dict) and it.get("ref")]
    if not refs:
        return
    block_el = ET.SubElement(parent, block_tag)
    for ref in refs:
        _set_text(block_el, item_tag, ref)


def _build_line(lines_el: ET.Element, line: Dict[str, Any]) -> None:
    li = ET.SubElement(lines_el, "prescription-line")
    drug_ref = line.get("drugRef")
    _set_text(li, "drug", f"vidal://product/{drug_ref}" if drug_ref else None)
    _set_text(li, "dose", line.get("dose"))
    _set_text(li, "unitId", line.get("unitId"))
    _set_text(li, "duration", line.get("duration"))
    _set_text(li, "durationType", line.get("durationType"))
    _set_text(li, "frequencyType", line.get("frequencyType"))
    route_ref = line.get("route")
    if route_ref:
        routes_el = ET.SubElement(li, "routes")
        _set_text(routes_el, "route", f"vidal://route/{route_ref}")
    posologies = line.get("posologies") or []
    if posologies:
        dosages_el = ET.SubElement(li, "dosages")
        for p in posologies:
            if not (p.get("dose") or p.get("intervalMin") or p.get("intervalMax")):
                continue
            dosage_el = ET.SubElement(dosages_el, "dosage")
            _set_text(dosage_el, "dose", p.get("dose"))
            _set_text(dosage_el, "unitId", p.get("unitId"))
            interval_el = ET.SubElement(dosage_el, "interval")
            _set_text(interval_el, "min", p.get("intervalMin"))
            _set_text(interval_el, "max", p.get("intervalMax"))
            _set_text(interval_el, "unitId", p.get("intervalUnitId") or "41")
    if line.get("startDate") or line.get("endDate"):
        period_el = ET.SubElement(li, "period")
        sd, ed = line.get("startDate"), line.get("endDate")
        _set_text(period_el, "startDate", f"{sd}T00:00:00" if sd else None)
        _set_text(period_el, "endDate", f"{ed}T00:00:00" if ed else None)
    _set_text(li, "status", line.get("status") or "ACTIVE")
    group_el = ET.SubElement(li, "group")
    _set_text(group_el, "groupId", line.get("groupId") or 1)
    _set_text(group_el, "groupType", line.get("groupType") or "SAME_ORDER")
    if line.get("ald"):
        ald_el = ET.SubElement(li, "aldStatus")
        _set_text(ald_el, "ald", "true")
        _set_text(ald_el, "aldCode", line.get("aldCode"))


def build_prescription_xml(
    patient: Dict[str, Any],
    lines: List[Dict[str, Any]],
    alert_types: Optional[List[str]] = None,
) -> str:
    """Construit le body XML de `/alerts/full` selon le schéma confirmé du
    manuel d'intégration VIDAL (patient / prescription-lines / alert-types)."""
    root = ET.Element("prescription")
    patient_el = ET.SubElement(root, "patient")
    _build_patient(patient_el, patient or {})
    lines_el = ET.SubElement(root, "prescription-lines")
    for line in (lines or []):
        if not line.get("drugRef") and not line.get("drug"):
            continue
        _build_line(lines_el, line)
    types_el = ET.SubElement(root, "alert-types")
    for t in (alert_types or DEFAULT_ALERT_TYPES):
        _set_text(types_el, "alert-type", t)
    xml_str = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str


# Chemin VIDAL deviné + schéma d'URI de référence, par type de recherche —
# voir la note en tête de fichier : jamais testés contre l'API réelle.
_REFERENTIAL = {
    "allergy": {"path": "/allergies", "scheme": "allergy"},
    "pathology": {"path": "/pathologies", "scheme": "cim10"},
    # Mockup : "même référentiel que les allergies (terme MOLECULE)" — on
    # tente le même chemin que les allergies avec un paramètre `type`
    # supplémentaire, faute de mieux ; à corriger si le vrai chemin diffère.
    "molecule": {"path": "/allergies", "scheme": "molecule", "extra_params": {"type": "MOLECULE"}},
}


def attach_vidal_securisation_routes(*, api, db, get_current_user):
    from fastapi import Body, Depends, HTTPException, Query
    from pydantic import BaseModel

    class SecurisationPayload(BaseModel):
        patient: Dict[str, Any] = {}
        current_treatments: List[Dict[str, Any]] = []
        new_prescription_lines: List[Dict[str, Any]] = []
        alert_types: Optional[List[str]] = None

    # ---- Recherche référentielle allergies/pathologies/molécules (NON CONFIRMÉE) ----
    @api.get("/vidal/referential/search", tags=["VIDAL"])
    async def referential_search(
        kind: str = Query(..., regex="^(allergy|pathology|molecule)$"),
        q: str = Query(..., min_length=2),
        user: dict = Depends(get_current_user),
    ):
        from routes.vidal import _ensure_tenant_can_access, _ensure_active, _quota_check_and_increment, _vidal_call
        from routes.vidal_riche import _parse_atom_entries

        cfg = await _ensure_tenant_can_access(db, user)
        _ensure_active(cfg)
        spec = _REFERENTIAL[kind]
        try:
            await _quota_check_and_increment(db, user["id"], cfg)
            params = {"q": q, **spec.get("extra_params", {})}
            data = await _vidal_call(cfg, "GET", spec["path"], params=params)
            if (data or {}).get("_error"):
                raise HTTPException(status_code=502, detail="Recherche référentielle indisponible")
            entries = _parse_atom_entries((data or {}).get("raw"))
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 — chemin deviné : dégrade proprement, jamais d'erreur 500
            raise HTTPException(status_code=502, detail=f"Recherche référentielle indisponible : {str(exc)[:150]}") from exc
        results = [
            {"label": e["title"], "ref": f"vidal://{spec['scheme']}/{e['vidal_id']}"}
            for e in entries if e.get("title") and e.get("vidal_id")
        ]
        return {"kind": kind, "query": q, "results": results, "confirmed": False}

    @api.post("/vidal/securisation/analyze", tags=["VIDAL"])
    async def securisation_analyze(
        payload: SecurisationPayload = Body(...),
        user: dict = Depends(get_current_user),
    ):
        from routes.vidal import _ensure_tenant_can_access, _ensure_active, _quota_check_and_increment, _vidal_call

        if not payload.new_prescription_lines and not payload.current_treatments:
            raise HTTPException(status_code=400, detail="Au moins un médicament est requis")
        cfg = await _ensure_tenant_can_access(db, user)
        _ensure_active(cfg)
        await _quota_check_and_increment(db, user["id"], cfg)

        all_lines = [
            {**l, "groupType": "PREVIOUS_ORDER", "groupId": 2} for l in payload.current_treatments
        ] + [
            {**l, "groupType": "SAME_ORDER", "groupId": 1} for l in payload.new_prescription_lines
        ]
        xml_body = build_prescription_xml(payload.patient, all_lines, payload.alert_types)
        data = await _vidal_call(cfg, "POST", "/alerts/full", body=xml_body)
        try:
            await db.vidal_prescription_audit.insert_one({
                "user_id": user["id"], "user_email": user.get("email"),
                "request_xml": xml_body[:4000], "response_summary": str(data)[:1500],
                "mode": cfg["mode"], "source": "securisation_v2",
                "created_at": datetime.now(timezone.utc),
            })
        except Exception:  # noqa: BLE001
            pass
        return {"data": data, "request_xml": xml_body}
