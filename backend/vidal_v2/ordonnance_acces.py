"""Lot 383 (pharmacie, lot P1) — accès à l'ordonnance sécurisée par l'officine (QR ou étiquette NFC) : validité, révocation, clôture, journal d'accès, lien NFC.
Logique pure : aucun réseau, aucune base (testée par tests/test_lot383_pharmacie_p1.py).

Règles :
  - une ordonnance est VALABLE `ORDONNANCE_VALIDITE_JOURS` jours (30 par défaut) après son émission ;
  - le prescripteur peut la RÉVOQUER (perdue, annulée, erreur) ; elle n'est alors plus servable ;
  - dès qu'elle est ENTIÈREMENT SERVIE, elle est CLÔTURÉE : lisible, mais plus aucun retour n'est accepté ;
  - chaque lecture, service ou refus est JOURNALISÉ (date, canal QR ou NFC, adresse masquée) ; une réutilisation anormale est signalée au prescripteur.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

UTC = timezone.utc
VALIDITE_JOURS_DEFAUT = 30
CAPACITES_ETIQUETTES = {"NTAG213": 144, "NTAG215": 504, "NTAG216": 888}     # octets utiles (norme NDEF)
SEUIL_IP_24H = 5                       # plus de 5 adresses différentes en 24 h = réutilisation suspecte
SEUIL_LECTURES_1H = 30                 # plus de 30 lectures en 1 h = réutilisation suspecte


def validite_jours() -> int:
    """Durée de validité d'une ordonnance (jours) : variable d'environnement ORDONNANCE_VALIDITE_JOURS (1 à 365), 30 par défaut."""
    try:
        return max(1, min(365, int(os.environ.get("ORDONNANCE_VALIDITE_JOURS", VALIDITE_JOURS_DEFAUT))))
    except ValueError:
        return VALIDITE_JOURS_DEFAUT


def _aware(d: Any) -> Optional[datetime]:
    """Date avec fuseau (MongoDB rend des dates sans fuseau : ce sont des dates UTC)."""
    if not isinstance(d, datetime):
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def date_expiration(doc: Dict[str, Any]) -> Optional[datetime]:
    """Date limite de l'ordonnance : `expire_le` si elle existe, sinon émission + durée de validité (ordonnances imprimées avant ce lot)."""
    exp = _aware(doc.get("expire_le"))
    if exp:
        return exp
    cree = _aware(doc.get("created_at"))
    return cree + timedelta(days=validite_jours()) if cree else None


def etat_acces(doc: Dict[str, Any], maintenant: datetime) -> Dict[str, Any]:
    """État d'accès pour l'officine : code « ok », « revoquee », « expiree » ou « cloturee », avec le message à afficher. Ordre de priorité : révoquée, expirée, clôturée."""
    exp = date_expiration(doc)
    base = {"expire_le": exp.isoformat() if exp else None}
    if doc.get("revoquee"):
        return {"code": "revoquee", "message": "Cette ordonnance a été annulée par le prescripteur. Ne la servez pas : contactez-le.", **base}
    if exp and _aware(maintenant) > exp:
        return {"code": "expiree", "message": f"Cette ordonnance a expiré le {exp.strftime('%d/%m/%Y')}. Demandez au patient une nouvelle ordonnance.", **base}
    if doc.get("etat_service") == "servie":
        return {"code": "cloturee", "message": "Cette ordonnance a déjà été entièrement servie : aucun nouveau retour n'est possible.", **base}
    return {"code": "ok", "message": "", **base}


def masquer_ip(ip: Optional[str]) -> str:
    """Adresse masquée pour le journal : le dernier octet IPv4 (a.b.c.x) ou les 3 premiers groupes IPv6 ; jamais l'adresse complète."""
    ip = (ip or "").strip()
    if not ip:
        return "inconnue"
    if ":" in ip:
        return ":".join(ip.split(":")[:3]) + "::x"
    p = ip.split(".")
    return ".".join(p[:3]) + ".x" if len(p) == 4 else "inconnue"


def adresse_client(en_tete_xff: Optional[str], hote: Optional[str]) -> str:
    """Adresse du client : premier élément de X-Forwarded-For (derrière le proxy de Render), sinon l'hôte de la connexion."""
    if en_tete_xff:
        return en_tete_xff.split(",")[0].strip()
    return hote or ""


def canal(src: Optional[str]) -> str:
    """Canal d'accès indiqué par le lien : « nfc » (étiquette) ou « qr » (par défaut). Information déclarative : ne donne aucun droit."""
    return "nfc" if (src or "").lower() == "nfc" else "qr"


def analyse_acces(acces: List[Dict[str, Any]], maintenant: datetime) -> Dict[str, Any]:
    """Résumé du journal d'accès d'une ordonnance : nombre d'événements, dernier accès, adresses distinctes sur 24 h, et réutilisation suspecte."""
    maintenant = _aware(maintenant)
    lectures = [a for a in acces if a.get("action") in ("lecture", "service")]
    dates = [_aware(a.get("date")) for a in lectures if _aware(a.get("date"))]
    ips = {a.get("ip_masquee") for a in lectures if _aware(a.get("date")) and maintenant - _aware(a["date"]) <= timedelta(hours=24)}
    heure = sum(1 for d in dates if maintenant - d <= timedelta(hours=1))
    motif = None
    if len(ips) > SEUIL_IP_24H:
        motif = f"{len(ips)} adresses différentes en 24 h"
    elif heure > SEUIL_LECTURES_1H:
        motif = f"{heure} lectures en 1 heure"
    return {"nombre": len(lectures), "dernier": max(dates).isoformat() if dates else None, "adresses_24h": len(ips), "suspect": motif is not None, "motif": motif}


# ---- Étiquette NFC ----
_PREFIXES_URI = (("https://www.", 0x02), ("http://www.", 0x01), ("https://", 0x04), ("http://", 0x03))


def url_nfc(url_officine: str) -> str:
    """Lien écrit sur l'étiquette : celui du QR avec « ?src=nfc » (le journal distingue ainsi les deux canaux)."""
    return f"{url_officine}{'&' if '?' in url_officine else '?'}src=nfc"


def taille_ndef_url(url: str) -> int:
    """Octets occupés sur l'étiquette par un enregistrement NDEF « URI » (préfixe compressé) avec son enveloppe : à comparer à la capacité (NTAG213 = 144 octets)."""
    reste = url
    for prefixe, _code in _PREFIXES_URI:
        if url.startswith(prefixe):
            reste = url[len(prefixe):]
            break
    charge = 1 + len(reste.encode("utf-8"))                       # code de préfixe + texte
    enregistrement = 1 + 1 + (1 if charge < 256 else 4) + 1 + charge   # drapeaux, longueur du type, longueur de la charge, type « U », charge
    enveloppe = 1 + (1 if enregistrement < 255 else 3) + 1       # balise 0x03, longueur, balise de fin 0xFE
    return enregistrement + enveloppe


def compatibilite_etiquettes(url: str) -> Dict[str, Any]:
    """Pour chaque type d'étiquette courant : le lien tient-il dedans ?"""
    n = taille_ndef_url(url)
    return {"octets": n, "etiquettes": {nom: {"capacite": cap, "tient": n <= cap} for nom, cap in CAPACITES_ETIQUETTES.items()}}
