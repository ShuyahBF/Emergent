"""Indicateurs du tableau de bord OCR (par modèle, par période)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .models import get_model, usd_to_xof_rate

PERIODS = {"today", "7d", "30d", "all"}


def period_start(period: str) -> Optional[str]:
    """Date ISO (UTC) de début de période ; None = depuis toujours.

    Lève ValueError pour une période inconnue."""
    if period not in PERIODS:
        raise ValueError(f"period invalide (attendu : {sorted(PERIODS)})")
    now = datetime.now(timezone.utc)
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    if period == "7d":
        return (now - timedelta(days=7)).isoformat()
    if period == "30d":
        return (now - timedelta(days=30)).isoformat()
    return None


def _avg(values: List[float]) -> Optional[float]:
    return round(sum(values) / len(values), 4) if values else None


def stats_block(rows: List[dict]) -> Dict[str, Any]:
    """Indicateurs d'un groupe d'analyses (un modèle, ou le total)."""
    reviews = [r["review"] for r in rows if r.get("review")]
    ok_rows = [r for r in rows if not r.get("error")]
    total_cost = sum(float(r.get("cost_xof") or 0) for r in rows)
    return {
        "runs": len(rows),
        "errors": len(rows) - len(ok_rows),
        "total_cost_xof": round(total_cost, 2),
        "avg_cost_xof": round(total_cost / len(rows), 2) if rows else None,
        "total_input_tokens": sum(int(r.get("input_tokens") or 0) for r in rows),
        "total_output_tokens": sum(int(r.get("output_tokens") or 0) for r in rows),
        "avg_duration_ms": _avg([float(r.get("duration_ms") or 0) for r in ok_rows]),
        # Confiance auto-déclarée par le modèle — indicative seulement
        "avg_confidence": _avg([float(r["confidence"]) for r in ok_rows if r.get("confidence") is not None]),
        # Mesures humaines (seules à faire foi)
        "reviewed": len(reviews),
        "avg_rating": _avg([float(rv["rating"]) for rv in reviews if rv.get("rating")]),
        "avg_accuracy": _avg([float(rv["accuracy"]) for rv in reviews if rv.get("accuracy") is not None]),
    }


def stats_by_model(rows: List[dict], period: str) -> Dict[str, Any]:
    """Réponse complète de la route « tableau de bord » : identique sur tous les sites."""
    by_model: Dict[str, List[dict]] = {}
    for r in rows:
        by_model.setdefault(r.get("model") or "inconnu", []).append(r)
    models = []
    for model_id, model_rows in by_model.items():
        cfg = get_model(model_id)
        models.append({"model": model_id, "label": cfg.label if cfg else model_id, **stats_block(model_rows)})
    models.sort(key=lambda m: m["runs"], reverse=True)
    return {"period": period, "usd_to_xof_rate": usd_to_xof_rate(), "models": models, "total": stats_block(rows)}
