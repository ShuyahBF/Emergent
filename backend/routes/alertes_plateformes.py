# alertes_plateformes.py — Lot 352 : les pannes des plateformes externes remontent à l'ADMINISTRATEUR seul.
#
# Demande du propriétaire (29/10/2026) : « ça fait trop de plateformes à suivre » — un défaut de paiement chez Meta, un jeton expiré,
# un compte restreint… ne doivent plus être découverts par hasard ; SAWALI les détecte et les signale à l'administrateur.
#
# Source de ce premier lot : les ÉCHECS D'ENVOI WhatsApp (erreurs Meta enregistrées sur `whatsapp_messages.wa_error_code`).
# Seuls les codes qui bloquent TOUT le compte sont retenus (paiement, compte verrouillé, jeton, numéro non enregistré, blocage de
# politique) : les limites par destinataire (131047 « re-engagement », 131049 « healthy ecosystem »…) sont normales et ignorées.
#
# Historique PAR LIGNE (identifiant du numéro de téléphone Meta, « Phone Number ID » : Standard, VIP, ALBARKA…) : pour chaque ligne,
# envois, échecs par jour et par code d'erreur Meta (30 jours par défaut) et alertes concernées, imprimable en PDF (copie pour Meta,
# la comptabilité…). Chaque message porte le Phone Number ID de la ligne qui l'a envoyé (`wa_numero_id`) ; un message sans identifiant
# est rattaché à la ligne principale. Le compte WABA (`wa_business_account_id`, un seul pour toutes les lignes) est rappelé en tête.
# Le moyen de paiement se règle par COMPTE (WABA) : une alerte de paiement touche donc toutes les lignes en même temps.
#
# Fonctionnement : une tâche (toutes les 10 min) lit les échecs de l'heure écoulée :
#   - un code critique apparaît → alerte OUVERTE (bandeau rouge sur les pages /admin pour l'administrateur + e-mail, car WhatsApp
#     lui-même est en panne : le canal ne doit pas dépendre de lui) ; rappel par e-mail toutes les 12 h tant qu'elle reste ouverte ;
#   - plus d'échec depuis 60 min ET un envoi réussi depuis → alerte FERMÉE automatiquement (« rétablie ») ; fermeture manuelle possible.
# Les alertes sont gardées dans le document `alertes_plateformes` de `settings` (aucune nouvelle collection MongoDB).
# Un autre contrôle (Atlas, Render, Qdrant…) s'ajoute en appelant `ouvrir_ou_mettre_a_jour` avec sa propre clé.
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger("sawali.alertes_plateformes")

DOC_ID = "alertes_plateformes"
FENETRE_ECHECS_MIN = 60          # échecs pris en compte : la dernière heure
RAPPEL_HEURES = 12               # rappel par e-mail tant que l'alerte reste ouverte
RETABLI_APRES_MIN = 60           # aucun échec depuis ce délai (et un envoi réussi) → alerte rétablie
HISTORIQUE_MAX = 30

# Codes d'erreur Meta qui bloquent tout le compte WhatsApp Business — titre, que faire, où.
CODES_CRITIQUES: Dict[int, Dict[str, str]] = {
    131042: {"titre": "WhatsApp : moyen de paiement refusé ou absent",
             "action": "Meta Business Suite → WhatsApp Manager → Paramètres de paiement : ajoutez ou réactivez la carte du compte WhatsApp Business.",
             "plateforme": "Meta — WhatsApp Business"},
    131031: {"titre": "WhatsApp : compte verrouillé ou restreint",
             "action": "Meta Business Suite → Qualité du compte / Centre d'assistance : consultez la restriction et suivez la procédure de réactivation.",
             "plateforme": "Meta — WhatsApp Business"},
    190: {"titre": "WhatsApp : jeton d'accès expiré ou invalide",
          "action": "Meta for Developers → créez un nouveau jeton permanent (utilisateur système) puis remplacez-le dans les réglages WhatsApp de SAWALI.",
          "plateforme": "Meta — WhatsApp Business"},
    133010: {"titre": "WhatsApp : numéro non enregistré",
             "action": "WhatsApp Manager → Numéros de téléphone : réenregistrez le numéro (code de vérification).",
             "plateforme": "Meta — WhatsApp Business"},
    368: {"titre": "WhatsApp : compte temporairement bloqué (politique de Meta)",
          "action": "Meta Business Suite → Centre d'assistance : consultez la notification de violation et faites appel si besoin.",
          "plateforme": "Meta — WhatsApp Business"},
}


# Codes d'échec courants (pas tous critiques) : libellé court pour l'historique imprimé.
LIBELLES_CODES: Dict[int, str] = {
    131042: "Moyen de paiement du compte refusé ou absent",
    131031: "Compte verrouillé ou restreint",
    190: "Jeton d'accès expiré ou invalide",
    133010: "Numéro non enregistré",
    368: "Compte bloqué temporairement (politique de Meta)",
    131047: "Hors fenêtre de 24 h : un modèle approuvé est nécessaire",
    131049: "Message non remis (qualité de l'écosystème / limite par destinataire)",
    131026: "Message non remis (destinataire injoignable ou sans WhatsApp)",
    131056: "Trop de messages vers ce destinataire (limite de débit)",
    130429: "Limite de débit du compte atteinte",
    131048: "Limite d'envoi pour signalements de spam",
    132000: "Paramètres du modèle incorrects",
    132001: "Modèle introuvable ou non approuvé",
}


def libelle_code(code: Any) -> str:
    try:
        return LIBELLES_CODES.get(int(code), "Erreur Meta (voir le code)")
    except (TypeError, ValueError):
        return "Erreur Meta (voir le code)"


def carte_lignes(s: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Lignes WhatsApp par Phone Number ID avec leur WABA ID (fonction pure). La ligne principale est sous la clé « principale »
    si son identifiant n'est pas renseigné ; un message sans identifiant de ligne est rattaché à la principale."""
    waba_global = str(s.get("wa_business_account_id") or "").strip() or "non renseigné"
    principal = str(s.get("wa_phone_number_id") or "").strip()
    carte: Dict[str, Dict[str, Any]] = {principal or "principale": {
        "phone_number_id": principal, "libelle": str(s.get("wa_principal_libelle") or "").strip() or "Liluvine Standard",
        "telephone": str(s.get("wa_principal_telephone") or "").strip(), "waba_id": waba_global, "principale": True}}
    for brut in s.get("wa_numeros") or []:
        if not isinstance(brut, dict):
            continue
        pid = str(brut.get("id") or brut.get("phone_number_id") or "").strip()
        if not pid or pid in carte:
            continue
        carte[pid] = {"phone_number_id": pid, "libelle": str(brut.get("libelle") or "").strip() or f"Ligne {pid[-4:]}",
                      "telephone": str(brut.get("telephone") or "").strip(), "principale": False,
                      "waba_id": str(brut.get("waba_id") or brut.get("wa_business_account_id") or "").strip() or waba_global}
    return carte


def waba_du_message(carte: Dict[str, Dict[str, Any]], numero_id: Any) -> str:
    """WABA ID d'un message d'après la ligne qui l'a envoyé (message sans ligne → ligne principale). Fonction pure."""
    pid = str(numero_id or "").strip()
    if pid and pid in carte:
        return carte[pid]["waba_id"]
    principale = next((l for l in carte.values() if l.get("principale")), None)
    return (principale or {}).get("waba_id") or "non renseigné"


def ligne_du_message(carte: Dict[str, Dict[str, Any]], numero_id: Any) -> str:
    """Clé (Phone Number ID) de la ligne d'un message ; un message sans identifiant ou inconnu → ligne principale. Fonction pure."""
    pid = str(numero_id or "").strip()
    if pid and pid in carte:
        return pid
    return next((k for k, l in carte.items() if l.get("principale")), next(iter(carte), "principale"))


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def cle_alerte(code: int, waba_id: str = "") -> str:
    return f"meta-{int(code)}-{re.sub(r'[^0-9A-Za-z_-]', '', waba_id or 'inconnu')}"


def decrire_code(code: Any) -> Optional[Dict[str, str]]:
    """Description d'un code d'erreur Meta critique, ou None si le code n'est pas critique (fonction pure)."""
    try:
        return CODES_CRITIQUES.get(int(code))
    except (TypeError, ValueError):
        return None


def texte_email(alerte: Dict[str, Any], rappel: bool = False) -> Dict[str, str]:
    """Sujet et corps HTML de l'e-mail à l'administrateur (fonction pure)."""
    debut = "Rappel : " if rappel else ""
    sujet = f"🚨 {debut}{alerte['titre']}"
    corps = (f"<h2>🚨 {alerte['titre']}</h2>"
             f"<p><strong>Plateforme :</strong> {alerte.get('plateforme') or '—'}<br>"
             f"<strong>Compte WABA :</strong> {alerte.get('waba_id') or '—'}<br>"
             f"<strong>Depuis :</strong> {alerte.get('depuis', '')[:16].replace('T', ' ')} UTC<br>"
             f"<strong>Lignes touchées :</strong> {', '.join(f'{k} ({n})' for k, n in (alerte.get('lignes') or {}).items()) or '—'}<br>"
             f"<strong>Messages en échec :</strong> {alerte.get('nombre', 0)} (code Meta {alerte.get('code')})</p>"
             f"<p><strong>Que faire :</strong> {alerte.get('action') or ''}</p>"
             "<p>Dès que le problème est réglé, l'alerte se ferme toute seule après le premier envoi réussi.</p>"
             "<p style='color:#64748b;font-size:.85rem'>— SAWALI Smart Systems · Alertes plateformes</p>")
    return {"sujet": sujet, "corps": corps}


async def _etat(db) -> Dict[str, Any]:
    return await db.settings.find_one({"_id": DOC_ID}) or {}


async def ouvrir_ou_mettre_a_jour(db, send_email, *, cle: str, code: Any, titre: str, action: str, plateforme: str,
                                  nombre: int, derniere: str, maintenant: Optional[datetime] = None, waba_id: str = "",
                                  lignes: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """Ouvre l'alerte `cle` ou la met à jour ; envoie l'e-mail à l'ouverture puis un rappel toutes les 12 h. Jamais d'exception."""
    maintenant = maintenant or _maintenant()
    etat = await _etat(db)
    ouvertes = dict(etat.get("ouvertes") or {})
    a = ouvertes.get(cle)
    nouvelle = a is None
    if nouvelle:
        a = {"cle": cle, "code": code, "titre": titre, "action": action, "plateforme": plateforme, "waba_id": waba_id,
             "depuis": maintenant.isoformat(), "email_le": None}
    a.update({"nombre": nombre, "derniere": derniere, "vue_le": maintenant.isoformat(), "lignes": dict(lignes or a.get("lignes") or {})})
    envoyer = nouvelle
    if not nouvelle and a.get("email_le"):
        try:
            envoyer = maintenant - datetime.fromisoformat(a["email_le"]) >= timedelta(hours=RAPPEL_HEURES)
        except ValueError:
            envoyer = True
    elif not nouvelle:
        envoyer = True
    if envoyer and send_email is not None:
        try:
            from routes.llm_health import SUPER_ADMIN_EMAIL
            mail = texte_email(a, rappel=not nouvelle)
            if await send_email(to_email=SUPER_ADMIN_EMAIL, subject=mail["sujet"], html_body=mail["corps"],
                                text_body=re.sub(r"<[^>]+>", "", mail["corps"])):
                a["email_le"] = maintenant.isoformat()
        except Exception:  # noqa: BLE001 — l'alerte reste affichée même si l'e-mail échoue
            logger.warning("[alertes_plateformes] e-mail non envoyé (%s)", cle, exc_info=True)
    ouvertes[cle] = a
    await db.settings.update_one({"_id": DOC_ID}, {"$set": {"ouvertes": ouvertes}}, upsert=True)
    return {"cle": cle, "nouvelle": nouvelle, "email_envoye": bool(a.get("email_le")) and envoyer}


async def fermer(db, cle: str, motif: str, maintenant: Optional[datetime] = None) -> bool:
    """Ferme une alerte (rétablie automatiquement ou réglée à la main) et la range dans l'historique."""
    maintenant = maintenant or _maintenant()
    etat = await _etat(db)
    ouvertes = dict(etat.get("ouvertes") or {})
    a = ouvertes.pop(cle, None)
    if a is None:
        return False
    historique = [{**a, "fermee_le": maintenant.isoformat(), "motif": motif}] + list(etat.get("historique") or [])
    await db.settings.update_one({"_id": DOC_ID}, {"$set": {"ouvertes": ouvertes, "historique": historique[:HISTORIQUE_MAX]}}, upsert=True)
    return True


async def surveiller(db, send_email=None, maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Un passage de contrôle (tâche toutes les 10 min) : ouvre / met à jour les alertes, ferme celles qui sont rétablies."""
    maintenant = maintenant or _maintenant()
    bilan: Dict[str, Any] = {"ouvertes": [], "fermees": []}
    try:
        depuis = (maintenant - timedelta(minutes=FENETRE_ECHECS_MIN)).isoformat()
        carte = carte_lignes(await db.settings.find_one({"_id": "global"}) or {})
        echecs = await db.whatsapp_messages.find(
            {"direction": "outbound", "wa_status": "failed", "wa_error_code": {"$in": list(CODES_CRITIQUES)}, "created_at": {"$gte": depuis}},
            {"_id": 0, "wa_error_code": 1, "created_at": 1, "wa_numero_id": 1}).to_list(5000)
        groupes: Dict[Any, Dict[str, Any]] = {}
        for m in echecs:
            code = int(m["wa_error_code"])
            waba = waba_du_message(carte, m.get("wa_numero_id"))
            g = groupes.setdefault((code, waba), {"nombre": 0, "derniere": "", "lignes": {}})
            g["nombre"] += 1
            cle_l = ligne_du_message(carte, m.get("wa_numero_id"))
            g["lignes"][cle_l] = g["lignes"].get(cle_l, 0) + 1
            g["derniere"] = max(g["derniere"], m.get("created_at") or "")
        for (code, waba), g in groupes.items():
            d = CODES_CRITIQUES[code]
            cle = cle_alerte(code, waba)
            await ouvrir_ou_mettre_a_jour(db, send_email, cle=cle, code=code, titre=d["titre"], action=d["action"], plateforme=d["plateforme"],
                                          nombre=g["nombre"], derniere=g["derniere"], maintenant=maintenant, waba_id=waba, lignes=g["lignes"])
            bilan["ouvertes"].append(cle)
        # alertes rétablies : plus d'échec depuis RETABLI_APRES_MIN et au moins un envoi réussi (par une ligne du MÊME WABA) depuis
        for cle, a in list(((await _etat(db)).get("ouvertes") or {}).items()):
            if not cle.startswith("meta-") or cle in bilan["ouvertes"]:
                continue
            derniere = a.get("derniere") or a.get("depuis") or ""
            try:
                ancien = maintenant - datetime.fromisoformat(derniere.replace("Z", "+00:00")) >= timedelta(minutes=RETABLI_APRES_MIN)
            except ValueError:
                ancien = True
            if not ancien:
                continue
            filtre: Dict[str, Any] = {"direction": "outbound", "wa_status": {"$in": ["sent", "delivered", "read"]}, "created_at": {"$gt": derniere}}
            ids = [pid for pid, l in carte.items() if l["waba_id"] == a.get("waba_id") and l.get("phone_number_id")]
            principale_ici = any(l.get("principale") and l["waba_id"] == a.get("waba_id") for l in carte.values())
            if ids or principale_ici:
                cond: List[Dict[str, Any]] = [{"wa_numero_id": {"$in": ids}}]
                if principale_ici:
                    cond.append({"wa_numero_id": {"$in": [None, ""]}})
                filtre["$or"] = cond
            if await db.whatsapp_messages.count_documents(filtre, limit=1):
                if await fermer(db, cle, "rétablie : envois réussis", maintenant):
                    bilan["fermees"].append(cle)
    except Exception:  # noqa: BLE001 — la tâche ne doit jamais tomber
        logger.warning("[alertes_plateformes] passage de contrôle échoué", exc_info=True)
        bilan["erreur"] = True
    return bilan


async def historique_par_ligne(db, jours: int = 30, ligne: Optional[str] = None) -> Dict[str, Any]:
    """Historique PAR LIGNE (Phone Number ID) sur `jours` jours : envois, échecs, échecs par jour et par code d'erreur Meta, alertes."""
    jours = max(1, min(int(jours or 30), 365))
    maintenant = _maintenant()
    depuis = (maintenant - timedelta(days=jours)).isoformat()
    s = await db.settings.find_one({"_id": "global"}) or {}
    carte = carte_lignes(s)
    etat = await _etat(db)
    vide = lambda l: {"phone_number_id": l.get("phone_number_id"), "cle": None, "libelle": l.get("libelle"), "telephone": l.get("telephone"),  # noqa: E731
                      "principale": bool(l.get("principale")), "waba_id": l.get("waba_id"), "envois": 0, "echecs": 0,
                      "par_jour": {}, "par_code": {}, "alertes": []}
    lignes: Dict[str, Dict[str, Any]] = {}
    for cle, l in carte.items():
        lignes[cle] = {**vide(l), "cle": cle}
    sortants = await db.whatsapp_messages.find(
        {"direction": "outbound", "created_at": {"$gte": depuis}, "wa_status": {"$in": ["sent", "delivered", "read", "failed"]}},
        {"_id": 0, "wa_status": 1, "wa_error_code": 1, "created_at": 1, "wa_numero_id": 1}).to_list(50000)
    for m in sortants:
        cle = ligne_du_message(carte, m.get("wa_numero_id"))
        w = lignes.get(cle) or lignes.setdefault(cle, {**vide({"phone_number_id": cle, "libelle": f"Ligne {cle[-4:]}"}), "cle": cle})
        w["envois"] += 1
        if m.get("wa_status") != "failed":
            continue
        w["echecs"] += 1
        jour = (m.get("created_at") or "")[:10]
        code = m.get("wa_error_code")
        j = w["par_jour"].setdefault(jour, {"date": jour, "echecs": 0, "codes": {}})
        j["echecs"] += 1
        j["codes"][str(code)] = j["codes"].get(str(code), 0) + 1
        c = w["par_code"].setdefault(str(code), {"code": code, "libelle": libelle_code(code), "critique": decrire_code(code) is not None,
                                                  "nombre": 0, "premiere": m.get("created_at"), "derniere": m.get("created_at")})
        c["nombre"] += 1
        c["premiere"] = min(c["premiere"] or "", m.get("created_at") or "") or c["premiere"]
        c["derniere"] = max(c["derniere"] or "", m.get("created_at") or "")
    toutes = list((etat.get("ouvertes") or {}).values()) + list(etat.get("historique") or [])
    for a in toutes:
        if (a.get("depuis") or "") < depuis:
            continue
        for cle in (a.get("lignes") or {}):
            if cle in lignes:
                lignes[cle]["alertes"].append({k: a.get(k) for k in ("titre", "code", "depuis", "fermee_le", "motif", "waba_id")}
                                              | {"nombre": a["lignes"][cle], "ouverte": not a.get("fermee_le")})
    sortie = []
    for w in lignes.values():
        if ligne and w["cle"] != ligne and w.get("phone_number_id") != ligne:
            continue
        w["par_jour"] = sorted(w["par_jour"].values(), key=lambda x: x["date"], reverse=True)
        w["par_code"] = sorted(w["par_code"].values(), key=lambda x: -x["nombre"])
        w["alertes"].sort(key=lambda x: x.get("depuis") or "", reverse=True)
        sortie.append(w)
    waba = str(s.get("wa_business_account_id") or "").strip() or None
    return {"jours": jours, "genere_le": maintenant.isoformat(), "waba_id": waba, "lignes": sortie}


def pdf_historique(donnees: Dict[str, Any]) -> bytes:
    """PDF A4 de l'historique par ligne : une page par ligne (identité, totaux, alertes, échecs par code, échecs par jour)."""
    import io
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    petit = ParagraphStyle("petit", parent=styles["Normal"], fontSize=8, leading=10)
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, leading=9.5)
    sortie = io.BytesIO()
    doc = SimpleDocTemplate(sortie, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title="Historique WhatsApp par ligne", author="SAWALI Smart Systems")

    def esc(t: Any) -> str:
        return str(t if t is not None else "—").replace("&", "&amp;").replace("<", "&lt;")

    def tableau(lignes: List[List[Any]], largeurs: List[float]):
        entete = ParagraphStyle("entete", parent=cell, textColor=colors.white, fontName="Helvetica-Bold")      # en-tête blanc sur bleu
        t = Table([[Paragraph(esc(c), entete if i == 0 else cell) for c in l] for i, l in enumerate(lignes)], colWidths=largeurs, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#b8c2d0")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5fb")])]))
        return t

    corps: List[Any] = [Paragraph("<b>Historique des envois WhatsApp par ligne</b>", styles["Title"]),
                        Paragraph(f"Période : {donnees['jours']} derniers jours · édité le {esc(donnees['genere_le'][:16].replace('T', ' '))} UTC"
                                  + (f" · compte WABA : {esc(donnees.get('waba_id'))}" if donnees.get("waba_id") else ""), petit)]
    if not donnees["lignes"]:
        corps.append(Paragraph("Aucune ligne.", styles["Normal"]))
    for i, w in enumerate(donnees["lignes"]):
        if i:
            corps.append(PageBreak())
        taux = f"{100 * w['echecs'] / w['envois']:.1f} %" if w["envois"] else "—"
        corps += [Spacer(1, 4 * mm),
                  Paragraph(f"<b>{esc(w['libelle'])}</b>" + (" (ligne principale)" if w.get("principale") else ""), styles["Heading2"]),
                  Paragraph(f"Téléphone : <b>{esc(w.get('telephone') or '—')}</b> · ID du numéro de téléphone (Phone Number ID) : "
                            f"<b>{esc(w.get('phone_number_id') or '—')}</b>", styles["Normal"]),
                  Paragraph(f"Envois : <b>{w['envois']}</b> · échecs : <b>{w['echecs']}</b> ({taux})", styles["Normal"]),
                  Spacer(1, 3 * mm), Paragraph("<b>Alertes</b>", styles["Heading3"])]
        corps.append(tableau([["Ouverte le", "Alerte", "Code", "Messages", "État"]] + [
            [(a.get("depuis") or "")[:16].replace("T", " "), a.get("titre"), a.get("code"), a.get("nombre"),
             "ouverte" if a.get("ouverte") else f"fermée le {(a.get('fermee_le') or '')[:10]} ({a.get('motif') or ''})"] for a in w["alertes"]]
            if w["alertes"] else [["Ouverte le", "Alerte", "Code", "Messages", "État"], ["—", "Aucune alerte sur la période", "—", "—", "—"]],
            [30 * mm, 62 * mm, 14 * mm, 18 * mm, 56 * mm]))
        corps += [Spacer(1, 3 * mm), Paragraph("<b>Échecs par code d'erreur Meta</b>", styles["Heading3"])]
        corps.append(tableau([["Code", "Signification", "Nombre", "Premier", "Dernier"]] + [
            [c["code"], c["libelle"] + (" — CRITIQUE" if c["critique"] else ""), c["nombre"], (c["premiere"] or "")[:16].replace("T", " "),
             (c["derniere"] or "")[:16].replace("T", " ")] for c in w["par_code"]]
            if w["par_code"] else [["Code", "Signification", "Nombre", "Premier", "Dernier"], ["—", "Aucun échec", "0", "—", "—"]],
            [16 * mm, 84 * mm, 18 * mm, 31 * mm, 31 * mm]))
        corps += [Spacer(1, 3 * mm), Paragraph("<b>Échecs par jour</b>", styles["Heading3"])]
        corps.append(tableau([["Date", "Échecs", "Détail par code"]] + [
            [j["date"], j["echecs"], " · ".join(f"{c} ×{n}" for c, n in sorted(j["codes"].items(), key=lambda x: -x[1]))] for j in w["par_jour"]]
            if w["par_jour"] else [["Date", "Échecs", "Détail par code"], ["—", "0", "—"]], [26 * mm, 20 * mm, 134 * mm]))

    def pied(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawString(14 * mm, 8 * mm, "SAWALI Smart Systems · Alertes plateformes")
        canvas.drawRightString(A4[0] - 14 * mm, 8 * mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(corps, onFirstPage=pied, onLaterPages=pied)
    return sortie.getvalue()


def make_router(*, db, get_current_user, send_email):
    from routes.llm_health import SUPER_ADMIN_EMAIL

    router = APIRouter(prefix="/admin/alertes-plateformes", tags=["Admin — Alertes plateformes (lot 352)"])

    def _gate(user: dict):
        # « Administrateur seul » : le compte super-administrateur, comme le bandeau du crédit IA
        if (user.get("email") or "").lower() != SUPER_ADMIN_EMAIL:
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")

    @router.get("")
    async def lire(user: dict = Depends(get_current_user)):
        """Alertes ouvertes (les plus anciennes d'abord) et historique des alertes fermées."""
        _gate(user)
        etat = await _etat(db)
        ouvertes = sorted((etat.get("ouvertes") or {}).values(), key=lambda a: a.get("depuis") or "")
        return {"ouvertes": ouvertes, "historique": etat.get("historique") or [], "codes_surveilles": sorted(CODES_CRITIQUES)}

    @router.get("/historique")
    async def historique(jours: int = 30, ligne: Optional[str] = None, user: dict = Depends(get_current_user)):
        """Historique par ligne (Phone Number ID) : envois / échecs, échecs par code et par jour, alertes."""
        _gate(user)
        return await historique_par_ligne(db, jours, ligne)

    @router.get("/historique.pdf")
    async def historique_pdf(jours: int = 30, ligne: Optional[str] = None, user: dict = Depends(get_current_user)):
        """Même historique en PDF (toutes les lignes, ou une seule avec ?ligne=<Phone Number ID>)."""
        _gate(user)
        from fastapi.responses import Response
        donnees = await historique_par_ligne(db, jours, ligne)
        return Response(content=pdf_historique(donnees), media_type="application/pdf",
                        headers={"Content-Disposition": 'inline; filename="historique-lignes-whatsapp.pdf"', "Cache-Control": "no-store"})

    @router.post("/verifier")
    async def verifier(user: dict = Depends(get_current_user)):
        """Lance un passage de contrôle tout de suite."""
        _gate(user)
        return await surveiller(db, send_email)

    @router.post("/{cle}/regle")
    async def regle(cle: str, user: dict = Depends(get_current_user)):
        """Ferme une alerte à la main (« c'est réglé »). Elle se rouvre seule si les échecs reprennent."""
        _gate(user)
        if not await fermer(db, cle, f"fermée par {user.get('email')}"):
            raise HTTPException(status_code=404, detail="Alerte introuvable")
        return {"ok": True}

    return router
