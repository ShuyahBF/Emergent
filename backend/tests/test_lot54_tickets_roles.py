"""Lot 54 — Tickets Liluvine partagés par client (clôture vers l'historique d'intervention,
validité, facturation, sessions WhatsApp minutées avec rappels T-10 / T-5), pastille de présence
des utilisateurs suivis, rôle « Auxiliaire en Pharmacie » (contrôle serveur) et règle d'Outils+
pour « Ordonnances et stock ».
MongoDB simulé (mongomock_motor), envoi WhatsApp simulé, vrais jetons JWT et vraie dépendance
auth.get_current_user pour le contrôle du rôle.
Lancer : cd backend && python -m pytest tests/test_lot54_tickets_roles.py -q
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot54")

from fastapi import APIRouter, Depends, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import abonnement_acces as abo  # noqa: E402
import auth  # noqa: E402
import controle_acces  # noqa: E402
import cycle_vie_abonnements as cva  # noqa: E402
import maintenance_plateforme as mp  # noqa: E402
import roles_restreints as rr  # noqa: E402
import sessions_comptes as sess  # noqa: E402
import tickets_clients as tc  # noqa: E402
import routes.presence_utilisateurs as pres  # noqa: E402
from routes.fonctions_clients import attach_fonctions_clients_routes  # noqa: E402
from routes.ordonnances_stock import attach_ordonnances_stock_routes  # noqa: E402

UTC = timezone.utc
JWT = "secret-tests-0123456789-abcdef"
T0 = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)


def _iso(d):
    return d.isoformat()


class FauxEnvoi:
    """Envoi WhatsApp simulé : enregistre (numéro, texte)."""

    def __init__(self, ok=True):
        self.envois, self.ok = [], ok

    async def __call__(self, to, texte, tenant_id=None, **_):
        self.envois.append((to, texte))
        return {"ok": self.ok, "message_id": f"wamid.{len(self.envois)}", "error": None if self.ok else "refus"}


@pytest.fixture()
def env(monkeypatch):
    b = mongomock_motor.AsyncMongoMockClient()[f"lot54_{time.time_ns()}"]
    for mod in (tc, pres, auth, mp, sess, abo, cva):
        monkeypatch.setattr(mod, "db", b)
    monkeypatch.setenv("JWT_SECRET", JWT)
    monkeypatch.setattr(auth, "JWT_SECRET", JWT, raising=False)
    monkeypatch.delenv("SUPER_ADMIN_EMAIL", raising=False)
    tc._index_ok["fait"] = False
    mp.vider_cache()
    sess.vider_caches()
    abo.vider_cache()
    boucle = asyncio.new_event_loop()

    class Env:
        pass
    e = Env()
    e.db, e.run = b, boucle.run_until_complete
    e.run(b.users.insert_many([
        {"id": "plateforme", "email": "admin@sawalismartsystems.com", "role": "admin", "account_status": "active"},
        # Client sans contrat : validité 2 h, session WhatsApp 30 mn, tarifs
        {"id": "pharma", "email": "pharma@x.bf", "role": "client", "company": "Pharmacie Lot", "client_code": "PLOT",
         "account_status": "active", "hourly_rate": 10000, "flat_rate": 45000, "ticket_validite_heures": 2,
         "ticket_session_wa_minutes": 30,
         "ticket_message_rappel": "Reste {X} mn — ticket {Y} — sessions de {Z} mn"},
        # Client sous contrat : pas de validité
        {"id": "contrat", "email": "c@x.bf", "role": "client", "company": "Clinique", "contract_number": "C-1",
         "account_status": "active", "hourly_rate": 5000, "flat_rate": 0},
    ]))
    e.run(b.directory_contacts.insert_many([
        {"id": "ca", "client_id": "pharma", "name": "Awa", "whatsapp": "+22670000001"},
        {"id": "cb", "client_id": "pharma", "name": "Boris", "whatsapp": "+22670000002"},
        {"id": "cx", "client_id": "plateforme", "name": "Inconnu", "whatsapp": "+22670000009"},
    ]))
    yield e
    boucle.close()


async def _ticket(b, *, client_id="pharma", contact_id="ca", ouvert=T0, numero="PLOT-2026-0001", **extra):
    client = await b.users.find_one({"id": client_id}, {"_id": 0})
    t = {"id": f"t-{numero}", "number": numero, "client_id": client_id, "contact_id": contact_id,
         "contact_ids": [contact_id], "contact_name": "Awa", "contact_phone": "+22670000001", "motif": "BLOCAGE",
         "status": "open", "opened_at": _iso(ouvert), "archived_at": None, **tc.champs_creation(client, _iso(ouvert)),
         **extra}
    await b.support_tickets.insert_one(dict(t))
    return t


async def _entrant(b, chiffres, quand):
    await b.whatsapp_messages.insert_one({"id": f"in-{chiffres}-{quand.timestamp()}", "direction": "inbound",
                                          "phone_digits": chiffres, "client_id": "plateforme",
                                          "received_at": _iso(quand), "created_at": _iso(quand)})


# ---------------------------------------------------------------------------
# 1. Ticket partagé entre les contacts du client
# ---------------------------------------------------------------------------
def test_ticket_partage_entre_contacts_du_client(env):
    b = env.db
    t = env.run(_ticket(b))
    # Boris (autre contact du même client) est couvert par le ticket ouvert via Awa
    trouve = env.run(tc.ticket_ouvert_pour_contact("cb"))
    assert trouve and trouve["id"] == t["id"]
    # Le carnet de l'opérateur (plateforme) ne rattache pas ses contacts aux tickets des clients
    assert env.run(tc.ticket_ouvert_pour_contact("cx")) is None
    # Conversation reçue sur le numéro du client lui-même (ses propres contacts, ses patients) :
    # pas couverte par le ticket de support de ce client
    assert env.run(tc.ticket_ouvert_pour_contact("cb", scope_conversation="pharma")) is None
    assert env.run(tc.noter_action_liluvine(inbound={"id": "m0", "client_id": "pharma"},
                                            contact={"id": "cb", "client_id": "pharma"}, resultat={"ok": True})) is None
    # Liluvine agit dans la conversation de Boris : action notée sous le ticket, contact rattaché
    env.run(b.whatsapp_messages.insert_one({"id": "m1", "direction": "inbound", "phone_digits": "22670000002"}))
    tid = env.run(tc.noter_action_liluvine(inbound={"id": "m1"}, contact={"id": "cb", "client_id": "pharma"},
                                            resultat={"ok": True, "command": "!garde"}))
    assert tid == t["id"]
    doc = env.run(b.support_tickets.find_one({"id": t["id"]}))
    assert set(doc["contact_ids"]) == {"ca", "cb"}
    assert doc["liluvine_actions_total"] == 1 and doc["liluvine_actions"][0]["commande"] == "!garde"
    assert env.run(b.whatsapp_messages.find_one({"id": "m1"}))["ticket_id"] == t["id"]
    assert env.run(b[tc.JOURNAL].count_documents({"evenement": "contact_rattache", "contact_id": "cb"})) == 1
    # Un seul ticket ouvert pour ce client : pas de nouveau ticket tant qu'il est ouvert
    assert env.run(tc.ticket_ouvert_du_client("pharma"))["id"] == t["id"]
    # Une fois clôturé, le contact n'est plus couvert
    env.run(tc.cloturer_ticket(doc, outcome="done", acteur={"id": "u1", "full_name": "Tech"}, quand=T0 + timedelta(hours=1)))
    assert env.run(tc.ticket_ouvert_pour_contact("cb")) is None


# ---------------------------------------------------------------------------
# 2. Clôture → historique d'intervention ; 4. facturation
# ---------------------------------------------------------------------------
def test_cloture_reporte_debut_fin_et_lien_dans_historique(env):
    b = env.db
    t = env.run(_ticket(b))
    fin = T0 + timedelta(hours=1, minutes=30)
    r = env.run(tc.cloturer_ticket(t, outcome="done", acteur={"id": "u1", "full_name": "Tech", "role": "admin"},
                                   note="Réglé", quand=fin))
    assert r["ok"]
    inter = env.run(b.interventions.find_one({"source_ticket_id": t["id"]}, {"_id": 0}))
    assert inter["date_heure_debut"] == _iso(T0) and inter["date_heure_fin"] == _iso(fin)
    assert inter["source_ticket_number"] == "PLOT-2026-0001"
    assert inter["ticket_url"] == "/portal/tickets?numero=PLOT-2026-0001"
    assert inter["duration_hours"] == 1.5 and inter["intervention_number"].startswith("INT-2026-PLOT-")
    ticket = env.run(b.support_tickets.find_one({"id": t["id"]}))
    assert ticket["status"] == "done" and ticket["intervention_id"] == inter["id"]
    # 1,5 h < 5 h : coût horaire × durée
    assert ticket["cost_mode"] == "hourly" and ticket["cost_amount"] == 15000
    # Clôture unique
    assert env.run(tc.cloturer_ticket(t, outcome="done", acteur={"id": "u1"}, quand=fin))["ok"] is False
    assert env.run(b.interventions.count_documents({"source_ticket_id": t["id"]})) == 1


def test_facturation_horaire_sous_le_seuil_forfait_au_dela():
    client = {"hourly_rate": 10000, "flat_rate": 45000}
    assert tc.calculer_facturation(4.99, client)["cost_mode"] == "hourly"
    assert tc.calculer_facturation(4.99, client)["cost_amount"] == 49900
    assert tc.calculer_facturation(5, client)["cost_mode"] == "flat"
    assert tc.calculer_facturation(5, client)["cost_amount"] == 45000
    assert tc.calculer_facturation(9, client)["cost_amount"] == 45000
    # Seuil réglable sur la fiche
    assert tc.calculer_facturation(3, {**client, "ticket_seuil_forfait_heures": 3})["cost_mode"] == "flat"
    assert tc.calculer_facturation(3, {**client, "ticket_seuil_forfait_heures": 0})["cost_threshold_hours"] == 5
    # Sans forfait renseigné : horaire au-delà du seuil (signalé)
    r = tc.calculer_facturation(6, {"hourly_rate": 1000, "flat_rate": 0})
    assert r["cost_mode"] == "hourly_sans_forfait" and r["cost_amount"] == 6000


def test_cloture_au_dela_de_5h_applique_le_forfait(env):
    b = env.db
    t = env.run(_ticket(b, numero="PLOT-2026-0002"))
    env.run(tc.cloturer_ticket(t, outcome="done", acteur={"id": "u1"}, quand=T0 + timedelta(hours=6)))
    ticket = env.run(b.support_tickets.find_one({"id": t["id"]}))
    assert ticket["cost_mode"] == "flat" and ticket["cost_amount"] == 45000 and ticket["active_hours"] == 6


# ---------------------------------------------------------------------------
# 3. Validité (clients non contractuels)
# ---------------------------------------------------------------------------
def test_expiration_du_ticket_client_non_contractuel(env):
    b = env.db
    t = env.run(_ticket(b))
    assert t["validite_expire_le"] == _iso(T0 + timedelta(hours=2)) and t["client_contractuel"] is False
    # Client sous contrat : pas de validité
    sous_contrat = tc.champs_creation(env.run(b.users.find_one({"id": "contrat"})), _iso(T0))
    assert sous_contrat["validite_expire_le"] is None and sous_contrat["client_contractuel"] is True
    # Pas encore échu (la session WhatsApp est neutralisée pour isoler la validité)
    env.run(b.support_tickets.update_one({"id": t["id"]}, {"$set": {"session_wa_fin": None}}))
    env.run(tc.executer_echeances(envoyer=FauxEnvoi(), quand=T0 + timedelta(hours=1, minutes=59)))
    assert env.run(b.support_tickets.find_one({"id": t["id"]}))["status"] == "open"
    bilan = env.run(tc.executer_echeances(envoyer=FauxEnvoi(), quand=T0 + timedelta(hours=2, minutes=1)))
    assert bilan["expirations"] == 1
    doc = env.run(b.support_tickets.find_one({"id": t["id"]}))
    assert doc["status"] == "done" and doc["cloture_auto"] == "validite_expiree"
    assert env.run(b[tc.JOURNAL].count_documents({"ticket_id": t["id"], "evenement": "validite_expiree"})) == 1
    assert env.run(b.interventions.count_documents({"source_ticket_id": t["id"]})) == 1
    # Passage suivant : rien de plus
    assert env.run(tc.executer_echeances(quand=T0 + timedelta(hours=3)))["expirations"] == 0


# ---------------------------------------------------------------------------
# 5. Session WhatsApp : rappels uniques T-10 / T-5 puis fermeture
# ---------------------------------------------------------------------------
def test_rappels_uniques_t10_t5_puis_fermeture(env):
    b = env.db
    t = env.run(_ticket(b, validite_expire_le=None))
    env.run(b.support_tickets.update_one({"id": t["id"]}, {"$set": {"validite_expire_le": None,
                                                                    "contact_ids": ["ca", "cb"]}}))
    env.run(_entrant(b, "22670000001", T0 + timedelta(minutes=2)))   # Awa : fenêtre 24 h ouverte
    # Boris n'a jamais écrit : fenêtre fermée → rappel non envoyé, journalisé
    envoi = FauxEnvoi()
    passe = lambda m, s=0: env.run(tc.executer_echeances(envoyer=envoi, quand=T0 + timedelta(minutes=m, seconds=s)))  # noqa: E731
    passe(19)
    assert envoi.envois == []
    passe(20, 1)                                  # T-10
    assert envoi.envois == [("+22670000001", "Reste 10 mn — ticket PLOT-2026-0001 — sessions de 30 mn")]
    passe(21)
    passe(22)
    assert len(envoi.envois) == 1                 # envoyé une seule fois
    passe(25)                                     # T-5
    assert envoi.envois[-1] == ("+22670000001", "Reste 5 mn — ticket PLOT-2026-0001 — sessions de 30 mn")
    passe(26)
    assert len(envoi.envois) == 2
    journal = env.run(b[tc.JOURNAL].find({"ticket_id": t["id"]}, {"_id": 0}).to_list(50))
    refus = [j for j in journal if j["evenement"] == "rappel_t10_non_envoye"]
    assert refus and refus[0]["raison"] == "fenetre_24h_fermee" and refus[0]["contact_id"] == "cb"
    # Copie du rappel dans le fil de la conversation
    assert env.run(b.whatsapp_messages.count_documents({"ticket_id": t["id"], "direction": "outbound"})) == 2
    passe(30)                                     # fin de session : fermeture + message de clôture
    doc = env.run(b.support_tickets.find_one({"id": t["id"]}))
    assert doc["status"] == "done" and doc["cloture_auto"] == "session_wa_expiree"
    assert "PLOT-2026-0001" in envoi.envois[-1][1] and "30 mn" in envoi.envois[-1][1]
    assert len(envoi.envois) == 3
    passe(31)
    assert len(envoi.envois) == 3
    assert env.run(b.interventions.count_documents({"source_ticket_id": t["id"]})) == 1


def test_rappel_t10_manque_seul_le_t5_part(env):
    b = env.db
    t = env.run(_ticket(b, numero="PLOT-2026-0003"))
    env.run(b.support_tickets.update_one({"id": t["id"]}, {"$set": {"validite_expire_le": None}}))
    env.run(_entrant(b, "22670000001", T0))
    envoi = FauxEnvoi()
    env.run(tc.executer_echeances(envoyer=envoi, quand=T0 + timedelta(minutes=26)))
    assert len(envoi.envois) == 1 and envoi.envois[0][1].startswith("Reste 4 mn")
    doc = env.run(b.support_tickets.find_one({"id": t["id"]}))
    assert sorted(doc["rappels_envoyes"]) == [5, 10]
    assert env.run(b[tc.JOURNAL].count_documents({"evenement": "rappel_saute", "palier_minutes": 10})) == 1


def test_duree_de_session_modifiable_par_ticket_et_modele_par_defaut(env):
    b = env.db
    t = env.run(_ticket(b, numero="PLOT-2026-0004"))
    t = env.run(tc.regler_session(t, 60, par={"email": "admin@x"}))
    assert t["session_wa_fin"] == _iso(T0 + timedelta(minutes=60))
    assert tc.remplir_modele(tc.MESSAGE_RAPPEL_DEFAUT, x=10, y="N-1", z=30) == (
        "Il vous reste 10 mn avant la fermeture automatique de ce ticket n°N-1. "
        "Parce que d'autres interventions nous attendent, nos sessions sont limitées à 30 mn.")
    # 0 = pas de limite : plus d'échéance
    t = env.run(tc.regler_session(t, 0, par={"email": "admin@x"}))
    assert t["session_wa_fin"] is None


# ---------------------------------------------------------------------------
# Présence des utilisateurs suivis
# ---------------------------------------------------------------------------
def test_pastille_de_presence_seuils(env):
    maintenant = datetime.now(UTC)
    assert pres.etat(maintenant - timedelta(minutes=4, seconds=59), True, maintenant) == pres.VERT
    assert pres.etat(maintenant - timedelta(minutes=5, seconds=1), True, maintenant) == pres.ORANGE
    assert pres.etat(maintenant - timedelta(minutes=10), True, maintenant) == pres.ORANGE
    assert pres.etat(maintenant - timedelta(minutes=10, seconds=1), True, maintenant) == pres.ROUGE
    assert pres.etat(maintenant, False, maintenant) == pres.ROUGE
    b = env.db
    env.run(b.sessions_comptes.insert_many([
        {"id": "s1", "user_id": "u-vert", "fermee_le": None, "expire_a": maintenant + timedelta(hours=2),
         "ouverte_le": _iso(maintenant - timedelta(hours=1)), "derniere_interaction": _iso(maintenant - timedelta(minutes=1)),
         "derniere_activite": _iso(maintenant)},
        # Onglet ouvert, sondages automatiques récents, mais aucune interaction depuis 7 mn → orange
        {"id": "s2", "user_id": "u-orange", "fermee_le": None, "expire_a": maintenant + timedelta(hours=2),
         "ouverte_le": _iso(maintenant - timedelta(hours=1)), "derniere_interaction": _iso(maintenant - timedelta(minutes=7)),
         "derniere_activite": _iso(maintenant)},
        {"id": "s3", "user_id": "u-ferme", "fermee_le": _iso(maintenant), "expire_a": maintenant + timedelta(hours=2),
         "derniere_interaction": _iso(maintenant)},
    ]))
    p = env.run(pres.presence(["u-vert", "u-orange", "u-ferme", "u-absent"], maintenant))
    assert p["u-vert"]["etat"] == pres.VERT and p["u-orange"]["etat"] == pres.ORANGE
    assert p["u-ferme"]["etat"] == pres.ROUGE and p["u-absent"]["etat"] == pres.ROUGE


# ---------------------------------------------------------------------------
# Rôle « Auxiliaire en Pharmacie » (contrôle serveur) et règle d'Outils+
# ---------------------------------------------------------------------------
def test_auxiliaire_liste_des_routes_permises():
    ok = [("GET", "/api/vidal/search/parsed"), ("GET", "/api/vidal/product/123/detail"),
          ("GET", "/api/vidal/vmp/9/equivalents"), ("POST", "/api/ordonnances-stock"),
          ("GET", "/api/ordonnances-stock"), ("GET", "/api/ordonnances-stock/abc"), ("GET", "/api/auth/me"),
          ("POST", "/api/me/activite"), ("GET", "/api/me/features")]
    refus = [("GET", "/api/me/tickets"), ("POST", "/api/ordonnances-stock/abc/reserver"),
             ("PUT", "/api/ordonnances-stock/abc/lignes/0"), ("DELETE", "/api/ordonnances-stock/abc"),
             ("GET", "/api/stock-produits"), ("GET", "/api/stock-produits/depots"), ("GET", "/api/admin/clients"),
             ("POST", "/api/vidal/product/123/detail"), ("GET", "/api/me/contacts")]
    assert all(rr.chemin_permis(m, c) for m, c in ok)
    assert not any(rr.chemin_permis(m, c) for m, c in refus)
    assert rr.est_auxiliaire({"role": "client", "tracked_role": "Auxiliaire en Pharmacie"})
    assert not rr.est_auxiliaire({"role": "admin", "tracked_role": "Auxiliaire en Pharmacie"})
    assert not rr.est_auxiliaire({"role": "client", "tracked_role": "Pharmacien"})


def _png() -> bytes:
    from PIL import Image
    tampon = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(tampon, format="PNG")
    return tampon.getvalue()


def _app(env, features_pharma: dict):
    """Application de test : vraie dépendance auth.get_current_user (contrôle du rôle compris),
    vraie règle d'Outils+ (fonction_active) et vraies routes « Ordonnances et stock »."""
    b = env.db
    env.run(b.users.update_one({"id": "pharma"}, {"$set": {"features": features_pharma}}))
    env.run(b.users.insert_many([
        {"id": "aux", "email": "aux@x.bf", "role": "client", "tracked_role": "Auxiliaire en Pharmacie",
         "parent_client_id": "pharma", "client_id": "pharma", "account_status": "active"},
        {"id": "aux2", "email": "aux2@x.bf", "role": "client", "tracked_role": "Auxiliaire en Pharmacie",
         "parent_client_id": "pharma", "client_id": "pharma", "account_status": "active"},
        {"id": "phm", "email": "phm@x.bf", "role": "client", "tracked_role": "Pharmacien",
         "parent_client_id": "pharma", "client_id": "pharma", "account_status": "active"},
    ]))
    app = FastAPI()
    app.add_exception_handler(controle_acces.RefusAcces, controle_acces.gestionnaire_refus)
    api = APIRouter(prefix="/api")

    async def admin_ou_sup(user: dict = Depends(auth.get_current_user)):
        return user
    outils = attach_fonctions_clients_routes(api=api, db=b, get_current_user=auth.get_current_user,
                                             get_admin_or_supervisor=admin_ou_sup,
                                             normalize_features=lambda f: dict(f or {}), now=lambda: "x")

    async def lire(images):
        return {"date_ordonnance": "01/10/2026", "lignes": [{"nom": "DOLIPRANE", "dosage": "1 g", "quantite": 2}]}
    attach_ordonnances_stock_routes(api=api, db=b, get_current_user=auth.get_current_user,
                                    fonction_active=outils["fonction_active"], lire_ordonnance=lire)

    @api.get("/vidal/product/{pid}/detail")
    async def fiche(pid: str, user: dict = Depends(auth.get_current_user)):
        return {"vidal_id": pid}

    @api.get("/me/tickets")
    async def tickets(user: dict = Depends(auth.get_current_user)):
        return []
    app.include_router(api)
    return TestClient(app)


def _h(uid):
    return {"Authorization": f"Bearer {auth.create_access_token(uid, 'client')}"}


def test_auxiliaire_acces_permis_et_refuse(env):
    env.run(env.db.users.update_one({"id": "pharma"}, {"$set": {"client_code": "PLOT"}}))
    c = _app(env, {"ordonnances_stock": True})
    # Permis : Fiche Produit / Posologie (VIDAL) et scan + OCR
    assert c.get("/api/vidal/product/42/detail", headers=_h("aux")).status_code == 200
    r = c.post("/api/ordonnances-stock", headers=_h("aux"), files=[("photos", ("o.png", _png(), "image/png"))])
    assert r.status_code == 200, r.text
    vue = r.json()
    assert vue["ocr_seulement"] is True and vue["lignes"][0]["nom"] == "DOLIPRANE"
    assert "statut" not in vue["lignes"][0] and "reservation" not in vue["lignes"][0]
    oid = vue["id"]
    assert c.get(f"/api/ordonnances-stock/{oid}", headers=_h("aux")).json()["ocr_seulement"] is True
    # Historique : seulement SES ordonnances scannées
    r2 = c.post("/api/ordonnances-stock", headers=_h("phm"), files=[("photos", ("o.png", _png(), "image/png"))])
    assert r2.status_code == 200 and "ocr_seulement" not in r2.json()
    assert [o["id"] for o in c.get("/api/ordonnances-stock", headers=_h("aux")).json()] == [oid]
    assert c.get(f"/api/ordonnances-stock/{r2.json()['id']}", headers=_h("aux")).status_code == 403
    assert c.get("/api/ordonnances-stock", headers=_h("aux2")).json() == []
    # Refusé : tout le reste (403 « role_restreint »), réservations et stock compris
    r = c.get("/api/me/tickets", headers=_h("aux"))
    assert r.status_code == 403 and r.json()["code"] == "role_restreint"
    for methode, chemin in (("post", f"/api/ordonnances-stock/{oid}/reserver"), ("get", "/api/stock-produits"),
                            ("get", "/api/stock-produits/depots"), ("delete", f"/api/ordonnances-stock/{oid}")):
        assert getattr(c, methode)(chemin, headers=_h("aux")).status_code == 403, chemin
    # Le Pharmacien suivi garde l'accès complet
    assert c.get("/api/me/tickets", headers=_h("phm")).status_code == 200
    assert c.get("/api/stock-produits/depots", headers=_h("phm")).status_code == 200


def test_regle_outils_plus_ordonnances_et_stock(env):
    c = _app(env, {"ordonnances_stock": False})
    # Fonction non cochée dans Outils+ pour le client : refusée au Pharmacien et à l'Auxiliaire
    assert c.get("/api/ordonnances-stock", headers=_h("phm")).status_code == 403
    assert c.get("/api/ordonnances-stock", headers=_h("aux")).status_code == 403
    # Cochée : accessible aux deux rôles
    env.run(env.db.users.update_one({"id": "pharma"}, {"$set": {"features": {"ordonnances_stock": True}}}))
    assert c.get("/api/ordonnances-stock", headers=_h("phm")).status_code == 200
    assert c.get("/api/ordonnances-stock", headers=_h("aux")).status_code == 200


def test_role_auxiliaire_attribuable():
    from models import TRACKED_USER_ROLES, UserUpdateAdmin
    assert "Auxiliaire en Pharmacie" in TRACKED_USER_ROLES
    champs = UserUpdateAdmin(ticket_seuil_forfait_heures=5, ticket_validite_heures=2, ticket_session_wa_minutes=30,
                             ticket_message_rappel="{X} {Y} {Z}").model_dump(exclude_none=True)
    assert champs["ticket_session_wa_minutes"] == 30
    with pytest.raises(Exception):
        UserUpdateAdmin(ticket_session_wa_minutes=-1)
