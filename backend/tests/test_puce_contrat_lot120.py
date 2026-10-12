"""Lot 120 — puce carrée « contrat » du Centre de messagerie : vert (valide), orange (retard), rouge (aucun),
détail sans AUCUN montant, une seule lecture groupée des comptes, droits de visibilité respectés."""
import asyncio
from datetime import date, timedelta

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from routes.puce_contrat import fiche_contrat, mois_entre, setup_puce_contrat_routes

AUJ = date(2026, 10, 12)
SAWALI = "t-sawali"                        # locataire de la plateforme (possède les contacts du Centre de messagerie)
MOTS_MONTANT = ("montant", "amount", "prix", "price", "solde", "reste_a", "du_", "paye", "devise", "currency",
                "tarif", "lignes", "paiement")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _jours(n):
    return (date.today() - timedelta(days=n)).isoformat()


# ----------------------------------------------------------------------------------------------------------------------
# Logique pure
# ----------------------------------------------------------------------------------------------------------------------

def test_mois_entre():
    assert mois_entre(date(2026, 10, 15), date(2026, 11, 14)) == 0
    assert mois_entre(date(2026, 10, 15), date(2027, 10, 15)) == 12
    assert mois_entre(date(2026, 10, 15), date(2026, 1, 1)) == 0


def test_valide_vert_avec_mois():
    f = fiche_contrat({"company": "Pharma A", "contract_number": "C-001", "contract_start_at": "2026-01-15",
                       "contract_end_at": "2027-01-15", "last_payment_at": "2026-10-10",
                       "contract_amount": 900000, "contract_currency": "XOF"}, AUJ)
    assert f["etat"] == "valide" and f["couleur"] == "vert" and f["numero"] == "C-001"
    assert f["duree_mois"] == 12 and f["mois_ecoules"] == 8 and f["mois_restants"] == 4
    assert f["jours_retard"] is None and f["echeance_prochaine"] == "2027-01-15"
    assert "contract_amount" not in f and 900000 not in f.values()


def test_retard_orange_compte_depuis_l_echeance():
    # Lot 127.3 — le retard se compte depuis l'ÉCHÉANCE (dernier règlement + périodicité), le seuil est un délai de grâce.
    # Mensuel payé le 23/08 → échéance 22/09 → 20 jours de retard au 12/10, seuil du client 15 j → orange
    f = fiche_contrat({"contract_number": "C-002", "last_payment_at": "2026-08-23", "contract_overdue_days": 15,
                       "contract_billing_period": "monthly"}, AUJ)
    assert f["etat"] == "retard" and f["couleur"] == "orange" and f["jours_retard"] == 20 and f["seuil_retard"] == 15
    assert f["echeance_prochaine"] == "2026-09-22" and f["periodicite"] == "Mensuel"
    # Cas réel (Pharmacie AMITIÉ MIYOUGOU) : payé il y a quelques jours → À JOUR (avant : orange au bout de 5 jours)
    assert fiche_contrat({"contract_number": "C", "last_payment_at": "2026-10-06"}, AUJ)["etat"] == "valide"
    assert fiche_contrat({"contract_number": "C-002", "last_payment_at": "2026-10-01",
                          "contract_overdue_days": 15}, AUJ)["etat"] == "valide"
    # Périodicité inconnue = mensuelle : payé le 01/09 → échéance 01/10 → 11 j > 5 j (défaut) → orange ; seuil 30 → vert
    assert fiche_contrat({"contract_number": "C", "last_payment_at": "2026-09-01"}, AUJ)["etat"] == "retard"
    assert fiche_contrat({"contract_number": "C", "last_payment_at": "2026-09-01"}, AUJ, 30)["etat"] == "valide"
    # Trimestriel payé le 01/09 → échéance 30/11 → à jour
    assert fiche_contrat({"contract_number": "C", "last_payment_at": "2026-09-01",
                          "contract_billing_period": "quarterly"}, AUJ)["etat"] == "valide"


def test_compte_suspendu_et_renouvellement_en_retard_orange():
    assert fiche_contrat({"contract_number": "C", "account_status": "suspended"}, AUJ)["statut"] == "suspendu"
    # Fin de contrat dépassée de 3 jours (J+1 à J+5, lot 82) → orange
    f = fiche_contrat({"contract_number": "C", "contract_end_at": "2026-10-09"}, AUJ)
    assert f["etat"] == "retard" and f["statut"] == "renouvellement" and f["jours_retard"] == 3


def test_aucun_rouge():
    assert fiche_contrat(None, AUJ)["etat"] == "aucun"
    assert fiche_contrat({"company": "X"}, AUJ)["couleur"] == "rouge"                       # pas de n° de contrat
    for statut in ("annulé", "Résilié", "cancelled"):
        f = fiche_contrat({"contract_number": "C", "contract_status": statut}, AUJ)
        assert f["etat"] == "aucun" and f["statut"] == "annule"
    assert fiche_contrat({"contract_number": "C", "account_status": "archive"}, AUJ)["etat"] == "aucun"
    # Échu (au-delà de J+5 après la fin) → rouge
    f = fiche_contrat({"contract_number": "C", "contract_end_at": "2026-09-01"}, AUJ)
    assert f["etat"] == "aucun" and f["statut"] == "expire"


# ----------------------------------------------------------------------------------------------------------------------
# Route POST /api/me/contacts-contrats
# ----------------------------------------------------------------------------------------------------------------------

class _Compteur:
    """Enveloppe db.users pour compter les lectures groupées (find)."""

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

    def __getattr__(self, nom):
        return getattr(self._b, nom)


def _app(utilisateur):
    base = AsyncMongoMockClient()["test_puce_contrat_lot120"]
    db = _Db(base)
    _run(base.users.insert_many([
        {"id": "sa", "email": "admin@sawalismartsystems.com", "role": "admin", "company": "SAWALI SMART SYSTEMS",
         "client_id": SAWALI},
        # Lot 126 : utilisatrice suivie de l'équipe SAWALI (même numéro que le contact « Diane »)
        {"id": "diane-u", "email": "diane@exemple.bf", "role": "client", "parent_client_id": "sa",
         "whatsapp_number": "22655264438"},
        {"id": "pA", "email": "dg@pharma-a.bf", "role": "client", "company": "Pharmacie A", "phone": "+226 70 11 11 11",
         "contract_number": "C-A", "last_payment_at": _jours(2), "contract_amount": 500000},
        {"id": "pA-suivi", "email": "caisse@pharma-a.bf", "role": "client", "parent_client_id": "pA",
         "whatsapp_number": "22670222222"},
        {"id": "pB", "email": "dg@pharma-b.bf", "role": "client", "company": "Pharmacie B",
         "contract_number": "C-B", "last_payment_at": _jours(40), "contract_amount": 750000,
         "contract_currency": "XOF"},
        {"id": "pC", "email": "dg@pharma-c.bf", "role": "client", "company": "Pharmacie C",
         "contract_number": "C-C", "contract_status": "résilié"},
        # Lot 127.2 : vrai client dont l'e-mail est au domaine interne (créé par l'équipe) → reste un CLIENT
        {"id": "pD", "email": "pharmacie.d@sawalismartsystems.com", "role": "client", "company": "Pharmacie D",
         "contract_number": "C-D", "last_payment_at": _jours(2)},
        {"id": "autre", "email": "x@ailleurs.bf", "role": "client", "company": "Ailleurs", "contract_number": "C-Z"},
    ]))
    _run(base.directory_contacts.insert_many([
        # Lot 124 : seuls les contacts avec « Société » sont analysés ; la société inconnue laisse jouer tél. / e-mail
        {"id": "k1", "client_id": SAWALI, "name": "Caisse A", "company": "Caisse A", "whatsapp": "70 22 22 22"},  # tél. d'un suivi de A
        {"id": "k2", "client_id": SAWALI, "name": "DG B", "company": "Groupe B", "email": "DG@pharma-b.bf"},       # e-mail du DG de B
        {"id": "k3", "client_id": SAWALI, "name": "Prospect", "company": "Prospect SARL", "phone": "+226 76 00 00 00"},  # inconnu
        {"id": "k7", "client_id": SAWALI, "name": "Sans société", "email": "dg@pharma-a.bf"},  # lot 124 : non analysé
        {"id": "k4", "client_id": SAWALI, "name": "C", "company": "pharmacie c"},            # société, résilié
        {"id": "k5", "client_id": SAWALI, "name": "Collègue", "email": "jean@sawalismartsystems.com"},  # interne
        {"id": "k6", "client_id": "autre-locataire", "name": "Invisible", "company": "Ailleurs"},     # hors périmètre
        # Lot 126 : société sans contrat, numéro d'un compte de l'équipe → puce ROUGE (et non « pas de puce »)
        {"id": "k8", "client_id": SAWALI, "name": "Diane", "company": "ECOLE DES METIERS", "whatsapp": "22655264438"},
        # La société désigne SAWALI elle-même → pas de puce
        {"id": "k9", "client_id": SAWALI, "name": "Ines", "company": "Sawali Smart Systems"},
        {"id": "k10", "client_id": SAWALI, "name": "Caissière D", "company": "PHARMACIE D"},     # lot 127.2
    ]))

    async def courant():
        return utilisateur

    async def visibles(user):
        # Lot 127 : comme en production, l'équipe SAWALI voit AUSSI les comptes de tous ses clients ; ils ne doivent
        # pas pour autant être pris pour des comptes « internes » (sinon leurs contacts n'ont plus de puce)
        if user.get("client_id") == SAWALI:
            return [SAWALI, user.get("id"), "pA", "pA-suivi", "pB", "pC"]
        return [user.get("client_id")]

    api = APIRouter(prefix="/api")
    outils = setup_puce_contrat_routes(db=db, api=api, get_current_user=courant, resolve_visible_client_ids=visibles)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app), db, outils


def _cles(obj, prefixe=""):
    """Toutes les clés d'une réponse JSON (récursif)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield prefixe + k
            yield from _cles(v, prefixe + k + ".")
    elif isinstance(obj, list):
        for v in obj:
            yield from _cles(v, prefixe)


def test_route_couleurs_liens_et_aucun_montant():
    client, db, _ = _app({"id": "sa", "email": "admin@sawalismartsystems.com", "role": "admin", "client_id": SAWALI})
    r = client.post("/api/me/contacts-contrats", json={})
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["actif"] is True
    c = corps["contrats"]
    assert c["k1"]["etat"] == "valide" and c["k1"]["numero"] == "C-A" and c["k1"]["relie_par"] == "telephone"
    # Lot 127.3 : payé il y a 40 jours (mensuel par défaut) → échéance dépassée de 10 jours → orange
    assert c["k2"]["etat"] == "retard" and c["k2"]["numero"] == "C-B" and c["k2"]["jours_retard"] == 10
    assert c["k2"]["relie_par"] == "email"
    assert c["k3"]["etat"] == "aucun" and c["k3"]["numero"] is None
    assert c["k4"]["etat"] == "aucun" and c["k4"]["statut"] == "annule" and c["k4"]["relie_par"] == "societe"
    assert c["k5"] is None                                          # membre de l'équipe : pas de puce
    assert c["k7"] is None                                          # lot 124 : sans « Société », pas analysé
    assert c["k8"]["etat"] == "aucun" and c["k8"]["couleur"] == "rouge"   # lot 126 : société sans contrat
    assert c["k9"] is None                                          # lot 126 : la société est SAWALI
    assert c["k10"]["etat"] == "valide" and c["k10"]["numero"] == "C-D"   # lot 127.2 : e-mail interne ≠ équipe
    assert "k6" not in c                                            # contact hors périmètre : jamais renvoyé
    # Aucun montant, nulle part dans la réponse
    for cle in _cles(corps):
        assert not any(m in cle.lower() for m in MOTS_MONTANT), cle
    texte = r.text
    assert "500000" not in texte and "750000" not in texte and "XOF" not in texte


def test_une_seule_lecture_groupee_et_filtre_par_ids():
    client, db, outils = _app({"id": "sa", "email": "admin@sawalismartsystems.com", "role": "admin",
                               "client_id": SAWALI})
    outils["vider_cache"]()
    r = client.post("/api/me/contacts-contrats", json={"contact_ids": ["k1", "k2", "k6"]})
    assert r.status_code == 200
    assert set(r.json()["contrats"]) == {"k1", "k2"}                # k6 n'est pas visible
    assert db.users.finds == 1                                     # une seule lecture groupée des comptes
    client.post("/api/me/contacts-contrats", json={})
    assert db.users.finds == 1                                     # index mémorisé (60 s)


def test_client_ordinaire_ne_voit_aucune_puce():
    client, _, outils = _app({"id": "pB", "email": "dg@pharma-b.bf", "role": "client", "client_id": "pB"})
    outils["vider_cache"]()
    r = client.post("/api/me/contacts-contrats", json={})
    assert r.status_code == 200 and r.json() == {"actif": False, "contrats": {}}


def test_membre_de_l_equipe_sawali_voit_les_puces():
    # Utilisateur suivi du locataire SAWALI, e-mail externe : autorisé car il voit le locataire du super-admin
    client, _, _ = _app({"id": "u9", "email": "assistante@gmail.com", "role": "client", "client_id": SAWALI})
    r = client.post("/api/me/contacts-contrats", json={"contact_ids": ["k2"]})
    assert r.json()["actif"] is True and r.json()["contrats"]["k2"]["etat"] == "retard"


def test_lot124_societe_normalisee_et_prioritaire():
    """Lot 124 — la société est comparée sans accents ni casse, et passe AVANT l'e-mail ; sans société : non analysé."""
    from routes.puce_contrat import IndexComptes, a_une_societe, cle_societe
    assert cle_societe("  Pharmacie   ÉVASION ") == "pharmacie evasion"
    assert a_une_societe({"company": "X"}) and not a_une_societe({"company": "  "}) and not a_une_societe({})
    idx = IndexComptes([
        {"id": "a", "email": "dg@a.bf", "company": "Pharmacie Évasion", "contract_number": "C-A"},
        {"id": "b", "email": "dg@b.bf", "company": "Pharmacie B", "contract_number": "C-B"},
    ])
    # Société de A mais e-mail de B : la société l'emporte
    client, critere = idx.client_du_contact({"company": "pharmacie evasion", "email": "dg@b.bf"})
    assert client["id"] == "a" and critere == "societe"
    # Société inconnue : l'e-mail sert de secours
    client, critere = idx.client_du_contact({"company": "Groupe B", "email": "dg@b.bf"})
    assert client["id"] == "b" and critere == "email"
