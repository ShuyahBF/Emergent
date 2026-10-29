# Lot 361 — moyens de paiement des formulaires / sondages, transmission aux plateformes, « autres travaux IA » par ligne.
import asyncio
from datetime import datetime, timezone

import mongomock_motor

from routes import alertes_plateformes as ap
from routes import paiement_formulaires as pf
from routes import transmission_plateformes as tp

DEFAUT = ["ORANGE", "MOOV", "TELECEL"]


def test_pawapay_actif_par_defaut_et_operateurs():
    assert pf.moyens_actifs({}) == ["PAWAPAY"]                      # règle : PawaPay par défaut
    assert pf.moyens_actifs({"paiement_formulaires_moyens": []}) == ["PAWAPAY"]
    assert pf.operateurs_autorises(["PAWAPAY"], DEFAUT) == DEFAUT   # PawaPay seul : les trois opérateurs
    assert pf.operateurs_autorises(["ORANGE", "PISPI"], DEFAUT) == ["ORANGE"]
    assert pf.operateurs_autorises(["PISPI"], DEFAUT) == []         # PI-SPI seul : aucun opérateur
    assert pf.methodes_du_lien(["ORANGE", "PISPI"], DEFAUT) == ["MOBILE", "PISPI"]
    assert pf.methodes_du_lien(["PISPI"], DEFAUT) == ["PISPI"]
    assert pf.libelle_moyens(["PAWAPAY"], DEFAUT) == "Orange, Moov ou Telecel"
    assert pf.libelle_moyens(["PISPI"], DEFAUT) == "PI-SPI"


def test_confirmation_pispi_lance_la_mise_en_ligne():
    async def scenario():
        db = mongomock_motor.AsyncMongoMockClient()["t"]
        appels = []

        async def hook(paiement):
            appels.append(paiement)
        await db.payment_links.insert_one({"id": "L1", "slug": "abc", "methodes": ["PISPI"], "amount": 5000, "client_id": "c1"})
        routeur = pf.make_router(db=db, get_current_user=lambda: {}, send_email=None, hooks_apres_paiement=[hook])
        confirmer = next(r.endpoint for r in routeur.routes if r.path.endswith("/confirmer"))
        await confirmer("abc", user={"role": "admin", "email": "a@b.c"})
        assert appels and appels[0]["status"] == "completed" and appels[0]["payment_link_id"] == "L1"
        await confirmer("abc", user={"role": "admin", "email": "a@b.c"})      # idempotent : un seul déclenchement
        assert len(appels) == 1
    asyncio.run(scenario())


def test_transmission_garde_la_copie_et_compte_sur_la_ligne(monkeypatch):
    async def scenario():
        db = mongomock_motor.AsyncMongoMockClient()["t"]
        maintenant = datetime.now(timezone.utc).isoformat()
        await db.settings.insert_one({"_id": "global", "wa_phone_number_id": "111", "wa_numero_id": None,
                                      "wa_numeros": [{"id": "222", "libelle": "ALBARKA"}]})
        await db.forms.insert_one({"id": "F1", "title": "Satisfaction", "client_id": "c1", "pages": [{"questions": []}]})
        await db.liluvine_emetteurs.insert_one({"code": "albarka", "nom": "ALBARKA", "actif": True, "secret": "s", "ligne": "222",
                                                "url_formulaires": "https://x.test/recevoir"})

        async def faux_poster(emetteur, corps):
            assert corps["type"] == "formulaire" and "client_id" not in corps["document"]       # champs internes retirés
            return {"ok": True, "http": 200, "erreur": None}
        monkeypatch.setattr(tp, "poster", faux_poster)
        doc = await db.forms.find_one({"id": "F1"})
        emetteur = await db.liluvine_emetteurs.find_one({"code": "albarka"})
        entree = await tp.transmettre(db, "formulaire", doc, emetteur, "admin@x")
        assert entree["ok"]
        copie = await db.forms.find_one({"id": "F1"})
        assert copie["title"] == "Satisfaction" and copie["transmissions"][0]["plateforme"] == "albarka"   # copie + historique
        # le journal compte la transmission comme AUTRE TRAVAIL IA de la ligne ALBARKA, pas comme envoi WhatsApp
        d = await ap.envois_par_ligne(db, 30, "222")
        w = d["lignes"][0]
        assert w["envois"] == 0 and w["autres_travaux"] == [{"libelle": "Formulaires transmis à des plateformes", "nombre": 1}]
        assert ap.pdf_envois(d).startswith(b"%PDF")
    asyncio.run(scenario())


def test_signature_hmac_stable():
    assert tp.signer(b"cle", '{"a":1}', "100") == tp.signer(b"cle", '{"a":1}', "100")
    assert tp.signer(b"cle", '{"a":1}', "100") != tp.signer(b"autre", '{"a":1}', "100")
