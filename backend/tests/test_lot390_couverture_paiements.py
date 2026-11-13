"""Lot 390 — validité du contrat : jusqu'à quelle date le client a PAYÉ (période réglée), pas la date du dernier paiement.
Lancer : cd backend && python -m pytest tests/test_lot390_couverture_paiements.py -q -p no:xdist
"""
import os
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
from datetime import date

import pytest

import couverture_paiements as cp
from retard_echeance import retard_client


def pay(cree, date_paiement, debut=None, fin=None, **kw):
    return {"created_at": cree, "payment_date": date_paiement, "periode_debut": debut, "periode_fin": fin, **kw}


MENSUEL = {"contract_billing_period": "monthly"}


def test_le_cas_du_proprietaire_paiement_hier_pour_janvier():
    # Aujourd'hui 14/11/2026. Le client a payé HIER (13/11) la facture de prestations de JANVIER.
    u = {**MENSUEL, "last_payment_at": "2026-11-13"}
    ancien = retard_client(u, date(2026, 11, 14))
    assert ancien["jours"] == 0 and ancien["echeance_iso"] == "2026-12-13"                    # ancien calcul : « à jour » (FAUX)
    paiements = [pay("2026-11-13T10:00", "2026-11-13", "2026-01-01", "2026-01-31")]
    couvert = cp.couvert_jusqu_au(paiements, 30)
    assert couvert == date(2026, 1, 31)
    nouveau = retard_client({**u, "couvert_jusqu_au": couvert.isoformat()}, date(2026, 11, 14))
    assert nouveau["echeance_iso"] == "2026-02-01" and nouveau["jours"] == 286 and nouveau["ref_field"] == "couvert_jusqu_au"      # en retard depuis le 1er février


def test_couverture_continue_et_trou():
    janv = pay("2026-02-02T09:00", "2026-02-02", "2026-01-01", "2026-01-31")
    fev = pay("2026-03-02T09:00", "2026-03-02", "2026-02-01", "2026-02-28")
    avril = pay("2026-04-02T09:00", "2026-04-02", "2026-04-01", "2026-04-30")             # mars non payé : trou
    assert cp.couvert_jusqu_au([janv, fev], 30) == date(2026, 2, 28)
    assert cp.couvert_jusqu_au([janv, fev, avril], 30) == date(2026, 2, 28)                # la couverture s'arrête avant le trou
    mars = pay("2026-11-13T09:00", "2026-11-13", "2026-03-01", "2026-03-31")              # payé en retard : comble le trou
    assert cp.couvert_jusqu_au([janv, fev, avril, mars], 30) == date(2026, 4, 30)
    assert cp.couvert_jusqu_au([avril, mars, fev, janv], 30) == date(2026, 4, 30)          # l'ordre de saisie n'importe pas


def test_ancien_mode_inchange_et_mixte():
    assert cp.couvert_jusqu_au([], 30) is None
    assert cp.couvert_jusqu_au([pay("2026-10-01", "2026-10-01")], 30) is None             # paiement sans période : ancien calcul
    # ancien paiement du 01/10 (couvre jusqu'au 30/10) puis paiement avec période pour novembre : la chaîne se prolonge
    assert cp.couvert_jusqu_au([pay("2026-10-01", "2026-10-01"), pay("2026-11-02", "2026-11-02", "2026-10-31", "2026-11-29")], 30) == date(2026, 11, 29)
    # un ancien paiement ENREGISTRÉ APRÈS repart de sa date : les périodes précédentes ne comptent plus
    assert cp.couvert_jusqu_au([pay("2026-03-01", "2026-03-01", "2026-01-01", "2026-01-31"), pay("2026-11-13", "2026-11-13")], 30) is None
    # les lignes typées (frais de réouverture) ne règlent aucune période
    assert cp.couvert_jusqu_au([pay("2026-11-13", "2026-11-13", "2026-01-01", "2026-01-31", type="frais_reouverture")], 30) is None


def test_imputation_plus_ancienne_echeance():
    u = {**MENSUEL, "last_payment_at": "2026-02-02"}                                       # couvert (ancien calcul) jusqu'au 03/03 (02/02 + 29 j)
    # le client règle aujourd'hui : on règle d'abord la plus ancienne période impayée, pas « à partir d'aujourd'hui »
    d, f = cp.periode_a_imputer("plus_ancienne", u, [], date(2026, 11, 13))
    assert (d, f) == (date(2026, 3, 4), date(2026, 4, 2))
    # un deuxième paiement enchaîne sur le premier
    p1 = pay("2026-11-13T10:00", "2026-11-13", d.isoformat(), f.isoformat())
    d2, f2 = cp.periode_a_imputer("plus_ancienne", u, [p1], date(2026, 11, 13), nb_periodes=2)
    assert d2 == date(2026, 4, 3) and f2 == date(2026, 6, 1)
    # aucune référence connue : la première période commence au paiement
    assert cp.periode_a_imputer("plus_ancienne", MENSUEL, [], date(2026, 11, 13)) == (date(2026, 11, 13), date(2026, 12, 12))


def test_imputation_periode_et_ancien_mode_et_erreurs():
    assert cp.periode_a_imputer("date_paiement", MENSUEL, [], date(2026, 11, 13)) == (None, None)
    assert cp.periode_a_imputer("periode", MENSUEL, [], date(2026, 11, 13), debut=date(2026, 1, 1), fin=date(2026, 1, 31)) == (date(2026, 1, 1), date(2026, 1, 31))
    for mauvais in ({"imputation": "autre"}, {"imputation": "periode"}, {"imputation": "periode", "debut": date(2026, 2, 1), "fin": date(2026, 1, 1)},
                    {"imputation": "periode", "debut": date(2020, 1, 1), "fin": date(2026, 1, 1)}):
        with pytest.raises(ValueError):
            cp.periode_a_imputer(mauvais.pop("imputation"), MENSUEL, [], date(2026, 11, 13), **mauvais)


def test_les_consommateurs_lisent_la_couverture():
    u = {"contract_billing_period": "monthly", "last_payment_at": "2026-11-13", "couvert_jusqu_au": "2026-01-31", "contract_signed_at": "2025-01-01"}
    assert cp.echeance_client(u, 30) == date(2026, 2, 1)
    assert cp.echeance_client({k: v for k, v in u.items() if k != "couvert_jusqu_au"}, 30) == date(2026, 12, 13)    # sans couverture : ancien calcul
    # abonnement d'accès : impayé depuis le lendemain de l'échéance
    import abonnement_acces as abo
    from datetime import datetime, timezone
    etat = abo.etat_client(u, datetime(2026, 11, 14, tzinfo=timezone.utc))
    assert etat["echeance"] == "2026-02-01" and etat["statut"] != abo.A_JOUR
    # puce de contrat : le cas du propriétaire — payé hier pour janvier : « À jour » (faux) devient « Retard de paiement »
    from routes.puce_contrat import fiche_contrat
    contrat = {"contract_number": "CT-1", "contract_start_at": "2025-01-01", "contract_end_at": "2027-01-01", "contract_billing_period": "monthly", "last_payment_at": "2026-11-13"}
    assert fiche_contrat(contrat, date(2026, 11, 14))["statut"] == "a_jour"
    avec = fiche_contrat({**contrat, "couvert_jusqu_au": "2026-01-31"}, date(2026, 11, 14))
    assert avec["statut"] == "retard_paiement" and avec["etat"] == "retard" and avec["echeance_prochaine"] == "2026-02-01"
