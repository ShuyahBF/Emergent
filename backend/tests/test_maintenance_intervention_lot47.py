"""Lot 47 — Maintenance : intervention en cours / arrêtée / terminée, durée, « Prête à
facturer », facturation refusée tant qu'une intervention est ouverte. MongoDB simulé, Caisse
simulée, horloge simulée.
Lancer : cd backend && python -m pytest tests/test_maintenance_intervention_lot47.py -q
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.maintenance_equipements as me  # noqa: E402

USERS = {"admin": {"id": "admin", "role": "admin", "full_name": "Admin"},
         "phl": {"id": "phl", "role": "pharmacien", "company": "Pharmacie PHL", "client_code": "PHL",
                 "whatsapp_number": "+226 70 11 22 33"},
         "sav": {"id": "sav", "role": "client", "client_code": "SAV", "company": "SAV", "full_name": "Tech SAV"},
         "autre": {"id": "autre", "role": "client", "client_code": "AUT"},
         "sans": {"id": "sans", "role": "client"}}
FICHE = {"compte_client_id": "phl", "type_materiel": "Imprimante", "marque_modele": "HP 1020",
         "etat_materiel": "mauvais", "motif": "Bourrage papier", "equipe": "Issa, Awa"}


@pytest.fixture()
def env(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_mnt47"]
    factures = []
    # Horloge simulée : chaque test avance le temps à la main
    horloge = {"t": datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(me, "_maintenant", lambda: horloge["t"].isoformat())

    async def get_user(request: Request):
        u = USERS.get(request.headers.get("X-User", ""))
        if not u:
            raise HTTPException(status_code=401)
        return u

    async def fonction_active(user, cle):
        assert cle == "maintenance_equipements"
        return user["id"] != "sans"

    async def facture(user, client, items, *, notes=None, due_date=None, kind="invoice", source=""):
        factures.append({"client": client, "items": items, "kind": kind, "source": source, "notes": notes})
        return {"id": f"inv{len(factures)}", "number": f"F-2026-{len(factures):04d}",
                "net_to_pay": sum(i["unit_price_ht"] * i["quantity"] for i in items)}

    api = APIRouter(prefix="/api")
    me.attach_maintenance_routes(api=api, db=db, get_current_user=get_user, fonction_active=fonction_active,
                                 create_invoice_for_client=facture)
    app = FastAPI()
    app.include_router(api)
    client = TestClient(app).__enter__()
    client.portal.call(db.users.insert_many, [dict(u) for u in USERS.values()])

    def avancer(minutes):
        horloge["t"] += timedelta(minutes=minutes)

    yield {"c": client, "db": db, "factures": factures, "avancer": avancer}
    client.__exit__(None, None, None)


def h(u):
    return {"X-User": u}


def _nouvelle(c, u="admin", **extra):
    return c.post("/api/me/maintenance", headers=h(u), json={**FICHE, **extra}).json()


def _etat(c, fid, etat, note=None, u="admin"):
    return c.post(f"/api/me/maintenance/{fid}/intervention", headers=h(u), json={"etat": etat, "note": note})


def test_fiche_neuve_sans_intervention(env):
    f = _nouvelle(env["c"])
    assert f["etat_intervention"] is None and f["interventions"] == [] and f["intervention_ouverte"] is None
    assert f["duree_totale_minutes"] == 0 and f["prete_a_facturer"] is False


def test_cycle_complet_et_duree(env):
    c, avancer = env["c"], env["avancer"]
    f = _nouvelle(c)
    # Ouverture
    r = _etat(c, f["id"], "en_cours", "Démontage")
    assert r.status_code == 200
    o = r.json()
    assert o["etat_intervention"] == "en_cours" and o["prete_a_facturer"] is False
    i = o["intervention_ouverte"]
    assert i["debut"].startswith("2026-09-30T08:00") and i["fin"] is None and i["duree_minutes"] is None
    assert i["equipe"] == "Issa, Awa" and i["ouverte_par"] == {"id": "admin", "nom": "Admin"} and i["note"] == "Démontage"
    # Double ouverture refusée
    assert _etat(c, f["id"], "en_cours").status_code == 409
    # Arrêt avec motif : 45 min, prête à facturer
    avancer(45)
    a = _etat(c, f["id"], "arrete", "Pièce à commander").json()
    assert a["etat_intervention"] == "arrete" and a["intervention_ouverte"] is None and a["prete_a_facturer"] is True
    i1 = a["interventions"][0]
    assert i1["duree_minutes"] == 45 and i1["motif"] == "Pièce à commander" and i1["etat_fin"] == "arrete"
    assert i1["fermee_par"]["nom"] == "Admin"
    # Nouvel arrêt / fin sans intervention ouverte : refus
    assert _etat(c, f["id"], "arrete").status_code == 409
    assert _etat(c, f["id"], "termine").status_code == 409
    # Réouverture (nouvelle intervention), puis terminaison : 1 h 30
    avancer(60 * 24)
    assert len(_etat(c, f["id"], "en_cours").json()["interventions"]) == 2
    avancer(90)
    t = _etat(c, f["id"], "termine", "Rouleau changé").json()
    assert t["etat_intervention"] == "termine" and t["interventions"][1]["duree_minutes"] == 90
    assert t["interventions"][1]["note_fin"] == "Rouleau changé"
    assert t["duree_totale_minutes"] == 135 and t["prete_a_facturer"] is True
    # Liste : champs exposés, filtre « Prêtes à facturer », compteurs
    _nouvelle(c)
    lst = c.get("/api/me/maintenance", headers=h("admin")).json()
    assert len(lst["fiches"]) == 2 and lst["compte_intervention"] == {"en_cours": 0, "prete_a_facturer": 1}
    pretes = c.get("/api/me/maintenance", headers=h("admin"), params={"prete": "true"}).json()["fiches"]
    assert [x["id"] for x in pretes] == [f["id"]] and pretes[0]["duree_totale_minutes"] == 135
    # Texte WhatsApp de la fiche : état et durée totale
    texte = me.texte_fiche(t)
    assert "Intervention : Terminée" in texte and "Durée d'intervention : 2 h 15 min" in texte


def test_facturation_refusee_puis_acceptee_avec_recap(env):
    c, avancer, factures = env["c"], env["avancer"], env["factures"]
    f = _nouvelle(c)
    _etat(c, f["id"], "en_cours")
    # Intervention ouverte : facture refusée, message clair ; proforma (devis) permise
    r = c.post(f"/api/me/maintenance/{f['id']}/facturer", headers=h("admin"), json={})
    assert r.status_code == 409 and r.json()["detail"] == "Fermez l'intervention (Arrêtée ou Terminée) avant de facturer"
    assert c.post(f"/api/me/maintenance/{f['id']}/facturer", headers=h("admin"), json={"kind": "proforma"}).status_code == 200
    avancer(30)
    _etat(c, f["id"], "termine")
    assert c.get(f"/api/me/maintenance/{f['id']}", headers=h("admin")).json()["prete_a_facturer"] is True
    fa = c.post(f"/api/me/maintenance/{f['id']}/facturer", headers=h("admin"), json={})
    assert fa.status_code == 200 and fa.json()["kind"] == "invoice"
    notes = factures[-1]["notes"]
    assert notes.startswith(f"Maintenance — fiche {f['numero']}")
    assert "Interventions :" in notes and "30/09/2026 08:00 → 30/09/2026 08:30 (30 min)" in notes
    assert "Terminée" in notes and "Équipe : Issa, Awa" in notes and "Durée totale : 30 min" in notes
    apres = c.get(f"/api/me/maintenance/{f['id']}", headers=h("admin")).json()
    assert apres["prete_a_facturer"] is False and apres["facture"]["numero"] == fa.json()["numero"]
    # Déjà facturée : une nouvelle intervention fermée ne la remet pas « Prête à facturer »
    _etat(c, f["id"], "en_cours")
    assert _etat(c, f["id"], "termine").json()["prete_a_facturer"] is False


def test_fiche_ancienne_toujours_facturable(env):
    c, db, factures = env["c"], env["db"], env["factures"]
    # Fiche antérieure au lot 47 : aucun champ d'intervention en base
    c.portal.call(db.maintenance_fiches.insert_one, {
        "id": "ancienne", "tenant_id": "admin", "numero": "MNT-ADM-2026-0099", "compte_client_id": "phl",
        "client_nom": "Pharmacie PHL", "type_materiel": "Onduleur", "motif": "Ne charge plus",
        "prix_diagnostic": 10000, "date_reception": "2026-01-10"})
    lue = c.get("/api/me/maintenance/ancienne", headers=h("admin")).json()
    assert lue["etat_intervention"] is None and lue["interventions"] == [] and lue["prete_a_facturer"] is False
    r = c.post("/api/me/maintenance/ancienne/facturer", headers=h("admin"), json={})
    assert r.status_code == 200 and factures[-1]["notes"] == "Maintenance — fiche MNT-ADM-2026-0099"


def test_put_ne_modifie_pas_l_intervention(env):
    c = env["c"]
    f = _nouvelle(c)
    _etat(c, f["id"], "en_cours")
    r = c.put(f"/api/me/maintenance/{f['id']}", headers=h("admin"), json={
        **FICHE, "diagnostic": "Galet usé", "etat_intervention": "termine", "prete_a_facturer": True,
        "interventions": []})
    assert r.status_code == 200
    d = r.json()
    assert d["diagnostic"] == "Galet usé" and d["etat_intervention"] == "en_cours"
    assert d["prete_a_facturer"] is False and len(d["interventions"]) == 1 and d["intervention_ouverte"]


def test_droits_et_validation(env):
    c = env["c"]
    f = _nouvelle(c, u="sav", compte_client_id=None, client_nom="Client comptoir")
    # Fiche d'un autre compte : introuvable ; fonction non activée : refus ; état inconnu : 422
    assert _etat(c, f["id"], "en_cours", u="autre").status_code == 404
    assert _etat(c, f["id"], "en_cours", u="sans").status_code == 403
    assert _etat(c, f["id"], "pause", u="sav").status_code == 422
    o = _etat(c, f["id"], "en_cours", u="sav").json()
    assert o["intervention_ouverte"]["ouverte_par"] == {"id": "sav", "nom": "Tech SAV"}
