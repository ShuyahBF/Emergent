"""
backend/vidal_v2/patients_fictifs.py
----------------------------------------
Lot 56 — repris de Ster (app/utils/vidal_patients_fictifs.py) : mêmes
profils, mêmes patients, mêmes prescriptions de test. Seule la fonction
`construire_patients_fictifs` (en bas) change : elle produit des patients
au format de `vidal_patients` (SAWALI) avec leur sous-document
`profil_clinique`, au lieu des fiches patient de Ster.

§ décision de l'utilisateur (validation VIDAL) : « Vrais appels [...] avec
des patients fictifs ; les patients doivent couvrir tous les profils
cliniques (bébés, femmes, hommes, etc.), 3 patients par profil. Aucune
donnée de vrai patient n'est transmise à VIDAL. »

Définition des PROFILS cliniques de recette (3 patients chacun) et
construction de leurs données (relatives à la date du jour, pour que les
âges, semaines d'aménorrhée et durées d'allaitement restent justes à
chaque remise à neuf). Chaque profil porte des prescriptions de test : le
NOM à rechercher dans VIDAL (aucun identifiant VIDAL inventé — le produit
est choisi lors de la recette) et le comportement attendu.

§ correction impérative de l'utilisateur : « Rien ne doit être simulé ni
venir des exemples de la documentation. » — ce module ne contient AUCUNE
référence VIDAL : allergies, molécules, pathologies et traitements en
cours ne sont décrits que par des TERMES DE RECHERCHE. Les références sont
obtenues par de vraies recherches dans l'API VIDAL de production au moment
de la génération (routes/vidal_validation.py) ; à défaut, elles
restent vides et marquées « à rechercher dans VIDAL pendant la recette ».
Sans dépendance Mongo/FastAPI (portable).
"""

from datetime import date, timedelta
from typing import Optional

from vidal_v2.fonction_renale import calculer_fonction_renale_locale

PREFIXE_NOM = "FICTIF –"


def _naissance(aujourdhui: date, ans: int = 0, mois: int = 0) -> date:
    jours = int(ans * 365.25 + mois * 30.44) + 15
    return aujourdhui - timedelta(days=jours)


def _p(suffixe, sexe, ans=0, mois=0, poids=None, taille=None, **cliniques):
    return {"suffixe": suffixe, "sexe": sexe, "ans": ans, "mois": mois, "poids": poids, "taille": taille, **cliniques}


# Termes de recherche (jamais des références) : classe d'allergie
# (/allergies, catégorie ALLERGY), substance (/allergies, catégorie MOLECULE),
# pathologie CIM-10 (/pathologies).
def _allergie(terme):
    return {"recherche": terme, "categorie": "ALLERGY"}


def _molecule(terme):
    return {"recherche": terme, "categorie": "MOLECULE"}


def _pathologie(terme):
    return {"recherche": terme, "categorie": "PATHOLOGY"}

# Chaque prescription de test : nom à rechercher, forme (code du filtre),
# dose par 24 h, fréquence, durée, et comportement attendu de VIDAL.
PROFILS: list[dict] = [
    {
        "code": "NOURRISSON", "libelle": "Nourrisson (< 2 ans, poids faible)",
        "patients": [_p(1, "Masculin", mois=4, poids=6.2, taille=62), _p(2, "Féminin", mois=11, poids=8.5, taille=72), _p(3, "Masculin", ans=1, mois=6, poids=10.8, taille=82)],
        "prescriptions": [
            {"recherche": "paracétamol", "forme": "sol_buv", "dose": 4, "frequence": "PER_DAY", "duree": 3, "type_duree": "DAY",
             "attendu": "Contrôle posologique selon l'âge et le poids ; une dose adulte doit déclencher un surdosage."},
            {"recherche": "ibuprofène", "forme": "susp_buv", "dose": 3, "frequence": "PER_DAY", "duree": 3, "type_duree": "DAY",
             "attendu": "Précaution / contre-indication selon l'âge (nourrisson de moins de 3 mois)."},
        ],
        "alertes_attendues": ["posolog"],
    },
    {
        "code": "ENFANT", "libelle": "Enfant (2–11 ans)",
        "patients": [_p(1, "Féminin", ans=4, poids=16, taille=103), _p(2, "Masculin", ans=7, poids=23, taille=122), _p(3, "Féminin", ans=10, poids=32, taille=138)],
        "prescriptions": [
            {"recherche": "amoxicilline", "forme": "susp_buv", "dose": 3, "frequence": "PER_DAY", "duree": 7, "type_duree": "DAY",
             "attendu": "Contrôle posologique pondéral (mg/kg/j)."},
            {"recherche": "doxycycline", "forme": "comp", "dose": 1, "frequence": "PER_DAY", "duree": 7, "type_duree": "DAY",
             "attendu": "Contre-indication / précaution chez l'enfant de moins de 8 ans (coloration dentaire)."},
        ],
        "alertes_attendues": ["enfant"],
    },
    {
        "code": "ADOLESCENT", "libelle": "Adolescent (12–17 ans)",
        "patients": [_p(1, "Masculin", ans=13, poids=45, taille=158), _p(2, "Féminin", ans=15, poids=52, taille=162), _p(3, "Masculin", ans=17, poids=65, taille=176)],
        "prescriptions": [
            {"recherche": "aspirine", "forme": "comp", "dose": 3, "frequence": "PER_DAY", "duree": 3, "type_duree": "DAY",
             "attendu": "Mise en garde / précaution chez l'adolescent (syndrome de Reye)."},
        ],
        "alertes_attendues": [],
    },
    {
        "code": "HOMME", "libelle": "Homme adulte sans particularité",
        "patients": [_p(1, "Masculin", ans=30, poids=72, taille=175, creat=80), _p(2, "Masculin", ans=45, poids=83, taille=178, creat=85), _p(3, "Masculin", ans=60, poids=79, taille=172, creat=72)],
        "prescriptions": [
            {"recherche": "paracétamol", "forme": "comp", "dose": 3, "frequence": "PER_DAY", "duree": 5, "type_duree": "DAY",
             "attendu": "Aucune alerte majeure à posologie usuelle ; surdosage si dose > 4 g/24 h."},
            {"recherche": "amoxicilline", "forme": "gel", "dose": 3, "frequence": "PER_DAY", "duree": 7, "type_duree": "DAY",
             "attendu": "Aucune alerte majeure (profil témoin)."},
        ],
        "alertes_attendues": [],
    },
    {
        "code": "FEMME", "libelle": "Femme adulte sans particularité",
        "patients": [_p(1, "Féminin", ans=25, poids=58, taille=163, creat=60), _p(2, "Féminin", ans=38, poids=66, taille=165, creat=65), _p(3, "Féminin", ans=52, poids=70, taille=160, creat=70)],
        "prescriptions": [
            {"recherche": "ibuprofène", "forme": "comp", "dose": 3, "frequence": "PER_DAY", "duree": 3, "type_duree": "DAY",
             "attendu": "Aucune alerte grossesse (patiente non enceinte) ; profil témoin."},
        ],
        "alertes_attendues": [],
    },
    {
        "code": "ENCEINTE", "libelle": "Femme enceinte (1er, 2e, 3e trimestre)",
        "patients": [_p(1, "Féminin", ans=27, poids=60, taille=165, sa=8), _p(2, "Féminin", ans=31, poids=68, taille=162, sa=20), _p(3, "Féminin", ans=34, poids=75, taille=168, sa=34)],
        "prescriptions": [
            {"recherche": "ibuprofène", "forme": "comp", "dose": 3, "frequence": "PER_DAY", "duree": 3, "type_duree": "DAY",
             "attendu": "AINS : contre-indication à partir du 6e mois (3e trimestre), précaution avant ; alerte grossesse."},
            {"recherche": "doxycycline", "forme": "comp", "dose": 1, "frequence": "PER_DAY", "duree": 7, "type_duree": "DAY",
             "attendu": "Contre-indication / mise en garde grossesse (cyclines)."},
        ],
        "alertes_attendues": ["grossesse"],
    },
    {
        "code": "ALLAITANTE", "libelle": "Femme allaitante (< 1 mois, > 1 mois, date inconnue)",
        "patients": [_p(1, "Féminin", ans=28, poids=64, taille=164, allaitement_jours=12), _p(2, "Féminin", ans=32, poids=62, taille=160, allaitement_jours=90),
                     _p(3, "Féminin", ans=35, poids=70, taille=166, allaitement="ALL")],
        "prescriptions": [
            {"recherche": "codéine", "forme": "comp", "dose": 3, "frequence": "PER_DAY", "duree": 3, "type_duree": "DAY",
             "attendu": "Contre-indication / mise en garde allaitement (codéine)."},
        ],
        "alertes_attendues": ["allaitement"],
    },
    {
        "code": "AGE", "libelle": "Personne âgée (≥ 75 ans)",
        "patients": [_p(1, "Masculin", ans=76, poids=68, taille=168, creat=95), _p(2, "Féminin", ans=82, poids=55, taille=155, creat=90), _p(3, "Masculin", ans=89, poids=60, taille=165, creat=110)],
        "prescriptions": [
            {"recherche": "diazépam", "forme": "comp", "dose": 2, "frequence": "PER_DAY", "duree": 14, "type_duree": "DAY",
             "attendu": "Précaution / mise en garde chez le sujet âgé (benzodiazépine, risque de chute)."},
        ],
        "alertes_attendues": [],
    },
    {
        "code": "INSUFFISANCE_RENALE", "libelle": "Insuffisance rénale (légère, modérée, sévère)",
        "patients": [_p(1, "Masculin", ans=62, poids=75, taille=172, creat=115), _p(2, "Féminin", ans=68, poids=62, taille=160, creat=160),
                     _p(3, "Masculin", ans=72, poids=70, taille=170, creat=380)],
        "prescriptions": [
            {"recherche": "énalapril", "forme": "comp", "dose": 1, "frequence": "PER_DAY", "duree": 1, "type_duree": "MONTH",
             "attendu": "IEC : adaptation posologique / précaution en insuffisance rénale sévère."},
            {"recherche": "metformine", "forme": "comp", "dose": 2, "frequence": "PER_DAY", "duree": 1, "type_duree": "MONTH",
             "attendu": "Contre-indication en insuffisance rénale sévère (clairance < 30 ml/min)."},
        ],
        "alertes_attendues": ["rénal"],
    },
    {
        "code": "INSUFFISANCE_HEPATIQUE", "libelle": "Insuffisance hépatique (modérée, sévère)",
        "patients": [_p(1, "Masculin", ans=55, poids=78, taille=176, hepatique="MODERATE"), _p(2, "Féminin", ans=60, poids=60, taille=162, hepatique="SEVERE"),
                     _p(3, "Masculin", ans=48, poids=85, taille=181, hepatique="SEVERE")],
        "prescriptions": [
            {"recherche": "paracétamol", "forme": "comp", "dose": 4, "frequence": "PER_DAY", "duree": 5, "type_duree": "DAY",
             "attendu": "Donnée transmise (la MI précise qu'elle n'est pas encore exploitée pour toutes les alertes) : vérifier sa présence dans le rappel du dossier patient."},
        ],
        "alertes_attendues": [],
    },
    {
        "code": "ALLERGIQUE", "libelle": "Patient allergique (classe, molécule/excipient, pathologie CIM-10)",
        "patients": [_p(1, "Féminin", ans=35, poids=62, taille=165, allergies=[_allergie("pénicillines")]),
                     _p(2, "Masculin", ans=42, poids=84, taille=178, molecules=[_molecule("amoxicilline")]),
                     _p(3, "Féminin", ans=50, poids=70, taille=160, allergies=[_allergie("paracétamol")],
                        pathologies=[_pathologie("asthme")])],
        "prescriptions": [
            {"recherche": "amoxicilline", "forme": "gel", "dose": 3, "frequence": "PER_DAY", "duree": 7, "type_duree": "DAY",
             "attendu": "Alerte allergie (niveau 4) chez les patients 1 et 2 (pénicillines)."},
            {"recherche": "paracétamol", "forme": "comp", "dose": 3, "frequence": "PER_DAY", "duree": 3, "type_duree": "DAY",
             "attendu": "Alerte allergie chez le patient 3 ; AINS/aspirine : précaution asthme."},
        ],
        "alertes_attendues": ["allergi"],
    },
    {
        "code": "POLYMEDIQUE", "libelle": "Patient polymédiqué (traitements en cours)",
        "patients": [_p(1, "Masculin", ans=70, poids=78, taille=172, creat=100, traitements=["warfarine", "amiodarone", "metformine"]),
                     _p(2, "Féminin", ans=66, poids=70, taille=160, creat=90, traitements=["énalapril", "furosémide", "allopurinol"]),
                     _p(3, "Masculin", ans=74, poids=82, taille=175, creat=105, traitements=["clopidogrel", "oméprazole", "simvastatine"])],
        "prescriptions": [
            {"recherche": "ibuprofène", "forme": "comp", "dose": 3, "frequence": "PER_DAY", "duree": 5, "type_duree": "DAY",
             "attendu": "Interactions médicamenteuses avec les traitements en cours (anticoagulant, IEC/diurétique, antiagrégant)."},
            {"recherche": "clarithromycine", "forme": "comp", "dose": 2, "frequence": "PER_DAY", "duree": 7, "type_duree": "DAY",
             "attendu": "Interaction avec la simvastatine / l'amiodarone."},
        ],
        "alertes_attendues": ["interaction"],
    },
    {
        "code": "SEXE_NON_RENSEIGNE", "libelle": "Sexe non renseigné / indéterminé",
        "patients": [_p(1, None, ans=40, poids=70, taille=170), _p(2, None, ans=29, poids=60, taille=165, indetermine=True),
                     _p(3, None, ans=33, poids=65, taille=168, indetermine=True)],
        "prescriptions": [
            {"recherche": "finastéride", "forme": "comp", "dose": 1, "frequence": "PER_DAY", "duree": 1, "type_duree": "MONTH",
             "attendu": "Sexe non renseigné : aucune alerte liée au sexe ; indéterminé : alertes des deux sexes."},
        ],
        "alertes_attendues": [],
    },
    {
        "code": "POIDS_EXTREMES", "libelle": "Poids et taille extrêmes (obésité, maigreur)",
        "patients": [_p(1, "Masculin", ans=45, poids=150, taille=172, creat=90), _p(2, "Féminin", ans=24, poids=38, taille=165, creat=55),
                     _p(3, "Féminin", ans=50, poids=135, taille=158, creat=80)],
        "prescriptions": [
            {"recherche": "amoxicilline", "forme": "gel", "dose": 6, "frequence": "PER_DAY", "duree": 7, "type_duree": "DAY",
             "attendu": "Contrôle posologique selon le poids / la surface corporelle."},
        ],
        "alertes_attendues": [],
    },
    {
        # § MI §4.7.1 : médicament dont les alertes dépendent d'une donnée
        # patient manquante -> alerte INTERRUPTIVE côté SAWALI.
        "code": "DONNEES_INCOMPLETES", "libelle": "Données patient incomplètes (poids, taille, fonction rénale absents)",
        "patients": [_p(1, "Masculin", ans=35), _p(2, "Féminin", ans=41), _p(3, "Masculin", ans=8)],
        "prescriptions": [
            {"recherche": "amoxicilline", "forme": "susp_buv", "dose": 3, "frequence": "PER_DAY", "duree": 7, "type_duree": "DAY",
             "attendu": "SAWALI : alerte interruptive « données manquantes » (poids) avant l'envoi ; passer outre pour envoyer."},
        ],
        "alertes_attendues": [],
    },
]


# Sexe des définitions ci-dessus (libellés de Ster) -> code VIDAL du profil clinique.
_SEXE_VIDAL = {"Masculin": "MALE", "Féminin": "FEMALE"}


def construire_patients_fictifs(aujourdhui: Optional[date] = None) -> list[dict]:
    """
    Liste à plat des patients fictifs : {code_fictif, profil, document
    (champs d'un patient de `vidal_patients`, dont `profil_clinique`),
    recherches (termes à résoudre dans VIDAL), traitements (noms des
    médicaments d'une ordonnance antérieure fictive)}. L'identifiant `id`
    et le propriétaire `user_id` sont posés par l'appelant (création) ou
    conservés (remise à neuf).
    """
    jour = aujourdhui or date.today()
    resultat = []
    for profil in PROFILS:
        for spec in profil["patients"]:
            naissance = _naissance(jour, spec["ans"], spec["mois"])
            nom = f"{PREFIXE_NOM} {profil['libelle'].split(' (')[0]} {spec['suffixe']}"
            # § "indéterminé" (UNKNOWN) est distinct de "non renseigné" (None).
            sexe = "UNKNOWN" if spec.get("indetermine") else _SEXE_VIDAL.get(spec["sexe"])
            clinique = {
                "date_naissance": naissance.isoformat(), "sexe": sexe,
                "poids_kg": spec["poids"], "taille_cm": spec["taille"],
                "date_saisie_poids_taille": jour.isoformat() if spec["poids"] or spec["taille"] else None,
                # § aucune valeur par défaut : non renseignée sauf pour les profils hépatiques.
                "insuffisance_hepatique": spec.get("hepatique"),
                # Références VIDAL : remplies UNIQUEMENT par de vraies recherches (voir `recherches`).
                "allergies": [], "molecules_a_eviter": [], "pathologies": [],
                "derniere_creatininemie_umol_l": None, "clairance_creatinine_ml_min": None, "dfg_ml_min_173": None,
                "date_bilan_renal": None, "date_dernieres_regles": None, "allaitement": None, "date_debut_allaitement": None,
                "groupe_reference_dfg": None,
            }
            if spec.get("creat") and spec["poids"] and sexe in ("MALE", "FEMALE"):
                renal = calculer_fonction_renale_locale(date_naissance=naissance, sexe=sexe, poids_kg=spec["poids"],
                                                        creatininemie_umol_l=spec["creat"], reference=jour)
                clinique.update({
                    "derniere_creatininemie_umol_l": float(spec["creat"]), "clairance_creatinine_ml_min": renal.get("creatin"),
                    "dfg_ml_min_173": renal.get("glomerularFiltrationRate"), "date_bilan_renal": jour.isoformat(),
                })
            if spec.get("sa"):
                clinique["date_dernieres_regles"] = (jour - timedelta(days=7 * spec["sa"] + 2)).isoformat()
            if spec.get("allaitement_jours"):
                clinique.update({"allaitement": "LESS_THAN_ONE_MONTH" if spec["allaitement_jours"] < 30 else "MORE_THAN_ONE_MONTH",
                                 "date_debut_allaitement": (jour - timedelta(days=spec["allaitement_jours"])).isoformat()})
            elif spec.get("allaitement"):
                clinique["allaitement"] = spec["allaitement"]
            doc = {
                # § jamais transmis à VIDAL (seul le bloc <patient> clinique part) ;
                # aucun n° WhatsApp pour ne jamais envoyer d'ordonnance fictive.
                "name": nom, "whatsapp_number": None,
                "est_fictif": True, "profil_fictif": profil["libelle"], "code_fictif": f"{profil['code']}-{spec['suffixe']}",
                "prescriptions_test_validation": profil["prescriptions"],
                "alertes_attendues_validation": profil["alertes_attendues"],
                "profil_clinique": clinique,
            }
            recherches = spec.get("allergies", []) + spec.get("molecules", []) + spec.get("pathologies", [])
            resultat.append({"code_fictif": doc["code_fictif"], "profil": profil["libelle"], "document": doc,
                             "recherches": recherches, "traitements": spec.get("traitements", [])})
    return resultat
