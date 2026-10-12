# puce_contrat.py — Lot 120 : puce CARRÉE « contrat » devant chaque contact du Centre de messagerie.
#
# Demande du propriétaire (12/10/2026) : « Dans le centre de messagerie (liste des contacts), afficher avec une puce
# CARRÉE les infos de contrat : vert (contrat valide), rouge (pas de contrat ou annulé) et orange (contrat en retard de
# paiement). Un survol sur cette puce affiche le détail : n° de contrat, statut, nombre de mois, etc. mais PAS de
# montants. »
#
# En résumé (pour un développeur WinDev) :
#   - Les CONTRATS sont ceux de SAWALI avec ses clients : ils vivent sur la fiche du client (db.users, compte principal),
#     champs contract_number, contract_signed_at, contract_start_at, contract_end_at (lots 81/82), last_payment_at,
#     contract_overdue_days, contract_billing_period, account_status, cycle_vie.statut (lot 51)…
#   - Un CONTACT du Centre de messagerie (db.directory_contacts) n'a pas de lien direct vers un contrat. On le relie à la
#     fiche d'un client, par ordre de priorité :
#        1. son e-mail = e-mail d'un compte (compte principal OU utilisateur rattaché au client) ;
#        2. son numéro WhatsApp / téléphone = numéro d'un compte (8 derniers chiffres, même règle que les non-lus) ;
#        3. sa société = société (ou code client ACME) d'un compte principal.
#     (Son `client_id` n'est pas un critère : il désigne le locataire qui POSSÈDE le contact, ici SAWALI.)
#     Un compte rattaché (utilisateur suivi, parent_client_id / client_id) renvoie au contrat de son compte principal.
#     Si plusieurs fiches correspondent au même critère, celle qui porte un n° de contrat est préférée.
#   - Couleur (logique pure `fiche_contrat`, testée) :
#        ROUGE  « aucun »  : aucun client relié, pas de n° de contrat, contrat annulé/résilié (champ facultatif
#                            contract_status), compte archivé/désactivé, contrat échu (au-delà de J+5 après la fin, lot 82) ;
#        ORANGE « retard » : compte suspendu (retard), OU retard de paiement selon la MÊME règle que les alertes
#                            quotidiennes (lot 79.7 / retards_paiement, liste Admin → Clients) : jours depuis le dernier
#                            règlement (à défaut la signature) ≥ seuil du client (contract_overdue_days, sinon le seuil
#                            global contract_overdue_days_default, sinon 5), OU fin de contrat dépassée de 1 à 5 jours
#                            (renouvellement en retard, lot 82) ;
#        VERT   « valide » : contrat en cours et à jour (y compris « échéance proche » et « pas encore commencé »).
#   - AUCUN MONTANT : la fiche client est relue avec une liste FERMÉE de champs (CHAMPS_CLIENT) qui n'en contient
#     aucun (ni contract_amount, ni devise, ni lignes, ni paiements) ; la réponse ne peut donc pas en contenir.
#   - Qui voit les puces : les contrats sont ceux de SAWALI → seulement le super-administrateur et les comptes du
#     locataire de la plateforme (SAWALI et son équipe). Un client (pharmacie…) ne voit aucune puce : ses contacts sont
#     ses propres clients/patients et il ne doit pas voir les contrats des autres clients de SAWALI.
#   - Pas de puce pour un contact INTERNE (relié au locataire de la plateforme lui-même, au super-admin ou à un e-mail
#     des domaines internes) : un membre de l'équipe n'a pas de contrat avec SAWALI.
#   - Droits : seuls les contacts que l'utilisateur voit déjà dans le Centre de messagerie (même périmètre que
#     GET /me/contacts : sociétés visibles + lignes WhatsApp autorisées) reçoivent une puce.
#   - Lot 124 (12/10/2026, demande du propriétaire) : « les contacts sur lesquels il faut analyser, c'est ceux ayant le
#     champ "Société" renseigné ». Un contact SANS société n'est pas analysé : pas de puce, pas de bandeau (null).
#     Pour un contact avec société, la société passe EN PREMIER (comparaison sans accents, majuscules ni espaces en
#     trop), puis l'e-mail et le téléphone servent de secours si la société ne correspond à aucun client.
#   - Lot 126 : un contact AVEC société n'est jamais écarté parce que son e-mail / téléphone correspond à un compte de
#     l'équipe : seule une société qui désigne SAWALI elle-même masque la puce ; sinon, sans contrat → puce ROUGE.
#   - Lot 127 : « interne » = UNIQUEMENT le locataire SAWALI (super-admin, son locataire, son compte parent).
#     Avant, c'étaient TOUS les comptes visibles par l'utilisateur — pour le super-admin, tous les clients : la puce
#     d'un contact relié à un vrai client (ex. Pharmacie AMITIÉ MIYOUGOU) était donc masquée à tort.
#   - Efficacité : UNE requête groupée sur les comptes (index mémorisé 60 s), puis tout se calcule en mémoire.
from __future__ import annotations

import logging

import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel

from routes.contrats_plateformes import APRES_DEFAUT, AVANT_DEFAUT, etat_contrat

# ---------------------------------------------------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------------------------------------------------
# Lot 120 — champs lus sur les fiches des comptes : liste FERMÉE, sans AUCUN montant (garantie « pas de montant »).
CHAMPS_CLIENT = {
    "_id": 0, "id": 1, "email": 1, "phone": 1, "whatsapp_number": 1, "company": 1, "client_code": 1,
    "full_name": 1, "role": 1, "parent_client_id": 1, "client_id": 1, "account_status": 1,
    "contract_number": 1, "contract_status": 1, "contract_signed_at": 1, "contract_start_at": 1,
    "contract_end_at": 1, "last_payment_at": 1, "contract_overdue_days": 1, "contract_billing_period": 1,
    "contract_alerte_avant_jours": 1, "contract_alerte_apres_jours": 1, "contract_services_suspendus": 1,
    "cycle_vie.statut": 1,
}
SEUIL_RETARD_DEFAUT = 5                                 # même défaut que les alertes de retard (lot 79.7)
PERIODES_JOURS = {"monthly": 30, "quarterly": 90, "annual": 365}   # même table que abonnement_acces (lot 50)
LIBELLES_PERIODES = {"monthly": "Mensuel", "quarterly": "Trimestriel", "annual": "Annuel"}
STATUTS_ANNULES = {"annule": "Contrat annulé", "cancelled": "Contrat annulé", "canceled": "Contrat annulé",
                   "resilie": "Contrat résilié", "terminated": "Contrat résilié"}
COMPTES_FERMES = {"archive": "Compte archivé", "disabled": "Compte désactivé", "deleted": "Compte supprimé",
                  "inactive": "Compte inactif", "expired": "Compte expiré"}
COULEURS = {"valide": "vert", "retard": "orange", "aucun": "rouge"}
DUREE_CACHE_S = 60.0


# Lot 128 — journal de diagnostic (comptages seulement, aucune donnée personnelle)
logger = logging.getLogger("sawali.puce_contrat")


def _jour(valeur: Any) -> Optional[date]:
    """« 2026-10-15 » (ou ISO complet) → date ; None si vide ou illisible."""
    try:
        return date.fromisoformat(str(valeur or "")[:10])
    except ValueError:
        return None


def _chiffres(valeur: Any) -> str:
    """Les 8 derniers chiffres d'un numéro (même clé que le Centre de messagerie, lot 23)."""
    d = re.sub(r"\D", "", str(valeur or ""))
    return d[-8:]


def _sans_accent(texte: str) -> str:
    """« Résilié » → « resilie » (comparaison des statuts saisis à la main)."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn")


def mois_entre(debut: date, fin: date) -> int:
    """Nombre de mois ENTIERS entre deux dates (15/10 → 14/11 = 0 ; 15/10 → 15/11 = 1) ; jamais négatif."""
    n = (fin.year - debut.year) * 12 + (fin.month - debut.month) - (1 if fin.day < debut.day else 0)
    return max(0, n)


# =====================================================================================================================
# Logique pure (testée : tests/test_puce_contrat_lot120.py)
# =====================================================================================================================

def fiche_contrat(client: Optional[Dict[str, Any]], aujourdhui: date,
                  seuil_defaut: int = SEUIL_RETARD_DEFAUT) -> Dict[str, Any]:
    """Lot 120 — informations de la puce pour la fiche d'un client (ou None = aucun client relié).

    Renvoie {etat, couleur, numero, statut, statut_libelle, client, debut, fin, duree_mois, mois_ecoules,
    mois_restants, jours_retard, seuil_retard, echeance_prochaine, periodicite, services_suspendus}
    — JAMAIS de montant."""
    vide = {"etat": "aucun", "couleur": COULEURS["aucun"], "numero": None, "statut": "sans_contrat",
            "statut_libelle": "Aucun contrat", "client": None, "debut": None, "fin": None, "duree_mois": None,
            "mois_ecoules": None, "mois_restants": None, "jours_retard": None, "seuil_retard": None,
            "echeance_prochaine": None, "periodicite": None, "services_suspendus": []}
    if not client:
        return vide
    c = client
    base = dict(vide, client=(c.get("company") or c.get("full_name") or None))
    numero = str(c.get("contract_number") or "").strip()
    if not numero:
        return base                                                     # ROUGE : pas de n° de contrat

    # --- Dates du contrat (début, fin, durée, mois écoulés / restants) ---------------------------------------------
    d_debut = _jour(c.get("contract_start_at")) or _jour(c.get("contract_signed_at"))
    d_fin = _jour(c.get("contract_end_at"))
    duree = mois_entre(d_debut, d_fin) if d_debut and d_fin else None
    ecoules = None
    if d_debut:
        ecoules = 0 if aujourdhui < d_debut else mois_entre(d_debut, aujourdhui)
        if duree is not None:
            ecoules = min(ecoules, duree)
    restants = max(0, duree - ecoules) if duree is not None and ecoules is not None else None

    # --- Prochaine échéance : règlement périodique (lot 50 : dernier règlement + période), sinon fin du contrat ----
    periode = str(c.get("contract_billing_period") or "").strip().lower()
    ref = _jour(c.get("last_payment_at")) or _jour(c.get("contract_signed_at"))
    echeance = None
    # Lot 127.3 — périodicité inconnue : mensuelle par défaut (cas le plus fréquent) pour calculer l'échéance
    jours_periode = PERIODES_JOURS.get(periode, PERIODES_JOURS["monthly"])
    d_echeance = (ref + timedelta(days=jours_periode)) if ref else None
    # Affichage (inchangé) : échéance du règlement si la périodicité est connue, sinon fin du contrat
    if periode in PERIODES_JOURS and d_echeance:
        echeance = d_echeance.isoformat()
    elif d_fin:
        echeance = d_fin.isoformat()

    services = [str(s) for s in (c.get("contract_services_suspendus") or []) if str(s).strip()]
    base.update(numero=numero, debut=d_debut.isoformat() if d_debut else None,
                fin=d_fin.isoformat() if d_fin else None, duree_mois=duree, mois_ecoules=ecoules,
                mois_restants=restants, echeance_prochaine=echeance,
                periodicite=LIBELLES_PERIODES.get(periode), services_suspendus=services)

    def _resultat(etat: str, statut: str, libelle: str, jours: Optional[int] = None,
                  seuil: Optional[int] = None) -> Dict[str, Any]:
        return dict(base, etat=etat, couleur=COULEURS[etat], statut=statut, statut_libelle=libelle,
                    jours_retard=jours, seuil_retard=seuil)

    # --- ROUGE : contrat annulé / résilié (champ facultatif contract_status), compte fermé ou archivé -------------
    statut_saisi = _sans_accent(str(c.get("contract_status") or "").strip().lower())
    if statut_saisi in STATUTS_ANNULES:
        return _resultat("aucun", "annule", STATUTS_ANNULES[statut_saisi])
    compte = str(c.get("account_status") or "active").strip().lower()
    cycle = str(((c.get("cycle_vie") or {}).get("statut")) or "").upper()
    if compte in COMPTES_FERMES:
        return _resultat("aucun", "compte_ferme", COMPTES_FERMES[compte])
    if cycle == "ARCHIVE":
        return _resultat("aucun", "compte_ferme", "Compte archivé (non renouvelé)")

    # --- État de la fin de contrat (lots 81/82 : orange J−5→J, rouge J+1→J+5, échu au-delà) ----------------------
    avant = int(c.get("contract_alerte_avant_jours") or AVANT_DEFAUT)
    apres = int(c.get("contract_alerte_apres_jours") or APRES_DEFAUT)
    fin_etat = etat_contrat(d_debut.isoformat() if d_debut else None, c.get("contract_end_at"), aujourdhui,
                            avant, apres)
    if fin_etat["niveau"] == "echu":
        return _resultat("aucun", "expire", "Contrat expiré")

    # --- ORANGE : compte suspendu (retard, lot 27 / lot 51) ------------------------------------------------------------
    # Lot 127.3 (12/10/2026, « Pharmacie AMITIÉ MIYOUGOU a un contrat et est à jour ») — le retard se compte À PARTIR
    # DE L'ÉCHÉANCE (dernier règlement + périodicité), et non plus depuis le dernier règlement : un client mensuel qui a
    # payé le 1er n'est plus « en retard » le 6. Le seuil (contract_overdue_days, défaut 5 j) devient un délai de grâce
    # après l'échéance.
    jours, seuil = None, None
    if d_echeance:
        jours = max(0, (aujourdhui - d_echeance).days)
        seuil = max(1, int(c.get("contract_overdue_days") or seuil_defaut or SEUIL_RETARD_DEFAUT))
    if compte == "suspended" or cycle == "SUSPENDU_NON_RENOUVELE":
        return _resultat("retard", "suspendu", "Compte suspendu (retard de paiement)", jours, seuil)
    # --- ORANGE : retard de paiement, MÊME règle que les alertes quotidiennes (lot 79.7) et Admin → Clients -------
    if jours is not None and jours >= seuil:
        return _resultat("retard", "retard_paiement", "Retard de paiement", jours, seuil)
    # --- ORANGE : fin de contrat dépassée de 1 à 5 jours (renouvellement en retard, lot 82) ------------------------
    if fin_etat["niveau"] == "expire":
        return _resultat("retard", "renouvellement", "Renouvellement en retard", -int(fin_etat["jours_restants"]))

    # --- VERT : contrat en cours et à jour -----------------------------------------------------------------------------
    if fin_etat["niveau"] == "a_venir":
        return _resultat("valide", "a_venir", "Contrat signé, pas encore commencé", None, seuil)
    if fin_etat["niveau"] == "bientot":
        return _resultat("valide", "bientot", "À jour — fin de contrat proche", None, seuil)
    return _resultat("valide", "a_jour", "À jour", None, seuil)


def cle_societe(nom: Any) -> str:
    """Lot 124 — société comparable : sans accents, en minuscules, espaces multiples réduits (« Pharmacie  Évasion » =
    « pharmacie evasion »)."""
    return " ".join(_sans_accent(str(nom or "")).lower().split())


def a_une_societe(contact: Dict[str, Any]) -> bool:
    """Lot 124 — seuls les contacts dont le champ « Société » est renseigné sont analysés."""
    return bool(cle_societe(contact.get("company")))


class IndexComptes:
    """Lot 120 — index en mémoire des comptes (UNE lecture de db.users) pour relier les contacts aux contrats."""

    def __init__(self, comptes: List[Dict[str, Any]]):
        self.par_id: Dict[str, Dict[str, Any]] = {}
        self.par_email: Dict[str, List[Dict[str, Any]]] = {}
        self.par_tel: Dict[str, List[Dict[str, Any]]] = {}
        self.par_societe: Dict[str, List[Dict[str, Any]]] = {}
        for u in comptes:
            if u.get("id"):
                self.par_id[u["id"]] = u
        for u in comptes:
            email = str(u.get("email") or "").strip().lower()
            if email:
                self.par_email.setdefault(email, []).append(u)
            for tel in (u.get("whatsapp_number"), u.get("phone")):
                fin = _chiffres(tel)
                if len(fin) >= 8:
                    lst = self.par_tel.setdefault(fin, [])
                    if u not in lst:
                        lst.append(u)
            # Société / code client : uniquement les comptes PRINCIPAUX (pas de parent)
            if self.principal(u) is u:
                for nom in (u.get("company"), u.get("client_code")):
                    cle = cle_societe(nom)
                    if cle:
                        self.par_societe.setdefault(cle, []).append(u)

    def principal(self, u: Dict[str, Any]) -> Dict[str, Any]:
        """Compte principal (porteur du contrat) d'un compte : son parent, sinon son client, sinon lui-même."""
        for cle in ("parent_client_id", "client_id"):
            pid = u.get(cle)
            if pid and pid != u.get("id") and pid in self.par_id:
                return self.par_id[pid]
        return u

    @staticmethod
    def _choisir(candidats: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Parmi plusieurs fiches pour un même critère : celle qui a un n° de contrat, sinon la première."""
        if not candidats:
            return None
        for c in candidats:
            if str(c.get("contract_number") or "").strip():
                return c
        return candidats[0]

    def client_du_contact(self, contact: Dict[str, Any]) -> Tuple[Optional[Dict], str]:
        """→ (fiche du compte principal ou None, critère utilisé : email | telephone | societe | aucun)."""
        # Lot 124 — 1. la SOCIÉTÉ d'abord (c'est elle qui désigne le client), comparée sans accents ni casse
        soc = cle_societe(contact.get("company"))
        if soc and soc in self.par_societe:
            p = self._choisir(self.par_societe[soc])
            if p:
                return p, "societe"
        # 1. e-mail (le client_id du contact n'est pas un critère : dans le Centre de messagerie il désigne
        #    toujours le locataire de l'utilisateur lui-même, jamais le client concerné)
        email = str(contact.get("email") or "").strip().lower()
        if email and email in self.par_email:
            p = self._choisir([self.principal(u) for u in self.par_email[email]])
            if p:
                return p, "email"
        # 2. numéro WhatsApp / téléphone (8 derniers chiffres)
        for tel in (contact.get("whatsapp"), contact.get("phone")):
            fin = _chiffres(tel)
            if len(fin) >= 8 and fin in self.par_tel:
                p = self._choisir([self.principal(u) for u in self.par_tel[fin]])
                if p:
                    return p, "telephone"
        return None, "aucun"


def _email_super_admin() -> str:
    return (os.environ.get("SUPER_ADMIN_EMAIL") or "admin@sawalismartsystems.com").strip().lower()


def est_interne(compte: Optional[Dict[str, Any]], locataires_internes: set, domaines: List[str]) -> bool:
    """Compte de la plateforme (super-admin, locataire SAWALI, e-mail d'un domaine interne) : pas de puce."""
    if not compte:
        return False
    email = str(compte.get("email") or "").strip().lower()
    if email == _email_super_admin():
        return True
    # Lot 127.2 — SEUL le locataire SAWALI lui-même est interne. Avant, une fiche client dont l'e-mail avait un domaine
    # « interne » (réglage internal_domains) était prise pour un membre de l'équipe : ses contacts n'avaient AUCUNE
    # puce (diagnostic du 12/10 : 364 contacts sur 377 sans puce). Le domaine de l'e-mail ne sert plus qu'aux droits
    # d'accès (qui voit les puces), plus au classement des clients. `domaines` est gardé pour compatibilité.
    return compte.get("id") in locataires_internes


# =====================================================================================================================
# Route
# =====================================================================================================================

class DemandeContrats(BaseModel):
    """Corps de POST /me/contacts-contrats : identifiants des contacts affichés (vide = tous les contacts visibles)."""
    contact_ids: Optional[List[str]] = None


def setup_puce_contrat_routes(*, db, api, get_current_user,
                              resolve_visible_client_ids: Callable[[dict], Awaitable[List[str]]]) -> Dict[str, Any]:
    """Branche la route du lot 120 (appelée depuis server_parts/p20). `resolve_visible_client_ids` = le périmètre du
    Centre de messagerie (server._resolve_visible_client_ids), injecté pour que les tests puissent le simuler."""
    from fastapi import Depends

    cache: Dict[str, Any] = {"lu_a": 0.0, "index": None}

    async def _index() -> IndexComptes:
        """UNE lecture groupée des comptes (champs sans montant), mémorisée 60 s."""
        if cache["index"] is not None and time.monotonic() - cache["lu_a"] < DUREE_CACHE_S:
            return cache["index"]
        comptes = await db.users.find({}, CHAMPS_CLIENT).to_list(50000)
        cache.update(index=IndexComptes(comptes), lu_a=time.monotonic())
        return cache["index"]

    def vider_cache() -> None:
        cache.update(index=None, lu_a=0.0)

    async def _domaines_internes(s: Dict[str, Any]) -> List[str]:
        return [d.strip().lower().lstrip("@") for d in
                str(s.get("internal_domains") or "sawalismartsystems.com").split(",") if d.strip()]

    async def _contexte(user: dict) -> Optional[Dict[str, Any]]:
        """Qui voit les puces : super-admin, comptes du locataire SAWALI, e-mails des domaines internes.
        Renvoie None pour tout autre utilisateur, sinon {settings, domaines, visibles_ids, internes, seuil_defaut}.
        (Lot 121 : bloc extrait de la route du lot 120, sans changement, pour être partagé avec le Support Loois.)"""
        s = await db.settings.find_one({"_id": "global"}) or {}
        domaines = await _domaines_internes(s)
        visibles_ids = await resolve_visible_client_ids(user)
        email_user = str(user.get("email") or "").strip().lower()
        autorise = email_user == _email_super_admin() or (email_user and email_user.rsplit("@", 1)[-1] in domaines)
        # Comptes du locataire SAWALI lui-même : le super-admin, son locataire et son compte parent
        sa = await db.users.find_one({"email": _email_super_admin()},
                                     {"_id": 0, "id": 1, "client_id": 1, "parent_client_id": 1}) or {}
        ids_sa = {v for v in (sa.get("id"), sa.get("client_id"), sa.get("parent_client_id")) if v}
        if not autorise:
            # Compte du locataire SAWALI : son périmètre contient le compte du super-admin (ou son locataire)
            autorise = bool(ids_sa & set(visibles_ids))
        if not autorise:
            # Lot 128 — diagnostic : pourquoi les puces ne s'affichent pas pour ce compte
            logger.info("[puce_contrat] puces refusées : rôle=%s domaine_interne=%s super_admin_trouvé=%s périmètre=%s",
                        user.get("role"), bool(email_user) and email_user.rsplit("@", 1)[-1] in domaines,
                        bool(ids_sa), len(visibles_ids or []))
            return None
        try:
            seuil_defaut = int(s.get("contract_overdue_days_default") or SEUIL_RETARD_DEFAUT)
        except (TypeError, ValueError):
            seuil_defaut = SEUIL_RETARD_DEFAUT
        return {"settings": s, "domaines": domaines, "visibles_ids": visibles_ids,
                "internes": ids_sa, "seuil_defaut": seuil_defaut}

    @api.post("/me/contacts-contrats", tags=["Portail Client"])
    async def contrats_des_contacts(payload: DemandeContrats, user: dict = Depends(get_current_user)):
        """Lot 120 — puce « contrat » des contacts du Centre de messagerie, en UNE requête pour toute la liste.

        Réponse : {actif, contrats: {contact_id: {etat, couleur, numero, statut_libelle, …} | null}} — null = contact
        interne (pas de puce). Aucun montant. `actif` = False pour un utilisateur qui n'est pas de l'équipe SAWALI."""
        ctx = await _contexte(user)
        if ctx is None:
            return {"actif": False, "contrats": {}}
        s, domaines, visibles_ids = ctx["settings"], ctx["domaines"], ctx["visibles_ids"]

        # --- Contacts : SEULEMENT ceux que l'utilisateur voit déjà (même périmètre que GET /me/contacts) -----------
        filtre: Dict[str, Any] = {"client_id": {"$in": visibles_ids}}
        if payload.contact_ids:
            filtre["id"] = {"$in": [str(i) for i in payload.contact_ids[:5000]]}
        contacts = await db.directory_contacts.find(
            filtre, {"_id": 0, "id": 1, "client_id": 1, "email": 1, "phone": 1, "whatsapp": 1, "company": 1,
                     "wa_ligne": 1}).to_list(5000)
        try:
            from routes.numeros_wa import VisibiliteLignes    # Lot 59 : lignes WhatsApp autorisées
            vis = await VisibiliteLignes.charger(db, user, settings_doc=s)
            if vis.restreint:
                contacts = [c for c in contacts if vis.contact_visible(c)]
        except Exception:  # noqa: BLE001 — en cas d'erreur, le périmètre des sociétés suffit
            pass

        # --- Calcul : une seule lecture des comptes, puis tout en mémoire -------------------------------------------
        index = await _index()
        internes = ctx["internes"]
        aujourdhui = datetime.now(timezone.utc).date()
        seuil_defaut = ctx["seuil_defaut"]
        resultat: Dict[str, Optional[Dict[str, Any]]] = {}
        raisons: Dict[str, int] = {}          # lot 127.2 : pourquoi un contact n'a pas de puce (comptages)
        for c in contacts:
            # Lot 124 — contact sans « Société » : non analysé (ni puce ni bandeau)
            if not a_une_societe(c):
                resultat[c["id"]] = None
                raisons["sans_societe"] = raisons.get("sans_societe", 0) + 1     # lot 127.2 : diagnostic
                continue
            client, critere = index.client_du_contact(c)
            if est_interne(client, internes, domaines):
                if critere == "societe":
                    resultat[c["id"]] = None                 # la SOCIÉTÉ est SAWALI elle-même : pas de puce
                    raisons["societe_sawali"] = raisons.get("societe_sawali", 0) + 1   # lot 127.2 : diagnostic
                    continue
                # Lot 126 — relié à un compte de l'équipe seulement par son e-mail / téléphone (ex. Diane, ÉCOLE DES
                # MÉTIERS ; Sonia, Alimentation DELI GROCERY) : sa société n'a pas de contrat → puce ROUGE, pas d'oubli
                client, critere = None, "aucun"
            fiche = fiche_contrat(client, aujourdhui, seuil_defaut)
            fiche["relie_par"] = critere
            resultat[c["id"]] = fiche
        # Lot 128 — diagnostic (comptages) : contacts reçus / analysés / reliés, par critère et par couleur
        bilan: Dict[str, int] = {}
        for f in resultat.values():
            cle = "sans_puce" if f is None else f"{f.get('etat')}_{f.get('relie_par')}"
            bilan[cle] = bilan.get(cle, 0) + 1
        logger.info("[puce_contrat] demandés=%s visibles=%s comptes_indexés=%s sociétés_indexées=%s bilan=%s sans_puce=%s",
                    len(payload.contact_ids or []), len(contacts), len(index.par_id), len(index.par_societe), bilan,
                    raisons)
        return {"actif": True, "contrats": resultat}

    # Lot 121 — même puce dans la fenêtre de chat « Support Loois » (postes Loois → client SAWALI) : mêmes droits
    # (_contexte), même index des comptes (_index), même calcul (fiche_contrat). Voir puce_contrat_support.py.
    from routes.puce_contrat_support import installer_routes_support
    installer_routes_support(db=db, api=api, get_current_user=get_current_user, contexte=_contexte, index=_index)

    return {"vider_cache": vider_cache}
