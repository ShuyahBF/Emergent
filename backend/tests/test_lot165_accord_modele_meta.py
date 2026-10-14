"""Lot 165 — modèle Meta de demande d'accord à lien personnel : définition, essai des deux formes d'exemple d'adresse,
modèle déjà existant, statut et motif. Client HTTP simulé (aucun appel réseau).
Lancer : cd backend && python -m pytest tests/test_lot165_accord_modele_meta.py -q
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import routes.accord_modele_meta as amm  # noqa: E402

URL = "https://sawali.test/accord/{{1}}"


def lancer(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_definition_du_modele_calquee_sur_le_modele_approuve():
    d = amm.definition_modele("sawali_accord_lien", "fr", URL)
    types = [c["type"] for c in d["components"]]
    assert types == ["HEADER", "BODY", "FOOTER", "BUTTONS"]           # même structure que « envoidemandeaccordcarroussel »
    entete, corps, pied, boutons = d["components"]
    assert d["category"] == "MARKETING" and entete["format"] == "TEXT" and len(entete["text"]) <= 60 and len(pied["text"]) <= 60
    assert corps["text"].count("{{") == 1 and len(corps["example"]["body_text"][0]) == 1       # UNE seule variable (prénom)
    assert not corps["text"].startswith("{{") and not corps["text"].rstrip().endswith("}}")      # règle Meta : pas aux extrémités
    oui, non = boutons["buttons"]
    assert oui["type"] == "URL" and oui["url"] == URL and oui["example"] == ["https://sawali.test/accord/exemple"]
    assert non["type"] == "QUICK_REPLY" and "NON" in non["text"]
    assert amm.PAYLOAD_NON == "accord_wa:non"
    assert amm.definition_modele("n", "fr", URL, exemple_url_complete=False)["components"][3]["buttons"][0]["example"] == ["exemple"]


def client(reponses, appels):
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        appels.append((requete.method, json.loads(requete.content or b"{}")))
        return reponses.pop(0)
    return httpx.AsyncClient(transport=httpx.MockTransport(gestionnaire))


def creer(reponses):
    appels: list = []
    c = client(reponses, appels)
    r = lancer(amm.creer_modele(version="v22.0", waba_id="W", jeton="J", nom="sawali_accord_lien", langue="fr", url_bouton=URL, client=c))
    return r, appels


def test_creation_acceptee_du_premier_coup():
    r, appels = creer([httpx.Response(200, json={"id": "1", "status": "PENDING"})])
    assert r == {"nom": "sawali_accord_lien", "statut": "soumis", "detail": "PENDING"} and len(appels) == 1


def test_seconde_forme_essayee_si_meta_refuse_l_exemple():
    erreur = httpx.Response(400, json={"error": {"error_user_msg": "Exemple d'URL invalide"}})
    r, appels = creer([erreur, httpx.Response(200, json={"status": "PENDING"})])
    assert r["statut"] == "soumis" and len(appels) == 2
    assert appels[0][1]["components"][3]["buttons"][0]["example"][0].startswith("https://")
    assert appels[1][1]["components"][3]["buttons"][0]["example"] == ["exemple"]


def test_deux_refus_donnent_l_erreur_de_meta():
    erreur = httpx.Response(400, json={"error": {"message": "Paramètre invalide"}})
    r, appels = creer([erreur, erreur])
    assert r["statut"] == "erreur" and "invalide" in r["detail"] and len(appels) == 2


def test_modele_deja_existant_n_est_pas_une_panne():
    r, appels = creer([httpx.Response(400, json={"error": {"error_user_msg": "Content in this language already exists"}})])
    assert r["statut"] == "existe déjà" and len(appels) == 1


def statut(donnees):
    c = client([httpx.Response(200, json={"data": donnees})], [])
    return lancer(amm.lire_statut(version="v22.0", waba_id="W", jeton="J", nom="sawali_accord_lien", langue="fr", client=c))


def test_statuts():
    assert statut([]) ["statut"] == "ABSENT"
    assert statut([{"name": "sawali_accord_lien", "language": "fr", "status": "APPROVED", "rejected_reason": "NONE"}]) == \
        {"statut": "APPROVED", "motif": None, "erreur": None}
    r = statut([{"name": "sawali_accord_lien", "language": "fr", "status": "REJECTED", "rejected_reason": "INVALID_FORMAT"}])
    assert r["statut"] == "REJECTED" and r["motif"] == "INVALID_FORMAT"
    assert statut([{"name": "autre", "language": "fr", "status": "APPROVED"}])["statut"] == "ABSENT"
