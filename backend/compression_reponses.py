# compression_reponses.py — Lot 79.6 : compression GZip SÉLECTIVE des réponses de l'API.
#
# Pourquoi : Render compte la bande passante sortante (5 Go inclus par mois sur le plan Hobby).
# Les réponses JSON (contacts, conversations, tableaux) se compressent très bien : 100 Ko → 15-25 Ko.
#
# Ce qui est compressé : réponses « texte » (JSON, HTML, texte, CSV, XML, JavaScript, CSS, SVG)
#   d'au moins TAILLE_MIN octets, envoyées d'un seul bloc, quand le navigateur accepte gzip.
# Ce qui ne l'est JAMAIS (passe tel quel, sans aucun délai) :
#   - les flux en continu (Liluvine PRO qui écrit au fil de l'eau, text/event-stream, téléchargements
#     envoyés par morceaux) : les compresser retarderait l'affichage ;
#   - les fichiers déjà compressés (images, vidéos, sons, PDF, .gz, .zip, sauvegardes .sawali) ;
#   - les petites réponses (< TAILLE_MIN) : rien à gagner ;
#   - les WebSocket (chat Loois, appels WhatsApp) : seules les requêtes HTTP passent ici.
# Pourquoi pas le GZipMiddleware de Starlette : dans la version installée (0.37), il compresse aussi
# les flux en continu, ce qui bloquerait l'écriture progressive de Liluvine.
from __future__ import annotations

import gzip

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

TAILLE_MIN = 1000      # octets : en dessous, la réponse part telle quelle
NIVEAU = 6             # 1 (rapide) … 9 (plus petit) : 6 = bon compromis, ~1 ms pour 100 Ko
# Types de contenu compressibles (début du Content-Type)
TYPES_COMPRESSIBLES = ("application/json", "text/html", "text/plain", "text/csv", "text/css",
                       "text/xml", "application/xml", "application/javascript", "text/javascript",
                       "image/svg+xml", "application/problem+json")


def compressible(type_contenu: str) -> bool:
    """Le type de contenu vaut-il la peine d'être compressé ? (jamais les flux text/event-stream)"""
    t = (type_contenu or "").split(";")[0].strip().lower()
    return t.startswith(TYPES_COMPRESSIBLES) and t != "text/event-stream"


class CompressionSelective:
    """Intergiciel ASGI : compresse en gzip les réponses texte complètes ; laisse passer tout le reste."""

    def __init__(self, app: ASGIApp, taille_min: int = TAILLE_MIN, niveau: int = NIVEAU) -> None:
        self.app = app
        self.taille_min = taille_min
        self.niveau = niveau

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Seules les requêtes HTTP dont le navigateur accepte gzip sont concernées
        if scope["type"] != "http" or "gzip" not in Headers(scope=scope).get("accept-encoding", "").lower():
            await self.app(scope, receive, send)
            return

        debut: Message = {}          # en-têtes retenus le temps de voir le premier morceau du corps
        decide = False               # True une fois la décision prise (compresser ou non)

        async def envoyer(message: Message) -> None:
            nonlocal debut, decide
            if message["type"] == "http.response.start":
                debut = message                      # retenu : les en-têtes peuvent encore changer
                return
            if message["type"] != "http.response.body" or decide:
                await send(message)                  # suite d'un flux déjà commencé : tel quel
                return
            decide = True
            entetes = Headers(raw=debut.get("headers") or [])
            corps = message.get("body", b"")
            if (message.get("more_body")                         # flux en continu
                    or "content-encoding" in entetes             # déjà compressé par la route
                    or not compressible(entetes.get("content-type", ""))
                    or len(corps) < self.taille_min):
                await send(debut)
                await send(message)
                return
            # Réponse complète et compressible : compression en une fois
            compresse = gzip.compress(corps, compresslevel=self.niveau)
            modifiables = MutableHeaders(raw=debut["headers"])
            modifiables["Content-Encoding"] = "gzip"
            modifiables["Content-Length"] = str(len(compresse))
            modifiables.add_vary_header("Accept-Encoding")
            await send(debut)
            await send({"type": "http.response.body", "body": compresse, "more_body": False})

        await self.app(scope, receive, envoyer)
