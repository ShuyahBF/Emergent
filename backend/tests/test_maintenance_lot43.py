"""Lot 43 — Maintenance : comptes clients, prix du diagnostic, équipe, photos, envoi WhatsApp,
lien de paiement, facturation. MongoDB simulé, WhatsApp et Caisse simulés.
Lancer : cd backend && python -m pytest tests/test_maintenance_lot43.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.maintenance_equipements as me  # noqa: E402

USERS = {"admin": {"id": "admin", "role": "admin", "full_name": "Admin"},
         "phl": {"id": "phl", "role": "pharmacien", "company": "Pharmacie PHL", "client_code": "PHL",
                 "whatsapp_number": "+226 70 11 22 33", "phone": "25 00 00 00", "pawapay_mnos": ["ORANGE"]},
         "suivi": {"id": "suivi", "role": "client", "parent_client_id": "phl", "client_id": "phl"},
         "sav": {"id": "sav", "role": "client", "client_code": "SAV", "company": "SAV"}}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


@pytest.fixture()
def env():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_mnt43"]
    envoyes, factures, fenetres = [], [], set()

    async def get_user(request: Request):
        u = USERS.get(request.headers.get("X-User", ""))
        if not u:
            raise HTTPException(status_code=401)
        return u

    async def save_and_log(db_, *, data, kind, tenant_id, ext, content_type, original_filename, user_id):
        return {"url": f"/api/files/maintenance/{len(data)}.{ext}"}

    async def wa_text(to, texte):
        envoyes.append(("texte", to, texte))
        return {"ok": True}

    async def wa_media(to, kind, *, public_url, caption=None):
        envoyes.append(("image", to, public_url))
        return {"ok": True}

    async def wa_template(to, nom, langue, comps):
        envoyes.append(("modele", to, nom, comps))
        return {"ok": True}

    def build(variables, ctx, header_text=None, header_media=None, button_specs=None):
        import re
        comps = [{"type": "body", "parameters": [re.sub(r"\{\{(\w+)\}\}", lambda m: ctx.get(m.group(1), ""), v)
                                                 for v in variables]}]
        if header_media:
            comps.insert(0, {"type": "header", "image": header_media["link"]})
        return comps

    async def ouvertes(chiffres):
        return {c for c in chiffres if c in fenetres}

    async def mnos(cid):
        return ["ORANGE"] if cid == "phl" else ["ORANGE", "MOOV"]

    async def facture(user, client, items, *, notes=None, due_date=None, kind="invoice", source=""):
        factures.append((client, items, kind, source))
        return {"id": f"inv{len(factures)}", "number": f"F-2026-{len(factures):04d}",
                "net_to_pay": sum(i["unit_price_ht"] * i["quantity"] for i in items)}

    api = APIRouter(prefix="/api")
    me.attach_maintenance_routes(
        api=api, db=db, get_current_user=get_user, fonction_active=None, save_and_log=save_and_log,
        base_publique=lambda: "https://sawali.test", wa_send_text=wa_text, wa_send_media=wa_media,
        wa_send_template=wa_template, build_components=build, fenetres_ouvertes=ouvertes,
        gen_slug=lambda n: "abc12345", mnos_du_compte=mnos, create_invoice_for_client=facture)
    app = FastAPI()
    app.include_router(api)
    client = TestClient(app).__enter__()
    client.portal.call(db.users.insert_many, [dict(u) for u in USERS.values()])
    yield {"c": client, "db": db, "envoyes": envoyes, "factures": factures, "fenetres": fenetres}
    client.__exit__(None, None, None)


def h(u):
    return {"X-User": u}


FICHE = {"compte_client_id": "phl", "type_materiel": "Imprimante", "marque_modele": "HP 1020",
         "etat_materiel": "mauvais", "motif": "Bourrage papier", "equipe": "Issa, Awa"}


def test_clients_comptes_prix_equipe(env):
    c = env["c"]
    lst = c.get("/api/me/maintenance-clients", headers=h("admin")).json()
    assert lst["type"] == "compte" and [i["id"] for i in lst["items"]] == ["phl", "sav"]    # ni admin, ni suivi
    assert lst["items"][0]["telephone"] == "+226 70 11 22 33"                                  # numéro des alertes
    assert c.get("/api/me/maintenance-clients", headers=h("sav")).json()["type"] == "contact"
    f = c.post("/api/me/maintenance", headers=h("admin"), json=FICHE).json()
    assert f["client_nom"] == "Pharmacie PHL" and f["client_telephone"] == "+226 70 11 22 33"
    assert f["prix_diagnostic"] == 10000 and f["equipe"] == "Issa, Awa" and f["compte_client_id"] == "phl"
    f2 = c.put(f"/api/me/maintenance/{f['id']}", headers=h("admin"), json={**FICHE, "prix_diagnostic": 15000}).json()
    assert f2["prix_diagnostic"] == 15000
    # Un client ne choisit pas un compte client
    assert c.post("/api/me/maintenance", headers=h("sav"), json=FICHE).status_code == 403


def test_photos_whatsapp_paiement_facture(env):
    c, envoyes = env["c"], env["envoyes"]
    f = c.post("/api/me/maintenance", headers=h("admin"), json=FICHE).json()
    # Photos : PNG accepté, autre format refusé, suppression
    p = c.post(f"/api/me/maintenance/{f['id']}/photos", headers=h("admin"), files={"fichier": ("a.png", PNG, "image/png")})
    assert p.status_code == 200 and p.json()["url"].startswith("https://sawali.test/api/files/")
    assert c.post(f"/api/me/maintenance/{f['id']}/photos", headers=h("admin"),
                  files={"fichier": ("a.gif", b"GIF89a", "image/gif")}).status_code == 400
    p2 = c.post(f"/api/me/maintenance/{f['id']}/photos", headers=h("admin"), files={"fichier": ("b.png", PNG, "image/png")}).json()
    c.delete(f"/api/me/maintenance/{f['id']}/photos/{p2['id']}", headers=h("admin"))
    assert len(c.get(f"/api/me/maintenance/{f['id']}", headers=h("admin")).json()["photos"]) == 1
    # Lien de paiement : montant du diagnostic, opérateurs du réparateur (compte de la fiche)
    lien = c.post(f"/api/me/maintenance/{f['id']}/lien-paiement", headers=h("admin"), json={}).json()
    assert lien["url"] == "https://sawali.test/pay/abc12345" and lien["montant"] == 10000
    pl = env["c"].portal.call(env["db"].payment_links.find_one, {"slug": "abc12345"})
    assert pl["allowed_mnos"] == ["ORANGE", "MOOV"] and pl["prefill_phone"] == "+226 70 11 22 33" and pl["max_uses"] == 1
    assert c.get(f"/api/me/maintenance/{f['id']}", headers=h("admin")).json()["lien_paiement"]["paye"] is False
    env["c"].portal.call(env["db"].payment_links.update_one, {"slug": "abc12345"}, {"$set": {"uses_count": 1}})
    assert c.get("/api/me/maintenance", headers=h("admin")).json()["fiches"][0]["lien_paiement"]["paye"] is True
    # Modèle à en-tête image sans photo jointe : refus clair (Meta refuserait l'envoi)
    sans = c.post(f"/api/me/maintenance/{f['id']}/whatsapp", headers=h("admin"), json={
        "template_name": "fiche_mnt", "variables": ["{{numero}}"], "header_image": True, "photos": False})
    assert sans.status_code == 400 and "en-tête image" in sans.json()["detail"]
    # WhatsApp hors fenêtre de 24 h : modèle obligatoire, 1re photo en en-tête
    assert c.post(f"/api/me/maintenance/{f['id']}/whatsapp", headers=h("admin"), json={}).status_code == 400
    r = c.post(f"/api/me/maintenance/{f['id']}/whatsapp", headers=h("admin"), json={
        "template_name": "fiche_mnt", "variables": ["{{numero}}", "{{prix}}", "{{lien_paiement}}"], "header_image": True}).json()
    assert r["mode"] == "template" and r["photos_envoyees"] == 1
    modele = envoyes[-1]
    assert modele[0] == "modele" and modele[3][0]["image"].startswith("https://sawali.test/api/files/")
    assert modele[3][1]["parameters"] == [f["numero"], "10 000 FCFA", "https://sawali.test/pay/abc12345"]
    # Fenêtre ouverte : texte de la fiche + photos
    env["fenetres"].add("22670112233")
    r = c.post(f"/api/me/maintenance/{f['id']}/whatsapp", headers=h("admin"), json={}).json()
    assert r["mode"] == "text" and r["photos_envoyees"] == 1
    texte = [e for e in envoyes if e[0] == "texte"][-1][2]
    assert f["numero"] in texte and "10 000 FCFA" in texte and "Issa, Awa" in texte and "/pay/abc12345" in texte
    # Facturer : diagnostic + ligne en plus ; une seule facture
    fa = c.post(f"/api/me/maintenance/{f['id']}/facturer", headers=h("admin"),
                json={"lignes": [{"label": "Rouleau", "quantity": 1, "unit_price_ht": 7500}]}).json()
    assert fa["numero"] == "F-2026-0001" and fa["montant"] == 17500
    client, items, kind, source = env["factures"][0]
    assert client["id"] == "phl" and len(items) == 2 and source == "maintenance"
    assert c.post(f"/api/me/maintenance/{f['id']}/facturer", headers=h("admin"), json={}).status_code == 409
