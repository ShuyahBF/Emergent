"""Lot 348 — recalcul de la base de connaissances avec le modèle de Qdrant : copie sans risque, bascule réversible, recherche sans modèle local."""
import asyncio
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routes import qdrant_migration_e5 as M  # noqa: E402
from routes import qdrant_rag as Q  # noqa: E402


def faux_vecteur(t):
    h = hashlib.sha256(t.lower().encode()).digest()
    return [((h[i % 32] / 255.0) - 0.5) for i in range(384)]


def test_moteur_par_collection_et_texte_a_vectoriser():
    s = {"qdrant_collection_settings": {"a": {"moteur": "inference"}, "b": {}}}
    assert Q.moteur_de(s, "a") == "inference" and Q.moteur_de(s, "b") == "local" and Q.moteur_de(s, "zzz") == "local" and Q.moteur_de({}, "a") == "local"
    assert M.texte_a_vectoriser({"text": " Bonjour "}) == "Bonjour"
    image = {"kind": "image", "title": "Écran caisse", "caption": "Légende", "visual_summary": "Un écran", "ocr_text": "Total 500", "text": "x"}
    assert M.texte_a_vectoriser(image) == "Écran caisse\nLégende\nUn écran\nTotal 500"
    assert M.texte_a_vectoriser({"kind": "text", "text": ""}) == ""
    assert M.nom_copie("kb") == "kb-e5"


def test_recalcul_copie_bascule_et_recherche_sans_modele_local(monkeypatch):
    from mongomock_motor import AsyncMongoMockClient
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    qd = QdrantClient(":memory:")

    class ClientInference:
        """Simule Qdrant Cloud Inference : transforme les « Document » en vecteurs factices avant de les confier à Qdrant en mémoire."""
        def __getattr__(self, nom):
            return getattr(qd, nom)

        def upsert(self, collection_name, points, **k):
            for p in points:
                if hasattr(p.vector, "text"):
                    assert p.vector.model == Q.MODELE_E5 and p.vector.text.startswith("passage: ")
                    p.vector = faux_vecteur(p.vector.text.replace("passage: ", "", 1))
            return qd.upsert(collection_name, points=points, **k)

        def query_points(self, collection_name, query=None, **k):
            if hasattr(query, "text"):
                assert query.model == Q.MODELE_E5 and query.text.startswith("query: ")
                query = faux_vecteur(query.text.replace("query: ", "", 1))
            return qd.query_points(collection_name, query=query, **k)

    async def creds(*a, **k):
        return "http://x", "k"

    monkeypatch.setattr(Q, "_resolve_credentials", creds)
    monkeypatch.setattr(Q, "_make_client_ia", lambda url, cle: ClientInference())
    monkeypatch.setattr(Q, "embeddings_autorises", lambda: False)       # petit serveur : AUCUN modèle local
    monkeypatch.setattr(Q, "_vider_cache_liste", lambda: None)

    async def scenario():
        db = AsyncMongoMockClient()["t"]
        await db.settings.insert_one({"_id": "global", "qdrant_enabled": True, "qdrant_collection_settings": {"kb": {"enabled_for_liluvine": True}}})
        qd.create_collection("kb", vectors_config=VectorParams(size=384, distance=Distance.COSINE))
        qd.upsert("kb", points=[
            PointStruct(id=1, vector=faux_vecteur("ancien 1"), payload={"kind": "text", "title": "Garde", "text": "La pharmacie de garde ouvre à 20h"}),
            PointStruct(id=2, vector=faux_vecteur("ancien 2"), payload={"kind": "text", "title": "Tarif", "text": "Le bilan coûte 5000 F"}),
            PointStruct(id=3, vector=faux_vecteur("ancien 3"), payload={"kind": "image", "title": "Écran", "caption": "Caisse", "image_url": "/f/x.png", "text": "Caisse"}),
            PointStruct(id=4, vector=faux_vecteur("ancien 4"), payload={"kind": "text", "text": ""}),
        ])
        # 1. recalcul : copie « kb-e5 », originale intacte, point sans texte compté « sauté »
        await M.recalculer(db, "kb")
        suivi = (await db.settings.find_one({"_id": M.ETAT_ID}))["kb"]
        assert suivi["statut"] == "copie_prete" and suivi["faits"] == 3 and suivi["saute"] == 1 and suivi["total"] == 4, suivi
        assert qd.count("kb").count == 4 and qd.count("kb-e5").count == 3
        assert {p.id for p in qd.scroll("kb-e5", limit=10)[0]} == {1, 2, 3}
        copie = qd.retrieve("kb-e5", ids=[3])[0].payload
        assert copie["image_url"] == "/f/x.png" and copie["kind"] == "image"
        meta = (await db.settings.find_one({"_id": "global"}))["qdrant_collection_settings"]
        assert meta["kb-e5"]["moteur"] == "inference" and meta["kb-e5"]["enabled_for_liluvine"] is False and meta["kb"]["enabled_for_liluvine"] is True
        # relancer ne crée aucun doublon
        await M.recalculer(db, "kb")
        assert qd.count("kb-e5").count == 3
        # 2. avant la bascule, Liluvine n'a plus de recherche (modèle local suspendu) ; après, elle retrouve le contenu SANS modèle local
        assert await Q.build_rag_context(db, query="La pharmacie de garde ouvre à 20h") == ""
        await M.basculer(db, "kb", True)
        meta = (await db.settings.find_one({"_id": "global"}))["qdrant_collection_settings"]
        assert meta["kb-e5"]["enabled_for_liluvine"] is True and meta["kb"]["enabled_for_liluvine"] is False
        contexte = await Q.build_rag_context(db, query="La pharmacie de garde ouvre à 20h")
        assert "pharmacie de garde" in contexte
        # 3. ajout d'une entrée dans la collection recalculée : vecteur calculé par Qdrant (aucun modèle local)
        await Q.upsert_text_documents(db, collection="kb-e5", docs=[{"title": "Horaires", "text": "Ouvert de 8h à 18h", "source": "test"}])
        assert qd.count("kb-e5").count == 4
        assert (await Q.search_points(db, collection="kb-e5", query="Ouvert de 8h à 18h"))["items"][0]["text"] == "Ouvert de 8h à 18h"
        # 4. annulation : l'original est remis
        await M.basculer(db, "kb", False)
        meta = (await db.settings.find_one({"_id": "global"}))["qdrant_collection_settings"]
        assert meta["kb"]["enabled_for_liluvine"] is True and meta["kb-e5"]["enabled_for_liluvine"] is False

    asyncio.run(scenario())


def test_bascule_refusee_sans_copie_prete(monkeypatch):
    from fastapi import HTTPException
    from mongomock_motor import AsyncMongoMockClient

    async def scenario():
        db = AsyncMongoMockClient()["t"]
        await db.settings.insert_one({"_id": "global", "qdrant_collection_settings": {"kb": {"enabled_for_liluvine": True}}})
        try:
            await M.basculer(db, "kb", True)
            raise AssertionError("la bascule sans copie doit être refusée")
        except HTTPException as exc:
            assert exc.status_code == 409

    asyncio.run(scenario())
