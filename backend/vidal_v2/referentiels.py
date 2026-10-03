"""
backend/vidal_v2/referentiels.py
--------------------------------
Lot 56 — repris TEL QUEL de Ster (app/utils/vidal_referentiels.py), seuls les imports changent.

§ Revue d'implémentation VIDAL (reproche n°3 : "listes déroulantes dès que
les valeurs sont finies, contrôles de saisie") — SOURCE UNIQUE, côté
backend, de toutes les valeurs énumérées attendues par l'API de
sécurisation VIDAL (balises du corps XML de /alerts/full), avec leur
libellé français et les bornes numériques de contrôle.

Le miroir frontend est `frontend/src/lib/vidalReferentiels.js` (SAWALI) (mêmes
codes, mêmes libellés, mêmes bornes). Un test (tests/test_lot56_vidal_securisation_v2.py)
vérifie que chaque code déclaré ici figure aussi dans le fichier JS, pour
qu'une évolution d'un côté ne soit jamais oubliée de l'autre.

Fichier volontairement SANS dépendance (ni FastAPI, ni Mongo) : il se
recopie tel quel dans un autre portail (SAWALI) — voir
docs/vidal-securisation/README.md.
"""

import re

# ---------------------------------------------------------------------------
# Listes de valeurs (code VIDAL -> libellé français affiché)
# ---------------------------------------------------------------------------

# § <gender> (MI VIDAL §6.2.3) : UNKNOWN = sexe INDÉTERMINÉ (VIDAL renvoie
# alors les alertes des deux sexes) ; sexe NON RENSEIGNÉ = balise nil
# (aucune alerte liée au sexe) — deux situations distinctes, d'où la
# valeur vide "" proposée en plus dans la liste de l'interface.
SEXES = {
    "MALE": "Homme",
    "FEMALE": "Femme",
    "UNKNOWN": "Indéterminé",
}
LIBELLE_SEXE_NON_RENSEIGNE = "Non renseigné"

# § <breastFeeding> : "ALL" = allaitement en cours dont la durée n'est pas
# connue (choix "Non renseignée" de la durée approximative). MI VIDAL
# §6.2.7 : balise DÉPRÉCIÉE au profit de <breastFeedingStartDate> (qui
# permet à VIDAL de calculer la durée) — la date de début est donc la
# saisie privilégiée ; la durée approximative reste un repli.
ALLAITEMENTS = {
    "NONE": "Pas d'allaitement",
    "LESS_THAN_ONE_MONTH": "Depuis moins d'un mois",
    "MORE_THAN_ONE_MONTH": "Depuis plus d'un mois",
    "ALL": "Non renseignée",
}

# § <hepaticInsufficiency>
INSUFFISANCES_HEPATIQUES = {
    "NONE": "Aucune",
    "MODERATE": "Modérée",
    "SEVERE": "Sévère",
}

# § <durationType> : unité de la durée du traitement. Le second libellé
# (pluriel, minuscule) sert à l'unité entre parenthèses du champ "Durée".
TYPES_DUREE = {
    "MINUTE": "Minute(s)",
    "HOUR": "Heure(s)",
    "DAY": "Jour(s)",
    "WEEK": "Semaine(s)",
    "MONTH": "Mois",
    "YEAR": "Année(s)",
}
UNITES_DUREE_LIBELLE_CHAMP = {
    "MINUTE": "minutes", "HOUR": "heures", "DAY": "jours",
    "WEEK": "semaines", "MONTH": "mois", "YEAR": "années",
}

# § <frequencyType>
TYPES_FREQUENCE = {
    "THIS_DAY": "Ce jour (prise unique)",
    "PER_DAY": "Par jour",
    "PER_24_HOURS": "Par 24 heures",
}

# § <drugType> : COMMON_NAME_GROUP (groupe de dénomination commune) est
# transmis selon la "méthode 1" de la doc (<drugId> + <drugType>) ; les
# autres selon la "méthode 2" (<drug>vidal://<type>/<id></drug>).
TYPES_MEDICAMENT = {
    "PRODUCT": "Spécialité (produit)",
    "PACK": "Présentation (package)",
    "VMP": "Produit virtuel (VMP)",
    "UCD": "Unité commune de dispensation (UCD)",
    "PRESCRIBABLE": "Prescriptible",
    "COMMON_NAME_GROUP": "Groupe de dénomination commune",
}
# Préfixe d'URI VIDAL pour la méthode 2 (<drug>) — § MI VIDAL : les
# présentations s'écrivent vidal://package/{id} (et non "pack").
SCHEMAS_URI_MEDICAMENT = {"PRODUCT": "product", "PACK": "package", "VMP": "vmp", "UCD": "ucd", "PRESCRIBABLE": "prescribable"}
# § MI VIDAL §6.3 : unités, voies, indications et indicateurs se lisent sur
# la ressource du MÊME type que le médicament prescrit
# (/product/{id}/units, /package/{id}/units, /ucd/{id}/units, /vmp/{id}/units).
RESSOURCES_API_MEDICAMENT = {"PRODUCT": "product", "PACK": "package", "VMP": "vmp", "UCD": "ucd", "PRESCRIBABLE": "prescribable"}

# § <status> d'une ligne
STATUTS_LIGNE = {
    "ACTIVE": "En cours",
    "COMPLETED": "Terminée",
}

# § <groupType>
TYPES_GROUPE = {
    "SAME_ORDER": "Même prescription",
    "PREVIOUS_ORDER": "Prescription précédente (traitement en cours)",
    "INFUSION": "Perfusion",
}

# § <interval><unitId> d'un <dosage> : identifiants d'unité VIDAL listés
# par la doc (clé = identifiant transmis tel quel).
UNITES_INTERVALLE = {
    "169": "Seconde",
    "59": "Minute",
    "41": "Heure",
    "15": "3 heures",
    "11": "12 heures",
    "14": "24 heures",
    "44": "Jour",
    "77": "Semaine",
    "62": "Mois",
    "22": "Année",
}
# Libellé court (pluriel) pour l'unité entre parenthèses des champs min/max.
UNITES_INTERVALLE_LIBELLE_CHAMP = {
    "169": "secondes", "59": "minutes", "41": "heures", "15": "× 3 heures",
    "11": "× 12 heures", "14": "× 24 heures", "44": "jours", "77": "semaines",
    "62": "mois", "22": "années",
}
# § aucune unité d'intervalle par défaut : le médecin la choisit toujours.
# Pas d'endpoint VIDAL documenté pour cette liste : elle reste la liste des
# valeurs AUTORISÉES décrite par la documentation (énumération du schéma).

# § Filtre "forme recherchée" de la recherche médicament (reproche n°3,
# exemple "comp"). Liste documentée des formes galéniques usuelles, avec
# les abréviations rencontrées dans les libellés de spécialités VIDAL
# (ex : "DOLIPRANE 1000 mg cp") — le filtrage se fait sur le libellé et,
# quand l'API le fournit, sur la forme galénique renvoyée.
FORMES_GALENIQUES = {
    "comp": {"libelle": "Comprimé (comp, cp)", "motifs": ["cp", "cpr", "comp", "comprimé", "comprime", "lyoc"]},
    "gel": {"libelle": "Gélule (gél)", "motifs": ["gél", "gel", "gélule", "gelule"]},
    "sol_buv": {"libelle": "Solution buvable (sol buv)", "motifs": ["sol buv", "solution buvable", "gtte", "gouttes"]},
    "susp_buv": {"libelle": "Suspension buvable (susp buv)", "motifs": ["susp buv", "suspension buvable"]},
    "sirop": {"libelle": "Sirop", "motifs": ["sirop", "sir"]},
    "pdre": {"libelle": "Poudre / sachet (pdre, sach)", "motifs": ["pdre", "poudre", "sach", "sachet"]},
    "inj": {"libelle": "Injectable (inj)", "motifs": ["inj", "injectable", "sol inj", "pdre p sol inj"]},
    "bain_bouche": {"libelle": "Bain de bouche", "motifs": ["bain bouche", "bain de bouche", "p bain bouche"]},
    "gel_buccal": {"libelle": "Gel / pâte buccale ou gingivale", "motifs": ["gel buccal", "gel gingival", "pâte", "pate"]},
    "creme": {"libelle": "Crème / pommade (cr, pom)", "motifs": ["cr", "crème", "creme", "pom", "pommade"]},
    "suppo": {"libelle": "Suppositoire (suppos)", "motifs": ["suppos", "suppositoire"]},
    "collyre": {"libelle": "Collyre", "motifs": ["collyre", "coll"]},
    "spray": {"libelle": "Pulvérisation / spray (pulv)", "motifs": ["pulv", "spray", "aérosol", "aerosol"]},
    "cp_eff": {"libelle": "Comprimé effervescent (cp eff)", "motifs": ["cp eff", "comp eff", "effervescent"]},
    "cp_orodisp": {"libelle": "Comprimé orodispersible (cp orodisp)", "motifs": ["orodisp", "orodispersible"]},
}

# ---------------------------------------------------------------------------
# Bornes de contrôle de saisie (identiques côté frontend)
# ---------------------------------------------------------------------------
BORNES = {
    # § doc VIDAL : grossesse exprimée en semaines d'aménorrhée, de 2 à 42.
    "semaines_amenorrhee": {"min": 2, "max": 42},
    # § MI §6.2.6 : durée théorique 41 SA — avertir le médecin au-delà.
    "semaines_amenorrhee_alerte": 41,
    # § MI §6.2.7 : faire confirmer un allaitement au-delà de 2 ans.
    "allaitement_jours_alerte": 730,
    # § doc VIDAL : clairance de la créatinine en ml/min, de 0 à 120 ; MI
    # §6.2.8 : jamais 0 pour "inconnue" (interprété comme insuffisance
    # rénale sévère) et transmise en ENTIER -> 1 à 120.
    "clairance_ml_min": {"min": 1, "max": 120},
    # Bornes de vraisemblance (non imposées par VIDAL, garde-fous de saisie).
    "creatininemie_umol_l": {"min": 10, "max": 3000},
    "creatininemie_mg_dl": {"min": 0.1, "max": 34},
    "dfg_ml_min_173": {"min": 0, "max": 200},
    "poids_kg": {"min": 0.3, "max": 350},
    "taille_cm": {"min": 20, "max": 250},
    "age_ans": {"min": 0, "max": 130},
    "dose": {"min_exclu": 0, "max": 100000},
    "duree": {"min": 1, "max": 1000},
    "intervalle": {"min": 0, "max": 100000},
    "code_ald_longueur_max": 20,
}

# § Conversion créatininémie : 1 mg/dL = 88,4 µmol/L.
FACTEUR_MG_DL_VERS_UMOL_L = 88.4

# § Seuil de la catégorie d'allaitement déduite d'une date de début :
# moins de 30 jours révolus -> LESS_THAN_ONE_MONTH, sinon MORE_THAN_ONE_MONTH.
JOURS_SEUIL_ALLAITEMENT_UN_MOIS = 30

# § Ancres du rapport HTML /alerts/full/html (navigation par rubrique).
ANCRES_RAPPORT_HTML = {
    "menu_global": "Tout",
    "menu_synthesis": "Synthèse",
    "sommaire_precautions": "Sommaire des précautions",
    "menu_posology": "Posologies",
    "menu_allergy": "Allergies",
    "menu_contraindications_precautions": "Contre-indications / précautions",
    "menu_drugs_interaction": "Interactions médicamenteuses",
    "menu_pregnancy": "Grossesse / allaitement / procréation",
    "menu_side_effects": "Effets indésirables",
    "menu_phy_chm_interaction": "Interactions physico-chimiques",
    "menu_warning": "Mises en garde",
    "menu_observation": "Surveillance",
    "menu_dispensing_risk": "Risques lors de la dispensation",
    "menu_substance_redundancy": "Redondance de substance",
    "menu_profile": "Rappel du dossier patient",
    "menu_prescription": "Prescription",
}


# § MI VIDAL §6.5.5 : rubriques de la synthèse HTML V2 filtrable
# (<alert-display-types>, distincte de <alert-types>). Sans filtre, toutes
# les rubriques sont affichées ; synthèse, profil patient, contenu de
# l'ordonnance et "tout voir" le sont toujours.
RUBRIQUES_RAPPORT_HTML = {
    "POSOLOGY": "Posologie",
    "ALLERGY": "Allergies",
    "CONTRA_INDICATION_PRECAUTION": "Contre-indications / précautions d'emploi",
    "DRUG_INTERACTION": "Interactions médicamenteuses",
    "REPRODUCTIVE_HEALTH": "Grossesse / allaitement / procréation",
    "SIDE_EFFECT": "Effets indésirables",
    "PHYSICO_CHEMICAL_INTERACTION": "Incompatibilités physico-chimiques",
    "WARNING": "Mises en garde",
    "SURVEILLANCE": "Surveillances",
    "DISPENSING": "Risques lors de la dispensation",
    "DUPLICATE": "Redondances",
}

# § MI VIDAL §4.7.1 : indicateurs d'un médicament signalant qu'une donnée
# patient est UTILISÉE dans le calcul de ses alertes (/{type}/{id}/indicators).
# Âge, sexe, poids, taille et fonction rénale manquants -> alerte
# interruptive (le médecin doit cliquer pour passer outre) ; grossesse et
# allaitement -> information du risque.
INDICATEURS_DONNEES_PATIENT = {
    "26": "Âge", "27": "Poids", "28": "Grossesse", "29": "Allaitement",
    "30": "Fonction rénale (clairance)", "31": "Sexe", "36": "Taille",
}
INDICATEURS_INTERRUPTIFS = ("26", "27", "30", "31", "36")


def referentiels_en_dict() -> dict:
    """Ensemble des référentiels, sérialisable en JSON (GET /api/vidal/referentiels) — pratique pour un autre frontend (SAWALI) qui ne voudrait pas recopier le fichier JS."""
    return {
        "sexes": SEXES,
        "allaitements": ALLAITEMENTS,
        "insuffisances_hepatiques": INSUFFISANCES_HEPATIQUES,
        "types_duree": TYPES_DUREE,
        "unites_duree_libelle_champ": UNITES_DUREE_LIBELLE_CHAMP,
        "types_frequence": TYPES_FREQUENCE,
        "types_medicament": TYPES_MEDICAMENT,
        "statuts_ligne": STATUTS_LIGNE,
        "types_groupe": TYPES_GROUPE,
        "unites_intervalle": UNITES_INTERVALLE,
        "unites_intervalle_libelle_champ": UNITES_INTERVALLE_LIBELLE_CHAMP,
        "formes_galeniques": {code: f["libelle"] for code, f in FORMES_GALENIQUES.items()},
        "bornes": BORNES,
        "ancres_rapport_html": ANCRES_RAPPORT_HTML,
        "rubriques_rapport_html": RUBRIQUES_RAPPORT_HTML,
        "indicateurs_donnees_patient": INDICATEURS_DONNEES_PATIENT,
    }


def libelles_liste(referentiel: dict) -> str:
    """"Homme, Femme, Non précisé" — pour les messages d'erreur en français."""
    return ", ".join(f"{libelle} ({code})" for code, libelle in referentiel.items())


def correspond_forme_galenique(code_forme: str, titre: str, forme_api: str | None = None) -> bool:
    """§ filtre "forme recherchée" : vrai si le libellé du produit (ou la
    forme galénique renvoyée par l'API) contient l'un des motifs de la
    forme choisie, en mot entier (pour que "cr" ne capture pas "crème"
    d'un autre mot, ni "gel" le mot "gelée" accidentellement)."""
    forme = FORMES_GALENIQUES.get(code_forme)
    if not forme:
        return True  # forme inconnue -> aucun filtrage plutôt qu'une liste vide
    texte = f" {(titre or '').lower()} {(forme_api or '').lower()} "
    for motif in forme["motifs"]:
        if re.search(rf"(?<![\wéèêàùûôîç]){re.escape(motif.lower())}(?![\wéèêàùûôîç])", texte):
            return True
    return False
