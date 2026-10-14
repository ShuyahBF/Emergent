# accord_modele_meta.py — Lot 165 : modèle WhatsApp (Meta) de DEMANDE D'ACCORD avec bouton « lien personnel ».
#
# Contexte : un bouton de modèle avec une adresse FIXE (ex. le lien wa.me) ne peut pas porter le lien personnel de
# chaque contact. Ce modèle a un bouton URL DYNAMIQUE  <site>/accord/{{1}}  : au moment de l'envoi, SAWALI y met le
# jeton de la personne (routes/accord_page.py) et la personne ouvre SA page d'accord.
#   - corps : 2 variables  {{1}} prénom, {{2}} expéditeur ;
#   - catégorie MARKETING (la demande vise l'envoi de nouveautés et d'offres) ;
#   - bouton URL « Répondre » → <site>/accord/{{1}}.
# Ce module ne fait QUE créer le modèle chez Meta et lire son statut : aucun message n'est envoyé aux contacts.
# Aucun secret n'est écrit dans les journaux ; le jeton n'est jamais renvoyé au navigateur.
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("sawali.accord_modele_meta")

NOM_DEFAUT = "sawali_accord_lien"
# Une variable n'est jamais au tout début ni à la toute fin du texte (règle Meta)
TEXTE_CORPS = ("Bonjour {{1}}, {{2}} souhaite vous envoyer ses nouveautés et offres sur WhatsApp. "
               "Touchez le bouton pour accepter ou refuser : vous pourrez arrêter à tout moment.")
EXEMPLE_CORPS = ["Awa", "SAWALI SMART SYSTEMS"]
TEXTE_BOUTON = "Répondre"
EXEMPLE_JETON = "exemple"


def definition_modele(nom: str, langue: str, url_bouton: str, *, exemple_url_complete: bool = True) -> Dict[str, Any]:
    """Corps JSON envoyé à POST /{waba-id}/message_templates. Meta documente l'exemple du bouton comme une adresse
    COMPLÈTE ; certaines versions acceptent seulement le suffixe : `exemple_url_complete` choisit la forme."""
    exemple = url_bouton.replace("{{1}}", EXEMPLE_JETON) if exemple_url_complete else EXEMPLE_JETON
    return {
        "name": nom, "language": langue, "category": "MARKETING",
        "components": [
            {"type": "BODY", "text": TEXTE_CORPS, "example": {"body_text": [EXEMPLE_CORPS]}},
            {"type": "BUTTONS", "buttons": [{"type": "URL", "text": TEXTE_BOUTON, "url": url_bouton, "example": [exemple]}]},
        ],
    }


def _message_erreur(reponse: httpx.Response) -> str:
    try:
        err = (reponse.json() or {}).get("error") or {}
        return (err.get("error_user_msg") or err.get("message") or f"HTTP {reponse.status_code}")[:300]
    except ValueError:
        return f"HTTP {reponse.status_code}"


def deja_existant(message: str) -> bool:
    m = (message or "").lower()
    return "already exists" in m or "existe déjà" in m or "content in this language already exists" in m


async def creer_modele(*, version: str, waba_id: str, jeton: str, nom: str, langue: str, url_bouton: str,
                       client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    """Crée le modèle chez Meta. → {nom, statut: « soumis » | « existe déjà » | « erreur », detail}. Ne lève jamais.
    Si Meta refuse la forme de l'exemple d'adresse, la seconde forme est essayée avant de signaler l'erreur."""
    propre = client is None
    http = client or httpx.AsyncClient(timeout=60)
    detail = ""
    try:
        for complete in (True, False):
            try:
                r = await http.post(f"https://graph.facebook.com/{version}/{waba_id}/message_templates",
                                    json=definition_modele(nom, langue, url_bouton, exemple_url_complete=complete),
                                    headers={"Authorization": f"Bearer {jeton}"})
            except httpx.HTTPError as exc:
                return {"nom": nom, "statut": "erreur", "detail": f"Réseau : {type(exc).__name__}"}
            if r.status_code < 300:
                return {"nom": nom, "statut": "soumis", "detail": (r.json() or {}).get("status") or "PENDING"}
            detail = _message_erreur(r)
            if deja_existant(detail):
                return {"nom": nom, "statut": "existe déjà", "detail": detail}
        return {"nom": nom, "statut": "erreur", "detail": detail}
    finally:
        if propre:
            await http.aclose()


async def lire_statut(*, version: str, waba_id: str, jeton: str, nom: str, langue: str,
                      client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    """Statut actuel chez Meta : {statut: ABSENT | PENDING | APPROVED | REJECTED…, motif}. Ne lève jamais."""
    propre = client is None
    http = client or httpx.AsyncClient(timeout=20)
    try:
        r = await http.get(f"https://graph.facebook.com/{version}/{waba_id}/message_templates",
                           params={"name": nom, "fields": "name,status,language,rejected_reason", "limit": 50},
                           headers={"Authorization": f"Bearer {jeton}"})
        if r.status_code >= 300:
            return {"statut": "INCONNU", "motif": None, "erreur": _message_erreur(r)}
        for m in (r.json() or {}).get("data") or []:
            if m.get("name") == nom and (m.get("language") or langue) == langue:
                motif = str(m.get("rejected_reason") or "")
                return {"statut": str(m.get("status") or "PENDING").upper(),
                        "motif": motif if motif and motif.upper() != "NONE" else None, "erreur": None}
        return {"statut": "ABSENT", "motif": None, "erreur": None}
    except httpx.HTTPError as exc:
        return {"statut": "INCONNU", "motif": None, "erreur": f"Réseau : {type(exc).__name__}"}
    finally:
        if propre:
            await http.aclose()
