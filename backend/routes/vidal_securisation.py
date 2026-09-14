"""Sécurisation de prescription — schéma XML réel (portage site-meetafrican).

Remplace, pour la NOUVELLE page "Sécurisation" (`/portal/vidal-securisation`),
le générateur XML "best-effort" historique (`vidal._build_alerts_xml`, qui
sérialise juste les clés du payload telles quelles — jamais vérifié contre
le manuel). Cette version reprend la structure du corps de requête ET DE LA
RÉPONSE de `/alerts/full`, vérifiées ligne à ligne contre le Manuel
d'intégration API REST VIDAL Sécurisation France (MI_APIREST, REV_03,
partagé par l'utilisateur) — pas seulement la maquette site-meetafrican, qui
n'avait jamais eu la réponse réelle sous les yeux (ses propres cartes
d'alerte étaient explicitement "Aperçu illustratif").

L'ancien endpoint `/vidal/prescription/analyze` (routes/vidal.py) N'EST PAS
modifié : il reste utilisé tel quel par l'ancienne page `PrescriptionAnalysis.jsx`
(toujours liée depuis l'onglet "Analyse prescription" de Vidal.jsx) — aucune
régression sur du code déjà déployé.

Allergies/pathologies/molécules/indications — recherche référentielle RÉELLE
ET CONFIRMÉE dans le manuel (chapitre "Les allergies" / "Saisie d'une
pathologie CIM10" / "prescription-line") :
  - `/rest/api/allergies?q=...` renvoie À LA FOIS des classes d'allergie
    (catégorie ALLERGY) et des molécules (catégorie MOLECULE) — même
    endpoint pour les deux recherches, l'utilisateur choisit dans quelle
    liste (allergie ou molécule) ranger le résultat.
  - `/rest/api/pathologies?q=...&type=CIM10` pour les pathologies.
  - `/rest/api/product/{id}/indications` pour les indications compatibles
    d'un produit donné (référence `vidal://indication/{id}`) — Sécurisation
    ET Posologie utilisent ce même endpoint, au même titre que les voies
    d'administration (`/product/{id}/detail`, déjà réel).

Réponse `/alerts/full` — schéma confirmé (voir `parse_alerts_response`) :
un résumé par catégorie (`<vidal:max...Severity severity="...">`) en tête de
flux, puis des `<entry vidal:categories="ALERT">` avec au minimum `<title>`,
`<content>`, `<vidal:alertType name="...">`, `<vidal:severity>` (NO_ALERT/
INFO/LEVEL_1..4, croissant en gravité), `<vidal:subType name="...">`, et
souvent `<vidal:detail>`/`<vidal:triggeredBy>`/`<vidal:source>`.
"""
from __future__ import annotations

import re
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
    # Indication thérapeutique — confirmée dans le manuel (`<indications><indication>
    # vidal://indication/{id}</indication></indications>`), résolue via
    # /vidal/product/{id}/indications (même logique que les voies d'administration).
    indication_ref = line.get("indication")
    if indication_ref:
        indications_el = ET.SubElement(li, "indications")
        _set_text(indications_el, "indication", indication_ref)
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


# Chemins et schémas d'URI de référence — CONFIRMÉS dans le manuel MI_APIREST
# REV_03 (chapitre "Les allergies" / "Saisie d'une pathologie CIM10").
# Allergie ET molécule utilisent le MÊME endpoint (`/allergies?q=...` renvoie
# les deux catégories mélangées, distinguées par la terminologie de la
# source côté VIDAL) — c'est l'utilisateur qui choisit dans quelle liste
# (allergie ou molécule) ranger le résultat choisi, pas un paramètre de requête.
_REFERENTIAL = {
    "allergy": {"path": "/allergies", "scheme": "allergy"},
    "molecule": {"path": "/allergies", "scheme": "molecule"},
    "pathology": {"path": "/pathologies", "scheme": "cim10", "extra_params": {"type": "CIM10"}},
}


# ---------------------------------------------------------------------------
# Réponse /alerts/full — schéma confirmé (manuel MI_APIREST REV_03)
# ---------------------------------------------------------------------------
_SUMMARY_RE = re.compile(
    r'<vidal:(max\w+Severity)\b[^>]*\bseverity="([^"]*)"[^>]*>(.*?)</vidal:\1>',
    re.DOTALL | re.IGNORECASE,
)
_ALERT_ENTRY_RE = re.compile(
    r'<entry\b[^>]*\bvidal:categories="ALERT"[^>]*>(.*?)</entry>', re.DOTALL | re.IGNORECASE,
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_CONTENT_RE = re.compile(r'<content\b[^>]*>(.*?)</content>', re.DOTALL | re.IGNORECASE)
_ALERT_TYPE_RE = re.compile(r'<vidal:alertType\b[^>]*\bname="([^"]*)"[^>]*>(.*?)</vidal:alertType>', re.DOTALL | re.IGNORECASE)
_SEVERITY_RE = re.compile(r"<vidal:severity>(.*?)</vidal:severity>", re.DOTALL | re.IGNORECASE)
_SUBTYPE_RE = re.compile(r'<vidal:subType\b[^>]*\bname="([^"]*)"[^>]*>(.*?)</vidal:subType>', re.DOTALL | re.IGNORECASE)
_DETAIL_RE = re.compile(r'<vidal:detail\b[^>]*>(.*?)</vidal:detail>', re.DOTALL | re.IGNORECASE)
_TRIGGERED_BY_RE = re.compile(
    r'<vidal:triggeredBy\b[^>]*\bid="([^"]*)"[^>]*\btype="([^"]*)"[^>]*>(.*?)</vidal:triggeredBy>',
    re.DOTALL | re.IGNORECASE,
)
_SOURCE_RE = re.compile(r'<vidal:source\b[^>]*\bdate="([^"]*)"[^>]*>(.*?)</vidal:source>', re.DOTALL | re.IGNORECASE)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")

# Gravité croissante — sert à trier les alertes et à choisir une couleur.
_SEVERITY_ORDER = {"NO_ALERT": 0, "INFO": 1, "LEVEL_1": 2, "LEVEL_2": 3, "LEVEL_3": 4, "LEVEL_4": 5}


def _clean(text: Optional[str]) -> str:
    if not text:
        return ""
    return _TAG_STRIP_RE.sub("", text).strip()


def parse_alerts_response(raw: Optional[str]) -> Dict[str, Any]:
    """Parse la réponse `/alerts/full` selon le schéma confirmé du manuel :
    un résumé par catégorie en tête de flux, puis des `<entry vidal:categories=
    "ALERT">` détaillées. Dégrade proprement (listes vides) si le format
    diffère — jamais d'exception remontée à l'appelant."""
    summary: List[Dict[str, Any]] = []
    alerts: List[Dict[str, Any]] = []
    if not isinstance(raw, str) or "<" not in raw:
        return {"summary": summary, "alerts": alerts}

    for category, severity, label in _SUMMARY_RE.findall(raw):
        summary.append({"category": category, "severity": severity, "label": _clean(label)})

    for block in _ALERT_ENTRY_RE.findall(raw):
        title_m = _TITLE_RE.search(block)
        content_m = _CONTENT_RE.search(block)
        type_m = _ALERT_TYPE_RE.search(block)
        severity_m = _SEVERITY_RE.search(block)
        subtype_m = _SUBTYPE_RE.search(block)
        detail_m = _DETAIL_RE.search(block)
        triggered_m = _TRIGGERED_BY_RE.search(block)
        source_m = _SOURCE_RE.search(block)
        alerts.append({
            "title": _clean(title_m.group(1)) if title_m else None,
            "content": _clean(content_m.group(1)) if content_m else None,
            "alert_type": type_m.group(1) if type_m else None,
            "alert_type_label": _clean(type_m.group(2)) if type_m else None,
            "severity": severity_m.group(1).strip() if severity_m else None,
            "sub_type": subtype_m.group(1) if subtype_m else None,
            "sub_type_label": _clean(subtype_m.group(2)) if subtype_m else None,
            "detail": _clean(detail_m.group(1)) if detail_m else None,
            "triggered_by_id": triggered_m.group(1) if triggered_m else None,
            "triggered_by_type": triggered_m.group(2) if triggered_m else None,
            "triggered_by_label": _clean(triggered_m.group(3)) if triggered_m else None,
            "source_date": source_m.group(1) if source_m else None,
            "source_label": _clean(source_m.group(2)) if source_m else None,
        })
    alerts.sort(key=lambda a: _SEVERITY_ORDER.get(a.get("severity"), -1), reverse=True)
    return {"summary": summary, "alerts": alerts}


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
        return {"kind": kind, "query": q, "results": results, "confirmed": True}

    # ---- Indications compatibles d'un produit (réel, confirmé — même schéma que /detail) ----
    @api.get("/vidal/product/{product_id}/indications", tags=["VIDAL"])
    async def product_indications(product_id: str, user: dict = Depends(get_current_user)):
        from routes.vidal import _ensure_tenant_can_access, _ensure_active, _quota_check_and_increment, _vidal_call
        from routes.vidal_riche import _parse_atom_entries

        cfg = await _ensure_tenant_can_access(db, user)
        _ensure_active(cfg)
        await _quota_check_and_increment(db, user["id"], cfg)
        data = await _vidal_call(cfg, "GET", f"/product/{product_id}/indications")
        entries = _parse_atom_entries((data or {}).get("raw"))
        results = [
            {"label": e["title"], "ref": f"vidal://indication/{e['vidal_id']}"}
            for e in entries if e.get("title") and e.get("vidal_id")
        ]
        return {"product_id": product_id, "indications": results}

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
        parsed = parse_alerts_response((data or {}).get("raw"))
        try:
            await db.vidal_prescription_audit.insert_one({
                "user_id": user["id"], "user_email": user.get("email"),
                "request_xml": xml_body[:4000], "response_summary": str(data)[:1500],
                "mode": cfg["mode"], "source": "securisation_v2",
                "created_at": datetime.now(timezone.utc),
            })
        except Exception:  # noqa: BLE001
            pass
        return {"data": data, "request_xml": xml_body, "parsed": parsed}
