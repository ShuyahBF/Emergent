"""Lot 163 — offre du client (logiciels, produits, services) connue de Liluvine et refus d'assistance si contrat pas à jour :
normalisation, détection de l'objet, réglages, texte exact du refus, signature, ticket, escalade, routes. MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_lot163_offre_client.py -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.offre_client as oc  # noqa: E402


def lancer(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


OFFRE = oc.normaliser_offre([
    {"type": "logiciel", "nom": "SAWALI CRM", "version": "2.1"},
    {"type": "service", "nom": "Hébergement"},
    {"type": "produit", "nom": "Caisse", "actif": False},
])


def test_normalisation_de_l_offre():
    r = oc.normaliser_offre([{"nom": "  CRM  ", "type": "inconnu"}, {"nom": ""}, "x", {"id": "a", "nom": "A"}, {"id": "a", "nom": "B"}])
    assert [l["nom"] for l in r] == ["CRM", "A", "B"] and r[0]["type"] == "logiciel" and r[0]["actif"] is True
    assert len({l["id"] for l in r}) == 3                                    # identifiants uniques
    assert len(oc.normaliser_offre([{"nom": f"n{i}"} for i in range(100)])) == oc.MAX_LIGNES


def test_objet_detecte():
    assert oc.detecter_objet("Bonjour, j'ai un problème avec SAWALI CRM", OFFRE) == "la résolution du problème signalé de SAWALI CRM"
    assert oc.detecter_objet("Besoin de maintenance sur l'hébergement", OFFRE) == "la maintenance de Hébergement"
    assert oc.detecter_objet("Mon écran ne fonctionne plus", OFFRE) == "la résolution de la panne signalée"
    assert oc.detecter_objet("J'ai besoin d'une assistance", []) == "l'assistance demandée"
    # produit inactif : jamais cité ; messages sans demande d'assistance : rien
    assert oc.detecter_objet("panne de la caisse", OFFRE) == "la résolution de la panne signalée"
    assert oc.detecter_objet("Bonjour, merci beaucoup", OFFRE) is None
    assert oc.detecter_objet("Quels sont vos tarifs ?", OFFRE) is None


def test_reglages_et_texte_exact():
    assert oc.reglages({})["actif"] is False                                 # désactivé par défaut
    assert oc.texte_refus({}, "la maintenance de SAWALI CRM") == \
        "Notre assistance pour la maintenance de SAWALI CRM n'est pas disponible pour le moment. Contactez votre responsable."
    assert oc.reglages({"offre_client_message_refus": "sans variable"})["message"] == oc.MESSAGE_REFUS_DEFAUT
    assert oc.texte_refus({"offre_client_message_refus": "Indisponible : {objet}."}, "X") == "Indisponible : X."


def _contexte(monkeypatch, envoyes, tickets, escalades):
    async def faux_ticket(db, client, contact, objet, texte):
        tickets.append((client["id"], objet)); return {"id": "t1", "number": "ACME-2026-0001", "rattache": False}

    async def faux_notify(db, **kw):
        escalades.append(kw); return {"sent": True}
    monkeypatch.setattr(oc, "ouvrir_ticket", faux_ticket)
    import routes.liluvine_escalation as esc
    monkeypatch.setattr(esc, "notify_admin", faux_notify)

    async def envoyer(to, texte, **kw):
        envoyes.append((to, texte)); return {"ok": True}
    return envoyer


def _refuser(monkeypatch, *, actif=True, etat="retard", texte="Mon CRM est en panne", client="defaut"):
    envoyes, tickets, escalades = [], [], []
    envoyer = _contexte(monkeypatch, envoyes, tickets, escalades)
    c = {"id": "c1", "company": "ACME", "offre_client": OFFRE} if client == "defaut" else client
    r = lancer(oc.refuser_assistance(None, {"offre_client_refus_actif": actif}, contact={"id": "k1", "name": "Awa"}, texte=texte,
                                     etat_contrat=etat, client=c, phone_digits="22670112233", envoyer=envoyer, signature="— 🤖 Liluvine"))
    return r, envoyes, tickets, escalades


def test_refus_complet_si_contrat_en_retard(monkeypatch):
    r, envoyes, tickets, escalades = _refuser(monkeypatch)
    assert r["refuse"] and r["envoye"] and r["ticket"]["number"] == "ACME-2026-0001"
    assert envoyes == [("+22670112233", "Notre assistance pour la résolution de la panne signalée n'est pas disponible pour le moment. "
                                        "Contactez votre responsable.\n\n— 🤖 Liluvine")]            # texte exact + signature IA
    assert len(tickets) == 1 and len(escalades) == 1 and "ACME-2026-0001" in escalades[0]["reason"]


@pytest.mark.parametrize("cas", [dict(actif=False), dict(etat="valide"), dict(etat=None), dict(texte="Bonjour, merci"), dict(client=None)])
def test_pas_de_refus(monkeypatch, cas):
    r, envoyes, tickets, escalades = _refuser(monkeypatch, **cas)
    assert not r["refuse"] and envoyes == [] and tickets == [] and escalades == []     # à jour, désactivé, non analysable, pas d'assistance


def test_bloc_prompt():
    b = oc.bloc_prompt("ACME", OFFRE)
    assert "SAWALI CRM" in b and "v2.1" in b and "Hébergement" in b and "Caisse" not in b and "JAMAIS" in b
    assert oc.bloc_prompt("ACME", []) == ""


def test_bloc_prompt_limite_l_assistance_a_l_offre():
    """Lot 336 — cas réel (28/10/2026) : le client n'a que e-KOL ; l'assistant a pourtant aidé pour la mise à jour d'un autre logiciel (Aizenta).
    Le prompt doit borner l'assistance aux logiciels, produits et services de l'offre et faire escalader le reste."""
    b = oc.bloc_prompt("ECOLE DES METIERS", [{"type": "logiciel", "nom": "e-KOL", "actif": True}])
    assert "e-KOL" in b and "PÉRIMÈTRE" in b and "QUE sur les logiciels" in b and "n'y figure PAS" in b and "AUCUNE aide technique" in b
    assert "marqueur d'escalade" in b


def test_routes_offre_et_reglages():
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    base = mongomock_motor.AsyncMongoMockClient()["sawali_t163"]
    lancer(base.users.insert_one({"id": "c1", "company": "ACME"}))
    app, api = FastAPI(), APIRouter(prefix="/api")
    oc.setup_offre_client_routes(db=base, api=api, get_current_admin=lambda: {"id": "a", "full_name": "Admin"})
    app.include_router(api)
    c = TestClient(app)
    assert c.get("/api/admin/clients/zz/offre").status_code == 404
    r = c.put("/api/admin/clients/c1/offre", json={"lignes": [{"nom": "CRM", "type": "logiciel"}, {"nom": ""}]}).json()
    assert [l["nom"] for l in r["lignes"]] == ["CRM"] and r["maj"]["par"] == "Admin"
    assert c.get("/api/admin/clients/c1/offre").json()["lignes"][0]["nom"] == "CRM"
    assert c.get("/api/admin/offre-client/reglages").json() == {"actif": False, "message": oc.MESSAGE_REFUS_DEFAUT,
                                                                "message_defaut": oc.MESSAGE_REFUS_DEFAUT, "clients_avec_offre": 1}
    assert c.put("/api/admin/offre-client/reglages", json={"actif": True, "message": "sans variable"}).status_code == 422
    assert c.put("/api/admin/offre-client/reglages", json={"actif": True, "message": ""}).json()["actif"] is True


def test_lot169_copie_de_l_offre_d_un_client_a_d_autres():
    """Lot 169 — copie d'un client vers d'autres : remplacer / ajouter sans doublon, identifiants neufs, source intacte."""
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    base = mongomock_motor.AsyncMongoMockClient()["sawali_t169"]
    lancer(base.users.insert_many([
        {"id": "src", "company": "SOURCE", "offre_client": [{"id": "a1", "type": "logiciel", "nom": "SAWALI CRM", "version": "2"},
                                                            {"id": "a2", "type": "service", "nom": "Hébergement"}]},
        {"id": "c1", "company": "Cible Un", "offre_client": [{"id": "x", "type": "logiciel", "nom": "sawali crm"},
                                                              {"id": "y", "type": "produit", "nom": "Caisse"}]},
        {"id": "c2", "company": "Cible Deux"},
        {"id": "adm", "role": "admin", "company": "Admin"}]))
    app, api = FastAPI(), APIRouter(prefix="/api")
    oc.setup_offre_client_routes(db=base, api=api, get_current_admin=lambda: {"id": "a", "full_name": "Admin"})
    app.include_router(api)
    c = TestClient(app)
    liste = c.get("/api/admin/offre-client/clients").json()["clients"]
    assert [x["nom"] for x in liste] == ["Cible Deux", "Cible Un", "SOURCE"] and {x["id"]: x["nb_lignes"] for x in liste}["src"] == 2
    # Ajouter : « sawali crm » existe déjà (même type + même nom, sans tenir compte de la casse) → seule « Hébergement » est ajoutée
    r = c.post("/api/admin/offre-client/copier", json={"source_id": "src", "cible_ids": ["c1", "c2", "zz", "src"], "mode": "ajouter"}).json()
    assert r["source"] == "SOURCE" and r["clients"] == 2 and r["copiees"] == 3
    assert [x["copiees"] for x in r["resultat"] if x["ok"]] == [1, 2] and r["resultat"][2]["ok"] is False
    c1 = c.get("/api/admin/clients/c1/offre").json()
    assert [l["nom"] for l in c1["lignes"]] == ["sawali crm", "Caisse", "Hébergement"] and c1["maj"]["copie_de"] == "SOURCE"
    # Listes indépendantes : identifiants neufs, la source est intacte
    ids_c2 = {l["id"] for l in c.get("/api/admin/clients/c2/offre").json()["lignes"]}
    assert not ({"a1", "a2"} & ids_c2) and len(ids_c2) == 2
    assert [l["id"] for l in c.get("/api/admin/clients/src/offre").json()["lignes"]] == ["a1", "a2"]
    # Remplacer : la liste de la cible devient celle de la source
    c.post("/api/admin/offre-client/copier", json={"source_id": "src", "cible_ids": ["c1"], "mode": "remplacer"})
    assert [l["nom"] for l in c.get("/api/admin/clients/c1/offre").json()["lignes"]] == ["SAWALI CRM", "Hébergement"]
    # Refus : source inconnue, source vide, mode inconnu
    assert c.post("/api/admin/offre-client/copier", json={"source_id": "zz", "cible_ids": ["c1"]}).status_code == 404
    assert c.post("/api/admin/offre-client/copier", json={"source_id": "c2x", "cible_ids": ["c1"]}).status_code == 404
    lancer(base.users.insert_one({"id": "vide", "company": "Vide"}))
    assert c.post("/api/admin/offre-client/copier", json={"source_id": "vide", "cible_ids": ["c1"]}).status_code == 409
    assert c.post("/api/admin/offre-client/copier", json={"source_id": "src", "cible_ids": ["c1"], "mode": "x"}).status_code == 422


def test_lot178_offre_appliquee_sur_la_ligne_de_la_plateforme():
    """Lot 178 : l'offre du client est lue quand un CLIENT de SAWALI écrit sur la ligne de la plateforme (avant : condition inversée)."""
    from routes.liluvine_wa_autoreply import offre_du_client_applicable as ok
    assert ok(is_prospect=False, platform_tenant=True) is True      # client de SAWALI sur la ligne SAWALI : offre lue
    assert ok(is_prospect=True, platform_tenant=True) is False      # prospect : aucune offre
    assert ok(is_prospect=False, platform_tenant=False) is False    # ligne d'un client (tenant) : ses contacts ne sont pas des clients de SAWALI


# ---------------------------------------------------------------------------------------------------------------------
# Lot 337 — l'historique rejoué ne ramène pas un logiciel absent de l'offre
# ---------------------------------------------------------------------------------------------------------------------
def test_lot337_historique_sans_logiciel_hors_offre():
    from routes import offre_client as O
    offre = O.normaliser_offre([{"type": "logiciel", "nom": "e-KOL"}, {"type": "logiciel", "nom": "Bitdefender Standard"}])
    autre = O.normaliser_offre([{"type": "logiciel", "nom": "Aizenta"}, {"type": "logiciel", "nom": "Bitdefender Business"}])
    absents = (O.mots_logiciels(offre) | O.mots_logiciels(autre)) - O.mots_logiciels(offre)
    assert absents == {"aizenta"}                       # Bitdefender est dans l'offre : jamais retiré
    docs = [{"role": "user", "content": "la liste de classe"},
            {"role": "assistant", "content": "Je remonte votre demande pour les listes dans AIZENTA."},
            {"role": "user", "content": "Ok"},
            {"role": "assistant", "content": "Un souci avec Bitdefender ?"}]
    restant = O.retirer_mentions_hors_offre(docs, absents)
    assert [d["content"] for d in restant] == ["la liste de classe", "Ok", "Un souci avec Bitdefender ?"]   # seule la réponse fautive part
    assert O.retirer_mentions_hors_offre(docs, set()) == docs
    # Les messages du CLIENT ne sont jamais retirés, même s'il cite le logiciel
    assert O.retirer_mentions_hors_offre([{"role": "user", "content": "Aizenta ne marche pas"}], absents)
