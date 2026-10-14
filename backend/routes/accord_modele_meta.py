# accord_modele_meta.py — Lot 165 : modèle WhatsApp (Meta) de DEMANDE D'ACCORD avec bouton « lien personnel ».
#
# Contexte : un bouton de modèle avec une adresse FIXE (ex. le lien wa.me) ne peut pas porter le lien personnel de
# chaque contact. Ce modèle a un bouton URL DYNAMIQUE  <site>/accord/{{1}}  : au moment de l'envoi, SAWALI y met le
# jeton de la personne (routes/accord_page.py) et la personne ouvre SA page d'accord.
#   - STRUCTURE calquée sur le modèle « envoidemandeaccordcarroussel » DÉJÀ APPROUVÉ par Meta (14/10/2026) :
#     titre (texte), corps, pied de page, bouton URL dynamique « OUI, j'accepte », bouton de réponse « NON » ;
#   - corps : UNE seule variable  {{1}} = prénom (moins de variables = moins de risque de refus) ;
#   - catégorie MARKETING (la demande vise l'envoi de nouveautés et d'offres) ;
#   - bouton URL « OUI, j'accepte » → <site>/accord/{{1}} (jeton personnel) ;
#   - bouton de réponse « NON, pas intéressé(e) » : SAWALI y attache l'identifiant `accord_wa:non` à l'envoi, et le
#     webhook note le refus (la personne n'est plus jamais sollicitée).
# Ce module ne fait QUE créer le modèle chez Meta et lire son statut : aucun message n'est envoyé aux contacts.
# Aucun secret n'est écrit dans les journaux ; le jeton n'est jamais renvoyé au navigateur.
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("sawali.accord_modele_meta")

NOM_DEFAUT = "sawali_accord_lien"
# Une variable n'est jamais au tout début ni à la toute fin du texte (règle Meta)
TEXTE_TITRE = "Nous avons besoin de votre ACCORD"
TEXTE_CORPS = ("Bonjour {{1}},\n\n"
               "Cliquez sur le bouton OUI pour nous autoriser à vous envoyer nos nouveautés et offres sur WhatsApp, "
               "ou sur NON si vous ne le souhaitez pas.\n\n"
               "C'est gratuit et sans engagement : vous pourrez arrêter à tout moment en écrivant STOP.\n\n"
               "SAWALI SMART SYSTEMS")
EXEMPLE_CORPS = ["Awa"]
TEXTE_PIED = "SAWALI SMART SYSTEMS - Service de Communications"
TEXTE_BOUTON = "OUI, j'accepte"
TEXTE_BOUTON_NON = "NON, pas intéressé(e)"
PAYLOAD_NON = "accord_wa:non"      # même identifiant que le bouton « Non merci » des messages libres (accord_whatsapp.py)
EXEMPLE_JETON = "exemple"


def definition_modele(nom: str, langue: str, url_bouton: str, *, exemple_url_complete: bool = True) -> Dict[str, Any]:
    """Corps JSON envoyé à POST /{waba-id}/message_templates. Meta documente l'exemple du bouton comme une adresse
    COMPLÈTE ; certaines versions acceptent seulement le suffixe : `exemple_url_complete` choisit la forme."""
    exemple = url_bouton.replace("{{1}}", EXEMPLE_JETON) if exemple_url_complete else EXEMPLE_JETON
    return {
        "name": nom, "language": langue, "category": "MARKETING",
        "components": [
            {"type": "HEADER", "format": "TEXT", "text": TEXTE_TITRE},
            {"type": "BODY", "text": TEXTE_CORPS, "example": {"body_text": [EXEMPLE_CORPS]}},
            {"type": "FOOTER", "text": TEXTE_PIED},
            {"type": "BUTTONS", "buttons": [
                {"type": "URL", "text": TEXTE_BOUTON, "url": url_bouton, "example": [exemple]},
                {"type": "QUICK_REPLY", "text": TEXTE_BOUTON_NON},
            ]},
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
