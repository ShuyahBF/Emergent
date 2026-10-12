"""Lot 128 — la « Société » d'un contact est comparée aux MÊMES valeurs que la liste « Société (client) » du
formulaire contact (company, à défaut full_name, et client_code de TOUS les comptes, rattachés compris)."""
from routes.puce_contrat import IndexComptes, est_interne

SAWALI = "tenant-sawali"


def _index():
    return IndexComptes([
        # Locataire SAWALI et son super-admin
        {"id": SAWALI, "email": "contact@sawalismartsystems.com", "company": "SAWALI SMART SYSTEMS"},
        {"id": "sa", "email": "admin@sawalismartsystems.com", "company": "SAWALI SMART SYSTEMS", "client_id": SAWALI},
        # Client créé par l'équipe : son client_id désigne le locataire SAWALI (cas de la Pharmacie AMY)
        {"id": "amy", "email": "dg@amy.bf", "role": "client", "company": "Pharmacie AMITIE MIYOUGOU",
         "client_code": "AMY", "client_id": SAWALI, "contract_number": "C-AMY"},
        # Client sans « company » : la liste du formulaire propose son NOM (full_name)
        {"id": "f", "email": "dg@f.bf", "role": "client", "full_name": "Clinique Fadima", "contract_number": "C-F"},
        # Compte rattaché portant une autre raison sociale ; le contrat est sur son compte principal
        {"id": "g", "email": "dg@g.bf", "role": "client", "company": "Groupe G", "contract_number": "C-G"},
        {"id": "g2", "email": "agence@g.bf", "role": "client", "company": "Agence G Bobo", "parent_client_id": "g"},
        # Client sans contrat créé par l'équipe
        {"id": "h", "email": "dg@h.bf", "role": "client", "company": "Quincaillerie H", "client_id": SAWALI},
    ])


def test_client_cree_par_l_equipe_retrouve_par_sa_societe():
    idx = _index()
    client, critere = idx.client_du_contact({"company": "PHARMACIE AMITIÉ MIYOUGOU"})
    assert critere == "societe" and client["id"] == "amy"
    assert not est_interne(client, {SAWALI, "sa"}, ["sawalismartsystems.com"])
    client, critere = idx.client_du_contact({"company": "amy"})          # code client
    assert client["id"] == "amy"


def test_client_sans_company_retrouve_par_son_nom():
    client, critere = _index().client_du_contact({"company": "clinique fadima"})
    assert critere == "societe" and client["id"] == "f"


def test_compte_rattache_renvoie_le_contrat_du_principal():
    client, critere = _index().client_du_contact({"company": "Agence G Bobo"})
    assert critere == "societe" and client["id"] == "g"


def test_client_sans_contrat_n_est_pas_pris_pour_sawali():
    idx = _index()
    client, critere = idx.client_du_contact({"company": "Quincaillerie H"})
    assert critere == "societe" and client["id"] == "h"                  # → puce rouge, pas « interne »
    assert not est_interne(client, {SAWALI, "sa"}, [])
    client, critere = idx.client_du_contact({"company": "Sawali Smart Systems"})
    assert est_interne(client, {SAWALI, "sa"}, [])                       # SAWALI elle-même : pas de puce


def test_lot128_1_forme_juridique_ignoree():
    """Lot 128.1 — « SAWALI SMART SYSTEMS SARL » = « Sawali Smart Systems » ; un nom réduit à « SA » reste « sa »."""
    from routes.puce_contrat import cle_societe
    assert cle_societe("SAWALI SMART SYSTEMS SARL") == "sawali smart systems"
    assert cle_societe("Felin Énergie S.A.") == "felin energie"
    assert cle_societe("SA") == "sa"
    client, critere = _index().client_du_contact({"company": "Sawali Smart Systems SARL"})
    assert critere == "societe" and est_interne(client, {SAWALI, "sa"}, [])
