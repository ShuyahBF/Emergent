# carrousel_modeles_meta.py — Lot 76 : création automatique chez Meta des 9 modèles du carrousel WhatsApp.
#
# Contexte : l'interface WhatsApp Manager ne propose pas toujours le type « Carrousel ». L'API de Meta, elle,
# l'accepte toujours. Ce module construit les modèles <préfixe>_2 … <préfixe>_10 EXACTEMENT comme SAWALI les
# remplit à l'envoi (routes/carrousel_whatsapp.py → composants()) :
#   - bulle principale : 2 variables  {{1}} expéditeur, {{2}} message ;
#   - chaque carte : en-tête IMAGE, corps à 2 variables ({{1}} titre, {{2}} texte),
#     1 bouton URL dynamique  <site>/api/public/carrousel/l/{{1}}  (code court qui compte le clic).
# Meta exige une image d'EXEMPLE par carte : elle est déposée par l'API « Resumable Upload »
# (POST /{app-id}/uploads), d'où le besoin de l'App ID Meta (Paramètres → Intégration Meta).
# Aucun secret n'est écrit dans les journaux ; le jeton n'est jamais renvoyé au navigateur.
from __future__ import annotations

import io
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("sawali.carrousel_modeles_meta")

CARTES_MIN, CARTES_MAX = 2, 10
# Textes fixes : une variable n'est jamais au tout début ni à la toute fin (règle Meta)
TEXTE_BULLE = "Bonjour, {{1}} vous présente : {{2}}. Faites défiler les cartes ci-dessous."
TEXTE_CARTE = "Découvrez {{1}} : {{2}}. Touchez le bouton pour en savoir plus."
TEXTE_BOUTON = "Voir plus"
EXEMPLE_BULLE = ["SAWALI SMART SYSTEMS", "nos nouveautés de la semaine"]
EXEMPLE_CARTE = ["Formulaires", "création de formulaires électroniques"]
EXEMPLE_CODE = "aBc123"


def nom_modele(prefixe: str, nb_cartes: int) -> str:
    """Même règle que l'envoi : un modèle par nombre de cartes, <préfixe>_<N>."""
    return f"{prefixe}_{nb_cartes}"


def definition_modele(prefixe: str, nb_cartes: int, langue: str, url_bouton: str, handle_image: str) -> Dict[str, Any]:
    """Corps JSON envoyé à POST /{waba-id}/message_templates pour un carrousel de nb_cartes cartes."""
    carte = {"components": [
        {"type": "HEADER", "format": "IMAGE", "example": {"header_handle": [handle_image]}},
        {"type": "BODY", "text": TEXTE_CARTE, "example": {"body_text": [EXEMPLE_CARTE]}},
        {"type": "BUTTONS", "buttons": [
            {"type": "URL", "text": TEXTE_BOUTON, "url": url_bouton, "example": [EXEMPLE_CODE]},
        ]},
    ]}
    return {
        "name": nom_modele(prefixe, nb_cartes),
        "language": langue,
        "category": "MARKETING",
        "components": [
            {"type": "BODY", "text": TEXTE_BULLE, "example": {"body_text": [EXEMPLE_BULLE]}},
            {"type": "CAROUSEL", "cards": [carte for _ in range(nb_cartes)]},
        ],
    }


def image_exemple() -> bytes:
    """Image d'exemple (PNG 800×800, couleur unie SAWALI) exigée par Meta pour chaque carte."""
    from PIL import Image
    tampon = io.BytesIO()
    Image.new("RGB", (800, 800), (14, 116, 144)).save(tampon, format="PNG")
    return tampon.getvalue()


def _message_erreur(reponse: httpx.Response) -> str:
    """Message d'erreur lisible renvoyé par Meta (sans jeton)."""
    try:
        err = (reponse.json() or {}).get("error") or {}
        return (err.get("error_user_msg") or err.get("message") or f"HTTP {reponse.status_code}")[:300]
    except ValueError:
        return f"HTTP {reponse.status_code}"


def deja_existant(message: str) -> bool:
    """Meta refuse un nom déjà pris (même nom + même langue) : ce n'est pas une panne."""
    m = (message or "").lower()
    return "already exists" in m or "existe déjà" in m or "content in this language already exists" in m


async def deposer_image(http: httpx.AsyncClient, *, version: str, app_id: str, jeton: str, octets: bytes) -> str:
    """Dépôt de l'image d'exemple (Resumable Upload) → « handle » utilisé dans header_handle."""
    r = await http.post(f"https://graph.facebook.com/{version}/{app_id}/uploads",
                        params={"file_name": "carrousel-exemple.png", "file_length": len(octets),
                                "file_type": "image/png", "access_token": jeton})
    if r.status_code >= 300:
        raise RuntimeError(f"Dépôt de l'image d'exemple refusé : {_message_erreur(r)}")
    session = (r.json() or {}).get("id")
    r2 = await http.post(f"https://graph.facebook.com/{version}/{session}", content=octets,
                         headers={"Authorization": f"OAuth {jeton}", "file_offset": "0"})
    if r2.status_code >= 300 or not (r2.json() or {}).get("h"):
        raise RuntimeError(f"Dépôt de l'image d'exemple refusé : {_message_erreur(r2)}")
    return r2.json()["h"]


async def creer_modeles(*, version: str, app_id: str, waba_id: str, jeton: str, prefixe: str, langue: str,
                        url_bouton: str, client: Optional[httpx.AsyncClient] = None) -> List[Dict[str, Any]]:
    """Crée les 9 modèles (2 à 10 cartes). Renvoie une ligne par modèle :
    {nom, statut: « soumis » | « existe déjà » | « erreur », detail}. Ne lève jamais d'exception par modèle."""
    resultats: List[Dict[str, Any]] = []
    propre = client is None
    http = client or httpx.AsyncClient(timeout=60)
    try:
        handle = await deposer_image(http, version=version, app_id=app_id, jeton=jeton, octets=image_exemple())
        for n in range(CARTES_MIN, CARTES_MAX + 1):
            nom = nom_modele(prefixe, n)
            try:
                r = await http.post(f"https://graph.facebook.com/{version}/{waba_id}/message_templates",
                                    json=definition_modele(prefixe, n, langue, url_bouton, handle),
                                    headers={"Authorization": f"Bearer {jeton}"})
                if r.status_code < 300:
                    d = r.json() or {}
                    resultats.append({"nom": nom, "statut": "soumis", "detail": d.get("status") or "PENDING"})
                else:
                    msg = _message_erreur(r)
                    resultats.append({"nom": nom, "statut": "existe déjà" if deja_existant(msg) else "erreur", "detail": msg})
            except httpx.HTTPError as exc:
                resultats.append({"nom": nom, "statut": "erreur", "detail": f"Réseau : {type(exc).__name__}"})
    finally:
        if propre:
            await http.aclose()
    logger.info("[carrousel] modèles Meta « %s » : %s", prefixe, ", ".join(f"{x['nom']}={x['statut']}" for x in resultats))
    return resultats
