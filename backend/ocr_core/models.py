"""Catalogue des modèles Claude proposés pour l'OCR + coût réel en FCFA.

Tarifs officiels Anthropic en USD pour 1 million de tokens (2026-09).
Ajouter un modèle = ajouter une entrée dans OCR_MODELS, rien d'autre.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class OcrModel:
    id: str                       # identifiant exact transmis au proxy Emergent
    label: str                    # libellé affiché dans la liste déroulante
    price_input_per_mtok: float   # USD / 1M tokens en entrée (images/texte + consigne)
    price_output_per_mtok: float  # USD / 1M tokens en sortie (JSON + réflexion)
    note: str                     # conseil d'usage affiché sous la liste

    def public(self) -> Dict[str, Any]:
        """Version sérialisable renvoyée au frontend."""
        return {
            "id": self.id, "label": self.label, "note": self.note,
            "price_input_per_mtok": self.price_input_per_mtok,
            "price_output_per_mtok": self.price_output_per_mtok,
        }


OCR_MODELS: Dict[str, OcrModel] = {
    "claude-opus-5": OcrModel(
        id="claude-opus-5",
        label="Claude Opus 5 — le plus précis (manuscrit, tampons)",
        price_input_per_mtok=5.00, price_output_per_mtok=25.00,
        note="Meilleure précision, notamment sur l'écriture manuscrite. Coût le plus élevé.",
    ),
    "claude-sonnet-5": OcrModel(
        id="claude-sonnet-5",
        label="Claude Sonnet 5 — bon compromis coût/précision",
        price_input_per_mtok=2.00, price_output_per_mtok=10.00,
        note="Modèle recommandé : validé en production sur manuscrit et filigrane (Albarka).",
    ),
    # Identifiant daté : c'est celui déjà éprouvé en production via le proxy
    # Emergent (Sawali : Liluvine, SMS, bannières…).
    "claude-haiku-4-5-20251001": OcrModel(
        id="claude-haiku-4-5-20251001",
        label="Claude Haiku 4.5 — le moins cher (imprimé net, gros volume)",
        price_input_per_mtok=1.00, price_output_per_mtok=5.00,
        note="Le plus économique. À réserver aux pièces imprimées nettes, sans manuscrit.",
    ),
}

# Modèle par défaut commun à tous les sites (surchargeable par la variable
# d'environnement OCR_DEFAULT_MODEL, ou par l'adaptateur du site).
FALLBACK_DEFAULT_MODEL = "claude-sonnet-5"

# Taux USD → FCFA (XOF). Le FCFA est arrimé à l'EURO (655,957 XOF/EUR), pas
# au dollar : ce taux suit l'EUR/USD et doit être ajusté périodiquement.
DEFAULT_USD_TO_XOF = 600.0


def get_model(model_id: Optional[str]) -> Optional[OcrModel]:
    """Modèle du catalogue, ou None si l'identifiant est inconnu."""
    return OCR_MODELS.get(model_id or "")


def default_model_id(env_var: str = "OCR_DEFAULT_MODEL") -> str:
    """Modèle par défaut : variable d'environnement si valide, sinon Sonnet 5."""
    value = os.environ.get(env_var, "")
    return value if value in OCR_MODELS else FALLBACK_DEFAULT_MODEL


def public_catalog(default_model: Optional[str] = None) -> Dict[str, Any]:
    """Réponse de la route « liste des modèles » : identique sur tous les sites."""
    return {
        "models": [m.public() for m in OCR_MODELS.values()],
        "default_model": default_model or default_model_id(),
        "usd_to_xof_rate": usd_to_xof_rate(),
    }


def usd_to_xof_rate() -> float:
    """Taux USD→XOF lu à chaque appel (modifiable sans toucher au code)."""
    try:
        rate = float(os.environ.get("USD_TO_XOF_RATE", DEFAULT_USD_TO_XOF))
        return rate if rate > 0 else DEFAULT_USD_TO_XOF
    except ValueError:
        return DEFAULT_USD_TO_XOF


def compute_cost(model: OcrModel, input_tokens: int, output_tokens: int) -> Tuple[float, float]:
    """Coût réel d'un appel : (USD, FCFA), à partir des tokens effectivement consommés."""
    cost_usd = (input_tokens * model.price_input_per_mtok + output_tokens * model.price_output_per_mtok) / 1_000_000
    return round(cost_usd, 6), round(cost_usd * usd_to_xof_rate(), 2)


def model_ids() -> List[str]:
    return list(OCR_MODELS)
