"""Lot 129 — Admin → Clients, alerte quotidienne et Liluvine comptent le retard depuis l'ÉCHÉANCE, comme la puce."""
from datetime import date

from retard_echeance import retard_client

AUJ = date(2026, 10, 12)


def test_mensuel_a_jour_pas_de_retard():
    # Payé le 20/09 : échéance le 20/10 → aucun retard le 12/10 (avant : 22 jours « de retard »)
    r = retard_client({"last_payment_at": "2026-09-20", "contract_billing_period": "monthly"}, AUJ)
    assert r["jours"] == 0 and r["echeance_iso"] == "2026-10-20" and r["ref_field"] == "last_payment_at"


def test_mensuel_par_defaut_et_retard_depuis_l_echeance():
    # Périodicité absente → mensuelle ; payé le 01/08 → échéance 31/08 → 42 jours de retard
    r = retard_client({"last_payment_at": "2026-08-01"}, AUJ)
    assert r["echeance_iso"] == "2026-08-31" and r["jours"] == 42


def test_trimestriel_annuel_et_signature():
    assert retard_client({"last_payment_at": "2026-08-01", "contract_billing_period": "quarterly"}, AUJ)["jours"] == 0
    r = retard_client({"contract_signed_at": "2025-01-01T10:00:00", "contract_billing_period": "annual"}, AUJ)
    assert r["ref_field"] == "contract_signed_at" and r["echeance_iso"] == "2026-01-01" and r["jours"] == 284


def test_sans_date_ou_date_illisible():
    assert retard_client({}, AUJ) is None
    assert retard_client({"last_payment_at": "pas une date"}, AUJ) is None


def test_validite_du_contrat_lue_par_liluvine():
    from routes.liluvine_wa_autoreply import _tenant_contract_validity
    # Payé il y a 20 jours, mensuel : à jour (avant : en retard au-delà de 5 jours)
    from datetime import datetime, timedelta, timezone
    il_y_a_20j = (datetime.now(timezone.utc).date() - timedelta(days=20)).isoformat()
    v = _tenant_contract_validity({"contract_number": "C-1", "last_payment_at": il_y_a_20j}, 5)
    assert v["valid"] is True and v["days_overdue"] == 0
    il_y_a_40j = (datetime.now(timezone.utc).date() - timedelta(days=40)).isoformat()
    v = _tenant_contract_validity({"contract_number": "C-1", "last_payment_at": il_y_a_40j}, 5)
    assert v["valid"] is False and v["days_overdue"] == 10
