"""
backend/vidal_v2/historique_clinique.py
-------------------------------------------
Lot 56 — repris de Ster (app/utils/vidal_historique_clinique.py). Seule
adaptation SAWALI : la 3e colonne de CHAMPS_PROFIL désigne la clé du
sous-document `profil_clinique` d'un patient de `vidal_patients` (au lieu
de l'alias Mongo de la fiche patient de Ster).

§ demande utilisateur (validée) : historique du profil clinique VIDAL du
patient — chaque enregistrement (fiche, page Sécurisation, modale de
l'ordonnance, page Posologie) crée une VERSION datée, jamais écrasée, avec
la liste des champs modifiés par rapport à la version précédente ; aucune
version n'est créée si rien n'a changé.

Ce module, sans dépendance Mongo/FastAPI (portable), décrit les champs
suivis, extrait leurs valeurs d'un document Patient et compare deux
versions. Les écritures en base sont faites par routes/vidal_patients.py.
"""

from datetime import date, datetime
from typing import Any, Optional

# (clé de version, libellé affiché avec unité, clé du sous-document
# `profil_clinique` du patient — voir routes/vidal_patients.py)
CHAMPS_PROFIL: list[tuple[str, str, str]] = [
    ("sexe", "Sexe", "sexe"),
    ("date_naissance", "Date de naissance", "date_naissance"),
    ("poids_kg", "Poids (kg)", "poids_kg"),
    ("taille_cm", "Taille (cm)", "taille_cm"),
    ("date_saisie_poids_taille", "Date de saisie du poids et de la taille", "date_saisie_poids_taille"),
    ("creatininemie_umol_l", "Créatininémie (µmol/L)", "derniere_creatininemie_umol_l"),
    ("clairance_ml_min", "Clairance de la créatinine (ml/min)", "clairance_creatinine_ml_min"),
    ("dfg_ml_min_173", "DFG (ml/min/1,73 m²)", "dfg_ml_min_173"),
    ("date_bilan_renal", "Date du bilan rénal", "date_bilan_renal"),
    ("groupe_reference_dfg", "Groupe de référence du DFG", "groupe_reference_dfg"),
    ("date_dernieres_regles", "Date des dernières règles", "date_dernieres_regles"),
    ("allaitement", "Allaitement", "allaitement"),
    ("date_debut_allaitement", "Date de début d'allaitement", "date_debut_allaitement"),
    ("insuffisance_hepatique", "Insuffisance hépatique", "insuffisance_hepatique"),
    ("allergies", "Allergies (classes)", "allergies"),
    ("molecules", "Allergies molécules / excipients", "molecules_a_eviter"),
    ("pathologies", "Pathologies (CIM-10)", "pathologies"),
]
LIBELLES_CHAMPS = {cle: libelle for cle, libelle, _ in CHAMPS_PROFIL}
LIBELLES_CHAMPS["semaines_amenorrhee"] = "Semaines d'aménorrhée (SA)"

# § valeurs DÉDUITES (recalculées, jamais comparées) : les SA changent
# chaque jour pour une même date des dernières règles.
CHAMPS_CALCULES = ("semaines_amenorrhee", "valeur_normale_dfg_groupe", "libelle_groupe_dfg")


def _normaliser(valeur: Any) -> Any:
    """Forme comparable et sérialisable : dates -> "AAAA-MM-JJ", listes {label, ref} triées, nombres arrondis."""
    if isinstance(valeur, datetime):
        return valeur.date().isoformat()
    if isinstance(valeur, date):
        return valeur.isoformat()
    if isinstance(valeur, float):
        return round(valeur, 2)
    if isinstance(valeur, list):
        elements = [{"label": e.get("label"), "ref": e.get("ref")} for e in valeur if isinstance(e, dict)]
        return sorted(elements, key=lambda e: (e["ref"] or "", e["label"] or ""))
    if valeur == "":
        return None
    return valeur


def valeurs_depuis_patient(patient: dict, reference: Optional[date] = None, groupes_dfg: Optional[list[dict]] = None) -> dict:
    """Instantané des champs suivis d'un profil clinique (dict `profil_clinique`), plus les valeurs déduites (SA, référence du groupe DFG)."""
    valeurs = {cle: _normaliser(patient.get(alias)) for cle, _, alias in CHAMPS_PROFIL}
    for cle in ("allergies", "molecules", "pathologies"):
        valeurs[cle] = valeurs[cle] or []
    jour = reference or date.today()
    ddr = valeurs.get("date_dernieres_regles")
    valeurs["semaines_amenorrhee"] = (jour - date.fromisoformat(ddr)).days // 7 if ddr else None
    groupe = next((g for g in (groupes_dfg or []) if g.get("id") == valeurs.get("groupe_reference_dfg")), None)
    if groupe is None and groupes_dfg:
        groupe = next((g for g in groupes_dfg if g.get("par_defaut")), None)
    valeurs["valeur_normale_dfg_groupe"] = groupe.get("valeur_normale") if groupe else None
    valeurs["libelle_groupe_dfg"] = groupe.get("libelle") if groupe else None
    return valeurs


def champs_modifies(precedentes: Optional[dict], nouvelles: dict) -> list[str]:
    """Clés dont la valeur diffère de la version précédente (toutes les clés renseignées pour une première version)."""
    cles = [cle for cle, _, _ in CHAMPS_PROFIL]
    if not precedentes:
        return [c for c in cles if nouvelles.get(c) not in (None, [], "")]
    return [c for c in cles if _normaliser(precedentes.get(c)) != _normaliser(nouvelles.get(c))]


def resume_gravites(alertes: list[dict]) -> dict:
    """{gravité: nombre d'alertes} — résumé conservé avec l'instantané de sécurisation."""
    resume: dict[str, int] = {}
    for a in alertes or []:
        g = a.get("severity") or "INCONNUE"
        resume[g] = resume.get(g, 0) + 1
    return resume
