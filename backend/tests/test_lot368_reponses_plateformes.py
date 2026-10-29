# Lot 368 — retour des réponses : une plateforme renvoie à SAWALI les réponses à un formulaire / sondage qu'elle a reçu.
import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone

import mongomock_motor
import pytest
from fastapi import HTTPException

from routes import transmission_plateformes as tp


async def _base():
    db = mongomock_motor.AsyncMongoMockClient()["t"]
    await db.liluvine_emetteurs.insert_one({"code": "albarka", "nom": "ALBARKA", "actif": True, "secret": "cle"})
    await db.liluvine_emetteurs.insert_one({"code": "ekol", "nom": "e-Kol", "actif": True, "secret": "cle2"})
    ok = {"plateforme": "albarka", "ok": True, "le": "2026-10-29T10:00:00+00:00"}
    await db.forms.insert_one({"id": "F1", "title": "Satisfaction", "client_id": "c1", "transmissions": [ok]})
    await db.forms.insert_one({"id": "F2", "title": "Jamais transmis", "client_id": "c1"})
    await db.wa_surveys.insert_one({"id": "S1", "title": "Évaluation", "client_id": "c1", "transmissions": [ok]})
    return db


def _corps(**plus):
    return {"type": "formulaire", "id_sawali": "F1", "reponse_id": "r1", "recu_le": "2026-10-29T11:00:00+00:00",
            "repondant": {"nom": "Awa", "email": "awa@test.bf"}, "data": {"a1": "Très bien", "a2": ["x", "y"], "a3": {"imbrique": 1}}, **plus}


def test_reponse_rangee_dans_la_copie_sous_le_nom_de_la_plateforme():
    async def scenario():
        db = await _base()
        emetteur = await db.liluvine_emetteurs.find_one({"code": "albarka"})
        assert (await tp.recevoir_reponse(db, emetteur, _corps())) == {"ok": True, "deja": False}
        sub = await db.form_submissions.find_one({"form_id": "F1"})
        assert sub["plateforme_nom"] == "ALBARKA" and sub["via"] == "plateforme" and sub["user_label"] == "Awa"
        assert sub["client_id"] == "c1" and sub["created_at"] == "2026-10-29T11:00:00+00:00"
        assert sub["data"]["a1"] == "Très bien" and sub["data"]["a2"] == ["x", "y"] and isinstance(sub["data"]["a3"], str)   # un objet est réduit à du texte
        assert (await db.forms.find_one({"id": "F1"}))["uses_count"] == 1
        # Même réponse renvoyée : aucun doublon
        assert (await tp.recevoir_reponse(db, emetteur, _corps()))["deja"] is True
        assert await db.form_submissions.count_documents({}) == 1
    asyncio.run(scenario())


def test_reponse_de_sondage():
    async def scenario():
        db = await _base()
        emetteur = await db.liluvine_emetteurs.find_one({"code": "albarka"})
        await tp.recevoir_reponse(db, emetteur, _corps(type="sondage", id_sawali="S1", data={"q1": 5, "q2": "Bien"}))
        r = await db.wa_survey_responses.find_one({"survey_id": "S1"})
        assert r["answers"] == {"q1": 5, "q2": "Bien"} and r["plateforme_nom"] == "ALBARKA"
    asyncio.run(scenario())


def test_refus_document_inconnu_non_transmis_ou_mal_forme():
    async def scenario():
        db = await _base()
        albarka = await db.liluvine_emetteurs.find_one({"code": "albarka"})
        ekol = await db.liluvine_emetteurs.find_one({"code": "ekol"})
        with pytest.raises(HTTPException) as e:
            await tp.recevoir_reponse(db, albarka, _corps(id_sawali="INCONNU"))
        assert e.value.status_code == 422
        with pytest.raises(HTTPException) as e:
            await tp.recevoir_reponse(db, albarka, _corps(id_sawali="F2"))               # jamais transmis à ALBARKA
        assert e.value.status_code == 403
        with pytest.raises(HTTPException) as e:
            await tp.recevoir_reponse(db, ekol, _corps())                                # transmis à ALBARKA, pas à e-Kol
        assert e.value.status_code == 403
        for mauvais in (_corps(reponse_id=""), _corps(data="texte"), _corps(type="autre")):
            with pytest.raises(HTTPException) as e:
                await tp.recevoir_reponse(db, albarka, mauvais)
            assert e.value.status_code == 422
        assert await db.form_submissions.count_documents({}) == 0
    asyncio.run(scenario())


def test_route_signee_signature_valide_et_refusee():
    async def scenario():
        db = await _base()
        routeur = tp.make_router(db=db, get_current_user=lambda: {}, is_admin_like=lambda u: True)
        route = next(r.endpoint for r in routeur.routes if r.path.endswith("/webhook/plateforme-reponse-formulaire"))
        brut = json.dumps(_corps()).encode()
        ts = str(int(datetime.now(timezone.utc).timestamp()))

        class Requete:
            def __init__(self, signature):
                self.headers = {"X-Emetteur": "albarka", "X-Timestamp": ts, "X-Signature": signature}

            async def body(self):
                return brut
        bonne = hmac.new(b"cle", f"{ts}.{brut.decode()}".encode(), hashlib.sha256).hexdigest()
        assert (await route(Requete(bonne)))["ok"] is True
        with pytest.raises(HTTPException) as e:
            await route(Requete("0" * 64))
        assert e.value.status_code == 401
    asyncio.run(scenario())
