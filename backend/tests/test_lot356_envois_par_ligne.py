# Lot 356 — impression des envois par ligne, coût estimé avec le « Coût par message » de la fiche du client lié.
import asyncio
from datetime import datetime, timezone

import mongomock_motor

from routes import alertes_plateformes as ap


def test_envois_par_ligne_cout_fiche_client():
    async def scenario():
        db = mongomock_motor.AsyncMongoMockClient()["t"]
        now = datetime.now(timezone.utc).isoformat()
        await db.settings.insert_one({"_id": "global", "wa_phone_number_id": "111", "wa_numero_id": None})
        await db.users.insert_one({"id": "c1", "company": "Clinique X", "wa_unit_cost": 15, "wa_currency": "XOF"})
        msgs = [{"direction": "outbound", "created_at": now, "wa_status": st, "wa_numero_id": "111", "client_id": "c1"}
                for st in ("sent", "delivered", "failed")]
        await db.whatsapp_messages.insert_many(msgs)
        d = await ap.envois_par_ligne(db, 30, "111")
        w = d["lignes"][0]
        assert w["envois"] == 2                      # l'échec n'est pas un envoi réussi
        assert w["par_client"][0]["cout"] == 30      # 2 × 15 (fiche du client lié)
        assert w["cout_total"] == 30
        assert ap.pdf_envois(d).startswith(b"%PDF")
    asyncio.run(scenario())
