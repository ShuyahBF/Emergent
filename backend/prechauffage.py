# prechauffage.py — Lot 475 : PRÉCHAUFFAGE des modules lourds au démarrage, hors de la boucle principale.
# Constat (sentinelle « [boucle-bloquee] », 27/11/2026) : 3 à 4 s de gel après chaque redémarrage, car la tâche planifiée de
# l'agenda de Liluvine importait ses modules (pydantic, formulaires, appels…) À LA PREMIÈRE MINUTE, dans la boucle du serveur,
# donc toutes les requêtes attendaient. Un import est exécuté dans un FIL : la boucle continue de répondre pendant ce temps.
import asyncio
import importlib
import logging
import time
from typing import List, Sequence

logger = logging.getLogger("sawali.prechauffage")

# Modules importés « paresseusement » par des tâches planifiées ou des routes, à charger d'avance (ordre = ordre de chargement)
MODULES_A_PRECHAUFFER: Sequence[str] = (
    "routes.liluvine_agenda",
)


def importer_modules(noms: Sequence[str]) -> List[dict]:
    """Importe chaque module (synchrone, à appeler DANS un fil). Une erreur d'import n'arrête jamais le serveur : elle est notée."""
    bilan = []
    for nom in noms:
        debut = time.monotonic()
        try:
            importlib.import_module(nom)
            bilan.append({"module": nom, "ok": True, "ms": round((time.monotonic() - debut) * 1000)})
        except Exception as exc:  # noqa: BLE001 — le préchauffage est facultatif
            bilan.append({"module": nom, "ok": False, "ms": round((time.monotonic() - debut) * 1000), "erreur": str(exc)[:200]})
    return bilan


async def prechauffer(noms: Sequence[str] = MODULES_A_PRECHAUFFER) -> List[dict]:
    """Lance l'import dans un fil et journalise le bilan ; la boucle principale n'est jamais bloquée."""
    bilan = await asyncio.to_thread(importer_modules, list(noms))
    for b in bilan:
        if b["ok"]:
            logger.info("[prechauffage] %s chargé en %d ms (hors boucle principale)", b["module"], b["ms"])
        else:
            logger.warning("[prechauffage] %s non chargé : %s", b["module"], b.get("erreur"))
    return bilan
