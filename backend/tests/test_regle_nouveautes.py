"""Règle permanente du propriétaire (06/10/2026) : « Ça doit être systématique ! »
Chaque lot déployé (backend/lot.py) a sa carte dans backend/nouveautes.py."""
import re
from datetime import date


def test_le_lot_courant_a_sa_carte_nouveaute():
    # Le numéro de lot de lot.py doit apparaître dans nouveautes.py : sinon le déploiement est incomplet
    import lot
    from nouveautes import NOUVEAUTES
    lots = {str(n.get("lot")) for n in NOUVEAUTES}
    assert str(lot.LOT) in lots, (
        f"Lot {lot.LOT} sans carte « Nouveautés » : ajoutez une entrée dans backend/nouveautes.py")


def test_entrees_bien_formees():
    # Chaque carte : lot, date AAAA-MM-JJ valide, titre, description, et une destination (rubrique ou écran)
    from nouveautes import NOUVEAUTES
    for n in NOUVEAUTES:
        assert n.get("lot") and n.get("titre") and n.get("description"), n
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", n["date"]), n
        date.fromisoformat(n["date"])
        assert n.get("rubrique") or n.get("lien"), f"carte sans destination : {n['titre']}"


def test_plus_recentes_en_premier():
    # L'ordre du fichier suit les dates (les plus récentes d'abord) : lecture facile pour le propriétaire
    from nouveautes import NOUVEAUTES
    dates = [n["date"] for n in NOUVEAUTES]
    assert dates == sorted(dates, reverse=True)


def test_nouveautes_valides_ignore_une_entree_abimee(monkeypatch):
    # Une entrée incomplète est écartée sans casser la liste
    import nouveautes
    monkeypatch.setattr(nouveautes, "NOUVEAUTES", [{"lot": "1"}, {"lot": "2", "date": "2026-10-06", "titre": "T", "lien": "/x"}])
    assert [n["lot"] for n in nouveautes.nouveautes_valides()] == ["2"]


def _client(role):
    # Petite application FastAPI avec la seule route des nouveautés et un utilisateur simulé
    from fastapi import FastAPI, APIRouter
    from fastapi.testclient import TestClient
    from routes.nouveautes_route import setup_nouveautes_routes
    app, api = FastAPI(), APIRouter(prefix="/api")
    setup_nouveautes_routes(api=api, get_current_user=lambda: {"role": role})
    app.include_router(api)
    return TestClient(app)


def test_route_reservee_admin():
    # Un client ordinaire n'a pas accès à la liste
    assert _client("client").get("/api/admin/nouveautes").status_code == 403


def test_route_renvoie_le_lot_courant_et_les_cartes():
    # L'administrateur reçoit le lot courant et les cartes, le lot courant en fait partie
    import lot
    corps = _client("admin").get("/api/admin/nouveautes").json()
    assert corps["lot_courant"] == str(lot.LOT)
    assert any(n["lot"] == str(lot.LOT) for n in corps["nouveautes"])
