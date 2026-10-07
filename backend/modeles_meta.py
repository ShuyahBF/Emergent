# modeles_meta.py — Lot 74 : règles communes sur les modèles WhatsApp Meta (fonctions pures, testées).
#
# Rappel : hors de la « fenêtre de 24 h » (le contact n'a pas écrit depuis plus de 24 h), WhatsApp
# n'accepte qu'un modèle approuvé par Meta. Le nom et la langue saisis dans SAWALI doivent être
# exactement ceux du modèle approuvé, et le nombre de variables doit correspondre.
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

# Nom par défaut du reçu de caisse (4 variables + en-tête document PDF)
MODELE_RECU_CAISSE_DEFAUT = "confirmation_paiement_avecrecu"
# Lot 74 (anomalie A1) : confirmation de paiement d'un client abonné (5 variables, sans en-tête).
# Avant ce lot, elle utilisait par défaut le MÊME nom que le reçu de caisse, alors que les deux
# structures sont incompatibles : un seul modèle Meta ne pouvait pas servir aux deux.
MODELE_PAIEMENT_CLIENT_DEFAUT = "confirmation_paiement_client"
# Alerte de retard de paiement envoyée au super-admin (5 variables)
MODELE_ALERTE_RETARD_DEFAUT = "alerte_retard_paiement"


def _texte(valeur: Any) -> str:
    """Valeur de réglage nettoyée (None -> chaîne vide)."""
    return str(valeur or "").strip()


def modele_paiement_client(modele_fiche: Any, reglages: Dict[str, Any]) -> Tuple[str, str, Optional[str]]:
    """Choisit le modèle de confirmation de paiement d'un client abonné.

    Ordre : modèle de la fiche client → réglage général (Paramètres) → nom par défaut.
    Le modèle de la fiche est ignoré s'il porte le nom du reçu de caisse (structure incompatible).
    Renvoie (nom, langue, remarque) — la remarque explique un modèle de fiche ignoré, sinon None.
    """
    nom_recu = _texte(reglages.get("wa_template_receipt_name")) or MODELE_RECU_CAISSE_DEFAUT
    general = _texte(reglages.get("wa_template_client_payment")) or MODELE_PAIEMENT_CLIENT_DEFAUT
    langue = _texte(reglages.get("wa_template_client_payment_language")) or "fr"
    fiche = _texte(modele_fiche)
    if fiche and fiche == nom_recu:
        # Le reçu de caisse attend 4 variables et un PDF : il ne peut pas servir ici
        return general, langue, (f"modèle de la fiche « {fiche} » ignoré : c'est celui du reçu de caisse "
                                 f"(structure différente) — « {general} » utilisé")
    return (fiche or general), langue, None


def parametres_alerte_retard(reglages: Dict[str, Any]) -> Tuple[str, str, str]:
    """Lot 74 (anomalie A2) : modèle, langue et numéro WhatsApp de l'alerte de retard de paiement,
    désormais réglables dans Paramètres → « Contrats — Seuil de retard de paiement (par défaut) »."""
    nom = _texte(reglages.get("contract_overdue_wa_template")) or MODELE_ALERTE_RETARD_DEFAUT
    langue = _texte(reglages.get("contract_overdue_wa_language")) or "fr"
    numero = _texte(reglages.get("super_admin_phone"))
    return nom, langue, numero
