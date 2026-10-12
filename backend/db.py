"""MongoDB connection and helpers."""
import os
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).parent / ".env")

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Lot 116 — garde-fou central : une collection archivée (sauvegardée dans R2 puis supprimée depuis
# « 🧹 Libérer l'Espace ») n'est pas recréée par les créations d'index du démarrage.
# Voir garde_collections_archivees.py. Une erreur ici ne doit jamais empêcher le serveur de démarrer.
try:
    import garde_collections_archivees as _garde_archivees
    _garde_archivees.definir_base(db.name)     # base surveillée = celle de SAWALI
    _garde_archivees.installer()
except Exception:  # noqa: BLE001
    pass


def serialize(doc: dict | None) -> dict | None:
    if doc is None:
        return None
    doc.pop("_id", None)
    return doc


def serialize_many(docs: list[dict]) -> list[dict]:
    return [serialize(d) for d in docs]
