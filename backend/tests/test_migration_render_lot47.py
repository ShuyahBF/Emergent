"""Lot 47 — Migration vers Render : fichiers copiés EN FLUX (sans tout charger en mémoire),
signe de vie pendant les longs fichiers, durée maximale par fichier, option « Copier les médias ».
MongoDB simulé (mongomock_motor), stockage Emergent (flux httpx) et R2 simulés.
Lancer : cd backend && python -m pytest tests/test_migration_render_lot47.py -q
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
httpx = pytest.importorskip("httpx")

# db.py lit ces variables à l'import (aucune connexion n'est ouverte)
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot47")

import routes.migration_render as mr  # noqa: E402
import storage  # noqa: E402


class FauxR2:
    """Bucket R2 en mémoire. Retient la façon dont chaque objet a été envoyé."""

    def __init__(self):
        self.objets, self.modes, self.types = {}, {}, {}

    def put_object(self, Bucket, Key, Body, **_):  # noqa: N803 (signature boto3)
        self.objets[Key], self.modes[Key] = Body, "put_object"

    def upload_fileobj(self, Fileobj, Bucket, Key, ExtraArgs=None, Callback=None):  # noqa: N803
        # Lu par morceaux, comme boto3 (envoi en plusieurs parties)
        morceaux = []
        for morceau in iter(lambda: Fileobj.read(256 * 1024), b""):
            morceaux.append(morceau)
            if Callback:
                Callback(len(morceau))
        self.objets[Key], self.modes[Key] = b"".join(morceaux), "upload_fileobj"
        self.types[Key] = (ExtraArgs or {}).get("ContentType")

    def upload_file(self, Filename, Bucket, Key, ExtraArgs=None, Callback=None):  # noqa: N803
        self.objets[Key], self.modes[Key] = Path(Filename).read_bytes(), "upload_file"

    def head_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.objets:
            raise KeyError(Key)
        return {}

    def head_bucket(self, Bucket):  # noqa: N803
        return {}


def cible(**options) -> "mr.Cible":
    return mr.Cible(r2_account_id="acct", r2_access_key_id="cle1", r2_secret_access_key="cle2", r2_bucket="seau",
                    copier_base=False, copier_fichiers=True, sauver_secrets=False, **options)


@pytest.fixture()
def base(monkeypatch, tmp_path):
    b = mongomock_motor.AsyncMongoMockClient()["sawali_lot47"]
    monkeypatch.setattr(mr, "db", b)
    monkeypatch.setattr(mr, "ATTENTES_ESSAIS", (0, 0))
    monkeypatch.setattr(mr, "DOSSIER_UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(mr, "DOSSIER_SNAPSHOTS", tmp_path / "snapshots")
    return b


def test_gros_fichier_lu_en_flux_et_sha256(base, monkeypatch, tmp_path):
    """Un objet de 6 Mo arrive en plusieurs morceaux par httpx.stream (transport simulé), passe par un
    fichier temporaire puis upload_fileobj ; storage.fetch_bytes (tout en mémoire) n'est jamais appelé."""
    contenu = os.urandom(6 * 1024 * 1024)
    monkeypatch.setattr(mr, "MORCEAU", 256 * 1024)
    monkeypatch.setattr(mr, "GROS_FICHIER", 1024 * 1024)
    # Stockage Emergent prêt, clé connue ; la lecture « tout en mémoire » est interdite
    monkeypatch.setattr(storage, "_ensure_ready", lambda: True)
    monkeypatch.setattr(storage, "_storage_key", "cle-test")
    monkeypatch.setattr(storage, "fetch_bytes", lambda *_: pytest.fail("fetch_bytes ne doit plus être utilisé"))
    vus = {}

    class FluxMorceaux(httpx.SyncByteStream):
        def __iter__(self):
            for i in range(0, len(contenu), 300 * 1024):
                yield contenu[i:i + 300 * 1024]

    def repondre(requete: httpx.Request) -> httpx.Response:
        vus["url"], vus["cle"] = str(requete.url), requete.headers.get("X-Storage-Key")
        return httpx.Response(200, headers={"Content-Type": "application/pdf", "Content-Length": str(len(contenu))},
                              stream=FluxMorceaux())

    def faux_stream(methode, url, headers=None, timeout=None):
        vus["timeout"] = timeout
        return httpx.Client(transport=httpx.MockTransport(repondre)).stream(methode, url, headers=headers)

    monkeypatch.setattr(httpx, "stream", faux_stream)
    # Un gros fichier local aussi : envoyé directement depuis le disque
    (tmp_path / "uploads").mkdir()
    local = os.urandom(2 * 1024 * 1024)
    (tmp_path / "uploads" / "scan.pdf").write_bytes(local)
    r2 = FauxR2()

    async def scenario():
        await base.stored_objects.insert_one({"storage_path": "sawali/gros.pdf"})
        await base.migration_jobs.insert_one({"id": "G", "statut": "EN_COURS", "journal": []})
        await mr._executer("G", cible(), None, r2, "p")
        return await base.migration_jobs.find_one({"id": "G"}, {"_id": 0})

    job = asyncio.run(scenario())
    assert vus["url"].endswith("/objects/sawali/gros.pdf") and vus["cle"] == "cle-test"
    assert vus["timeout"].read == mr.DELAI_LECTURE  # délai de lecture explicite
    assert r2.objets["p/objets/sawali/gros.pdf"] == contenu
    assert r2.modes["p/objets/sawali/gros.pdf"] == "upload_fileobj"
    assert r2.types["p/objets/sawali/gros.pdf"] == "application/pdf"
    assert r2.objets["p/uploads/scan.pdf"] == local and r2.modes["p/uploads/scan.pdf"] == "upload_file"
    manifeste = {f["source"]: f for f in json.loads(r2.objets["p/manifest.json"])["fichiers"]}
    assert manifeste["sawali/gros.pdf"]["sha256"] == hashlib.sha256(contenu).hexdigest()
    assert manifeste["sawali/gros.pdf"]["octets"] == len(contenu)
    assert manifeste[str(tmp_path / "uploads" / "scan.pdf")]["sha256"] == hashlib.sha256(local).hexdigest()
    assert job["statut"] == "TERMINEE" and job["fichiers_copies"] == 2
    # Fichiers locaux d'abord, puis ligne de journal avant chaque gros fichier
    journal = "\n".join(job["journal"])
    assert "Fichier 1/2 : uploads/scan.pdf (2.0 Mo)" in journal
    assert "Fichier 2/2 : sawali/gros.pdf (6.0 Mo)" in journal


def test_battement_pendant_un_fichier_lent(base, monkeypatch):
    """Pendant un fichier long, le signe de vie périodique publie le fichier en cours et les octets reçus."""
    monkeypatch.setattr(mr, "BATTEMENT_FICHIER", 0.05)
    publies = []
    battement_origine = mr._battement

    async def espion(job_id, en_cours=None, force=False, **_):
        publies.append((force, dict(en_cours or {})))
        await battement_origine(job_id, en_cours, force)

    monkeypatch.setattr(mr, "_battement", espion)

    @contextmanager
    def flux_lent(chemin):
        def morceaux():
            for _ in range(8):
                time.sleep(0.05)  # lecture lente
                yield b"x" * 1000
        yield morceaux(), "application/octet-stream", 8000

    monkeypatch.setattr(mr, "_flux_objet_emergent", flux_lent)
    r2 = FauxR2()

    async def scenario():
        await base.stored_objects.insert_one({"storage_path": "sawali/lent.bin"})
        await base.migration_jobs.insert_one({"id": "B", "statut": "EN_COURS", "journal": []})
        await mr._executer("B", cible(), None, r2, "p")
        return await base.migration_jobs.find_one({"id": "B"}, {"_id": 0})

    job = asyncio.run(scenario())
    pendant = [e for force, e in publies if force and e.get("fichier") == "sawali/lent.bin"
               and e.get("phase") == "lecture" and 0 < e.get("recus", 0) < 8000]
    assert pendant, publies
    assert pendant[0]["taille"] == 8000 and pendant[0]["total"] == 1
    assert job["statut"] == "TERMINEE" and r2.objets["p/objets/sawali/lent.bin"] == b"x" * 8000


def test_duree_max_depassee_puis_fichier_suivant(base, monkeypatch):
    """Un objet qui n'en finit pas est abandonné à DUREE_MAX_FICHIER (« délai dépassé », sans nouvel essai),
    puis le fichier suivant est copié normalement."""
    monkeypatch.setattr(mr, "DUREE_MAX_FICHIER", 0.3)
    appels = {}

    @contextmanager
    def flux(chemin):
        appels[chemin] = appels.get(chemin, 0) + 1
        if "infini" in chemin:
            def sans_fin():
                while True:
                    time.sleep(0.05)
                    yield b"y" * 100
            yield sans_fin(), "application/octet-stream", None  # taille inconnue
        else:
            yield iter([b"ok"]), "application/pdf", 2

    monkeypatch.setattr(mr, "_flux_objet_emergent", flux)
    r2 = FauxR2()

    async def scenario():
        await base.stored_objects.insert_many([{"storage_path": "sawali/infini.bin"},
                                               {"storage_path": "sawali/suivant.pdf"}])
        await base.migration_jobs.insert_one({"id": "D", "statut": "EN_COURS", "journal": []})
        debut = time.monotonic()
        await mr._executer("D", cible(), None, r2, "p")
        duree = time.monotonic() - debut
        return await base.migration_jobs.find_one({"id": "D"}, {"_id": 0}), duree

    job, duree = asyncio.run(scenario())
    assert duree < 3
    assert appels["sawali/infini.bin"] == 1  # durée épuisée : pas de nouvel essai
    assert "p/objets/sawali/infini.bin" not in r2.objets
    assert r2.objets["p/objets/sawali/suivant.pdf"] == b"ok"
    assert job["fichiers_copies"] == 1 and job["fichiers_echecs"] == 1
    assert job["statut"] == "TERMINEE_AVEC_ERREURS"
    assert job["echecs_fichiers"][0]["cause"] == "délai dépassé"
    assert "durée maximale" in job["echecs_fichiers"][0]["erreur"]
    assert "Fichier 1/2 : sawali/infini.bin (taille inconnue)" in "\n".join(job["journal"])


def test_medias_ignores_par_option_et_repris(base, monkeypatch, tmp_path):
    """« Copier les médias » décoché : .mp4 (local) et .ogg (Emergent) ignorés et comptés à part, un objet
    sans extension annoncé audio/* ignoré sans être lu, le .pdf copié ; le choix est repris par
    « Réessayer les échecs »."""
    lus = []

    @contextmanager
    def flux(chemin):
        if chemin.endswith("sans-extension"):
            def jamais():
                lus.append(chemin)
                yield b"son"
            yield jamais(), "audio/mpeg", 3
        else:
            lus.append(chemin)
            yield iter([b"pdf"]), "application/pdf", 3

    monkeypatch.setattr(mr, "_flux_objet_emergent", flux)
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "clip.MP4").write_bytes(b"video")
    r2 = FauxR2()
    monkeypatch.setattr(mr, "_client_r2", lambda *_: r2)

    async def scenario():
        await base.stored_objects.insert_many([{"storage_path": "sawali/voix.ogg"},
                                               {"storage_path": "sawali/doc.pdf"},
                                               {"storage_path": "sawali/sans-extension"}])
        await base.migration_jobs.insert_one({"id": "M", "statut": "EN_COURS", "journal": [],
                                              "options": {"medias": False}, "cible": {"prefixe": "p"}})
        await mr._executer("M", cible(copier_medias=False), None, r2, "p")
        job = await base.migration_jobs.find_one({"id": "M"}, {"_id": 0})
        echecs = await base.migration_echecs.count_documents({})
        csv = (await mr.exporter_echecs("M", {"role": "admin"})).body.decode("utf-8")
        # « Réessayer les échecs » sans préciser l'option : le choix de la sauvegarde reprise est conservé
        await base.migration_jobs.update_one({"id": "M"}, {"$set": {"statut": "INTERROMPUE"}})
        nouveau = await mr.reessayer_echecs("M", cible(), {"email": "admin@test"})
        await mr._TACHES_PAR_JOB[nouveau["id"]]
        repris = await base.migration_jobs.find_one({"id": nouveau["id"]}, {"_id": 0})
        return job, echecs, csv, repris

    job, echecs, csv, repris = asyncio.run(scenario())
    assert job["fichiers_medias_ignores"] == 3 and job["fichiers_copies"] == 1
    assert job.get("fichiers_echecs", 0) == 0 and job["statut"] == "TERMINEE"
    assert "p/objets/sawali/doc.pdf" in r2.objets
    assert not any(k.endswith(("voix.ogg", "clip.MP4", "sans-extension")) for k in r2.objets)
    assert lus == ["sawali/doc.pdf"]  # ni le .ogg ni l'objet audio n'ont été téléchargés
    # Jamais comptés comme erreurs : ni dans migration_echecs, ni dans l'export CSV, ni par cause
    assert echecs == 0 and csv.count("\n") == 1 and not job.get("echecs_par_cause")
    manifeste = json.loads(r2.objets["p/manifest.json"])["fichiers"]
    assert sum(f["cause"] == mr.CAUSE_MEDIA for f in manifeste) == 3
    assert "Médias : ignorés (3)" in "\n".join(job["journal"])
    # Reprise : option conservée, médias toujours ignorés, le .pdf déjà présent est sauté
    assert repris["options"]["medias"] is False and repris["fichiers_medias_ignores"] == 3
    assert repris["statut"] == "TERMINEE"


def test_veilleur_epargne_une_tache_vivante(base, monkeypatch):
    """Une sauvegarde silencieuse dont la tâche tourne encore ici n'est pas déclarée interrompue ;
    une sauvegarde inconnue de ce processus l'est après SILENCE_MAX s."""
    ancien = "2020-01-01T00:00:00+00:00"

    async def scenario():
        await base.migration_jobs.insert_many([{"id": "V", "statut": "EN_COURS", "battement": ancien, "journal": []},
                                               {"id": "X", "statut": "EN_COURS", "battement": ancien, "journal": []}])
        monkeypatch.setattr(mr, "SILENCE_MAX_TACHE_VIVANTE", 10 ** 12)
        vivante = asyncio.create_task(asyncio.sleep(10))
        monkeypatch.setitem(mr._TACHES_PAR_JOB, "V", vivante)
        await mr._marquer_orphelines()
        statuts = {j["id"]: j["statut"] async for j in base.migration_jobs.find({}, {"_id": 0})}
        vivante.cancel()
        return statuts

    assert asyncio.run(scenario()) == {"V": "EN_COURS", "X": "INTERROMPUE"}
