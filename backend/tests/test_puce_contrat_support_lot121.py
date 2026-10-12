"""Lot 121 — puce carrée « contrat » dans la fenêtre de chat Support Loois : lien poste / session → client SAWALI,
droits (équipe SAWALI seulement), une seule requête groupée pour la liste, AUCUN montant dans la réponse."""
import asyncio
from datetime import date, timedelta

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from routes.puce_contrat import setup_puce_contrat_routes
from routes.puce_contrat_support import client_id_support

SAWALI = "t-sawali"
MOTS_MONTANT = ("montant", "amount", "prix", "price", "solde", "reste_a", "du_", "paye", "devise", "currency",
                "tarif", "lignes", "paiement")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _jours(n):
    return (date.today() - timedelta(days=n)).isoformat()


# ----------------------------------------------------------------------------------------------------------------------
# Logique pure : lien session / poste → client
# ----------------------------------------------------------------------------------------------------------------------

def test_ordre_du_lien_session_poste_cle():
    cles = {"LYCEE-X": {"code": "LYCEE-X", "tenant_id": "cli-cle"}}
    poste = {"id": "loois-1", "client_id": "cli-poste", "cle_client_code": "LYCEE-X"}
    # 1. client choisi à l'acceptation de la session (client du ticket)
    assert client_id_support({"client_id": "cli-session", "client_id_suggere": "x"}, poste, cles) == \
        ("cli-session", "session")
    # 2. client retenu pour le poste
    assert client_id_support({"client_id_suggere": "cli-sugg"}, poste, cles) == ("cli-poste", "poste")
    # 3. client proposé à la demande
    assert client_id_support({"client_id_suggere": "cli-sugg"}, {"cle_client_code": "LYCEE-X"}, cles) == \
        ("cli-sugg", "session_suggere")
    # 4. clé client Loois du poste
    assert client_id_support(None, {"cle_client_code": "LYCEE-X"}, cles) == ("cli-cle", "cle_client")
    # Rien : aucun client relié
    assert client_id_support(None, {"cle_client_code": "INCONNU"}, cles) == (None, "aucun")
    assert client_id_support(None, None) == (None, "aucun")


# ----------------------------------------------------------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------------------------------------------------------

class _Compteur:
    """Enveloppe d'une collection pour compter les lectures groupées (find)."""

    def __init__(self, coll):
        self._c, self.finds = coll, 0

    def find(self, *a, **k):
        self.finds += 1
        return self._c.find(*a, **k)

    def __getattr__(self, nom):
        return getattr(self._c, nom)


class _Db:
    def __init__(self, base):
        self._b = base
        self.users = _Compteur(base.users)
        self.support_loois_postes = _Compteur(base.support_loois_postes)
        self.support_loois_sessions = _Compteur(base.support_loois_sessions)

    def __getattr__(self, nom):
        return getattr(self._b, nom)


def _app(utilisateur):
    base = AsyncMongoMockClient()["test_puce_contrat_lot121"]
    db = _Db(base)
    _run(base.users.insert_many([
        {"id": "sa", "email": "admin@sawalismartsystems.com", "role": "admin", "company": "SAWALI SMART SYSTEMS",
         "client_id": SAWALI},
        {"id": SAWALI, "email": "contact@sawalismartsystems.com", "role": "client", "company": "SAWALI"},
        {"id": "ecole", "email": "dg@ecole.bf", "role": "client", "company": "Ecole des Métiers",
         "contract_number": "C-ECO", "last_payment_at": _jours(2), "contract_amount": 650000,
         "contract_currency": "XOF"},
        {"id": "ecole-suivi", "email": "secretariat@ecole.bf", "role": "client", "parent_client_id": "ecole"},
        {"id": "lycee", "email": "dg@lycee.bf", "role": "client", "company": "Lycée X",
         "contract_number": "C-LYC", "last_payment_at": _jours(45), "contract_amount": 990000},
        {"id": "pharma", "email": "dg@pharma.bf", "role": "client", "company": "Pharmacie P",
         "contract_number": "C-PH", "contract_status": "annulé", "contract_amount": 123456},
    ]))
    _run(base.support_loois_postes.insert_many([
        # Poste dont la session active a été acceptée pour un utilisateur rattaché à l'école → contrat de l'école
        {"id": "loois-a", "nom": "Ecole — PC-SECRETARIAT (marie)", "ecole": "Ecole des Métiers", "client_id": "pharma"},
        # Poste relié seulement par sa clé client Loois (tenant_id renseigné sur la clé)
        {"id": "loois-b", "nom": "Lycée — PC1 (paul)", "ecole": "Lycée X", "cle_client_code": "LYCEE-X",
         "cle_client_libelle": "Lycée X (clé)"},
        # Poste sans aucun client relié
        {"id": "loois-c", "nom": "Inconnu — PC (zoe)", "ecole": "Ecole inconnue"},
        # Poste de l'équipe SAWALI elle-même
        {"id": "loois-d", "nom": "SAWALI — PC (jf)", "ecole": "SAWALI", "client_id": "sa"},
        # Poste dont le client retenu est annulé
        {"id": "loois-e", "nom": "Pharmacie — PC (ali)", "ecole": "Pharmacie P", "client_id": "pharma"},
    ]))
    _run(base.support_loois_sessions.insert_many([
        {"id": "s-a", "poste_id": "loois-a", "statut": "active", "en_cours": True, "demande_le": "2026-10-12T08:00",
         "client_id": "ecole-suivi", "ticket_number": "ECO-2026-0001"},
        {"id": "s-old", "poste_id": "loois-e", "statut": "terminee", "en_cours": False, "demande_le": "2026-10-01T08:00",
         "client_id": "lycee"},
    ]))
    _run(base.loois_cles_clients.insert_many([
        {"id": "k1", "code": "LYCEE-X", "libelle": "Lycée X", "tenant_id": "lycee", "actif": True,
         "cle_hash": "secret-ne-doit-jamais-sortir"},
    ]))

    async def courant():
        return utilisateur

    async def visibles(user):
        return [SAWALI, user.get("id")] if user.get("client_id") == SAWALI else [user.get("client_id")]

    api = APIRouter(prefix="/api")
    outils = setup_puce_contrat_routes(db=db, api=api, get_current_user=courant, resolve_visible_client_ids=visibles)
    app = FastAPI()
    app.include_router(api)
    outils["vider_cache"]()
    return TestClient(app), db


def _cles(obj, prefixe=""):
    """Toutes les clés d'une réponse JSON (récursif)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield prefixe + k
            yield from _cles(v, prefixe + k + ".")
    elif isinstance(obj, list):
        for v in obj:
            yield from _cles(v, prefixe)


SUPER_ADMIN = {"id": "sa", "email": "admin@sawalismartsystems.com", "role": "admin", "client_id": SAWALI}


def _sans_montant(r):
    for cle in _cles(r.json()):
        assert not any(m in cle.lower() for m in MOTS_MONTANT), cle
    for valeur in ("650000", "990000", "123456", "XOF", "secret-ne-doit-jamais-sortir"):
        assert valeur not in r.text


def test_liste_groupee_lien_couleurs_et_aucun_montant():
    client, db = _app(SUPER_ADMIN)
    r = client.post("/api/support-loois/postes-contrats",
                    json={"poste_ids": ["loois-a", "loois-b", "loois-c", "loois-d", "loois-e", "pas-un-poste"]})
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["actif"] is True
    c = corps["contrats"]
    # Session acceptée pour un utilisateur rattaché → compte principal (école), prioritaire sur le client du poste
    assert c["loois-a"]["numero"] == "C-ECO" and c["loois-a"]["etat"] == "valide"
    assert c["loois-a"]["relie_par"] == "session" and c["loois-a"]["client_nom"] == "Ecole des Métiers"
    # Clé client Loois → compte du lycée, en retard de paiement (orange)
    assert c["loois-b"]["numero"] == "C-LYC" and c["loois-b"]["etat"] == "retard"
    assert c["loois-b"]["couleur"] == "orange" and c["loois-b"]["relie_par"] == "cle_client"
    # Aucun client relié → rouge, nom affiché = école déclarée par le poste
    assert c["loois-c"]["etat"] == "aucun" and c["loois-c"]["numero"] is None
    assert c["loois-c"]["relie_par"] == "aucun" and c["loois-c"]["client_nom"] == "Ecole inconnue"
    # Poste de l'équipe SAWALI → pas de puce
    assert c["loois-d"] is None
    # Session terminée ignorée dans la liste : client retenu pour le poste (annulé → rouge)
    assert c["loois-e"]["statut"] == "annule" and c["loois-e"]["relie_par"] == "poste"
    assert "pas-un-poste" not in c
    _sans_montant(r)
    # Une seule lecture groupée par collection
    assert db.users.finds == 1 and db.support_loois_postes.finds == 1 and db.support_loois_sessions.finds == 1


def test_route_d_une_session():
    client, _ = _app(SUPER_ADMIN)
    # Session terminée : c'est SON client (lycée) qui compte, pas celui retenu ensuite pour le poste
    r = client.get("/api/support-loois/sessions/s-old/contrat")
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["actif"] is True and corps["poste_id"] == "loois-e"
    assert corps["contrat"]["numero"] == "C-LYC" and corps["contrat"]["relie_par"] == "session"
    _sans_montant(r)
    # Session inconnue
    assert client.get("/api/support-loois/sessions/inconnue/contrat").json() == \
        {"actif": True, "poste_id": None, "contrat": None}


def test_client_ordinaire_ne_voit_rien():
    client, _ = _app({"id": "lycee", "email": "dg@lycee.bf", "role": "client", "client_id": "lycee"})
    r = client.post("/api/support-loois/postes-contrats", json={"poste_ids": ["loois-a", "loois-b"]})
    assert r.status_code == 200 and r.json() == {"actif": False, "contrats": {}}
    r = client.get("/api/support-loois/sessions/s-a/contrat")
    assert r.json() == {"actif": False, "poste_id": None, "contrat": None}
    # Même un administrateur d'un autre locataire, hors domaines internes, ne voit rien
    client, _ = _app({"id": "x", "email": "admin@ailleurs.bf", "role": "admin", "client_id": "ailleurs"})
    assert client.post("/api/support-loois/postes-contrats", json={"poste_ids": ["loois-a"]}).json()["actif"] is False


def test_membre_de_l_equipe_sawali_voit_les_puces():
    # E-mail externe mais rattaché au locataire SAWALI : autorisé (même règle que le lot 120)
    client, _ = _app({"id": "u9", "email": "assistante@gmail.com", "role": "client", "client_id": SAWALI})
    r = client.post("/api/support-loois/postes-contrats", json={"poste_ids": ["loois-b"]})
    assert r.json()["actif"] is True and r.json()["contrats"]["loois-b"]["etat"] == "retard"
    # Domaine interne
    client, _ = _app({"id": "u8", "email": "tech@sawalismartsystems.com", "role": "admin", "client_id": "zz"})
    assert client.get("/api/support-loois/sessions/s-a/contrat").json()["contrat"]["numero"] == "C-ECO"
