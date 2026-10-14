"""Lot 159 — « Pseudo contrat VALIDE » (5 jours) : calcul d'activité, effet sur la puce du contrat et sur le statut envoyé
à Loois, route de la fiche client. MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_lot159_pseudo_contrat.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# abonnement_acces (utilisé par le statut Loois) importe db.py, qui lit ces variables à l'import : valeurs factices de test
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test")
mongomock_motor = pytest.importorskip("mongomock_motor")

from routes.loois_synchro import statut_contrat_loois  # noqa: E402
from routes.puce_contrat import fiche_contrat  # noqa: E402
import routes.pseudo_contrat as pc  # noqa: E402

MAINTENANT = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
FUTUR = (MAINTENANT + timedelta(days=3)).isoformat()
PASSE = (MAINTENANT - timedelta(hours=1)).isoformat()
EN_RETARD = {"id": "c1", "company": "Clinique X", "contract_number": "C-1", "contract_billing_period": "monthly",
             "last_payment_at": "2025-01-01", "contract_signed_at": "2025-01-01"}


def test_activite_et_expiration_apres_cinq_jours():
    assert pc.pseudo_actif({pc.CHAMP: FUTUR}, MAINTENANT) is True
    assert pc.pseudo_actif({pc.CHAMP: PASSE}, MAINTENANT) is False          # expiré : retour à la normale
    assert pc.pseudo_actif({}, MAINTENANT) is False and pc.pseudo_actif(None) is False
    assert pc.pseudo_actif({pc.CHAMP: "n'importe quoi"}, MAINTENANT) is False


def test_puce_toujours_verte_quand_la_case_est_cochee():
    jour = date(2026, 10, 14)
    assert fiche_contrat(EN_RETARD, jour)["etat"] in ("retard", "aucun")       # sans la case : pas valide
    futur_reel = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    f = fiche_contrat({**EN_RETARD, pc.CHAMP: futur_reel}, jour)
    assert f["etat"] == "valide" and f["statut"] == "pseudo_valide" and "Pseudo contrat VALIDE" in f["statut_libelle"]
    # Même sans aucun contrat (ni numéro) : la case rend le contrat valide
    assert fiche_contrat({"id": "c2", "company": "Y", pc.CHAMP: futur_reel}, jour)["etat"] == "valide"
    # Case expirée : retour à la normale
    expire = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert fiche_contrat({**EN_RETARD, pc.CHAMP: expire}, jour)["etat"] != "valide"


def test_loois_pas_d_anonymisation_pendant_les_cinq_jours():
    a = datetime.now(timezone.utc)
    sans = statut_contrat_loois({**EN_RETARD}, a)
    assert sans["anonymiser"] is True                                            # contrat échu, case décochée
    avec = statut_contrat_loois({**EN_RETARD, pc.CHAMP: (a + timedelta(days=2)).isoformat()}, a)
    assert avec == {"statut": "pseudo_valide", "actif": True, "anonymiser": False, "echeance": None}
    assert statut_contrat_loois({**EN_RETARD, pc.CHAMP: (a - timedelta(days=1)).isoformat()}, a)["anonymiser"] is True


def test_route_coche_decoche_et_compte_rattache_refuse():
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot159"]
    asyncio.new_event_loop().run_until_complete(db.users.insert_many([
        {"id": "p", "email": "p@x.bf"}, {"id": "f", "email": "f@x.bf", "parent_client_id": "p"}]))

    async def admin():
        return {"id": "a", "email": "admin@test"}

    api = APIRouter(prefix="/api")
    pc.setup_pseudo_contrat_routes(db=db, api=api, get_current_admin=admin)
    app = FastAPI()
    app.include_router(api)
    c = TestClient(app)
    r = c.put("/api/admin/clients/p/pseudo-contrat", json={"actif": True}).json()
    assert r["actif"] is True
    fin = datetime.fromisoformat(r["jusqu_au"])
    assert timedelta(days=4, hours=23) < fin - datetime.now(timezone.utc) <= timedelta(days=5)
    doc = asyncio.new_event_loop().run_until_complete(db.users.find_one({"id": "p"}))
    assert pc.pseudo_actif(doc) and doc["pseudo_contrat_modifie_par"] == "admin@test"
    assert c.put("/api/admin/clients/p/pseudo-contrat", json={"actif": False}).json() == {"actif": False, "jusqu_au": None}
    assert c.put("/api/admin/clients/f/pseudo-contrat", json={"actif": True}).status_code == 422     # compte rattaché
    assert c.put("/api/admin/clients/zzz/pseudo-contrat", json={"actif": True}).status_code == 404
