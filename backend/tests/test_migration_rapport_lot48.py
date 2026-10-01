"""Lot 48 — Rapports de sauvegarde archivés, envoi / renvoi à la demande, journal des envois,
destinataires du bloc « Sauvegardes programmées et rétention », chemins d'exemple ignorés.
MongoDB simulé (mongomock_motor), envois WhatsApp / e-mail simulés, horloge injectée.
Lancer : cd backend && python -m pytest tests/test_migration_rapport_lot48.py -q
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

# db.py lit ces variables à l'import (aucune connexion n'est ouverte)
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot48")

from fastapi import HTTPException  # noqa: E402

import routes.migration_programmation as mp  # noqa: E402
import routes.migration_rapports as rap  # noqa: E402
import routes.migration_render as mr  # noqa: E402

UTC = timezone.utc
ADMIN = {"email": "admin@test", "role": "admin"}
MAINTENANT = datetime(2026, 9, 30, 4, 12, tzinfo=UTC)
ERREUR_131042 = "(#131042) Business eligibility payment issue"


@pytest.fixture()
def base(monkeypatch):
    b = mongomock_motor.AsyncMongoMockClient()["sawali_lot48"]
    monkeypatch.setattr(mr, "db", b)
    monkeypatch.setattr(mp, "_maintenant", lambda: MAINTENANT)
    monkeypatch.setitem(mp._EMAIL_DEFAUT, "adresse", "")
    return b


@pytest.fixture()
def envois(monkeypatch):
    """Envois simulés. `reponse_modele` : réponse du faux envoi de modèle (modifiable par test)."""
    journal = {"texte": [], "modele": [], "email": [], "reponse_modele": {"ok": True, "message_id": "wamid.M1"}}

    async def texte(numero, message):
        journal["texte"].append((numero, message))
        return {"ok": True, "message_id": f"wamid.T{len(journal['texte'])}"}

    async def modele(numero, nom, langue, composants):
        journal["modele"].append((numero, nom, langue, composants))
        return dict(journal["reponse_modele"])

    async def email(adresse, sujet, html, texte_):
        journal["email"].append((adresse, sujet, html, texte_))
        return True

    monkeypatch.setattr(mp, "_ENVOIS", {"texte": texte, "modele": modele, "email": email})
    return journal


def lancer(coro):
    return asyncio.run(coro)


def fenetre_ouverte(base, chiffres, il_y_a=timedelta(hours=2)):
    """L'admin a écrit à Liluvine : fenêtre de 24 h ouverte."""
    lancer(base.whatsapp_messages.insert_one({"direction": "inbound", "phone_digits": chiffres,
                                              "created_at": mp._iso(MAINTENANT - il_y_a)}))


def sauvegarde(job_id="j1", **kw):
    """Suivi d'une sauvegarde terminée (mêmes champs que migration_render._demarrer)."""
    return {"id": job_id, "statut": "TERMINEE", "programmee": False, "lance_par": "admin@test",
            "debut": mp._iso(datetime(2026, 9, 30, 3, 0, tzinfo=UTC)),
            "fin": mp._iso(datetime(2026, 9, 30, 3, 20, 5, tzinfo=UTC)),
            "cible": {"r2_bucket": "seau", "prefixe": f"migration-20260930-0300{job_id[-2:]}"},
            "options": {"base": True, "fichiers": True, "medias": False},
            "collections_faites": 85, "collections_total": 85, "documents_copies": 123456,
            "fichiers_total": 1250, "fichiers_copies": 1200, "fichiers_absents": 12, "fichiers_medias_ignores": 30,
            "fichiers_echecs": 0, "octets_archives": 512 << 20, "octets_fichiers": 1 << 30,
            "references_ignorees": {"disque": 1, "inconnu": 2, "exemples": 3}, "journal": ["fin"], **kw}


# ---------------------------------------------------------------------------
# Archivage
# ---------------------------------------------------------------------------
def test_sauvegarde_programmee_rapport_archive_avec_journal(base, envois, monkeypatch):
    async def fausse_purge(*_a, **_k):
        return {"supprimees": [{"prefixe": "migration-20260801-030000"}], "objets": 4, "octets": 4 << 20,
                "erreurs": 0, "gardees": 3}

    monkeypatch.setattr(mp, "purger", fausse_purge)
    lancer(base.migration_jobs.insert_one(sauvegarde("prog", programmee=True, rapport=None, rapport_archive=False)))
    lancer(base.settings.insert_one({"_id": "global", "liluvine_remote_admin_phones": ["+226 70 00 00 01"]}))
    fenetre_ouverte(base, "22670000001")
    assert lancer(mp.passage(MAINTENANT))["rapports"] == ["prog"]
    doc = lancer(base.migration_rapports.find_one({"id": "sauvegarde-prog"}))
    assert doc["type"] == "sauvegarde" and doc["job_id"] == "prog" and doc["source"] == "automatique"
    assert doc["texte"] == envois["texte"][0][1] and "Sauvegarde programmée du" in doc["texte"]
    assert "3 chemin(s) d'exemple" in doc["texte"]
    d = doc["donnees"]
    assert (d["statut"], d["duree_s"], d["collections_faites"], d["documents_copies"]) == ("TERMINEE", 1205, 85, 123456)
    assert (d["fichiers_copies"], d["fichiers_absents"], d["fichiers_medias_ignores"], d["fichiers_echecs"]) == (1200, 12, 30, 0)
    assert d["octets"] == (512 << 20) + (1 << 30) and d["prefixe"] == "migration-20260930-0300og"
    assert d["purge"]["supprimees"] == ["migration-20260801-030000"]
    (ligne,) = doc["envois"]
    assert ligne["canal"] == "whatsapp" and ligne["mode"] == "texte" and ligne["par"] == "auto" and ligne["ok"]
    assert rap.badge(doc["envois"])["etat"] == "attente"  # accepté par Meta, remise pas encore confirmée
    job = lancer(base.migration_jobs.find_one({"id": "prog"}))
    assert job["rapport_archive"] is True and job["rapport"]["rapport_id"] == "sauvegarde-prog"


def test_sauvegarde_manuelle_archivee_sans_envoi(base, envois):
    lancer(base.migration_jobs.insert_one(sauvegarde("man", rapport=None, rapport_archive=False)))
    lancer(mp.passage(MAINTENANT))
    doc = lancer(base.migration_rapports.find_one({"job_id": "man"}))
    assert "Sauvegarde manuelle (par admin@test) du 30/09/2026 à 03:00" in doc["texte"]
    assert doc["envois"] == [] and not envois["texte"] and not envois["email"]
    # Passage suivant : rien de nouveau
    lancer(mp.passage(MAINTENANT + timedelta(minutes=1)))
    assert lancer(base.migration_rapports.count_documents({})) == 1


def test_ancienne_sauvegarde_rapport_recalcule_a_la_volee(base, envois):
    # Sauvegarde d'avant le lot 48 : pas de rapport archivé ; résultat d'envoi du lot 47 gardé dans le suivi
    ancien = sauvegarde("old", programmee=True, purgee=True, purgee_le=mp._iso(MAINTENANT),
                        rapport={"le": mp._iso(MAINTENANT), "envoye": False, "email": None,
                                 "whatsapp": [{"a": "22670000001", "mode": "modèle", "ok": False,
                                               "erreur": ERREUR_131042}]})
    ancien.pop("references_ignorees")
    lancer(base.migration_jobs.insert_one(ancien))
    r = lancer(rap.lire_rapport("old", ADMIN))
    assert r["source"] == "recalcule" and r["id"] == "sauvegarde-old"
    assert r["texte"].startswith("🤖 Liluvine — Rapport de sauvegarde") and "1 200 copiés" in r["texte"]
    assert "Supprimée de R2 par la rétention" in r["texte"] and "rapport recalculé" in r["texte"]
    (repris,) = r["envois"]
    assert repris["code"] == 131042 and "Paiement du compte WhatsApp Business" in repris["explication"]
    assert r["badge"]["etat"] == "echec"
    # Archivé : relu à l'identique par l'id du rapport
    assert lancer(rap.lire_rapport("sauvegarde-old", ADMIN))["texte"] == r["texte"]
    # Même fonction de rédaction que le rapport automatique
    cfg = lancer(mp.lire_reglage())
    job = lancer(base.migration_jobs.find_one({"id": "old"}, {"_id": 0}))
    assert r["texte"] == mp.texte_rapport_sauvegarde(job, None, cfg, None, recalcule=True)


def test_sauvegarde_en_cours_rapport_provisoire_non_envoyable(base, envois):
    lancer(base.migration_jobs.insert_one(sauvegarde("cours", statut="EN_COURS", fin=None)))
    r = lancer(rap.lire_rapport("cours", ADMIN))
    assert r["provisoire"] and lancer(base.migration_rapports.count_documents({})) == 0
    with pytest.raises(HTTPException) as e:
        lancer(rap.envoyer("cours", rap.EnvoiIn(canal="email", emails="a@b.bf"), ADMIN))
    assert e.value.status_code == 409


# ---------------------------------------------------------------------------
# Envoi / renvoi à la demande
# ---------------------------------------------------------------------------
def test_envoi_a_la_demande_whatsapp_dans_et_hors_fenetre_et_email(base, envois):
    lancer(base.migration_jobs.insert_one(sauvegarde("j1")))
    lancer(base.migration_programmation.insert_one({"_id": "parametres", "modele_wa": "rapport_admin",
                                                    "modele_wa_langue": "fr"}))
    fenetre_ouverte(base, "22670000001")
    corps = rap.EnvoiIn(canal="les_deux", numeros="+226 70 00 00 01, 226 70 00 00 02",
                        emails=["dg@sawali.bf", "it@sawali.bf"])
    r = lancer(rap.envoyer("j1", corps, ADMIN))
    modes = {x["a"]: (x["mode"], x["modele"]) for x in r["resultats"] if x["canal"] == "whatsapp"}
    assert modes == {"22670000001": ("texte", None), "22670000002": ("modele", "rapport_admin")}
    assert envois["modele"][0][3][0]["parameters"][0]["text"].startswith("🤖 Liluvine — Rapport de sauvegarde · ")
    # E-mail : HTML lisible + texte
    assert [e[0] for e in envois["email"]] == ["dg@sawali.bf", "it@sawali.bf"]
    _, sujet, corps_html, texte = envois["email"][0]
    assert sujet == "[SAWALI] Sauvegarde manuelle : ✅ Terminée" and "<table" in corps_html and "Statut" in corps_html
    assert texte.startswith("🤖 Liluvine")
    assert all(x["par"] == "admin@test" for x in r["envois"]) and len(r["envois"]) == 4
    assert r["badge"]["libelle"] == "envoyé WhatsApp + e-mail"
    # Autre modèle choisi, et modèle forcé même dans la fenêtre
    r = lancer(rap.envoyer("sauvegarde-j1", rap.EnvoiIn(numeros=["22670000001"], modele="autre_modele", langue="en",
                                                        forcer_modele=True), ADMIN))
    assert envois["modele"][-1][:3] == ("22670000001", "autre_modele", "en") and len(r["envois"]) == 5
    # Destinataires manquants : refus clair
    with pytest.raises(HTTPException):
        lancer(rap.envoyer("j1", rap.EnvoiIn(canal="email", emails="pas-une-adresse"), ADMIN))


def test_hors_fenetre_sans_modele_explication_131047(base, envois):
    lancer(base.migration_jobs.insert_one(sauvegarde("j1")))
    r = lancer(rap.envoyer("j1", rap.EnvoiIn(numeros="22670000009"), ADMIN))
    (x,) = r["resultats"]
    assert x["mode"] == "aucun" and not x["ok"] and x["explication"].startswith("Hors fenêtre de 24 h")
    assert not envois["texte"] and not envois["modele"] and r["badge"]["etat"] == "echec"


# ---------------------------------------------------------------------------
# Échecs Meta traduits, repli e-mail
# ---------------------------------------------------------------------------
def test_traduction_des_erreurs_meta():
    assert mp.traduire_erreur_meta(None, ERREUR_131042) == (
        131042, "Paiement du compte WhatsApp Business à régulariser chez Meta (moyen de paiement)")
    assert mp.traduire_erreur_meta(131047)[1] == "Hors fenêtre de 24 h : un modèle est nécessaire"
    assert mp.traduire_erreur_meta("132001")[1] == mp.traduire_erreur_meta(132000)[1]
    assert mp.traduire_erreur_meta(131026)[1] == "Numéro injoignable / pas sur WhatsApp"
    assert mp.traduire_erreur_meta(None, "Timeout") == (None, None)


def test_echec_131042_immediat_journalise_et_repli_email(base, envois):
    envois["reponse_modele"] = {"ok": False, "error": ERREUR_131042, "error_code": 131042}
    lancer(base.settings.insert_one({"_id": "global", "liluvine_remote_admin_phones": ["22670000001"],
                                     "auto_snapshot_email_to": "admin@sawali.bf"}))
    cfg = mp.normaliser({"modele_wa": "rapport_admin"})
    res = lancer(mp.envoyer_rapport("Sujet", "ligne 1\nligne 2", cfg, important=True, maintenant=MAINTENANT))
    assert res["envoye"] and res["whatsapp"][0]["code"] == 131042 and res["email"]["a"] == "admin@sawali.bf"
    wa, mail = res["envois"]
    assert wa["mode"] == "modele" and wa["modele"] == "rapport_admin" and wa["etat"] == "echec"
    assert wa["explication"].startswith("Paiement du compte WhatsApp Business")
    assert mail["canal"] == "email" and mail["ok"] and mail["lot"] == wa["lot"]
    assert rap.badge(res["envois"])["libelle"] == "envoyé e-mail"


def test_echec_131042_signale_par_le_webhook_puis_repli_email(base, envois, monkeypatch):
    """Meta accepte le modèle puis le refuse (statut « failed » reçu par le webhook) : le journal
    est corrigé au passage suivant et l'e-mail de repli part alors."""
    async def fausse_purge(*_a, **_k):
        return {"supprimees": [], "objets": 0, "octets": 0, "erreurs": 0, "gardees": 2}

    monkeypatch.setattr(mp, "purger", fausse_purge)
    lancer(base.settings.insert_one({"_id": "global", "liluvine_remote_admin_phones": ["22670000001"],
                                     "health_email_to": "sante@sawali.bf"}))
    lancer(base.migration_programmation.insert_one({"_id": "parametres", "modele_wa": "rapport_admin"}))
    lancer(base.migration_jobs.insert_one(sauvegarde("prog", programmee=True, rapport=None)))
    lancer(mp.passage(MAINTENANT))
    assert len(envois["modele"]) == 1 and not envois["email"]  # accepté par Meta : pas de repli tout de suite
    assert lancer(base.migration_rapports.find_one({"id": "sauvegarde-prog"}))["a_verifier"] is True
    # Le webhook ne trouve pas le message dans whatsapp_messages : statut gardé dans wa_pending_statuses
    lancer(base.wa_pending_statuses.insert_one({"message_id": "wamid.M1", "wa_status": "failed",
                                                "wa_error_code": 131042,
                                                "wa_error_message": "Business eligibility payment issue"}))
    lancer(mp.passage(MAINTENANT + timedelta(minutes=1)))
    doc = lancer(base.migration_rapports.find_one({"id": "sauvegarde-prog"}))
    wa, repli = doc["envois"]
    assert wa["etat"] == "echec" and wa["code"] == 131042 and "moyen de paiement" in wa["explication"]
    assert repli["canal"] == "email" and repli["a"] == "sante@sawali.bf" and repli["par"] == "auto (repli)"
    assert doc["a_verifier"] is False and [e[0] for e in envois["email"]] == ["sante@sawali.bf"]
    # Pas de second repli
    lancer(mp.passage(MAINTENANT + timedelta(minutes=2)))
    assert len(envois["email"]) == 1


def test_whatsapp_remis_confirme_par_le_webhook(base, envois):
    lancer(base.migration_jobs.insert_one(sauvegarde("j1")))
    fenetre_ouverte(base, "22670000001")
    lancer(rap.envoyer("j1", rap.EnvoiIn(numeros="22670000001"), ADMIN))
    lancer(base.whatsapp_messages.insert_one({"message_id": "wamid.T1", "wa_status": "delivered"}))
    r = lancer(rap.lire_rapport("j1", ADMIN))
    assert r["envois"][0]["etat"] == "remis" and r["badge"]["etat"] == "whatsapp" and not r["a_verifier"]


# ---------------------------------------------------------------------------
# Destinataires du bloc
# ---------------------------------------------------------------------------
def test_destinataires_du_bloc_prioritaires(base, envois):
    lancer(base.settings.insert_one({"_id": "global", "liluvine_remote_admin_phones": ["22670000001"],
                                     "auto_snapshot_email_to": "snap@sawali.bf"}))
    cfg = mp.normaliser({"rapport_wa": "+226 76 00 00 01, 22676000002", "rapport_emails": "dg@sawali.bf; it@sawali.bf"})
    assert cfg["rapport_wa"] == ["22676000001", "22676000002"] and cfg["rapport_emails"] == ["dg@sawali.bf", "it@sawali.bf"]
    for n in cfg["rapport_wa"]:
        fenetre_ouverte(base, n)
    lancer(mp.envoyer_rapport("Sujet", "texte", cfg, important=True, maintenant=MAINTENANT))
    assert [n for n, _ in envois["texte"]] == ["22676000001", "22676000002"]
    # Repli e-mail : adresses du bloc (WhatsApp hors fenêtre et sans modèle)
    cfg2 = mp.normaliser({"rapport_emails": ["dg@sawali.bf"]})
    res = lancer(mp.envoyer_rapport("Sujet", "texte", cfg2, important=True, maintenant=MAINTENANT))
    assert res["whatsapp"][0]["a"] == "22670000001" and res["email"]["a"] == "dg@sawali.bf"
    with pytest.raises(ValueError, match="E-mail du rapport illisible"):
        mp.normaliser({"rapport_emails": "dg@sawali"})
    with pytest.raises(ValueError, match="Numéro WhatsApp du rapport illisible"):
        mp.normaliser({"rapport_wa": "12"})


def test_ligne_prochain_rapport_vers_calculee_par_le_serveur(base):
    # Numéros autorisés de la Jauge enregistrés sous forme de TEXTE séparé par virgules
    lancer(base.settings.insert_one({"_id": "global", "liluvine_remote_admin_phones": "22670000001, 22670000002",
                                     "health_email_to": "sante@sawali.bf"}))
    dest = lancer(mp.lire(ADMIN))["destinataires"]
    assert dest["whatsapp"] == ["22670000001", "22670000002"] and dest["source_whatsapp"].startswith("Jauge d'occupation")
    assert dest["ligne"].startswith("Le prochain rapport partira vers : WhatsApp +22670000001, +22670000002")
    assert "sante@sawali.bf (source : Santé applicative" in dest["ligne"]
    # Champs du bloc remplis : ils passent devant
    lancer(base.migration_programmation.insert_one({"_id": "parametres", "rapport_wa": ["22676000001"],
                                                    "rapport_emails": ["dg@sawali.bf"]}))
    dest = lancer(mp.lire(ADMIN))["destinataires"]
    assert "+22676000001 (source : champ « Numéros WhatsApp du rapport » de ce bloc)" in dest["ligne"]
    assert "dg@sawali.bf (source : champ « E-mails du rapport » de ce bloc)" in dest["ligne"]
    # Rien nulle part
    lancer(base.settings.delete_many({}))
    lancer(base.migration_programmation.delete_many({}))
    assert lancer(mp.lire(ADMIN))["destinataires"]["ligne"].startswith("Aucun destinataire")


def test_purger_maintenant_rapport_archive(base, envois, monkeypatch):
    async def fausse_purge(*_a, **_k):
        return {"le": mp._iso(MAINTENANT), "bucket": "seau", "examinees": 5, "objets": 2, "octets": 2048, "erreurs": 0,
                "gardees": 4, "raisons": {"dans la rétention": 4},
                "supprimees": [{"prefixe": "migration-20250101-000000", "objets": 2, "octets": 2048, "erreurs": 0}]}

    monkeypatch.setattr(mp, "purger", fausse_purge)
    lancer(base.settings.insert_one({"_id": "global", "auto_snapshot_email_to": "admin@sawali.bf"}))
    res = lancer(mp.purger_maintenant(ADMIN))
    doc = lancer(base.migration_rapports.find_one({"id": res["rapport"]["rapport_id"]}))
    assert doc["type"] == "purge" and "Rapport de purge" in doc["texte"]
    assert doc["donnees"]["supprimees"] == ["migration-20250101-000000"] and doc["envois"][0]["a"] == "admin@sawali.bf"
    resumes = lancer(rap.lister_rapports(ADMIN))
    assert resumes[0]["badge"]["etat"] == "email" and "texte" not in resumes[0] and resumes[0]["nb_envois"] == 1


# ---------------------------------------------------------------------------
# Nettoyage des chemins d'exemple (migration_render)
# ---------------------------------------------------------------------------
def test_nettoyage_des_references_et_chemins_d_exemple(base):
    assert mr._nettoyer_reference("sawali/sawali_global/a.png`.") == "sawali/sawali_global/a.png"
    assert mr._nettoyer_reference("/sawali/doc.pdf'),") == "sawali/doc.pdf"
    assert mr._est_exemple("sawali/sawali_global/mon_image.png") and mr._est_exemple("sawali_global/Exemple.JPG")
    assert not mr._est_exemple("sawali/autre/mon_image.png") and not mr._est_exemple("sawali/sawali_global/logo.png")

    async def scenario():
        # Un VRAI fichier homonyme d'un exemple, connu de `files` : jamais ignoré
        await base.files.insert_one({"id": "f1", "storage_path": "sawali/sawali_global/image.png"})
        await base.stored_objects.insert_one({"storage_path": "sawali/sawali_global/example.pdf"})
        refs = {("api", "sawali/sawali_global/mon_image.png`"): "aide",
                ("api", "sawali/sawali_global/fichier.png"): "aide",
                ("stockage", "sawali_global/exemple.jpg"): "invites",
                ("api", "sawali/sawali_global/image.png)"): "messages",
                ("api", "sawali/sawali_global/example.pdf"): "messages",
                ("api", "sawali/docs/vrai.pdf`"): "messages"}
        return await mr._chemins_emergent(refs)

    chemins, ignores = lancer(scenario())
    assert chemins == {"sawali/sawali_global/image.png": "files.storage_path",
                       "sawali/sawali_global/example.pdf": "stored_objects",
                       "sawali/docs/vrai.pdf": "messages (/api/files)"}
    assert ignores == {"disque": 0, "inconnu": 0, "exemples": 3}
