"""Lot 61 — Liste noire des numéros interdits aux commandes « ! » (refus + message de Liluvine,
anti-répétition 10 min, administration) et activité de chaque plateforme (adLyn, beAuthentik…)
dans la synthèse quotidienne. MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_lot61_liste_noire_plateformes.py -q
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.liste_noire_commandes as ln  # noqa: E402
import routes.rapport_plateformes as rp  # noqa: E402
import routes.synthese as sy  # noqa: E402


def lancer(coro):
    """Exécute une coroutine dans une boucle neuve."""
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def db():
    return mongomock_motor.AsyncMongoMockClient()["sawali_lot61"]


@pytest.fixture()
def client(db):
    """Application minimale avec les routes d'administration de la liste noire."""
    utilisateurs = {"adm": {"id": "adm", "role": "admin", "full_name": "Admin"},
                    "agent": {"id": "agent", "role": "client", "full_name": "Agent"}}

    async def utilisateur(request: Request):
        uid = request.headers.get("X-User")
        if uid not in utilisateurs:
            raise HTTPException(status_code=401)
        return utilisateurs[uid]

    api = APIRouter(prefix="/api")
    ln.setup_liste_noire_commandes_routes(db=db, api=api, get_current_user=utilisateur)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app)


def test_administration_liste_noire(client, db):
    h = {"X-User": "adm"}
    assert client.get("/api/admin/liluvine-commandes-bloquees", headers={"X-User": "agent"}).status_code == 403
    assert client.post("/api/admin/liluvine-commandes-bloquees", json={"telephone": "123"}, headers=h).status_code == 400
    r = client.post("/api/admin/liluvine-commandes-bloquees",
                    json={"telephone": "+226 70 11 22 33", "nom": "Abus", "motif": "spam !garde"}, headers=h)
    assert r.json()["chiffres"] == "22670112233"
    assert client.put("/api/admin/liluvine-commandes-bloquees/message", json={"message": "Accès refusé."}, headers=h).status_code == 200
    liste = client.get("/api/admin/liluvine-commandes-bloquees", headers=h).json()
    assert liste["items"][0]["actif"] and liste["message"] == "Accès refusé."
    assert client.delete("/api/admin/liluvine-commandes-bloquees/22670112233", headers=h).status_code == 200
    assert lancer(ln.fiche_bloquee(db, "+22670112233")) is None


def test_commande_refusee_avec_message_et_anti_repetition(db):
    envoyes = []

    async def envoyer(to, texte):
        envoyes.append((to, texte))

    lancer(db.liluvine_commandes_bloquees.insert_one({"chiffres": "22670112233", "telephone": "+22670112233", "actif": True}))
    # Message ordinaire : pas concerné
    assert lancer(ln.refuser_si_bloque(db, "22670112233", "Bonjour", envoyer)) is False
    # Numéro non bloqué : pas concerné
    assert lancer(ln.refuser_si_bloque(db, "22670999999", "!garde", envoyer)) is False
    # Commande d'un numéro bloqué (numéro reconnu sur ses 8 derniers chiffres) : refusée + message par défaut
    assert lancer(ln.refuser_si_bloque(db, "70112233", "!garde", envoyer)) is True
    assert envoyes[-1][1] == ln.MESSAGE_DEFAUT
    # Deuxième commande dans les 10 minutes : refusée, sans nouveau message
    assert lancer(ln.refuser_si_bloque(db, "22670112233", "/meteo", envoyer)) is True
    assert len(envoyes) == 1
    fiche = lancer(db.liluvine_commandes_bloquees.find_one({"chiffres": "22670112233"}))
    assert fiche["tentatives"] == 2 and fiche["derniere_commande"] == "/meteo"
    # Après 10 minutes : nouveau message, personnalisé
    vieux = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    lancer(db.liluvine_commandes_bloquees.update_one({"chiffres": "22670112233"}, {"$set": {"derniere_reponse": vieux}}))
    lancer(db.settings.insert_one({"_id": "global", "liluvine_commandes_bloquees_message": "Accès refusé."}))
    assert lancer(ln.refuser_si_bloque(db, "22670112233", "!doc paracetamol", envoyer)) is True
    assert envoyes[-1][1] == "Accès refusé."


def test_activite_par_plateforme_dans_la_synthese(db):
    async def remplir():
        await db.liluvine_emetteurs.insert_many([
            {"code": "adlyn", "nom": "adLyn", "actif": True, "quota_jour": 100, "secret": "x",
             "dernier_envoi": "2026-10-05T10:00:00+00:00"},
            {"code": "beauthentik", "nom": "beAuthentik", "actif": True},
        ])
        for i in range(4):
            await db.liluvine_transmissions.insert_one({
                "date": f"2026-10-05T0{i}:00:00+00:00", "emetteur": "adlyn", "ok": i != 3,
                "statut": "read" if i == 0 else ("delivered" if i == 1 else None)})
        await db.liluvine_transmissions.insert_one({"date": "2026-10-04T10:00:00+00:00", "emetteur": "adlyn", "ok": True})
        await db.liluvine_reponses.insert_one({"emetteur": "adlyn", "relaye_le": "2026-10-05T11:00:00+00:00"})
        await db.liluvine_desinscriptions.insert_one({"emetteur": "adlyn", "actif": True, "date": "2026-10-05T12:00:00+00:00"})
        await db.liluvine_incidents.insert_one({"emetteur": "adlyn", "date": "2026-10-05T03:00:00+00:00"})
    lancer(remplir())
    plateformes = lancer(rp.activite_plateformes(db, "2026-10-05", "2026-10-06"))
    adlyn = next(p for p in plateformes if p["code"] == "adlyn")
    assert (adlyn["envois"], adlyn["reussis"], adlyn["echecs"], adlyn["remis"], adlyn["lus"]) == (4, 3, 1, 2, 1)
    assert (adlyn["reponses"], adlyn["desinscriptions"], adlyn["incidents"], adlyn["usage_quota_pct"]) == (1, 1, 1, 4)
    assert "secret" not in adlyn
    texte = rp.bloc_plateformes(plateformes)
    assert "adLyn : 4 envoi(s), 3 réussi(s), 1 échec(s)" in texte
    assert "beAuthentik : aucune activité" in texte
    # Intégré aux indicateurs et au texte transmis à Liluvine
    kpis = lancer(sy._gather_kpis(db, "", date(2026, 10, 5), date(2026, 10, 5)))
    assert len(kpis["plateformes"]) == 2
    prompt = sy._build_prompt("", kpis, date(2026, 10, 5), date(2026, 10, 5))
    assert "🌐 Activité des plateformes" in prompt and "une puce par plateforme" in prompt


# ---------------------------------------------------------------------------
# Lot 61.1 — fenêtre de 24 h pour la synthèse du jour, écran d'administration
# ---------------------------------------------------------------------------

def test_fenetre_24h_et_ecran_administration(db):
    debut, fin = rp.fenetre_plateformes(date.today(), date.today())
    ecart = datetime.fromisoformat(fin) - datetime.fromisoformat(debut)
    assert ecart == timedelta(hours=24)
    assert rp.fenetre_plateformes(date(2026, 10, 1), date(2026, 10, 3)) == ("2026-10-01", "2026-10-04")

    lancer(db.liluvine_emetteurs.insert_one({"code": "adlyn", "nom": "adLyn", "actif": True}))
    recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    lancer(db.liluvine_transmissions.insert_one({"date": recent, "emetteur": "adlyn", "ok": True}))

    async def utilisateur(request: Request):
        return {"id": "adm", "role": request.headers.get("X-Role", "admin")}

    api = APIRouter(prefix="/api")
    rp.setup_rapport_plateformes_routes(db=db, api=api, get_current_user=utilisateur)
    app = FastAPI()
    app.include_router(api)
    c = TestClient(app)
    r = c.get("/api/admin/plateformes-activite", params={"jours": 1}).json()
    assert r["items"][0]["envois"] == 1 and "adLyn : 1 envoi(s)" in r["texte"]
    assert c.get("/api/admin/plateformes-activite", headers={"X-Role": "client"}).status_code == 403
