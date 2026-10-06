"""Lot 59 — Plusieurs numéros WhatsApp SAWALI (lignes Liluvine Standard / VIP / Publicités) :
choix du numéro d'envoi, réponse depuis le numéro qui a reçu le message, règle VIP (montant du
contrat), visibilité par utilisateur dans le Centre de messagerie. MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_lot59_numeros_wa.py -q
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import HTTPException  # noqa: E402

import routes.numeros_wa as nw  # noqa: E402

# Paramètres globaux : ligne principale + ligne VIP + ligne Publicités (prospects)
REGLAGES = {
    "_id": "global",
    "wa_phone_number_id": "PN-STANDARD",
    "wa_access_token": "jeton-factice",
    "wa_numeros": [
        {"id": "PN-VIP", "libelle": "Liluvine VIP", "telephone": "+226 73 88 49 99", "vip": True,
         "complement_prompt": "Client VIP : accueil personnalisé."},
        {"id": "PN-PUB", "libelle": "Publicités", "prospects": True},
        {"id": "", "libelle": "incomplète"},           # ignorée (pas d'ID)
        {"id": "PN-STANDARD", "libelle": "doublon"},   # ignorée (doublon du principal)
    ],
    "wa_seuil_vip": 100000,
}
IL_Y_A = lambda heures: (datetime.now(timezone.utc) - timedelta(hours=heures)).isoformat()  # noqa: E731


def lancer(coro):
    """Exécute une coroutine dans une boucle neuve (tests synchrones)."""
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def db():
    """Base simulée : deux entreprises (contrat VIP / standard) et leurs contacts."""
    base = mongomock_motor.AsyncMongoMockClient()["sawali_lot59"]

    async def remplir():
        await base.settings.insert_one(dict(REGLAGES))
        await base.users.insert_many([
            {"id": "tenant-vip", "role": "client", "contract_amount": 250000},
            {"id": "tenant-std", "role": "client", "contract_amount": 76231},
        ])
        await base.directory_contacts.insert_many([
            {"id": "c-vip", "client_id": "tenant-vip", "name": "Client VIP", "whatsapp": "+22670000001"},
            {"id": "c-std", "client_id": "tenant-std", "name": "Client Standard", "whatsapp": "+22670000002"},
            {"id": "c-manuel", "client_id": "tenant-std", "name": "Affecté VIP", "whatsapp": "+22670000003",
             "wa_ligne": "PN-VIP"},
        ])
    lancer(remplir())
    return base


def test_lignes_configurees_principale_en_tete_et_doublons_ignores():
    lignes = nw.lignes_configurees(REGLAGES)
    assert [l["cle"] for l in lignes] == ["principal", "PN-VIP", "PN-PUB"]
    assert lignes[0]["libelle"] == "Liluvine Standard"   # nom par défaut de la ligne principale
    assert lignes[1]["vip"] and lignes[2]["prospects"]
    assert nw.cle_de_numero(REGLAGES, "PN-STANDARD") == "principal"
    assert nw.cle_de_numero(REGLAGES, "PN-INCONNU") is None


def test_reponse_depuis_le_numero_qui_a_recu_le_message(db):
    jeton = nw.definir_numero_recu("PN-VIP")
    try:
        # Même un client standard reçoit la réponse du numéro sur lequel il a écrit
        assert lancer(nw.numero_envoi(db, "+22670000002", REGLAGES)) == "PN-VIP"
        assert nw.numero_reponse(REGLAGES) == "PN-VIP"
        assert "accueil personnalisé" in lancer(nw.complement_prompt_ligne(REGLAGES))
    finally:
        nw.retablir_numero_recu(jeton)
    # Numéro inconnu (autre compte) : on retombe sur le principal
    jeton = nw.definir_numero_recu("PN-AUTRE-COMPTE")
    try:
        assert nw.numero_reponse(REGLAGES) == "PN-STANDARD"
    finally:
        nw.retablir_numero_recu(jeton)


def test_envoi_hors_reponse_regle_vip_affectation_et_fenetre_24h(db):
    # Règle VIP : contrat 250 000 ≥ seuil 100 000 → ligne VIP ; 76 231 → ligne principale
    assert lancer(nw.numero_envoi(db, "+22670000001", REGLAGES)) == "PN-VIP"
    assert lancer(nw.numero_envoi(db, "+22670000002", REGLAGES)) == "PN-STANDARD"
    # Affectation manuelle
    assert lancer(nw.numero_envoi(db, "+22670000003", REGLAGES)) == "PN-VIP"
    # Le client standard a écrit il y a 2 h sur la ligne Publicités : la fenêtre 24 h est sur ce numéro
    lancer(db.whatsapp_messages.insert_one({"direction": "inbound", "phone_digits": "22670000002",
                                            "wa_numero_id": "PN-PUB", "created_at": IL_Y_A(2)}))
    assert lancer(nw.numero_envoi(db, "+22670000002", REGLAGES)) == "PN-PUB"
    # Un message vieux de 3 jours ne compte plus pour l'envoi
    lancer(db.whatsapp_messages.insert_one({"direction": "inbound", "phone_digits": "22670000009",
                                            "wa_numero_id": "PN-VIP", "created_at": IL_Y_A(72)}))
    assert lancer(nw.numero_envoi(db, "+22670000009", REGLAGES)) == "PN-STANDARD"


def test_une_seule_ligne_aucune_lecture_numero_principal(db):
    seul = {"wa_phone_number_id": "PN-STANDARD"}
    assert lancer(nw.numero_envoi(db, "+22670000001", seul)) == "PN-STANDARD"


def test_droits_superviseurs_voient_tout_utilisateur_suivi_restreint():
    assert nw.lignes_autorisees({"role": "superviseur", "wa_lignes_autorisees": ["principal"]}, REGLAGES) is None
    assert nw.lignes_autorisees({"role": "client", "tracked_role": "Superviseur",
                                 "wa_lignes_autorisees": ["principal"]}, REGLAGES) is None
    assert nw.lignes_autorisees({"role": "client", "wa_lignes_autorisees": []}, REGLAGES) is None
    assert nw.lignes_autorisees({"role": "client", "wa_lignes_autorisees": ["principal"]}, REGLAGES) == {"principal"}
    # Toutes les lignes cochées = aucune restriction
    tout = {"role": "client", "wa_lignes_autorisees": ["principal", "PN-VIP", "PN-PUB"]}
    assert nw.lignes_autorisees(tout, REGLAGES) is None


def test_visibilite_utilisateur_standard(db):
    b = {"id": "u-b", "role": "client", "tracked_user_id": "tu-b", "wa_lignes_autorisees": ["principal"]}
    # Un prospect inconnu a écrit sur la ligne Publicités
    lancer(db.whatsapp_messages.insert_one({"direction": "inbound", "phone_digits": "22677777777",
                                            "wa_numero_id": "PN-PUB", "created_at": IL_Y_A(1)}))
    vis = lancer(nw.VisibiliteLignes.charger(db, b))
    contacts = {c["id"]: c for c in lancer(db.directory_contacts.find({}, {"_id": 0}).to_list(10))}
    assert vis.restreint
    assert not vis.contact_visible(contacts["c-vip"])        # règle VIP (montant du contrat)
    assert vis.contact_visible(contacts["c-std"])
    assert not vis.contact_visible(contacts["c-manuel"])     # affecté à la main
    assert not vis.contact_visible(None, "+22677777777")     # prospect des publicités
    # Un client VIP qui écrit sur le numéro Standard reste réservé aux utilisateurs VIP
    lancer(db.whatsapp_messages.insert_one({"direction": "inbound", "phone_digits": "22670000001",
                                            "wa_numero_id": "PN-STANDARD", "created_at": IL_Y_A(1)}))
    vis = lancer(nw.VisibiliteLignes.charger(db, b))
    assert not vis.contact_visible(contacts["c-vip"])
    # Envoi refusé vers un contact non autorisé, accepté vers un contact standard
    with pytest.raises(HTTPException) as err:
        lancer(nw.exiger_telephone_visible(db, b, "+22670000001", "c-vip"))
    assert err.value.status_code == 403
    lancer(nw.exiger_telephone_visible(db, b, "+22670000002", "c-std"))
    # Le superviseur voit tout
    assert lancer(nw.telephone_visible(db, {"role": "superviseur"}, "+22670000001"))


def test_ligne_prospects_detectee():
    jeton = nw.definir_numero_recu("PN-PUB")
    try:
        assert nw.ligne_recue_prospects(REGLAGES)
        assert lancer(nw.complement_prompt_ligne(REGLAGES)) == ""   # pas de consignes sur cette ligne
    finally:
        nw.retablir_numero_recu(jeton)
    assert not nw.ligne_recue_prospects(REGLAGES)
