# liluvine_agenda_formulaire.py — Lot 71 : appels de Liluvine basés sur un FORMULAIRE SAWALI.
#
# Demande du propriétaire (06/10/2026) : « Peut-on baser les appels de Liluvine sur un formulaire ?
# Elle se base sur les champs du formulaire pour enregistrer les réponses. Elle utilisera soit le
# prompt soit un formulaire parmi la liste des formulaires disponibles. »
#
# Principe (le mode « prompt » du lot 70 reste inchangé) :
#   1. PLAN : les champs du formulaire (collection db.forms, pages → champs) deviennent les questions de
#      l'appel, DANS L'ORDRE. Chaque type de champ donne une question orale adaptée (texte, nombre, date,
#      date et heure, oui/non, choix unique, choix multiples, e-mail, téléphone, lien). Les choix sont dits
#      dans une phrase (« plutôt A, B ou C ? »), jamais numérotés (style oral du lot 70).
#      Les champs impossibles à remplir à la voix (fichier joint, signature, tableau, géolocalisation) ne
#      sont PAS demandés : ils sont marqués « à compléter » (lien du formulaire envoyé par WhatsApp).
#   2. CONFIRMATION : pour les valeurs ambiguës (dates, nombres, e-mails, numéros, noms propres), Liluvine
#      relit la valeur ou fait épeler (consigne ajoutée au prompt pour chaque champ concerné).
#   3. EXTRACTION : après l'appel, l'IA renvoie un JSON « id du champ → valeur » ; chaque valeur est
#      CONTRÔLÉE contre le type et les choix du champ (valeur invalide → vide + signalée).
#   4. SOUMISSION : une VRAIE réponse au formulaire est créée dans db.form_submissions (même collection
#      que les réponses saisies en ligne ou par WhatsApp), avec la source « appel Liluvine » (évènement,
#      appel, confiance par champ, lien vers la transcription) et le statut « complète » ou « incomplète ».
#
# Toutes les fonctions de ce fichier sont PURES (aucun accès à la base) : elles sont testées une à une
# dans tests/test_lot71_formulaire_transfert.py. Les accès à la base sont dans liluvine_agenda.py.
from __future__ import annotations

import os
import re
import unicodedata
import uuid
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import routes.liluvine_decroche as ld

# Types de champs du formulaire que Liluvine sait demander au téléphone (voir FormEditor.jsx)
TYPES_VOCAUX = ("text", "textarea", "number", "boolean", "select", "multiselect", "date", "datetime",
                "email", "tel", "url")
# Types impossibles à remplir à la voix → « à compléter » (avec la raison affichée)
TYPES_NON_VOCAUX = {"file": "fichier joint", "signature": "signature", "table": "tableau",
                    "location": "géolocalisation"}
# Libellés lisibles des types (écran de l'agenda, prompt d'extraction)
LIBELLES_TYPES = {
    "text": "texte", "textarea": "texte long", "number": "nombre", "boolean": "oui_non", "select": "choix",
    "multiselect": "choix_multiple", "date": "date", "datetime": "date_heure", "email": "email",
    "tel": "telephone", "url": "url",
}
# Réglage « envoyer le lien du formulaire par WhatsApp à la fin »
REGLAGES_LIEN = ("auto", "toujours", "jamais")
# Champs « nom propre » : Liluvine fait épeler ou confirme l'orthographe
MOTIF_NOM_PROPRE = re.compile(r"\b(nom|pr[ée]nom|name|raison sociale|entreprise|soci[ée]t[ée]|ville|quartier|"
                              r"adresse|rue|village|commune|structure|pharmacie|[ée]tablissement)\b", re.I)
# Au-delà de ce nombre de choix, Liluvine n'en lit que quelques-uns (« par exemple … »)
CHOIX_LUS_MAX = 8


# ---------------------------------------------------------------------------
# Petits outils de texte
# ---------------------------------------------------------------------------

def sans_accents(texte: Any) -> str:
    """« Élevé » → « eleve » (comparaison des choix sans accents ni majuscules)."""
    t = unicodedata.normalize("NFD", str(texte or ""))
    return re.sub(r"\s+", " ", "".join(c for c in t if unicodedata.category(c) != "Mn")).strip().lower()


def libelle_oral(libelle: Any) -> str:
    """Libellé d'un champ prêt à être dit : numérotation (« 1. », « a) »), astérisque d'obligation,
    deux-points final et mise en forme écrite retirés (nettoyage oral du lot 70)."""
    t = str(libelle or "").strip()
    t = re.sub(r"^\s*(?:\d{1,3}\s*[.)\-]|[a-zA-Z]\))\s+", "", t)        # « 3. Nom » → « Nom »
    t = t.replace("*", " ")
    t = ld.nettoyer_pour_voix(t)
    return re.sub(r"\s*:\s*$", "", t).strip()


def _minuscule_initiale(texte: str) -> str:
    """« Nom complet » → « nom complet » (sauf sigle tout en majuscules : « NIF » reste « NIF »)."""
    if not texte:
        return texte
    premier = texte.split(" ", 1)[0]
    if len(premier) > 1 and premier.isupper():
        return texte
    return texte[:1].lower() + texte[1:]


def lire_choix(options: List[Any], *, multiple: bool = False) -> str:
    """Choix d'un champ dits dans UNE phrase, sans numérotation : « A, B ou C » (« A, B et C » pour un
    choix multiple). Au-delà de CHOIX_LUS_MAX choix : « par exemple A, B ou C »."""
    propres = [libelle_oral(o) for o in options or [] if libelle_oral(o)]
    if not propres:
        return ""
    debut = ""
    if len(propres) > CHOIX_LUS_MAX:
        propres, debut = propres[:3], "par exemple "
    liaison = " et " if multiple and not debut else " ou "
    if len(propres) == 1:
        return debut + propres[0]
    return debut + ", ".join(propres[:-1]) + liaison + propres[-1]


# ---------------------------------------------------------------------------
# 1. Plan de l'appel : champs → questions orales
# ---------------------------------------------------------------------------

def champs_du_formulaire(form: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Formulaire (pages → champs) → liste plate et ordonnée des champs {id, label, type, required, options}.
    Les champs sans identifiant ou sans libellé sont ignorés ; un identifiant en double n'est gardé qu'une fois."""
    sortie: List[Dict[str, Any]] = []
    vus = set()
    for page in (form or {}).get("pages") or []:
        for champ in (page or {}).get("fields") or []:
            if not isinstance(champ, dict):
                continue
            fid = str(champ.get("id") or "").strip()
            label = str(champ.get("label") or "").strip()
            if not fid or not label or fid in vus:
                continue
            vus.add(fid)
            sortie.append({"id": fid, "label": label[:300], "type": str(champ.get("type") or "text"),
                           "required": bool(champ.get("required")),
                           "options": [str(o) for o in (champ.get("options") or []) if str(o).strip()]})
    return sortie


def question_orale(champ: Dict[str, Any]) -> str:
    """Question dite par Liluvine pour ce champ (une seule question, style oral, choix sans numéros)."""
    label = libelle_oral(champ.get("label"))
    genre = champ.get("type")
    est_question = label.endswith("?")
    sujet = _minuscule_initiale(label.rstrip(" ?"))
    if genre == "boolean":
        return label if est_question else f"Concernant {sujet}, est-ce oui ou non ?"
    if genre == "select":
        choix = lire_choix(champ.get("options") or [])
        if est_question:
            return f"{label[:-1].rstrip()}, plutôt {choix} ?" if choix else label
        return f"Concernant {sujet}, plutôt {choix} ?" if choix else f"Concernant {sujet}, que dois-je noter ?"
    if genre == "multiselect":
        choix = lire_choix(champ.get("options") or [], multiple=True)
        intro = label[:-1].rstrip() if est_question else f"Concernant {sujet}"
        return f"{intro}, plusieurs réponses sont possibles parmi {choix}. Lesquelles retenez-vous ?"
    if est_question:
        return label
    fin = {
        "number": "quel nombre dois-je noter ?",
        "date": "quelle date dois-je noter ?",
        "datetime": "quelle date et quelle heure dois-je noter ?",
        "email": "quelle adresse e-mail dois-je noter ?",
        "tel": "quel numéro de téléphone dois-je noter ?",
        "url": "quelle adresse de site internet dois-je noter ?",
    }.get(genre, "que dois-je noter ?")
    return f"Concernant {sujet}, {fin}"


def consigne_confirmation(champ: Dict[str, Any]) -> str:
    """Consigne de vérification d'une valeur ambiguë (relire, faire épeler), ou « » si inutile."""
    genre = champ.get("type")
    if genre in ("date", "datetime"):
        return "relis la date comprise (jour, mois et année) et fais-la confirmer"
    if genre == "number":
        return "répète le nombre compris et fais-le confirmer"
    if genre == "email":
        return "fais épeler l'adresse e-mail lettre par lettre, puis relis-la pour confirmation"
    if genre == "tel":
        return "relis le numéro chiffre par chiffre pour confirmation"
    if genre == "url":
        return "fais épeler l'adresse du site, puis relis-la"
    if genre in ("select", "boolean", "multiselect"):
        return "si la réponse ne correspond clairement à aucun choix, reformule la question une fois"
    if genre in ("text", "textarea") and MOTIF_NOM_PROPRE.search(champ.get("label") or ""):
        return "si l'orthographe n'est pas évidente, fais épeler puis relis"
    return ""


def plan_formulaire(form: Dict[str, Any]) -> Dict[str, Any]:
    """Plan de l'appel : champs demandés à la voix (question + consigne) et champs « à compléter »."""
    vocaux: List[Dict[str, Any]] = []
    a_completer: List[Dict[str, Any]] = []
    tous = champs_du_formulaire(form)
    for champ in tous:
        genre = champ["type"]
        if genre in TYPES_NON_VOCAUX:
            a_completer.append({"id": champ["id"], "label": champ["label"], "type": genre,
                                "required": champ["required"], "raison": TYPES_NON_VOCAUX[genre]})
            continue
        if genre not in TYPES_VOCAUX:                 # type inconnu : traité comme un texte
            champ = {**champ, "type": "text"}
        if genre in ("select", "multiselect") and not champ["options"]:
            champ = {**champ, "type": "text"}        # liste de choix vide : réponse libre
        vocaux.append({**champ, "question": question_orale(champ), "confirmation": consigne_confirmation(champ)})
    return {"id": (form or {}).get("id"), "titre": str((form or {}).get("title") or "Formulaire")[:160],
            "number": (form or {}).get("number"), "nb_champs": len(tous), "champs": vocaux,
            "a_completer": a_completer, "lien": None}


def resume_formulaire(form: Dict[str, Any]) -> Dict[str, Any]:
    """Résumé d'un formulaire pour le sélecteur de l'agenda (nombre de champs, demandés, à compléter)."""
    plan = plan_formulaire(form)
    return {"id": form.get("id"), "titre": plan["titre"], "number": form.get("number"),
            "nb_champs": plan["nb_champs"], "nb_vocaux": len(plan["champs"]),
            "nb_a_completer": len(plan["a_completer"]), "is_public": bool(form.get("is_public"))}


def bloc_prompt(plan: Dict[str, Any], *, lien_prevu: bool) -> str:
    """Consignes du formulaire ajoutées au prompt système de l'appel (fonction pure, testée)."""
    lignes = [f"Formulaire à remplir pendant l'appel : « {plan.get('titre')} ».",
              "Pose les questions ci-dessous DANS L'ORDRE, une seule à la fois, avec tes mots et au style oral "
              "(jamais de numéro, de liste ni de puce ; les choix se disent dans une phrase). "
              "Attends chaque réponse avant de passer à la suivante."]
    for n, c in enumerate(plan.get("champs") or [], 1):
        ligne = f"Question {n} [{'obligatoire' if c.get('required') else 'facultative'}] : {c['question']}"
        if c.get("confirmation"):
            ligne += f" (Vérification : {c['confirmation']}.)"
        lignes.append(ligne)
    lignes.append("Si la personne ne sait pas ou refuse, passe à la suivante ; pour une question obligatoire, "
                  "insiste une seule fois, gentiment.")
    if plan.get("a_completer"):
        noms = ", ".join(libelle_oral(c["label"]) for c in plan["a_completer"])
        lignes.append(f"Ne demande PAS au téléphone : {noms} (impossible à remplir à la voix)."
                      + (" À la fin, annonce qu'un lien lui sera envoyé par WhatsApp pour les compléter."
                         if lien_prevu else ""))
    lignes.append(f"Quand toutes les questions sont posées (ou si la personne ne veut pas continuer), remercie, "
                  f"dis au revoir et termine par {ld.MARQUEUR_FIN}.")
    return "\n".join(lignes)


# ---------------------------------------------------------------------------
# 2. Extraction : consigne de l'IA et contrôle des valeurs
# ---------------------------------------------------------------------------

SYSTEME_EXTRACTION_FORMULAIRE = (
    "Tu analyses la transcription d'un appel téléphonique passé par Liluvine, l'assistante de SAWALI, pour "
    "remplir un formulaire. Réponds UNIQUEMENT par un objet JSON valide, sans texte autour, de la forme : "
    '{"resume": "1 à 3 phrases en français", '
    '"reponses": {"<id du champ>": {"valeur": <valeur ou null>, "confiance": <0 à 1>}}, '
    '"action_suivante": {"texte": "action conseillée", "type": "relance|suivi_client|rappel_rdv|prospection|autre|aucune", '
    '"date": "AAAA-MM-JJ HH:MM ou null"}}. '
    "Types : texte = chaîne ; nombre = nombre ; oui_non = true/false ; date = AAAA-MM-JJ ; "
    "date_heure = AAAA-MM-JJTHH:MM ; choix = EXACTEMENT un des choix proposés ; choix_multiple = liste de "
    "choix proposés ; email = adresse e-mail ; telephone = chiffres avec l'indicatif ; url = adresse web. "
    "Utilise la valeur CONFIRMÉE par la personne (après épellation ou relecture). "
    "Mets null si l'information n'a pas été donnée ; n'invente rien."
)


def texte_a_extraire(plan: Dict[str, Any], transcription: List[Dict[str, Any]], date_appel: str) -> str:
    """Message envoyé à l'IA d'extraction : champs du formulaire (id, type, choix) + transcription."""
    lignes = [f"Date de l'appel : {date_appel} (heure de Ouagadougou)",
              f"Formulaire : {plan.get('titre')}", "Champs à remplir :"]
    for c in plan.get("champs") or []:
        choix = f" (choix : {' | '.join(c['options'])})" if c.get("options") and c["type"] in ("select", "multiselect") else ""
        lignes.append(f"- id={c['id']} ; type={LIBELLES_TYPES.get(c['type'], 'texte')} ; champ : {c['label']}{choix}")
    lignes.append("\nTranscription :")
    lignes.append("\n".join(f"{'Liluvine' if t.get('qui') == 'liluvine' else 'Interlocuteur'} : {t.get('texte')}"
                            for t in transcription or [])[:12000])
    return "\n".join(lignes)


def _vide(valeur: Any) -> bool:
    """Valeur absente (None, chaîne vide, « null », « inconnu »…) ?"""
    if valeur is None:
        return True
    if isinstance(valeur, (list, dict)) and not valeur:
        return True
    return isinstance(valeur, str) and valeur.strip().lower() in ("", "null", "none", "inconnu", "n/a", "nc", "-")


def _choix_reconnu(valeur: Any, options: List[str]) -> Optional[str]:
    """Valeur dite → choix EXACT du formulaire (sans accents ni majuscules), sinon None.
    Égalité d'abord ; sinon un SEUL choix contenu dans la réponse (ou l'inverse)."""
    v = sans_accents(valeur)
    if not v:
        return None
    for o in options:
        if sans_accents(o) == v:
            return o
    proches = [o for o in options if sans_accents(o) and (sans_accents(o) in v or v in sans_accents(o))]
    return proches[0] if len(proches) == 1 else None


def _nombre(valeur: Any) -> Optional[float]:
    """« 25 000 », « 12,5 », 3 → nombre ; None si illisible."""
    if isinstance(valeur, bool):
        return None
    if isinstance(valeur, (int, float)):
        return valeur
    brut = re.sub(r"[\s  ]", "", str(valeur)).replace(",", ".")
    brut = re.sub(r"[^\d.\-]", "", brut)
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", brut or ""):
        return None
    n = float(brut)
    return int(n) if n.is_integer() else n


def _date(valeur: Any) -> Optional[str]:
    """« 2026-10-06 » ou « 06/10/2026 » → « 2026-10-06 » (date réelle), sinon None."""
    t = str(valeur or "").strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t[:10]) and (len(t) == 10 or t[10] in "T "):
            return date.fromisoformat(t[:10]).isoformat()
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", t)
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None
    return None


def _date_heure(valeur: Any) -> Optional[str]:
    """« 2026-10-06 14:30 », « 2026-10-06T14:30 », « 06/10/2026 14h30 » → « 2026-10-06T14:30 » ; None sinon
    (une date SANS heure est refusée : l'heure est demandée par le champ)."""
    t = str(valeur or "").strip()
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})[T ]+(\d{1,2})[:hH](\d{2})(?::\d{2})?(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?", t)
    if not m:
        return None
    jour = _date(m.group(1))
    h, mi = int(m.group(2)), int(m.group(3))
    if not jour or h > 23 or mi > 59:
        return None
    return f"{jour}T{h:02d}:{mi:02d}"


def _email(valeur: Any) -> Optional[str]:
    """Adresse e-mail (formes dites acceptées : « arobase », « point ») → adresse en minuscules, sinon None."""
    t = str(valeur or "").strip().lower()
    t = re.sub(r"\s*(?:arobase|arrobase|at)\s*", "@", t)
    t = re.sub(r"\s+point\s+", ".", t)
    t = re.sub(r"\s+", "", t)
    return t if re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", t) else None


def _telephone(valeur: Any) -> Optional[str]:
    """Numéro de téléphone → chiffres (avec « + » si un indicatif est donné) ; 8 à 15 chiffres, sinon None."""
    t = str(valeur or "").strip()
    chiffres = re.sub(r"\D", "", t)
    if not 8 <= len(chiffres) <= 15:
        return None
    return f"+{chiffres}" if (t.startswith("+") or t.startswith("00") or len(chiffres) > 10) else chiffres


def _url(valeur: Any) -> Optional[str]:
    """Adresse web (« www.exemple.com » accepté, « https:// » ajouté) ; None si ce n'est pas une adresse."""
    t = re.sub(r"\s+", "", str(valeur or "").strip())
    if t and not re.match(r"https?://", t, re.I):
        t = "https://" + t
    return t if re.fullmatch(r"https?://[\w\-]+(\.[\w\-]+)+(/\S*)?", t, re.I) else None


def valider_valeur(valeur: Any, champ: Dict[str, Any]) -> Tuple[Any, Optional[str]]:
    """Valeur extraite par l'IA → (valeur au format du formulaire, motif d'invalidité ou None).
    Valeur absente → (None, None) ; valeur incohérente → (None, motif) : jamais de valeur inventée."""
    if _vide(valeur):
        return None, None
    genre = champ.get("type")
    options = champ.get("options") or []
    if genre == "boolean":
        if isinstance(valeur, bool):
            return valeur, None
        v = sans_accents(valeur)
        if v in ("oui", "yes", "true", "vrai", "1", "d'accord", "ok", "bien sur"):
            return True, None
        if v in ("non", "no", "false", "faux", "0", "pas du tout"):
            return False, None
        return None, "réponse oui/non attendue"
    if genre == "number":
        n = _nombre(valeur)
        return (n, None) if n is not None else (None, "nombre illisible")
    if genre == "date":
        d = _date(valeur)
        return (d, None) if d else (None, "date invalide (AAAA-MM-JJ attendu)")
    if genre == "datetime":
        d = _date_heure(valeur)
        return (d, None) if d else (None, "date et heure invalides")
    if genre == "email":
        e = _email(valeur)
        return (e, None) if e else (None, "adresse e-mail invalide")
    if genre == "tel":
        t = _telephone(valeur)
        return (t, None) if t else (None, "numéro de téléphone invalide")
    if genre == "url":
        u = _url(valeur)
        return (u, None) if u else (None, "adresse web invalide")
    if genre == "select":
        if isinstance(valeur, list):
            valeur = valeur[0] if len(valeur) == 1 else ""
        c = _choix_reconnu(valeur, options)
        return (c, None) if c else (None, "réponse hors des choix proposés")
    if genre == "multiselect":
        if isinstance(valeur, list):
            brut = valeur
        elif any(sans_accents(o) == sans_accents(valeur) for o in options):
            brut = [valeur]                          # un seul choix dont le libellé contient « et » / « ou »
        else:
            brut = re.split(r"\s*(?:,|;|\bet\b|\bou\b)\s*", str(valeur))
        retenus: List[str] = []
        for morceau in brut:
            if _vide(morceau):
                continue
            c = _choix_reconnu(morceau, options)
            if c is None:
                return None, f"« {str(morceau)[:40]} » ne fait pas partie des choix"
            if c not in retenus:
                retenus.append(c)
        return (retenus, None) if retenus else (None, None)
    # Texte (court ou long) : chaîne nettoyée
    if isinstance(valeur, (list, tuple)):
        valeur = ", ".join(str(x) for x in valeur)
    elif isinstance(valeur, dict):
        valeur = ", ".join(f"{k} : {v}" for k, v in valeur.items())
    texte = re.sub(r"\s+", " ", str(valeur)).strip()
    return (texte[:2000], None) if texte else (None, None)


def analyser_reponses(donnees: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    """JSON de l'IA (déjà lu) → réponses CHAMP PAR CHAMP, contrôlées, prêtes pour la soumission.
    → {reponses: [{id, label, type, required, valeur, confiance, statut, motif}], data, confiances,
       invalides, obligatoires_manquants, a_completer, complet}.
    statut : rempli | vide | invalide | a_completer. Ne lève jamais d'exception."""
    reponses_ia = (donnees or {}).get("reponses")
    reponses_ia = reponses_ia if isinstance(reponses_ia, dict) else {}
    reponses: List[Dict[str, Any]] = []
    data: Dict[str, Any] = {}
    confiances: Dict[str, float] = {}
    for c in plan.get("champs") or []:
        brut = reponses_ia.get(c["id"], reponses_ia.get(c["label"]))
        confiance = None
        if isinstance(brut, dict) and ("valeur" in brut or "confiance" in brut):
            confiance = brut.get("confiance")
            brut = brut.get("valeur")
        try:
            confiance = max(0.0, min(1.0, float(confiance))) if confiance is not None else None
        except (TypeError, ValueError):
            confiance = None
        valeur, motif = valider_valeur(brut, c)
        statut = "rempli" if valeur is not None else ("invalide" if motif else "vide")
        if valeur is not None:
            data[c["id"]] = valeur
            confiances[c["id"]] = confiance if confiance is not None else 0.5
        reponses.append({"id": c["id"], "label": c["label"], "type": c["type"], "required": c["required"],
                         "valeur": valeur, "confiance": confiances.get(c["id"], 0.0), "statut": statut,
                         "motif": motif})
    for c in plan.get("a_completer") or []:
        reponses.append({"id": c["id"], "label": c["label"], "type": c["type"], "required": c["required"],
                         "valeur": None, "confiance": 0.0, "statut": "a_completer",
                         "motif": f"{c['raison']} : à compléter par écrit"})
    manquants = [r["id"] for r in reponses if r["required"] and r["valeur"] is None]
    return {"reponses": reponses, "data": data, "confiances": confiances,
            "invalides": [r["id"] for r in reponses if r["statut"] == "invalide"],
            "obligatoires_manquants": manquants,
            "a_completer": [c["id"] for c in plan.get("a_completer") or []],
            "complet": not manquants}


def informations_depuis(analyse: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Réponses au format « informations recueillies » du lot 70 (tiroir, export CSV, journal d'appel)."""
    return [{"id": r["id"], "libelle": r["label"], "type": LIBELLES_TYPES.get(r["type"], r["type"]),
             "valeur": r["valeur"], "confiance": r["confiance"], "statut": r["statut"], "motif": r["motif"]}
            for r in analyse.get("reponses") or []]


# ---------------------------------------------------------------------------
# 3. Soumission du formulaire et lien envoyé par WhatsApp
# ---------------------------------------------------------------------------

def document_soumission(form: Dict[str, Any], ev: Dict[str, Any], analyse: Dict[str, Any], *,
                        call_id: Optional[str], le: str) -> Dict[str, Any]:
    """Réponse au formulaire (collection db.form_submissions) créée par un appel de Liluvine.
    Même forme qu'une réponse saisie en ligne (id, form_id, client_id, user_id, user_label, data…) pour
    apparaître dans l'écran des réponses du formulaire, plus la SOURCE de l'appel.
    user_id unique (« appel-… ») : l'index unique (form_id, user_id) n'empêche pas plusieurs appels."""
    contact = ev.get("contact") or {}
    return {
        "id": str(uuid.uuid4()), "form_id": form["id"], "client_id": form.get("client_id"),
        "user_id": f"appel-{uuid.uuid4().hex[:12]}",
        "user_label": (contact.get("nom") or f"+{ev.get('telephone')}")[:120],
        "data": dict(analyse.get("data") or {}), "geo": None, "anonymous": False,
        "respondent_phone": ev.get("telephone"),
        "via": "appel_liluvine", "source": "appel Liluvine",
        "statut": "complete" if analyse.get("complet") else "incomplete",
        "appel": {"agenda_id": ev.get("id"), "call_id": call_id, "telephone": ev.get("telephone"),
                  "contact_nom": contact.get("nom"), "confiances": dict(analyse.get("confiances") or {}),
                  "invalides": list(analyse.get("invalides") or []),
                  "obligatoires_manquants": list(analyse.get("obligatoires_manquants") or []),
                  "a_completer": list(analyse.get("a_completer") or []),
                  "transcription_lien": f"/admin/liluvine-agenda?ev={ev.get('id')}"},
        "created_at": le, "updated_at": le, "revisions_count": 1,
    }


def base_publique(s: Dict[str, Any]) -> str:
    """Adresse publique du portail (réglage « public_base_url », sinon variable PUBLIC_BASE_URL)."""
    return ((s or {}).get("public_base_url") or os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")


def lien_public(form: Dict[str, Any], base: str) -> Optional[str]:
    """Lien de saisie en ligne du formulaire : seulement s'il est PUBLIC (sinon personne ne peut l'ouvrir)."""
    if not form or not form.get("is_public") or not base:
        return None
    return f"{base}/f/{form['id']}"


def envoyer_lien_voulu(reglage: str, plan: Dict[str, Any], analyse: Optional[Dict[str, Any]]) -> bool:
    """Faut-il envoyer le lien du formulaire à la fin ? « jamais », « toujours », ou « auto » (défaut) :
    oui s'il reste des champs à compléter par écrit OU si le formulaire n'est pas complet après l'appel."""
    if not plan or not plan.get("lien") or reglage == "jamais":
        return False
    if reglage == "toujours":
        return True
    return bool(plan.get("a_completer")) or not (analyse or {}).get("complet", False)


def texte_lien(prenom: str, plan: Dict[str, Any], analyse: Optional[Dict[str, Any]]) -> str:
    """Message WhatsApp envoyé avec le lien du formulaire (champs restant à compléter rappelés)."""
    salut = f"Bonjour {prenom}" if prenom else "Bonjour"
    restants = [r["label"] for r in (analyse or {}).get("reponses") or [] if r["valeur"] is None]
    if not analyse:
        restants = [c["label"] for c in (plan.get("champs") or []) + (plan.get("a_completer") or [])]
    lignes = [f"{salut}, ici Liluvine, l'assistante de SAWALI. Merci pour votre temps.",
              f"Pour compléter le formulaire « {plan.get('titre')} », voici le lien : {plan.get('lien')}"]
    if restants:
        lignes.append("Reste à renseigner : " + ", ".join(restants[:12]) + (" …" if len(restants) > 12 else ""))
    return "\n".join(lignes)[:3900]

