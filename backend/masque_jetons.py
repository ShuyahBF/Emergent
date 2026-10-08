# masque_jetons.py — Lot 78.2 : aucun jeton ne doit apparaître dans les journaux du serveur.
#
# Constat : la bibliothèque httpx écrit dans le journal l'adresse COMPLÈTE de chaque requête
# (« HTTP Request: POST https://graph.facebook.com/...?access_token=EAA... »). Un jeton passé dans
# l'adresse se retrouvait donc en clair dans les journaux Render.
# Ce filtre remplace la valeur des paramètres sensibles par « *** » dans TOUS les messages du journal
# avant leur écriture (httpx, uvicorn et nos propres journaux).
from __future__ import annotations

import logging
import re

# Paramètres d'adresse ou en-têtes dont la valeur est un secret
_SENSIBLES = re.compile(
    r"(?i)\b(access_token|input_token|client_secret|appsecret_proof|api_key|apikey|token|key|password|secret)=([^&\s\"']+)")


# Lot 79.2 — jetons reconnaissables à leur forme, où qu'ils apparaissent (ex. dans une adresse mal construite) :
# jetons d'API Cloudflare (cfat_…, cfut_…), jetons Meta / WhatsApp (EAA…), clés OpenAI / Anthropic (sk-…).
_FORMES = re.compile(r"\b(cfat_|cfut_|EAA|sk-ant-|sk-)[A-Za-z0-9_\-]{16,}")


def masquer(texte: str) -> str:
    """Remplace la valeur des paramètres sensibles par *** (ex. access_token=*** ) et masque les jetons connus."""
    texte = _SENSIBLES.sub(lambda m: f"{m.group(1)}=***", texte or "")
    return _FORMES.sub(lambda m: f"{m.group(1)}***", texte)


class FiltreJetons(logging.Filter):
    """Filtre de journal : réécrit le message déjà formaté, sans jeton."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
            propre = masquer(message)
            if propre != message:
                record.msg, record.args = propre, ()
        except Exception:  # noqa: BLE001 — un journal ne doit jamais faire échouer une requête
            pass
        return True


def installer() -> None:
    """Pose le filtre sur les gestionnaires du journal racine et sur les journaux bavards connus."""
    filtre = FiltreJetons()
    racine = logging.getLogger()
    for h in racine.handlers:
        h.addFilter(filtre)
    for nom in ("httpx", "httpcore", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(nom).addFilter(filtre)
