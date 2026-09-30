"""Lot 47 — Parc informatique : équipements (numérotation, IP / MAC, unicité, filtres, CSV),
interventions multi-équipements avec équipe, état reporté, historique, rapport public, envoi
WhatsApp (dans / hors fenêtre de 24 h), signature (preuves, verrouillage), droits.
MongoDB simulé, WhatsApp simulé, horloge simulée.
Lancer : cd backend && python -m pytest tests/test_parc_informatique_lot47.py -q
"""
from __future__ import annotations

import base64
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.parc_informatique as pi  # noqa: E402

USERS = {"admin": {"id": "admin", "role": "admin", "full_name": "Admin SAWALI"},
         "phl": {"id": "phl", "role": "pharmacien", "company": "Pharmacie PHL", "client_code": "PHL",
                 "whatsapp_number": "+226 70 11 22 33"},
         "suivi": {"id": "suivi", "role": "client", "parent_client_id": "phl", "client_id": "phl", "full_name": "Awa"},
         "amy": {"id": "amy", "role": "pharmacien", "company": "Pharmacie AMY", "client_code": "AMY"},
         "sans": {"id": "sans", "role": "client", "client_code": "SAN"}}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200
SIGNATURE = "data:image/png;base64," + base64.b64encode(PNG).decode()


@pytest.fixture()
def env(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_parc47"]
    envoyes, fenetres, notifications = [], set(), []
    horloge = {"t": datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(pi, "_maintenant", lambda: horloge["t"].isoformat())

    async def get_user(request: Request):
        u = USERS.get(request.headers.get("X-User", ""))
        if not u:
            raise HTTPException(status_code=401)
        return u

    async def fonction_active(user, cle):
        assert cle == "parc_informatique"
        return user["id"] != "sans"

    async def wa_text(to, texte):
        envoyes.append(("texte", to, texte))
        return {"ok": True}

    async def wa_template(to, nom, langue, comps):
        envoyes.append(("modele", to, nom, comps))
        return {"ok": True}

    def build(variables, ctx, header_text=None, header_media=None, button_specs=None):
        return [{"type": "body", "parameters": [re.sub(r"\{\{(\w+)\}\}", lambda m: ctx.get(m.group(1), ""), v)
                                                for v in variables]}]

    async def ouvertes(chiffres):
        return {c for c in chiffres if c in fenetres}

    async def notifier(sujet, texte):
        notifications.append((sujet, texte))
        return {"envoye": True}

    async def save_and_log(db_, *, data, kind, tenant_id, ext, content_type, original_filename, user_id):
        return {"url": f"/api/files/parc/{len(data)}.{ext}"}

    api = APIRouter(prefix="/api")
    pi.attach_parc_routes(api=api, db=db, get_current_user=get_user, fonction_active=fonction_active,
                          save_and_log=save_and_log, base_publique=lambda: "https://sawali.test",
                          wa_send_text=wa_text, wa_send_template=wa_template, build_components=build,
                          fenetres_ouvertes=ouvertes, notifier_admin=notifier,
                          client_ip=lambda r: r.headers.get("X-Forwarded-For", "10.0.0.1"))
    app = FastAPI()
    app.include_router(api)
    client = TestClient(app).__enter__()
    client.portal.call(db.users.insert_many, [dict(u) for u in USERS.values()])

    def avancer(minutes):
        horloge["t"] += timedelta(minutes=minutes)

    yield {"c": client, "db": db, "envoyes": envoyes, "fenetres": fenetres, "notifications": notifications,
           "avancer": avancer}
    client.__exit__(None, None, None)


def h(u):
    return {"X-User": u}


def _equipement(c, u="admin", **extra):
    corps = {"compte_client_id": "phl", "categorie": "PC portable", "fabricant": "HP", "modele": "ProBook 450",
             **extra}
    return c.post("/api/me/parc/equipements", headers=h(u), json=corps)


def _intervention(c, ids, u="admin", **extra):
    corps = {"equipement_ids": ids, "type_intervention": "curative", "debut": "2026-09-30T08:00",
             "fin": "2026-09-30T09:30", "equipe": ["Issa", {"nom": "Awa", "user_id": "suivi"}, "issa"],
             "probleme": "Ne démarre plus", "actions": "Remplacement de la barrette mémoire",
             "pieces": [{"designation": "Barrette DDR4 8 Go", "quantite": 1, "reference": "KVR26"}],
             "resultat": "Poste fonctionnel", "recommandations": "Sauvegarde hebdomadaire", "etat_apres": "en_service",
             "responsable": {"nom": "Dr Ouédraogo", "fonction": "Pharmacien titulaire"}, **extra}
    return c.post("/api/me/parc/interventions", headers=h(u), json=corps)


# ---- Équipements -------------------------------------------------------------------------------
def test_creation_et_numerotation(env):
    c = env["c"]
    e1 = _equipement(c, adresse_ip=" 192.168.1.10 ", adresse_mac="aa-bb-cc-dd-ee-ff", numero_serie="5CD 123").json()
    assert e1["numero_inventaire"] == "PARC-PHL-0001" and e1["tenant_id"] == "phl"
    assert e1["client_nom"] == "Pharmacie PHL" and e1["etat"] == "en_service"
    assert e1["adresse_ip"] == "192.168.1.10" and e1["adresse_mac"] == "AA:BB:CC:DD:EE:FF"
    # Le compte client (et son utilisateur suivi) crée dans SON parc, numérotation continue
    e2 = _equipement(c, u="suivi", compte_client_id=None, categorie="Imprimante", adresse_ip="fe80::1",
                     adresse_mac="aabb.ccdd.eef0").json()
    assert e2["numero_inventaire"] == "PARC-PHL-0002" and e2["adresse_mac"] == "AA:BB:CC:DD:EE:F0"
    # Un autre client : sa propre numérotation
    assert _equipement(c, compte_client_id="amy").json()["numero_inventaire"] == "PARC-AMY-0001"
    # Un client ne choisit pas un autre compte
    assert _equipement(c, u="phl", compte_client_id="amy").status_code == 403


def test_validation_ip_mac(env):
    c = env["c"]
    r = _equipement(c, adresse_ip="192.168.1.300")
    assert r.status_code == 400 and "Adresse IP invalide" in r.json()["detail"]
    r = _equipement(c, adresse_mac="AA:BB:CC:DD:EE")
    assert r.status_code == 400 and "Adresse MAC invalide" in r.json()["detail"]
    assert _equipement(c, date_achat="31/01/2025").json()["date_achat"] == "2025-01-31"
    assert _equipement(c, fin_garantie="demain").status_code == 400
    assert pi.normaliser_mac("aabbccddeeff") == "AA:BB:CC:DD:EE:FF"
    assert pi.normaliser_ip("2001:0db8::0001") == "2001:db8::1"


def test_unicite_serie_et_mac(env):
    c = env["c"]
    _equipement(c, numero_serie="SN-001", adresse_mac="AA:BB:CC:00:00:01")
    r = _equipement(c, numero_serie="sn-001 ")
    assert r.status_code == 409 and "PARC-PHL-0001" in r.json()["detail"] and "n° de série" in r.json()["detail"]
    r = _equipement(c, adresse_mac="aa:bb:cc:00:00:01")
    assert r.status_code == 409 and "adresse MAC" in r.json()["detail"]
    # Même série chez un autre client : accepté ; modification de soi-même : acceptée
    assert _equipement(c, compte_client_id="amy", numero_serie="SN-001").status_code == 200
    e = c.get("/api/me/parc/equipements", headers=h("admin"), params={"compte_client_id": "phl"}).json()["equipements"][0]
    corps = {k: e[k] for k in ("categorie", "fabricant", "modele", "numero_serie", "adresse_mac")}
    assert c.put(f"/api/me/parc/equipements/{e['id']}", headers=h("admin"), json={**corps, "site": "Siège"}).status_code == 200


def test_filtres_et_compteurs(env):
    c = env["c"]
    _equipement(c, categorie="Imprimante", site="Siège", etat="en_panne")
    _equipement(c, site="Annexe", utilisateur_affecte="Awa")
    _equipement(c, compte_client_id="amy", site="Siège")
    d = c.get("/api/me/parc/equipements", headers=h("admin"), params={"compte_client_id": "phl"}).json()
    assert d["total"] == 2 and d["compte"]["en_panne"] == 1 and d["compte"]["en_service"] == 1
    assert d["sites"] == ["Annexe", "Siège"] and d["par_categorie"] == {"Imprimante": 1, "PC portable": 1}
    assert len(c.get("/api/me/parc/equipements", headers=h("admin")).json()["equipements"]) == 3
    f = c.get("/api/me/parc/equipements", headers=h("admin"), params={"etat": "en_panne"}).json()["equipements"]
    assert [e["categorie"] for e in f] == ["Imprimante"]
    f = c.get("/api/me/parc/equipements", headers=h("admin"), params={"site": "Siège"}).json()["equipements"]
    assert len(f) == 2
    assert len(c.get("/api/me/parc/equipements", headers=h("phl"), params={"q": "awa"}).json()["equipements"]) == 1
    # Le client ne voit que son parc, même en demandant un autre compte
    assert c.get("/api/me/parc/equipements", headers=h("phl"), params={"compte_client_id": "amy"}).json()["total"] == 2


def test_categories_extensibles(env):
    c = env["c"]
    assert c.post("/api/me/parc-categories", headers=h("phl"), json={"libelle": "Scanner"}).status_code == 200
    assert c.post("/api/me/parc-categories", headers=h("phl"), json={"libelle": "scanner"}).status_code == 409
    toutes = c.get("/api/me/parc-categories", headers=h("suivi")).json()["toutes"]
    assert "Scanner" in toutes and toutes[-1] == "Autre"
    assert "Scanner" not in c.get("/api/me/parc-categories", headers=h("amy")).json()["toutes"]


def test_export_et_import_csv(env):
    c = env["c"]
    _equipement(c, numero_serie="SN-1", adresse_mac="AA:BB:CC:00:00:01", notes="=SOMME(A1)")
    r = c.get("/api/me/parc/equipements/export.csv", headers=h("admin"), params={"compte_client_id": "phl"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    texte = r.content.decode("utf-8")
    assert texte.startswith("﻿") and "Client;N° inventaire;Catégorie" in texte
    assert "PARC-PHL-0001;PC portable;HP" in texte and "'=SOMME(A1)" in texte and "En service" in texte
    csv_import = ("Catégorie;Fabricant;Modele;N° de serie;Adresse MAC;Adresse IP;Etat;Site\n"
                  "Imprimante;Canon;LBP;SN-2;;192.168.1.20;En panne;Siège\n"
                  "Switch;Cisco;;SN-1;;;;\n"                                 # série déjà utilisée
                  ";Dell;;;;;;\n"                                          # catégorie manquante
                  "PC de bureau;Dell;;SN-3;zz;;;\n"                        # MAC invalide
                  "Onduleur;APC;;SN-4;;;Cassé;\n"                          # état inconnu
                  "Routeur;MikroTik;;SN-5;11-22-33-44-55-66;;en_stock;Annexe\n").encode("utf-8")
    r = c.post("/api/me/parc/equipements/import", headers=h("admin"), data={"compte_client_id": "phl"},
               files={"fichier": ("parc.csv", csv_import, "text/csv")})
    d = r.json()
    assert r.status_code == 200 and d["importes"] == 2 and d["numeros"] == ["PARC-PHL-0002", "PARC-PHL-0003"]
    assert [x["ligne"] for x in d["rejets"]] == [3, 4, 5, 6]
    assert "SN-1" in d["rejets"][0]["motif"] and "Catégorie" in d["rejets"][1]["motif"]
    assert "MAC" in d["rejets"][2]["motif"] and "État inconnu" in d["rejets"][3]["motif"]
    liste = c.get("/api/me/parc/equipements", headers=h("phl")).json()["equipements"]
    routeur = next(e for e in liste if e["categorie"] == "Routeur")
    assert routeur["adresse_mac"] == "11:22:33:44:55:66" and routeur["etat"] == "en_stock"
    # Séparateur « , » et fichier sans colonne Catégorie
    r = c.post("/api/me/parc/equipements/import", headers=h("phl"),
               files={"fichier": ("p.csv", "Fabricant,Modele\nHP,X\n".encode(), "text/csv")})
    assert r.status_code == 400


# ---- Interventions ------------------------------------------------------------------------------
def test_intervention_multi_equipements_equipe_etat_historique(env):
    c, db = env["c"], env["db"]
    e1 = _equipement(c, numero_serie="SN-1", adresse_mac="AA:BB:CC:00:00:01", etat="en_panne").json()
    e2 = _equipement(c, categorie="Imprimante", etat="en_panne").json()
    iv = _intervention(c, [e1["id"], e2["id"]]).json()
    assert iv["numero"] == "INT-PHL-2026-0001" and iv["tenant_id"] == "phl" and iv["statut"] == "terminee"
    assert iv["duree_minutes"] == 90 and iv["etat_signature"] == "sans_rapport"
    assert iv["equipe"] == [{"nom": "Issa", "user_id": None}, {"nom": "Awa", "user_id": "suivi"}]
    assert [e["numero_inventaire"] for e in iv["equipements"]] == ["PARC-PHL-0001", "PARC-PHL-0002"]
    assert iv["equipements"][0]["adresse_mac"] == "AA:BB:CC:00:00:01"
    # Responsable : saisi ; le téléphone manquant est repris du client (numéro des alertes)
    assert iv["responsable"]["nom"] == "Dr Ouédraogo" and iv["responsable"]["telephone"] == "+226 70 11 22 33"
    # État reporté sur les équipements
    f1 = c.get(f"/api/me/parc/equipements/{e1['id']}", headers=h("phl")).json()
    assert f1["etat"] == "en_service" and f1["derniere_intervention"]["numero"] == "INT-PHL-2026-0001"
    # Historique : ordre chronologique inverse
    env["avancer"](60 * 24)
    iv2 = _intervention(c, [e1["id"]], debut="2026-10-01T10:00", fin=None, etat_apres="en_reparation").json()
    assert iv2["statut"] == "en_cours" and iv2["numero"] == "INT-PHL-2026-0002"
    f1 = c.get(f"/api/me/parc/equipements/{e1['id']}", headers=h("admin")).json()
    assert [i["numero"] for i in f1["interventions"]] == ["INT-PHL-2026-0002", "INT-PHL-2026-0001"]
    assert f1["etat"] == "en_reparation"
    assert len(c.get(f"/api/me/parc/equipements/{e2['id']}", headers=h("admin")).json()["interventions"]) == 1
    # Démarrer / terminer
    iv3 = _intervention(c, [e2["id"]], debut=None, fin=None).json()
    assert iv3["statut"] == "planifiee"
    assert c.post(f"/api/me/parc/interventions/{iv3['id']}/terminer", headers=h("admin")).status_code == 409
    assert c.post(f"/api/me/parc/interventions/{iv3['id']}/demarrer", headers=h("admin")).json()["statut"] == "en_cours"
    env["avancer"](45)
    t = c.post(f"/api/me/parc/interventions/{iv3['id']}/terminer", headers=h("admin")).json()
    assert t["statut"] == "terminee" and t["duree_minutes"] == 45
    # Dates incohérentes, équipements de deux clients, équipement supprimable ou non
    assert _intervention(c, [e1["id"]], debut="2026-09-30T10:00", fin="2026-09-30T09:00").status_code == 400
    autre = _equipement(c, compte_client_id="amy").json()
    assert _intervention(c, [e1["id"], autre["id"]]).status_code == 400
    assert c.delete(f"/api/me/parc/equipements/{e1['id']}", headers=h("admin")).status_code == 409
    assert c.delete(f"/api/me/parc/equipements/{autre['id']}", headers=h("admin")).status_code == 200
    assert c.portal.call(db.parc_interventions.count_documents, {}) == 3


# ---- Rapport, envoi, signature ----------------------------------------------------------------
def _rapport(env):
    c = env["c"]
    e = _equipement(c, numero_serie="SN-9", adresse_ip="10.0.0.5").json()
    iv = _intervention(c, [e["id"]]).json()
    r = c.post(f"/api/me/parc/interventions/{iv['id']}/rapport", headers=h("admin"), json={}).json()
    return iv, r


def test_lien_public_du_rapport(env):
    c = env["c"]
    iv, r = _rapport(env)
    lien = r["rapport"]["url"]
    jeton = r["rapport"]["jeton"]
    assert lien == f"https://sawali.test/rapport-parc/{jeton}" and len(jeton) >= 40
    assert r["etat_signature"] == "en_attente" and r["rapport"]["expire_le"].startswith("2026-10-30")
    # Le même lien est rendu tant qu'il est valable ; « renouveler » en crée un autre
    assert c.post(f"/api/me/parc/interventions/{iv['id']}/rapport", headers=h("admin"), json={}).json()["rapport"]["jeton"] == jeton
    p = c.get(f"/api/public/parc-rapport/{jeton}")
    assert p.status_code == 200 and "noindex" in p.headers["x-robots-tag"]
    d = p.json()
    assert d["numero"] == iv["numero"] and d["client"] == "Pharmacie PHL" and d["signable"] is True
    assert d["equipements"][0]["numero_serie"] == "SN-9" and d["equipements"][0]["adresse_ip"] == "10.0.0.5"
    assert d["equipe"] == ["Issa", "Awa"] and d["prestataire"]["email"] == "contact@sawalismartsystems.com"
    assert re.fullmatch(r"[0-9a-f]{64}", d["empreinte_sha256"]) and "tenant_id" not in d and "telephone" not in d["responsable"]
    assert c.get(f"/api/public/parc-rapport/{jeton}/pdf").content.startswith(b"%PDF")
    assert c.get(f"/api/me/parc/interventions/{iv['id']}/pdf", headers=h("phl")).content.startswith(b"%PDF")
    # Lien inconnu ou mal formé : 404
    assert c.get("/api/public/parc-rapport/" + "x" * 43).status_code == 404
    assert c.get("/api/public/parc-rapport/abc").status_code == 404
    nouveau = c.post(f"/api/me/parc/interventions/{iv['id']}/rapport", headers=h("admin"), json={"renouveler": True}).json()
    assert nouveau["rapport"]["jeton"] != jeton and c.get(f"/api/public/parc-rapport/{jeton}").status_code == 404


def test_envoi_whatsapp_dans_et_hors_fenetre(env):
    c, envoyes = env["c"], env["envoyes"]
    iv, r = _rapport(env)
    lien = r["rapport"]["url"]
    # Hors fenêtre de 24 h, sans modèle : refus clair
    x = c.post(f"/api/me/parc/interventions/{iv['id']}/envoyer", headers=h("admin"), json={})
    assert x.status_code == 400 and "modèle Meta" in x.json()["detail"]
    # Hors fenêtre, modèle Meta : variables numéro, client, date, lien
    x = c.post(f"/api/me/parc/interventions/{iv['id']}/envoyer", headers=h("admin"),
               json={"template_name": "sawali_rapport_intervention",
                     "variables": ["{{numero}}", "{{client}}", "{{date}}", "{{lien}}"]}).json()
    assert x["mode"] == "template" and x["fenetre_ouverte"] is False
    assert envoyes[-1] == ("modele", "+226 70 11 22 33", "sawali_rapport_intervention",
                           [{"type": "body", "parameters": [iv["numero"], "Pharmacie PHL", "30/09/2026", lien]}])
    # Dans la fenêtre : message libre avec le lien
    env["fenetres"].add("22670112233")
    x = c.post(f"/api/me/parc/interventions/{iv['id']}/envoyer", headers=h("admin"), json={}).json()
    assert x["mode"] == "text" and envoyes[-1][0] == "texte" and lien in envoyes[-1][2]
    assert "Dr Ouédraogo, merci de lire le rapport" in envoyes[-1][2]
    assert len(c.get(f"/api/me/parc/interventions/{iv['id']}", headers=h("admin")).json()["envois"]) == 2
    # E-mail : SMTP non branché ici -> 503 ; adresse manquante -> 400
    assert c.post(f"/api/me/parc/interventions/{iv['id']}/envoyer", headers=h("admin"), json={"canal": "email"}).status_code == 400
    assert c.post(f"/api/me/parc/interventions/{iv['id']}/envoyer", headers=h("admin"),
                  json={"canal": "email", "email": "dr@phl.bf"}).status_code == 503


def test_signature_preuves_verrouillage(env):
    c, db = env["c"], env["db"]
    iv, r = _rapport(env)
    jeton = r["rapport"]["jeton"]
    lu = c.get(f"/api/public/parc-rapport/{jeton}").json()
    # Modification après lecture : l'empreinte change, la signature est refusée
    corps = {"equipement_ids": iv["equipement_ids"], "equipe": ["Issa"], "probleme": "Écran noir",
             "debut": "2026-09-30T08:00", "fin": "2026-09-30T09:30"}
    assert c.put(f"/api/me/parc/interventions/{iv['id']}", headers=h("admin"), json=corps).status_code == 200
    signature = {"nom": "Dr Ouédraogo", "fonction": "Pharmacien titulaire", "image": SIGNATURE,
                 "empreinte": lu["empreinte_sha256"], "accepte": True}
    x = c.post(f"/api/public/parc-rapport/{jeton}/signer", json=signature)
    assert x.status_code == 409 and "modifié" in x.json()["detail"]
    lu = c.get(f"/api/public/parc-rapport/{jeton}").json()
    signature["empreinte"] = lu["empreinte_sha256"]
    assert c.post(f"/api/public/parc-rapport/{jeton}/signer", json={**signature, "accepte": False}).status_code == 400
    assert c.post(f"/api/public/parc-rapport/{jeton}/signer", json={**signature, "image": "data:image/png;base64,QUJD" + "A" * 40}).status_code == 400
    env["avancer"](30)
    x = c.post(f"/api/public/parc-rapport/{jeton}/signer", json=signature,
               headers={"User-Agent": "Mozilla/5.0 Test", "X-Forwarded-For": "41.138.1.2"})
    assert x.status_code == 200
    s = x.json()["signature"]
    assert s["nom"] == "Dr Ouédraogo" and s["fonction"] == "Pharmacien titulaire" and s["ip"] == "41.138.1.2"
    assert s["navigateur"] == "Mozilla/5.0 Test" and s["signe_le"].startswith("2026-09-30T08:30")
    assert s["empreinte"] == lu["empreinte_sha256"] and s["image"] == SIGNATURE and x.json()["signable"] is False
    stocke = c.portal.call(db.parc_interventions.find_one, {"id": iv["id"]})["signature"]
    assert stocke["image_sha256"] and stocke["jeton"] == jeton
    # Double signature refusée
    assert c.post(f"/api/public/parc-rapport/{jeton}/signer", json=signature).status_code == 409
    # Notification Liluvine de l'admin
    assert env["notifications"] and "signé" in env["notifications"][0][1] and iv["numero"] in env["notifications"][0][1]
    # Verrouillage : modification, photos, démarrage, suppression refusés (423)
    assert c.put(f"/api/me/parc/interventions/{iv['id']}", headers=h("admin"), json=corps).status_code == 423
    assert c.delete(f"/api/me/parc/interventions/{iv['id']}", headers=h("admin")).status_code == 423
    assert c.post(f"/api/me/parc/interventions/{iv['id']}/photos", headers=h("admin"),
                  files={"fichier": ("a.png", PNG, "image/png")}).status_code == 423
    # Badge « Signé » dans la liste ; le lien signé reste lisible et n'est pas renouvelé
    liste = c.get("/api/me/parc/interventions", headers=h("phl")).json()
    assert liste["compte"]["signe"] == 1 and liste["interventions"][0]["etat_signature"] == "signe"
    assert c.post(f"/api/me/parc/interventions/{iv['id']}/rapport", headers=h("admin"),
                  json={"renouveler": True}).json()["rapport"]["jeton"] == jeton
    assert c.get(f"/api/public/parc-rapport/{jeton}").json()["signature"]["nom"] == "Dr Ouédraogo"
    assert c.get(f"/api/public/parc-rapport/{jeton}/pdf").content.startswith(b"%PDF")


def test_lien_expire(env):
    c = env["c"]
    iv, r = _rapport(env)
    jeton = r["rapport"]["jeton"]
    empreinte = c.get(f"/api/public/parc-rapport/{jeton}").json()["empreinte_sha256"]
    env["avancer"](60 * 24 * 31)
    d = c.get(f"/api/public/parc-rapport/{jeton}").json()
    assert d["expire"] is True and d["signable"] is False
    x = c.post(f"/api/public/parc-rapport/{jeton}/signer",
               json={"nom": "Dr O", "image": SIGNATURE, "empreinte": empreinte, "accepte": True})
    assert x.status_code == 410
    # Un nouveau lien est créé à la demande (ou à l'envoi)
    assert c.post(f"/api/me/parc/interventions/{iv['id']}/rapport", headers=h("admin"), json={}).json()["rapport"]["jeton"] != jeton


# ---- Droits ---------------------------------------------------------------------------------------
def test_droits(env):
    c = env["c"]
    e = _equipement(c).json()
    iv = _intervention(c, [e["id"]]).json()
    # Autre client : 404 sur l'équipement et l'intervention
    assert c.get(f"/api/me/parc/equipements/{e['id']}", headers=h("amy")).status_code == 404
    assert c.get(f"/api/me/parc/interventions/{iv['id']}", headers=h("amy")).status_code == 404
    assert c.post(f"/api/me/parc/interventions/{iv['id']}/rapport", headers=h("amy"), json={}).status_code == 404
    assert _intervention(c, [e["id"]], u="amy").status_code == 404
    assert c.get("/api/me/parc/interventions", headers=h("amy")).json()["interventions"] == []
    # Le client et son utilisateur suivi voient leur parc et leurs interventions
    assert c.get(f"/api/me/parc/interventions/{iv['id']}", headers=h("suivi")).status_code == 200
    assert len(c.get("/api/me/parc/interventions", headers=h("phl")).json()["interventions"]) == 1
    # Fonction inactive : 403
    r = c.get("/api/me/parc/equipements", headers=h("sans"))
    assert r.status_code == 403 and "Parc informatique" in r.json()["detail"]
    # Comptes proposés : tous pour l'Admin, le sien pour un client
    assert {x["id"] for x in c.get("/api/me/parc-clients", headers=h("admin")).json()["items"]} >= {"phl", "amy"}
    assert [x["id"] for x in c.get("/api/me/parc-clients", headers=h("suivi")).json()["items"]] == ["phl"]
    # Responsable du client
    r = c.put("/api/me/parc-responsable", headers=h("phl"), json={"nom": "Dr O", "telephone": "70 00 00 00",
                                                                  "email": "dr@phl.bf"}).json()
    assert r["nom"] == "Dr O" and c.get("/api/me/parc-responsable", headers=h("admin"),
                                        params={"compte_client_id": "phl"}).json()["email"] == "dr@phl.bf"
