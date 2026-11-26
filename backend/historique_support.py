# historique_support.py — Lot 467 : « Chat interne » de l'Historique Conversation (fils du Support Loois) avec la DURÉE de l'assistance (logique, sans accès réseau).
#
# Demande du propriétaire : sur la page « Historique Conversation », d'abord les conversations WhatsApp (lot 466), puis un BLOC À PART pour le chat interne du support
# (espace « Support Loois » : un fil par poste Loois), avec, comme pour WhatsApp, une sélection par client et par poste, les messages horodatés du plus récent au plus
# ancien, l'impression PDF et l'export CSV, et la DURÉE de chaque session d'assistance (de l'acceptation par l'agent à la fin ; base de la facturation).
#
# Données (déjà existantes, aucune nouvelle collection) :
#   - `support_loois_sessions` : une session = une demande d'assistance d'un poste (demande_le, acceptee_le, terminee_le, client_nom, poste_id, poste_nom, ticket_number…) ;
#   - `internal_chat_messages` (client_id = "support-loois") : messages du fil d'un poste (sender_id / recipient_id = identifiant du poste).
# Un message est rattaché à la session de son poste dont la période le contient (de la demande à la fin, sans dépasser la demande suivante du même poste).
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from historique_conversations import date_fr, neutraliser

ESPACE = "support-loois"
MAX_POSTES = 100
MAX_MESSAGES = 5000
ENTETE_CSV = ["Date et heure", "Client", "Poste", "Émetteur", "Session (ticket)", "Durée de l'assistance", "Statut de la session", "Message"]
STATUTS = {"attente": "en attente", "active": "en cours", "terminee": "terminée", "refusee": "refusée", "abandonnee": "abandonnée"}
LOIN = "9999-12-31T23:59:59+00:00"


def _date(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def duree_fr(secondes: Optional[int]) -> str:
    """« 754 » → « 12 min 34 s » ; « 3725 » → « 1 h 02 min » ; « — » si la session n'a jamais été acceptée."""
    if secondes is None:
        return "—"
    s = max(0, int(secondes))
    if s >= 3600:
        return f"{s // 3600} h {(s % 3600) // 60:02d} min"
    return f"{s // 60} min {s % 60:02d} s" if s >= 60 else f"{s} s"


def duree_session(session: Dict[str, Any], maintenant: datetime) -> Optional[int]:
    """Durée de l'assistance : acceptation → fin (ou maintenant si la session est encore active) ; None si jamais acceptée."""
    debut = _date(session.get("acceptee_le"))
    if not debut:
        return None
    fin = _date(session.get("terminee_le")) or maintenant
    return max(0, int((fin - debut).total_seconds()))


def ligne_session(s: Dict[str, Any], maintenant: datetime) -> Dict[str, Any]:
    """Une session d'assistance, prête pour l'écran, le PDF et le CSV."""
    d = duree_session(s, maintenant)
    return {"id": s.get("id") or "", "poste_id": s.get("poste_id") or "", "poste": s.get("poste_nom") or "Poste sans nom", "client": s.get("client_nom") or "",
            "ticket": s.get("ticket_number") or "", "agent": s.get("acceptee_par_nom") or "", "statut": STATUTS.get(s.get("statut"), str(s.get("statut") or "")),
            "demande_le_iso": str(s.get("demande_le") or ""), "demande_le": date_fr(s.get("demande_le")), "debut": date_fr(s.get("acceptee_le")) if s.get("acceptee_le") else "—",
            "fin": date_fr(s.get("terminee_le")) if s.get("terminee_le") else "—", "duree_s": d, "duree": duree_fr(d)}


def total_durees(sessions: List[Dict[str, Any]]) -> int:
    return sum(x["duree_s"] or 0 for x in sessions)


def fenetres(sessions: List[Dict[str, Any]]) -> Dict[str, List[Tuple[str, str, Dict[str, Any]]]]:
    """Par poste : (début, fin, session) triées ; la fin est la fin réelle, limitée à la demande suivante du même poste."""
    par_poste: Dict[str, List[Dict[str, Any]]] = {}
    for s in sessions:
        par_poste.setdefault(s["poste_id"], []).append(s)
    sortie: Dict[str, List[Tuple[str, str, Dict[str, Any]]]] = {}
    for pid, lst in par_poste.items():
        lst.sort(key=lambda x: x["demande_le_iso"])
        res = []
        for i, s in enumerate(lst):
            suivante = lst[i + 1]["demande_le_iso"] if i + 1 < len(lst) else LOIN
            fin = s.get("_fin_iso") or LOIN
            res.append((s["demande_le_iso"], min(fin, suivante) if suivante else fin, s))
        sortie[pid] = res
    return sortie


def session_du_message(created_at: str, liste: List[Tuple[str, str, Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """Session (parmi celles d'un poste) dont la période contient ce message ; la plus récente si plusieurs."""
    trouvee = None
    for debut, fin, s in liste:
        if debut <= created_at <= fin:
            trouvee = s
    return trouvee


def texte_chat(m: Dict[str, Any]) -> str:
    """Texte d'un message du chat ; pièce jointe signalée par son type et son nom."""
    t = str(m.get("text") or "").strip()
    if m.get("media_kind"):
        return f"[{m['media_kind']} joint{' : ' + str(m['file_name']) if m.get('file_name') else ''}] {t}".strip()
    return t


def ligne_message(m: Dict[str, Any], s: Dict[str, Any]) -> Dict[str, Any]:
    """Un message du chat interne, rattaché à sa session ; `sens` = « Poste » (utilisateur Loois) ou le nom de l'agent / de Liluvine."""
    du_poste = m.get("sender_id") == s["poste_id"]
    return {"id": m.get("id") or "", "quand_iso": str(m.get("created_at") or ""), "quand": date_fr(m.get("created_at")), "contact": s["poste"], "client": s["client"],
            "sens": "Poste" if du_poste else (m.get("sender_name") or "Support"), "session": s["ticket"] or "—", "duree": s["duree"], "statut": s["statut"],
            "message": texte_chat(m), "telephone": "", "type": "", "contact_id": s["poste_id"]}


def construire_csv(lignes: List[Dict[str, Any]], sessions: List[Dict[str, Any]]) -> bytes:
    """CSV « Excel français » (« ; », UTF-8 avec BOM) : un bloc de messages (plus récent d'abord) puis le récapitulatif des sessions avec leurs durées."""
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=";", lineterminator="\r\n")
    w.writerow(ENTETE_CSV)
    for x in lignes:
        w.writerow([neutraliser(v) for v in (x["quand"], x["client"], x["contact"], x["sens"], x["session"], x["duree"], x["statut"], x["message"])])
    w.writerow([])
    w.writerow(["RÉCAPITULATIF DES SESSIONS D'ASSISTANCE"])
    w.writerow(["Ticket", "Poste", "Agent", "Demande", "Début", "Fin", "Durée", "Statut"])
    for x in sessions:
        w.writerow([neutraliser(v) for v in (x["ticket"], x["poste"], x["agent"], x["demande_le"], x["debut"], x["fin"], x["duree"], x["statut"])])
    w.writerow(["Total", f"{len(sessions)} session(s)", "", "", "", "", duree_fr(total_durees(sessions)), ""])
    return ("﻿" + sortie.getvalue()).encode("utf-8")


def recap_pdf(sessions: List[Dict[str, Any]]) -> Tuple[List[str], List[List[str]], List[str]]:
    """Tableau récapitulatif pour le PDF : (en-têtes, lignes, ligne de total)."""
    en_tete = ["Ticket", "Poste", "Agent", "Début", "Fin", "Durée", "Statut"]
    lignes = [[x["ticket"] or "—", x["poste"], x["agent"] or "—", x["debut"], x["fin"], x["duree"], x["statut"]] for x in sessions]
    return en_tete, lignes, ["Total", f"{len(sessions)} session(s)", "", "", "", duree_fr(total_durees(sessions)), ""]


# ------------------------------------------------------------------------------------------------------------------------ lecture
def _filtre_client(client: str) -> Dict[str, Any]:
    """Client de la session (nom enregistré à l'acceptation), sans tenir compte des majuscules."""
    return {"client_nom": {"$regex": "^" + re.escape(client.strip()) + "$", "$options": "i"}}


async def clients_avec_sessions(db) -> List[Dict[str, Any]]:
    """Clients ayant eu au moins une session d'assistance : [{client, sessions}], triés par nom (une seule lecture)."""
    cumul: Dict[str, Dict[str, Any]] = {}
    async for s in db.support_loois_sessions.find({"client_nom": {"$nin": [None, ""]}}, {"_id": 0, "client_nom": 1}):
        nom = str(s["client_nom"]).strip()
        c = cumul.setdefault(nom.lower(), {"client": nom, "sessions": 0})
        c["sessions"] += 1
    return sorted(cumul.values(), key=lambda c: c["client"].lower())


async def postes_du_client(db, client: str) -> List[Dict[str, Any]]:
    """Postes ayant eu au moins une session d'assistance pour ce client : [{id, nom, sessions}], triés par nom (une seule lecture)."""
    if not client.strip():
        return []
    cumul: Dict[str, Dict[str, Any]] = {}
    async for s in db.support_loois_sessions.find(_filtre_client(client), {"_id": 0, "poste_id": 1, "poste_nom": 1}):
        p = cumul.setdefault(s.get("poste_id") or "", {"id": s.get("poste_id") or "", "nom": s.get("poste_nom") or "Poste sans nom", "sessions": 0})
        p["sessions"] += 1
    return sorted((p for p in cumul.values() if p["id"]), key=lambda p: p["nom"].lower())[:MAX_POSTES * 3]


async def collecter(db, *, client: str, poste_ids: List[str], du: str = "", au: str = "", limite: int = MAX_MESSAGES,
                    maintenant: Optional[datetime] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], bool]:
    """(sessions, messages, tronqué) : sessions du client pour les postes choisis (période = date de la demande), puis leurs messages du plus récent au plus ancien.
    Une lecture des sessions, une lecture groupée des messages (règle 7)."""
    maintenant = maintenant or datetime.now(timezone.utc)
    if not poste_ids or not client.strip():
        return [], [], False
    filtre: Dict[str, Any] = {**_filtre_client(client), "poste_id": {"$in": list(poste_ids)}}
    if du or au:
        filtre["demande_le"] = {**({"$gte": du} if du else {}), **({"$lte": au + "T99"} if au else {})}
    brutes = await db.support_loois_sessions.find(filtre, {"_id": 0}).to_list(2000)
    sessions: List[Dict[str, Any]] = []
    for b in brutes:
        s = ligne_session(b, maintenant)
        s["_fin_iso"] = str(b.get("terminee_le") or b.get("refusee_le") or b.get("abandonnee_le") or "")
        sessions.append(s)
    if not sessions:
        return [], [], False
    sessions.sort(key=lambda x: x["demande_le_iso"], reverse=True)
    wins = fenetres(sessions)
    debut = min(x["demande_le_iso"] for x in sessions)
    ids = sorted({x["poste_id"] for x in sessions})
    q = {"client_id": ESPACE, "$or": [{"sender_id": {"$in": ids}}, {"recipient_id": {"$in": ids}}], "created_at": {"$gte": debut}}
    bruts = await db.internal_chat_messages.find(q, {"_id": 0}).sort("created_at", -1).limit(limite + 1).to_list(limite + 1)
    tronque = len(bruts) > limite
    lignes: List[Dict[str, Any]] = []
    for m in bruts[:limite]:
        pid = m.get("sender_id") if m.get("sender_id") in wins else m.get("recipient_id")
        s = session_du_message(str(m.get("created_at") or ""), wins.get(pid, []))
        if s:
            lignes.append(ligne_message(m, s))
    lignes.sort(key=lambda x: x["quand_iso"], reverse=True)
    for s in sessions:
        s.pop("_fin_iso", None)
    return sessions, lignes, tronque
