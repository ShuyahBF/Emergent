"""
backend/vidal_v2/modeles.py
-------------------------------
Lot 56 — repris de Ster (app/models/vidal_securisation.py). Adaptations
SAWALI : `ModeleBase` de Ster remplacé par `pydantic.BaseModel` (le
nettoyage des espaces est refait ici), et rattachement local de la
sécurisation par `patient_id` (identifiant d'un patient de
`vidal_patients`) au lieu du numéro de dossier patient de Ster.

§ Revue d'implémentation VIDAL (reproche n°3 : "contrôles de saisie
(types, bornes, cohérence)") — validation SERVEUR du payload de
sécurisation, strictement alignée sur les contrôles du frontend
(`frontend/src/lib/vidalReferentiels.js`, fonctions validerPatient /
validerLigne) : mêmes bornes (vidal_v2/referentiels.BORNES), mêmes
listes de valeurs, mêmes règles de cohérence.

Toute erreur remonte en HTTP 422 avec un message FRANÇAIS par champ :
    {"detail": {"message": "...", "erreurs": [{"champ": "patient.weeksOfAmenorrhea", "message": "..."}]}}
(voir `valider_payload_securisation` en bas de fichier).

Convention interne : un contrôle de COHÉRENCE (portant sur plusieurs
champs, donc écrit dans un model_validator) lève
`ValueError("nomDuChamp|message")` — éventuellement plusieurs lignes —
pour que l'erreur soit rattachée au bon champ et non au bloc entier.

Les noms de champs reprennent ceux des balises VIDAL (dateOfBirth,
weeksOfAmenorrhea, creatin...) : le payload validé alimente directement
la construction XML (vidal_v2/xml_securisation.py).
"""

import re
from datetime import date
from typing import Any, Optional

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from vidal_v2.referentiels import (
    ALLAITEMENTS, BORNES, INSUFFISANCES_HEPATIQUES, JOURS_SEUIL_ALLAITEMENT_UN_MOIS, SEXES, STATUTS_LIGNE,
    RUBRIQUES_RAPPORT_HTML, TYPES_DUREE, TYPES_FREQUENCE, TYPES_GROUPE, TYPES_MEDICAMENT, UNITES_INTERVALLE, libelles_liste,
)

_IDENTIFIANT_RE = re.compile(r"^\d+$")


def _dans_liste(valeur: Optional[str], referentiel: dict, libelle_champ: str) -> Optional[str]:
    if valeur is None:
        return None
    if valeur not in referentiel:
        raise ValueError(f"{libelle_champ} : valeur « {valeur} » non autorisée. Valeurs possibles : {libelles_liste(referentiel)}.")
    return valeur


def _borne(valeur: Optional[float], cle: str, libelle: str) -> Optional[float]:
    """Contrôle min/max (inclusifs) ou min exclusif, d'après BORNES[cle]."""
    if valeur is None:
        return None
    b = BORNES[cle]
    # Lot 56.4 — un nombre négatif est toujours refusé, avec un message explicite
    # (les champs numériques de l'interface sont des « spins » qui ne descendent pas sous 0).
    if valeur < 0:
        raise ValueError(f"{libelle} : un nombre négatif n'est pas accepté.")
    if "min_exclu" in b and valeur <= b["min_exclu"]:
        raise ValueError(f"{libelle} doit être strictement supérieur(e) à {b['min_exclu']:g}.")
    if "min" in b and valeur < b["min"]:
        raise ValueError(f"{libelle} doit être compris(e) entre {b['min']:g} et {b['max']:g}.")
    if valeur > b["max"]:
        raise ValueError(f"{libelle} doit être compris(e) entre {b.get('min', b.get('min_exclu', 0)):g} et {b['max']:g}.")
    return valeur


def _date_non_future(valeur: Optional[date], libelle: str) -> Optional[date]:
    if valeur is not None and valeur > date.today():
        raise ValueError(f"{libelle} ne peut pas être dans le futur.")
    return valeur


def _identifiant(valeur: Any, libelle: str, prefixe_uri: Optional[str] = None) -> Optional[str]:
    """Accepte un entier, sa forme texte ou (si prefixe_uri) l'URI "vidal://<type>/<id>" — renvoie toujours la forme texte de l'identifiant."""
    if valeur is None or valeur == "":
        return None
    texte = str(valeur).strip()
    if prefixe_uri and texte.startswith(prefixe_uri):
        texte = texte[len(prefixe_uri):]
    if not _IDENTIFIANT_RE.match(texte):
        raise ValueError(f"{libelle} : identifiant VIDAL invalide « {valeur} » (nombre entier attendu).")
    return texte


class _ModeleVidal(BaseModel):
    # extra="ignore" : un champ inconnu envoyé par l'interface (ex. le groupe
    # de référence du DFG glissé par erreur dans `patient`) est IGNORÉ, donc
    # ne peut jamais atteindre le XML envoyé à VIDAL.
    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _vides_en_none(cls, donnees: Any) -> Any:
        # § un champ de formulaire vidé arrive en "" : on le traite comme
        # "non renseigné" plutôt que comme un nombre/une date invalide.
        # (SAWALI) Les espaces de début/fin de tout texte sont aussi retirés,
        # comme le faisait la classe ModeleBase de Ster.
        if isinstance(donnees, dict):
            propres = {}
            for cle, v in donnees.items():
                if isinstance(v, str):
                    v = v.strip()
                propres[cle] = None if v == "" else v
            return propres
        return donnees


class ReferenceVidal(_ModeleVidal):
    """Allergie / molécule / pathologie : {label, ref}. `ref` nul = texte libre informatif, jamais transmis à VIDAL."""
    label: Optional[str] = None
    ref: Optional[str] = None

    @field_validator("ref")
    @classmethod
    def _ref_vidal(cls, v: Optional[str]) -> Optional[str]:
        # § MI §5.2.1.1 : une pathologie peut aussi être passée par son CODE
        # CIM-10 (vidal://cim10/code/<code>) plutôt que par son identifiant.
        if v is not None and not (re.match(r"^vidal://[a-z0-9_]+/\d+$", v) or re.match(r"^vidal://cim10/code/[A-Z][0-9A-Z.]{1,7}$", v)):
            raise ValueError(f"Référence VIDAL invalide « {v} » (attendu : vidal://<type>/<identifiant> ou vidal://cim10/code/<code>).")
        return v


class PatientSecurisation(_ModeleVidal):
    dateOfBirth: Optional[date] = None
    gender: Optional[str] = None
    weight: Optional[float] = None
    height: Optional[float] = None
    # Date de saisie du poids/de la taille — affichée ("Saisi le ..."), jamais transmise.
    weightDate: Optional[date] = None
    breastFeeding: Optional[str] = None
    breastFeedingStartDate: Optional[date] = None
    weeksOfAmenorrhea: Optional[int] = None
    # Date des dernières règles : convertie en semaines d'aménorrhée si celles-ci ne sont pas fournies.
    lastMenstrualPeriodDate: Optional[date] = None
    # § MI §6.2.8 : clairance transmise en ENTIER (pas de virgule, pas de point), jamais 0.
    creatin: Optional[int] = None
    serumCreatinine: Optional[float] = None
    glomerularFiltrationRate: Optional[float] = None
    renalDate: Optional[date] = None
    hepaticInsufficiency: Optional[str] = None
    allergies: list[ReferenceVidal] = Field(default_factory=list)
    molecules: list[ReferenceVidal] = Field(default_factory=list)
    pathologies: list[ReferenceVidal] = Field(default_factory=list)
    # § compatibilité : ancien nom de la clairance calculée (frontend antérieur).
    clairance: Optional[float] = None

    @field_validator("dateOfBirth")
    @classmethod
    def _v_naissance(cls, v):
        _date_non_future(v, "La date de naissance")
        if v is not None and (date.today().year - v.year) > BORNES["age_ans"]["max"]:
            raise ValueError(f"La date de naissance correspond à un âge supérieur à {BORNES['age_ans']['max']} ans.")
        return v

    @field_validator("gender")
    @classmethod
    def _v_sexe(cls, v):
        return _dans_liste(v, SEXES, "Sexe")

    @field_validator("weight")
    @classmethod
    def _v_poids(cls, v):
        return _borne(v, "poids_kg", "Le poids (kg)")

    @field_validator("height")
    @classmethod
    def _v_taille(cls, v):
        return _borne(v, "taille_cm", "La taille (cm)")

    @field_validator("weightDate", "renalDate")
    @classmethod
    def _v_dates_saisie(cls, v):
        return _date_non_future(v, "La date de saisie")

    @field_validator("breastFeeding")
    @classmethod
    def _v_allaitement(cls, v):
        return _dans_liste(v, ALLAITEMENTS, "Allaitement")

    @field_validator("breastFeedingStartDate")
    @classmethod
    def _v_debut_allaitement(cls, v):
        return _date_non_future(v, "La date de début d'allaitement")

    @field_validator("weeksOfAmenorrhea")
    @classmethod
    def _v_sa(cls, v):
        b = BORNES["semaines_amenorrhee"]
        if v is not None and v < 0:  # Lot 56.4 — négatif refusé explicitement
            raise ValueError("Les semaines d'aménorrhée (SA) ne peuvent pas être négatives.")
        if v is not None and not (b["min"] <= v <= b["max"]):
            raise ValueError(f"Les semaines d'aménorrhée (SA) doivent être comprises entre {b['min']} et {b['max']}.")
        return v

    @field_validator("lastMenstrualPeriodDate")
    @classmethod
    def _v_ddr(cls, v):
        return _date_non_future(v, "La date des dernières règles")

    @field_validator("creatin")
    @classmethod
    def _v_clairance(cls, v):
        b = BORNES["clairance_ml_min"]
        if v is not None and v < 0:  # Lot 56.4 — négatif refusé explicitement
            raise ValueError("La clairance de la créatinine (ml/min) ne peut pas être négative.")
        if v is not None and not (b["min"] <= v <= b["max"]):
            raise ValueError(
                f"La clairance de la créatinine (ml/min) doit être un entier compris entre {b['min']} et {b['max']} "
                "(au-delà de 120 : saisir 120, fonction rénale normale ; inconnue : laisser vide, jamais 0)."
            )
        return v

    @field_validator("serumCreatinine")
    @classmethod
    def _v_creatininemie(cls, v):
        return _borne(v, "creatininemie_umol_l", "La créatininémie (µmol/L)")

    @field_validator("glomerularFiltrationRate")
    @classmethod
    def _v_dfg(cls, v):
        return _borne(v, "dfg_ml_min_173", "Le débit de filtration glomérulaire (ml/min/1,73 m²)")

    @field_validator("hepaticInsufficiency")
    @classmethod
    def _v_hepatique(cls, v):
        return _dans_liste(v, INSUFFISANCES_HEPATIQUES, "Insuffisance hépatique")

    @model_validator(mode="after")
    def _coherence(self):
        erreurs: list[str] = []
        aujourdhui = date.today()

        # § compatibilité : l'ancien champ "clairance" (valeur brute, parfois
        # > 120) alimente <creatin>, arrondie et bornée comme la nouvelle saisie.
        if self.creatin is None and self.clairance is not None:
            from vidal_v2.fonction_renale import clairance_transmise
            self.creatin = clairance_transmise(self.clairance)
        self.clairance = None

        # § grossesse/allaitement (MI §6.2.6/6.2.7) : réservés à une patiente
        # ou à un sexe NON RENSEIGNÉ — pour un homme ou un sexe indéterminé
        # ils sont NEUTRALISÉS (jamais transmis), comme le bloc masqué de
        # l'interface (VIDAL alerterait sinon sur une incohérence).
        if self.gender in ("MALE", "UNKNOWN"):
            self.breastFeeding = None
            self.breastFeedingStartDate = None
            self.weeksOfAmenorrhea = None
            self.lastMenstrualPeriodDate = None
        else:
            # Grossesse : date des dernières règles -> SA (semaines révolues).
            if self.lastMenstrualPeriodDate is not None:
                if self.dateOfBirth and self.lastMenstrualPeriodDate <= self.dateOfBirth:
                    erreurs.append("lastMenstrualPeriodDate|La date des dernières règles doit être postérieure à la date de naissance.")
                sa_calculees = (aujourdhui - self.lastMenstrualPeriodDate).days // 7
                b = BORNES["semaines_amenorrhee"]
                if not (b["min"] <= sa_calculees <= b["max"]):
                    erreurs.append(
                        f"lastMenstrualPeriodDate|La date des dernières règles correspond à {sa_calculees} SA : "
                        f"la grossesse doit être comprise entre {b['min']} et {b['max']} SA."
                    )
                elif self.weeksOfAmenorrhea is None:
                    self.weeksOfAmenorrhea = sa_calculees
                elif abs(self.weeksOfAmenorrhea - sa_calculees) > 1:
                    erreurs.append(
                        f"weeksOfAmenorrhea|Incohérence : {self.weeksOfAmenorrhea} SA saisies mais la date des dernières règles "
                        f"correspond à {sa_calculees} SA."
                    )
            # Allaitement : une date de début impose la catégorie (< ou > 1 mois).
            if self.breastFeedingStartDate is not None:
                if self.breastFeeding == "NONE":
                    erreurs.append("breastFeedingStartDate|Une date de début d'allaitement est saisie alors que « Pas d'allaitement » est choisi.")
                elif self.dateOfBirth and self.breastFeedingStartDate <= self.dateOfBirth:
                    erreurs.append("breastFeedingStartDate|La date de début d'allaitement doit être postérieure à la date de naissance.")
                else:
                    jours = (aujourdhui - self.breastFeedingStartDate).days
                    self.breastFeeding = "LESS_THAN_ONE_MONTH" if jours < JOURS_SEUIL_ALLAITEMENT_UN_MOIS else "MORE_THAN_ONE_MONTH"

        for champ in ("weightDate", "renalDate"):
            valeur = getattr(self, champ)
            if valeur and self.dateOfBirth and valeur < self.dateOfBirth:
                erreurs.append(f"{champ}|La date de saisie ne peut pas précéder la date de naissance.")

        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class DosageSecurisation(_ModeleVidal):
    """<dosage> : dose + intervalle (min/max) entre deux prises."""
    dose: Optional[float] = None
    unitId: Optional[str] = None
    intervalMin: Optional[float] = None
    intervalMax: Optional[float] = None
    intervalUnitId: Optional[str] = None

    @field_validator("unitId", "intervalUnitId", mode="before")
    @classmethod
    def _v_ids(cls, v):
        return _identifiant(v, "Unité")

    @field_validator("dose")
    @classmethod
    def _v_dose(cls, v):
        return _borne(v, "dose", "La dose")

    @field_validator("intervalMin", "intervalMax")
    @classmethod
    def _v_intervalle(cls, v):
        return _borne(v, "intervalle", "L'intervalle")

    @field_validator("intervalUnitId")
    @classmethod
    def _v_unite_intervalle(cls, v):
        return _dans_liste(v, UNITES_INTERVALLE, "Unité de l'intervalle")

    @model_validator(mode="after")
    def _coherence(self):
        erreurs = []
        if self.intervalMin is not None and self.intervalMax is not None and self.intervalMin > self.intervalMax:
            erreurs.append("intervalMax|L'intervalle maximum doit être supérieur ou égal à l'intervalle minimum.")
        # § aucune unité par défaut : un intervalle saisi exige son unité.
        if (self.intervalMin is not None or self.intervalMax is not None) and not self.intervalUnitId:
            erreurs.append("intervalUnitId|Choisissez l'unité de l'intervalle entre les prises.")
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class LigneSecurisation(_ModeleVidal):
    drugRef: str
    drugType: Optional[str] = "PRODUCT"
    label: Optional[str] = None
    dose: Optional[float] = None
    unitId: Optional[str] = None
    unitLabel: Optional[str] = None
    duration: Optional[int] = None
    durationType: Optional[str] = None
    frequencyType: Optional[str] = None
    route: Optional[str] = None
    indication: Optional[str] = None
    dosages: list[DosageSecurisation] = Field(default_factory=list)
    # § compatibilité : ancien nom de la liste des dosages.
    posologies: list[DosageSecurisation] = Field(default_factory=list)
    startDate: Optional[date] = None
    endDate: Optional[date] = None
    status: Optional[str] = None
    groupId: Optional[int] = None
    groupType: Optional[str] = None
    ald: bool = False
    aldCode: Optional[str] = None

    @field_validator("drugRef", mode="before")
    @classmethod
    def _v_drug(cls, v):
        ident = _identifiant(v, "Médicament")
        if ident is None:
            raise ValueError("Médicament obligatoire : choisissez-le dans la recherche VIDAL.")
        return ident

    @field_validator("unitId", mode="before")
    @classmethod
    def _v_unite(cls, v):
        return _identifiant(v, "Unité de prise")

    @field_validator("route", mode="before")
    @classmethod
    def _v_route(cls, v):
        return _identifiant(v, "Voie d'administration", "vidal://route/")

    @field_validator("indication", mode="before")
    @classmethod
    def _v_indication(cls, v):
        ident = _identifiant(v, "Indication", "vidal://indication/")
        return f"vidal://indication/{ident}" if ident else None

    @field_validator("drugType")
    @classmethod
    def _v_type(cls, v):
        return _dans_liste(v, TYPES_MEDICAMENT, "Type de médicament") or "PRODUCT"

    @field_validator("dose")
    @classmethod
    def _v_dose(cls, v):
        return _borne(v, "dose", "La dose")

    @field_validator("duration")
    @classmethod
    def _v_duree(cls, v):
        return _borne(v, "duree", "La durée")

    @field_validator("durationType")
    @classmethod
    def _v_type_duree(cls, v):
        return _dans_liste(v, TYPES_DUREE, "Unité de durée")

    @field_validator("frequencyType")
    @classmethod
    def _v_frequence(cls, v):
        return _dans_liste(v, TYPES_FREQUENCE, "Fréquence")

    @field_validator("status")
    @classmethod
    def _v_statut(cls, v):
        return _dans_liste(v, STATUTS_LIGNE, "Statut")

    @field_validator("groupType")
    @classmethod
    def _v_groupe(cls, v):
        return _dans_liste(v, TYPES_GROUPE, "Type de groupe")

    @field_validator("groupId")
    @classmethod
    def _v_groupe_id(cls, v):
        if v is not None and v < 0:
            raise ValueError("Le numéro de groupe doit être positif ou nul.")
        return v

    @model_validator(mode="after")
    def _coherence(self):
        erreurs: list[str] = []
        if self.posologies and not self.dosages:
            self.dosages = self.posologies
        self.posologies = []
        if self.duration is not None and not self.durationType:
            erreurs.append("durationType|Choisissez l'unité de la durée (jours, semaines...).")
        if self.dose is not None and not self.unitId:
            erreurs.append("unitId|Choisissez l'unité de la dose (comprimé, ml...).")
        # § MI §6.4.4 : <dose> est la dose CUMULÉE par 24 h, indissociable de
        # <frequencyType> ; pour des prises espacées de plus de 24 h, seules
        # la dose par prise et l'intervalle (<dosages>) sont transmis.
        if self.dose is not None and not self.frequencyType:
            erreurs.append("frequencyType|Choisissez la fréquence de la dose par 24 h (ou laissez la dose vide et utilisez dose par prise + intervalle pour des prises espacées de plus de 24 h).")
        if self.startDate and self.endDate and self.startDate > self.endDate:
            erreurs.append("endDate|La date de fin doit être postérieure ou égale à la date de début.")
        if self.ald:
            if not self.aldCode:
                erreurs.append("aldCode|Le code ALD est obligatoire quand la ligne est prise en charge en ALD.")
            elif len(self.aldCode) > BORNES["code_ald_longueur_max"]:
                erreurs.append(f"aldCode|Le code ALD ne doit pas dépasser {BORNES['code_ald_longueur_max']} caractères.")
        else:
            self.aldCode = None
        for d in self.dosages:
            if d.dose is not None and not d.unitId:
                d.unitId = self.unitId  # § unité du dosage = unité de prise de la ligne par défaut
        if erreurs:
            raise ValueError("\n".join(erreurs))
        return self


class PayloadSecurisationValide(_ModeleVidal):
    patient: PatientSecurisation = Field(default_factory=PatientSecurisation)
    current_treatments: list[LigneSecurisation] = Field(default_factory=list)
    new_prescription_lines: list[LigneSecurisation] = Field(default_factory=list)
    alert_types: Optional[list[str]] = None
    # § MI §6.5.5 : rubriques du rapport HTML filtré (<alert-display-types>).
    alert_display_types: Optional[list[str]] = None
    # § historique clinique : rattachement LOCAL de l'instantané de
    # sécurisation et groupe de référence du DFG choisi — conservés en
    # base, JAMAIS transmis à VIDAL (la construction XML n'utilise que
    # `patient` et les lignes).
    # (SAWALI) `patient_id` = identifiant d'un patient enregistré de
    # `vidal_patients` (bouton « Enregistrer ») ; nom et n° WhatsApp ne
    # servent qu'à l'affichage de l'historique et à l'ordonnance.
    patient_id: Optional[str] = None
    patient_name: Optional[str] = None
    patient_whatsapp: Optional[str] = None
    # Ancien nom (Ster) du nom affiché, accepté pour compatibilité.
    patient_nom: Optional[str] = None
    groupe_reference_dfg: Optional[str] = None

    @field_validator("alert_display_types")
    @classmethod
    def _v_rubriques(cls, v):
        inconnues = [t for t in (v or []) if t not in RUBRIQUES_RAPPORT_HTML]
        if inconnues:
            raise ValueError(f"Rubrique(s) du rapport HTML inconnue(s) : {', '.join(inconnues)}.")
        return v

    @field_validator("alert_types")
    @classmethod
    def _v_types_alerte(cls, v):
        from vidal_v2.xml_securisation import TYPES_ALERTE

        inconnus = [t for t in (v or []) if t not in TYPES_ALERTE]
        if inconnus:
            raise ValueError(f"Type(s) d'alerte inconnu(s) : {', '.join(inconnus)}.")
        return v


# ---------------------------------------------------------------------------
# Traduction des erreurs pydantic -> 422 en français, par champ
# ---------------------------------------------------------------------------

_MESSAGES_TYPE = {
    "missing": "Champ obligatoire.",
    "float_parsing": "Doit être un nombre.",
    "float_type": "Doit être un nombre.",
    "int_parsing": "Doit être un nombre entier.",
    "int_type": "Doit être un nombre entier.",
    "int_from_float": "Doit être un nombre entier (sans décimales).",
    "date_parsing": "Date invalide (format attendu AAAA-MM-JJ).",
    "date_type": "Date invalide (format attendu AAAA-MM-JJ).",
    "date_from_datetime_parsing": "Date invalide (format attendu AAAA-MM-JJ).",
    "date_from_datetime_inexact": "Date invalide : l'heure n'est pas attendue.",
    "bool_parsing": "Doit être vrai ou faux.",
    "bool_type": "Doit être vrai ou faux.",
    "string_type": "Doit être un texte.",
    "list_type": "Doit être une liste.",
    "dict_type": "Doit être un objet.",
    "model_type": "Doit être un objet.",
}


def _chemin(loc: tuple) -> str:
    """("new_prescription_lines", 0, "duration") -> "new_prescription_lines[0].duration"."""
    texte = ""
    for partie in loc:
        if isinstance(partie, int):
            texte += f"[{partie}]"
        else:
            texte += f".{partie}" if texte else str(partie)
    return texte


def traduire_erreurs(exc: ValidationError) -> list[dict]:
    erreurs: list[dict] = []
    for e in exc.errors():
        loc = tuple(e.get("loc", ()))
        if e.get("type") == "value_error":
            message = str(e.get("msg", "")).removeprefix("Value error, ")
            # § contrôles de cohérence : "champ|message", éventuellement sur plusieurs lignes.
            for ligne in message.split("\n"):
                if "|" in ligne:
                    champ, texte = ligne.split("|", 1)
                    erreurs.append({"champ": _chemin(loc + (champ,)), "message": texte})
                else:
                    erreurs.append({"champ": _chemin(loc), "message": ligne})
        else:
            erreurs.append({"champ": _chemin(loc), "message": _MESSAGES_TYPE.get(e.get("type"), e.get("msg", "Valeur invalide."))})
    return erreurs


def valider_payload_securisation(donnees: dict) -> PayloadSecurisationValide:
    """Valide le payload brut ; lève HTTP 422 {message, erreurs[{champ, message}]} au premier problème."""
    try:
        return PayloadSecurisationValide.model_validate(donnees or {})
    except ValidationError as exc:
        erreurs = traduire_erreurs(exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Données de sécurisation invalides : " + " ; ".join(f"{e['champ']} — {e['message']}" for e in erreurs),
                "erreurs": erreurs,
            },
        ) from exc
