# android_loois.py — Lot 475 : API « Loois mobile » (logique pure : requêtes SQL préparées, lecture des résultats, droits, session). Aucun accès réseau.
#
# L'application Android ne parle JAMAIS SQL : elle appelle des fonctions précises (connexion, historique de caisse, détail d'un reçu, reçus à corriger) ; SAWALI fabrique
# lui-même la requête HFSQL (modèles ci-dessous, mêmes noms de tables et de colonnes que Loois : Config.cs, LecteurUtilisateurs.cs, RepositoryRecus.cs) et la fait exécuter par
# UNE machine du client (file de requêtes SQL à distance, lots 439 / 458). La clé « SQL à distance » reste sur SAWALI : elle n'est jamais dans l'APK.
#
# Règles reprises de Loois (CLAUDE.md du dépôt Loois) :
#   - mots de passe comparés tels quels dans la table des utilisateurs (UtilisateurBlg pour Biolog, Utilisateur pour Aizenta) — jamais relus, jamais renvoyés ;
#   - un reçu = ligne de VenteClinique dont la référence commence par « R- » et dont « Mag » n'est pas « SUP » (ou est vide) ;
#   - un caissier ne voit que SES reçus (colonne Machine = son login en MAJUSCULES) ; l'administrateur (SUPERVISEU pour Biolog, AIZ pour Aizenta) et le laboratoire (GroupeLogin = LABO) voient tous les reçus ;
#   - une ligne de reçu « nécessite correction » si la durée de validité PROPRE à sa prestation (Prestations.JoursValidité, via Domaine) est > 0 et DIFFÈRE de celle de la clinique (Clinique.Validité_recu) ;
#   - date d'expiration d'une ligne = date de vente (sans l'heure) + durée effective − 1 seconde.
from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

PREFIXE_RECU = "R-"
MAX_RECUS = 200                       # une réponse de la file porte 200 lignes au plus
MAX_REFERENCES_PAR_REQUETE = 120      # références dans un « IN (…) » : reste très en dessous des 4000 caractères d'une requête
SESSION_DUREE_S = 8 * 3600            # une session d'utilisateur dure 8 heures
ESSAIS_MAX = 5                        # mots de passe faux autorisés…
ESSAIS_FENETRE_S = 900                # … par appareil ET identifiant sur 15 minutes
_RE_LOGIN = re.compile(r"^[\w .@'-]{1,40}$", re.UNICODE)
_RE_REFERENCE = re.compile(r"^R-[A-Za-z0-9_.-]{1,40}$")
_RE_JOUR = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Espaces de travail connus : table des utilisateurs et colonnes (Loois : LecteurUtilisateurs.cs)
ESPACES = {
    "biolog": {"nom": "Biolog", "table": "UtilisateurBlg", "login": "Login", "mdp": "Mot_de_Passe", "autoriser": "AutoriserCorrectionReçu", "groupe": "GroupeLogin",
               "supprimer": "PeutSupprimerRecu", "admin": "SUPERVISEU", "caisse": True},
    "aizenta": {"nom": "Aizenta", "table": "Utilisateur", "login": "Code", "mdp": "Mot de Passe", "autoriser": None, "groupe": None, "supprimer": None, "admin": "AIZ", "caisse": False},
}


def espace_de_la_zone(zone: str) -> Optional[Dict[str, Any]]:
    """Espace de travail d'une zone de lancement : « docx=… » = Biolog, « doc=… » = Aizenta ; « ekol » et le reste : non pris en charge (None). docx est testé AVANT doc."""
    z = (zone or "").strip().lower()
    if z.startswith("docx="):
        return ESPACES["biolog"]
    if z.startswith("doc="):
        return ESPACES["aizenta"]
    return None


# ------------------------------------------------------------------------------------------------------------------------ outils SQL
def echapper(texte: Any) -> str:
    """Texte placé entre apostrophes : les apostrophes sont doublées (jamais de paramètre « ? » avec le fournisseur HFSQL, comme dans Loois)."""
    return str(texte if texte is not None else "").replace("'", "''")


def login_valide(login: str) -> bool:
    return bool(_RE_LOGIN.match(login or ""))


def reference_valide(reference: str) -> bool:
    return bool(_RE_REFERENCE.match(reference or ""))


def jour_valide(jour: str) -> Optional[date]:
    if not _RE_JOUR.match(jour or ""):
        return None
    try:
        return datetime.strptime(jour, "%Y-%m-%d").date()
    except ValueError:
        return None


def vrai(valeur: Any) -> bool:
    """Booléen HFSQL lu comme texte : 1, vrai, true, oui…"""
    return str(valeur or "").strip().lower() in ("1", "-1", "true", "vrai", "oui", "o", "t", "yes", "y")


def nombre(valeur: Any) -> float:
    """Nombre lu comme texte HFSQL : espaces (même insécables) retirés, virgule décimale acceptée ; 0 si illisible."""
    t = re.sub(r"[\s  ]", "", str(valeur or "")).replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return 0.0


def date_vente(valeur: Any) -> Optional[datetime]:
    """Date-heure d'un reçu : « AAAAMMJJHHMMSSCCC », « AAAAMMJJ », « AAAA-MM-JJ HH:MM:SS » ou « JJ/MM/AAAA HH:MM:SS » → datetime (None si illisible)."""
    t = str(valeur or "").strip()
    if not t:
        return None
    chiffres = re.sub(r"\D", "", t)
    if re.fullmatch(r"\d{8}(\d{6})?(\d{0,3})?", chiffres) and not re.search(r"[-/:]", t):
        try:
            return datetime.strptime(chiffres[:14].ljust(14, "0"), "%Y%m%d%H%M%S")
        except ValueError:
            return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(t[:19], fmt)
        except ValueError:
            continue
    return None


# ------------------------------------------------------------------------------------------------------------------------ requêtes préparées
def sql_authentifier(espace: Dict[str, Any], login: str, mot_de_passe: str) -> str:
    """Connexion : la ligne de l'utilisateur SEULEMENT si identifiant ET mot de passe correspondent. Le mot de passe n'est jamais sélectionné."""
    colonnes = f"[{espace['login']}]" + (f", [{espace['autoriser']}]" if espace["autoriser"] else "")
    return f"SELECT {colonnes} FROM [{espace['table']}] WHERE [{espace['login']}] = '{echapper(login)}' AND [{espace['mdp']}] = '{echapper(mot_de_passe)}'"


def sql_utilisateur_connu(espace: Dict[str, Any], login: str) -> str:
    """Connexion rapide : la ligne de l'utilisateur (identifiant seul, SANS mot de passe) pour vérifier qu'il existe toujours chez le client."""
    colonnes = f"[{espace['login']}]" + (f", [{espace['autoriser']}]" if espace["autoriser"] else "")
    return f"SELECT {colonnes} FROM [{espace['table']}] WHERE [{espace['login']}] = '{echapper(login)}'"


def sql_colonne_utilisateur(espace: Dict[str, Any], cle: str, login: str) -> Optional[str]:
    """Lecture tolérante d'une colonne de droits (groupe, droit de suppression) pour un identifiant déjà authentifié (None si l'espace n'a pas cette colonne)."""
    colonne = espace.get(cle)
    return f"SELECT [{colonne}] FROM [{espace['table']}] WHERE [{espace['login']}] = '{echapper(login)}'" if colonne else None


def masquer_sql_connexion(espace: Dict[str, Any], login: str) -> str:
    """Texte gardé dans l'historique de la file à la place de la requête de connexion : sans le mot de passe."""
    return f"SELECT [{espace['login']}] FROM [{espace['table']}] WHERE [{espace['login']}] = '(identifiant)' AND [{espace['mdp']}] = '(mot de passe masqué)'"


COLONNES_RECU = "Référence, [Date Vente], [Code Client], Libellé, MontantRéglé, Machine, PPC, PArtAssuré, PArtAssureur"


def sql_recus_du_jour(jour: date, caissier: Optional[str]) -> str:
    """Reçus d'une journée (non supprimés), du plus récent au plus ancien ; `caissier` = login en MAJUSCULES, ou None pour tous (Loois : RepositoryRecus.ObtenirRecusRecents)."""
    debut, fin = jour.strftime("%Y%m%d"), (jour + timedelta(days=1)).strftime("%Y%m%d")
    filtre_caissier = f"AND Machine = '{echapper(caissier.upper())}' " if caissier else ""
    return (f"SELECT TOP {MAX_RECUS + 1} {COLONNES_RECU} FROM VenteClinique WHERE Référence LIKE '{PREFIXE_RECU}%' AND (Mag <> 'SUP' OR Mag IS NULL) "
            f"{filtre_caissier}AND [Date Vente] >= '{debut}' AND [Date Vente] < '{fin}' ORDER BY [Date Vente] DESC, Référence DESC")


_FILTRE_RECUS = "Référence LIKE '" + PREFIXE_RECU + "%' AND (Mag <> 'SUP' OR Mag IS NULL)"


def sql_agregat_par_caissier(jour: date) -> str:
    """Tableau de bord : nombre de reçus et montant réglé PAR CAISSIER pour un jour (totaux calculés par la base, jamais 200 lignes à additionner)."""
    debut, fin = jour.strftime("%Y%m%d"), (jour + timedelta(days=1)).strftime("%Y%m%d")
    return f"SELECT Machine, COUNT(*), SUM(MontantRéglé) FROM VenteClinique WHERE {_FILTRE_RECUS} AND [Date Vente] >= '{debut}' AND [Date Vente] < '{fin}' GROUP BY Machine"


def sql_agregat_jour(jour: date) -> str:
    """Nombre de reçus et montant réglé d'un jour (courbe des 7 derniers jours)."""
    debut, fin = jour.strftime("%Y%m%d"), (jour + timedelta(days=1)).strftime("%Y%m%d")
    return f"SELECT COUNT(*), SUM(MontantRéglé) FROM VenteClinique WHERE {_FILTRE_RECUS} AND [Date Vente] >= '{debut}' AND [Date Vente] < '{fin}'"


def sql_entete_recu(reference: str) -> str:
    return f"SELECT {COLONNES_RECU} FROM VenteClinique WHERE Référence = '{echapper(reference)}'"


def sql_lignes_recu(reference: str) -> str:
    return f"SELECT [Code Produit], Realisé_par, Domaine, [Qte Livrée], [Prix Cession] FROM A_Acheté WHERE Référence = '{echapper(reference)}'"


def sql_designations(codes: List[str]) -> Optional[str]:
    liste = ",".join(f"'{echapper(c)}'" for c in codes[:100])
    return f"SELECT [Code Produit], Libellé FROM ProduitClinique WHERE [Code Produit] IN ({liste})" if codes else None


def sql_medecins(ids: List[str]) -> Optional[str]:
    liste = ",".join(f"'{echapper(i)}'" for i in ids[:100])
    return f"SELECT IDMédecin, Nom, Prénoms FROM MédecinT WHERE IDMédecin IN ({liste})" if ids else None


def sql_validite_clinique() -> str:
    return "SELECT Validité_recu FROM Clinique"


def sql_prestations() -> str:
    return "SELECT Prestation, JoursValidité FROM Prestations WHERE JoursValidité > 0"


def sql_domaines(references: List[str]) -> Optional[str]:
    liste = ",".join(f"'{echapper(r)}'" for r in references[:MAX_REFERENCES_PAR_REQUETE])
    return f"SELECT Référence, Domaine FROM A_Acheté WHERE Référence IN ({liste})" if references else None


# ------------------------------------------------------------------------------------------------------------------------ lecture des résultats
def _cellule(ligne: List[Any], i: int) -> str:
    return str(ligne[i]).strip() if i < len(ligne) and ligne[i] is not None else ""


def lire_recus(lignes: List[List[Any]]) -> List[Dict[str, Any]]:
    """Lignes de la requête COLONNES_RECU → reçus pour l'écran (lecture PAR POSITION, jamais par nom de colonne)."""
    sortie = []
    for l in lignes:
        d = date_vente(_cellule(l, 1))
        sortie.append({"reference": _cellule(l, 0), "date_vente": d.strftime("%Y-%m-%d") if d else "", "heure": d.strftime("%H:%M") if d else "",
                       "date_heure_iso": d.strftime("%Y-%m-%dT%H:%M:%S") if d else "", "code_client": _cellule(l, 2), "patient": _cellule(l, 3),
                       "montant": nombre(_cellule(l, 4)), "caissier": _cellule(l, 5), "ppc": nombre(_cellule(l, 6)),
                       "part_assure": nombre(_cellule(l, 7)), "part_assureur": nombre(_cellule(l, 8))})
    return sortie


def lire_prestations(lignes: List[List[Any]]) -> Dict[str, int]:
    """Prestation → jours de validité PROPRES (entiers > 0 seulement)."""
    sortie: Dict[str, int] = {}
    for l in lignes:
        jours = int(nombre(_cellule(l, 1)))
        if _cellule(l, 0) and jours > 0:
            sortie[_cellule(l, 0)] = jours
    return sortie


def lire_validite_clinique(lignes: List[List[Any]]) -> Optional[int]:
    """Durée de validité d'un reçu pour toute la clinique (première ligne de Clinique) ; None si absente."""
    if not lignes:
        return None
    jours = int(nombre(_cellule(lignes[0], 0)))
    return jours if jours > 0 else None


def necessite_correction(jours_specifiques: Optional[int], validite_clinique: Optional[int]) -> bool:
    """Règle de Loois (RepositoryRecus.EstNecessiteCorrection) : durée propre > 0 ET (clinique inconnue OU différente)."""
    if not jours_specifiques or jours_specifiques <= 0:
        return False
    return validite_clinique is None or jours_specifiques != validite_clinique


def date_expiration(date_emission: Optional[datetime], jours: int) -> str:
    """Dernier instant valide : émission (sans l'heure) + durée − 1 seconde, « AAAA-MM-JJ HH:MM:SS » ; vide si la date de vente est inconnue."""
    if date_emission is None:
        return ""
    fin = datetime.combine(date_emission.date(), datetime.min.time()) + timedelta(days=jours) - timedelta(seconds=1)
    return fin.strftime("%Y-%m-%d %H:%M:%S")


def lire_lignes_recu(lignes: List[List[Any]], designations: Dict[str, str], medecins: Dict[str, str], prestations: Dict[str, int], validite_clinique: Optional[int],
                     date_emission: Optional[datetime]) -> List[Dict[str, Any]]:
    """Lignes d'un reçu (A_Acheté) enrichies : désignation, médecin, durée propre, besoin de correction, date d'expiration effective."""
    sortie = []
    for l in lignes:
        code, realise, domaine = _cellule(l, 0), _cellule(l, 1), _cellule(l, 2)
        qte, prix = nombre(_cellule(l, 3)), nombre(_cellule(l, 4))
        propres = prestations.get(domaine)
        effective = propres if propres else (validite_clinique or 0)
        sortie.append({"code_produit": code, "designation": designations.get(code, ""), "domaine": domaine, "medecin": medecins.get(realise, realise), "quantite": qte,
                       "prix_unitaire": prix, "montant": round(qte * prix, 2), "jours_validite_propre": propres, "jours_validite_effective": effective,
                       "necessite_correction": necessite_correction(propres, validite_clinique),
                       "date_expiration": date_expiration(date_emission, effective) if effective else ""})
    return sortie


def recus_a_corriger(recus: List[Dict[str, Any]], domaines: List[List[Any]], prestations: Dict[str, int], validite_clinique: Optional[int]) -> List[Dict[str, Any]]:
    """Ajoute à chaque reçu `a_corriger` et `lignes_a_corriger` (nombre de lignes dont la prestation a une durée propre différente de celle de la clinique)."""
    par_reference: Dict[str, int] = defaultdict(int)
    for l in domaines:
        if necessite_correction(prestations.get(_cellule(l, 1)), validite_clinique):
            par_reference[_cellule(l, 0)] += 1
    return [{**r, "lignes_a_corriger": par_reference.get(r["reference"], 0), "a_corriger": par_reference.get(r["reference"], 0) > 0} for r in recus]


def lire_par_caissier(lignes: List[List[Any]]) -> List[Dict[str, Any]]:
    """Lignes (Machine, COUNT, SUM) → [{caissier, nombre, montant}], les plus gros montants d'abord ; un caissier vide devient « (sans caissier) »."""
    sortie = [{"caissier": _cellule(l, 0) or "(sans caissier)", "nombre": int(nombre(_cellule(l, 1))), "montant": round(nombre(_cellule(l, 2)), 2)} for l in lignes]
    return sorted(sortie, key=lambda x: (-x["montant"], x["caissier"].lower()))


def lire_agregat_jour(lignes: List[List[Any]]) -> Tuple[int, float]:
    """Ligne (COUNT, SUM) → (nombre, montant) ; (0, 0) si la base ne rend rien."""
    if not lignes:
        return 0, 0.0
    return int(nombre(_cellule(lignes[0], 0))), round(nombre(_cellule(lignes[0], 1)), 2)


# ------------------------------------------------------------------------------------------------------------------------ droits
def droits(espace: Dict[str, Any], login: str, groupe: str, autoriser_correction: bool, peut_supprimer: bool, profil: str = "agent") -> Dict[str, Any]:
    """Droits de l'utilisateur (règles de Loois) : administrateur = login attendu pour l'espace ; laboratoire = groupe LABO (consultation seule, tous les reçus)."""
    admin = (login or "").strip().upper() == espace["admin"]
    labo = (groupe or "").strip().upper() == "LABO"
    return {"administrateur": admin, "laboratoire": labo, "voir_tous_les_recus": admin or labo, "caisse": bool(espace.get("caisse")),
            "corrections": bool(espace.get("caisse")) and (admin or labo or autoriser_correction), "consultation_seule": labo, "supprimer_recu": peut_supprimer and not labo,
            # Lot 483 : tableau de bord de suivi = l'administrateur, ou le téléphone d'un responsable d'établissement (profil « client » choisi par l'administrateur de SAWALI) ; jamais le laboratoire
            "tableau_de_bord": bool(espace.get("caisse")) and not labo and (admin or profil == "client")}


# ------------------------------------------------------------------------------------------------------------------------ essais de connexion
_essais: Dict[str, Deque[float]] = defaultdict(deque)


def essais_restants(cle: str, maintenant: Optional[float] = None) -> int:
    """Mots de passe faux encore permis pour cette clé (appareil + identifiant) sur la fenêtre glissante."""
    t = maintenant if maintenant is not None else time.monotonic()
    f = _essais[cle]
    while f and t - f[0] > ESSAIS_FENETRE_S:
        f.popleft()
    return max(0, ESSAIS_MAX - len(f))


def noter_echec(cle: str, maintenant: Optional[float] = None) -> None:
    _essais[cle].append(maintenant if maintenant is not None else time.monotonic())


def effacer_echecs(cle: str) -> None:
    _essais.pop(cle, None)


def cle_essais(appareil_id: str, login: str) -> str:
    return f"{appareil_id}|{(login or '').strip().upper()}"
