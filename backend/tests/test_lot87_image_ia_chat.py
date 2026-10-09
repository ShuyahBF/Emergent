"""Lot 87 — image illustrative générée par l'IA dans la fenêtre de support : générer, annoter, envoyer dans le chat,
transférer (chat, WhatsApp, e-mail), maintenant ou planifié. Réservé à l'équipe SAWALI.
Lancer : cd backend && python -m pytest tests/test_lot87_image_ia_chat.py -q
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, FastAPI, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routes import image_ia_chat as ia  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200


# --- Fonctions pures --------------------------------------------------------
def test_droits_equipe_sawali_seulement():
    assert ia.peut_generer({"role": "admin"})
    assert ia.peut_generer({"role": "superviseur"})
    assert ia.peut_generer({"role": "user", "tracked_role": "Superviseur"})
    assert not ia.peut_generer({"role": "superviseur", "parent_client_id": "t1"})   # rattaché à un client
    assert not ia.peut_generer({"role": "client"})
    assert not ia.peut_generer({})


def test_prompt_final_style_et_consigne():
    p = ia.prompt_final("  Un technicien   répare un serveur ", "schema")
    assert p.startswith("Un technicien répare un serveur.") and "Schéma" in p and "aucun texte" in p
    assert "Photographie" in ia.prompt_final("x", "photo")
    assert ia.prompt_final("x", "inconnu") == ia.prompt_final("x", "illustration")   # style inconnu → défaut
    with pytest.raises(ValueError):
        ia.prompt_final("   ")


def test_formats_numeros_emails():
    assert ia.taille_du_format("paysage") == "1536x1024" and ia.taille_du_format(None) == "1024x1024"
    assert ia.numero_whatsapp("76 22 22 22") == "22676222222"
    assert ia.numero_whatsapp("+33 6 12 34 56 78") == "33612345678"
    assert ia.numero_whatsapp("0022676222222") == "22676222222"
    assert ia.email_valide("a@b.co") and not ia.email_valide("a@b")
    assert "24 h" in ia.raison_whatsapp("(#131047) Re-engagement message")


def test_date_planifiee():
    t0 = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    assert ia.date_planifiee("", t0) is None
    assert ia.date_planifiee("2026-10-09T11:00:00Z", t0) is None                    # passé → tout de suite
    assert ia.date_planifiee("2026-10-09T14:00:00+00:00", t0) == datetime(2026, 10, 9, 14, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        ia.date_planifiee("demain", t0)
    with pytest.raises(ValueError):
        ia.date_planifiee("2027-01-30T10:00:00Z", t0)                               # > 60 jours


# --- Parcours complet ---------------------------------------------------------
class FauxChat:
    """Imite le routeur du chat interne (fonctions exposées par make_router)."""

    def __init__(self):
        self.postes = []

    async def verifier_membre(self, user, client_id):
        if client_id == "interdit":
            raise HTTPException(status_code=403, detail="Vous n'êtes pas membre de ce client.")

    async def poster_image(self, user, client_id, data, mime, *, recipient_id=None, caption=None, reply_to_id=None, extra=None):
        doc = {"id": f"m{len(self.postes) + 1}", "client_id": client_id, "recipient_id": recipient_id, "text": caption or "",
               "media_kind": "image", "media_mime": mime, "storage_path": f"chat/{client_id}/x.png", "taille": len(data),
               **(extra or {})}
        self.postes.append(doc)
        return doc


def _montage(utilisateur):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot87"]
    chat, envois = FauxChat(), {"wa": [], "mail": []}

    async def generateur(prompt, taille):
        envois.setdefault("prompts", []).append((prompt, taille))
        return PNG

    async def wa(numero, kind, public_url=None, caption=None):
        envois["wa"].append((numero, public_url, caption))
        return {"ok": numero != "22670000000", "error": "(#131047) Re-engagement message"}

    async def mail(to, sujet, html, texte):
        envois["mail"].append((to, html))
        return True

    async def save_and_log(db_, **kw):
        return {"url": "/api/files/sawali/u/chat-ia/a.png", "path": "sawali/u/chat-ia/a.png"}

    app, api = FastAPI(), APIRouter(prefix="/api")
    sortie = ia.setup_image_ia_chat_routes(db=db, api=api, get_current_user=lambda: utilisateur["v"], chat=chat,
                                           save_and_log=save_and_log, wa_send_media=wa, send_email=mail,
                                           base_publique=lambda: "https://api.sawali.test", generateur=generateur)
    app.include_router(api)
    return TestClient(app), db, chat, envois, sortie["traiter_planifies"]


def test_parcours_generer_annoter_envoyer_transferer():
    utilisateur = {"v": {"id": "s1", "role": "superviseur", "full_name": "Support"}}
    c, db, chat, envois, _ = _montage(utilisateur)
    assert c.get("/api/me/chat/image-ia/etat").json()["autorise"] is True
    r = c.post("/api/me/chat/image-ia", json={"prompt": "Un écran de connexion Loois", "format": "paysage"})
    assert r.status_code == 200, r.text
    apercu = r.json()
    assert apercu["apercu"].startswith("data:image/png;base64,")
    assert envois["prompts"][0][1] == "1536x1024"
    # Annoter : la version annotée (JPEG) remplace l'aperçu
    r = c.post(f"/api/me/chat/image-ia/{apercu['apercu_id']}/annoter", files={"image": ("a.jpg", b"\xff\xd8JPEG" + b"1" * 50, "image/jpeg")})
    assert r.status_code == 200 and r.json()["apercu"].startswith("data:image/jpeg")
    # Accepter : l'image part dans la discussion ouverte (fil d'un poste Loois)
    r = c.post(f"/api/me/chat/image-ia/{apercu['apercu_id']}/envoyer",
               json={"client_id": "support-loois", "recipient_id": "poste1", "legende": "Voici l'écran"})
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["ia"] is True and m["ia_annotee"] is True and m["recipient_id"] == "poste1" and m["media_mime"] == "image/jpeg"
    # Transférer à une autre discussion, sur WhatsApp et par e-mail
    assert c.post("/api/me/chat/image-ia/transferer", json={"apercu_id": apercu["apercu_id"], "canal": "chat",
                                                             "client_id": "t1", "recipient_id": "general"}).status_code == 200
    assert chat.postes[-1]["transfere"] is True and chat.postes[-1]["recipient_id"] is None
    r = c.post("/api/me/chat/image-ia/transferer", json={"apercu_id": apercu["apercu_id"], "canal": "whatsapp",
                                                          "telephone": "76 22 22 22", "legende": "Pour vous"})
    assert r.status_code == 200, r.text
    assert envois["wa"][-1] == ("22676222222", "https://api.sawali.test/api/files/sawali/u/chat-ia/a.png", "Pour vous")
    r = c.post("/api/me/chat/image-ia/transferer", json={"apercu_id": apercu["apercu_id"], "canal": "whatsapp", "telephone": "70000000"})
    assert r.status_code == 502 and "24 h" in r.json()["detail"]                       # fenêtre fermée : message clair
    assert c.post("/api/me/chat/image-ia/transferer", json={"apercu_id": apercu["apercu_id"], "canal": "email",
                                                             "email": "x@y.com"}).status_code == 200
    assert 'img src="https://api.sawali.test/' in envois["mail"][-1][1]
    assert c.post("/api/me/chat/image-ia/transferer", json={"apercu_id": apercu["apercu_id"], "canal": "fax"}).status_code == 422
    assert c.post("/api/me/chat/image-ia/transferer", json={"apercu_id": apercu["apercu_id"], "canal": "chat",
                                                             "client_id": "interdit"}).status_code == 403
    journal = asyncio.new_event_loop().run_until_complete(db[ia.COLLECTION_JOURNAL].count_documents({}))
    assert journal == 4                                                                # chat, wa ok, wa échec, e-mail
    reg = c.get("/api/admin/chat-image-ia").json()
    assert reg["stats_7j"]["generees"] == 1 and reg["stats_7j"]["envoyees"] == 1 and reg["stats_7j"]["transferts"] == 3


def test_reserve_a_l_equipe_et_limite_par_heure():
    utilisateur = {"v": {"id": "c1", "role": "client"}}
    c, db, *_ = _montage(utilisateur)
    assert c.get("/api/me/chat/image-ia/etat").json()["autorise"] is False
    assert c.post("/api/me/chat/image-ia", json={"prompt": "x"}).status_code == 403
    assert c.post("/api/me/chat/image-ia/transferer", json={"message_id": "m1", "canal": "chat"}).status_code == 403
    utilisateur["v"] = {"id": "a1", "role": "admin"}
    assert c.put("/api/admin/chat-image-ia", json={"par_heure": 1, "style": "photo"}).json()["par_heure"] == 1
    assert c.post("/api/me/chat/image-ia", json={"prompt": "x"}).status_code == 200
    assert c.post("/api/me/chat/image-ia", json={"prompt": "y"}).status_code == 429
    assert c.put("/api/admin/chat-image-ia", json={"actif": False}).json()["actif"] is False
    assert c.get("/api/me/chat/image-ia/etat").json()["autorise"] is False


def test_envoi_et_transfert_planifies():
    utilisateur = {"v": {"id": "a1", "role": "admin", "full_name": "Admin"}}
    c, db, chat, envois, traiter = _montage(utilisateur)
    boucle = asyncio.new_event_loop()
    boucle.run_until_complete(db.users.insert_one({"id": "a1", "role": "admin", "full_name": "Admin"}))
    apercu = c.post("/api/me/chat/image-ia", json={"prompt": "Affiche de maintenance"}).json()
    plus_tard = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    r = c.post(f"/api/me/chat/image-ia/{apercu['apercu_id']}/envoyer",
               json={"client_id": "t1", "planifie_le": plus_tard})
    assert r.status_code == 200 and r.json()["planifie"] is True and chat.postes == []
    r2 = c.post("/api/me/chat/image-ia/transferer", json={"apercu_id": apercu["apercu_id"], "canal": "email",
                                                           "email": "x@y.com", "planifie_le": plus_tard})
    assert r2.json()["planifie"] is True
    assert c.post("/api/me/chat/image-ia/transferer", json={"apercu_id": apercu["apercu_id"], "canal": "email",
                                                             "email": "faux", "planifie_le": plus_tard}).status_code == 422
    assert len(c.get("/api/me/chat/image-ia/planifies").json()["planifies"]) == 2
    # Rien ne part avant l'heure
    assert boucle.run_until_complete(traiter()) == 0
    # L'heure arrive : on avance les deux envois dans le passé
    boucle.run_until_complete(db[ia.COLLECTION_PLANIFIES].update_many({}, {"$set": {"planifie_le": "2000-01-01T00:00:00+00:00"}}))
    # Annulation de l'e-mail avant son traitement
    assert c.delete(f"/api/me/chat/image-ia/planifies/{r2.json()['id']}").status_code == 200
    assert boucle.run_until_complete(traiter()) == 1
    assert len(chat.postes) == 1 and chat.postes[0]["ia"] is True and envois["mail"] == []
    statuts = {d["id"]: d["statut"] for d in c.get("/api/me/chat/image-ia/planifies").json()["planifies"]}
    assert statuts == {r.json()["id"]: "envoye", r2.json()["id"]: "annule"}
    assert boucle.run_until_complete(traiter()) == 0                                  # jamais deux fois
