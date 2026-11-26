# historique_conversations.py — Lot 466 : sous-menu Liluvine « Historique Conversation » (logique, sans accès réseau).
#
# Besoin du propriétaire : choisir un CLIENT (tenant), voir tous ses contacts, en cocher plusieurs, et afficher EN BAS toutes leurs conversations WhatsApp du
# Centre de Messagerie, horodatées, de la plus récente à la plus ancienne ; une pastille (noir sur fond blanc) donne le nom du contact ; impression PDF ou export CSV ;
# date et heure d'édition sur le document, « Liluvine » écrit verticalement et discrètement en bas de chaque page. Les messages BLOQUÉS ne comptent pas.
#
# « Bloqués » = 1) messages retenus par la barrière anti-rafale (`barriere_retenu`), 2) messages d'un numéro de la liste noire (`liste_noire`, ou numéro encore inscrit),
# 3) contacts actuellement bloqués (absents de la liste, comme dans le Centre de Messagerie).
# Ce fichier : fonctions PURES (choix des messages, mise en forme, CSV, PDF) + collecte. Les routes sont dans routes/historique_conversations.py.
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

MAX_CONTACTS = 100            # contacts cochés au plus
MAX_MESSAGES = 5000           # messages rendus au plus (les plus récents) ; au-delà, « tronqué »
MAX_TEXTE_PDF = 3000          # caractères d'un message dans le PDF
ENTETE_CSV = ["Date et heure", "Client", "Contact", "Téléphone", "Sens", "Type", "Statut", "Message"]
SENS = {"inbound": "Reçu", "outbound": "Envoyé"}


# ---------------------------------------------------------------------------------------------------------------------- outils
def chiffres(valeur: Any) -> str:
    return "".join(c for c in str(valeur or "") if c.isdigit())


def cle8(valeur: Any) -> str:
    """Numéro reconnu par ses 8 derniers chiffres (comme le Centre de Messagerie et la liste noire) ; vide si trop court."""
    d = chiffres(valeur)
    return d[-8:] if len(d) >= 8 else ""


def jour_valide(texte: Any) -> str:
    """« AAAA-MM-JJ » valide ou chaîne vide."""
    t = str(texte or "").strip()
    try:
        datetime.strptime(t, "%Y-%m-%d")
        return t
    except ValueError:
        return ""


def date_fr(iso: Any, avec_secondes: bool = True) -> str:
    """« 2026-11-26T09:41:07+00:00 » → « 26/11/2026 09:41:07 » (UTC = heure du Burkina Faso) ; « — » si illisible."""
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if t.tzinfo is not None:
            t = t.astimezone(timezone.utc)
        return t.strftime("%d/%m/%Y %H:%M:%S" if avec_secondes else "%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return "—"


# ------------------------------------------------------------------------------------------------------ choix et mise en forme
def message_ignore(m: Dict[str, Any], bloques: Set[str]) -> bool:
    """Vrai pour un message BLOQUÉ : retenu par la barrière, marqué liste noire, ou d'un numéro encore inscrit en liste noire."""
    return bool(m.get("liste_noire") or m.get("barriere_retenu")) or (bool(bloques) and cle8(m.get("phone_digits")) in bloques)


def rattacher(m: Dict[str, Any], par_id: Dict[str, Dict[str, Any]], par_cle: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Contact (parmi les contacts choisis) auquel appartient ce message : son contact_id, sinon son numéro sur 8 chiffres."""
    return par_id.get(m.get("contact_id")) or par_cle.get(cle8(m.get("phone_digits")))


def type_message(m: Dict[str, Any]) -> str:
    """Type lisible : texte, image, audio, document, modèle…"""
    if m.get("template_name"):
        return "modèle"
    t = str(m.get("message_type") or m.get("type") or "text").lower()
    return {"text": "texte", "image": "image", "audio": "audio", "voice": "audio", "video": "vidéo", "document": "document", "sticker": "autocollant",
            "location": "position", "interactive": "bouton", "button": "bouton"}.get(t, t)


def texte_message(m: Dict[str, Any]) -> str:
    """Texte du message ; pour un message sans texte (image, audio…), le type entre crochets ; pour un modèle, son texte rendu ou son nom."""
    corps = str(m.get("body") or m.get("template_rendered_body") or m.get("media_caption") or "").strip()
    if corps:
        return corps
    if m.get("template_name"):
        return f"[modèle {m['template_name']}]"
    t = type_message(m)
    return "" if t == "texte" else f"[{t}]"


def ligne(m: Dict[str, Any], contact: Dict[str, Any], client: str = "") -> Dict[str, Any]:
    """Une ligne d'historique, prête pour l'écran, le CSV et le PDF."""
    return {"id": m.get("id") or "", "quand_iso": str(m.get("created_at") or m.get("received_at") or ""), "quand": date_fr(m.get("created_at") or m.get("received_at")),
            "contact_id": contact.get("id") or "", "contact": contact.get("name") or contact.get("whatsapp") or contact.get("phone") or "Contact sans nom",
            "telephone": contact.get("whatsapp") or contact.get("phone") or "", "client": client, "sens": SENS.get(m.get("direction"), str(m.get("direction") or "")),
            "type": type_message(m), "statut": str(m.get("status") or m.get("wa_status") or ""), "message": texte_message(m)}


def trier(lignes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Date et heure DÉCROISSANTES (la plus récente d'abord)."""
    return sorted(lignes, key=lambda x: x["quand_iso"], reverse=True)


# -------------------------------------------------------------------------------------------------------------------------- CSV
def neutraliser(cellule: Any) -> str:
    """Protection contre l'injection de formule (Excel) : une cellule qui commence par = + - @ est précédée d'une apostrophe. Le texte vient de correspondants extérieurs."""
    t = str(cellule if cellule is not None else "")
    return "'" + t if t[:1] in ("=", "+", "-", "@", "\t", "\r") else t


def construire_csv(lignes: List[Dict[str, Any]]) -> bytes:
    """CSV « Excel français » : séparateur « ; », UTF-8 avec BOM (accents lus correctement), une ligne par message, plus récent d'abord."""
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=";", lineterminator="\r\n")
    w.writerow(ENTETE_CSV)
    for x in lignes:
        w.writerow([neutraliser(v) for v in (x["quand"], x["client"], x["contact"], x["telephone"], x["sens"], x["type"], x["statut"], x["message"])])
    return ("﻿" + sortie.getvalue()).encode("utf-8")


# -------------------------------------------------------------------------------------------------------------------------- PDF
def texte_pdf(texte: Any) -> str:
    """Texte sûr pour reportlab (police Helvetica = caractères Windows-1252) : accents conservés ; émojis et autres signes non imprimables remplacés par « · » ; balises échappées."""
    brut = str(texte if texte is not None else "")[:MAX_TEXTE_PDF]
    propre = "".join(c if (c in "\n\t" or (ord(c) >= 32 and _cp1252(c))) else "·" for c in brut)
    propre = re.sub(r"·{2,}", "·", propre)
    return propre.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


def _cp1252(c: str) -> bool:
    try:
        c.encode("cp1252")
        return True
    except UnicodeEncodeError:
        return False


def construire_pdf(lignes: List[Dict[str, Any]], *, client: str, contacts: List[str], du: str, au: str, genere_le: datetime, tronque: bool = False) -> bytes:
    """PDF A4 : titre, client, contacts, période, nombre de messages, DATE ET HEURE D'ÉDITION ; tableau Date/heure · Contact (pastille noir sur blanc) · Sens · Message ;
    sur CHAQUE page : « Page n / N » en pied et « Liluvine » écrit verticalement, en gris clair, discret, dans la marge du bas à droite."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    edite = genere_le.astimezone(timezone.utc).strftime("%d/%m/%Y à %H:%M")

    class CanevasNumerote(rl_canvas.Canvas):
        """Deux passes : on connaît le nombre total de pages avant d'écrire « Page n / N » et la marque verticale sur chacune."""
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._pages: List[Dict[str, Any]] = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for etat in self._pages:
                self.__dict__.update(etat)
                self._marques(total)
                super().showPage()
            super().save()

        def _marques(self, total: int):
            self.saveState()
            self.setFont("Helvetica", 7.5)
            self.setFillColor(colors.HexColor("#6b7280"))
            self.drawString(14 * mm, 8 * mm, f"Édité le {edite} (heure du Burkina Faso)")
            self.drawRightString(A4[0] - 22 * mm, 8 * mm, f"Page {self._pageNumber} / {total}")
            # « Liluvine » VERTICAL (lu de bas en haut) dans la marge de droite, tout en bas : gris clair, petit, sans gêner le texte
            self.translate(A4[0] - 7 * mm, 8 * mm)
            self.rotate(90)
            self.setFont("Helvetica-Oblique", 9)
            self.setFillColor(colors.HexColor("#b6bcc6"))
            self.drawString(0, 0, "Liluvine")
            self.restoreState()

    styles = getSampleStyleSheet()
    petit = ParagraphStyle("petit", parent=styles["Normal"], fontSize=8.5, leading=11, textColor=colors.HexColor("#374151"))
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, leading=10)
    entete = ParagraphStyle("entete", parent=cell, textColor=colors.white, fontName="Helvetica-Bold")
    pastille_style = ParagraphStyle("pastille", parent=cell, fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=colors.black, alignment=1)

    def pastille(nom: str) -> Table:
        """Pastille : texte NOIR sur fond BLANC, contour noir arrondi (nom du contact)."""
        t = Table([[Paragraph(texte_pdf(nom), pastille_style)]], colWidths=[33 * mm])
        t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, colors.black), ("BACKGROUND", (0, 0), (-1, -1), colors.white), ("ROUNDEDCORNERS", [4, 4, 4, 4]),
                               ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
        return t

    sortie = io.BytesIO()
    doc = SimpleDocTemplate(sortie, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=16 * mm,
                            title="Historique des conversations WhatsApp", author="Liluvine — SAWALI Smart Systems")
    def _j(j: str) -> str:
        return f"{j[8:10]}/{j[5:7]}/{j[:4]}"
    periode = f"du {_j(du)} au {_j(au)}" if du and au else (f"depuis le {_j(du)}" if du else (f"jusqu'au {_j(au)}" if au else "toutes les dates"))
    corps: List[Any] = [
        Paragraph("<b>Historique des conversations WhatsApp</b>", styles["Title"]),
        Paragraph(f"<b>Client :</b> {texte_pdf(client or '—')}", petit),
        Paragraph(f"<b>Contacts ({len(contacts)}) :</b> {texte_pdf(', '.join(contacts) if contacts else '—')}", petit),
        Paragraph(f"<b>Période :</b> {periode} · <b>Messages :</b> {len(lignes)}{' (les plus récents ; liste tronquée)' if tronque else ''} · "
                  f"<b>Édité le :</b> {edite} (heure du Burkina Faso)", petit),
        Paragraph("Messages bloqués (liste noire, barrière anti-rafale) non pris en compte. Du plus récent au plus ancien.", petit), Spacer(1, 4 * mm)]
    donnees: List[List[Any]] = [[Paragraph(h, entete) for h in ("Date et heure", "Contact", "Sens", "Message")]]
    for x in lignes:
        donnees.append([Paragraph(x["quand"], cell), pastille(x["contact"]), Paragraph(x["sens"], cell), Paragraph(texte_pdf(x["message"]) or "<i>(sans texte)</i>", cell)])
    if not lignes:
        donnees.append([Paragraph("—", cell), "", "", Paragraph("Aucun message pour cette sélection.", cell)])
    t = Table(donnees, colWidths=[30 * mm, 36 * mm, 15 * mm, 101 * mm], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#b8c2d0")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6fb")])]))
    corps.append(t)
    doc.build(corps, canvasmaker=CanevasNumerote)
    return sortie.getvalue()


# ------------------------------------------------------------------------------------------------------------------------ collecte
async def collecter(db, *, contacts_visibles: List[Dict[str, Any]], visible_scope: List[str], du: str = "", au: str = "", client: str = "",
                    seulement_utilisateur: Optional[str] = None, limite: int = MAX_MESSAGES) -> Tuple[List[Dict[str, Any]], bool]:
    """Messages WhatsApp des contacts donnés (déjà contrôlés : visibles, non bloqués), SANS les messages bloqués, du plus récent au plus ancien : (lignes, tronqué).
    Une seule lecture groupée (règle 7) : messages rattachés par contact_id OU par numéro (8 derniers chiffres). `seulement_utilisateur` : restriction
    « communications anonymisées » du Centre de Messagerie (seuls les messages échangés par cet utilisateur)."""
    if not contacts_visibles:
        return [], False
    import liste_noire_wa
    par_id = {c["id"]: c for c in contacts_visibles if c.get("id")}
    par_cle: Dict[str, Dict[str, Any]] = {}
    for c in contacts_visibles:
        for brut in (c.get("whatsapp"), c.get("phone")):
            k = cle8(brut)
            if k:
                par_cle.setdefault(k, c)
    clauses: List[Dict[str, Any]] = [{"contact_id": {"$in": list(par_id)}}]
    if par_cle:
        clauses.append({"phone_digits": {"$regex": "(" + "|".join(re.escape(k) for k in par_cle) + ")$"}})
    filtre: Dict[str, Any] = {"client_id": {"$in": visible_scope}, "$or": clauses, "liste_noire": {"$ne": True}, "barriere_retenu": {"$ne": True}}
    if du or au:
        filtre["created_at"] = {**({"$gte": du} if du else {}), **({"$lte": au + "T99"} if au else {})}
    bruts = await db.whatsapp_messages.find(filtre, {"_id": 0}).sort("created_at", -1).limit(limite + 1).to_list(limite + 1)
    tronque = len(bruts) > limite
    bloques = set(await liste_noire_wa.cles_bloquees(db))
    sortie: List[Dict[str, Any]] = []
    for m in bruts[:limite]:
        if message_ignore(m, bloques):
            continue
        if seulement_utilisateur and seulement_utilisateur not in (m.get("sender_id"), m.get("owner_id")):
            continue
        c = rattacher(m, par_id, par_cle)
        if c:
            sortie.append(ligne(m, c, client))
    return trier(sortie), tronque
