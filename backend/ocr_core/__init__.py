"""ocr_core — module commun d'OCR des pièces (factures, reçus, pièces comptables).

SOURCE UNIQUE : ce dossier est maintenu dans le dépôt ShuyahBF/Claude
(`ocr-core/backend/ocr_core/`) et COPIÉ À L'IDENTIQUE dans chaque site
(Albarka, Sawali, …) par `ocr-core/sync.sh`. Ne jamais le modifier
directement dans un site : corriger ici, monter la version, puis
resynchroniser tous les sites (voir ocr-core/README.md).

Ce module ne connaît AUCUN site : ni base de données, ni authentification,
ni stockage, ni route HTTP. Chaque site fournit une fine couche
d'« adaptateur » (ex. Sawali : backend/routes/ocr_pieces.py) qui gère qui a
le droit de voir quoi, où sont stockés les fichiers et les collections Mongo.

Contenu :
  - models   : catalogue des modèles Claude + calcul du coût réel en FCFA
  - prepare  : préparation de la pièce (PDF texte / PDF scanné → images / photo)
  - engine   : appel au modèle via EMERGENT_LLM_KEY + lecture de la réponse
  - review   : précision réelle à partir des corrections humaines
  - stats    : indicateurs du tableau de bord (par modèle, par période)
"""
from .models import (  # noqa: F401
    DEFAULT_USD_TO_XOF,
    OCR_MODELS,
    OcrModel,
    compute_cost,
    default_model_id,
    get_model,
    public_catalog,
    usd_to_xof_rate,
)
from .engine import analyze_document, build_system_prompt  # noqa: F401
from .review import build_review, compute_accuracy, normalize_value  # noqa: F401
from .stats import PERIODS, period_start, stats_block, stats_by_model  # noqa: F401

__version__ = "1.0.0"   # garder identique au fichier ocr-core/VERSION
