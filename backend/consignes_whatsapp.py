"""consignes_whatsapp.py — CONSIGNES À LILUVINE DONNÉES PAR WHATSAPP (lot 457).

Un numéro AUTORISÉ par l'administrateur (Paramètres → « Consignes à Liluvine — numéros WhatsApp autorisés », actif) peut écrire à Liluvine :
    « consigne : jusqu'à lundi, aucune intervention entre 12h et 13h »
Comme à l'écran, RIEN n'est actif avant la confirmation : Liluvine répond par ce qu'elle a compris (nature, période, créneau) et attend « OUI » (ou « NON »).
Pour un envoi en masse, il y a DEUX temps : « OUI » pour voir la liste (nombre, texte, exclus) puis « OUI » pour envoyer (la réponse « OUI » ne vaut que pour l'aperçu qui vient d'être montré).
Sécurité (règle 21) :
  - seul un numéro de la liste (actif) est écouté ; tout autre message suit le traitement habituel ;
  - le déclencheur est EXPLICITE (« consigne… », « consigne : … ») : une phrase ordinaire du responsable n'est jamais prise pour une consigne ;
  - une proposition en attente expire en 15 minutes ; une réponse « OUI » sans proposition récente ne fait rien ;
  - un numéro lié à un client précis (tenant) ne peut pas faire d'envoi en masse (les RDV ne sont pas cloisonnés par client) ;
  - jamais le texte des consignes dans les journaux.
Stockage : une fiche de `settings` (`liluvine_consignes_wa`, propositions en attente), aucune nouvelle collection.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

import consignes_liluvine as cl
import consignes_masse as cm

ID_ATTENTE = "liluvine_consignes_wa"
VALIDITE_MIN = 15
DECLENCHEUR = re.compile(r"^\s*!?\s*consignes?\s*[:\-–]?\s*(.+)$", re.I | re.S)
OUI = {"oui", "o", "ok", "d'accord", "daccord", "valider", "valide", "confirme", "confirmer", "envoyer", "envoie", "yes"}
NON = {"non", "n", "annuler", "annule", "stop", "no"}


def _mot(texte: str) -> str:
    """Réponse normalisée (sans accents, sans ponctuation finale, minuscules)."""
    t = unicodedata.normalize("NFD", str(texte or "")).encode("ascii", "ignore").decode().lower().strip()
    return re.sub(r"[\s.!]+$", "", t)


def extraire_consigne(texte: str) -> Optional[str]:
    """Phrase de la consigne si le message commence par « consigne » (avec ou sans « : »), sinon None."""
    m = DECLENCHEUR.match(str(texte or ""))
    if not m:
        return None
    phrase = m.group(1).strip()
    return phrase if len(phrase) >= 3 else None


def reponse_oui_non(texte: str) -> Optional[bool]:
    """True = oui, False = non, None = autre chose."""
    m = _mot(texte)
    return True if m in OUI or m.replace("é", "e") in OUI else (False if m in NON else None)


def resume_proposition(p: Dict[str, Any]) -> str:
    """Ce que Liluvine a compris, en clair, pour la personne qui doit confirmer."""
    lignes = [f"Voici ce que j'ai compris ({cl.NATURES.get(p['nature'], p['nature'])}) :", f"« {p['instruction']} »", f"Du {p['debut'].replace('T', ' à ')} au {p['fin'].replace('T', ' à ')} (heure du Burkina Faso)."]
    if p["nature"] == "blocage":
        lignes.append(f"Créneau bloqué : de {p.get('creneau_debut') or '?'} à {p.get('creneau_fin') or '?'}.")
    return "\n".join(lignes)


async def _fiche(db) -> Dict[str, Any]:
    f = await db["settings"].find_one({"_id": ID_ATTENTE}) or {}
    f.setdefault("attente", {})
    return f


async def _poser(db, cle: str, valeur: Optional[Dict[str, Any]]) -> None:
    f = await _fiche(db)
    if valeur is None:
        f["attente"].pop(cle, None)
    else:
        f["attente"][cle] = valeur
    await db["settings"].update_one({"_id": ID_ATTENTE}, {"$set": {"attente": f["attente"]}}, upsert=True)


async def traiter(db, numero: Any, texte: str, instant: Optional[datetime] = None, interpreter: Optional[Callable[[str], Awaitable[Dict[str, Any]]]] = None,
                  envoyeurs: Optional[tuple] = None) -> Optional[str]:
    """Point d'entrée : rend le TEXTE À RÉPONDRE si le message a été pris en charge (numéro autorisé ET consigne ou réponse à une proposition en attente), sinon None
    (le traitement habituel de Liluvine continue). `interpreter` et `envoyeurs` sont injectables pour les tests (aucun accès réseau)."""
    acces = await cl.numero_autorise(db, numero)
    if not acces:
        return None
    instant = instant or datetime.now(timezone.utc)
    cle = acces["cle"]
    f = await _fiche(db)
    attente = f["attente"].get(cle)
    if attente and datetime.fromisoformat(attente["expire_le"]) < instant:
        await _poser(db, cle, None)
        attente = None
    phrase = extraire_consigne(texte)
    par = f"WhatsApp {acces.get('nom') or acces['numero']}"

    # --- réponse à une proposition en attente
    if attente and phrase is None:
        rep = reponse_oui_non(texte)
        if rep is None:
            return None                                           # autre sujet : traitement habituel
        await _poser(db, cle, None)
        if not rep:
            return "D'accord, la consigne est annulée. Rien n'a été activé ni envoyé."
        try:
            if attente["etape"] == "consigne":
                fiche = await cl.creer(db, attente["proposition"], attente["texte"], par, tenant=acces.get("tenant") or "", tenants=acces.get("tenants") or [])
                return f"✅ Consigne activée (n° {fiche['id']}). Liluvine l'applique dès maintenant. Pour l'arrêter : écran Liluvine → Consignes."
            if attente["etape"] == "masse_apercu":                # 1er OUI : montrer la liste (deuxième temps de confirmation)
                ap = await cm.apercu(db, attente["message"], attente["rdv_du"], attente["rdv_au"], par, instant)
                await _poser(db, cle, {"etape": "masse_envoi", "apercu_id": ap["id"], "empreinte": ap["empreinte"], "expire_le": (instant + timedelta(minutes=VALIDITE_MIN)).isoformat()})
                ex = ap["exclus"]
                return (f"📣 {len(ap['destinataires'])} destinataire(s) pour les RDV du {ap['du']} au {ap['au']}.\nMessage : « {ap['message']} »\n"
                        f"Exclus : {ex['sans_numero']} sans numéro, {ex['bloques']} bloqués, {ex['annules']} annulés, {ex['doublons']} doublon(s).\nRépondez OUI pour ENVOYER maintenant, NON pour annuler.")
            if attente["etape"] == "masse_envoi":                 # 2e OUI : envoi en arrière-plan
                envoyeur, fenetre, modeleur = envoyeurs or cm.envoyeurs_serveur()
                lot = await cm.confirmer(db, attente["apercu_id"], attente["empreinte"], par, envoyeur, fenetre, instant, modeleur=modeleur)
                return f"✅ Envoi lancé pour {lot['total']} personne(s). Le suivi est dans l'écran Liluvine → Consignes → « Envois en masse »."
        except ValueError as exc:
            return f"⚠️ {exc}"
        return None

    # --- nouvelle consigne
    if phrase is None:
        return None
    try:
        prop = await (interpreter or cl.interpreter)(phrase)
    except ValueError as exc:
        return f"⚠️ {exc}"
    expire = (instant + timedelta(minutes=VALIDITE_MIN)).isoformat()
    if prop["nature"] == "masse":
        if cl.tenants_de(acces):                                  # lot 462 : lié à UN OU PLUSIEURS clients
            return "⚠️ Les envois en masse ne sont pas permis à un numéro lié à un client précis. Demandez à l'administrateur."
        if not prop.get("message") or not prop.get("rdv_du"):
            return "⚠️ Pour un envoi à un groupe, précisez le message et le jour des rendez-vous (ex. « consigne : écris à tous les RDV de demain que… »)."
        await _poser(db, cle, {"etape": "masse_apercu", "message": prop["message"], "rdv_du": prop["rdv_du"], "rdv_au": prop.get("rdv_au") or prop["rdv_du"], "expire_le": expire})
        return (f"📣 Envoi à un groupe : RDV du {prop['rdv_du']} au {prop.get('rdv_au') or prop['rdv_du']}.\nMessage : « {prop['message']} »\n"
                "Rien n'est envoyé. Répondez OUI pour voir la liste des destinataires, NON pour annuler (valable 15 minutes).")
    if not prop.get("appliquee"):
        return "⚠️ Cette nature de consigne n'est pas encore appliquée par SAWALI : rien n'a été activé."
    if prop["nature"] == "blocage" and not (prop.get("creneau_debut") and prop.get("creneau_fin")):
        return "⚠️ Je n'ai pas compris le créneau (ex. « entre 12h et 13h »). Reformulez la consigne."
    await _poser(db, cle, {"etape": "consigne", "proposition": {k: v for k, v in prop.items() if k not in ("ia", "appliquee", "envoi_masse")}, "texte": phrase, "expire_le": expire})
    return resume_proposition(prop) + "\nRépondez OUI pour ACTIVER, NON pour annuler (valable 15 minutes)."
