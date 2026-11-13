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
    assert ts.numero_de("Vous avez recu 25000 FCFA de 70112233. Solde: 40000 FCFA") == "70112233"
    assert ts.numero_de("Transfert reçu de +226 70 11 22 33 le 12/11") == "70112233"
    assert ts.numero_de("de 00226 70-11-22-33") == "70112233"
    assert ts.numero_de("Paiement de 2,150.00 FCFA a ALIMENTATION a ete effectue. Trans id: MP261113.1339.95787510. Votre solde est de 64030202 FCFA") is None
    assert ts.numero_de("Vous avez payé 15000000 FCFA à SONABEL") is None          # un montant n'est pas un numéro
    assert ts.numero_de("") is None


def test_cles_de_lien():
    assert ts.cle_lien("+226 70 11 22 33") == ("numero", "70112233")
    assert ts.cle_lien("70112233") == ("numero", "70112233")
    assert ts.cle_lien("OUEDRAOGO  Awa") == ("nom", "ouedraogo awa")
    with pytest.raises(ValueError):
        ts.cle_lien("ab")


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
    assert v["sens"] == "entree" and v["numero"] == "70112233" and v["client"] == "Cabinet Dr X" and "corps" not in v and "adresse" not in v


# ----------------------------------------------------------------- routes
def _app():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot389"]
    asyncio.get_event_loop().run_until_complete(db.liluvine_emetteurs.insert_many([
        {"code": "albarka", "nom": "ALBARKA", "secret": "cle-albarka", "actif": True}, {"code": "ster", "nom": "Ster", "secret": "cle-ster", "actif": True}]))
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
