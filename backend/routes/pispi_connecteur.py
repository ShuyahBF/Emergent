"""Lot 57.8 — Connecteurs PI-SPI (paiement instantané BCEAO) : interface commune et connecteur manuel.

Contexte (vérifié le 04/10/2026) :
  - PI-SPI = Plateforme Interopérable du Système de Paiement Instantané de la BCEAO (UEMOA).
  - Le QR code PI-SPI est fourni par la banque du bénéficiaire ; son format interne n'est pas
    public. SAWALI ne fabrique donc AUCUN QR « PI-SPI » : il imprime celui de la banque.
  - Au Burkina, seule Ecobank propose une API Business homologuée ; UBA et BSIC participent à
    PI-SPI sans API Business homologuée ; IB Bank : statut à confirmer.

Conséquence : AUCUN appel d'API bancaire n'est fait aujourd'hui. Ce module prépare seulement
l'emplacement des futurs connecteurs, sans inventer d'adresse ni de format d'API.

Organisation (équivalent WinDev : une classe abstraite + des classes dérivées) :
  - ConnecteurPispi        : interface commune (3 méthodes à fournir par chaque connecteur) ;
  - ConnecteurManuel       : le SEUL actif — l'encaissement est saisi à la main (référence bancaire) ;
  - ConnecteurNonDisponible: emplacements Ecobank / UBA / BSIC / IB Bank, qui répondent tous
                             « non disponible » tant que l'accès à une API Business n'est pas obtenu ;
  - connecteur_actif()     : choisit le connecteur d'après la variable PISPI_FOURNISSEUR.

Variables d'environnement prévues (facultatives, saisies par le propriétaire dans Render,
jamais écrites dans le code) : PISPI_FOURNISSEUR, PISPI_API_URL, PISPI_CLIENT_ID,
PISPI_CLIENT_SECRET. Aujourd'hui seule PISPI_FOURNISSEUR est lue (choix du connecteur).
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class ConnecteurIndisponible(Exception):
    """Levée par un connecteur bancaire qui n'est pas encore utilisable (pas d'API homologuée)."""


# ---------------------------------------------------------------------------
# Interface commune : chaque connecteur doit fournir ces trois méthodes.
# ---------------------------------------------------------------------------
class ConnecteurPispi(ABC):
    code: str = ""          # identifiant court (ex. « manuel », « ecobank »)
    libelle: str = ""       # nom affiché
    automatique: bool = False   # True = la banque confirme elle-même les paiements (API)

    @abstractmethod
    async def demander_paiement(self, *, reference: str, montant: float, devise: str = "XOF") -> Dict[str, Any]:
        """Prépare une demande de paiement pour la facture `reference` (montant restant dû)."""

    @abstractmethod
    async def statut(self, *, reference: str) -> Dict[str, Any]:
        """Renvoie l'état connu du paiement de la facture `reference`."""

    @abstractmethod
    async def notification(self, *, corps: bytes, entetes: Dict[str, str]) -> Dict[str, Any]:
        """Traite une notification de paiement envoyée par la banque (webhook)."""


# ---------------------------------------------------------------------------
# Connecteur manuel : le seul actif aujourd'hui.
# Le client paie avec le QR imprimé ; le caissier saisit ensuite l'encaissement
# (mode « PI-SPI » + référence bancaire) et la facture est rapprochée.
# ---------------------------------------------------------------------------
class ConnecteurManuel(ConnecteurPispi):
    code = "manuel"
    libelle = "Saisie manuelle (QR de la banque imprimé sur la facture)"
    automatique = False

    async def demander_paiement(self, *, reference: str, montant: float, devise: str = "XOF") -> Dict[str, Any]:
        # Rien n'est envoyé à la banque : on rappelle seulement ce que le client doit indiquer.
        return {
            "connecteur": self.code,
            "reference": reference,
            "montant": float(montant or 0),
            "devise": devise,
            "statut": "attendu",
            "message": "Le client paie avec le QR PI-SPI imprimé et indique la référence ; "
                       "l'encaissement est ensuite saisi à la main.",
        }

    async def statut(self, *, reference: str) -> Dict[str, Any]:
        # Le connecteur manuel ne sait rien de plus que ce qui a été saisi en base.
        return {"connecteur": self.code, "reference": reference, "statut": "inconnu",
                "message": "Statut connu uniquement par la saisie manuelle des encaissements."}

    async def notification(self, *, corps: bytes, entetes: Dict[str, str]) -> Dict[str, Any]:
        # Aucune banque n'envoie de notification en mode manuel.
        raise ConnecteurIndisponible("Notifications désactivées : connecteur manuel (aucune API bancaire configurée).")


# ---------------------------------------------------------------------------
# Emplacements des futurs connecteurs bancaires.
# À REMPLIR seulement quand la banque aura fourni sa documentation officielle et des accès
# (URL, identifiants, format des notifications, signature). D'ici là, toute méthode répond
# « non disponible » — aucune URL ni aucun format n'est inventé ici.
# ---------------------------------------------------------------------------
class ConnecteurNonDisponible(ConnecteurPispi):
    raison: str = "API Business non homologuée / accès non obtenu"

    def _refus(self):
        raise ConnecteurIndisponible(f"Connecteur {self.libelle} non disponible : {self.raison}.")

    async def demander_paiement(self, *, reference: str, montant: float, devise: str = "XOF") -> Dict[str, Any]:
        self._refus()

    async def statut(self, *, reference: str) -> Dict[str, Any]:
        self._refus()

    async def notification(self, *, corps: bytes, entetes: Dict[str, str]) -> Dict[str, Any]:
        self._refus()


class ConnecteurEcobank(ConnecteurNonDisponible):
    # Seule API Business homologuée au Burkina (au 17/09/2026) : à brancher après obtention
    # du contrat et de la documentation Ecobank (PISPI_API_URL, PISPI_CLIENT_ID, PISPI_CLIENT_SECRET).
    code = "ecobank"
    libelle = "Ecobank"
    raison = "accès à l'API Business Ecobank non obtenu"


class ConnecteurUba(ConnecteurNonDisponible):
    # UBA participe à PI-SPI mais sans API Business homologuée (au 17/09/2026).
    code = "uba"
    libelle = "UBA"


class ConnecteurBsic(ConnecteurNonDisponible):
    # BSIC participe à PI-SPI mais sans API Business homologuée (au 17/09/2026).
    code = "bsic"
    libelle = "BSIC"


class ConnecteurIbBank(ConnecteurNonDisponible):
    # IB Bank : participation à PI-SPI et API Business à confirmer.
    code = "ib_bank"
    libelle = "IB Bank"
    raison = "statut PI-SPI et API Business à confirmer"


# Table des connecteurs connus (code -> classe)
CONNECTEURS = {
    c.code: c for c in (ConnecteurManuel, ConnecteurEcobank, ConnecteurUba, ConnecteurBsic, ConnecteurIbBank)
}


def connecteur_actif(code: Optional[str] = None) -> ConnecteurPispi:
    """Connecteur choisi par PISPI_FOURNISSEUR (vide ou inconnu = manuel)."""
    choix = (code if code is not None else os.environ.get("PISPI_FOURNISSEUR") or "").strip().lower()
    classe = CONNECTEURS.get(choix) or ConnecteurManuel
    return classe()


def notifications_actives() -> bool:
    """La route de notification n'est ouverte que pour un connecteur automatique réellement branché.
    Aujourd'hui aucun ne l'est : toujours False."""
    c = connecteur_actif()
    return bool(c.automatique) and not isinstance(c, ConnecteurNonDisponible)
