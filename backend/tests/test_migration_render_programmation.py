"""Lot 47 — Sauvegardes de migration programmées, rétention dans R2 et rapport Liluvine.
MongoDB simulé (mongomock_motor), R2 simulé, horloge injectée, envois WhatsApp / e-mail simulés.
Lancer : cd backend && python -m pytest tests/test_migration_render_programmation.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
pytest.importorskip("cryptography")

# db.py lit ces variables à l'import (aucune connexion n'est ouverte)
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_programmation")

from fastapi import HTTPException  # noqa: E402

import routes.migration_programmation as mp  # noqa: E402
import routes.migration_render as mr  # noqa: E402

UTC = timezone.utc
ADMIN = {"email": "admin@test", "role": "admin"}
SECRET_R2 = "cle-secrete-r2-tres-longue"
URI_ATLAS = "mongodb+srv://alice:motdepasse@cluster0.exemple.mongodb.net"


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


class FauxR2:
    """Bucket R2 en mémoire (liste paginée, suppression par lots)."""

    def __init__(self, page: int = 1000):
        self.objets = {}  # clé -> taille
        self.page = page
        self.suppressions = []  # nombre de clés par appel delete_objects

    def ajouter(self, prefixe: str, n: int, taille: int = 100):
        for i in range(n):
            self.objets[f"{prefixe}/fichier-{i}"] = taille

    def head_bucket(self, Bucket):  # noqa: N803 (signature boto3)
        return {}

    def list_objects_v2(self, Bucket, Prefix="", Delimiter=None, MaxKeys=1000, ContinuationToken=None,  # noqa: N803
                        StartAfter=None):  # noqa: N803
        cles = sorted(k for k in self.objets if k.startswith(Prefix) and (StartAfter is None or k > StartAfter))
        if Delimiter:
            dossiers = sorted({k[len(Prefix):].split(Delimiter, 1)[0] + Delimiter for k in cles if Delimiter in k[len(Prefix):]})
            debut = int(ContinuationToken or 0)
            morceau = dossiers[debut:debut + self.page]
            fin = debut + self.page < len(dossiers)
            return {"CommonPrefixes": [{"Prefix": d} for d in morceau], "IsTruncated": fin,
                    "NextContinuationToken": str(debut + self.page) if fin else None}
        debut = int(ContinuationToken or 0)
        pas = min(MaxKeys, self.page)
        morceau = cles[debut:debut + pas]
        fin = debut + pas < len(cles)
        return {"Contents": [{"Key": k, "Size": self.objets[k]} for k in morceau], "IsTruncated": fin,
                "NextContinuationToken": str(debut + pas) if fin else None}

    def delete_objects(self, Bucket, Delete):  # noqa: N803
        cles = [o["Key"] for o in Delete["Objects"]]
        assert len(cles) <= 1000
        self.suppressions.append(len(cles))
        for k in cles:
            self.objets.pop(k, None)
        return {"Errors": []}


@pytest.fixture()
def base(monkeypatch):
    b = mongomock_motor.AsyncMongoMockClient()["sawali_programmation"]
    monkeypatch.setattr(mr, "db", b)
    monkeypatch.setenv("JWT_SECRET", "cle-jwt-de-test-assez-longue-0123456789")
    monkeypatch.delenv("MIGRATION_COFFRE_CLE", raising=False)
    return b


@pytest.fixture()
def envois(monkeypatch):
    """Envois simulés : WhatsApp texte, modèle Meta, e-mail."""
    journal = {"texte": [], "modele": [], "email": []}

    async def texte(numero, message):
        journal["texte"].append((numero, message))
        return {"ok": True}

    async def modele(numero, nom, langue, composants):
        journal["modele"].append((numero, nom, langue, composants))
        return {"ok": True}

    async def email(adresse, sujet, html, texte_):
        journal["email"].append((adresse, sujet, texte_))
        return True

    monkeypatch.setattr(mp, "_ENVOIS", {"texte": texte, "modele": modele, "email": email})
    return journal


def reglage(**kw):
    return mp.normaliser({"actif": True, **kw})


# ---------------------------------------------------------------------------
# Échéances
# ---------------------------------------------------------------------------
def test_premiere_echeance_tous_les_jours_heure_et_fuseau():
    """Ouagadougou = UTC+0 ; avec un fuseau décalé (Paris, été UTC+2) l'heure locale est respectée."""
    cfg = reglage(heure="03:00")
    assert mp.premiere_echeance(cfg, utc(2026, 9, 30, 1, 0)) == utc(2026, 9, 30, 3, 0)
    assert mp.premiere_echeance(cfg, utc(2026, 9, 30, 3, 0)) == utc(2026, 10, 1, 3, 0)  # heure atteinte : demain
    paris = reglage(heure="03:00", fuseau="Europe/Paris")
    assert mp.premiere_echeance(paris, utc(2026, 9, 30, 0, 30)) == utc(2026, 9, 30, 1, 0)


def test_echeance_suivante_tous_les_3_jours_et_rattrapage_sans_rafale():
    cfg = reglage(heure="22:15", tous_les=3)
    echeance = utc(2026, 9, 30, 22, 15)
    # Exécution à l'heure : + 3 jours
    assert mp.echeance_suivante(cfg, echeance, echeance) == utc(2026, 10, 3, 22, 15)
    # Serveur arrêté 10 jours : une seule exécution de rattrapage, puis la prochaine dans le futur
    retard = echeance + timedelta(days=10, hours=1)
    suivante = mp.echeance_suivante(cfg, echeance, retard)
    assert suivante == utc(2026, 10, 12, 22, 15) and suivante > retard
    # Tous les jours
    assert mp.echeance_suivante(reglage(heure="22:15"), echeance, echeance) == utc(2026, 10, 1, 22, 15)


def test_normaliser_refuse_les_valeurs_invalides():
    for mauvais in ({"heure": "25:00"}, {"tous_les": 0}, {"retention_jours": 0}, {"garder_min": 0},
                    {"fuseau": "Lune/Base"}, {"base": False, "fichiers": False}):
        with pytest.raises(ValueError):
            mp.normaliser({"actif": True, **mauvais})


# ---------------------------------------------------------------------------
# Identifiants : chiffrés, jamais renvoyés
# ---------------------------------------------------------------------------
def enregistrer_identifiants(monkeypatch, r2=None):
    monkeypatch.setattr(mr, "_client_r2", lambda *a: r2 or FauxR2())

    class FauxClient:
        class admin:  # noqa: N801
            @staticmethod
            async def command(_):
                return {"ok": 1}

        def close(self):
            pass

    monkeypatch.setattr(mr, "_client_cible", lambda uri: FauxClient())
    corps = mp.IdentifiantsIn(mongo_uri=URI_ATLAS, mongo_db="sawali", r2_account_id="compte", r2_access_key_id="acces",
                              r2_secret_access_key=SECRET_R2, r2_bucket="seau")
    return asyncio.run(mp.enregistrer_identifiants(corps, ADMIN))


def test_identifiants_chiffres_et_jamais_renvoyes(base, monkeypatch):
    reponse = enregistrer_identifiants(monkeypatch)
    texte = str(reponse)
    assert SECRET_R2 not in texte and "motdepasse" not in texte and "alice" not in texte
    assert reponse["identifiants"]["existe"] and reponse["identifiants"]["lisibles"]
    assert reponse["identifiants"]["mongo_hote"] == "cluster0.exemple.mongodb.net"
    # En base : seulement l'enveloppe chiffrée
    doc = asyncio.run(base.migration_programmation.find_one({"_id": "identifiants"}))
    assert SECRET_R2 not in str(doc) and "motdepasse" not in str(doc)
    assert asyncio.run(mp.charger_identifiants())["r2_secret_access_key"] == SECRET_R2
    # Lecture de l'état : rien non plus
    assert SECRET_R2 not in str(asyncio.run(mp.lire(ADMIN)))
    # Clé du serveur changée : illisibles, signalé clairement
    monkeypatch.setenv("JWT_SECRET", "une-autre-cle-jwt-bien-differente-9876")
    assert asyncio.run(mp.lire(ADMIN))["identifiants"]["lisibles"] is False
    with pytest.raises(RuntimeError):
        asyncio.run(mp.charger_identifiants())


def test_cle_serveur_de_secours_refusee(base, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "fallback-insecure")
    with pytest.raises(HTTPException) as exc:
        enregistrer_identifiants(monkeypatch)
    assert exc.value.status_code == 400


def test_activation_calcule_la_prochaine_execution(base, monkeypatch):
    monkeypatch.setattr(mp, "_maintenant", lambda: utc(2026, 9, 30, 10, 0))
    with pytest.raises(HTTPException):  # sans identifiants : refus
        asyncio.run(mp.enregistrer(mp.ReglageIn(actif=True, heure="03:00"), ADMIN))
    enregistrer_identifiants(monkeypatch)
    etat = asyncio.run(mp.enregistrer(mp.ReglageIn(actif=True, heure="03:00", tous_les=2), ADMIN))
    assert etat["prochaine_execution"] == mp._iso(utc(2026, 10, 1, 3, 0))
    assert etat["secrets_programmes"] is False and "mot de passe" in etat["explication_secrets"]


# ---------------------------------------------------------------------------
# Déclenchement : échéance, EN_COURS, verrou anti-double
# ---------------------------------------------------------------------------
@pytest.fixture()
def programmation(base, monkeypatch, envois):
    """Programmation active (tous les jours à 03:00), échéance le 30/09 à 03:00 ; _demarrer simulé."""
    enregistrer_identifiants(monkeypatch)
    lancees = []

    async def faux_demarrer(cible, lance_par, programmee=False):
        lancees.append((cible, lance_par, programmee))
        return {"id": f"job{len(lancees)}", "prefixe": f"migration-2026093{len(lancees)}-030000"}

    monkeypatch.setattr(mr, "_demarrer", faux_demarrer)
    asyncio.run(base.migration_programmation.update_one({"_id": "parametres"}, {"$set": {
        **reglage(heure="03:00"), "prochaine_execution": mp._iso(utc(2026, 9, 30, 3, 0))}}, upsert=True))
    return lancees


def test_declenchement_a_l_echeance_en_fusion_sans_secrets(programmation, base):
    assert asyncio.run(mp.passage(utc(2026, 9, 30, 2, 59)))["declenchee"] is None
    bilan = asyncio.run(mp.passage(utc(2026, 9, 30, 3, 0, 30)))
    assert bilan["declenchee"]["ok"]
    cible, _, programmee = programmation[0]
    assert programmee and cible.remplacer is False and cible.sauver_secrets is False
    assert cible.mongo_uri == URI_ATLAS and cible.r2_secret_access_key == SECRET_R2
    doc = asyncio.run(base.migration_programmation.find_one({"_id": "parametres"}))
    assert doc["prochaine_execution"] == mp._iso(utc(2026, 10, 1, 3, 0))
    # Passage suivant, même minute : rien de plus
    asyncio.run(mp.passage(utc(2026, 9, 30, 3, 1)))
    assert len(programmation) == 1


def test_pas_de_declenchement_si_une_sauvegarde_est_en_cours(programmation, base):
    maintenant = utc(2026, 9, 30, 3, 5)
    # Signe de vie récent (horloge réelle du veilleur) : la sauvegarde manuelle n'est pas déclarée interrompue
    asyncio.run(base.migration_jobs.insert_one({"id": "manuelle", "statut": "EN_COURS", "battement": mr._maintenant(),
                                                "debut": mr._maintenant()}))
    bilan = asyncio.run(mp.passage(maintenant))
    assert bilan["declenchee"] is None and bilan["attente"] == "sauvegarde en cours" and not programmation
    # Fin de la sauvegarde manuelle : rattrapage au passage suivant
    asyncio.run(base.migration_jobs.update_one({"id": "manuelle"}, {"$set": {"statut": "TERMINEE"}}))
    assert asyncio.run(mp.passage(maintenant + timedelta(minutes=1)))["declenchee"]["ok"]
    assert len(programmation) == 1


def test_verrou_un_seul_declenchement_pour_deux_processus(programmation, base):
    async def deux_processus():
        return await asyncio.gather(mp.passage(utc(2026, 9, 30, 3, 0, 10)), mp.passage(utc(2026, 9, 30, 3, 0, 10)))

    bilans = asyncio.run(deux_processus())
    assert sum(1 for b in bilans if b["declenchee"]) == 1
    assert len(programmation) == 1


def test_rattrapage_apres_arret_une_seule_fois(programmation, base):
    reveil = utc(2026, 10, 4, 9, 0)  # serveur arrêté 4 jours
    asyncio.run(mp.passage(reveil))
    asyncio.run(mp.passage(reveil + timedelta(minutes=1)))
    assert len(programmation) == 1
    doc = asyncio.run(base.migration_programmation.find_one({"_id": "parametres"}))
    assert doc["prochaine_execution"] == mp._iso(utc(2026, 10, 5, 3, 0))


def test_echec_au_demarrage_rapport_toujours_envoye(programmation, base, envois, monkeypatch):
    async def refus(*_a, **_k):
        raise HTTPException(400, "Accès au bucket R2 « seau » impossible")

    monkeypatch.setattr(mr, "_demarrer", refus)
    asyncio.run(base.settings.insert_one({"_id": "global", "auto_snapshot_email_to": "admin@sawali.test"}))
    asyncio.run(base.migration_programmation.update_one({"_id": "parametres"}, {"$set": {"rapport_si_ok": False}}))
    bilan = asyncio.run(mp.passage(utc(2026, 9, 30, 3, 1)))
    assert bilan["declenchee"]["ok"] is False
    # Aucun numéro WhatsApp : repli par e-mail
    assert envois["email"] and "Échec" in envois["email"][0][2] and "bucket R2" in envois["email"][0][2]


# ---------------------------------------------------------------------------
# Purge
# ---------------------------------------------------------------------------
def job(prefixe, statut="TERMINEE", programmee=True, bucket="seau"):
    return {"id": f"j-{prefixe}", "statut": statut, "programmee": programmee,
            "cible": {"prefixe": prefixe, "r2_bucket": bucket}, "debut": "x", "rapport": {"envoye": True}}


def test_purge_jours_k_dernieres_motif_et_en_cours(base):
    maintenant = utc(2026, 9, 30, 12, 0)
    r2 = FauxR2(page=2)  # pagination forcée
    prefixes = {
        "migration-20260929-030000": "TERMINEE",  # récente
        "migration-20260901-030000": "TERMINEE",  # vieille, K
        "migration-20260801-030000": "TERMINEE_AVEC_ERREURS",  # vieille, K
        "migration-20260701-030000": "TERMINEE",  # vieille -> supprimée
        "migration-20260601-030000": "ECHEC",  # vieille, non réussie -> supprimée
        "migration-20260501-030000": "EN_COURS",  # vieille mais en cours -> gardée
        "migration-20260401-030000": None,  # inconnue de l'historique -> gardée
        "migration-20260301-030000-copie": "TERMINEE",  # hors motif -> gardée
        "autre-dossier": None,  # hors motif -> gardé
        "migration-20260201-030000": "TERMINEE",  # manuelle, vieille -> selon l'option
    }
    for p, statut in prefixes.items():
        r2.ajouter(p, 3, taille=1000)
        if statut:
            asyncio.run(base.migration_jobs.insert_one(job(p, statut, programmee=p != "migration-20260201-030000")))
    r2.ajouter("migration-20260701-030000", 2500, taille=10)  # 2 500 objets (remplacent les 3) : plusieurs lots
    cfg = mp.normaliser({"retention_jours": 14, "garder_min": 3, "purge_manuelles": False})
    res = asyncio.run(mp.purger(maintenant, r2=r2, bucket="seau", cfg=cfg))
    supprimees = {s["prefixe"] for s in res["supprimees"]}
    assert supprimees == {"migration-20260701-030000", "migration-20260601-030000"}
    assert res["objets"] == 2500 + 3 and res["octets"] == 2500 * 10 + 3 * 1000
    assert all(n <= 1000 for n in r2.suppressions)
    restants = {k.split("/")[0] for k in r2.objets}
    assert {"migration-20260501-030000", "migration-20260401-030000", "migration-20260301-030000-copie",
            "autre-dossier", "migration-20260201-030000", "migration-20260929-030000"} <= restants
    # Historique conservé, marqué purgé
    doc = asyncio.run(base.migration_jobs.find_one({"id": "j-migration-20260701-030000"}))
    assert doc["purgee"] is True and doc["purge"]["objets"] == 2500
    # Option « purger aussi les manuelles » : la manuelle ancienne part à son tour
    cfg2 = mp.normaliser({"retention_jours": 14, "garder_min": 3, "purge_manuelles": True})
    res2 = asyncio.run(mp.purger(maintenant, r2=r2, bucket="seau", cfg=cfg2))
    assert {s["prefixe"] for s in res2["supprimees"]} == {"migration-20260201-030000"}


def test_k_dernieres_reussies_gardees_meme_au_dela_des_jours(base):
    maintenant = utc(2026, 9, 30)
    r2 = FauxR2()
    for p in ("migration-20250101-000000", "migration-20250201-000000", "migration-20250301-000000"):
        r2.ajouter(p, 1)
        asyncio.run(base.migration_jobs.insert_one(job(p)))
    res = asyncio.run(mp.purger(maintenant, r2=r2, bucket="seau", cfg=mp.normaliser({"retention_jours": 1, "garder_min": 2})))
    assert [s["prefixe"] for s in res["supprimees"]] == ["migration-20250101-000000"]


# ---------------------------------------------------------------------------
# Rapport Liluvine
# ---------------------------------------------------------------------------
def test_rapport_apres_sauvegarde_programmee_avec_les_bons_chiffres(programmation, base, envois, monkeypatch):
    maintenant = utc(2026, 9, 30, 4, 12)
    r2 = FauxR2()
    monkeypatch.setattr(mr, "_client_r2", lambda *a: r2)
    # Ancienne sauvegarde purgeable + la sauvegarde programmée qui vient de finir
    r2.ajouter("migration-20260801-030000", 4, taille=1 << 20)
    asyncio.run(base.migration_jobs.insert_one(job("migration-20260801-030000")))
    for p in ("migration-20260927-030000", "migration-20260928-030000"):
        asyncio.run(base.migration_jobs.insert_one(job(p)))
        r2.ajouter(p, 1)
    r2.ajouter("migration-20260930-030000", 1)
    asyncio.run(base.migration_jobs.insert_one({
        **job("migration-20260930-030000", "TERMINEE_AVEC_ERREURS"), "id": "prog", "rapport": None,
        "debut": mp._iso(utc(2026, 9, 30, 3, 0)), "fin": mp._iso(utc(2026, 9, 30, 4, 10, 5)),
        "options": {"base": True, "fichiers": True}, "collections_faites": 85, "collections_total": 85,
        "documents_copies": 123456, "fichiers_copies": 1200, "fichiers_absents": 12, "fichiers_medias_ignores": 30,
        "fichiers_echecs": 2, "octets_archives": 512 << 20, "octets_fichiers": 1 << 30, "journal": ["fin"]}))
    asyncio.run(base.settings.insert_one({"_id": "global", "liluvine_remote_admin_phones": ["+226 70 00 00 01"]}))
    # L'admin a écrit à Liluvine il y a 2 h : fenêtre de 24 h ouverte -> texte libre
    asyncio.run(base.whatsapp_messages.insert_one({"direction": "inbound", "phone_digits": "22670000001",
                                                   "created_at": mp._iso(maintenant - timedelta(hours=2))}))
    asyncio.run(base.migration_programmation.update_one({"_id": "parametres"}, {"$set": {"retention_jours": 30}}))
    bilan = asyncio.run(mp.passage(maintenant))
    assert bilan["rapports"] == ["prog"]
    (numero, texte), = envois["texte"]
    assert numero == "22670000001" and texte.startswith("🤖 Liluvine — Rapport de sauvegarde")
    for attendu in ("Terminée avec anomalies", "Durée : 1 h 10 min", "85/85 collections", "123 456 documents",
                    "1 200 copiés", "12 absents", "30 médias ignorés", "2 vraies erreurs", "1,5 Go",
                    "seau/migration-20260930-030000", "1 sauvegarde(s) supprimée(s), 4,0 Mo libéré(s)",
                    "Prochaine exécution : 30/09/2026 à 03:00"):
        assert attendu in texte, attendu
    doc = asyncio.run(base.migration_jobs.find_one({"id": "prog"}))
    assert doc["rapport"]["envoye"] is True
    assert "migration-20260801-030000/fichier-0" not in r2.objets
    # Un seul rapport : le passage suivant ne renvoie rien
    asyncio.run(mp.passage(maintenant + timedelta(minutes=1)))
    assert len(envois["texte"]) == 1


def test_rapport_hors_fenetre_modele_meta_ou_email(base, envois):
    asyncio.run(base.settings.insert_one({"_id": "global", "liluvine_remote_admin_phones": ["22670000001"],
                                          "health_email_to": "sante@sawali.test"}))
    maintenant = utc(2026, 9, 30, 4, 0)
    # Hors fenêtre, modèle réglé : modèle avec le rapport sur une ligne
    cfg = mp.normaliser({"modele_wa": "rapport_admin", "modele_wa_langue": "fr"})
    res = asyncio.run(mp.envoyer_rapport("Sujet", "ligne 1\nligne 2", cfg, important=False, maintenant=maintenant))
    assert res["envoye"] and envois["modele"][0][1] == "rapport_admin"
    assert envois["modele"][0][3][0]["parameters"][0]["text"] == "ligne 1 · ligne 2"
    # Hors fenêtre, sans modèle : e-mail
    res = asyncio.run(mp.envoyer_rapport("Sujet", "texte", mp.normaliser({}), important=True, maintenant=maintenant))
    assert res["whatsapp"][0]["mode"] == "aucun" and res["email"]["a"] == "sante@sawali.test" and res["envoye"]
    # Tout va bien et option décochée : rien
    res = asyncio.run(mp.envoyer_rapport("Sujet", "texte", mp.normaliser({"rapport_si_ok": False}), important=False))
    assert res["envoye"] is False and len(envois["email"]) == 1


def test_purger_maintenant_envoie_un_rapport(base, envois, monkeypatch):
    r2 = FauxR2()
    enregistrer_identifiants(monkeypatch, r2)
    monkeypatch.setattr(mp, "_maintenant", lambda: utc(2026, 9, 30, 12, 0))
    asyncio.run(base.settings.insert_one({"_id": "global", "auto_snapshot_email_to": "admin@sawali.test"}))
    for p in ("migration-20250101-000000", "migration-20260901-000000", "migration-20260902-000000",
              "migration-20260903-000000"):
        r2.ajouter(p, 2)
        asyncio.run(base.migration_jobs.insert_one(job(p)))
    res = asyncio.run(mp.purger_maintenant(ADMIN))
    assert [s["prefixe"] for s in res["supprimees"]] == ["migration-20250101-000000"]
    assert "Rapport de purge" in envois["email"][0][2] and "1 sauvegarde(s) supprimée(s)" in envois["email"][0][2]
