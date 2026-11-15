# agenda_parseur.py — comprend une note vocale en français et en tire un RENDEZ-VOUS : jour, heure, titre.
#
# Exemple : « samedi 8h15 rdv chez le dentiste »  ->  samedi suivant, 08:15, titre « RDV chez le dentiste ».
#
# Pour un développeur WinDev : c'est une analyse de TEXTE par règles (expressions régulières), sans IA ni appel réseau ;
# le même texte donne toujours le même résultat, et le résultat est TESTÉ. Règle du propriétaire : on ne DEVINE jamais en silence.
# Quand le jour ou l'heure manque, la liste `manque` le dit ; l'application demande alors à l'utilisateur et lui montre
# toujours « samedi 21 novembre 2026 à 08:15 — RDV chez le dentiste » avec un bouton Enregistrer avant de créer l'événement.
#
# Reconnu : aujourd'hui, demain, après-demain, lundi…dimanche (« prochain » accepté), « dans 3 jours / 2 semaines », « le 21 »,
# « le 21 novembre », « 1er décembre », « 21/11 », « 21/11/2026 » ; « 8h15 », « 8 h », « 8:15 », « 14h30 », « midi », « minuit »,
# « 8h et demie », « 8h et quart », « 8h moins le quart », « 8h du soir » ; durée « pendant 2 heures / 45 minutes ».
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, tzinfo
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

FUSEAU_DEFAUT = "Africa/Ouagadougou"        # Burkina Faso : UTC+0, sans heure d'été
DUREE_DEFAUT_MIN = 60
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre", "octobre", "novembre", "decembre"]
MOIS_AFFICHES = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
JOURS_AFFICHES = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _sans_accents(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def libelle_date(debut: datetime) -> str:
    """« samedi 21 novembre 2026 à 08:15 » : ce que l'utilisateur lit et confirme."""
    return f"{JOURS_AFFICHES[debut.weekday()]} {debut.day} {MOIS_AFFICHES[debut.month - 1]} {debut.year} à {debut:%H:%M}"


def _heure(t: str) -> Optional[Dict[str, Any]]:
    """Cherche l'heure dans le texte normalisé ; rend {h, m, span} ou None. `span` = morceau à retirer du titre."""
    m = re.search(r"\b(midi|minuit)\b", t)
    if m:
        return {"h": 12 if m.group(1) == "midi" else 0, "m": 0, "span": m.span()}
    m = re.search(r"\b(\d{1,2})\s*(?:h|:)\s*(\d{2})?\s*(et demie|et demi|et quart|moins le quart|moins quart)?", t)
    if not m:
        return None
    h, mn = int(m.group(1)), int(m.group(2) or 0)
    suite = m.group(3) or ""
    if "demi" in suite:
        mn = 30
    elif "et quart" in suite:
        mn = 15
    elif "moins" in suite:
        h, mn = h - 1, 45
    fin = m.end()
    # « du soir » / « de l'après-midi » : 1 h–11 h deviennent l'après-midi ; « du matin » ne change rien
    apres = t[fin:fin + 22]
    if re.match(r"\s*(?:du soir|de l apres midi|de l'apres-midi|de l apres-midi|apres midi)", apres) and 1 <= h <= 11:
        h += 12
    if not (0 <= h <= 23 and 0 <= mn <= 59):
        return None
    sp = m.span()
    ap = re.match(r"\s*(?:du matin|du soir|de l apres[- ]midi|de l'apres[- ]midi)", t[fin:])
    return {"h": h, "m": mn, "span": (sp[0], fin + (ap.end() if ap else 0))}


def _date(t: str, aujourdhui: datetime) -> Optional[Dict[str, Any]]:
    """Cherche le jour ; rend {date, span, relatif_jour} ou None."""
    d0 = aujourdhui.date()
    m = re.search(r"\bapres[- ]demain\b", t)
    if m:
        return {"date": d0 + timedelta(days=2), "span": m.span()}
    m = re.search(r"\bdemain\b", t)
    if m:
        return {"date": d0 + timedelta(days=1), "span": m.span()}
    m = re.search(r"\baujourd ?hui\b|\bce jour\b", t)
    if m:
        return {"date": d0, "span": m.span()}
    m = re.search(r"\bdans\s+(\d{1,3})\s+(jour|jours|semaine|semaines|mois)\b", t)
    if m:
        n = int(m.group(1))
        if m.group(2).startswith("semaine"):
            return {"date": d0 + timedelta(days=7 * n), "span": m.span()}
        if m.group(2) == "mois":
            mois = d0.month - 1 + n
            return {"date": d0.replace(year=d0.year + mois // 12, month=mois % 12 + 1, day=min(d0.day, 28)), "span": m.span()}
        return {"date": d0 + timedelta(days=n), "span": m.span()}
    # 21/11/2026 ou 21/11
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
    if m:
        j, mo = int(m.group(1)), int(m.group(2))
        an = int(m.group(3)) if m.group(3) else d0.year
        an = an + 2000 if an < 100 else an
        try:
            d = d0.replace(year=an, month=mo, day=j)
        except ValueError:
            d = None
        if d:
            if not m.group(3) and d < d0:
                d = d.replace(year=d.year + 1)
            return {"date": d, "span": m.span()}
    # « le 21 novembre », « 1er décembre », « le 21 » (mois courant, ou suivant si le jour est passé)
    noms = "|".join(MOIS)
    m = re.search(rf"\b(?:le\s+)?(\d{{1,2}})\s*(?:er)?\s+({noms})(?:\s+(\d{{4}}))?\b", t)
    if m:
        j, mo = int(m.group(1)), MOIS.index(m.group(2)) + 1
        an = int(m.group(3)) if m.group(3) else d0.year
        try:
            d = d0.replace(year=an, month=mo, day=j)
        except ValueError:
            return None
        if not m.group(3) and d < d0:
            d = d.replace(year=d.year + 1)
        return {"date": d, "span": m.span()}
    # jour de la semaine : le prochain (aujourd'hui si c'est le même jour, sauf mention « prochain » ; voir _resoudre_semaine)
    m = re.search(rf"\b({'|'.join(JOURS)})(?:\s+(prochain|suivant))?\b|\b(?:ce|le)\s+({'|'.join(JOURS)})\b", t)
    if m:
        nom = m.group(1) or m.group(3)
        return {"jour_semaine": JOURS.index(nom), "prochain": bool(m.group(2)), "span": m.span()}
    m = re.search(r"\ble\s+(\d{1,2})\b(?!\s*(?:h|:))", t)
    if m:
        j = int(m.group(1))
        if 1 <= j <= 31:
            for decal in (0, 1, 2):
                mois = d0.month - 1 + decal
                try:
                    d = d0.replace(year=d0.year + mois // 12, month=mois % 12 + 1, day=j)
                except ValueError:
                    continue
                if d >= d0:
                    return {"date": d, "span": m.span()}
    return None


def _duree(t: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\b(?:pendant|duree(?: de)?|pour)\s+(\d{1,2})\s*(heures?|h|minutes?|min)\b", t)
    if not m:
        return None
    n = int(m.group(1))
    return {"minutes": n * 60 if m.group(2).startswith("h") else n, "span": m.span()}


def analyser(texte: str, maintenant: datetime, fuseau: str = FUSEAU_DEFAUT) -> Dict[str, Any]:
    """Texte dicté -> proposition de rendez-vous. Ne crée RIEN. `maintenant` = instant présent (aware ou naïf, en UTC si naïf)."""
    zone: tzinfo = ZoneInfo(fuseau)
    base = maintenant.astimezone(zone) if maintenant.tzinfo else maintenant.replace(tzinfo=ZoneInfo("UTC")).astimezone(zone)
    brut = re.sub(r"\s+", " ", (texte or "").strip())
    t = _sans_accents(brut.lower()).replace("'", " ").replace("’", " ")
    heure, jour, duree = _heure(t), _date(t, base), _duree(t)
    manque: List[str] = []
    # Résolution du jour de la semaine : le prochain jour portant ce nom (aujourd'hui seulement si l'heure est encore à venir)
    date = None
    if jour:
        if "date" in jour:
            date = jour["date"]
        else:
            ecart = (jour["jour_semaine"] - base.weekday()) % 7
            if ecart == 0 and (jour["prochain"] or not heure or (heure["h"], heure["m"]) <= (base.hour, base.minute)):
                ecart = 7
            date = base.date() + timedelta(days=ecart)
    if date is None:
        manque.append("date")
        date = base.date()
    if heure is None:
        manque.append("heure")
        h, m = 9, 0                         # valeur PROVISOIRE : `manque` oblige l'application à demander
    else:
        h, m = heure["h"], heure["m"]
    debut = datetime(date.year, date.month, date.day, h, m, tzinfo=zone)
    minutes = duree["minutes"] if duree else DUREE_DEFAUT_MIN
    fin = debut + timedelta(minutes=minutes)
    # Titre : le texte sans le jour, l'heure et la durée, sans les formules d'introduction ; « rdv » est gardé en tête (« RDV chez le dentiste »)
    morceaux = sorted([x["span"] for x in (heure, jour, duree) if x], reverse=True)
    reste = t
    for a, b in morceaux:
        reste = reste[:a] + " " + reste[b:]
    reste = re.sub(r"^\s*(?:note|ajoute|ajouter|planifie|planifier|mets|met|prends|prendre|rappelle moi(?: de)?|n oublie pas(?: de)?)\b", " ", reste)
    reste = re.sub(r"\b(?:a|le|ce)\s*$", "", re.sub(r"\s+", " ", reste)).strip(" ,.;:-")
    reste = re.sub(r"^(?:a|le|ce|un|une)\s+(?=\S)", "", reste).strip(" ,.;:-")
    # On retrouve l'écriture d'origine (avec accents) pour l'affichage : mêmes mots, dans l'ordre du texte dicté
    mots_titre = reste.split(" ") if reste else []
    originaux = brut.replace("’", " ").replace("'", " ").split(" ")
    norm_orig = [_sans_accents(w.lower()) for w in originaux]
    titre_mots, i = [], 0
    for mot in mots_titre:
        while i < len(norm_orig) and norm_orig[i].strip(",.;:") != mot:
            i += 1
        if i < len(originaux):
            titre_mots.append(originaux[i].strip(",.;:")); i += 1
        else:
            titre_mots.append(mot)
    titre = " ".join(titre_mots).strip()
    titre = re.sub(r"^(?:rdv|rendez vous|rendez-vous)\b", "RDV", titre, flags=re.IGNORECASE)
    titre = (titre[:1].upper() + titre[1:]) if titre else "Rendez-vous"
    if not mots_titre:
        manque.append("titre")
    return {"titre": titre, "debut": debut.isoformat(), "fin": fin.isoformat(), "duree_minutes": minutes,
            "libelle": libelle_date(debut), "manque": manque, "fuseau": fuseau, "texte": brut}
