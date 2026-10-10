"""Lot 104 — codes de connexion (OTP) des plateformes par modèle WhatsApp d'AUTHENTIFICATION :
le code part par le modèle (corps + bouton « Copier le code ») dès qu'il est paramétré, sinon en texte libre ;
corps du modèle créé chez Meta conforme à la catégorie AUTHENTICATION."""
from tests.test_transmission_wa_universelle_lot57_5 import _app, _envoyer, _run
from routes.liluvine_emetteurs import corps_modele_otp
from routes.liluvine_send_webhook import composants_otp


def test_code_par_modele_authentification():
    client, db, envois, cle = _app()
    _run(db.settings.update_one({"_id": "global"}, {"$set": {"liluvine_modele_otp": "code_connexion_plateformes"}}))
    r = _envoyer(client, cle, {"id": "o1", "to": "+22658437050", "message": "ZandGo — votre code : 123456",
                               "code_otp": "123456"})
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "otp"
    genre, numero, nom, composants = envois[-1]
    assert genre == "modele" and nom == "code_connexion_plateformes"
    assert composants == composants_otp("123456")
    # Le journal garde le mode, jamais le code
    j = _run(db.liluvine_transmissions.find_one({"id_externe": "o1"}, {"_id": 0}))
    assert j["mode"] == "otp" and "123456" not in str(j)


def test_sans_modele_otp_texte_libre_et_code_invalide():
    client, db, envois, cle = _app()
    r = _envoyer(client, cle, {"id": "o2", "to": "+22658437050", "message": "Code 123456", "code_otp": "123456"})
    assert r.status_code == 200 and r.json()["mode"] == "texte"
    assert envois[-1][0] == "texte"
    r = _envoyer(client, cle, {"id": "o3", "to": "+22658437050", "message": "Code", "code_otp": "12"})
    assert r.status_code == 422


def test_corps_du_modele_meta():
    corps = corps_modele_otp("code_connexion_plateformes")
    assert corps["category"] == "AUTHENTICATION" and corps["language"] == "fr"
    boutons = [c for c in corps["components"] if c["type"] == "BUTTONS"][0]["buttons"]
    assert boutons[0]["otp_type"] == "COPY_CODE"


def test_synthese_par_plateforme_lot104_1():
    """Lot 104.1 — par plateforme : statut réel de remise et dernier motif d'échec donné par Meta."""
    import routes.liluvine_relais as relais
    client, db, envois, cle = _app()
    _envoyer(client, cle, {"id": "s1", "to": "+22658437050", "message": "Code 1"})
    _envoyer(client, cle, {"id": "s2", "to": "+22670000002", "message": "Code 2"})
    mid = _run(db.liluvine_transmissions.find_one({"id_externe": "s1"}))["message_id"]
    _run(relais.mettre_a_jour_statut(db, mid, "failed", "Re-engagement message (hors fenêtre de 24 h)"))
    r = client.get("/api/admin/liluvine-transmissions/synthese").json()["plateformes"]
    ster = next(p for p in r if p["emetteur"] == "ster")
    assert ster["total"] == 2 and ster["echec"] == 1 and ster["sans_statut"] == 1
    assert "24 h" in ster["dernier_echec"]["motif"] and ster["dernier_echec"]["to"] == "+22658437050"
    # Filtre du journal sur une plateforme
    assert len(client.get("/api/admin/liluvine-transmissions", params={"emetteur": "ster"}).json()["transmissions"]) == 2
    assert client.get("/api/admin/liluvine-transmissions", params={"emetteur": "autre"}).json()["transmissions"] == []
