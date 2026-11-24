"""consignes_masse.py — ENVOIS EN MASSE demandés par une consigne à Liluvine (lot 456).

Règle du propriétaire : un message à tout un groupe (ex. « décalage d'1 h pour tous les RDV de demain ») est TOUJOURS confirmé avant l'envoi :
  1) APERÇU  : SAWALI choisit les destinataires (rendez-vous du jour ou de la période) et MONTRE qui, combien, quel texte ; rien ne part.
  2) CONFIRMATION : la personne confirme l'aperçu (valable 15 minutes, lié à CET aperçu : liste et texte ne peuvent plus changer).
  3) ENVOI en arrière-plan (règle 7), message après message ; le résultat se consulte (envoyés / hors fenêtre / bloqués / échecs).
Sécurité : les contacts de la liste noire WhatsApp sont exclus ; un numéro n'est contacté qu'une fois ; WhatsApp n'accepte le texte libre que dans la
fenêtre de 24 h : les autres contacts sont LISTÉS « non envoyé » (jamais un envoi forcé ni un modèle choisi à notre place). 200 destinataires au plus.
Stockage : une seule fiche de `settings` (`liluvine_masse`), aucune nouvelle collection (cluster plein).
"""
from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

MAX_DESTINATAIRES = 200
VALIDITE_APERCU_MIN = 15
MAX_LOTS_GARDES = 20
MAX_TEXTE = 1000
ID_FICHE = "liluvine_masse"
STATUTS_EXCLUS = ("cancelled", "canceled", "annule", "annulé", "refused", "refuse", "refusé")


def _chiffres(v: Any) -> str:
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def _jour(v: Any) -> str:
    """« 2026-11-25T09:30:00+00:00 » → « 2026-11-25 » ('' si illisible)."""
    s = str(v or "")[:10]
    return s if len(s) == 10 and s[4] == "-" and s[7] == "-" else ""


def choisir_destinataires(rdvs: List[Dict[str, Any]], du: str, au: str, bloques: frozenset = frozenset()) -> Dict[str, Any]:
    """Fonction PURE : parmi les rendez-vous, garde ceux de la période [du, au] (AAAA-MM-JJ), non annulés, avec un numéro valable, hors liste noire, un seul par numéro (8 derniers chiffres).
    Rend {destinataires: [{nom, telephone, quand}], exclus: {sans_numero, bloques, annules, doublons}}."""
    exclus = {"sans_numero": 0, "bloques": 0, "annules": 0, "doublons": 0}
    vus: set = set()
    sortie: List[Dict[str, str]] = []
    for r in sorted(rdvs, key=lambda x: str(x.get("scheduled_at") or "")):
        j = _jour(r.get("scheduled_at"))
        if not j or j < du or j > au:
            continue
        if str(r.get("status") or "").lower() in STATUTS_EXCLUS:
            exclus["annules"] += 1
            continue
        tel = _chiffres(r.get("whatsapp") or r.get("phone"))
        if len(tel) < 8:
            exclus["sans_numero"] += 1
            continue
        cle = tel[-8:]
        if cle in bloques:
            exclus["bloques"] += 1
            continue
        if cle in vus:
            exclus["doublons"] += 1
            continue
        vus.add(cle)
        sortie.append({"nom": str(r.get("name") or "")[:80], "telephone": tel, "quand": str(r.get("scheduled_at") or "")[:16].replace("T", " ")})
    return {"destinataires": sortie, "exclus": exclus}


def empreinte(message: str, destinataires: List[Dict[str, str]]) -> str:
    """Empreinte du message ET de la liste : la confirmation n'est valable que pour CET aperçu exact."""
    base = message + "|" + ",".join(d["telephone"] for d in destinataires)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]


def valider_periode(du: Any, au: Any) -> tuple:
    """Dates AAAA-MM-JJ cohérentes (au ≥ du, 31 jours au plus) ou ValueError."""
    d, a = _jour(du), _jour(au or du)
    if not d or not a:
        raise ValueError("Précisez la période des rendez-vous (de AAAA-MM-JJ à AAAA-MM-JJ)")
    if a < d:
        raise ValueError("La fin de la période est avant son début")
    if (datetime.fromisoformat(a) - datetime.fromisoformat(d)).days > 31:
        raise ValueError("La période est limitée à 31 jours")
    return d, a


async def _fiche(db) -> Dict[str, Any]:
    f = await db["settings"].find_one({"_id": ID_FICHE}) or {}
    f.setdefault("apercus", [])
    f.setdefault("lots", [])
    return f


async def _ecrire(db, fiche: Dict[str, Any]) -> None:
    fiche["apercus"] = fiche["apercus"][-10:]
    fiche["lots"] = fiche["lots"][-MAX_LOTS_GARDES:]
    await db["settings"].update_one({"_id": ID_FICHE}, {"$set": {"apercus": fiche["apercus"], "lots": fiche["lots"]}}, upsert=True)


async def apercu(db, message: str, du: Any, au: Any, par: str, instant: Optional[datetime] = None) -> Dict[str, Any]:
    """ÉTAPE 1 : choisit les destinataires et MONTRE ; rien ne part. Garde l'aperçu (15 min) pour la confirmation."""
    message = " ".join(str(message or "").split())[:MAX_TEXTE]
    if len(message) < 5:
        raise ValueError("Écrivez le message à envoyer")
    d, a = valider_periode(du, au)
    from liste_noire_wa import cles_bloquees
    rdvs = await db.appointments.find({"scheduled_at": {"$gte": d, "$lte": a + "T99"}}, {"_id": 0}).to_list(5000)
    choix = choisir_destinataires(rdvs, d, a, await cles_bloquees(db))
    dest = choix["destinataires"]
    if not dest:
        raise ValueError("Aucun destinataire : aucun rendez-vous avec un numéro valable sur cette période")
    if len(dest) > MAX_DESTINATAIRES:
        raise ValueError(f"{len(dest)} destinataires : au plus {MAX_DESTINATAIRES} par envoi (réduisez la période)")
    instant = instant or datetime.now(timezone.utc)
    ap = {"id": uuid.uuid4().hex[:12], "message": message, "du": d, "au": a, "destinataires": dest, "exclus": choix["exclus"], "empreinte": empreinte(message, dest),
          "par": par, "cree_le": instant.isoformat(), "expire_le": (instant + timedelta(minutes=VALIDITE_APERCU_MIN)).isoformat(), "utilise": False}
    f = await _fiche(db)
    f["apercus"].append(ap)
    await _ecrire(db, f)
    return ap


def masquer(tel: str) -> str:
    """Numéro partiellement masqué pour l'affichage de l'aperçu."""
    return tel[:3] + "*" * max(0, len(tel) - 5) + tel[-2:] if len(tel) > 5 else tel


async def confirmer(db, identifiant: str, empreinte_vue: str, par: str, envoyeur, fenetre, instant: Optional[datetime] = None) -> Dict[str, Any]:
    """ÉTAPE 2 : la personne a vu l'aperçu et confirme. Vérifie (aperçu connu, non expiré, non déjà utilisé, empreinte identique), crée le lot puis lance l'envoi EN ARRIÈRE-PLAN.
    `envoyeur(tel, texte) -> dict{ok,error}` et `fenetre(tel) -> bool` sont injectés (tests sans réseau)."""
    instant = instant or datetime.now(timezone.utc)
    f = await _fiche(db)
    ap = next((x for x in f["apercus"] if x.get("id") == identifiant), None)
    if not ap:
        raise ValueError("Aperçu introuvable : refaites l'aperçu avant d'envoyer")
    if ap.get("utilise"):
        raise ValueError("Cet aperçu a déjà été envoyé")
    if datetime.fromisoformat(ap["expire_le"]) < instant:
        raise ValueError("L'aperçu a expiré (15 minutes) : refaites l'aperçu")
    if ap["empreinte"] != empreinte_vue:
        raise ValueError("L'aperçu a changé : relisez-le avant de confirmer")
    ap["utilise"] = True
    lot = {"id": ap["id"], "message": ap["message"], "du": ap["du"], "au": ap["au"], "par": par, "confirme_le": instant.isoformat(), "total": len(ap["destinataires"]),
           "envoyes": 0, "hors_fenetre": 0, "echecs": 0, "termine": False, "details": []}
    f["lots"].append(lot)
    await _ecrire(db, f)
    asyncio.get_event_loop().create_task(_envoyer_tout(db, ap, envoyeur, fenetre))      # règle 7 : jamais dans la requête
    return {k: v for k, v in lot.items() if k != "details"}


async def _envoyer_tout(db, ap: Dict[str, Any], envoyeur, fenetre) -> None:
    """Envoi message après message ; une panne sur un numéro n'arrête pas les autres. Résultat gardé dans le lot."""
    compte = {"envoyes": 0, "hors_fenetre": 0, "echecs": 0}
    details: List[Dict[str, str]] = []
    for d in ap["destinataires"]:
        try:
            if not await fenetre(d["telephone"]):
                compte["hors_fenetre"] += 1
                details.append({"tel": masquer(d["telephone"]), "etat": "non envoyé : hors fenêtre de 24 h (modèle Meta nécessaire)"})
                continue
            r = await envoyeur(d["telephone"], ap["message"])
            if r.get("ok"):
                compte["envoyes"] += 1
            else:
                compte["echecs"] += 1
                details.append({"tel": masquer(d["telephone"]), "etat": str(r.get("error") or "échec")[:120]})
        except Exception as exc:  # noqa: BLE001
            compte["echecs"] += 1
            details.append({"tel": masquer(d["telephone"]), "etat": str(exc)[:120]})
        await asyncio.sleep(0.3)             # cadence douce : jamais de rafale
    f = await _fiche(db)
    for lot in f["lots"]:
        if lot["id"] == ap["id"]:
            lot.update(compte)
            lot["details"] = details[:50]
            lot["termine"] = True
    await _ecrire(db, f)


async def lots(db) -> List[Dict[str, Any]]:
    """Derniers envois (le plus récent d'abord)."""
    return list(reversed((await _fiche(db))["lots"]))
