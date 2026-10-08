# retards_paiement.py — Lot 79.7 : retards de paiement en UN récapitulatif numéroté, relance au choix.
#
# Avant : chaque matin (08:15), un WhatsApp + un e-mail au propriétaire PAR client en retard (6 clients = 6 messages).
# Maintenant (mode « récapitulatif », par défaut) :
#   1. Liluvine envoie au propriétaire UN seul message : la liste numérotée des clients en retard
#        « 1) Pharmacie X — 12 j de retard — 50 000 FCFA · 2) … — Répondez « ok 1,2,5 » pour les relancer »
#      (texte libre si le propriétaire a écrit à la ligne SAWALI depuis moins de 24 h, sinon le modèle Meta
#       « relais » du lot 67 à 3 variables : qui, message, date) ;
#   2. le propriétaire répond depuis son WhatsApp :  « ok 1,2,5 »  ou  « ok tous » ;
#   3. Liluvine relance CES clients-là (WhatsApp : texte libre dans leur fenêtre de 24 h, sinon le modèle Meta
#      de relance déclaré dans les Paramètres ; e-mail en complément) puis confirme au propriétaire :
#        « ✅ Relance envoyée : 1 Pharmacie X, 2 … · ⚠️ 5 : WhatsApp impossible (…) ».
# Réglages (db.settings {_id: "global"}, Paramètres → « Contrats — Seuil de retard de paiement ») :
#   contract_overdue_mode : "recap" (défaut) | "detail" (ancien : un message par client) | "off" (aucun message)
#   contract_relance_wa_template / contract_relance_wa_language : modèle Meta de la relance au client,
#     4 variables : {{1}} nom du client, {{2}} jours de retard, {{3}} n° de contrat, {{4}} montant.
# Le dernier récapitulatif est gardé dans db.settings {_id: "retards_paiement_recap"} (aucune nouvelle collection :
# la base est limitée en nombre de collections) avec le journal des relances (200 dernières).
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("sawali.retards_paiement")

DOC_RECAP = "retards_paiement_recap"        # _id du document de suivi dans db.settings
JOURNAL_MAX = 200                           # relances gardées dans le journal
MODES = ("recap", "detail", "off")
# Réponse du propriétaire : « ok 1,2,5 », « OK 1 2 5 », « ok 1 et 3 », « ok tous »
MOTIF_REPONSE = re.compile(r"^\s*ok\b[\s:,-]*(?P<choix>(?:tous|tout|\d+)(?:\s*(?:,|;|et|&|-|\s)\s*\d+)*)\s*[.!]?\s*$",
                           re.IGNORECASE)


def mode_alertes(s: Dict[str, Any]) -> str:
    """Mode des alertes de retard : récapitulatif (défaut), détail (ancien comportement) ou aucune."""
    m = str((s or {}).get("contract_overdue_mode") or "recap").strip().lower()
    return m if m in MODES else "recap"


def _chiffres(valeur: Any) -> str:
    """Garde uniquement les chiffres d'un numéro."""
    return re.sub(r"\D", "", str(valeur or ""))


def _nom(t: Dict[str, Any]) -> str:
    """Nom affiché d'un client (société, sinon nom, sinon e-mail)."""
    return (t.get("company") or t.get("full_name") or t.get("email") or "Client").strip()


def _montant(t: Dict[str, Any]) -> str:
    """Montant du contrat lisible (« 50000 FCFA ») ou « — »."""
    return f"{t.get('contract_amount') or ''} {t.get('contract_currency') or ''}".strip() or "—"


def elements_recap(retards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Liste numérotée (du plus gros retard au plus petit) gardée pour interpréter « ok 1,2,5 »."""
    tries = sorted(retards, key=lambda t: -int(t.get("days_overdue") or 0))
    return [{"n": i, "tenant_id": t.get("id"), "nom": _nom(t), "jours": int(t.get("days_overdue") or 0),
             "contrat": t.get("contract_number") or "—", "montant": _montant(t),
             "email": (t.get("email") or "").strip().lower(),
             "telephone": _chiffres(t.get("whatsapp_number") or t.get("phone"))}
            for i, t in enumerate(tries, start=1)]


def texte_recap(elements: List[Dict[str, Any]], une_ligne: bool = False) -> str:
    """Texte du récapitulatif. une_ligne=True pour un modèle Meta (retours à la ligne interdits)."""
    lignes = [f"{e['n']}) {e['nom']} — {e['jours']} j de retard — {e['montant']}" for e in elements]
    consigne = "Répondez « ok 1,2,5 » (ou « ok tous ») pour relancer ces clients."
    if une_ligne:
        return f"{len(elements)} client(s) en retard de paiement : " + " · ".join(lignes) + f" — {consigne}"
    return (f"💰 {len(elements)} client(s) en retard de paiement :\n" + "\n".join(lignes) + f"\n\n{consigne}")


def lire_choix(texte: Optional[str], nombre: int) -> Optional[Tuple[List[int], List[str]]]:
    """« ok 1,2,5 » → ([1, 2, 5], [numéros invalides]) ; « ok tous » → tous ; None si ce n'est pas une réponse."""
    m = MOTIF_REPONSE.match(texte or "")
    if not m:
        return None
    choix = m.group("choix").strip().lower()
    if choix in ("tous", "tout"):
        return list(range(1, nombre + 1)), []
    valides, invalides = [], []
    for brut in re.findall(r"\d+", choix):
        n = int(brut)
        if 1 <= n <= nombre:
            if n not in valides:
                valides.append(n)
        else:
            invalides.append(brut)
    return valides, invalides


def texte_relance(e: Dict[str, Any]) -> str:
    """Message de relance envoyé au client (texte libre)."""
    return (f"Bonjour {e['nom']},\n\nSauf erreur de notre part, le règlement de votre abonnement SAWALI SMART SYSTEMS "
            f"(contrat {e['contrat']}, {e['montant']}) est en retard de {e['jours']} jour(s).\n"
            "Merci de régulariser dès que possible pour éviter toute interruption de service. "
            "Si le paiement a déjà été effectué, merci d'ignorer ce message.\n\nL'équipe SAWALI SMART SYSTEMS.")


async def _lire_recap(db) -> Dict[str, Any]:
    """Dernier récapitulatif envoyé (document de suivi dans db.settings)."""
    return await db.settings.find_one({"_id": DOC_RECAP}) or {}


async def envoyer_recap(db, s: Dict[str, Any], retards: List[Dict[str, Any]], *,
                        envoyer_email: Optional[Callable[..., Awaitable[Any]]] = None,
                        email_proprio: str = "", maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Envoie UN récapitulatif numéroté au propriétaire (WhatsApp + e-mail) et le mémorise.
    Une seule fois par jour (un second passage le même jour ne renvoie rien)."""
    from routes import appel_proprietaire as ap
    maintenant = maintenant or datetime.now(timezone.utc)
    jour = maintenant.date().isoformat()
    if not retards:
        return {"envoye": False, "raison": "aucun client en retard"}
    precedent = await _lire_recap(db)
    if precedent.get("jour") == jour and precedent.get("whatsapp_ok"):
        return {"envoye": False, "raison": "récapitulatif déjà envoyé aujourd'hui"}
    elements = elements_recap(retards)
    proprio = _chiffres(s.get("super_admin_phone"))
    resultat: Dict[str, Any] = {"envoye": False, "whatsapp_ok": False, "email_ok": False, "erreur": None}
    if proprio:
        cfg = ap.reglages(s)
        numero_id, _ligne = ap.ligne_appelante(s, cfg)
        r = await ap.envoyer_relais(db, s, cfg, numero_id, proprio, texte_recap(elements),
                                    ["Liluvine — retards de paiement", texte_recap(elements, une_ligne=True),
                                     ap.formater_date(maintenant)], maintenant)
        resultat["whatsapp_ok"], resultat["erreur"] = bool(r.get("ok")), r.get("erreur")
    else:
        resultat["erreur"] = "numéro WhatsApp du propriétaire absent (Paramètres → Contrats)"
    if envoyer_email and email_proprio:
        try:
            resultat["email_ok"] = bool(await envoyer_email(
                email_proprio, f"[SAWALI] {len(elements)} client(s) en retard de paiement", texte_recap(elements)))
        except Exception as exc:  # noqa: BLE001 — l'e-mail ne bloque jamais le WhatsApp
            logger.warning("[retards] e-mail du récapitulatif en échec : %s", exc)
    resultat["envoye"] = resultat["whatsapp_ok"] or resultat["email_ok"]
    await db.settings.update_one({"_id": DOC_RECAP}, {"$set": {
        "jour": jour, "envoye_le": maintenant.isoformat(), "proprio": proprio, "elements": elements,
        "whatsapp_ok": resultat["whatsapp_ok"], "email_ok": resultat["email_ok"], "erreur": resultat["erreur"]}},
        upsert=True)
    logger.info("[retards] récapitulatif : %d client(s), WhatsApp=%s, e-mail=%s%s", len(elements),
                resultat["whatsapp_ok"], resultat["email_ok"],
                f" ({resultat['erreur']})" if resultat["erreur"] else "")
    return resultat


def _est_proprietaire(s: Dict[str, Any], chiffres: str) -> bool:
    """Le numéro qui écrit est-il celui du propriétaire (alerte de retard ou appels de Liluvine) ?"""
    from routes.appel_proprietaire import numeros_proprietaire
    fin = _chiffres(chiffres)[-8:]
    if len(fin) < 8:
        return False
    connus = [_chiffres(s.get("super_admin_phone"))] + [_chiffres(n) for n in numeros_proprietaire(s)]
    return any(c and c[-8:] == fin for c in connus)


async def relancer_client(db, s: Dict[str, Any], e: Dict[str, Any], *,
                          envoyer_email: Optional[Callable[..., Awaitable[Any]]] = None,
                          maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Relance UN client : WhatsApp (texte libre dans sa fenêtre de 24 h, sinon modèle Meta de relance),
    e-mail en complément. → {"ok", "whatsapp", "email", "erreur"}."""
    from routes import appel_proprietaire as ap
    maintenant = maintenant or datetime.now(timezone.utc)
    res: Dict[str, Any] = {"ok": False, "whatsapp": False, "email": False, "erreur": None}
    tel = e.get("telephone") or ""
    if len(tel) >= 8:
        cfg = ap.reglages(s)
        numero_id, _ligne = ap.ligne_appelante(s, cfg)
        modele = (s.get("contract_relance_wa_template") or "").strip()
        langue = (s.get("contract_relance_wa_language") or "fr").strip() or "fr"
        if await ap.fenetre_24h_ouverte(db, tel, numero_id, maintenant):
            corps = {"messaging_product": "whatsapp", "to": tel, "type": "text",
                     "text": {"body": texte_relance(e), "preview_url": False}}
        elif modele:
            corps = {"messaging_product": "whatsapp", "to": tel, "type": "template",
                     "template": {"name": modele, "language": {"code": langue}, "components": [
                         {"type": "body", "parameters": [{"type": "text", "text": str(v)[:200] or "—"}
                                                         for v in (e["nom"], e["jours"], e["contrat"], e["montant"])]}]}}
        else:
            corps = None
            res["erreur"] = ("fenêtre WhatsApp de 24 h fermée et aucun modèle de relance déclaré "
                             "(Paramètres → Contrats)")
        if corps:
            r = await ap._graph_post(s, numero_id, "messages", corps)
            res["whatsapp"], res["erreur"] = bool(r.get("ok")), r.get("erreur")
    else:
        res["erreur"] = "aucun numéro WhatsApp sur la fiche"
    if envoyer_email and e.get("email"):
        try:
            res["email"] = bool(await envoyer_email(e["email"], "[SAWALI] Rappel de paiement", texte_relance(e)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[retards] e-mail de relance en échec : %s", exc)
    res["ok"] = res["whatsapp"] or res["email"]
    return res


async def traiter_reponse(db, s: Dict[str, Any], chiffres: str, texte: Optional[str], *,
                          envoyer_email: Optional[Callable[..., Awaitable[Any]]] = None,
                          maintenant: Optional[datetime] = None) -> Optional[str]:
    """Appelé par le webhook WhatsApp pour chaque message texte reçu. Si c'est la réponse « ok 1,2,5 »
    du propriétaire à un récapitulatif : relance les clients choisis et renvoie le texte de confirmation ;
    sinon None (message ordinaire, traité normalement)."""
    if not texte or not MOTIF_REPONSE.match(texte) or not _est_proprietaire(s, chiffres):
        return None
    recap = await _lire_recap(db)
    elements = recap.get("elements") or []
    if not elements:
        return "Aucun récapitulatif de retards de paiement en attente."
    choix = lire_choix(texte, len(elements))
    if choix is None:
        return None
    valides, invalides = choix
    maintenant = maintenant or datetime.now(timezone.utc)
    reussis, echecs, journal = [], [], []
    for n in valides:
        e = elements[n - 1]
        r = await relancer_client(db, s, e, envoyer_email=envoyer_email, maintenant=maintenant)
        (reussis if r["ok"] else echecs).append(f"{n} {e['nom']}" + ("" if r["ok"] else f" ({r['erreur']})"))
        journal.append({"le": maintenant.isoformat(), "n": n, "tenant_id": e.get("tenant_id"), "nom": e["nom"],
                        "whatsapp": r["whatsapp"], "email": r["email"], "erreur": r["erreur"]})
    if journal:
        await db.settings.update_one({"_id": DOC_RECAP}, {"$push": {"relances": {"$each": journal,
                                                                               "$slice": -JOURNAL_MAX}}})
    logger.info("[retards] relance demandée par le propriétaire : %d réussie(s), %d échec(s)",
                len(reussis), len(echecs))
    morceaux = []
    if reussis:
        morceaux.append("✅ Relance envoyée : " + ", ".join(reussis))
    if echecs:
        morceaux.append("⚠️ Non relancé(s) : " + " ; ".join(echecs))
    if invalides:
        morceaux.append(f"❓ Numéro(s) inconnu(s) : {', '.join(invalides)} (liste de 1 à {len(elements)})")
    return "\n".join(morceaux) or "Aucun client choisi."
