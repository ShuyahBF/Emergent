"""Lot 44 — « Voir en tant que » (super-admin, lecture seule par défaut, journal) et comptes
de test en un clic. MongoDB simulé ; vrais jetons JWT (secret de test).
Lancer : cd backend && python -m pytest tests/test_lot44_voir_en_tant_que.py -q
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import jwt  # noqa: E402
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.voir_en_tant_que as vet  # noqa: E402

SECRET = "secret-de-test"
ROLES_SUIVI = ["Consultation", "Edition", "Moderation", "Administrateur", "Superviseur", "Comptable",
               "Caissier", "Traducteur", "Médecin", "Secrétaire médicale", "Pharmacien"]
USERS = [
    {"id": "admin", "role": "admin", "full_name": "Super Admin", "email": "admin@sawalismartsystems.com",
     "account_status": "active"},
    {"id": "sup", "role": "superviseur", "full_name": "Superviseur", "email": "sup@x.com", "account_status": "active"},
    {"id": "admin2", "role": "admin", "full_name": "Autre admin", "email": "a2@x.com", "account_status": "active"},
    {"id": "phl", "role": "pharmacien", "full_name": "Pharmacie PHL", "email": "phl@x.com", "account_status": "active"},
    {"id": "med", "role": "client", "full_name": "Dr Awa", "email": "awa@x.com", "account_status": "active",
     "tracked_role": "Médecin", "tracked_user_id": "tu-med", "parent_client_id": "phl", "client_id": "phl"},
    {"id": "off", "role": "client", "full_name": "Ancien", "email": "old@x.com", "account_status": "inactive"},
    {"id": "susp", "role": "client", "full_name": "Suspendu", "email": "susp@x.com", "account_status": "suspended"},
]
TRACKED = [{"id": "tu-med", "client_id": "phl", "name": "Dr Awa", "role": "Médecin", "user_account_id": "med"},
           {"id": "tu-sans", "client_id": "phl", "name": "Sans accès", "role": "Consultation"}]


def encode(charge):
    return jwt.encode(charge, SECRET, algorithm="HS256")


def decode(jeton):
    return jwt.decode(jeton, SECRET, algorithms=["HS256"])


def jeton_normal(uid, role="admin"):
    now = int(time.time())
    return encode({"sub": uid, "role": role, "iat": now, "exp": now + 3600})


@pytest.fixture()
def env():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot44"]
    journal = []
    bearer = HTTPBearer(auto_error=False)

    # Même logique que auth.get_current_user : décodage du jeton puis compte actif.
    async def get_user(cred: HTTPAuthorizationCredentials = Depends(bearer)):
        if cred is None:
            raise HTTPException(status_code=401, detail="Token manquant")
        try:
            charge = decode(cred.credentials)
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expiré")
        except Exception:
            raise HTTPException(status_code=401, detail="Token invalide")
        u = await db.users.find_one({"id": charge["sub"]}, {"_id": 0, "password_hash": 0})
        if not u:
            raise HTTPException(status_code=401)
        if u.get("account_status") != "active":
            raise HTTPException(status_code=403, detail="Compte désactivé")
        return u

    async def get_admin(u: dict = Depends(get_user)):
        if u.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Accès réservé à l'administrateur")
        return u

    async def journal_activite(**kw):
        journal.append(kw)

    app = FastAPI()
    api = APIRouter(prefix="/api")
    vet.attach_voir_en_tant_que_routes(
        app=app, api=api, db=db, get_current_user=get_user, get_current_admin=get_admin,
        encode_jwt=encode, decode_jwt=decode, hash_password=lambda p: "haché:" + p[::-1],
        client_ip=lambda r: r.headers.get("x-forwarded-for", "").split(",")[0].strip() or "ip-test",
        roles_suivi=ROLES_SUIVI, base_publique=lambda r: "https://sawali.test",
        journal_activite=journal_activite)

    # Routes « métier » simulées pour vérifier le contrôle global
    ecrits = []

    @api.get("/me/rapports")
    async def lire(u: dict = Depends(get_user)):
        return {"moi": u["id"]}

    @api.post("/me/rapports")
    async def ecrire(u: dict = Depends(get_user)):
        ecrits.append(u["id"])
        return {"ok": True}

    @api.post("/me/contact-groups/resolve")
    async def resoudre(u: dict = Depends(get_user)):
        return {"total": 0}

    @api.post("/me/access-log")
    async def access_log(u: dict = Depends(get_user)):
        ecrits.append("access-log")
        return {"ok": True}

    @api.post("/auth/change-password")
    async def change_mdp(u: dict = Depends(get_user)):
        ecrits.append("mdp")
        return {"ok": True}

    @api.put("/me/profile")
    async def profil(u: dict = Depends(get_user)):
        ecrits.append("profil")
        return {"ok": True}

    @api.delete("/me")
    async def supprimer_moi(u: dict = Depends(get_user)):
        ecrits.append("suppression")
        return {"ok": True}

    @api.post("/me/2fa/disable")
    async def deux_fa(u: dict = Depends(get_user)):
        ecrits.append("2fa")
        return {"ok": True}

    app.include_router(api)
    client = TestClient(app).__enter__()
    client.portal.call(db.users.insert_many, [dict(u) for u in USERS])
    client.portal.call(db.tracked_users.insert_many, [dict(t) for t in TRACKED])
    yield {"c": client, "db": db, "journal": journal, "ecrits": ecrits}
    client.__exit__(None, None, None)


def h(jeton):
    return {"Authorization": f"Bearer {jeton}"}


def ouvrir(c, cible="med", qui="admin", **kw):
    return c.post(f"/api/admin/voir-en-tant-que/{cible}", headers={**h(jeton_normal(qui)), **kw},
                  json={"retour": "/admin/tracked-users"})


def lire_bd(env, coll, filtre):
    return env["c"].portal.call(lambda: env["db"][coll].find(filtre, {"_id": 0}).to_list(500))


# ---------------------------------------------------------------------------
# Ouverture
# ---------------------------------------------------------------------------
def test_seul_admin_ouvre_et_jeton_30_minutes(env):
    c = env["c"]
    assert c.post("/api/admin/voir-en-tant-que/med").status_code == 401
    assert c.post("/api/admin/voir-en-tant-que/med", headers=h(jeton_normal("sup", "superviseur"))).status_code == 403
    assert c.post("/api/admin/voir-en-tant-que/med", headers=h(jeton_normal("phl", "pharmacien"))).status_code == 403
    r = ouvrir(c, **{"X-Forwarded-For": "41.1.2.3, 10.0.0.1", "User-Agent": "Navigateur/1.0"})
    assert r.status_code == 200, r.text
    d = r.json()
    charge = decode(d["access_token"])
    assert charge["sub"] == "med" and charge["imp"] == "admin" and charge["imp_nom"] == "Super Admin"
    assert charge["ro"] is True and charge["imp_session"] == d["session_id"]
    assert charge["exp"] - charge["iat"] == 30 * 60                                   # 30 minutes
    assert d["accueil"] == "/portal/planning" and d["retour"] == "/admin/tracked-users"
    s = lire_bd(env, "impersonation_journal", {"type": "session"})[0]
    assert s["admin_id"] == "admin" and s["cible_id"] == "med" and s["ip"] == "41.1.2.3"
    assert s["navigateur"] == "Navigateur/1.0" and s["ro"] is True and s["fin"] is None and s["debut"]
    assert env["journal"][0]["action"] == "started"
    # Par l'identifiant de l'utilisateur suivi aussi
    assert ouvrir(c, cible="tu-med").json()["cible"]["id"] == "med"
    assert ouvrir(c, cible="tu-sans").status_code == 400                               # pas d'identifiant
    assert ouvrir(c, cible="inconnu").status_code == 404
    # Retour forcé vers l'administration
    r2 = c.post("/api/admin/voir-en-tant-que/med", headers=h(jeton_normal("admin")), json={"retour": "https://x"})
    assert r2.json()["retour"] == "/admin"


def test_refus_cibles_admin_superviseur_desactivees(env):
    c = env["c"]
    for cible in ("sup", "admin2"):
        assert ouvrir(c, cible=cible).status_code == 403
    for cible in ("off", "susp"):
        r = ouvrir(c, cible=cible)
        assert r.status_code == 403 and "désactivé" in r.json()["detail"]
    assert ouvrir(c, cible="admin").status_code == 400                                 # soi-même


def test_pas_d_imbrication(env):
    c = env["c"]
    jeton = ouvrir(c).json()["access_token"]
    # Le contrôle global refuse, même hors lecture seule
    c.post("/api/voir-en-tant-que/mode", headers=h(jeton), json={"ro": False})
    r = c.post("/api/admin/voir-en-tant-que/phl", headers=h(jeton))
    assert r.status_code == 403 and "imbrication" in r.json()["detail"]
    # Jeton « en tant que » d'un admin fabriqué à la main : la route refuse aussi
    now = int(time.time())
    faux = encode({"sub": "admin", "role": "admin", "iat": now, "exp": now + 600, "imp": "admin",
                   "imp_session": "x"})
    assert c.post("/api/admin/voir-en-tant-que/phl", headers=h(faux)).status_code in (401, 403)


# ---------------------------------------------------------------------------
# Lecture seule, interdits permanents, bascule, fin
# ---------------------------------------------------------------------------
def test_lecture_seule_bloque_ecritures_laisse_lectures(env):
    c, ecrits = env["c"], env["ecrits"]
    jeton = ouvrir(c).json()["access_token"]
    assert c.get("/api/me/rapports", headers=h(jeton)).json() == {"moi": "med"}
    r = c.post("/api/me/rapports", headers=h(jeton))
    assert r.status_code == 403 and r.json()["detail"].startswith("Mode lecture seule : décochez-le")
    assert ecrits == []
    # POST purement lecture de la liste blanche : permis
    assert c.post("/api/me/contact-groups/resolve", headers=h(jeton)).status_code == 200
    # Journal technique : ignoré (ni refus, ni enregistrement au nom de la personne)
    r = c.post("/api/me/access-log", headers=h(jeton))
    assert r.status_code == 200 and r.json()["ignore"] == "voir_en_tant_que" and ecrits == []
    etat = c.get("/api/voir-en-tant-que/etat", headers=h(jeton)).json()
    assert etat["actif"] is True and etat["ro"] is True and etat["cible_nom"] == "Dr Awa"
    assert etat["admin_nom"] == "Super Admin" and etat["expire_le"]
    refus = lire_bd(env, "impersonation_journal", {"type": "action", "action": "refus"})
    assert [(a["methode"], a["chemin"]) for a in refus] == [("POST", "/api/me/rapports")]
    # Un jeton normal n'est pas concerné
    assert c.post("/api/me/rapports", headers=h(jeton_normal("phl", "pharmacien"))).status_code == 200


def test_bascule_mode_ecriture_journalisee_et_interdits_permanents(env):
    c, ecrits = env["c"], env["ecrits"]
    d = ouvrir(c).json()
    ancien = d["access_token"]
    r = c.post("/api/voir-en-tant-que/mode", headers=h(ancien), json={"ro": False})
    assert r.status_code == 200
    nouveau = r.json()["access_token"]
    ca, cn = decode(ancien), decode(nouveau)
    assert cn["ro"] is False and cn["exp"] == ca["exp"] and cn["imp_session"] == ca["imp_session"]
    assert c.post("/api/me/rapports", headers=h(nouveau)).status_code == 200 and ecrits == ["med"]
    # Toujours interdits, même hors lecture seule
    assert c.post("/api/auth/change-password", headers=h(nouveau)).status_code == 403
    assert c.put("/api/me/profile", headers=h(nouveau)).status_code == 403
    assert c.delete("/api/me", headers=h(nouveau)).status_code == 403
    assert c.post("/api/me/2fa/disable", headers=h(nouveau)).status_code == 403
    assert ecrits == ["med"]
    actions = lire_bd(env, "impersonation_journal", {"type": "action"})
    ecriture = [a for a in actions if a["action"] == "ecriture"]
    assert len(ecriture) == 1 and ecriture[0]["chemin"] == "/api/me/rapports" and ecriture[0]["statut"] == 200
    assert ecriture[0]["horodatage"] and ecriture[0]["methode"] == "POST"
    assert any(a["action"] == "mode" for a in actions)
    assert len([a for a in actions if a["action"] == "refus"]) == 4
    # Retour en lecture seule : c'est la session qui fait foi (l'ancien jeton « écriture » est bloqué)
    c.post("/api/voir-en-tant-que/mode", headers=h(nouveau), json={"ro": True})
    assert c.post("/api/me/rapports", headers=h(nouveau)).status_code == 403
    # Bascule impossible avec un jeton normal
    assert c.post("/api/voir-en-tant-que/mode", headers=h(jeton_normal("phl", "pharmacien")),
                  json={"ro": False}).status_code == 400


def test_fin_de_session(env):
    c = env["c"]
    jeton = ouvrir(c).json()["access_token"]
    r = c.post("/api/voir-en-tant-que/fin", headers=h(jeton))
    assert r.status_code == 200 and r.json()["retour"] == "/admin/tracked-users"
    s = lire_bd(env, "impersonation_journal", {"type": "session"})[0]
    assert s["fin"] and s["fin_motif"] == "retour"
    assert [j["action"] for j in env["journal"]] == ["started", "ended"]
    # Le jeton ne vaut plus rien
    r = c.get("/api/me/rapports", headers=h(jeton))
    assert r.status_code == 401 and r.json()["code"] == "voir_en_tant_que_termine"
    assert c.get("/api/voir-en-tant-que/etat", headers=h(jeton)).status_code == 401
    # Clôture idempotente
    assert c.post("/api/voir-en-tant-que/fin", headers=h(jeton)).json()["deja_terminee"] is True
    # Journal réservé à l'Admin, statut calculé
    assert c.get("/api/admin/voir-en-tant-que/journal", headers=h(jeton_normal("sup", "superviseur"))).status_code == 403
    items = c.get("/api/admin/voir-en-tant-que/journal", headers=h(jeton_normal("admin"))).json()["items"]
    assert items[0]["statut"] == "terminée" and items[0]["cible_nom"] == "Dr Awa"


def test_jeton_expire(env):
    c, db = env["c"], env["db"]
    d = ouvrir(c).json()
    charge = decode(d["access_token"])
    charge["exp"] = int(time.time()) - 5
    charge["iat"] = charge["exp"] - 1800
    expire = encode(charge)
    r = c.get("/api/me/rapports", headers=h(expire))
    assert r.status_code == 401 and r.json()["detail"] == "Token expiré"                 # expiration normale
    c.portal.call(db.impersonation_journal.update_one, {"id": d["session_id"]},
                  {"$set": {"expire_le": "2000-01-01T00:00:00+00:00"}})
    items = c.get("/api/admin/voir-en-tant-que/journal", headers=h(jeton_normal("admin"))).json()["items"]
    assert items[0]["statut"] == "expirée"


def test_raison_interdiction():
    assert vet.raison_interdiction("/api/auth/change-password")
    assert vet.raison_interdiction("/api/admin/tracked-users/x/set-password")
    assert vet.raison_interdiction("/api/me/kyc")
    assert vet.raison_interdiction("/api/me/profile-update-request")
    assert vet.raison_interdiction("/api/admin/voir-en-tant-que/abc")
    assert vet.raison_interdiction("/api/me/rapports") is None
    assert vet.raison_interdiction("/api/me/contacts/1") is None


# ---------------------------------------------------------------------------
# Comptes de test
# ---------------------------------------------------------------------------
def test_comptes_test_crees_remis_a_neuf_supprimes(env):
    c, db = env["c"], env["db"]
    adm = h(jeton_normal("admin"))
    assert c.post("/api/admin/comptes-test", headers=h(jeton_normal("sup", "superviseur")),
                  json={"mot_de_passe": "motdepasse123"}).status_code == 403
    assert c.post("/api/admin/comptes-test", headers=adm, json={"mot_de_passe": "court"}).status_code == 422
    # Domaine interne des Paramètres : le premier est utilisé
    c.portal.call(db.settings.insert_one, {"_id": "global", "internal_domains": "sawali.local, sawalismartsystems.com"})
    r = c.post("/api/admin/comptes-test", headers=adm, json={"mot_de_passe": "MotDePasse-2026"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert "MotDePasse-2026" not in r.text                                              # jamais renvoyé
    emails = [x["email"] for x in d["comptes"]]
    assert all(e.endswith("@sawali.local") and e.startswith("test.") for e in emails)
    assert "test.client@sawali.local" in emails and "test.medecin@sawali.local" in emails
    assert "test.secretaire-medicale@sawali.local" in emails and "test.admin-limite@sawali.local" in emails
    assert len(d["comptes"]) == 1 + len(ROLES_SUIVI) + 1
    assert d["comptes"][1]["lien"].startswith("https://sawali.test/login?email=test.")
    assert set(d["fonctions_activees"]) >= {"forms_surveys", "ocr_pieces", "ordonnances_stock", "maintenance_equipements"}
    client = lire_bd(env, "users", {"client_code": "TEST"})[0]
    assert client["company"] == "TEST SAWALI" and client["est_test"] is True and client["features"]["ocr_pieces"]
    assert client["password_hash"] == "haché:" + "MotDePasse-2026"[::-1]              # haché, pas en clair
    comptes = lire_bd(env, "users", {"est_test": True})
    suivis = lire_bd(env, "tracked_users", {"est_test": True})
    assert len(comptes) == 13 and len(suivis) == 12
    med = next(u for u in comptes if u["email"] == "test.medecin@sawali.local")
    assert med["tracked_role"] == "Médecin" and med["parent_client_id"] == client["id"]
    tu = next(t for t in suivis if t["role"] == "Médecin")
    assert tu["user_account_id"] == med["id"] and tu["client_id"] == client["id"]
    # Des données créées par un compte de test
    c.portal.call(db.maintenance_fiches.insert_one, {"id": "f1", "client_id": client["id"]})
    c.portal.call(db.maintenance_fiches.insert_one, {"id": "f2", "client_id": "phl"})
    # Remise à neuf : mêmes comptes (pas de doublon), nouveau mot de passe, compte réactivé
    c.portal.call(db.users.update_one, {"id": med["id"]}, {"$set": {"account_status": "inactive"}})
    r2 = c.post("/api/admin/comptes-test", headers=adm, json={"mot_de_passe": "AutreMotDePasse"})
    assert r2.status_code == 200
    comptes2 = lire_bd(env, "users", {"est_test": True})
    assert len(comptes2) == 13 and len(lire_bd(env, "tracked_users", {"est_test": True})) == 12
    med2 = next(u for u in comptes2 if u["id"] == med["id"])
    assert med2["account_status"] == "active" and med2["password_hash"] == "haché:" + "AutreMotDePasse"[::-1]
    # On peut « voir en tant que » un compte de test
    assert ouvrir(c, cible=med["id"]).status_code == 200
    # Liste des comptes de test
    assert len(c.get("/api/admin/comptes-test", headers=adm).json()["comptes"]) == 13
    # Suppression : uniquement les documents de test
    r3 = c.delete("/api/admin/comptes-test", headers=adm)
    assert r3.status_code == 200 and r3.json()["comptes_supprimes"] == 13
    assert r3.json()["donnees_supprimees"].get("maintenance_fiches") == 1
    assert lire_bd(env, "users", {"est_test": True}) == []
    assert len(lire_bd(env, "users", {})) == len(USERS)
    assert len(lire_bd(env, "tracked_users", {})) == len(TRACKED)
    assert [f["id"] for f in lire_bd(env, "maintenance_fiches", {})] == ["f2"]
    assert lire_bd(env, "impersonation_journal", {"type": "session"})                 # journal conservé


def test_comptes_test_conflit_vrai_compte(env):
    c, db = env["c"], env["db"]
    c.portal.call(db.users.insert_one, {"id": "vrai", "email": "test.client@sawalismartsystems.com",
                                        "role": "client", "account_status": "active"})
    r = c.post("/api/admin/comptes-test", headers=h(jeton_normal("admin")), json={"mot_de_passe": "MotDePasse-2026"})
    assert r.status_code == 409
    assert lire_bd(env, "users", {"est_test": True}) == []
