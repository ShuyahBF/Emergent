"""Lot 34 — « Formulaires et Sondages » et « OCR sur Pièces » activables par client
(SMART Communications), par l'Admin ET le Superviseur.

Tests autonomes (mongomock-motor, aucune clé, aucun réseau) :
  - contrôle d'accès côté serveur (client, utilisateur suivi, Admin, Superviseur) ;
  - endpoints du Superviseur (liste, activation limitée aux 2 fonctions, journal) ;
  - OCR sur Pièces : accès selon la fonction, quel que soit le rôle du client ;
  - lien public d'un sondage : inactif si la fonction est désactivée pour le propriétaire.
Lancer : cd backend && python -m pytest tests/test_fonctions_clients.py -q
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routes.fonctions_clients import attach_fonctions_clients_routes  # noqa: E402

USERS = {
    "admin": {"id": "admin", "role": "admin", "email": "a@sawali.bf"},
    "sup": {"id": "sup", "role": "superviseur", "email": "s@sawali.bf"},
    # Client avec « Formulaires et Sondages » activé (et une autre fonction à ne pas toucher)
    "pharma_a": {"id": "pharma_a", "role": "pharmacien", "company": "Pharmacie A",
                 "features": {"forms_surveys": True, "whatsapp": True}},
    "suivi_a": {"id": "suivi_a", "role": "client", "parent_client_id": "pharma_a", "client_id": "pharma_a"},
    # Pharmacie sans aucune fonction (état initial de tous les clients existants)
    "pharma_b": {"id": "pharma_b", "role": "pharmacien", "company": "Pharmacie B"},
    # Médecin (pas pharmacie) avec l'OCR activé
    "medecin_c": {"id": "medecin_c", "role": "medecin", "company": "Cabinet C", "features": {"ocr_pieces": True}},
}


def _normalize(raw):
    """Doublure de _normalize_features (p03) : valeurs par défaut OFF + clés connues."""
    base = {"forms_surveys": False, "ocr_pieces": False, "whatsapp": False}
    base.update({k: bool(v) for k, v in (raw or {}).items() if k in base})
    return base


@pytest.fixture()
def env(monkeypatch):
    db = AsyncMongoMockClient()["sawali_test"]

    async def get_current_user(x_user: str = Header(...)):
        if x_user not in USERS:
            raise HTTPException(status_code=401)
        return USERS[x_user]

    async def get_admin_or_supervisor(user: dict = Depends(get_current_user)):
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")
        return user

    api = APIRouter(prefix="/api")
    outils = attach_fonctions_clients_routes(api=api, db=db, get_current_user=get_current_user,
                                             get_admin_or_supervisor=get_admin_or_supervisor,
                                             normalize_features=_normalize, now=lambda: "2026-09-29T12:00:00")

    # Route témoin protégée comme les routes /me/forms*
    @api.get("/me/forms")
    async def formulaires(user: dict = Depends(outils["exiger_fonction"]("forms_surveys"))):
        return {"ok": user["id"]}

    # OCR sur Pièces branché avec le contrôle du lot 34 (stockage objet simulé)
    fake_storage = types.ModuleType("object_storage")
    fake_storage.guess_content_type = lambda ext, fallback="application/octet-stream": fallback
    monkeypatch.setitem(sys.modules, "object_storage", fake_storage)
    from routes.ocr_pieces import attach_ocr_pieces_routes
    attach_ocr_pieces_routes(api=api, db=db, get_current_user=get_current_user,
                             fonction_active=outils["fonction_active"])

    app = FastAPI()
    app.include_router(api)
    with TestClient(app) as client:
        client.portal.call(db.users.insert_many, [dict(u) for u in USERS.values()])
        yield types.SimpleNamespace(client=client, db=db, outils=outils)


def _h(user):
    return {"X-User": user}


def test_acces_formulaires_selon_la_fonction(env):
    for user, attendu in (("admin", 200), ("sup", 200), ("pharma_a", 200), ("suivi_a", 200),   # hérite de A
                          ("pharma_b", 403), ("medecin_c", 403)):
        r = env.client.get("/api/me/forms", headers=_h(user))
        assert r.status_code == attendu, (user, r.text)
    detail = env.client.get("/api/me/forms", headers=_h("pharma_b")).json()["detail"]
    assert "« Formulaires et Sondages » n'est pas activée" in detail


def test_acces_ocr_selon_la_fonction_et_non_plus_le_role(env):
    # Pharmacie sans la fonction : refusée ; médecin avec la fonction : accepté.
    assert env.client.get("/api/ocr-pieces", headers=_h("pharma_b")).status_code == 403
    assert env.client.get("/api/ocr-pieces", headers=_h("medecin_c")).status_code == 200
    assert env.client.get("/api/ocr-pieces", headers=_h("sup")).status_code == 200
    assert "« OCR sur Pièces » n'est pas activée" in env.client.get(
        "/api/ocr-pieces", headers=_h("pharma_a")).json()["detail"]


def test_superviseur_liste_et_active(env):
    liste = env.client.get("/api/supervision/fonctions-clients", headers=_h("sup")).json()
    assert liste["fonctions"] == {"forms_surveys": "Formulaires et Sondages", "ocr_pieces": "OCR sur Pièces"}
    # Comptes clients seulement : ni Admin, ni Superviseur, ni utilisateur suivi ; triés par nom.
    assert [c["id"] for c in liste["clients"]] == ["medecin_c", "pharma_a", "pharma_b"]
    assert [(c["forms_surveys"], c["ocr_pieces"]) for c in liste["clients"]] == [(False, True), (True, False), (False, False)]
    # Le Superviseur active l'OCR pour la pharmacie B : accès ouvert aussitôt.
    r = env.client.put("/api/supervision/fonctions-clients/pharma_b", headers=_h("sup"), json={"ocr_pieces": True})
    assert r.status_code == 200 and r.json() == {"id": "pharma_b", "forms_surveys": False, "ocr_pieces": True}
    assert env.client.get("/api/ocr-pieces", headers=_h("pharma_b")).status_code == 200
    # Désactiver « Formulaires et Sondages » pour A coupe aussi son utilisateur suivi,
    # sans toucher aux autres fonctions (WhatsApp reste activé).
    env.client.put("/api/supervision/fonctions-clients/pharma_a", headers=_h("admin"), json={"forms_surveys": False})
    assert env.client.get("/api/me/forms", headers=_h("suivi_a")).status_code == 403
    a = env.client.portal.call(env.db.users.find_one, {"id": "pharma_a"}, {"_id": 0})
    assert a["features"]["whatsapp"] is True and a["features"]["forms_surveys"] is False
    assert a["features_journal"] == [{"le": "2026-09-29T12:00:00", "par": "a@sawali.bf", "role": "admin",
                                      "cle": "forms_surveys", "active": False}]


def test_refus(env):
    # Un client ne peut ni lister ni activer ; une autre fonction ne peut pas passer par là.
    assert env.client.get("/api/supervision/fonctions-clients", headers=_h("pharma_a")).status_code == 403
    assert env.client.put("/api/supervision/fonctions-clients/pharma_a", headers=_h("pharma_a"),
                          json={"ocr_pieces": True}).status_code == 403
    r = env.client.put("/api/supervision/fonctions-clients/pharma_b", headers=_h("sup"), json={"whatsapp": True})
    assert r.status_code == 400                                   # clé ignorée → rien à modifier
    b = env.client.portal.call(env.db.users.find_one, {"id": "pharma_b"}, {"_id": 0})
    assert "features" not in b                                    # aucune écriture
    assert env.client.put("/api/supervision/fonctions-clients/inconnu", headers=_h("sup"),
                          json={"ocr_pieces": True}).status_code == 404


def test_fonction_du_proprietaire(env):
    ok = env.outils["fonction_active_pour_compte"]
    run = env.client.portal.call
    assert run(ok, "admin", "forms_surveys") is True             # formulaire créé par l'Admin
    assert run(ok, "pharma_a", "forms_surveys") is True
    assert run(ok, "suivi_a", "forms_surveys") is True           # hérite de son client
    assert run(ok, "pharma_b", "forms_surveys") is False
    assert run(ok, "inconnu", "forms_surveys") is False and run(ok, None, "forms_surveys") is False


def test_lien_public_de_sondage_desactive(env):
    """Le lien public d'un sondage ne répond plus si la fonction est coupée chez son propriétaire."""
    import routes.wa_surveys as ws
    api = APIRouter(prefix="/api")
    ws.attach_wa_survey_routes(
        api=api, db=env.db, get_current_user=lambda: USERS["admin"], uuid_fn=lambda: "x", can_send_wa=lambda u: True,
        is_admin_like=lambda u: False, resolve_visible_client_ids=None, wa_enabled_for=None, enforce_demo_quota=None,
        wa_send_template=None, wa_send_text=None, wa_window_open=lambda i: False, build_recipient_ctx=None,
        build_components=None, public_base_url=lambda r: "",
        owner_enabled=lambda cid: env.outils["fonction_active_pour_compte"](cid, "forms_surveys"))
    app = FastAPI()
    app.include_router(api)
    c = TestClient(app)
    run = env.client.portal.call
    for sid, owner in (("s-a", "pharma_a"), ("s-b", "pharma_b")):
        run(env.db.wa_surveys.insert_one, {"id": sid, "client_id": owner, "title": "Avis", "questions": [],
                                           "status": "active"})
        run(env.db.wa_survey_invites.insert_one, {"id": f"i-{sid}", "survey_id": sid, "token": f"t-{sid}"})
    assert c.get("/api/public/surveys/t-s-a").status_code == 200
    r = c.get("/api/public/surveys/t-s-b")
    assert r.status_code == 404 and r.json()["detail"] == "Ce sondage n'est plus disponible"
