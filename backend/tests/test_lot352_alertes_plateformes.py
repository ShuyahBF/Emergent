"""Lot 352 — alertes des plateformes (Meta/WhatsApp) remontées à l'administrateur seul, historique par WABA et PDF."""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routes import alertes_plateformes as A  # noqa: E402

REGLAGES = {"_id": "global", "wa_business_account_id": "WABA-1", "wa_phone_number_id": "P1", "wa_principal_libelle": "Liluvine Standard",
            "wa_numeros": [{"id": "P2", "libelle": "Ligne VIP", "waba_id": "WABA-2"}, {"id": "P3", "libelle": "Autre ligne"}]}


def test_fonctions_pures():
    assert A.decrire_code(131042)["plateforme"].startswith("Meta") and A.decrire_code("131042") and A.decrire_code(131049) is None
    assert A.decrire_code(None) is None and "paiement" in A.libelle_code(131042) and A.libelle_code("x")
    carte = A.carte_lignes(REGLAGES)
    assert A.waba_du_message(carte, "P1") == "WABA-1" and A.waba_du_message(carte, "P2") == "WABA-2"
    assert A.waba_du_message(carte, "P3") == "WABA-1"            # ligne sans WABA propre : celui des réglages
    assert A.waba_du_message(carte, None) == "WABA-1" and A.waba_du_message(carte, "inconnu") == "WABA-1"
    assert A.cle_alerte(131042, "WABA-1") == "meta-131042-WABA-1"
    mail = A.texte_email({"titre": "T", "plateforme": "Meta", "depuis": "2026-10-29T12:00:00", "nombre": 3, "code": 131042, "action": "Payer",
                          "waba_id": "WABA-1"})
    assert "WABA-1" in mail["corps"] and "Payer" in mail["corps"] and mail["sujet"].startswith("🚨")


def _msg(code, quand, numero=None, statut="failed"):
    return {"direction": "outbound", "wa_status": statut, "wa_error_code": code, "created_at": quand.isoformat(), "wa_numero_id": numero}


def test_ouverture_email_unique_rappel_et_retablissement():
    from mongomock_motor import AsyncMongoMockClient

    async def scenario():
        db = AsyncMongoMockClient()["t"]
        mails = []

        async def send_email(**k):
            mails.append(k)
            return True

        await db.settings.insert_one(dict(REGLAGES))
        t0 = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
        await db.whatsapp_messages.insert_many([
            _msg(131042, t0 - timedelta(minutes=5)), _msg(131042, t0 - timedelta(minutes=2), "P1"),
            _msg(131042, t0 - timedelta(minutes=1), "P2"),                       # autre WABA
            _msg(131049, t0 - timedelta(minutes=1), "P1"), _msg(131047, t0 - timedelta(minutes=1), "P1")])      # limites normales : ignorées
        b = await A.surveiller(db, send_email, t0)
        assert sorted(b["ouvertes"]) == ["meta-131042-WABA-1", "meta-131042-WABA-2"] and len(mails) == 2
        assert all(m["to_email"] for m in mails) and "WABA-2" in mails[1]["html_body"] + mails[0]["html_body"]
        etat = await db.settings.find_one({"_id": A.DOC_ID})
        assert etat["ouvertes"]["meta-131042-WABA-1"]["nombre"] == 2 and etat["ouvertes"]["meta-131042-WABA-1"]["waba_id"] == "WABA-1"
        # passage suivant 10 min plus tard : toujours ouvertes, PAS de nouvel e-mail
        await A.surveiller(db, send_email, t0 + timedelta(minutes=10))
        assert len(mails) == 2
        # rappel 12 h plus tard tant que les échecs continuent
        await db.whatsapp_messages.insert_one(_msg(131042, t0 + timedelta(hours=12), "P1"))
        await A.surveiller(db, send_email, t0 + timedelta(hours=12, minutes=1))
        assert len(mails) == 3 and mails[2]["subject"].startswith("🚨 Rappel")
        # rétablissement : plus d'échec depuis 60 min ET un envoi réussi par une ligne du MÊME WABA
        t1 = t0 + timedelta(hours=14)
        await db.whatsapp_messages.insert_one(_msg(None, t1 - timedelta(minutes=30), "P1", statut="delivered"))
        b = await A.surveiller(db, send_email, t1)
        etat = await db.settings.find_one({"_id": A.DOC_ID})
        assert b["fermees"] == ["meta-131042-WABA-1"] and "meta-131042-WABA-2" in etat["ouvertes"]       # WABA-2 n'a eu aucun envoi réussi
        assert etat["historique"][0]["cle"] == "meta-131042-WABA-1" and "rétablie" in etat["historique"][0]["motif"]
        # fermeture manuelle
        assert await A.fermer(db, "meta-131042-WABA-2", "fermée par admin") and not await A.fermer(db, "inexistante", "x")

    asyncio.run(scenario())


def test_historique_par_waba_et_pdf():
    from mongomock_motor import AsyncMongoMockClient
    import pymupdf

    async def scenario():
        db = AsyncMongoMockClient()["t"]
        await db.settings.insert_one(dict(REGLAGES))
        maintenant = datetime.now(timezone.utc)
        await db.whatsapp_messages.insert_many([
            _msg(131042, maintenant - timedelta(days=1)), _msg(131042, maintenant - timedelta(days=1), "P1"), _msg(131049, maintenant - timedelta(days=2), "P1"),
            _msg(None, maintenant - timedelta(days=2), "P1", statut="delivered"), _msg(131042, maintenant - timedelta(days=1), "P2"),
            _msg(131042, maintenant - timedelta(days=90), "P1"),                                   # hors période
            _msg(131042, maintenant - timedelta(minutes=5), "P1")])                                # échec récent : ouvre l'alerte
        await A.surveiller(db, None, maintenant)
        h = await A.historique_par_waba(db, 30)
        par = {w["waba_id"]: w for w in h["wabas"]}
        assert set(par) == {"WABA-1", "WABA-2"}
        w1 = par["WABA-1"]
        assert w1["envois"] == 5 and w1["echecs"] == 4 and [c["code"] for c in w1["par_code"]][0] == 131042
        assert w1["par_code"][0]["critique"] is True and any(c["code"] == 131049 and not c["critique"] for c in w1["par_code"])
        assert len(w1["lignes"]) == 2 and len(w1["par_jour"]) == 3 and w1["alertes"] and w1["alertes"][0]["ouverte"] is True
        assert par["WABA-2"]["echecs"] == 1
        un = await A.historique_par_waba(db, 30, "WABA-2")
        assert [w["waba_id"] for w in un["wabas"]] == ["WABA-2"]
        pdf = A.pdf_historique(h)
        with pymupdf.open("pdf", pdf) as d:
            texte = " ".join(p.get_text() for p in d)
            assert d.page_count == 2 and "WABA-1" in texte and "WABA-2" in texte and "131042" in texte and "paiement" in texte
            assert abs(d[0].rect.width - 595) < 2          # A4

    asyncio.run(scenario())


def test_routes_reservees_a_l_administrateur():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from mongomock_motor import AsyncMongoMockClient
    from routes.llm_health import SUPER_ADMIN_EMAIL

    db = AsyncMongoMockClient()["t"]
    for email, code in ((SUPER_ADMIN_EMAIL, 200), ("autre@exemple.com", 403)):
        app = FastAPI()
        app.include_router(A.make_router(db=db, get_current_user=lambda e=email: {"email": e, "role": "admin"}, send_email=None), prefix="/api")
        c = TestClient(app)
        assert c.get("/api/admin/alertes-plateformes").status_code == code
        assert c.get("/api/admin/alertes-plateformes/historique?jours=30").status_code == code
        assert c.post("/api/admin/alertes-plateformes/verifier").status_code == code
        assert c.get("/api/admin/alertes-plateformes/historique.pdf").status_code == code
    assert c.post("/api/admin/alertes-plateformes/x/regle").status_code == 403
