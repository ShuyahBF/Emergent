"""Lot 224 — suivi des consommations WhatsApp PAR LIGNE et PAR PÉRIODE.

  - noter() compte envois / réceptions / modèles Meta (nom + catégorie) / heures / IA dans un document par ligne et par mois ;
  - rapport() filtre par période et par ligne, totalise, détaille date/heure, exporte en CSV ;
  - les helpers d'envoi comptent sur le numéro réellement utilisé (ligne dédiée comprise), pas les comptes propres des clients.
"""
import asyncio
from datetime import datetime, timezone

import mongomock_motor
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from routes import wa_usage_lignes as wu

PRINCIPAL, ALBARKA = "100200300", "555000111"
REGLAGES = {"_id": "global", "wa_phone_number_id": PRINCIPAL,
            "wa_numeros": [{"id": ALBARKA, "libelle": "ALBARKA", "telephone": "+226 73 37 48 48", "privee": True}]}


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _db():
    db = mongomock_motor.AsyncMongoMockClient()["test_lot224"]
    run(db.settings.insert_one(dict(REGLAGES)))
    return db


T1 = datetime(2026, 10, 17, 9, 30, tzinfo=timezone.utc)
T2 = datetime(2026, 10, 18, 14, 5, tzinfo=timezone.utc)
T3 = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)


def _remplir(db):
    run(wu.noter(db, phone_number_id=ALBARKA, sens="out", type_msg="texte", destinataire="+22670112233", maintenant=T1))
    run(wu.noter(db, phone_number_id=ALBARKA, sens="out", type_msg="modele", modele="rappel_echeance", categorie="utility",
                 destinataire="+22670112233", maintenant=T1))
    run(wu.noter(db, phone_number_id=ALBARKA, sens="in", type_msg="text", destinataire="22670112233", maintenant=T2))
    run(wu.noter(db, phone_number_id=ALBARKA, sens="out", type_msg="ia", destinataire="22670112233",
                 ia={"tokens": 1200, "cout_xof": 3.5}, maintenant=T2))
    run(wu.noter(db, phone_number_id=ALBARKA, sens="out", type_msg="texte", ok=False, maintenant=T2))
    run(wu.noter(db, phone_number_id=PRINCIPAL, sens="out", type_msg="modele", modele="bienvenue", categorie="MARKETING", maintenant=T3))


def test_comptage_par_ligne_et_par_mois():
    db = _db()
    _remplir(db)
    doc = run(db.settings.find_one({"_id": f"wa_usage:{ALBARKA}:2026-10"}))
    j1, j2 = doc["jours"]["2026-10-17"], doc["jours"]["2026-10-18"]
    assert j1["out"] == 2 and j1["t_texte"] == 1 and j1["t_modele"] == 1 and j1["m_rappel_echeance"] == 1 and j1["c_UTILITY"] == 1
    assert j1["h_09"] == 2
    assert j2["in"] == 1 and j2["echecs"] == 1 and j2["ia_appels"] == 1 and j2["ia_tokens"] == 1200 and j2["ia_cout_xof"] == 3.5
    assert doc["derniers"][0]["fin"] == "2233"                       # 4 derniers chiffres, jamais le numéro entier
    assert run(db.settings.find_one({"_id": f"wa_usage:{PRINCIPAL}:2026-11"}))["jours"]["2026-11-02"]["c_MARKETING"] == 1


def test_rapport_periode_et_ligne():
    db = _db()
    _remplir(db)
    r = run(wu.rapport(db, du="2026-10-01", au="2026-10-31", ligne=ALBARKA))
    assert [l["libelle"] for l in r["lignes"]] == ["ALBARKA"] and r["lignes"][0]["privee"] is True
    t = r["total"]
    assert (t["sortants"], t["entrants"], t["echecs"]) == (2, 1, 1)
    assert t["par_type"]["modele"] == 1 and t["modeles"] == {"rappel_echeance": 1} and t["categories"] == {"UTILITY": 1}
    assert t["ia"] == {"appels": 1, "tokens": 1200, "cout_xof": 3.5}
    assert [j["jour"] for j in r["serie"]][:2] == ["2026-10-01", "2026-10-02"] and len(r["serie"]) == 31
    assert r["nb_evenements"] == 5 and r["evenements"][0]["t"] >= r["evenements"][-1]["t"]       # plus récent d'abord
    # Une seule journée : seuls ses compteurs
    un_jour = run(wu.rapport(db, du="2026-10-17", au="2026-10-17"))
    assert un_jour["total"]["sortants"] == 2 and un_jour["total"]["entrants"] == 0
    # Toutes lignes sur deux mois : la ligne principale de novembre apparaît
    deux_mois = run(wu.rapport(db, du="2026-10-01", au="2026-11-30"))
    assert {l["libelle"]: l["sortants"] for l in deux_mois["lignes"]} == {"Liluvine Standard": 1, "ALBARKA": 2}
    assert deux_mois["total"]["categories"] == {"UTILITY": 1, "MARKETING": 1}


def test_periodes_invalides_et_ligne_inconnue():
    db = _db()
    for du, au in (("2026-10-05", "2026-10-01"), ("abc", None), ("2025-01-01", "2026-12-31")):
        with pytest.raises(HTTPException) as e:
            run(wu.rapport(db, du=du, au=au))
        assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        run(wu.rapport(db, du="2026-10-01", au="2026-10-02", ligne="inconnue"))
    assert e.value.status_code == 404


def test_csv_et_routes_admin():
    db = _db()
    _remplir(db)

    async def admin():
        return {"email": "admin@sawali.test"}
    app = FastAPI()
    app.include_router(wu.make_wa_usage_router(db=db, get_current_admin=admin), prefix="/api")
    c = TestClient(app)
    r = c.get("/api/admin/wa-lignes/usage?du=2026-10-01&au=2026-10-31&ligne=" + ALBARKA)
    assert r.status_code == 200 and r.json()["total"]["sortants"] == 2
    csv = c.get("/api/admin/wa-lignes/usage.csv?du=2026-10-01&au=2026-10-31")
    assert csv.status_code == 200 and "ALBARKA;+226 73 37 48 48;2026-10-17;2;0;0.0" in csv.text
    assert "rappel_echeance;UTILITY" in csv.text and "utf-8" in csv.headers["content-type"]
    assert c.get("/api/admin/wa-lignes/usage?du=2026-10-09&au=2026-10-01").status_code == 400


class _FauxHttp:
    """Faux client HTTP : Meta accepte tout et renvoie un identifiant de message."""
    appels = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None, **k):
        _FauxHttp.appels.append(url)

        class R:
            status_code = 200
            text = "ok"

            def json(self_inner):
                return {"messages": [{"id": f"wamid.{len(_FauxHttp.appels)}"}]}
        return R()

    async def get(self, *a, **k):
        class R:
            status_code = 404
            text = ""

            def json(self_inner):
                return {}
        return R()


def test_envois_comptes_sur_le_numero_reel(monkeypatch):
    """Les envois passent par l'enveloppe de suivi : la ligne réellement utilisée est comptée (ligne imposée comprise),
    le compte propre d'un client n'est pas compté, un envoi refusé compte comme échec."""
    from pathlib import Path
    from routes import numeros_wa, whatsapp_helpers as wh
    db = _db()
    run(db.settings.update_one({"_id": "global"}, {"$set": {"wa_access_token": "jeton", "wa_business_account_id": "waba1"}}))
    run(db.tenant_smart_comm.insert_one({"tenant_id": "t1", "wa_access_token": "jeton-client", "wa_phone_number_id": "777"}))
    monkeypatch.setattr(wh.httpx, "AsyncClient", _FauxHttp)
    _FauxHttp.appels.clear()
    aides = wh.attach_whatsapp_helpers(db=db, wa_graph_version="v22.0", wa_media_max_bytes=1000, upload_dir=Path("/tmp"),
                                       uuid_fn=lambda: "u", now_fn=lambda: "2026-10-17T10:00:00")
    # 1) texte sur la ligne principale, 2) modèle sur la ligne d'ALBARKA (ligne imposée), 3) compte propre d'un client
    assert run(aides["_wa_send_text"]("+22670112233", "Bonjour"))["ok"]
    jeton = numeros_wa.definir_ligne_forcee(ALBARKA)
    try:
        assert run(aides["_wa_send_template"]("+22670112233", "rappel_echeance", "fr", None))["ok"]
    finally:
        numeros_wa.retablir_ligne_forcee(jeton)
    assert run(aides["_wa_send_text"]("+22670112233", "Bonjour client", tenant_id="t1"))["ok"]
    mois = datetime.now(timezone.utc).strftime("%Y-%m")
    principal = run(db.settings.find_one({"_id": f"wa_usage:{PRINCIPAL}:{mois}"}))
    albarka = run(db.settings.find_one({"_id": f"wa_usage:{ALBARKA}:{mois}"}))
    jour_p, jour_a = next(iter(principal["jours"].values())), next(iter(albarka["jours"].values()))
    assert jour_p["out"] == 1 and jour_p["t_texte"] == 1
    assert jour_a["out"] == 1 and jour_a["t_modele"] == 1 and jour_a["m_rappel_echeance"] == 1
    assert run(db.settings.find_one({"_id": f"wa_usage:777:{mois}"})) is None          # compte propre d'un client : non compté
    assert any(f"/{ALBARKA}/messages" in u for u in _FauxHttp.appels)                   # le message est bien parti de la ligne d'ALBARKA
