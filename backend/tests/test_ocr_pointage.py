"""Lot OCR sur Pièces — type « Liste de pointage » (module ocr_pointage).

Deux niveaux, sans serveur, sans clé ni réseau :
  1. la logique de report lecture OCR → JSON d'inventaire (appliquer_lectures) ;
  2. le parcours complet via l'API (dépôt scan + JSON, analyse, téléchargement
     du JSON complété, cloisonnement), avec l'appel IA remplacé par une doublure.

Lancer : cd backend && python -m pytest tests/test_ocr_pointage.py -q
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ocr_pointage as op  # noqa: E402

# Fixture `env` (application + stockage + base simulés) partagée avec les tests OCR existants.
from test_ocr_pieces import _h, _wait_analysed, env  # noqa: E402,F401


# --- Données : extrait réel de l'inventaire INV067 (PPH) ---------------------------
def _ligne(chrono, libelle, sv=0, mg=0, mesure="B/1"):
    return {"Chrono": chrono, "Code_Produit": f"D?{chrono}", "Libellé": libelle, "Mesure": mesure,
            "IPPublic": 1000, "IPRevient": 700.5, "IMagasin": 0, "ISalle": 0, "Etat_Produit": "ACT",
            "StockAvant_SV": sv, "StockAvant_MG": mg, "cip": "", "Peremption1": " ",
            "Diff": -(sv + mg), "Saisie_par": "", "DH_Saisie": ""}


def _inventaire():
    return {op.CLE_TABLE: [
        _ligne(1, "ARGESUN INJ 120MG ", sv=10),
        _ligne(3, "ACETYL SALICLYLATE", mg=50),
        _ligne(70, "BANDELETTE CODEFREE", mesure="B/50"),
        _ligne(77, "BAVETTE", sv=4, mesure="B/50"),
    ]}


def _lu(n, libelle, mag=None, sv=None, per=None, incertain=False, note=None):
    return {"n_ordre": n, "libelle": libelle, "inv_mag": mag, "inv_sv": sv, "peremption": per,
            "incertain": incertain, "note": note}


def _page(lignes, titre="Liste pointage n° INV067 du 29/09/2026", pied=None, nom="p.1"):
    return {"page": nom, "titre": titre, "nombre_de_lignes_pied": pied, "lignes": lignes}


# --- 1. Logique de report ---------------------------------------------------------
def test_report_diff_et_tracabilite():
    data = _inventaire()
    t = datetime(2026, 9, 29, 14, 5, 7, 123000)
    out, rap = op.appliquer_lectures(data, [_page([
        _lu(1, "ARGESUN INJ 120MG [B/1]", mag=5, sv=3, per="06/28"),
        _lu(3, "ACETYL SALICLYLATE [B/1]", sv=40),
        _lu(70, "BANDELETTE CODEFREE [B/50]"),              # rien d'écrit
        _lu(77, "BAVETTE [B/50]", mag="12"),                # le modèle peut renvoyer une chaîne
    ], pied=4)], code_attendu="InventaireSélectionné_PPH_INV067.json", maintenant=t)
    l1, l3, l70, l77 = out[op.CLE_TABLE]
    assert (l1["IMagasin"], l1["ISalle"], l1["Peremption1"], l1["Diff"]) == (5, 3, "20280601", -2)
    assert (l3["ISalle"], l3["Diff"]) == (40, -10)
    assert (l1["Saisie_par"], l1["DH_Saisie"]) == ("Claude", "20260929140507123")
    assert l70 == data[op.CLE_TABLE][2]                     # cellule vide : ligne intacte
    assert l77["IMagasin"] == 12
    assert rap.nb_bloquants == 0 and rap.lignes_modifiees == 3 and rap.code_inventaire == "INV067"
    assert data[op.CLE_TABLE][0]["IMagasin"] == 0           # original jamais modifié


def test_numero_decale_retrouve_par_libelle():
    # « BANDELETTE » porte le N° 77 sur la liste (liste d'un autre inventaire, ou N°
    # mal lu) : retrouvée par son libellé (Chrono 70) ; la vraie ligne 77 passe aussi.
    out, rap = op.appliquer_lectures(_inventaire(), [_page([
        _lu(77, "BANDELETTE CODEFREE [B/50]", sv=9),
        _lu(77, "BAVETTE [B/50]", sv=2),
    ])])
    assert out[op.CLE_TABLE][2]["ISalle"] == 9 and out[op.CLE_TABLE][3]["ISalle"] == 2
    assert rap.nb_bloquants == 0
    assert any("1 ligne(s) retrouvée(s) par leur libellé" in a["message"] for a in rap.anomalies)
    assert {m["rapprochement"] for m in rap.modifications} == {"libelle", "numero"}


def test_liste_decalee_voisins_proches():
    """Cas réel des sondes : N° décalés d'un inventaire à l'autre ET libellés voisins
    (« N°6 » / « N°6,5 ») — le N° pointe sur le voisin, le libellé exact doit gagner."""
    data = {op.CLE_TABLE: [
        _ligne(697, "SONDE D'INTUBATION N°6", mesure="UNITE"),
        _ligne(698, "SONDE D'INTUBATION N°6,5", mesure="UNITE"),
        _ligne(699, "SONDE D'INTUBATION N°7", mesure="UNITE"),
    ]}
    out, rap = op.appliquer_lectures(data, [_page([
        _lu(698, "SONDE D'INTUBATION N°6 [UNITE]", sv=1),      # N° de la liste = 698
        _lu(699, "SONDE D'INTUBATION N°6,5 [UNITE]", sv=11),
        _lu(700, "SONDE D'INTUBATION N°7 [UNITE]", sv=5),       # 700 absent du JSON
    ])])
    l = {x["Chrono"]: x["ISalle"] for x in out[op.CLE_TABLE]}
    assert l == {697: 1, 698: 11, 699: 5} and rap.nb_bloquants == 0


def test_conditionnement_departage():
    data = {op.CLE_TABLE: [_ligne(39, "AMPOULE", mesure="1.20M"), _ligne(40, "AMPOULE", mesure="60CM")]}
    out, _ = op.appliquer_lectures(data, [_page([_lu(12, "AMPOULE [60CM]", mag=3)])])
    assert [x["IMagasin"] for x in out[op.CLE_TABLE]] == [0, 3]


def test_conditionnement_mal_lu_produit_unique():
    # Cas réel (scan basse résolution) : « PAPIER ECHO TYPE V [3/1] » lu, « B/1 » dans le JSON.
    data = {op.CLE_TABLE: [_ligne(509, "PAPIER ECHO TYPE V", mesure="B/1")]}
    out, rap = op.appliquer_lectures(data, [_page([_lu(574, "PAPIER ECHO TYPE V [3/1]", mag=0),
                                                    _lu(575, "PAPIER ECHO TYPE V [3/1]", mag=4)])])
    assert out[op.CLE_TABLE][0]["IMagasin"] == 0          # 1re lecture (0) : inchangé, 2e = doublon
    assert any("conditionnement différent" in a["message"] for a in rap.anomalies)


def test_ambiguite_et_produit_absent_bloques():
    data = {op.CLE_TABLE: [_ligne(5, "COTON", mesure="-"), _ligne(6, "COTON", mesure="-"),
                           _ligne(7, "SONDE D'INTUBATION N°6", mesure="UNITE"),
                           _ligne(8, "SONDE D'INTUBATION N°6,5", mesure="UNITE")]}
    out, rap = op.appliquer_lectures(data, [_page([
        _lu(99, "COTON [B/1]", mag=1),                         # 2 fois dans le JSON, N° non concordant
        _lu(50, "POCHETTE RADIOGRAPHIE [P/100]", sv=1),         # produit absent
        _lu(51, "SONDE D'INTUBATION N°6.5X [UNITE]", sv=2),     # proche de deux produits
    ])])
    assert out == data and rap.nb_bloquants == 3
    msgs = " | ".join(a["message"] for a in rap.anomalies)
    assert "plusieurs fois" in msgs and "aucun produit" in msgs and "plusieurs produits proches" in msgs


def test_anomalies_signalees():
    out, rap = op.appliquer_lectures(_inventaire(), [_page([
        _lu(999, "PRODUIT INCONNU XYZ [B/1]", mag=1),      # produit absent du JSON
        _lu(3, "ACETYL SALICLYLATE [B/1]", sv=1),
        _lu(3, "ACETYL SALICLYLATE [B/1]", sv=2),          # doublon
        _lu(77, "BAVETTE [B/50]", mag=-4),                 # négatif
        _lu(70, "BANDELETTE CODEFREE [B/50]", per="13/27"),  # mois invalide
    ], pied=5)])
    msgs = " | ".join(a["message"] for a in rap.anomalies)
    for attendu in ("aucun produit correspondant", "lu deux fois", "invalide « -4 »", "« 13/27 »",
                    "Pied de page : 5 lignes", "non retrouvée"):
        assert attendu in msgs, attendu
    assert out[op.CLE_TABLE][1]["ISalle"] == 1 and out[op.CLE_TABLE][3]["IMagasin"] == 0


def test_conventions_reelles_des_compteurs():
    """Lignes transcrites de vraies listes de pointage remplies à la main (pages 11 et
    12/15 fournies par le client) : zéros « 00 » / « / », zéros en tête « 07 »,
    additions « 1+1 », péremptions « 03/22 » ou « 2.27 », nom du compteur, note hors
    tableau. Le JSON est reconstitué avec les mêmes N° d'ordre et libellés."""
    data = {op.CLE_TABLE: [
        _ligne(688, "SONDE D'INTUBATION ARMEE N°4"), _ligne(691, "SONDE D'INTUBATION N°3", mesure="UNITE"),
        _ligne(696, "SONDE D'INTUBATION N°5,5", sv=3, mesure="UNITE"),
        _ligne(698, "SONDE D'INTUBATION N°6,5", mesure="UNITE"),
        _ligne(701, "SONDE D'INTUBATION N°8", sv=2, mesure="UNITE"),
        _ligne(704, "SONDE NASO GASTRIQUE CH8", mesure="UNITE"),
        _ligne(582, "PARACETAMOL INJ 1000MG-1G"),
    ]}
    pages = [
        {"page": "p.11", "titre": None, "compteur": "Dr Gacko / Inès", "nombre_de_lignes_pied": None,
         "annotations": ["Sonde Armée 7,5 => 9"],
         "lignes": [_lu(688, "SONDE D'INTUBATION ARMEE N°4 [B/1]", mag=2, incertain=True, note="écrit 1+1"),
                    _lu(691, "SONDE D'INTUBATION N°3 [UNITE]", mag="8+1")]},       # addition renvoyée brute
        {"page": "p.12", "titre": None, "compteur": "Koussoubé", "nombre_de_lignes_pied": None, "annotations": [],
         "lignes": [_lu(696, "SONDE D'INTUBATION N°5,5 [UNITE]", sv="07", per="03/22"),
                    _lu(698, "SONDE D'INTUBATION N°6,5 [UNITE]", sv=11),            # barre sur __/__ → null
                    _lu(701, "SONDE D'INTUBATION N°8 [UNITE]", sv=0),               # « 00 »
                    _lu(704, "SONDE NASO GASTRIQUE CH8 [UNITE]", sv=0)]},           # « / »
        {"page": "p.9", "titre": None, "nombre_de_lignes_pied": None,
         "lignes": [_lu(582, "PARACETAMOL ING 1000MG-1G [B/1]", mag=59, per="2.27")]},  # OCR « ING »
    ]
    out, rap = op.appliquer_lectures(data, pages)
    l = {x["Chrono"]: x for x in out[op.CLE_TABLE]}
    assert l[688]["IMagasin"] == 2 and l[691]["IMagasin"] == 9
    assert (l[696]["ISalle"], l[696]["Peremption1"], l[696]["Diff"]) == (7, "20220301", 4)
    assert l[698]["ISalle"] == 11 and l[698]["Peremption1"] == " "
    assert l[701]["ISalle"] == 0 and l[701]["Diff"] == -2 and l[701]["Saisie_par"] == "Claude"  # compté 0 : pointé
    assert (l[582]["IMagasin"], l[582]["Peremption1"]) == (59, "20270201")          # libellé toléré
    assert rap.nb_bloquants == 0
    assert rap.compteurs == [{"page": "p.11", "compteur": "Dr Gacko / Inès"}, {"page": "p.12", "compteur": "Koussoubé"}]
    msgs = " | ".join(a["message"] for a in rap.anomalies)
    assert "Sonde Armée 7,5 => 9" in msgs and "écrit 1+1" in msgs


def test_liste_d_un_autre_inventaire():
    """Cas réel : page 10/15 d'un inventaire antérieur rapprochée du JSON INV067 —
    N° 612 = POCHETTE RADIOGRAPHIE sur la liste, SERINGUE A INSULINE 1ML dans le JSON.
    Le produit présent dans le JSON est retrouvé par son libellé, l'absent est bloqué."""
    data = {op.CLE_TABLE: [_ligne(612, "SERINGUE A INSULINE 1ML", mesure="UNITE"),
                           _ligne(560, "POT DE PRELEVEMENT URINE", mesure="UNITE")]}
    out, rap = op.appliquer_lectures(data, [_page([
        _lu(612, "POCHETTE RADIOGRAPHIE [P/100]", sv=1),
        _lu(617, "POT DE PRELEVEMENT URINE [UNITE]", sv=55),
    ])])
    assert out[op.CLE_TABLE][0]["ISalle"] == 0 and out[op.CLE_TABLE][1]["ISalle"] == 55
    assert rap.nb_bloquants == 1


def test_autre_liste_signalee_non_bloquante():
    _, rap = op.appliquer_lectures(_inventaire(), [_page([], titre="Liste pointage n° INV066 du 28/08/2026")],
                                   code_attendu="InventaireSélectionné_PPH_INV067.json")
    assert rap.nb_bloquants == 0 and "INV066 ≠ JSON INV067" in rap.anomalies[0]["message"]


@pytest.mark.parametrize("texte,attendu", [
    ("06/28", "20280601"), ("6/28", "20280601"), ("06-2028", "20280601"), ("0628", "20280601"),
    ("13/28", None), ("", None), ("xx", None)])
def test_formats_peremption(texte, attendu):
    assert op.peremption_vers_hfsql(texte) == attendu


def test_json_invalide_refuse():
    for mauvais in (b"pas du json", b'{"autre": []}', b'{"REQ_D\\u00e9tailInventaire": [{"x": 1}]}'):
        with pytest.raises(ValueError):
            op.charger_json_inventaire(mauvais)


def test_format_windev_ascii():
    brut = op.json_windev(_inventaire())
    assert brut.startswith(b'{"REQ_D\\u00e9tailInventaire":[{"Chrono":1, ')
    assert json.loads(brut) == _inventaire()


# --- 2. Parcours via l'API --------------------------------------------------------
def _pdf(pages: int) -> bytes:
    import fitz
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page().insert_text((72, 72), "Liste pointage n° INV067")
    return doc.tobytes()


@pytest.fixture()
def fake_llm(monkeypatch):
    """Doublure de l'appel IA : réponse par page d'après le suffixe « p.N » du nom."""
    reponses = {
        "p.1": _page([_lu(1, "ARGESUN INJ 120MG [B/1]", mag=5, sv=3, per="06/28"),
                      _lu(3, "ACETYL SALICLYLATE [B/1]", sv=40)]),
        "p.2": _page([_lu(70, "BANDELETTE CODEFREE [B/50]"), _lu(77, "BAVETTE [B/50]", mag=2)],
                     titre=None, pied=4),
    }
    appels = []

    async def fake_call_llm(model, system_prompt, text, images, filename):
        assert "Liste pointage" in system_prompt and len(images) == 1 and text == ""
        appels.append((model.id, filename))
        page = reponses[filename.rsplit(" ", 1)[-1]]
        return json.dumps({k: v for k, v in page.items() if k != "page"}), 1500, 400

    monkeypatch.setattr(op, "call_llm", fake_call_llm)
    return appels


def _depot(env, user, json_bytes=None, kind="liste_pointage", scan=None, **form):
    files = {"file": ("liste_INV067.pdf", scan or _pdf(2), "application/pdf")}
    if json_bytes is not None:
        files["inventaire_json"] = ("InventaireSélectionné_PPH_INV067.json", json_bytes, "application/json")
    return env.client.post("/api/ocr-pieces", headers=_h(user), files=files, data={"kind": kind, **form})


def test_parcours_pharmacie(env, fake_llm):
    r = _depot(env, "pharma_a", json.dumps(_inventaire()).encode())
    assert r.status_code == 200, r.text
    piece = r.json()
    assert "inventaire_json_path" not in piece                  # chemin jamais exposé
    done = _wait_analysed(env, "pharma_a", piece["id"])
    assert done["status"] == "analyse", done
    assert done["json_complete_disponible"] is True
    assert done["extracted_fields"]["lignes_completees"] == 3
    assert done["extracted_fields"]["anomalies_bloquantes"] == 0
    assert "Aucune anomalie bloquante" in done["summary"]
    for cle in ("json_complete_path", "model", "cost_xof"):
        assert cle not in done
    assert len(fake_llm) == 2                                    # une requête par page

    dl = env.client.get(f"/api/ocr-pieces/{piece['id']}/json-complete", headers=_h("pharma_a"))
    assert dl.status_code == 200
    cd = dl.headers["content-disposition"]
    assert 'filename="InventaireSelectionne_PPH_INV067_complete.json"' in cd       # repli ASCII
    assert "filename*=UTF-8''InventaireS%C3%A9lectionn%C3%A9_PPH_INV067_complete.json" in cd
    complet = json.loads(dl.content)[op.CLE_TABLE]
    assert (complet[0]["IMagasin"], complet[0]["ISalle"], complet[0]["Peremption1"]) == (5, 3, "20280601")
    assert complet[0]["Saisie_par"] == "Claude" and len(complet[0]["DH_Saisie"]) == 17
    assert complet[3]["IMagasin"] == 2 and complet[2]["Saisie_par"] == ""

    # Autre pharmacie : aucun accès au JSON complété.
    assert env.client.get(f"/api/ocr-pieces/{piece['id']}/json-complete",
                          headers=_h("pharma_b")).status_code == 403


def test_admin_voit_rapport_et_relance(env, fake_llm):
    piece = _depot(env, "admin", json.dumps(_inventaire()).encode(), tenant_id="pharma_a",
                   model="claude-opus-5").json()
    done = _wait_analysed(env, "admin", piece["id"])
    run = done["ocr_runs"][0]
    assert run["model"] == "claude-opus-5" and run["pages_analyzed"] == 2
    assert run["pointage_rapport"]["lignes_modifiees"] == 3 and run["cost_xof"] > 0
    # Relance : le JSON d'origine est relu depuis le stockage.
    r = env.client.post(f"/api/ocr-pieces/{piece['id']}/reanalyze", headers=_h("admin"),
                        json={"model": "claude-sonnet-5"})
    assert r.status_code == 200
    done = _wait_analysed(env, "admin", piece["id"])
    assert [x["model"] for x in done["ocr_runs"]] == ["claude-opus-5", "claude-sonnet-5"]
    # Suppression : scan, JSON d'origine et JSON complétés marqués supprimés.
    assert env.client.delete(f"/api/ocr-pieces/{piece['id']}", headers=_h("admin")).status_code == 200
    rows = env.client.portal.call(env.db.stored_objects.find({}, {"_id": 0}).to_list, 100)
    assert rows and all(r["is_deleted"] for r in rows)


def test_depot_refuse_sans_json_ou_json_invalide(env, fake_llm):
    assert _depot(env, "pharma_a").status_code == 400
    assert _depot(env, "pharma_a", b"pas du json").status_code == 400
    assert _depot(env, "pharma_a", b'{"autre": []}').status_code == 400
    r = env.client.post("/api/ocr-pieces", headers=_h("pharma_a"),
                        files={"file": ("liste.txt", b"texte", "text/plain"),
                               "inventaire_json": ("inv.json", json.dumps(_inventaire()).encode(), "application/json")},
                        data={"kind": "liste_pointage"})
    assert r.status_code == 400
    assert fake_llm == []                                        # aucun appel IA payé


def test_json_complete_refuse_pour_une_facture(env, monkeypatch):
    piece = env.client.post("/api/ocr-pieces", headers=_h("pharma_a"),
                            files={"file": ("f.pdf", _pdf(1), "application/pdf")}).json()
    _wait_analysed(env, "pharma_a", piece["id"])
    assert env.client.get(f"/api/ocr-pieces/{piece['id']}/json-complete",
                          headers=_h("pharma_a")).status_code == 400
