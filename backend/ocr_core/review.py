"""Évaluation humaine : précision réelle à partir des corrections.

précision réelle = (champs extraits − champs corrigés) ÷ (champs extraits + champs oubliés)
Les différences de simple mise en forme ne comptent pas comme des erreurs.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def normalize_value(value: Any) -> Any:
    """Forme comparable : ignore espaces, casse et format des nombres
    ("150 000", "150000" et 150000.0 sont égaux)."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    text = " ".join(str(value).split())
    compact = text.replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(compact)
    except ValueError:
        return text.lower()


def compute_accuracy(extracted: Dict[str, Any], corrected: Dict[str, Any]) -> Dict[str, Any]:
    """Part des champs que le relecteur n'a PAS eu à corriger + détail des corrections.

    `corrected` peut contenir tous les champs (le formulaire les renvoie tous) :
    seuls ceux qui diffèrent réellement, ou qui manquaient, comptent."""
    changed = {
        k: v for k, v in corrected.items()
        if k not in extracted or normalize_value(v) != normalize_value(extracted.get(k))
    }
    total = len(set(extracted) | set(corrected))
    accuracy = round((total - len(changed)) / total, 4) if total else None
    return {"changed": changed, "fields_total": total, "fields_corrected": len(changed), "accuracy": accuracy}


def build_review(
    extracted: Dict[str, Any], rating: int, comment: Optional[str],
    corrected: Dict[str, Any], reviewer_id: str, reviewer_name: Optional[str],
) -> Dict[str, Any]:
    """Document « review » à enregistrer sur une analyse (identique sur tous les sites)."""
    if not 1 <= int(rating) <= 5:
        raise ValueError("La note doit être comprise entre 1 et 5")
    acc = compute_accuracy(extracted or {}, corrected or {})
    return {
        "rating": int(rating),
        "comment": (comment or "").strip() or None,
        "corrected_fields": acc["changed"],      # seulement ce qui a vraiment changé
        "fields_total": acc["fields_total"],
        "fields_corrected": acc["fields_corrected"],
        "accuracy": acc["accuracy"],
        "reviewed_by": reviewer_id,
        "reviewed_by_name": reviewer_name,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
