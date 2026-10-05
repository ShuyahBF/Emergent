"""Lot 57.14 — jeton de connexion des WebSockets HORS de l'adresse.

Avant : le navigateur ouvrait « wss://…/api/ws/chat?token=<JWT> ». L'adresse complète (donc le jeton de
session) était écrite dans les journaux de Render à chaque connexion : quiconque lisait les journaux pouvait
se connecter à la place de l'utilisateur.

Maintenant : le navigateur ouvre « wss://…/api/ws/chat » SANS jeton, puis envoie comme PREMIER message
    {"type": "auth", "token": "<JWT>"}
Les messages d'un WebSocket ne sont jamais journalisés. L'ancien « ?token= » reste accepté quelques jours
(onglets restés ouverts avec l'ancienne version de l'interface), puis pourra être retiré.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import WebSocket

# Délai pour recevoir le message d'authentification (au-delà : connexion fermée)
DELAI_AUTH_SECONDES = 10.0


async def lire_jeton(websocket: WebSocket, jeton_adresse: Optional[str] = None) -> Optional[str]:
    """
    Jeton de la connexion (le WebSocket doit déjà être accepté) : celui de l'ancienne adresse s'il est
    fourni, sinon celui du premier message {"type": "auth", "token": …}. None si rien de valide n'arrive
    dans le délai (message d'un autre type, texte illisible, déconnexion).
    """
    if jeton_adresse:
        return jeton_adresse
    try:
        data = await asyncio.wait_for(websocket.receive_json(), timeout=DELAI_AUTH_SECONDES)
    except Exception:  # délai dépassé, déconnexion, texte non JSON…
        return None
    if isinstance(data, dict) and data.get("type") == "auth":
        jeton = data.get("token")
        if isinstance(jeton, str) and jeton.strip():
            return jeton.strip()
    return None
