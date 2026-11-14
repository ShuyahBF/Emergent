"""Lot 389 — Transactions SMS : réception sans doublon, filtres, statistiques, associations numéro → plateforme, lecture signée par la plateforme.
Lancer : cd backend && python -m pytest tests/test_lot389_transactions_sms.py -q -p no:xdist
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routes import transactions_sms as ts  # noqa: E402


def ms(a, m, j, h=12):
    return int(datetime(a, m, j, h, tzinfo=timezone.utc).timestamp() * 1000)


# ----------------------------------------------------------------- logique pure
def test_numero_lu_dans_le_sms():
    # forme de référence = indicatif + numéro (22670112233) ; sans indicatif écrit = Burkina Faso (226)
    assert ts.numero_de("Vous avez recu 25000 FCFA de 70112233. Solde: 40000 FCFA") == "22670112233"
    assert ts.numero_de("Transfert reçu de +226 70 11 22 33 le 12/11") == "22670112233"
    assert ts.numero_de("de 00226 70-11-22-33") == "22670112233"
    assert ts.numero_de("Paiement de 2,150.00 FCFA a ALIMENTATION a ete effectue. Trans id: MP261113.1339.95787510. Votre solde est de 64030202 FCFA") is None
    assert ts.numero_de("Vous avez payé 15000000 FCFA à SONABEL") is None          # un montant n'est pas un numéro
    assert ts.numero_de("") is None
    # autres pays, écrits avec leur indicatif
    assert ts.numero_de("Reçu de +33 6 12 34 56 78 hier") == "33612345678"
    assert ts.numero_de("Reçu de 00225 07 12 34 56 78") == "2250712345678"
    assert ts.numero_de("de +233 24 123 4567") == "233241234567"
    # SMS au format réel d'Orange Money (valeurs fictives) : le numéro contient des chiffres > 7 (ex. 71828394) et est suivi d'une virgule et du nom
    reel = "Vous avez recu 25000.0 FCFA, Frais:  FCFA, Taxe:  FCFA du 71828394,awa. Le solde de votre compte est de 25153.0202 FCFA Trans ID: PP261113.0926.00000001. Flashez le QR CODE marchand"
    assert ts.numero_de(reel) == "22671828394" and ts.tiers_de(reel, "votre compte est de") == "awa"
    assert ts.tiers_de("Paiement de 2150 FCFA a ALIMENTATION", "ALIMENTATION") == "ALIMENTATION"


def test_indicatifs_des_pays():
    n = ts.normaliser_numero
    assert n("+226 70 11 22 33") == n("00226 70 11 22 33") == n("226 70112233") == n("70 11 22 33") == n("(+226) 70-11-22-33") == "22670112233"
    assert n("+33 6 12 34 56 78") == n("+33 06 12 34 56 78") == n("0033612345678") == "33612345678"       # le « 0 » de tête français est retiré
    assert n("06 12 34 56 78", "33") == "33612345678"                                                       # indicatif du pays choisi
    assert n("+225 07 12 34 56 78") == "2250712345678" and n("07 12 34 56 78", "225") == "2250712345678"
    assert n("70 11 22 3") is None and n("+226 70 11 22") is None and n("") is None and n("abc") is None   # mauvaise longueur
    assert n("+1 415 555 0123") == "14155550123"
    assert n("+380 44 123 45 67") == "380441234567"                                                         # pays hors liste : accepté tel quel
    assert ts.formater_numero("22670112233") == "+226 70 11 22 33" and ts.formater_numero("33612345678") == "+33 6 12 34 56 78" and ts.formater_numero(None) == ""


def test_cles_de_lien():
    assert ts.cle_lien("+226 70 11 22 33") == ("numero", "22670112233")
    assert ts.cle_lien("70112233") == ("numero", "22670112233")                                           # pays par défaut : Burkina Faso
    assert ts.cle_lien("06 12 34 56 78", "33") == ("numero", "33612345678")                               # pays choisi : France
    assert ts.cle_lien("+33 6 12 34 56 78", "226") == ("numero", "33612345678")                           # l'indicatif écrit l'emporte sur le pays choisi
    assert ts.cle_lien("OUEDRAOGO  Awa") == ("nom", "ouedraogo awa")
    for mauvais in ("ab", "70 11 22", "+226 12"):
        with pytest.raises(ValueError):
            ts.cle_lien(mauvais)
    # anciens liens du lot 389 : 8 chiffres sans indicatif = Burkina Faso
    assert ts.cle_canonique({"type": "numero", "cle": "70112233"}) == "22670112233" and ts.cle_canonique({"type": "numero", "cle": "33612345678"}) == "33612345678"


def test_operateurs_et_nettoyage():
    assert ts.operateur_de("OrangeMoney", "") == "Orange Money" and ts.operateur_de("MOOV", "") == "Moov Money" and ts.operateur_de("CORIS BANK", "") == "Banque"
    assert ts.operateur_de("AMI", "salut") == "Autre"
    ok = ts.nettoyer_paiement({"adresse": "MOOV", "recu_le_ms": 5, "genre": "RECETTE", "montant": "2500", "tiers": " Awa ", "solde": "10", "reference": "", "corps": "x"})
    assert ok["montant"] == 2500 and ok["tiers"] == "Awa" and ok["solde"] == 10 and ok["reference"] is None
    for mauvais in (None, {"genre": "AUTRE", "montant": 1, "recu_le_ms": 1}, {"genre": "DEPENSE", "montant": 0, "recu_le_ms": 1}, {"genre": "DEPENSE", "montant": "x", "recu_le_ms": 1},
                    {"genre": "DEPENSE", "montant": 5, "recu_le_ms": 0}):
        assert ts.nettoyer_paiement(mauvais) is None


def _item(adresse, jour, genre, montant, tiers, corps="", ref=None, source="s1"):
    p = {"k": f"{adresse}{jour}{montant}", "source": source, "adresse": adresse, "ms": ms(2026, 11, jour), "genre": genre, "montant": montant, "tiers": tiers, "solde": None, "reference": ref, "corps": corps}
    return ts.enrichir(p, [{"type": "numero", "cle": "70112233", "plateforme": "albarka", "libelle": "Cabinet Dr X"}])


ITEMS = [_item("OrangeMoney", 13, "DEPENSE", 2150, "ALIMENTATION LA MENAGERE", ref="MP261113.1"),
         _item("OrangeMoney", 10, "DEPENSE", 5000, "Pharmacie Étoile"),
         _item("MOOV", 2, "RECETTE", 25000, "OUEDRAOGO Awa", corps="Vous avez reçu 25000 FCFA de 70112233"),
         _item("TELECEL", 8, "DEPENSE", 10000, "pharmacie etoile", source="s2")]


def test_filtres_et_association():
    f = lambda **k: [p["montant"] for p in ts.filtrer(ITEMS, **k)]
    assert f() == [2150, 5000, 10000, 25000]                                          # plus récent d'abord
    assert f(operateur="Orange Money") == [2150, 5000] and f(genre="RECETTE") == [25000] and f(source="s2") == [10000]
    assert f(q="PHARMACIE etoile") == [5000, 10000] and f(q="MP261113") == [2150] and f(q="70112233") == [25000]
    assert f(plateforme="albarka") == [25000] and f(plateforme="*lie") == [25000] and f(plateforme="*non_lie") == [2150, 5000, 10000]
    assert f(du_ms=ms(2026, 11, 9), au_ms=ms(2026, 11, 13)) == [5000]                 # fin exclue


def test_statistiques():
    s = ts.statistiques(ITEMS)
    assert s["totaux"]["depenses"] == 17150 and s["totaux"]["recettes"] == 25000 and s["totaux"]["net"] == 7850 and s["totaux"]["plus_grosse"] == 10000
    assert s["par_operateur"][0]["operateur"] == "Orange Money" and s["par_operateur"][0]["nombre"] == 2
    assert [b["cle"] for b in s["barres"]] == ["2026-11-02", "2026-11-08", "2026-11-10", "2026-11-13"]
    assert [b["cle"] for b in ts.statistiques(ITEMS, par_mois=True)["barres"]] == ["2026-11"]
    pharmacie = next(t for t in s["top_tiers"] if "pharmacie" in t["nom"].lower())
    assert pharmacie["nombre"] == 2 and pharmacie["total"] == 15000                    # « Étoile » et « etoile » regroupés
    assert sum(p[1] for p in s["parts"]) == s["total_classement"] == 17150


def test_csv_et_vue_plateforme():
    c = ts.csv_de(ITEMS).splitlines()
    assert c[0].startswith("﻿\"Date\";\"Opérateur\"") and "albarka" in c[-1] or "albarka" in "".join(c)
    v = ts.vue_plateforme(ITEMS[2])
    assert v["sens"] == "entree" and v["numero"] == "+226 70 11 22 33" and v["client"] == "Cabinet Dr X" and "corps" not in v and "adresse" not in v


# ----------------------------------------------------------------- routes
def _app():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot389"]
    asyncio.get_event_loop().run_until_complete(db.liluvine_emetteurs.insert_many([
        {"code": "albarka", "nom": "ALBARKA", "secret": "cle-albarka", "actif": True, "client_id": "cli-albarka"}, {"code": "ster", "nom": "Ster", "secret": "cle-ster", "actif": True}]))
    asyncio.get_event_loop().run_until_complete(db.users.insert_one(
        {"id": "cli-albarka", "role": "client", "email": "dg@albarka.bf", "full_name": "BADINI Awa", "company": "Cabinet ALBARKA", "phone": "+226 71 82 83 94"}))
    qui = {"role": "admin"}
    app, api = FastAPI(), APIRouter(prefix="/api")

    async def utilisateur():
        return {"role": qui["role"]}
    ts.setup_transactions_sms_routes(db=db, api=api, get_current_user=utilisateur)
    app.include_router(api)
    return qui, TestClient(app)


def _signer(cle, corps: bytes, code="albarka"):
    t = str(int(time.time()))
    return {"X-Emetteur": code, "X-Timestamp": t, "X-Signature": hmac.new(cle.encode(), f"{t}.{corps.decode()}".encode(), hashlib.sha256).hexdigest(), "Content-Type": "application/json"}


def test_parcours_complet():
    qui, c = _app()
    src = c.post("/api/admin/transactions-sms/sources", json={"nom": "Téléphone du bureau"}).json()
    entetes = {"X-Source": src["id"], "X-Cle": src["cle"]}
    lot = {"paiements": [
        {"adresse": "MOOV", "recu_le_ms": ms(2026, 11, 2), "genre": "RECETTE", "montant": 25000, "tiers": "OUEDRAOGO Awa", "reference": None, "corps": "Vous avez reçu 25000 FCFA de 70 11 22 33"},
        {"adresse": "OrangeMoney", "recu_le_ms": ms(2026, 11, 13), "genre": "DEPENSE", "montant": 2150, "tiers": "ALIMENTATION", "reference": "MP261113.1", "corps": "Paiement ... Trans id: MP261113.1"},
        {"adresse": "OrangeMoney", "recu_le_ms": ms(2026, 10, 20), "genre": "DEPENSE", "montant": 700, "tiers": "Kiosque", "corps": "Paiement kiosque"},
        {"genre": "INCONNU", "montant": 5, "recu_le_ms": 1}]}
    r = c.post("/api/transactions-sms/v1/envoi", json=lot, headers=entetes).json()
    assert r == {"acceptees": 3, "doublons": 0, "ignorees": 1}
    assert c.post("/api/transactions-sms/v1/envoi", json=lot, headers=entetes).json() == {"acceptees": 0, "doublons": 3, "ignorees": 1}     # renvoi : aucun doublon
    assert c.post("/api/transactions-sms/v1/envoi", json=lot, headers={"X-Source": src["id"], "X-Cle": "mauvaise"}).status_code == 401
    assert c.post("/api/transactions-sms/v1/envoi", json=lot).status_code == 401
    # écran : liste, filtres, statistiques
    tout = c.get("/api/admin/transactions-sms").json()
    assert tout["total"] == 3 and tout["stats"]["totaux"]["recettes"] == 25000
    assert c.get("/api/admin/transactions-sms", params={"du": "2026-11-01", "au": "2026-11-13"}).json()["total"] == 2
    assert c.get("/api/admin/transactions-sms", params={"operateur": "Moov Money"}).json()["total"] == 1
    assert c.get("/api/admin/transactions-sms", params={"du": "pas une date"}).status_code == 422
    assert c.get("/api/admin/transactions-sms/export.csv").text.startswith("﻿")
    # association : numéro → plateforme ; la plateforme ne voit que ses transactions, sans le texte du SMS
    assert c.post("/api/admin/transactions-sms/liens", json={"cle": "+226 70112233", "plateforme": "albarka", "libelle": "Cabinet Dr X"}).status_code == 200
    assert c.post("/api/admin/transactions-sms/liens", json={"cle": "70112233", "plateforme": "albarka"}).status_code == 409
    assert c.post("/api/admin/transactions-sms/liens", json={"cle": "70112299", "plateforme": "inconnue"}).status_code == 422
    assert c.get("/api/admin/transactions-sms", params={"plateforme": "albarka"}).json()["total"] == 1
    corps = json.dumps({"sens": "entree"}).encode()
    pf = c.post("/api/webhook/plateforme-paiements", content=corps, headers=_signer("cle-albarka", corps)).json()
    assert pf["total"] == 1 and pf["transactions"][0]["montant"] == 25000 and pf["transactions"][0]["client"] == "Cabinet Dr X"
    assert "corps" not in pf["transactions"][0]
    autre = c.post("/api/webhook/plateforme-paiements", content=b"{}", headers=_signer("cle-ster", b"{}", "ster")).json()
    assert autre["total"] == 0                                                          # une autre plateforme ne voit rien
    assert c.post("/api/webhook/plateforme-paiements", content=corps, headers=_signer("mauvaise", corps)).status_code == 401
    # droits : réservé à l'administrateur ; suppression d'un téléphone
    qui["role"] = "superviseur"
    assert c.get("/api/admin/transactions-sms").status_code == 403 and c.post("/api/admin/transactions-sms/sources", json={"nom": "x y"}).status_code == 403
    qui["role"] = "admin"
    etat = c.get("/api/admin/transactions-sms/etat").json()
    assert etat["sources"][0]["recues"] == 3 and {p["code"] for p in etat["plateformes"]} == {"albarka", "ster"} and "cle_hash" not in etat["sources"][0]
    assert c.delete(f"/api/admin/transactions-sms/sources/{src['id']}").status_code == 200
    assert c.post("/api/transactions-sms/v1/envoi", json=lot, headers=entetes).status_code == 401
    assert c.get("/api/admin/transactions-sms").json()["total"] == 3                    # les transactions reçues sont conservées


def test_association_a_un_client_sawali_et_suggestions():
    qui, c = _app()
    src = c.post("/api/admin/transactions-sms/sources", json={"nom": "Téléphone du DG"}).json()
    reel = "Vous avez recu 25000.0 FCFA du 71828394,awa. Le solde de votre compte est de 25153 FCFA Trans ID: PP261113.0926.00000001."
    c.post("/api/transactions-sms/v1/envoi", headers={"X-Source": src["id"], "X-Cle": src["cle"]},
           json={"paiements": [{"adresse": "OrangeMoney", "recu_le_ms": ms(2026, 11, 13), "genre": "RECETTE", "montant": 25000, "tiers": "votre compte est de", "reference": "PP261113.0926.00000001", "corps": reel}]})
    etat = c.get("/api/admin/transactions-sms/etat").json()
    assert {x["id"] for x in etat["clients"]} == {"cli-albarka"}
    # suggestion : le numéro du SMS est le téléphone d'un client de SAWALI
    sug = c.get("/api/admin/transactions-sms/suggestions").json()["suggestions"]
    assert sug == [{"numero": "22671828394", "numero_affiche": "+226 71 82 83 94", "client_id": "cli-albarka", "client_nom": "Cabinet ALBARKA", "nombre": 1, "total": 25000}]
    # association à un CLIENT (sans plateforme) : refusée si le client est inconnu ou si rien n'est choisi
    assert c.post("/api/admin/transactions-sms/liens", json={"cle": "71828394"}).status_code == 422
    assert c.post("/api/admin/transactions-sms/liens", json={"cle": "71828394", "client_id": "inconnu"}).status_code == 422
    assert c.post("/api/admin/transactions-sms/liens", json={"cle": "+226 71 82 83 94", "client_id": "cli-albarka"}).status_code == 200
    assert c.get("/api/admin/transactions-sms/suggestions").json()["suggestions"] == []                 # n'est plus à associer
    liste = c.get("/api/admin/transactions-sms", params={"plateforme": "client:cli-albarka"}).json()
    assert liste["total"] == 1 and liste["transactions"][0]["client_nom"] == "Cabinet ALBARKA" and liste["transactions"][0]["tiers"] == "awa"
    # ALBARKA (émetteur lié au client cli-albarka) retrouve ce paiement ; ZandGo (autre client) non
    corps = json.dumps({"sens": "entree"}).encode()
    pf = c.post("/api/webhook/plateforme-paiements", content=corps, headers=_signer("cle-albarka", corps)).json()
    assert pf["total"] == 1 and pf["transactions"][0]["client"] == "Cabinet ALBARKA" and pf["transactions"][0]["montant"] == 25000
    ster = c.post("/api/webhook/plateforme-paiements", content=corps, headers=_signer("cle-ster", corps, "ster")).json()
    assert ster["total"] == 0


def test_transactions_du_client_pour_son_historique():
    """Lot 391 — les paiements reçus par SMS des numéros associés à un client de SAWALI (jamais ceux d'un autre client ni les dépenses)."""
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot391"]
    loop = asyncio.get_event_loop()
    item = lambda k, genre, corps, ms_: {"k": k, "source": "s1", "adresse": "OrangeMoney", "ms": ms_, "genre": genre, "montant": 25000, "tiers": "Payeur", "solde": None, "reference": k, "corps": corps}
    loop.run_until_complete(db.settings.insert_many([
        {"_id": "transactions-sms:config", "sources": [], "liens": [{"id": "1", "type": "numero", "cle": "22671828394", "plateforme": None, "libelle": "Cabinet", "client_id": "c1", "client_nom": "Cabinet"},
                                                                  {"id": "2", "type": "numero", "cle": "70112233", "plateforme": "albarka", "libelle": "Autre"}]},
        {"_id": "transactions-sms:2026-11", "mois": "2026-11", "items": [
            item("a", "RECETTE", "Vous avez recu 25000 FCFA du 71828394,awa.", ms(2026, 11, 13)),
            item("b", "DEPENSE", "Paiement de 25000 FCFA a 71828394", ms(2026, 11, 12)),             # une dépense : ignorée
            item("c", "RECETTE", "Vous avez recu 25000 FCFA du 70112233,x.", ms(2026, 11, 11)),       # associé à une plateforme, pas à ce client
            item("d", "RECETTE", "Vous avez recu 25000 FCFA du 71828394,awa.", ms(2026, 11, 2))]}]))
    res = loop.run_until_complete(ts.transactions_du_client(db, "c1"))
    assert [p["k"] for p in res] == ["a", "d"] and all(p["client_id"] == "c1" for p in res)
    assert loop.run_until_complete(ts.transactions_du_client(db, "inconnu")) == []
