"""Lot 158 — ligne « Liluvine VIP » réservée aux clients dont le contrat est valide :
réglages, contrôle d'accès, canal choisi dans la conversation (forcé sur la ligne standard), message de refus
envoyé une seule fois sur la ligne VIP. MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_lot158_vip_contrat.py -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.numeros_wa as nw  # noqa: E402
import routes.vip_contrat as vc  # noqa: E402

REGLAGES = {"wa_phone_number_id": "111", "wa_principal_libelle": "Liluvine Standard",
            "wa_numeros": [{"id": "222", "libelle": "Liluvine VIP", "vip": True}], "wa_vip_controle_actif": True}


def lancer(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def faux_etat(monkeypatch, etat):
    """Simule l'état du contrat du client (valide | retard | aucun | None)."""
    async def _etat(db, contact, settings_doc=None):
        return etat
    monkeypatch.setattr(vc, "etat_contrat_contact", _etat)


def test_reglages_par_defaut_et_contrat_valide():
    r = vc.reglages({})
    assert r["actif"] is False and "Transfert de votre message aux agents de SAWALI" in r["message"] and r["notification"]
    assert vc.reglages({"wa_vip_controle_actif": True, "wa_vip_message_refus": "  Bonjour  "})["message"] == "Bonjour"
    assert vc.contrat_valide("valide") and vc.contrat_valide(None)           # non analysable : non bloqué
    assert not vc.contrat_valide("retard") and not vc.contrat_valide("aucun")


def test_acces_vip(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot158a"]
    faux_etat(monkeypatch, "retard")
    assert lancer(vc.acces_vip(db, {}, telephone="22676111111"))["autorise"] is True               # contrôle désactivé
    assert lancer(vc.acces_vip(db, REGLAGES, telephone="22676111111", contact={"id": "c"}))["autorise"] is False
    faux_etat(monkeypatch, "valide")
    assert lancer(vc.acces_vip(db, REGLAGES, telephone="22676111111", contact={"id": "c"}))["autorise"] is True


def test_canal_vip_force_sur_la_ligne_standard(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot158b"]
    admin = {"id": "a", "role": "admin"}
    faux_etat(monkeypatch, "retard")
    c = lancer(vc.choisir_canal(db, REGLAGES, user=admin, telephone="22676111111", contact_id=None, demande="222"))
    assert c["cle"] == "principal" and c["force"] is True and "ligne standard" in c["avertissement"]
    faux_etat(monkeypatch, "valide")
    c = lancer(vc.choisir_canal(db, REGLAGES, user=admin, telephone="22676111111", contact_id=None, demande="222"))
    assert c["cle"] == "222" and c["force"] is False and c["avertissement"] is None
    # Rien demandé ou ligne inconnue : règles habituelles
    assert lancer(vc.choisir_canal(db, REGLAGES, user=admin, telephone="x", contact_id=None, demande=""))["cle"] is None
    assert lancer(vc.choisir_canal(db, REGLAGES, user=admin, telephone="x", contact_id=None, demande="999"))["cle"] is None
    # Utilisateur limité à la ligne standard : la ligne VIP demandée est ignorée
    limite = {"id": "u", "role": "client", "wa_lignes_autorisees": ["principal"]}
    assert lancer(vc.choisir_canal(db, REGLAGES, user=limite, telephone="x", contact_id=None, demande="222"))["cle"] is None


def test_message_refus_envoye_une_seule_fois_sur_la_ligne_vip(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot158c"]
    envoyes = []

    async def envoyer(to, texte, **kw):
        envoyes.append((to, texte))
        return {"ok": True}

    faux_etat(monkeypatch, "retard")
    appel = dict(chiffres="22676111111", contact={"id": "c", "company": "ACME"}, envoyer_texte=envoyer)
    r = lancer(vc.traiter_message_entrant(db, REGLAGES, numero_recu="222", **appel))
    assert r["refuse"] is True and r["texte_envoye"] is True and len(envoyes) == 1
    assert "Transfert de votre message aux agents de SAWALI" in envoyes[0][1]
    r = lancer(vc.traiter_message_entrant(db, REGLAGES, numero_recu="222", **appel))      # 2e message : pas de répétition
    assert r["refuse"] is True and r["texte_envoye"] is False and len(envoyes) == 1
    # Message reçu sur la ligne standard : rien à contrôler
    assert lancer(vc.traiter_message_entrant(db, REGLAGES, numero_recu="111", **appel))["refuse"] is False
    # Contrôle désactivé : rien ne change
    sans = dict(REGLAGES, wa_vip_controle_actif=False)
    assert lancer(vc.traiter_message_entrant(db, sans, numero_recu="222", **appel))["refuse"] is False
    # Contrat valide : Liluvine répond comme avant
    faux_etat(monkeypatch, "valide")
    assert lancer(vc.traiter_message_entrant(db, REGLAGES, numero_recu="222", **appel))["refuse"] is False


def test_ligne_forcee_et_regle_vip_dans_le_choix_du_numero(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot158d"]
    jeton = nw.definir_ligne_forcee("222")
    try:
        assert lancer(nw.numero_envoi(db, "22676111111", REGLAGES)) == "222"       # ligne choisie par l'agent
    finally:
        nw.retablir_ligne_forcee(jeton)
    # Contact affecté à la main à la ligne VIP, client en retard : ramené sur la ligne principale
    lancer(db.directory_contacts.insert_one({"id": "c", "client_id": "t", "whatsapp": "+22676111111", "wa_ligne": "222"}))
    faux_etat(monkeypatch, "retard")
    assert lancer(nw.numero_envoi(db, "22676111111", REGLAGES)) == "111"
    faux_etat(monkeypatch, "valide")
    assert lancer(nw.numero_envoi(db, "22676111111", REGLAGES)) == "222"
