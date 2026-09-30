"""Lot 46 — Migration vers Render : références de fichiers traduites, absents à la source (404)
séparés des vraies erreurs, nouvelles tentatives (429/5xx), export CSV des échecs.
MongoDB simulé (mongomock_motor), stockage Emergent et R2 simulés.
Lancer : cd backend && python -m pytest tests/test_migration_render_lot46.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
httpx = pytest.importorskip("httpx")

# db.py lit ces variables à l'import (aucune connexion n'est ouverte)
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot46")

import routes.migration_render as mr  # noqa: E402


def erreur_http(code: int) -> httpx.HTTPStatusError:
    """Même exception que storage.fetch_bytes (raise_for_status)."""
    requete = httpx.Request("GET", "https://stockage.test/objects/x")
    return httpx.HTTPStatusError(f"{code}", request=requete, response=httpx.Response(code, request=requete))


class FauxR2:
    """Bucket R2 en mémoire."""

    def __init__(self):
        self.objets = {}

    def put_object(self, Bucket, Key, Body, **_):  # noqa: N803 (signature boto3)
        self.objets[Key] = Body

    def head_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.objets:
            raise KeyError(Key)
        return {}


@pytest.fixture()
def env(monkeypatch, tmp_path):
    base = mongomock_motor.AsyncMongoMockClient()["sawali_lot46"]
    monkeypatch.setattr(mr, "db", base)
    monkeypatch.setattr(mr, "ATTENTES_ESSAIS", (0, 0))  # pas d'attente réelle entre les essais
    monkeypatch.setattr(mr, "DOSSIER_UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(mr, "DOSSIER_SNAPSHOTS", tmp_path / "snapshots")
    appels = {}

    # Faux stockage Emergent : « absent » -> 404, « lent » -> 503 au 1er essai puis succès,
    # « sature » -> 429 à chaque essai ; les autres objets existent.
    def faux_fetch(chemin):
        appels[chemin] = appels.get(chemin, 0) + 1
        if "absent" in chemin:
            raise erreur_http(404)
        if "lent" in chemin and appels[chemin] == 1:
            raise erreur_http(503)
        if "sature" in chemin:
            raise erreur_http(429)
        return f"contenu:{chemin}".encode(), "application/octet-stream"

    monkeypatch.setattr(mr, "_lire_objet_emergent", faux_fetch)
    return base, appels


def test_traduction_des_references():
    fichiers = {"u1": "sawali/files/u1.pdf", "u2": None}
    # Identifiant de la collection files (avec ou sans extension) -> storage_path
    assert mr._traduire_reference("u1.pdf", fichiers) == ("sawali/files/u1.pdf", "traduit")
    assert mr._traduire_reference("u1", fichiers) == ("sawali/files/u1.pdf", "traduit")
    # Fichier seulement sur le disque, fichier IA (disque), identifiant inconnu
    assert mr._traduire_reference("u2.jpg", fichiers) == (None, "disque")
    assert mr._traduire_reference("ai/tenant/img.png", fichiers) == (None, "disque")
    assert mr._traduire_reference("zzz", fichiers) == (None, "inconnu")
    # Chemin du stockage objet : gardé, décodé, sans paramètres ni ponctuation finale
    assert mr._traduire_reference("sawali/doc/é%20t.png?v=2#x", fichiers) == ("sawali/doc/é t.png", "chemin")
    assert mr._traduire_reference("/sawali/a.pdf.", fichiers) == ("sawali/a.pdf", "chemin")


def test_extraction_regex_et_journaux():
    docs = [{"_id": 1, "html": '<a href="/api/files/u1.pdf">x</a>', "url": "/api/files/sawali/ré sumé.pdf",
             "storage_path": "files/abc.pdf"}]
    _, refs = mr._serialiser_lot(docs)
    # Le guillemet échappé du JSON (\") n'est pas capturé ; l'accent est conservé
    assert ("api", "u1.pdf") in refs
    assert ("api", "sawali/ré") in refs  # l'espace brut termine l'URL
    assert ("stockage", "files/abc.pdf") in refs
    # Collections de journaux : aucune référence relevée
    assert mr._serialiser_lot(docs, extraire=False)[1] == set()
    assert mr._sans_references("api_traces") and mr._sans_references("nouveau_journal_log")
    assert not mr._sans_references("messages")


def test_chemins_emergent_dedoublonnes(env):
    base, _ = env

    async def scenario():
        await base.files.insert_many([{"id": "u1", "storage_path": "sawali/files/u1.pdf"},
                                      {"id": "u2", "stored_name": "u2.jpg"}])
        await base.stored_objects.insert_one({"storage_path": "sawali/img/a.png"})
        refs = {("api", "u1.pdf"): "messages", ("api", "ai/t/x.png"): "ia", ("api", "u2"): "docs",
                ("api", "inconnu"): "docs", ("api", "sawali/img/a.png?v=1"): "docs",
                ("stockage", "img/a.png"): "docs", ("api", "sawali/n%20ouveau.pdf"): "docs"}
        return await mr._chemins_emergent(refs)

    chemins, ignores = asyncio.run(scenario())
    assert chemins == {"sawali/img/a.png": "stored_objects", "sawali/files/u1.pdf": "files.storage_path",
                       "sawali/n ouveau.pdf": "docs (/api/files)"}
    assert ignores == {"disque": 2, "inconnu": 1}


def test_absent_404_classe_a_part_et_503_reessaye(env):
    base, appels = env
    r2 = FauxR2()

    async def scenario():
        await base.stored_objects.insert_many([{"storage_path": "sawali/ok.png"},
                                               {"storage_path": "sawali/absent.png"},
                                               {"storage_path": "sawali/lent.png"}])
        # Référence /api/files/<id> dans une collection métier, et une autre dans un journal (ignorée)
        await base.files.insert_one({"id": "u1", "storage_path": "sawali/files/u1.pdf"})
        await base.messages.insert_one({"piece": "/api/files/u1.pdf"})
        await base.api_traces.insert_one({"url": "/api/files/sawali/absent-journal.png"})
        await base.migration_jobs.insert_one({"id": "J", "statut": "EN_COURS", "journal": [],
                                              "cible": {"prefixe": "migration-test"}})
        cible = mr.Cible(r2_account_id="acct", r2_access_key_id="cle1", r2_secret_access_key="cle2",
                         r2_bucket="seau", copier_base=False, copier_fichiers=True, sauver_secrets=False)
        # Fichiers seuls (comme « Réessayer les échecs ») : la base est relue, pas recopiée
        await mr._executer("J", cible, None, r2, "migration-test")
        job = await base.migration_jobs.find_one({"id": "J"}, {"_id": 0})
        echecs = await base.migration_echecs.find({"job_id": "J"}, {"_id": 0}).to_list(None)
        csv = await mr.exporter_echecs("J", {"role": "admin"})
        return job, echecs, csv

    job, echecs, reponse = asyncio.run(scenario())
    # 503 puis succès : réessayé et copié
    assert appels["sawali/lent.png"] == 2
    assert "migration-test/objets/sawali/lent.png" in r2.objets
    # 404 : un seul essai, compté « absent », pas en erreur -> statut Terminée
    assert appels["sawali/absent.png"] == 1
    assert job["fichiers_copies"] == 3 and job["fichiers_absents"] == 1 and job.get("fichiers_echecs", 0) == 0
    assert job["statut"] == "TERMINEE"
    assert job["echecs_par_cause"] == {"absent à la source (HTTP 404)": 1}
    assert job["absents_fichiers"][0]["source"] == "sawali/absent.png"
    # Le journal api_traces n'a pas ajouté de référence
    assert "sawali/absent-journal.png" not in appels
    assert echecs[0]["absent"] is True and echecs[0]["code"] == 404 and echecs[0]["origine"] == "stored_objects"
    # Manifeste : code, cause et origine enregistrés
    import json
    manifeste = json.loads(r2.objets["migration-test/manifest.json"])
    lent = next(f for f in manifeste["fichiers"] if f["source"] == "sawali/lent.png")
    assert lent["ok"] and lent["essais"] == 2
    # Export CSV : BOM UTF-8, séparateur « ; »
    texte = reponse.body.decode("utf-8")
    assert texte.startswith("﻿") and texte.splitlines()[0].lstrip("﻿").startswith("type;source;origine")
    assert "absent à la source;sawali/absent.png;stored_objects" in texte


def test_429_persistant_vraie_erreur(env):
    base, appels = env
    r2 = FauxR2()

    async def scenario():
        await base.stored_objects.insert_one({"storage_path": "sawali/sature.png"})
        await base.migration_jobs.insert_one({"id": "K", "statut": "EN_COURS", "journal": []})
        cible = mr.Cible(r2_account_id="acct", r2_access_key_id="cle1", r2_secret_access_key="cle2",
                         r2_bucket="seau", copier_base=False, copier_fichiers=True, sauver_secrets=False)
        await mr._executer("K", cible, None, r2, "p")
        return await base.migration_jobs.find_one({"id": "K"}, {"_id": 0})

    job = asyncio.run(scenario())
    assert appels["sawali/sature.png"] == mr.ESSAIS_MAX
    assert job["fichiers_echecs"] == 1 and job["statut"] == "TERMINEE_AVEC_ERREURS"
    assert job["echecs_fichiers"][0]["code"] == 429 and job["echecs_fichiers"][0]["cause"] == "trop de requêtes"
