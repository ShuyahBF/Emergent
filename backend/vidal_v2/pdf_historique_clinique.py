"""
backend/vidal_v2/pdf_historique_clinique.py
-----------------------------------------------
Lot 56 — repris de Ster (app/utils/pdf_historique_clinique.py) ; en-tête
adapté à SAWALI (nom du patient enregistré, pas de n° de dossier).

§ demande utilisateur (historique du profil clinique) : export PDF de
l'historique des données cliniques d'un patient — ReportLab, déjà utilisé
par SAWALI pour l'ordonnance sécurisée (routes/vidal_ordonnance.py) : tableau
des versions (champs modifiés en gras), courbes d'évolution (poids,
créatininémie, clairance, DFG avec la référence du groupe) dessinées en
vectoriel, et liste des sécurisations avec leur résumé.
"""

import io
from datetime import datetime

from reportlab.graphics.shapes import Drawing, Line, PolyLine, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from vidal_v2.historique_clinique import LIBELLES_CHAMPS

_COURBES = [
    ("poids_kg", "Poids (kg)"),
    ("creatininemie_umol_l", "Créatininémie (µmol/L)"),
    ("clairance_ml_min", "Clairance de la créatinine (ml/min)"),
    ("dfg_ml_min_173", "DFG (ml/min/1,73 m²)"),
]


def _date(valeur) -> str:
    if isinstance(valeur, datetime):
        return valeur.strftime("%d/%m/%Y %H:%M")
    if isinstance(valeur, str) and len(valeur) >= 10:
        a, m, j = valeur[:10].split("-")
        return f"{j}/{m}/{a}"
    return "" if valeur is None else str(valeur)


def _texte(cle: str, valeur) -> str:
    if valeur in (None, "", []):
        return "—"
    if isinstance(valeur, list):
        return ", ".join(e.get("label") or e.get("ref") or "" for e in valeur)
    if cle.startswith("date"):
        return _date(valeur)
    return str(valeur)


def _courbe(titre: str, points: list[tuple[str, float]], reference: float | None = None) -> Drawing:
    """Petite courbe vectorielle (valeurs dans l'ordre chronologique), ligne de référence en pointillés."""
    largeur, hauteur, marge = 120 * mm, 40 * mm, 10 * mm
    dessin = Drawing(largeur, hauteur + 8 * mm)
    dessin.add(String(0, hauteur + 3 * mm, titre, fontSize=8, fontName="Helvetica-Bold"))
    valeurs = [v for _, v in points] + ([reference] if reference else [])
    if not points:
        dessin.add(String(marge, hauteur / 2, "Aucune valeur", fontSize=7))
        return dessin
    vmin, vmax = min(valeurs), max(valeurs)
    if vmax == vmin:
        vmin, vmax = vmin - 1, vmax + 1

    def y(v):
        return marge / 2 + (v - vmin) / (vmax - vmin) * (hauteur - marge)

    pas = (largeur - 2 * marge) / max(len(points) - 1, 1)
    coords = []
    for i, (etiquette, v) in enumerate(points):
        x = marge + i * pas
        coords += [x, y(v)]
        dessin.add(String(x - 6, y(v) + 3, f"{v:g}", fontSize=6))
        dessin.add(String(x - 8, 0, etiquette[:5], fontSize=5.5))
    if len(points) > 1:
        dessin.add(PolyLine(coords, strokeColor=colors.HexColor("#1c4587"), strokeWidth=1.2))
    if reference:
        dessin.add(Line(marge, y(reference), largeur - marge, y(reference), strokeColor=colors.HexColor("#2fa84f"), strokeDashArray=[3, 2]))
        dessin.add(String(largeur - marge + 2, y(reference) - 2, f"réf. {reference:g}", fontSize=6, fillColor=colors.HexColor("#2fa84f")))
    return dessin


def generer_pdf_historique_clinique(patient: dict, versions: list[dict], securisations: list[dict], etablissement: str = "SAWALI") -> bytes:
    """`patient` : document de `vidal_patients` ; `versions` du plus ancien au plus récent (courbes) ;
    `securisations` : instantanés au format de routes/vidal_patients.py (`instantane_depuis_audit`)."""
    tampon = io.BytesIO()
    doc = SimpleDocTemplate(tampon, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm)
    styles = getSampleStyleSheet()
    petit = styles["BodyText"].clone("petit", fontSize=6.5, leading=8)
    elements = [
        Paragraph(f"{etablissement} — Historique des données cliniques", styles["Title"]),
        Paragraph(f"Patient : {patient.get('name') or '—'}{' (patient fictif de validation)' if patient.get('est_fictif') else ''} — réf. {(patient.get('id') or '')[:8].upper()} — édité le {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles["BodyText"]),
        Spacer(1, 4 * mm),
    ]

    # Courbes d'évolution
    for cle, titre in _COURBES:
        points = [(_date(v["date"])[:5], float(v["valeurs"][cle])) for v in versions if isinstance(v["valeurs"].get(cle), (int, float))]
        reference = None
        if cle == "dfg_ml_min_173" and versions:
            reference = versions[-1]["valeurs"].get("valeur_normale_dfg_groupe")
        elements.append(_courbe(titre, points, reference))
    elements.append(Spacer(1, 4 * mm))

    # Tableau des versions
    elements.append(Paragraph("Versions du profil clinique (champs modifiés en gras)", styles["Heading3"]))
    # § sous-ensemble lisible en paysage ; le détail complet reste consultable à l'écran.
    cles = ["poids_kg", "taille_cm", "creatininemie_umol_l", "clairance_ml_min", "dfg_ml_min_173", "libelle_groupe_dfg",
            "date_dernieres_regles", "semaines_amenorrhee", "allaitement", "date_debut_allaitement", "insuffisance_hepatique",
            "allergies", "molecules", "pathologies"]
    libelles = {**LIBELLES_CHAMPS, "libelle_groupe_dfg": LIBELLES_CHAMPS["groupe_reference_dfg"]}
    entetes = ["Date", "Auteur"] + [libelles[c] for c in cles]
    lignes = [[Paragraph(f"<b>{e}</b>", petit) for e in entetes]]
    for v in reversed(versions):
        modifies = set(v.get("champs_modifies") or [])
        cellules = [Paragraph(_date(v["date"]), petit), Paragraph(v.get("login") or "", petit)]
        for cle in cles:
            texte = _texte(cle, v["valeurs"].get(cle))
            modifie = cle in modifies or (cle == "libelle_groupe_dfg" and "groupe_reference_dfg" in modifies) or (cle == "semaines_amenorrhee" and "date_dernieres_regles" in modifies)
            cellules.append(Paragraph(f"<b>{texte}</b>" if modifie else texte, petit))
        lignes.append(cellules)
    tableau = Table(lignes, repeatRows=1)
    tableau.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2fa")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elements += [tableau, Spacer(1, 4 * mm)]

    # Sécurisations
    elements.append(Paragraph("Sécurisations VIDAL", styles["Heading3"]))
    lignes = [[Paragraph(f"<b>{e}</b>", petit) for e in ("Date", "Auteur", "Référence", "Médicaments", "Alertes par gravité", "Données patient envoyées")]]
    for s in securisations:
        envoye = s.get("patient_envoye") or {}
        resume = ", ".join(f"{g} : {n}" for g, n in sorted((s.get("resume_gravites") or {}).items())) or "aucune"
        lignes.append([
            Paragraph(_date(s.get("date_creation")), petit), Paragraph(s.get("login") or "", petit),
            Paragraph(s.get("ordonnance_reference") or "—", petit),
            Paragraph(", ".join(l.get("label") or l.get("drugRef") or "" for l in s.get("lignes_envoyees") or []), petit),
            Paragraph(resume, petit),
            Paragraph("; ".join(f"{k} = {v if v is not None else 'nil'}" for k, v in envoye.items()), petit),
        ])
    tableau = Table(lignes, repeatRows=1, colWidths=[28 * mm, 22 * mm, 30 * mm, 60 * mm, 40 * mm, 90 * mm])
    tableau.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2fa")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elements.append(tableau)
    elements.append(Spacer(1, 3 * mm))
    elements.append(Paragraph(f"{LIBELLES_CHAMPS['groupe_reference_dfg']} : aide d'interprétation locale, jamais transmise à VIDAL.", petit))

    doc.build(elements)
    return tampon.getvalue()
