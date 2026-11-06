"""Lot 372.5 — Contenu de la « Checklist laboratoire » : SOURCE UNIQUE du document imprimable (PDF) ET du formulaire en ligne.

Pour un développeur WinDev : le contenu est une simple liste de SECTIONS ; chaque section a des POINTS (étapes), chaque point a des
QUESTIONS, chaque question a un ou plusieurs CHAMPS. La numérotation est CALCULÉE (jamais écrite à la main) :
    section 2, point 1, question 1, champ « a »  →  « 2.1.1a »
Un champ unique n'a pas de lettre (« 2.1.2 ») ; plusieurs champs dans la même question reçoivent a, b, c… (« 2.1.1a », « 2.1.1b »).
Ces numéros sont affichés dans le document et dans le formulaire : ils servent à référencer une réponse (« 2.4.1b : oui »).
Aucune dépendance (logique pure, testée) : le formulaire public et le PDF lisent la même liste.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

OUI_NON = ["Oui", "Non"]
ETAT = ["Fait", "Pas encore fait", "Impossible"]
ACCEPT_CSV = ".csv,.txt,.zip"
ACCEPT_JOURNAL = ".txt,.csv,.png,.jpg,.jpeg,.pdf,.zip"


def champ(type_: str, label: str, *, options: Optional[List[str]] = None, accept: Optional[str] = None, colonnes: Optional[List[str]] = None,
          qui: str = "") -> Dict[str, Any]:
    """Un champ de réponse. `qui` : « Responsable » ou « Technicien » (affiché dans le document, indicatif)."""
    c: Dict[str, Any] = {"type": type_, "label": label, "qui": qui}
    if options is not None:
        c["options"] = options
    if accept:
        c["accept"] = accept
    if colonnes:
        c["colonnes"] = colonnes
    return c


def question(titre: str, *champs: Dict[str, Any]) -> Dict[str, Any]:
    return {"titre": titre, "champs": list(champs)}


def _dossier(nom: str, exemples: str) -> List[Dict[str, Any]]:
    return [question(f"Dossier {nom}", champ("text", "Numéro du dossier", qui="Technicien"), champ("file", "Fichier CSV exporté", accept=ACCEPT_CSV, qui="Technicien"))]


SECTIONS: List[Dict[str, Any]] = [
    {"titre": "Poste du laboratoire", "introduction": "", "points": [
        {"titre": "Version de Loois", "consigne": "Ouvrir Loois sur le poste du laboratoire. Si la version n'est pas à jour, lancer maj.ps1 (version du 06/11/2026 au minimum).",
         "questions": [question("État de la mise à jour", champ("select", "Mise à jour de Loois", options=ETAT, qui="Responsable"))]},
        {"titre": "Adresse IP du PC de Loois", "consigne": "Windows : Paramètres › Réseau › Propriétés. Cette adresse est à saisir dans chaque automate relié par le réseau.",
         "questions": [question("Adresse du PC", champ("text", "Adresse IP du PC", qui="Responsable"))]},
        {"titre": "Pare-feu Windows", "consigne": "Autoriser Loois en entrée pour les ports utilisés par les automates.",
         "questions": [question("Autorisation", champ("select", "Pare-feu configuré", options=ETAT, qui="Responsable"), champ("text", "Ports autorisés", qui="Responsable"))]},
        {"titre": "Copie de test de la base Biolog", "consigne": "Disposer d'une copie de TEST de la base (jamais la base de production) pour essayer l'écriture des résultats.",
         "questions": [question("Copie de test", champ("select", "Copie de test disponible", options=OUI_NON, qui="Responsable"), champ("text", "Nom de la base de test", qui="Responsable"))]},
    ]},
    {"titre": "Exports de Biolog", "introduction":
        "Loois › Biolog › Explorateur de dossier LABO. Choisir un dossier dont les examens sont prescrits ET dont les résultats sont saisis, de préférence un dossier de test ou de "
        "personnel consentant. Cliquer sur Chercher, puis sur Exporter en CSV (masquage coché).", "points": [
        {"titre": "Hémostase", "consigne": "Dossier d'hémostase (coagulation).", "questions": _dossier("d'hémostase", "")},
        {"titre": "Immunoanalyse", "consigne": "Dossier d'immunoanalyse (hormones, marqueurs : TSH, FT3…).", "questions": _dossier("d'immunoanalyse", "")},
        {"titre": "Hématologie", "consigne": "Dossier d'hématologie (numération-formule).", "questions": _dossier("d'hématologie", "")},
        {"titre": "Chimie", "consigne": "Dossier de chimie (bilirubine, ALAT, ASAT…).", "questions": _dossier("de chimie", "")},
        {"titre": "Liste des examens et paramètres", "consigne": "Écran Examens et paramètres, puis Exporter en CSV (une seule fois).",
         "questions": [question("Liste des examens", champ("file", "Fichier CSV exporté", accept=ACCEPT_CSV, qui="Responsable"))]},
        {"titre": "Relecture avant envoi", "consigne": "Vérifier qu'aucun nom de patient n'apparaît dans les fichiers (données de santé reliées à un numéro de dossier).",
         "questions": [question("Relecture", champ("select", "Relecture effectuée", options=OUI_NON, qui="Responsable"))]},
        {"titre": "Correspondances examen / automate", "consigne":
            "Pour chaque examen de Biolog, indiquer l'automate et le code (ou le numéro de test) sur l'automate. Exemples : Fibrinogène = FIB sur le Sun UG ; TSH = TSH sur le MAGLUMI ; "
            "Numération = NFS sur le Sysmex ; Bilirubine totale = TBil (test n° 2) sur le Mindray.",
         "questions": [question("Tableau des correspondances", champ("table", "Correspondances", colonnes=["Examen dans Biolog", "Automate", "Code ou n° de test sur l'automate"], qui="Responsable"))]},
    ]},
    {"titre": "Branchement et essai des automates", "introduction":
        "Dans Loois : Biolog › Automates LABO › Ajouter, choisir le modèle, enregistrer, puis Démarrer. L'état passe à « connecté » quand l'automate se connecte.", "points": [
        {"titre": "Mindray BS-400", "consigne": "Dans l'automate : liaison LIS avec l'adresse IP du PC, le même port que dans Loois, protocole HL7, envoi des résultats en temps réel.",
         "questions": [question("Réglage et essai", champ("text", "Port choisi", qui="Responsable"),
                                champ("select", "Résultat d'un échantillon reçu dans Loois", options=["Oui", "Non", "Pas encore testé"], qui="Responsable"))]},
        {"titre": "Sysmex XN-L (XN-550)", "consigne": "Dans l'automate (réglage « hôte ») : adresse IP du PC, port (5000 par défaut) et protocole ASTM 1381-02/1394-97 ou ASTM 1381-95/1394-97.",
         "questions": [question("Réglage et essai", champ("select", "Variante choisie", options=["ASTM 1381-02/1394-97", "ASTM 1381-95/1394-97", "Liaison série"], qui="Responsable"),
                                champ("text", "Port choisi", qui="Responsable"),
                                champ("select", "Résultat d'un échantillon reçu dans Loois", options=["Oui", "Non", "Pas encore testé"], qui="Responsable"))]},
        {"titre": "MAGLUMI X8", "consigne": "Vérifier que l'automate est connecté (état « connecté » dans Loois).",
         "questions": [question("État", champ("select", "État dans Loois", options=["Connecté", "Non connecté"], qui="Responsable"))]},
        {"titre": "Sun UG", "consigne": "Liaison série : 9600 bauds, 8 bits, sans parité, 1 bit d'arrêt.",
         "questions": [question("Liaison série", champ("text", "Port COM utilisé", qui="Responsable"), champ("select", "État dans Loois", options=["Connecté", "Non connecté"], qui="Responsable"))]},
        {"titre": "Automate qui ne se connecte pas", "consigne": "Noter le message du journal de Loois (copie du texte ou photo de l'écran).",
         "questions": [question("Incident", champ("text", "Automate concerné", qui="Responsable"), champ("textarea", "Message du journal", qui="Responsable"),
                                champ("file", "Photo ou fichier du journal", accept=ACCEPT_JOURNAL, qui="Responsable"))]},
    ]},
    {"titre": "Mindray BS-400 : contrôle qualité et étalonnage", "introduction":
        "L'automate doit envoyer ses résultats en temps réel à Loois (point 3.1). Ces messages réels permettent de lire correctement les contrôles qualité et les étalonnages.", "points": [
        {"titre": "Contrôle qualité", "consigne": "Faire passer un contrôle qualité habituel (un test, un niveau), puis copier le journal de Loois › Automates LABO (texte ou photo).",
         "questions": [question("Contrôle", champ("text", "Test", qui="Technicien"), champ("text", "Niveau", qui="Technicien"),
                                champ("file", "Journal (texte ou photo)", accept=ACCEPT_JOURNAL, qui="Responsable"))]},
        {"titre": "Étalonnage", "consigne": "Faire passer ou refaire l'étalonnage d'un test, seulement si la routine du jour le prévoit (ne pas gaspiller de réactif).",
         "questions": [question("Étalonnage", champ("text", "Test", qui="Technicien"), champ("file", "Journal (texte ou photo)", accept=ACCEPT_JOURNAL, qui="Responsable"))]},
        {"titre": "Contrôle supplémentaire (facultatif)", "consigne": "Un deuxième niveau, et un second jour, permettent de vérifier la lecture.",
         "questions": [question("Journal du contrôle", champ("file", "Journal (texte ou photo)", accept=ACCEPT_JOURNAL, qui="Responsable"))]},
    ]},
    {"titre": "Enregistrement des résultats dans Biolog", "introduction": "", "points": [
        {"titre": "Résultats des patients", "consigne": "Les résultats seront écrits dans le dossier du patient dans Biolog, d'abord sur la copie de test.",
         "questions": [question("Principe", champ("select", "Principe confirmé", options=OUI_NON, qui="Responsable"))]},
        {"titre": "Contrôles qualité et étalonnages", "consigne": "Ils ne concernent aucun patient. Indiquer s'il existe dans Biolog un endroit où le laboratoire les enregistre déjà.",
         "questions": [question("Emplacement existant", champ("select", "Un tel endroit existe", options=OUI_NON, qui="Responsable"),
                                champ("text", "Nom de cet endroit (écran, onglet, table)", qui="Responsable"))]},
        {"titre": "À défaut d'emplacement dans Biolog", "consigne": "Les contrôles et étalonnages sont affichés dans Loois et exportables en CSV, sans toucher aux dossiers des patients.",
         "questions": [question("Accord", champ("select", "Affichage dans Loois et export CSV accepté", options=OUI_NON, qui="Responsable"))]},
    ]},
    {"titre": "Automates : modèle exact, type et version", "introduction":
        "Modèle : étiquette à l'arrière de l'automate (ou photo). Version : écran « À propos » du logiciel de l'automate.", "points": [
        {"titre": f"{nom} — {type_}", "consigne": consigne,
         "questions": [question("Identification", champ("text", f"Modèle exact{(' (' + indice + ')') if indice else ''}", qui="Responsable"), champ("text", "Version du logiciel", qui="Responsable"))]}
        for nom, type_, indice, consigne in [
            ("Sun UG", "analyseur d'hémostase (coagulation)", "série à confirmer", ""),
            ("MAGLUMI X8", "analyseur d'immunoanalyse par chimiluminescence", "modèle MAGLUMI ; X8 est le nom du logiciel", ""),
            ("Mindray BS", "analyseur de chimie", "BS-400 ou BS-430", ""),
            ("Sysmex XN", "analyseur d'hématologie", "XN-550, série XN-L", ""),
            ("SPIN 200E", "analyseur de chimie (à confirmer)", "", "Documentation d'interface LIS manquante (voir 6.7)."),
            ("Exias e|lyte / e|1", "analyseur d'ions (électrolytes)", "e|lyte ou e|1", "Ignorer ce point si l'appareil n'est pas utilisé au laboratoire."),
        ]] + [
        {"titre": "Documentation du SPIN 200E", "consigne": "Obtenir auprès du fournisseur ou du constructeur le manuel d'interface LIS (protocole de communication), et non le manuel d'utilisation.",
         "questions": [question("Manuel d'interface", champ("file", "Fichier du manuel (PDF)", accept=".pdf,.doc,.docx,.zip", qui="Responsable"),
                                champ("text", "Fournisseur ou constructeur contacté", qui="Responsable"))]},
        {"titre": "Autre automate", "consigne": "Ajouter ici tout automate non listé ci-dessus.",
         "questions": [question("Automate supplémentaire", champ("text", "Nom de l'automate", qui="Responsable"), champ("text", "Modèle exact", qui="Responsable"),
                                champ("text", "Type (chimie, hématologie…)", qui="Responsable"), champ("text", "Version du logiciel", qui="Responsable"))]},
    ]},
    {"titre": "Personne ayant rempli ce document", "introduction": "", "points": [
        {"titre": "Coordonnées", "consigne": "Ces informations permettent de poser une question en cas de doute sur une réponse.",
         "questions": [question("Identité", champ("text", "Nom et prénom"), champ("text", "Fonction (responsable, technicien…)"), champ("tel", "Téléphone ou WhatsApp"),
                                champ("date", "Date de remplissage"))]},
    ]},
]


def numero(section: int, point: int, question_: int, lettre: str = "") -> str:
    """« 2.1.1a » : section 2, point 1, question 1, champ a (sans lettre pour une question à champ unique)."""
    return f"{section}.{point}.{question_}{lettre}"


def champs_numerotes() -> List[Dict[str, Any]]:
    """Tous les champs, à plat, dans l'ordre, avec leur numéro et leur identifiant : [{numero, id, section, point, question, ...champ}]."""
    sortie: List[Dict[str, Any]] = []
    for i, section in enumerate(SECTIONS, start=1):
        for j, pt in enumerate(section["points"], start=1):
            for k, q in enumerate(pt["questions"], start=1):
                multiple = len(q["champs"]) > 1
                for n, c in enumerate(q["champs"]):
                    lettre = "abcdefghijklmnopqrstuvwxyz"[n] if multiple else ""
                    num = numero(i, j, k, lettre)
                    sortie.append({**c, "numero": num, "id": "q_" + num.replace(".", "_"), "section": i, "point": j, "question": k, "titre_question": q["titre"]})
    return sortie


def pages_formulaire() -> List[Dict[str, Any]]:
    """Pages du formulaire en ligne : une page par section ; avant chaque point, un bloc d'information (type « info ») avec son numéro, son titre et sa consigne ;
    chaque champ porte son numéro devant son libellé (« 2.1.1b — Fichier CSV exporté »)."""
    pages: List[Dict[str, Any]] = []
    for i, section in enumerate(SECTIONS, start=1):
        champs: List[Dict[str, Any]] = []
        if section["introduction"]:
            champs.append({"id": f"i_{i}", "type": "info", "label": f"{i}. {section['titre']}", "placeholder": section["introduction"], "required": False,
                           "col_start": 1, "col_span": 12, "row": 0})
        for j, pt in enumerate(section["points"], start=1):
            champs.append({"id": f"i_{i}_{j}", "type": "info", "label": f"{i}.{j} {pt['titre']}", "placeholder": pt.get("consigne", ""), "required": False,
                           "col_start": 1, "col_span": 12, "row": 0})
            for c in (x for x in champs_numerotes() if x["section"] == i and x["point"] == j):
                f: Dict[str, Any] = {"id": c["id"], "type": c["type"], "label": f"{c['numero']} — {c['label']}", "required": False, "col_start": 1, "col_span": 12, "row": 0}
                if c.get("qui"):
                    f["qui"] = c["qui"]                 # profil réservé : « Technicien » (pastille bleue) ou « Responsable » (pastille marron)
                if c.get("options") is not None:
                    f["options"] = c["options"]
                if c.get("accept"):
                    f["accept"] = c["accept"]
                if c.get("colonnes"):
                    f["columns"] = [{"key": f"c{n + 1}", "label": lab, "type": "text"} for n, lab in enumerate(c["colonnes"])]
                champs.append(f)
        for r, f in enumerate(champs):
            f["row"] = r
        pages.append({"id": f"pg_lab_{i}", "title": f"{i}. {section['titre']}", "fields": champs})
    return pages


DESCRIPTION = ("Document à remplir au laboratoire par le responsable et les techniciens. Chaque question porte un numéro (exemple : 2.4.1b) qui sert à référencer la réponse. "
               "Une pastille de couleur indique qui remplit la question : bleue = technicien, marron = responsable du laboratoire. "
               "Les pièces à joindre (exports CSV, journaux, photos) se déposent directement dans le formulaire. Les réponses sont enregistrées au fur et à mesure sur cet appareil "
               "et ne sont envoyées qu'au clic sur « Envoyer mes réponses » ; le formulaire peut être rempli en plusieurs fois, sur téléphone ou sur ordinateur.")

__all__ = ["SECTIONS", "numero", "champs_numerotes", "pages_formulaire", "DESCRIPTION"]
