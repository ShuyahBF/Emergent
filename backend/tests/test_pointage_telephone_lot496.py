# Lot 496 — pointage d'inventaire par téléphone : tests de la logique pure (aucune base, aucun réseau).
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import pointage_telephone as pt  # noqa: E402


def _export():
    """Export Aizenta minimal : 3 lignes (dont une à stock négatif)."""
    def l(c, lib, sv, mg):
        return {"Chrono": c, "Libellé": lib, "Mesure": "B/1", "IMagasin": 0, "ISalle": 0, "StockAvant_SV": sv,
                "StockAvant_MG": mg, "Peremption1": " ", "Diff": -(sv + mg), "Saisie_par": "", "DH_Saisie": ""}
    return {pt.CLE_TABLE: [l(1, "ACETYL SALICLYLATE", -2, 0), l(9, "ACTISKENAN 10MG", 5, 20), l(11, "ACTISKENAN 30MG", 0, 0)]}


def _doc(lieux=None):
    # Lot 497 : les saisies vivent dans leur propre collection ; la route les ajoute sous « saisies » avant les calculs
    return {"saisies": []} | pt.creer_inventaire(ident="abc", numero="PT-0001", structure={"id": "s1", "code": "PPH", "libelle": "Clinique Philadelphie"},
                               lieux=lieux if lieux is not None else [{"nom": "Salle de vente", "colonne": "SV"},
                                                                      {"nom": "Magasin", "colonne": "MG"},
                                                                      {"nom": "Réservés", "colonne": "MG"}],
                               export=_export(), nom_fichier="InventaireSélectionné_PPH_INV069.json", par="admin")


def _saisir(doc, chrono, qte, lieu, peremption=None, prenom="Awa", uid=None):
    s = pt.nettoyer_saisie({"uid": uid or f"u{len(doc['saisies']):07d}", "chrono": chrono, "qte": qte, "lieu": lieu,
                            "peremption": peremption}, lieux=doc["lieux"], chronos={1, 9, 11})
    doc["saisies"].append(s | {"prenom": prenom, "le": "2026-11-28T09:00:00+00:00"})
    return s


def test_creation_numero_code_et_lieux():
    doc = _doc()
    assert (doc["numero"], doc["code_inv"], doc["base"], doc["lignes_total"]) == ("PT-0001", "INV069", "PPH", 3)
    assert [l["id"] for l in doc["lieux"]] == ["L1", "L2", "L3"]
    assert len(doc["jeton"]) >= 30 and pt.jeton_valide(doc)


def test_lieux_invalides_et_defaut():
    assert [l["colonne"] for l in pt.valider_lieux([])] == ["SV", "MG"]
    with pytest.raises(ValueError):
        pt.valider_lieux([{"nom": "Salle", "colonne": "XX"}])
    with pytest.raises(ValueError):
        pt.valider_lieux([{"nom": "Salle", "colonne": "SV"}, {"nom": "salle", "colonne": "MG"}])


def test_export_invalide():
    with pytest.raises(ValueError):
        pt.valider_export({"autre": []})
    with pytest.raises(ValueError):
        pt.valider_export({pt.CLE_TABLE: [{"Chrono": 1}, {"Chrono": 1}]})


@pytest.mark.parametrize("texte,attendu", [("03/2027", "20270301"), ("3/27", "20270301"), ("2027-03", "20270301"),
                                           ("202703", "20270301"), ("20270315", "20270301"), (None, None), ("", None)])
def test_peremption(texte, attendu):
    assert pt.peremption_hfsql(texte) == attendu


def test_peremption_invalide():
    with pytest.raises(ValueError):
        pt.peremption_hfsql("13/2027")


def test_saisie_refusee():
    doc = _doc()
    with pytest.raises(ValueError):          # ligne absente de l'inventaire
        _saisir(doc, 999, 3, "L1")
    with pytest.raises(ValueError):          # lieu inconnu
        _saisir(doc, 9, 3, "L9")
    with pytest.raises(ValueError):          # quantité négative
        _saisir(doc, 9, -1, "L1")


def test_doublon_additionne_et_peremption_la_plus_proche():
    doc = _doc()
    _saisir(doc, 9, 12, "L1", "06/2027")
    _saisir(doc, 9, 5, "L1", "03/2027", prenom="Mariam")   # même ligne, même lieu : additionnée
    _saisir(doc, 9, 8, "L2")
    _saisir(doc, 9, 2, "L3")                               # « Réservés » rattaché au magasin
    t = pt.totaux_par_ligne(doc)[9]
    assert (t["SV"], t["MG"], t["peremption"], t["doublon"]) == (17, 10, "20270301", True)
    e = pt.etat(doc, aujourd_hui=datetime(2026, 11, 28, tzinfo=timezone.utc))
    assert e["lignes_comptees"] == 1 and e["progression"] == pytest.approx(33.3)
    assert any(a["type"] == "doublon" and a["chrono"] == 9 for a in e["alertes"])
    assert {a["prenom"] for a in e["par_auxiliaire"]} == {"Awa", "Mariam"}


def test_annulation_retire_la_saisie():
    doc = _doc()
    _saisir(doc, 9, 12, "L1")
    doc["saisies"][0]["annulee"] = True
    assert pt.totaux_par_ligne(doc) == {}
    assert pt.etat(doc)["annulees"] == 1


def test_alertes_perime_et_ecart():
    doc = _doc()
    _saisir(doc, 1, 0, "L1", "01/2026")      # périmé ; stock avant -2 : écart +2 (pas d'alerte d'écart, < 10)
    _saisir(doc, 11, 40, "L2")               # 40 comptés pour 0 attendu : écart important
    types = {(a["type"], a["chrono"]) for a in pt.etat(doc, aujourd_hui=datetime(2026, 11, 28, tzinfo=timezone.utc))["alertes"]}
    assert ("perime", 1) in types and ("ecart", 11) in types and ("ecart", 1) not in types


def test_export_windev():
    doc = _doc()
    _saisir(doc, 9, 3, "L1", "03/2027")
    _saisir(doc, 9, 20, "L2")
    _saisir(doc, 1, 0, "L1")
    sortie = pt.exporter(doc, quand=datetime(2026, 11, 28, 10, 5, 7, 123000, tzinfo=timezone.utc))
    l1, l9, l11 = sortie[pt.CLE_TABLE]
    assert (l9["ISalle"], l9["IMagasin"], l9["Peremption1"], l9["Diff"], l9["Saisie_par"], l9["DH_Saisie"]) == \
        (3, 20, "20270301", -2, "Awa", "20261128100507123")
    assert (l1["ISalle"], l1["Diff"]) == (0, 2)
    assert l11 == _export()[pt.CLE_TABLE][2]          # ligne non pointée : strictement identique
    assert doc["export"] == _export()                 # l'export d'origine n'est jamais modifié
    assert pt.nom_export(doc) == "InventaireSélectionné_PPH_INV069.pointe.json"


def test_jeton_cloture_ou_expire():
    doc = _doc()
    assert pt.jeton_valide(doc)
    assert not pt.jeton_valide(doc | {"etat": "cloture"})
    assert not pt.jeton_valide(doc | {"jeton_expire": "2020-01-01T00:00:00+00:00"})


def test_prenom():
    assert pt.nettoyer_prenom("  Awa  ") == "Awa"
    with pytest.raises(ValueError):
        pt.nettoyer_prenom("<")


def test_fiche_liste_sans_export():
    doc = _doc()
    _saisir(doc, 9, 3, "L1")
    leger = {k: v for k, v in doc.items() if k not in ("export", "jeton")}   # projection de la route « liste »
    f = pt.fiche_liste(leger)
    assert (f["lignes_total"], f["lignes_comptees"], f["numero"]) == (3, 1, "PT-0001")
    assert "jeton" not in f and "export" not in f


# ---------------------------------------------------------------------------- Lot 497 : tout commerce, CSV
CSV_EXCEL = "\ufeffDésignation;Code barre;Conditionnement;Stock théorique;Prix de vente\nSavon Lux;6001;Pièce;24;350\nRiz 25 kg;6002;Sac;1 200;18 500\n;;;;\n"


def test_csv_excel_sans_numero_d_ordre():
    export, fmt = pt.lire_liste_produits(CSV_EXCEL, "stock_boutique.csv")
    l1, l2 = export[pt.CLE_TABLE]
    assert fmt == "csv" and len(export[pt.CLE_TABLE]) == 2          # ligne vide ignorée
    assert (l1["Chrono"], l1["Code"], l1["Libellé"], l1["Mesure"], l1["StockAvant_MG"]) == (1, "6001", "Savon Lux", "Pièce", 24)
    assert (l2["Chrono"], l2["StockAvant_MG"], l2["IPPublic"]) == (2, 1200, 18500)


def test_csv_avec_numeros_et_virgules():
    export, _ = pt.lire_liste_produits("N°,Article,Qté\n10,Stylo bleu,5\n12,Cahier,3\n", "x.csv")
    assert [l["Chrono"] for l in export[pt.CLE_TABLE]] == [10, 12]


def test_csv_sans_libelle_refuse():
    with pytest.raises(ValueError):
        pt.lire_liste_produits("Code;Stock\n1;2\n", "x.csv")


def test_json_aizenta_reconnu():
    import json
    export, fmt = pt.lire_liste_produits("\ufeff" + json.dumps(_export()), "InventaireSélectionné_PPH_INV069.json")
    assert fmt == "aizenta" and len(export[pt.CLE_TABLE]) == 3


def test_export_csv_par_lieu():
    export, _ = pt.lire_liste_produits(CSV_EXCEL, "stock_boutique.csv")
    doc = {"saisies": []} | pt.creer_inventaire(ident="b", numero="PT-0002", structure={"source": "commerce", "id": "c1", "code": "CS-ABC234", "libelle": "Boutique Awa"},
                                                lieux=[{"nom": "Rayon", "colonne": "SV"}, {"nom": "Réserve", "colonne": "MG"}], export=export,
                                                nom_fichier="stock_boutique.csv", par="a", format_="csv")
    for uid, c, q, lieu in [("u0000001", 1, 20, "L1"), ("u0000002", 1, 6, "L2")]:
        doc["saisies"].append(pt.nettoyer_saisie({"uid": uid, "chrono": c, "qte": q, "lieu": lieu}, lieux=doc["lieux"], chronos={1, 2}) | {"prenom": "Awa"})
    texte = pt.exporter_csv(doc).decode("utf-8-sig").splitlines()
    assert texte[0] == "N°;Code;Libellé;Mesure;Stock théorique;Rayon;Réserve;Total compté;Écart;Péremption;Compté par"
    assert texte[1] == "1;6001;Savon Lux;Pièce;24;20;6;26;2;;Awa"
    assert texte[2] == "2;6002;Riz 25 kg;Sac;1200;;;;;;"
    assert pt.nom_export(doc, "csv") == "stock_boutique.pointe.csv"


def test_commerce_et_cle_de_suivi():
    assert pt.valider_commerce({"nom": " Boutique  Awa ", "type": "Boutique", "ville": "Koudougou"}) == {"nom": "Boutique Awa", "type": "Boutique", "ville": "Koudougou",
                                                                                                 "pays": "Burkina Faso", "langue": "fr"}
    with pytest.raises(ValueError):
        pt.valider_commerce({"nom": "B", "type": "Boutique"})
    cle = pt.generer_cle_suivi()
    assert cle.startswith("CS-") and len(cle) == 9 and not set(cle[3:]) & set("O0I1")



# ---------------------------------------------------------------------------- Lot 498 : clé de pointage et mot de passe
def test_cle_et_mot_de_passe_lisibles():
    cle, mdp = pt.generer_cle_pointage(), pt.generer_mot_de_passe()
    assert cle.startswith("CP-") and len(cle) == 9 and not set(cle[3:]) & set("O0I1")
    assert len(mdp) == 9 and mdp[4] == "-" and not set(mdp) & set("o0il1")
    assert pt.normaliser_cle("cp k7mp2q") == "CP-K7MP2Q"
    assert pt.normaliser_mot_de_passe(" K7MP 2QHX ") == "k7mp-2qhx"


def test_blocage_au_cinquieme_essai():
    quand = datetime(2026, 11, 28, 10, tzinfo=timezone.utc)
    acces = {"echecs": 3}
    assert pt.apres_echec(acces, quand=quand) == {"echecs": 4}
    bloque = pt.apres_echec({"echecs": 4}, quand=quand)
    assert bloque["echecs"] == 0 and pt.est_bloque(bloque, quand=quand) and not pt.est_bloque(bloque, quand=datetime(2026, 11, 28, 10, 16, tzinfo=timezone.utc))


def test_jetons_signes():
    inv = {"id": "i1", "jeton_expire": "2099-01-01T00:00:00+00:00"}
    j = pt.jeton_telephone("secret", inv, {"id": "a1", "version": 2})
    assert pt.lire_jeton("secret", j, "telephone")["v"] == 2
    assert pt.lire_jeton("secret", j, "espace") is None             # un jeton de téléphone n'ouvre pas l'espace
    assert pt.lire_jeton("autre", j, "telephone") is None           # signature vérifiée
    assert pt.lire_jeton("secret", pt.jeton_espace("secret", {"id": "a1"}), "espace")["acces"] == "a1"
