"""Lot 49 — Chemins portables, export / import complets chiffrés, restauration initiale,
sauvegarde automatique vers R2 (rétention 7/4/12).
MongoDB simulé (mongomock_motor), R2 simulé, e-mail simulé : aucune vraie base, aucun vrai R2.
Lancer : cd backend && python -m pytest tests/test_sauvegarde_complete_lot49.py -q
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import re
import sys
import uuid
from datetime import timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
pytest.importorskip("cryptography")

# db.py lit ces variables à l'import (aucune connexion n'est ouverte)
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot49")

from bson import Binary, Decimal128, Int64, ObjectId  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import chemins  # noqa: E402
import routes.sauvegarde_complete as sc  # noqa: E402
import sauvegarde_format as sf  # noqa: E402

PHRASE = "phrase secrète de test 2026"
JWT = "jwt-de-test-assez-long-0123456789abcdef"
MDP = "MotDePasse!2026"
UTC = timezone.utc
RE_CHEMIN_APP = re.compile(r"""["']/app(/|["'])""")  # « "/app/..." » ou « "/app" » dans le code


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def base(monkeypatch, tmp_path):
    """Base simulée vide, dossier d'export temporaire, JWT_SECRET défini, aucune phrase automatique."""
    b = mongomock_motor.AsyncMongoMockClient()[f"lot49_{uuid.uuid4().hex[:8]}"]
    monkeypatch.setattr(sc, "db", b)
    monkeypatch.setattr(sc, "EXPORTS_DIR", tmp_path)
    monkeypatch.setenv("JWT_SECRET", JWT)
    monkeypatch.delenv("SAUVEGARDE_AUTO_PHRASE", raising=False)
    for nom in ("ACCOUNT_ID", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY", "BUCKET", "PREFIXE"):
        monkeypatch.delenv(f"R2_SAUVEGARDES_{nom}", raising=False)
        monkeypatch.delenv(f"R2_STOCKS_{nom}", raising=False)
    sc._TENTATIVES.clear()
    return b


async def _remplir(b, admin_actif: bool = True):
    """Petite base représentative : types BSON variés, index unique et TTL, un admin."""
    await b.users.insert_many([
        {"id": "u-admin", "email": "admin@sawali.test", "role": "admin",
         "account_status": "active" if admin_actif else "disabled", "password_hash": auth.hash_password(MDP)},
        {"id": "u-client", "email": "client@sawali.test", "role": "client", "account_status": "active",
         "password_hash": auth.hash_password(MDP)},
    ])
    await b.users.create_index("email", unique=True)
    oid = ObjectId()
    await b["Produit"].insert_many([{
        "_id": oid if i == 0 else ObjectId(), "n": i, "quand": dt.datetime(2026, 9, 30, 12, 0, i % 60),
        "prix": Decimal128("1250.75"), "uuid": Binary(uuid.UUID(int=i).bytes, 4), "grand": Int64(2 ** 40 + i),
        "reel": 0.1 * i, "vide": None, "ok": i % 2 == 0, "liste": [1, "a", {"x": i}], "imbrique": {"a": {"b": i}},
    } for i in range(1203)])
    await b["Produit"].create_index([("n", 1)], unique=True, name="n_unique")
    await b.journal_log.insert_one({"x": 1})
    await b.settings.insert_one({"_id": "global", "smtp_password": "secret-smtp", "wa_access_token": "jeton-wa"})
    await b.migration_programmation.insert_one({"_id": "parametres", "actif": True})
    await b.sauvegardes_completes.insert_one({"_id": "etat_auto"})
    return oid


async def _exporter(b, chemin: Path, phrase: str = PHRASE, signature=None) -> dict:
    sc.db = b
    return await sc.exporter(chemin, phrase, signature if signature is not None else sf.cle_signature(JWT))


# ---------------------------------------------------------------------------
# 1. Chemins portables
# ---------------------------------------------------------------------------
def test_chemins_variable_puis_emergent_puis_projet(tmp_path, monkeypatch):
    emergent, projet = tmp_path / "app", tmp_path / "projet"
    monkeypatch.setenv("TEST_DOSSIER", str(tmp_path / "choisi"))
    assert chemins.resoudre("TEST_DOSSIER", "backend/uploads", racine_emergent=emergent,
                            racine_projet=projet) == tmp_path / "choisi"
    monkeypatch.delenv("TEST_DOSSIER")
    # Sans variable : le chemin « Emergent » quand il est utilisable (comportement inchangé)
    assert chemins.resoudre("TEST_DOSSIER", "backend/uploads", racine_emergent=emergent,
                            racine_projet=projet) == emergent / "backend/uploads"


def test_chemins_repli_quand_app_inaccessible(tmp_path, monkeypatch):
    """Comme sur Render : /app ne peut pas être créé -> dossier du projet, sans erreur."""
    fichier = tmp_path / "app"
    fichier.write_text("pas un dossier")  # mkdir impossible sous un fichier
    projet = tmp_path / "projet"
    d = chemins.resoudre(None, "backend/snapshots", racine_emergent=fichier, racine_projet=projet)
    assert d == projet / "backend/snapshots" and d.is_dir()
    # Variable inutilisable : on passe au candidat suivant au lieu d'échouer
    monkeypatch.setenv("TEST_DOSSIER", str(fichier / "x"))
    assert chemins.resoudre("TEST_DOSSIER", "backend/x", racine_emergent=fichier, racine_projet=projet) == projet / "backend/x"
    # Plus rien d'utilisable : dossier temporaire, toujours sans exception
    monkeypatch.setattr(chemins.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    d = chemins.resoudre(None, "backend/y", racine_emergent=fichier, racine_projet=fichier)
    assert d == tmp_path / "tmp" / "sawali" / "backend/y" and d.is_dir()


def test_chemins_lecture_seule_et_dossier_ia(tmp_path):
    projet = tmp_path / "projet"
    # Dossier lu seulement (memory, docs) : jamais créé ; absent partout -> chemin du projet
    assert chemins.resoudre(None, "memory", ecriture=False, racine_emergent=tmp_path / "app",
                            racine_projet=projet) == projet / "memory"
    assert not (tmp_path / "app" / "memory").exists()
    # Dossier IA : /app/backend/uploads/ai inaccessible -> UPLOAD_DIR/ai
    fichier = tmp_path / "app"
    fichier.write_text("x")
    d = chemins.resoudre(None, "backend/uploads/ai", racine_emergent=fichier, projet=False,
                         candidats_en_plus=[tmp_path / "uploads" / "ai"])
    assert d == tmp_path / "uploads" / "ai"


def test_aucun_chemin_fige_dans_le_code():
    """Plus aucun chemin « /app/... » figé dans le code du serveur (hors tests, ocr_core, commentaires)."""
    racine = Path(__file__).resolve().parents[1]
    fautifs = []
    for f in racine.rglob("*.py"):
        rel = f.relative_to(racine).as_posix()
        if rel.startswith(("tests/", "ocr_core/")) or rel == "chemins.py":
            continue
        for i, ligne in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            code = ligne.split("#", 1)[0]
            if RE_CHEMIN_APP.search(code) and not code.strip().startswith(('"""', "'''")):
                fautifs.append(f"{rel}:{i}")
    assert not fautifs, fautifs


# ---------------------------------------------------------------------------
# 2. Format chiffré
# ---------------------------------------------------------------------------
def test_aller_retour_types_conserves_et_index(base, tmp_path):
    source = mongomock_motor.AsyncMongoMockClient()["source49"]
    oid = run(_remplir(source))
    manifeste = run(_exporter(source, tmp_path / "e.sawali"))
    assert "migration_programmation" not in manifeste["collections"]
    assert "sauvegardes_completes" not in manifeste["collections"]
    assert manifeste["collections"]["Produit"]["documents"] == 1203 and manifeste["secrets_inclus"] is True
    cible = mongomock_motor.AsyncMongoMockClient()["cible49"]
    sc.db = cible
    rapport = run(sc.importer(tmp_path / "e.sawali", PHRASE, "vide"))
    assert rapport["anomalies"] == [] and rapport["signature"] == "valide"
    avant = run(source["Produit"].find_one({"_id": oid}))
    apres = run(cible["Produit"].find_one({"_id": oid}))
    assert apres == avant
    assert isinstance(apres["_id"], ObjectId) and isinstance(apres["prix"], Decimal128)
    assert isinstance(apres["quand"], dt.datetime) and isinstance(apres["grand"], Int64)
    assert run(cible["Produit"].count_documents({})) == 1203
    infos = run(cible["Produit"].index_information())
    assert infos["n_unique"]["unique"] is True
    # Les secrets de la base voyagent (fichier chiffré), sans masque
    assert run(cible.settings.find_one({"_id": "global"}))["smtp_password"] == "secret-smtp"


def test_index_texte_reconstruit_depuis_weights():
    info = {"v": 2, "key": {"_fts": "text", "_ftsx": 1, "client_id": 1}, "name": "recherche",
            "weights": {"nom": 3, "description": 1}, "default_language": "french",
            "language_override": "language", "textIndexVersion": 3}
    cles, options = sf.cles_et_options_index(info)
    assert cles == [("nom", "text"), ("description", "text"), ("client_id", 1)]
    assert options["weights"] == {"nom": 3, "description": 1} and options["name"] == "recherche"
    assert sf.cles_et_options_index({"key": {"_id": 1}, "name": "_id_"}) is None


def test_mauvaise_phrase_et_fichier_altere_rien_n_est_ecrit(base, tmp_path):
    source = mongomock_motor.AsyncMongoMockClient()["source49b"]
    run(_remplir(source))
    run(_exporter(source, tmp_path / "e.sawali"))
    sc.db = base
    with pytest.raises(sf.PhraseIncorrecte):
        run(sc.importer(tmp_path / "e.sawali", "une autre phrase longue", "vide"))
    brut = bytearray((tmp_path / "e.sawali").read_bytes())
    brut[len(brut) // 2] ^= 0x01
    (tmp_path / "altere.sawali").write_bytes(bytes(brut))
    with pytest.raises(sf.FichierAltere):
        run(sc.importer(tmp_path / "altere.sawali", PHRASE, "vide"))
    entier = (tmp_path / "e.sawali").read_bytes()
    (tmp_path / "tronque.sawali").write_bytes(entier[:len(entier) // 2])
    with pytest.raises(sf.ErreurSauvegarde):
        run(sc.importer(tmp_path / "tronque.sawali", PHRASE, "vide"))
    (tmp_path / "autre.bin").write_bytes(b"PK\x03\x04 pas un export")
    with pytest.raises(sf.ErreurSauvegarde):
        run(sc.importer(tmp_path / "autre.bin", PHRASE, "vide"))
    assert run(base.list_collection_names()) == []  # aucune écriture


def test_phrase_trop_courte_refusee(tmp_path):
    with open(tmp_path / "x", "wb") as f, pytest.raises(sf.ErreurSauvegarde):
        sf.EcrivainChiffre(f, "courte")


# ---------------------------------------------------------------------------
# 3. Modes d'import
# ---------------------------------------------------------------------------
def test_mode_vide_tolere_le_demarrage_et_refuse_les_donnees(base, tmp_path):
    source = mongomock_motor.AsyncMongoMockClient()["source49c"]
    run(_remplir(source))
    run(_exporter(source, tmp_path / "e.sawali"))
    sc.db = base
    # Ce que crée le démarrage + journaux + l'administrateur initial : toléré, puis remplacé
    run(base.settings.insert_one({"_id": "global", "recaptcha_enabled": False}))
    run(base.contents.insert_one({"slug": "home_hero"}))
    run(base.vidal_sync_config.insert_one({"_id": "x"}))
    run(base.auth_checks.insert_one({"ok": True}))
    run(base.users.insert_one({"id": "init", "email": "init@sawali.test", "role": "admin"}))
    rapport = run(sc.importer(tmp_path / "e.sawali", PHRASE, "vide"))
    assert rapport["anomalies"] == []
    assert run(base.users.find_one({"id": "init"})) is None  # comptes de la sauvegarde
    assert run(base.settings.find_one({"_id": "global"}))["wa_access_token"] == "jeton-wa"
    # Plus d'un compte : refus (il faut le mode « Remplacer »)
    with pytest.raises(sf.ErreurSauvegarde, match="compte"):
        run(sc.importer(tmp_path / "e.sawali", PHRASE, "vide"))
    # Une vraie donnée : refus, avant toute écriture
    run(base.users.delete_many({}))
    run(base.factures.insert_one({"n": 1}))
    with pytest.raises(sf.ErreurSauvegarde, match="pas vide"):
        run(sc.importer(tmp_path / "e.sawali", PHRASE, "vide"))
    assert run(base.factures.count_documents({})) == 1


def test_mode_remplacer_vide_puis_recharge_et_garde_le_reste(base, tmp_path):
    source = mongomock_motor.AsyncMongoMockClient()["source49d"]
    run(_remplir(source))
    run(_exporter(source, tmp_path / "e.sawali"))
    sc.db = base
    run(base["Produit"].insert_many([{"n": -1}, {"n": -2}]))
    run(base.autre_collection.insert_one({"garde": True}))
    rapport = run(sc.importer(tmp_path / "e.sawali", PHRASE, "remplacer"))
    assert rapport["anomalies"] == []
    assert run(base["Produit"].count_documents({})) == 1203
    assert run(base["Produit"].find_one({"n": -1})) is None
    assert run(base.autre_collection.count_documents({})) == 1  # absente de la sauvegarde : conservée


def test_controle_remplacer_mot_et_mot_de_passe(base):
    run(base.users.insert_one({"id": "a1", "email": "a@s.t", "role": "admin", "password_hash": auth.hash_password(MDP)}))
    admin = {"id": "a1", "role": "admin"}
    with pytest.raises(HTTPException) as e:
        run(sc._controle_remplacer(admin, "remplacer", MDP))
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        run(sc._controle_remplacer(admin, "REMPLACER", "mauvais"))
    assert e.value.status_code == 403
    run(sc._controle_remplacer(admin, "REMPLACER", MDP))  # accepté


# ---------------------------------------------------------------------------
# 4. Rôles (routes Admin)
# ---------------------------------------------------------------------------
def _client_http(utilisateur):
    app = FastAPI()
    app.include_router(sc.router, prefix="/api")
    app.include_router(sc.router_public, prefix="/api")
    app.dependency_overrides[auth.get_current_user] = lambda: utilisateur
    return TestClient(app)


def test_routes_admin_reservees_a_l_administrateur(base):
    for role in ("client", "superviseur", "demo"):
        http = _client_http({"id": "x", "role": role, "account_status": "active"})
        assert http.get("/api/admin/sauvegarde-complete/etat").status_code == 403
        assert http.post("/api/admin/sauvegarde-complete/export", json={"phrase": PHRASE}).status_code == 403
        assert http.get("/api/admin/sauvegarde-complete/r2").status_code == 403
        assert http.post("/api/admin/sauvegarde-complete/r2/restaurer",
                         json={"cle": "sauvegardes-completes/sawali-20260101-030000.sawali"}).status_code == 403
    http = _client_http({"id": "x", "role": "admin", "account_status": "active", "email": "a@s.t"})
    r = http.get("/api/admin/sauvegarde-complete/etat")
    assert r.status_code == 200
    assert r.json()["auto"]["active"] is False and "SAUVEGARDE_AUTO_PHRASE" in r.json()["auto"]["alerte"]
    # Phrase trop courte refusée par la validation
    assert http.post("/api/admin/sauvegarde-complete/export", json={"phrase": "court"}).status_code == 422


def test_telechargement_unique(base, tmp_path):
    run(base.sauvegardes_completes.insert_one({"_id": "t1", "id": "t1", "type": "export", "statut": "TERMINE",
                                               "fichier": "x.sawali", "telecharge_le": None, "efface_le": None}))
    (tmp_path / "x.sawali").write_bytes(b"contenu")
    http = _client_http({"id": "x", "role": "admin", "account_status": "active"})
    lien = http.post("/api/admin/sauvegarde-complete/taches/t1/lien").json()["url"]
    assert http.get(lien.replace("jeton=", "jeton=faux")).status_code == 410
    r = http.get(lien)
    assert r.status_code == 200 and r.content == b"contenu"
    assert not (tmp_path / "x.sawali").exists()  # effacé après le téléchargement
    assert http.get(lien).status_code == 410  # une seule fois


# ---------------------------------------------------------------------------
# 5. Restauration initiale
# ---------------------------------------------------------------------------
def test_restauration_initiale_controles(base, tmp_path, monkeypatch):
    source = mongomock_motor.AsyncMongoMockClient()["source49e"]
    run(_remplir(source))
    run(_exporter(source, tmp_path / "e.sawali"))
    sc.db = base
    ident = {"email": "ADMIN@sawali.test", "mot_de_passe": MDP}
    # Identifiants refusés : mauvais mot de passe, compte non admin -> rien n'est écrit
    for mauvais in ({"email": "admin@sawali.test", "mot_de_passe": "faux"},
                    {"email": "client@sawali.test", "mot_de_passe": MDP},
                    {"email": "inconnu@sawali.test", "mot_de_passe": MDP}):
        with pytest.raises(sf.ErreurSauvegarde, match="Identifiants refusés"):
            run(sc.importer(tmp_path / "e.sawali", PHRASE, "vide", exiger_signature=True, identifiants=mauvais,
                            comptes_max=0))
    assert run(base.list_collection_names()) == []
    # Autre JWT_SECRET sur ce serveur : signature refusée
    monkeypatch.setenv("JWT_SECRET", "un-autre-secret-de-serveur-0123456789")
    with pytest.raises(sf.ErreurSauvegarde, match="Signature refusée"):
        run(sc.importer(tmp_path / "e.sawali", PHRASE, "vide", exiger_signature=True, identifiants=ident, comptes_max=0))
    monkeypatch.setenv("JWT_SECRET", JWT)
    # Tout est correct : restauration faite
    rapport = run(sc.importer(tmp_path / "e.sawali", PHRASE, "vide", exiger_signature=True, identifiants=ident,
                              comptes_max=0))
    assert rapport["anomalies"] == [] and run(base.users.count_documents({})) == 2
    # Il y a maintenant des comptes : la restauration initiale n'est plus disponible
    assert run(sc.raison_restauration_impossible()) == "le site contient déjà des comptes"


def test_restauration_initiale_admin_inactif_refuse(base, tmp_path):
    source = mongomock_motor.AsyncMongoMockClient()["source49f"]
    run(_remplir(source, admin_actif=False))
    run(_exporter(source, tmp_path / "e.sawali"))
    sc.db = base
    with pytest.raises(sf.ErreurSauvegarde, match="Identifiants refusés"):
        run(sc.importer(tmp_path / "e.sawali", PHRASE, "vide", exiger_signature=True,
                        identifiants={"email": "admin@sawali.test", "mot_de_passe": MDP}, comptes_max=0))


def test_restauration_initiale_disponibilite(base, monkeypatch):
    http = _client_http(None)
    assert http.get("/api/public/restauration/etat").json() == {"disponible": True, "raison": None}
    # Fichier non signé ou serveur sans secret sûr : indisponible
    monkeypatch.setenv("JWT_SECRET", "fallback-insecure")
    assert "JWT_SECRET" in http.get("/api/public/restauration/etat").json()["raison"]
    monkeypatch.setenv("JWT_SECRET", JWT)
    run(base.factures.insert_one({"n": 1}))
    assert http.get("/api/public/restauration/etat").json()["disponible"] is False
    run(base.factures.delete_many({}))
    run(base.users.insert_one({"id": "u"}))
    r = http.post("/api/public/restauration", files={"fichier": ("e.sawali", b"x")},
                  data={"phrase": PHRASE, "email": "a@b.c", "mot_de_passe": "x"})
    assert r.status_code == 403
    # Essais limités
    sc._TENTATIVES.extend([10 ** 12] * sc.TENTATIVES_MAX)
    r = http.post("/api/public/restauration", files={"fichier": ("e.sawali", b"x")},
                  data={"phrase": PHRASE, "email": "a@b.c", "mot_de_passe": "x"})
    assert r.status_code == 429


def test_secret_par_defaut_ne_signe_pas():
    assert sf.cle_signature("fallback-insecure") is None and sf.cle_signature("") is None
    assert sf.cle_signature(JWT) != sf.cle_signature(JWT + "x")


# ---------------------------------------------------------------------------
# 6. Sauvegarde automatique vers R2 et rétention
# ---------------------------------------------------------------------------
class FauxR2:
    def __init__(self):
        self.objets = {}
        self.supprimees = []

    def upload_file(self, chemin, bucket, cle, ExtraArgs=None):  # noqa: N803
        self.objets[cle] = Path(chemin).read_bytes()

    def head_object(self, Bucket, Key):  # noqa: N803
        return {"ContentLength": len(self.objets[Key])}

    def download_file(self, bucket, cle, chemin):
        Path(chemin).write_bytes(self.objets[cle])

    def list_objects_v2(self, Bucket, Prefix="", ContinuationToken=None):  # noqa: N803
        cles = sorted(k for k in self.objets if k.startswith(Prefix))
        debut = int(ContinuationToken or 0)
        page = cles[debut:debut + 50]
        fin = debut + 50 < len(cles)
        return {"Contents": [{"Key": k, "Size": len(self.objets[k])} for k in page], "IsTruncated": fin,
                "NextContinuationToken": str(debut + 50) if fin else None}

    def delete_objects(self, Bucket, Delete):  # noqa: N803
        for o in Delete["Objects"]:
            self.supprimees.append(o["Key"])
            self.objets.pop(o["Key"], None)
        return {}


def test_retention_7_4_12():
    debut = dt.datetime(2026, 10, 2, 3, 0, tzinfo=UTC)
    cles = [f"p/sawali-{(debut - timedelta(days=j)):%Y%m%d-%H%M%S}.sawali" for j in range(400)]
    cles.append(f"p/sawali-{debut:%Y%m%d}-150000.sawali")  # deux sauvegardes le même jour
    cles += ["p/autre-fichier.sawali", "p/sawali-20260101-030000.sawali.part", "p/notes.txt"]
    d = sc.retention(cles)
    garder = d["garder"]
    assert sum("quotidienne" in r for r in garder.values()) == 7
    assert sum("hebdomadaire" in r for r in garder.values()) == 4
    assert sum("mensuelle" in r for r in garder.values()) == 12
    assert f"p/sawali-{debut:%Y%m%d}-150000.sawali" in garder  # la plus récente du jour
    assert f"p/sawali-{debut:%Y%m%d-%H%M%S}.sawali" not in garder
    for etranger in ("p/autre-fichier.sawali", "p/sawali-20260101-030000.sawali.part", "p/notes.txt"):
        assert etranger not in d["supprimer"]
    assert len(garder) + len(d["supprimer"]) == 401
    assert len(garder) <= 7 + 4 + 12


def test_sauvegarde_auto_desactivee_sans_phrase(base, monkeypatch):
    monkeypatch.setenv("R2_SAUVEGARDES_ACCOUNT_ID", "compte")
    monkeypatch.setenv("R2_SAUVEGARDES_ACCESS_KEY_ID", "cle")
    monkeypatch.setenv("R2_SAUVEGARDES_SECRET_ACCESS_KEY", "secret")
    r2 = FauxR2()
    monkeypatch.setitem(sc._FABRIQUE_R2, "client", lambda cfg: r2)
    res = run(sc.sauvegarde_automatique("test"))
    assert res["statut"] == "DESACTIVEE" and "SAUVEGARDE_AUTO_PHRASE" in res["raison"]
    assert r2.objets == {}
    etat = run(sc.etat_auto())
    assert etat["active"] is False and "désactivée" in etat["alerte"]
    monkeypatch.setenv("SAUVEGARDE_AUTO_PHRASE", "court")
    assert "trop courte" in run(sc.sauvegarde_automatique("test"))["raison"]


def test_sauvegarde_auto_r2_retention_rapport_et_restauration(base, monkeypatch, tmp_path):
    run(_remplir(base))
    sc.db = base
    monkeypatch.setenv("SAUVEGARDE_AUTO_PHRASE", PHRASE)
    # Repli : identifiants R2_STOCKS_*, bucket dédié aux sauvegardes
    monkeypatch.setenv("R2_STOCKS_ACCOUNT_ID", "compte")
    monkeypatch.setenv("R2_STOCKS_ACCESS_KEY_ID", "cle")
    monkeypatch.setenv("R2_STOCKS_SECRET_ACCESS_KEY", "secret")
    cfg = sc.config_r2()
    assert cfg["bucket"] == "sawali-sauvegardes" and cfg["source"].startswith("R2_STOCKS")
    r2 = FauxR2()
    for j in range(1, 40):  # anciennes sauvegardes quotidiennes
        r2.objets[f"sauvegardes-completes/sawali-{(dt.datetime(2026, 10, 2) - timedelta(days=j)):%Y%m%d}-030000.sawali"] = b"x"
    r2.objets["sauvegardes-completes/a-ne-pas-toucher.bin"] = b"y"
    monkeypatch.setitem(sc._FABRIQUE_R2, "client", lambda c: r2)
    courriels = []

    async def email(adresse, sujet, html, texte):
        courriels.append((adresse, sujet, texte))
        return True
    sc.configurer(envoyer_email=email, email_defaut="admin@sawali.test")
    monkeypatch.setattr(sc, "_maintenant", lambda: dt.datetime(2026, 10, 2, 3, 0, tzinfo=UTC))
    res = run(sc.sauvegarde_automatique("test"))
    assert res["statut"] == "TERMINE", res
    cle = "sauvegardes-completes/sawali-20261002-030000.sawali"
    assert cle in r2.objets and "sauvegardes-completes/a-ne-pas-toucher.bin" in r2.objets
    assert len([k for k in r2.objets if sc.date_de_cle(k)]) <= 7 + 4 + 12 and r2.supprimees
    assert courriels and "réussie" in courriels[0][1] and PHRASE not in courriels[0][2]
    assert not list(tmp_path.glob("*.sawali"))  # fichier local effacé
    etat = run(sc.etat_auto())
    assert etat["alerte"] is None and etat["derniere_reussite"]["cle"] == cle
    # 27 h plus tard sans nouvelle réussite : alerte
    monkeypatch.setattr(sc, "_maintenant", lambda: dt.datetime(2026, 10, 3, 6, 0, tzinfo=UTC))
    assert "plus de 26 h" in run(sc.etat_auto())["alerte"]
    # Échec d'envoi : rapport d'échec par e-mail
    monkeypatch.setitem(sc._FABRIQUE_R2, "client", lambda c: (_ for _ in ()).throw(RuntimeError("R2 injoignable")))
    res = run(sc.sauvegarde_automatique("test"))
    assert res["statut"] == "ECHEC" and "ÉCHEC" in courriels[-1][1]
    # Restauration de la sauvegarde R2 (mode Remplacer) sur une autre base
    cible = mongomock_motor.AsyncMongoMockClient()["cible49r2"]
    sc.db = cible
    chemin = tmp_path / "depuis-r2.sawali"
    r2.download_file("sawali-sauvegardes", cle, str(chemin))
    rapport = run(sc.importer(chemin, PHRASE, "remplacer"))
    assert rapport["anomalies"] == [] and run(cible["Produit"].count_documents({})) == 1203


def test_tache_import_suivi_et_un_seul_import_a_la_fois(base, tmp_path):
    source = mongomock_motor.AsyncMongoMockClient()["source49g"]
    run(_remplir(source))
    run(_exporter(source, tmp_path / "e.sawali"))
    sc.db = base
    (tmp_path / "copie.sawali").write_bytes((tmp_path / "e.sawali").read_bytes())
    # Un import tient le verrou : le second est refusé sans rien écrire
    assert run(sc._prendre_verrou("verrou_import", 600))
    t1 = run(sc._nouvelle_tache("import", "test"))
    run(sc._tache_import(t1, tmp_path / "copie.sawali", PHRASE, "vide"))
    doc = run(base.sauvegardes_completes.find_one({"_id": t1}))
    assert doc["statut"] == "ECHEC" and "déjà en cours" in doc["erreur"]
    assert not (tmp_path / "copie.sawali").exists() and run(base.users.count_documents({})) == 0
    run(sc._rendre_verrou("verrou_import"))
    # Verrou libre : import terminé, rapport enregistré, fichier importé effacé
    t2 = run(sc._nouvelle_tache("import", "test"))
    run(sc._tache_import(t2, tmp_path / "e.sawali", PHRASE, "vide"))
    doc = run(base.sauvegardes_completes.find_one({"_id": t2}))
    assert doc["statut"] == "TERMINE" and doc["rapport"]["anomalies"] == []
    assert not (tmp_path / "e.sawali").exists()
    # Mauvaise phrase : refus clair dans le suivi
    run(_exporter(source, tmp_path / "f.sawali"))
    sc.db = base
    t3 = run(sc._nouvelle_tache("import", "test"))
    run(sc._tache_import(t3, tmp_path / "f.sawali", "phrase totalement fausse", "remplacer"))
    doc = run(base.sauvegardes_completes.find_one({"_id": t3}))
    assert doc["statut"] == "ECHEC" and doc["erreur"] == "Phrase secrète incorrecte"
