"""Lot 462 — un numéro autorisé peut être lié à PLUSIEURS clients (codes sans doublon) ; la consigne créée vaut pour ces clients. Aucun accès réseau."""
import asyncio
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot462")

import mongomock_motor
import pytest

import consignes_liluvine as cl
import consignes_whatsapp as cw


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_codes_clients_sans_doublon_et_noms_alignes():
    r = cl.nettoyer_acces([{"numero": "+226 70 11 22 33", "nom": "Directeur", "tenants": ["A", "B", "A", " ", "B"], "tenants_noms": ["Client A", "Client B", "Client A", "", "Client B"]}])
    assert len(r) == 1 and r[0]["tenants"] == ["A", "B"]                                  # doublons et valeurs vides retirés, ordre gardé
    assert r[0]["tenants_noms"] == ["Client A", "Client B"] and r[0]["tenant"] == "A" and r[0]["tenant_nom"] == "Client A, Client B"


def test_ancien_client_unique_devient_une_liste_et_vide_veut_dire_tout_sawali():
    r = cl.nettoyer_acces([{"numero": "70123456", "tenant": "T1", "tenant_nom": "Client 1"}, {"numero": "71000001"}])
    assert r[0]["tenants"] == ["T1"] and r[0]["tenants_noms"] == ["Client 1"]
    assert r[1]["tenants"] == [] and r[1]["tenant"] == ""


def test_deux_lignes_du_meme_numero_ne_s_elargissent_jamais_a_tout_sawali():
    r = cl.nettoyer_acces([{"numero": "70123456", "tenants": ["A"]}, {"numero": "+226 70 12 34 56", "tenants": ["B", "A"]}, {"numero": "70123456"}])
    assert len(r) == 1 and r[0]["tenants"] == ["A", "B"]                                  # union des clients, jamais « vide = tout » par un doublon


def test_une_consigne_de_plusieurs_clients_vaut_pour_chacun_d_eux_seulement():
    c = {"tenants": ["A", "B"]}
    assert cl.concerne(c, "A") and cl.concerne(c, "B") and not cl.concerne(c, "C") and not cl.concerne(c, "")
    assert cl.concerne({}, "C") and cl.concerne({"tenants": []}, "C")                      # sans client : tout SAWALI
    assert cl.concerne({"tenant": "A"}, "A") and not cl.concerne({"tenant": "A"}, "B")      # anciennes consignes à un seul client


@pytest.fixture()
def db():
    d = mongomock_motor.AsyncMongoMockClient()["test_lot462"]
    run(cl.enregistrer_acces(d, [{"numero": "+226 70 11 22 33", "nom": "Responsable", "tenants": ["A", "B"], "tenants_noms": ["Client A", "Client B"], "actif": True}]))
    return d


def fausse_ia(nature="reponse"):
    async def f(phrase):
        return {"nature": nature, "resume": phrase, "instruction": phrase, "debut": "2026-11-24T00:00", "fin": "2026-11-30T23:59", "creneau_debut": "", "creneau_fin": "",
                "appliquee": nature in cl.NATURES_APPLIQUEES, "envoi_masse": nature == "masse", "ia": True, "message": "x", "rdv_du": "2026-11-25"}
    return f


def test_whatsapp_la_consigne_porte_les_clients_du_numero_et_l_envoi_en_masse_est_refuse(db):
    run(cw.traiter(db, "22670112233", "consigne : répondre que le centre ferme à 17h", interpreter=fausse_ia()))
    assert "activée" in run(cw.traiter(db, "22670112233", "oui"))
    fiche = run(cl.charger(db))[0]
    assert fiche["tenants"] == ["A", "B"] and fiche["tenant"] == "A"
    assert "pas permis" in run(cw.traiter(db, "22670112233", "consigne : écris à tous les RDV de demain", interpreter=fausse_ia("masse")))
