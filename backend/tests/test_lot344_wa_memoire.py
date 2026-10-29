"""Lot 344 — mémoire des conversations WhatsApp dans Qdrant : ce qu'on indexe, ce qu'on ignore, anonymisation, identifiants stables."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routes import wa_memoire_qdrant as W  # noqa: E402

CLIENT = {"direction": "inbound", "phone_digits": "22670000000", "message_type": "text", "body": "Quel est le prix du bilan sanguin ?"}


def test_desactive_par_defaut_et_reglages():
    r = W.reglages({})
    assert r["actif"] is False and r["images"] is True and r["ia"] is True and r["ia_reponses_equipe"] is False and r["images_par_jour"] == 200
    assert W.reglages({"wa_memoire_active": True, "wa_memoire_images_par_jour": "abc"})["images_par_jour"] == 200


def test_nature_du_message_tout_sauf_le_vocal():
    assert W.nature_du_message(CLIENT) == "texte"
    humain = {**CLIENT, "direction": "outbound", "sender_id": "u1", "body": "Le bilan coûte 5 000 F."}
    assert W.nature_du_message(humain) == "texte"
    pdf = {**CLIENT, "message_type": "document", "media_mime_type": "application/pdf", "media_id": "f1", "body": "[document]"}
    assert W.nature_du_message(pdf) == "pdf"
    image = {**CLIENT, "message_type": "image", "media_kind": "image", "media_mime_type": "image/jpeg", "media_id": "f2", "body": "[image]"}
    assert W.nature_du_message(image) == "image" and W.nature_du_message(image, images_actives=False) is None
    assert W.nature_du_message({**image, "media_caption": "Mon ordonnance"}, images_actives=False) == "texte"
    # vocaux, réponses de l'IA, réponses automatiques, messages retenus, sortants sans humain : jamais indexés
    assert W.nature_du_message({**CLIENT, "message_type": "audio", "media_kind": "audio", "media_id": "f3", "body": "[audio]"}) is None
    assert W.nature_du_message({**CLIENT, "media_mime_type": "audio/ogg", "media_id": "f4"}) is None
    assert W.nature_du_message({**humain, "ai_generated": True}) is None
    assert W.nature_du_message({**humain, "auto_reply": True}) is None
    assert W.nature_du_message({**CLIENT, "barriere_retenu": True}) is None
    assert W.nature_du_message({**humain, "sender_id": None}) is None
    assert W.nature_du_message({**CLIENT, "body": "[image envoyé]"}) is None


def test_identifiants_de_points_stables():
    assert W.identifiant_point("m1", 0) == W.identifiant_point("m1", 0)
    assert W.identifiant_point("m1", 0) != W.identifiant_point("m1", 1) != W.identifiant_point("m2", 0)


def test_anonymisation():
    t = "Bonjour Awa Traoré, appelez le +226 70 00 00 00 ou écrivez à awa@example.com. Dossier 12345678."
    sortie = W.anonymiser(t, ("Awa Traoré", "Dr Zongo"))
    assert "70 00 00 00" not in sortie and "awa@example.com" not in sortie and "12345678" not in sortie
    assert "Awa" not in sortie and "Traoré" not in sortie and "[numéro]" in sortie and "[e-mail]" in sortie
    assert W.anonymiser("Le bilan coûte 5000 F.") == "Le bilan coûte 5000 F."        # un tarif n'est pas une donnée personnelle


def test_reponse_utile():
    assert W.est_reponse_utile("Quel est le prix du bilan sanguin ?", "Le bilan sanguin complet coûte 5 000 F et les résultats sont prêts en 24 h.")
    assert not W.est_reponse_utile("Quel est le prix du bilan sanguin ?", "Merci")
    assert not W.est_reponse_utile("ok", "Le bilan sanguin complet coûte 5 000 F et les résultats sont prêts en 24 h.")


def test_blocs_legende_et_contenu():
    m = {"media_caption": "Résultats de mars", "body": "[document envoyé]"}
    blocs = W.blocs_de_message(m, "Glycémie 0,9 g/L. " * 3)
    assert blocs[0] == "Résultats de mars" and "Glycémie" in blocs[1] and all("[document" not in b for b in blocs)


def test_filtre_qdrant():
    f = W.filtre_qdrant(phone_digits="22670000000", sans_nature="qr")
    assert f.must and f.must[0].key == "phone_digits" and f.must_not and f.must_not[0].key == "nature"
    assert W.filtre_qdrant() is None


def test_indexation_de_bout_en_bout_avec_qdrant_en_memoire(monkeypatch):
    """Indexeur complet (Qdrant en mémoire, vecteurs factices) : messages indexés, vocal ignoré, question/réponse candidate anonymisée,
    curseur avancé, relance sans doublon, validation vers une collection de la base de connaissances."""
    import asyncio
    import hashlib
    from mongomock_motor import AsyncMongoMockClient
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams
    from routes import qdrant_rag as Q

    def faux_vecteur(t):
        h = hashlib.sha256(t.lower().encode()).digest()
        return [((h[i % 32] / 255.0) - 0.5) for i in range(384)]

    qd = QdrantClient(":memory:")
    qd.create_collection("base_kb", vectors_config=VectorParams(size=384, distance=Distance.COSINE))

    class ClientInference:
        """Simule Qdrant Cloud Inference : transforme les « Document » en vecteurs (ici factices) avant de les confier à Qdrant en mémoire."""
        def __getattr__(self, nom):
            return getattr(qd, nom)

        def upsert(self, collection_name, points, **k):
            for p in points:
                if hasattr(p.vector, "text"):
                    assert p.vector.model == W.MODELE_INFERENCE and p.vector.text.startswith("passage: ")
                    p.vector = faux_vecteur(p.vector.text)
            return qd.upsert(collection_name, points=points, **k)

        def query_points(self, collection_name, query=None, **k):
            if hasattr(query, "text"):
                assert query.model == W.MODELE_INFERENCE and query.text.startswith("query: ")
                query = faux_vecteur(query.text.replace("query: ", "passage: ", 1))
            return qd.query_points(collection_name, query=query, **k)

    async def creds(*a, **k):
        return "http://x", "k"

    monkeypatch.setattr(Q, "_resolve_credentials", creds)
    monkeypatch.setattr(W, "_creer_client_inference", lambda url, cle: ClientInference())

    async def scenario():
        db = AsyncMongoMockClient()["t"]
        await db.settings.insert_one({"_id": "global", "qdrant_enabled": True, "wa_memoire_active": True})
        tel = "22670000000"
        await db.whatsapp_messages.insert_many([
            {"id": "m1", "direction": "inbound", "phone_digits": tel, "message_type": "text", "contact_name": "Awa Traoré", "client_id": "c1",
             "body": "Bonjour, quel est le prix du bilan sanguin complet ? Mon numéro est 70 12 34 56.", "created_at": "2026-10-29T10:00:00+00:00"},
            {"id": "m2", "direction": "inbound", "phone_digits": tel, "message_type": "audio", "media_kind": "audio", "media_id": "a1",
             "body": "[audio]", "client_id": "c1", "created_at": "2026-10-29T10:00:30+00:00"},
            {"id": "m3", "direction": "outbound", "phone_digits": tel, "message_type": "text", "sender_id": "u1", "sender_label": "Dr Zongo",
             "contact_name": "Awa Traoré", "client_id": "c1", "created_at": "2026-10-29T10:01:00+00:00",
             "body": "Bonjour Awa, le bilan sanguin complet coûte 5 000 F et les résultats sont disponibles en 24 h."},
            {"id": "m4", "direction": "outbound", "phone_digits": tel, "message_type": "text", "ai_generated": True, "auto_reply": True,
             "client_id": "c1", "body": "Réponse automatique de l'IA", "created_at": "2026-10-29T10:01:30+00:00"},
        ])
        await db.settings.insert_one({"_id": W.ETAT_ID, "curseur": "2026-10-29T09:00:00+00:00"})
        bilan = await W.indexer_lot(db)
        assert bilan["lus"] == 4 and bilan["indexes"] == 2 and bilan["ignores"] == 2 and bilan.get("candidats") == 1, bilan
        etat = await db.settings.find_one({"_id": W.ETAT_ID})
        assert etat["curseur"] == "2026-10-29T10:01:30+00:00"
        total = qd.count(W.COLLECTION).count
        # relance : plus rien à lire, aucun doublon
        assert (await W.indexer_lot(db))["lus"] == 0 and qd.count(W.COLLECTION).count == total
        # recherche par numéro : les messages d'origine, sans les candidates
        trouves = await W.rechercher(db, requete="prix du bilan sanguin", phone_digits=tel)
        assert trouves and all(h["nature"] != "qr" for h in trouves) and not await W.rechercher(db, requete="prix", phone_digits="22600000000")
        # candidate : anonymisée
        pts, _ = qd.scroll(W.COLLECTION, scroll_filter=W.filtre_qdrant(nature="qr", statut="propose"), with_payload=True)
        assert len(pts) == 1
        pl = pts[0].payload
        assert "70 12 34 56" not in pl["question"] and "Awa" not in pl["reponse"] and "5 000 F" in pl["reponse"]
        return db, pts[0].id

    db, pid = asyncio.run(scenario())

    async def validation():
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        async def liste(_db):
            return [{"name": "base_kb"}]

        async def ecrire(_db, *, collection, docs):
            qd.upsert(collection, points=[__import__("qdrant_client.models", fromlist=["PointStruct"]).PointStruct(
                id=W.identifiant_point("kb", 0), vector=faux_vecteur(docs[0]["text"]), payload={"text": docs[0]["text"]})])
            return {"ok": True}

        monkeypatch.setattr(Q, "list_collections", liste)
        monkeypatch.setattr(Q, "upsert_text_documents", ecrire)
        app = FastAPI()
        app.include_router(W.make_router(db=db, get_current_user=lambda: {"role": "admin", "email": "a@x"}), prefix="/api")
        c = TestClient(app)
        assert c.get("/api/admin/wa-memoire/candidates").json()["items"][0]["id"] == str(pid)
        assert c.post(f"/api/admin/wa-memoire/candidates/{pid}/valider", json={"collection": W.COLLECTION}).status_code == 422
        # Petit serveur : le modèle local de la base de connaissances ne se charge pas → message clair (503), la candidate reste à valider
        async def modele_indisponible(_db, *, collection, docs):
            raise RuntimeError("Recherche Qdrant suspendue : mémoire du serveur insuffisante")

        monkeypatch.setattr(Q, "upsert_text_documents", modele_indisponible)
        refus = c.post(f"/api/admin/wa-memoire/candidates/{pid}/valider", json={"collection": "base_kb"})
        assert refus.status_code == 503 and "recalculer" in refus.json()["detail"]
        assert len(c.get("/api/admin/wa-memoire/candidates").json()["items"]) == 1
        monkeypatch.setattr(Q, "upsert_text_documents", ecrire)
        assert c.post(f"/api/admin/wa-memoire/candidates/{pid}/valider", json={"collection": "base_kb"}).status_code == 200
        assert qd.count("base_kb").count == 1 and c.get("/api/admin/wa-memoire/candidates").json()["items"] == []
        assert len(c.get("/api/admin/wa-memoire/candidates?statut=valide").json()["items"]) == 1

    asyncio.run(validation())
