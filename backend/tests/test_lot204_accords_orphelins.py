# Lot 204 — accords WhatsApp sans fiche : repérés, rattachés à un client (accord d'origine conservé), puis servis.
import asyncio

from mongomock_motor import AsyncMongoMockClient

from routes import carrousel_accords_orphelins as ao


def _run(c):
    return asyncio.new_event_loop().run_until_complete(c)


def _journal(db, tel, accepte=True, fiches=0, le="2026-10-15T08:55:25+00:00", moyen="bouton", tenant=None):
    return db.accords_whatsapp_journal.insert_one({"telephone": tel, "accepte": accepte, "moyen": moyen, "numero_recu": None,
                                                    "tenant_id": tenant, "fiches": fiches, "le": le})


def test_orphelin_liste_avec_nom_du_profil():
    db = AsyncMongoMockClient()["t"]
    _run(_journal(db, "22677001214"))
    _run(db.wa_pending_imports.insert_one({"phone_digits": "22677001214", "wa_profile_name": "alixyame"}))
    lignes = _run(ao.lister(db))
    assert lignes == [{"telephone": "22677001214", "nom": "alixyame", "le": "2026-10-15T08:55:25+00:00", "moyen": "bouton"}]


def test_pas_orphelin_si_fiche_retrait_ou_accord_rattache():
    db = AsyncMongoMockClient()["t"]
    _run(_journal(db, "22670000001"))                                   # a une fiche → exclu
    _run(db.directory_contacts.insert_one({"id": "c1", "whatsapp": "+226 70 00 00 01"}))
    _run(_journal(db, "22670000002"))                                   # puis retrait → exclu
    _run(_journal(db, "22670000002", accepte=False, le="2026-10-15T09:00:00+00:00"))
    _run(_journal(db, "22670000003", fiches=2))                         # accord déjà noté sur des fiches → exclu
    _run(_journal(db, "22670000004", tenant="t1"))                      # numéro propre d'un client → hors périmètre
    assert _run(ao.lister(db)) == []


def test_rattachement_cree_la_fiche_avec_l_accord_d_origine():
    db = AsyncMongoMockClient()["t"]
    _run(_journal(db, "22677001214", le="2026-10-15T08:55:25+00:00"))
    _run(db.wa_pending_imports.insert_one({"phone_digits": "22677001214", "wa_profile_name": "alixyame"}))
    res = _run(ao.rattacher(db, [{"telephone": "22677001214", "client_id": "cl1", "nom": ""}], {"cl1": "Clinique Alpha"}, "Admin"))
    assert len(res["crees"]) == 1 and res["refuses"] == []
    fiche = _run(db.directory_contacts.find_one({"client_id": "cl1"}))
    assert fiche["name"] == "alixyame" and fiche["whatsapp"] == "+22677001214"
    assert fiche["accepte_whatsapp"] is True and fiche["accepte_whatsapp_le"] == "2026-10-15T08:55:25+00:00"   # date d'origine
    assert "la personne elle-même (bouton)" in fiche["accepte_whatsapp_par"] and "Admin" in fiche["accepte_whatsapp_par"]
    assert _run(db.wa_pending_imports.count_documents({})) == 0
    trace = _run(db.accords_whatsapp_journal.find_one({"type": "rattachement"}))
    assert trace["client_id"] == "cl1" and trace["contact_id"] == fiche["id"]
    # Deuxième appel : plus rien à rattacher (le numéro a une fiche)
    assert _run(ao.lister(db)) == []
    res2 = _run(ao.rattacher(db, [{"telephone": "22677001214", "client_id": "cl1"}], {"cl1": "Clinique Alpha"}, "Admin"))
    assert res2["crees"] == [] and res2["refuses"]


def test_client_hors_liste_refuse():
    db = AsyncMongoMockClient()["t"]
    _run(_journal(db, "22677001214"))
    res = _run(ao.rattacher(db, [{"telephone": "22677001214", "client_id": "inconnu"}], {"cl1": "A"}, "Admin"))
    assert res["crees"] == [] and "client" in res["refuses"][0]["motif"].lower()
    assert _run(db.directory_contacts.count_documents({})) == 0


# ---- Routes (administration) : rattacher puis envoyer le carrousel choisi, sans jamais renvoyer aux déjà servis ----
import asyncio as _aio  # noqa: E402

from tests.test_carrousel_programmation_lot114 import env  # noqa: E402,F401  (fixture : application de test + base simulée)
from tests.test_carrousel_whatsapp import h  # noqa: E402


def test_routes_rattacher_et_envoyer(env):
    client, db, envois, _, moteur = env
    # Une campagne de l'administration déjà terminée (Awa a déjà reçu le carrousel)
    client.portal.call(db.carrousel_campagnes.insert_one, {
        "id": "camp1", "perimetre": "admin", "tenant_id": None, "cree_le": "2026-10-15T07:00:00+00:00", "cree_par": "admin",
        "cree_par_nom": "Admin", "expediteur": "SAWALI", "message": "Nouveautés d'octobre", "cartes": [{"titre": "A", "texte": "Offre", "lien": "https://x.bf", "code_lien": "abc", "image_url": "https://x.bf/a.png", "bouton": "presentation"},
                   {"titre": "B", "texte": "Offre", "lien": "https://x.bf", "code_lien": "abd", "image_url": "https://x.bf/b.png", "bouton": "presentation"}],
        "modele": "sawali_carrousel_2", "langue": "fr", "creds_tenant": None, "statut": "TERMINEE", "reprenable": True,
        "destinataires": [{"id": "c1", "nom": "Awa", "telephone": "22676111111", "statut": "ENVOYE"}],
        "compte": {"total": 1, "envoyes": 1, "echecs": 0}})
    client.portal.call(db.accords_whatsapp_journal.insert_one, {
        "telephone": "22677001214", "accepte": True, "moyen": "bouton", "numero_recu": None, "tenant_id": None, "fiches": 0,
        "le": "2026-10-15T08:55:25+00:00"})
    # Lecture : la personne est orpheline, les clients et le carrousel à envoyer sont proposés
    r = client.get("/api/admin/whatsapp/carrousel/accords-orphelins", headers=h("admin"))
    assert r.status_code == 200, r.text
    d = r.json()
    assert [o["telephone"] for o in d["orphelins"]] == ["22677001214"]
    assert {c["id"] for c in d["clients"]} >= {"cli_a", "cli_b"} and d["campagnes"][0]["id"] == "camp1"
    # Client hors liste : refusé, rien n'est créé ni envoyé
    r = client.post("/api/admin/whatsapp/carrousel/accords-orphelins/rattacher", headers=h("admin"),
                    json={"items": [{"telephone": "22677001214", "client_id": "inconnu"}], "campagne_id": "camp1"})
    assert r.status_code == 200 and r.json()["crees"] == [] and envois == []
    # Rattachement au client A + envoi du carrousel
    r = client.post("/api/admin/whatsapp/carrousel/accords-orphelins/rattacher", headers=h("admin"),
                    json={"items": [{"telephone": "22677001214", "client_id": "cli_a", "nom": "Alix"}], "campagne_id": "camp1"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert len(res["crees"]) == 1 and res["envoi"] == {"campagne_id": "camp1", "destinataires": 1, "deja": 0}
    fiche = client.portal.call(db.directory_contacts.find_one, {"client_id": "cli_a", "source": "accord_rattache"})
    assert fiche["name"] == "Alix" and fiche["accepte_whatsapp"] is True and fiche["accepte_whatsapp_le"] == "2026-10-15T08:55:25+00:00"
    # L'envoi se termine ; SEULE la nouvelle personne reçoit le carrousel (Awa, déjà servie, n'est pas renvoyée)
    for _ in range(40):
        camp = client.portal.call(db.carrousel_campagnes.find_one, {"id": "camp1"})
        if camp["statut"] == "TERMINEE":
            break
        client.portal.call(_aio.sleep, 0.1)
    assert camp["statut"] == "TERMINEE" and camp["compte"]["total"] == 2 and camp["compte"]["envoyes"] == 2
    assert envois == ["22677001214"]
    # La personne n'est plus orpheline
    assert client.get("/api/admin/whatsapp/carrousel/accords-orphelins", headers=h("admin")).json()["orphelins"] == []


def test_lot205_accord_note_sur_un_contact_de_societe(env):
    """Administration : en mode « Société », l'accord noté à la main doit atteindre le contact affiché (avant : 0 fiche
    modifiée, faux « Consentement noté », bouton « Envoyer » toujours grisé)."""
    client, db, envois, _, moteur = env
    # c3 (« Awa (doublon) ») appartient à la Pharmacie A (cli_a) et n'a pas encore accepté
    sans = client.put("/api/admin/whatsapp/carrousel/consentements", headers=h("admin"), json={"ids": ["c3"], "accepte": True})
    assert sans.status_code == 200 and sans.json()["modifies"] == 0            # sans société : introuvable (comportement signalé au client)
    avec = client.put("/api/admin/whatsapp/carrousel/consentements", headers=h("admin"),
                      json={"ids": ["c3"], "accepte": True, "societe_id": "cli_a"})
    assert avec.status_code == 200 and avec.json()["modifies"] == 1
    c3 = client.portal.call(db.directory_contacts.find_one, {"id": "c3"})
    assert c3["accepte_whatsapp"] is True and c3["accepte_whatsapp_le"]
    # Une autre société ne peut pas modifier ce contact
    autre = client.put("/api/admin/whatsapp/carrousel/consentements", headers=h("admin"),
                       json={"ids": ["c4"], "accepte": True, "societe_id": "cli_a"})
    assert autre.json()["modifies"] == 0


# ---- Lot 206 : clics sur un bouton jamais transformés en accord ; demande d'accord journalisée ----
from routes import accord_whatsapp as aw  # noqa: E402


def test_lot206_sens_d_un_bouton():
    assert aw.sens_bouton("Confirmer") is True and aw.sens_bouton("Oui, j'accepte") is True and aw.sens_bouton("OK") is True
    assert aw.sens_bouton("NON, pas intéressé(e)") is False and aw.sens_bouton("Stop") is False
    assert aw.sens_bouton("Plus d'infos") is None and aw.sens_bouton("") is None


def _clic(db, tel, texte="Confirmer", le="2026-10-15T08:55:25+00:00", profil="alixyame"):
    return db.whatsapp_messages.insert_one({"direction": "inbound", "message_type": "button", "phone_digits": tel, "body": texte,
                                            "created_at": le, "from_profile_name": profil})


def test_lot206_clics_a_valider_avec_et_sans_fiche():
    db = AsyncMongoMockClient()["t"]
    _run(_clic(db, "22677001214"))                                                    # sans fiche
    _run(_clic(db, "22670000001", profil="Awa"))                                      # fiche sans accord
    _run(db.directory_contacts.insert_one({"id": "c1", "client_id": "cl1", "name": "Awa Traoré", "whatsapp": "+226 70 00 00 01"}))
    _run(_clic(db, "22670000002"))                                                    # fiche déjà en accord → exclue
    _run(db.directory_contacts.insert_one({"id": "c2", "name": "Déjà", "whatsapp": "70000002", "accepte_whatsapp": True}))
    _run(_clic(db, "22670000003", texte="NON, pas intéressé(e)"))                     # refus → exclu
    _run(_clic(db, "22670000004"))                                                    # décision enregistrée après le clic → exclue
    _run(_journal(db, "22670000004", le="2026-10-15T09:30:00+00:00"))
    lignes = {l["telephone"]: l for l in _run(ao.clics_a_valider(db))}
    assert set(lignes) == {"22677001214", "22670000001"}
    assert lignes["22677001214"]["sans_fiche"] is True and lignes["22677001214"]["nom"] == "alixyame"
    assert lignes["22670000001"]["sans_fiche"] is False and lignes["22670000001"]["nom"] == "Awa Traoré"


def test_lot206_validation_note_l_accord_avec_la_date_du_clic():
    db = AsyncMongoMockClient()["t"]
    _run(_clic(db, "22670000001", profil="Awa", le="2026-10-15T08:10:00+00:00"))
    _run(db.directory_contacts.insert_one({"id": "c1", "client_id": "cl1", "name": "Awa Traoré", "whatsapp": "+226 70 00 00 01"}))
    res = _run(ao.valider_clics(db, ["22670000001", "22699999999"], "Admin"))
    assert res["ignores"] == 1 and res["valides"][0]["fiche"]["id"] == "c1"
    c1 = _run(db.directory_contacts.find_one({"id": "c1"}))
    assert c1["accepte_whatsapp"] is True and c1["accepte_whatsapp_le"] == "2026-10-15T08:10:00+00:00"
    assert "validé par Admin" in c1["accepte_whatsapp_par"]
    assert _run(ao.clics_a_valider(db)) == []                                         # n'apparaît plus


def test_lot206_routes_valider_et_envoyer(env):
    client, db, envois, _, moteur = env
    client.portal.call(db.carrousel_campagnes.insert_one, {
        "id": "camp1", "perimetre": "admin", "tenant_id": None, "cree_le": "2026-10-15T07:00:00+00:00", "cree_par": "admin",
        "cree_par_nom": "Admin", "expediteur": "SAWALI", "message": "Nouveautés", "modele": "sawali_carrousel_2", "langue": "fr",
        "cartes": [{"titre": "A", "texte": "x", "lien": "https://x.bf", "code_lien": "a1", "image_url": "https://x.bf/a.png", "bouton": "presentation"},
                   {"titre": "B", "texte": "x", "lien": "https://x.bf", "code_lien": "a2", "image_url": "https://x.bf/b.png", "bouton": "presentation"}],
        "creds_tenant": None, "statut": "TERMINEE", "reprenable": True,
        "destinataires": [{"id": "c1", "nom": "Awa", "telephone": "22676111111", "statut": "ENVOYE"}], "compte": {"total": 1, "envoyes": 1, "echecs": 0}})
    # Une personne avec fiche (Boris, c2 : 76 22 22 22) a cliqué « Confirmer » sans que l'accord soit noté ; Alix n'a pas de fiche
    client.portal.call(db.directory_contacts.update_one, {"id": "c2"}, {"$unset": {"accepte_whatsapp": ""}})
    client.portal.call(lambda: _clic(db, "22676222222", profil="Boris"))
    client.portal.call(lambda: _clic(db, "22677001214"))
    d = client.get("/api/admin/whatsapp/carrousel/accords-orphelins", headers=h("admin")).json()
    assert {c["telephone"] for c in d["clics"]} == {"22676222222", "22677001214"}
    r = client.post("/api/admin/whatsapp/carrousel/clics-a-valider/valider", headers=h("admin"),
                    json={"telephones": ["22676222222", "22677001214"], "campagne_id": "camp1"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert len(res["valides"]) == 2 and res["sans_fiche"] == 1 and res["envoi"]["destinataires"] == 1
    for _ in range(40):
        camp = client.portal.call(db.carrousel_campagnes.find_one, {"id": "camp1"})
        if camp["statut"] == "TERMINEE":
            break
        client.portal.call(_aio.sleep, 0.1)
    assert envois == ["22676222222"]                                                  # seul Boris (fiche) reçoit le carrousel
    # Alix, sans fiche, est maintenant proposé dans « accords sans fiche » (choisir son client)
    d2 = client.get("/api/admin/whatsapp/carrousel/accords-orphelins", headers=h("admin")).json()
    assert [o["telephone"] for o in d2["orphelins"]] == ["22677001214"] and d2["clics"] == []


def test_lot206_demande_recente_reconnait_le_clic_d_une_ancienne_demande():
    from datetime import datetime, timedelta, timezone
    db = AsyncMongoMockClient()["t"]
    maintenant = datetime.now(timezone.utc)
    _run(db.directory_contacts.insert_many([
        {"id": "c1", "whatsapp": "+226 70 16 39 45", "accord_demande_le": (maintenant - timedelta(hours=3)).isoformat()},
        {"id": "c2", "whatsapp": "+226 70 00 00 02", "accord_demande_le": (maintenant - timedelta(days=20)).isoformat()},
        {"id": "c3", "whatsapp": "+226 70 00 00 03"}]))
    assert _run(aw.demande_recente(db, "22670163945")) is True       # demande envoyée ce matin
    assert _run(aw.demande_recente(db, "22670000002")) is False      # demande vieille de 20 jours
    assert _run(aw.demande_recente(db, "22670000003")) is False      # aucune demande
