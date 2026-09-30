"""Lot 44 — « Voir en tant que » (super-admin) et comptes de test en un clic.

But : permettre à l'Admin de la plateforme de tester le parcours complet d'un
utilisateur (notamment un utilisateur suivi) sans avoir accès à sa boîte mail pour
le code OTP.

1. « Voir en tant que »
   L'Admin (rôle `admin` uniquement) ouvre une session courte (30 min) au nom d'un
   compte client ou d'un utilisateur suivi. Le jeton émis est celui de la cible, avec
   des informations en plus :
     imp         identifiant de l'Admin qui a ouvert la session
     imp_nom     son nom (affiché dans le bandeau rouge)
     ro          lecture seule (VRAI par défaut)
     imp_session identifiant de la session (collection `impersonation_journal`)
   Un contrôle placé devant TOUTES les routes (intergiciel HTTP, voir `controle`)
   applique les règles suivantes à toute requête qui porte un tel jeton :
     - session terminée → 401 (le navigateur revient au compte de l'Admin) ;
     - lecture seule → toute écriture (POST/PUT/PATCH/DELETE) est refusée (403),
       sauf la liste blanche POST_LECTURE (recherches / aperçus sans écriture) et
       les routes de la session elle-même (arrêt, bascule du mode) ;
     - toujours interdits, même hors lecture seule : mot de passe, e-mail, téléphone
       ou identité de la personne, double authentification, suppression du compte,
       ouverture d'un nouveau « voir en tant que » (INTERDITS_PERMANENTS) ;
     - les journaux techniques du navigateur (pages visitées, traces d'API, visites)
       sont ignorés : ils ne sont pas enregistrés au nom de la personne ;
     - chaque écriture autorisée (et chaque refus) est notée dans le journal.
   Le mode « lecture seule » qui fait foi est celui enregistré sur la session (et non
   celui du jeton) : un ancien jeton « écriture » ne permet plus d'écrire une fois la
   case recochée.

     POST /api/admin/voir-en-tant-que/{user_id}  ouverture (Admin) → jeton de la cible
     GET  /api/admin/voir-en-tant-que/journal    sessions et actions (Admin)
     GET  /api/voir-en-tant-que/etat             {actif, admin_nom, cible_nom, ro, expire_le}
     POST /api/voir-en-tant-que/mode             {ro} → nouveau jeton (même session, même fin)
     POST /api/voir-en-tant-que/fin              clôture de la session

2. Comptes de test en un clic (Admin)
   Un compte client « TEST SAWALI » (code client TEST) et, sous lui, un utilisateur
   suivi par rôle de suivi, aux adresses test.<rôle>@<premier domaine interne> : le
   code OTP de ces adresses s'affiche à l'écran (règle existante des domaines
   internes). Le mot de passe est saisi par l'Admin, haché, jamais renvoyé.
   Tous ces documents portent `est_test: true`.

     POST   /api/admin/comptes-test   {mot_de_passe} : création ou remise à neuf
     GET    /api/admin/comptes-test   comptes de test existants
     DELETE /api/admin/comptes-test   suppression des comptes de test et de leurs données

Collections : impersonation_journal (sessions et actions), users et tracked_users
(champ `est_test`), activity_events (via le journal d'activité existant).
"""
from __future__ import annotations

import asyncio
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware

# ---------------------------------------------------------------------------
# Réglages
# ---------------------------------------------------------------------------
DUREE_MINUTES = 30                                  # durée de vie du jeton « en tant que »
ROLES_PLATEFORME = {"admin", "superviseur"}         # cibles refusées
METHODES_ECRITURE = {"POST", "PUT", "PATCH", "DELETE"}
MESSAGE_LECTURE_SEULE = ("Mode lecture seule : décochez-le dans le bandeau pour tester une action.")

# Routes de la session elle-même : toujours permises (même en lecture seule).
CHEMINS_SESSION = {"/api/voir-en-tant-que/fin", "/api/voir-en-tant-que/mode"}

# POST purement lecture, indispensables à l'affichage de pages du portail : ils
# calculent une liste sans rien enregistrer. Tout autre POST est bloqué en lecture seule.
POST_LECTURE = {
    "/api/me/contact-groups/resolve",            # groupes + contacts → liste des destinataires
    "/api/me/wa-surveys/recipients/preview",     # aperçu des destinataires d'un sondage
}

# Journaux techniques envoyés automatiquement par le navigateur : ignorés (réponse
# « ok » sans rien enregistrer), pour ne rien écrire au nom de la personne.
TELEMETRIE = {"/api/me/access-log", "/api/me/api-trace", "/api/track"}

# Toujours interdits pendant une session, lecture seule ou non (motif → raison).
INTERDITS_PERMANENTS = [
    (re.compile(r"^/api/auth/"), "connexion, code OTP ou mot de passe"),
    (re.compile(r"password|passwd|mot-de-passe|motdepasse", re.I), "mot de passe"),
    (re.compile(r"2fa|totp|mfa|two-factor|double-auth", re.I), "double authentification"),
    (re.compile(r"^/api/me/profile-update-request"), "identité, e-mail ou téléphone de la personne"),
    (re.compile(r"^/api/me/(profile|profil|account|compte|email|e-mail|phone|telephone)(/|$)"),
     "profil, e-mail ou téléphone de la personne"),
    (re.compile(r"^/api/me/admin-clients/"), "e-mail, téléphone ou mot de passe d'un compte"),
    (re.compile(r"^/api/me/kyc"), "identité légale du compte"),
    (re.compile(r"delete-account|supprimer-compte|suppression-compte", re.I), "suppression du compte"),
    (re.compile(r"^/api/me/?$"), "suppression ou modification du compte"),
    (re.compile(r"^/api/admin/voir-en-tant-que"), "nouveau « voir en tant que » (pas d'imbrication)"),
    (re.compile(r"^/api/admin/comptes-test"), "comptes de test"),
]

# Comptes de test : fonctions activées sur le client TEST (clés de `users.features`).
FONCTIONS_TEST = {
    "forms_surveys": True,            # Formulaires et Sondages
    "ocr_pieces": True,               # OCR sur Pièces
    "ordonnances_stock": True,        # Ordonnances et stock
    "maintenance_equipements": True,  # Maintenance des équipements
    "whatsapp": True,                 # menus WhatsApp (envois réels : voir limites)
    "internal_chat": True,            # discussion interne entre utilisateurs suivis
}
CODE_CLIENT_TEST = "TEST"
NOM_CLIENT_TEST = "TEST SAWALI"
# Rôle de suivi hors liste standard : comptes démo créés par WhatsApp (wa_otp_login_9o).
ROLE_DEMO = "Admin (Limité)"


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


def _slug_role(role: str) -> str:
    """« Secrétaire médicale » → « secretaire-medicale » ; « Admin (Limité) » → « admin-limite »."""
    s = unicodedata.normalize("NFKD", role).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _chemin(request: Request) -> str:
    """Chemin de la requête sans barre finale (sauf la racine)."""
    p = request.url.path or "/"
    return p.rstrip("/") if len(p) > 1 else p


def _jeton_bearer(request: Request) -> Optional[str]:
    h = request.headers.get("authorization") or ""
    if h.lower().startswith("bearer "):
        return h.split(" ", 1)[1].strip() or None
    return None


def raison_interdiction(chemin: str) -> Optional[str]:
    """Raison de l'interdiction permanente d'une écriture sur ce chemin (sinon None)."""
    for motif, raison in INTERDITS_PERMANENTS:
        if motif.search(chemin):
            return raison
    return None


# ---------------------------------------------------------------------------
# Corps des requêtes (au niveau du module : FastAPI doit pouvoir les résoudre)
# ---------------------------------------------------------------------------
class OuvertureIn(BaseModel):
    retour: Optional[str] = Field(None, max_length=300)     # page admin d'origine


class ModeIn(BaseModel):
    ro: bool


class ComptesTestIn(BaseModel):
    mot_de_passe: str = Field(..., min_length=10, max_length=200)


def attach_voir_en_tant_que_routes(
    *,
    app,
    api,
    db,
    get_current_user: Callable[..., Awaitable[dict]],
    get_current_admin: Callable[..., Awaitable[dict]],
    encode_jwt: Callable[[Dict[str, Any]], str],
    decode_jwt: Callable[[str], Dict[str, Any]],
    hash_password: Callable[[str], str],
    client_ip: Callable[[Request], str],
    roles_suivi: List[str],
    to_user_public: Optional[Callable[[dict], dict]] = None,
    base_publique: Optional[Callable[[Request], str]] = None,
    journal_activite: Optional[Callable[..., Awaitable[None]]] = None,
    super_admin_email: str = "admin@sawalismartsystems.com",
) -> Dict[str, Any]:
    """Branche les routes du lot 44 et le contrôle des sessions « en tant que »."""

    async def _journaliser_activite(**kw) -> None:
        """Entrée du journal d'activité existant (sans jamais faire échouer la requête)."""
        if journal_activite is None:
            return
        try:
            await journal_activite(**kw)
        except Exception:  # noqa: BLE001
            pass

    async def _noter_action(session: dict, request: Request, *, type_action: str, statut: int,
                            detail: str = "") -> None:
        """Ajoute une action au journal de la session (méthode, chemin, heure, résultat)."""
        try:
            await db.impersonation_journal.insert_one({
                "id": str(uuid.uuid4()), "type": "action", "session_id": session.get("id"),
                "admin_id": session.get("admin_id"), "cible_id": session.get("cible_id"),
                "action": type_action, "methode": request.method, "chemin": _chemin(request),
                "statut": statut, "detail": detail[:300], "horodatage": _iso(_maintenant()),
            })
        except Exception:  # noqa: BLE001
            pass

    def _claims(request: Request) -> Optional[Dict[str, Any]]:
        """Contenu du jeton porté par la requête (None si absent ou invalide)."""
        jeton = _jeton_bearer(request)
        if not jeton:
            return None
        try:
            return decode_jwt(jeton)
        except Exception:  # noqa: BLE001
            return None

    async def _session_de(claims: Dict[str, Any]) -> Optional[dict]:
        return await db.impersonation_journal.find_one(
            {"type": "session", "id": claims.get("imp_session")}, {"_id": 0})

    def _jeton_cible(cible: dict, admin_id: str, admin_nom: str, ro: bool, session_id: str,
                     iat: int, exp: int) -> str:
        return encode_jwt({"sub": cible["id"], "role": cible.get("role"), "iat": iat, "exp": exp,
                           "imp": admin_id, "imp_nom": admin_nom, "ro": bool(ro),
                           "imp_session": session_id})

    # -----------------------------------------------------------------------
    # Contrôle global : placé au plus près des routes (après CORS, liste noire IP…)
    # -----------------------------------------------------------------------
    async def controle(request: Request, call_next):
        claims = _claims(request)
        # Requête normale (ou jeton expiré / invalide : l'expiration suit son cours habituel)
        if not claims or not claims.get("imp"):
            return await call_next(request)
        chemin = _chemin(request)
        methode = request.method.upper()
        session = await _session_de(claims)
        # Session close (bouton « Revenir à mon compte ») : le jeton ne vaut plus rien,
        # sauf pour rappeler la clôture (idempotente).
        if not session or session.get("fin"):
            if chemin == "/api/voir-en-tant-que/fin":
                return await call_next(request)
            return JSONResponse(status_code=401, content={
                "detail": "Session « Voir en tant que » terminée : retour à votre compte.",
                "code": "voir_en_tant_que_termine"})
        if methode not in METHODES_ECRITURE:
            return await call_next(request)
        # Routes de la session (arrêt, bascule du mode) : journalisées par leur route.
        if chemin in CHEMINS_SESSION:
            return await call_next(request)
        # Journaux techniques du navigateur : ignorés.
        if chemin in TELEMETRIE:
            return JSONResponse(status_code=200, content={"ok": True, "ignore": "voir_en_tant_que"})
        # Interdits permanents (lecture seule ou non).
        raison = raison_interdiction(chemin)
        if raison:
            await _noter_action(session, request, type_action="refus", statut=403,
                                detail=f"Interdit permanent : {raison}")
            return JSONResponse(status_code=403, content={
                "detail": f"Action interdite pendant « Voir en tant que » ({raison}).",
                "code": "voir_en_tant_que_interdit"})
        # Lecture seule : c'est le réglage de la SESSION qui fait foi.
        if session.get("ro", True) and not (methode == "POST" and chemin in POST_LECTURE):
            await _noter_action(session, request, type_action="refus", statut=403,
                                detail="Lecture seule")
            return JSONResponse(status_code=403, content={
                "detail": MESSAGE_LECTURE_SEULE, "code": "voir_en_tant_que_lecture_seule"})
        # Écriture autorisée : exécutée puis notée (avec son résultat).
        reponse = await call_next(request)
        await _noter_action(session, request, type_action="ecriture", statut=reponse.status_code)
        return reponse

    # Ajouté en DERNIER dans la liste des intergiciels = le plus proche des routes :
    # ses réponses 401/403 passent donc aussi par CORS et par les autres contrôles.
    app.user_middleware.append(Middleware(BaseHTTPMiddleware, dispatch=controle))

    # -----------------------------------------------------------------------
    # Ouverture d'une session (Admin)
    # -----------------------------------------------------------------------
    async def _resoudre_cible(user_id: str) -> dict:
        """`user_id` = compte (users.id) ou utilisateur suivi (tracked_users.id)."""
        cible = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
        if cible:
            return cible
        suivi = await db.tracked_users.find_one({"id": user_id}, {"_id": 0})
        if not suivi:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable")
        projection = {"_id": 0, "password_hash": 0}
        cible = None
        # 1) Lien enregistré sur la fiche suivie (cas normal)
        if suivi.get("user_account_id"):
            cible = await db.users.find_one({"id": suivi["user_account_id"]}, projection)
        # 2) Lien absent ou rompu (compte recréé, migration, ancienne fiche) : on cherche
        #    le compte de connexion rattaché à cette fiche, puis celui qui porte son e-mail
        #    (c'est par l'e-mail que l'utilisateur se connecte).
        if not cible:
            cible = await db.users.find_one({"tracked_user_id": suivi["id"]}, projection)
        email = (suivi.get("email") or "").strip()
        if not cible and email:
            cible = await db.users.find_one(
                {"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}}, projection)
            # Par sécurité : jamais un compte de la plateforme, ni celui d'un autre suivi
            if cible and (cible.get("role") in ROLES_PLATEFORME or
                          (cible.get("tracked_user_id") and cible.get("tracked_user_id") != suivi["id"])):
                cible = None
        if not cible:
            raise HTTPException(status_code=400, detail=(
                "Cet utilisateur suivi n'a pas de compte de connexion (lien absent ou rompu) : "
                "cliquez sur « Définir un mot de passe » pour le (re)créer, puis réessayez."))
        # Lien réparé sur la fiche suivie, pour les fois suivantes
        if suivi.get("user_account_id") != cible["id"]:
            await db.tracked_users.update_one(
                {"id": suivi["id"]}, {"$set": {"user_account_id": cible["id"], "has_password": True}})
        return cible

    def _accueil(cible: dict) -> str:
        """Page d'accueil du portail de la cible (même règle que la page de connexion)."""
        tr = cible.get("tracked_role") or ""
        if tr == "Traducteur":
            return "/portal/i18n"
        if tr == "Médecin":
            return "/portal/planning"
        return "/portal"

    def _public(cible: dict) -> dict:
        if to_user_public is not None:
            try:
                return to_user_public(cible)
            except Exception:  # noqa: BLE001
                pass
        cles = ("id", "email", "full_name", "role", "company", "tracked_role", "tracked_user_id",
                "parent_client_id", "account_status", "logo_url", "business_type")
        return {k: cible.get(k) for k in cles}

    @api.post("/admin/voir-en-tant-que/{user_id}", tags=["Admin — Voir en tant que"])
    async def ouvrir(user_id: str, request: Request, payload: Optional[OuvertureIn] = Body(None),
                     admin: dict = Depends(get_current_admin)):
        # Pas d'imbrication : un jeton « en tant que » ne peut pas en ouvrir un autre.
        claims = _claims(request) or {}
        if claims.get("imp"):
            raise HTTPException(status_code=403, detail="Impossible depuis une session « Voir en tant que ».")
        cible = await _resoudre_cible(user_id)
        if cible["id"] == admin["id"]:
            raise HTTPException(status_code=400, detail="Vous êtes déjà connecté à ce compte.")
        if cible.get("role") in ROLES_PLATEFORME or \
                (cible.get("email") or "").strip().lower() == super_admin_email.lower():
            raise HTTPException(status_code=403,
                                detail="Impossible de voir en tant qu'un compte Admin ou Superviseur.")
        if cible.get("account_status") != "active":
            raise HTTPException(status_code=403, detail="Compte désactivé ou suspendu : ouverture impossible.")

        maintenant = _maintenant()
        fin_prevue = maintenant + timedelta(minutes=DUREE_MINUTES)
        session_id = str(uuid.uuid4())
        admin_nom = admin.get("full_name") or admin.get("email") or "Admin"
        cible_nom = cible.get("full_name") or cible.get("email") or "—"
        cible_role = cible.get("tracked_role") or cible.get("role") or ""
        retour = ((payload.retour if payload else None) or "/admin").strip()
        if not retour.startswith("/admin"):          # retour limité aux pages de l'administration
            retour = "/admin"
        await db.impersonation_journal.insert_one({
            "id": session_id, "type": "session",
            "admin_id": admin["id"], "admin_nom": admin_nom, "admin_email": admin.get("email"),
            "cible_id": cible["id"], "cible_nom": cible_nom, "cible_email": cible.get("email"),
            "cible_role": cible_role,
            "cible_client_id": cible.get("parent_client_id") or cible.get("client_id") or cible["id"],
            "debut": _iso(maintenant), "expire_le": _iso(fin_prevue), "fin": None, "fin_motif": None,
            "ip": client_ip(request), "navigateur": (request.headers.get("user-agent") or "")[:400],
            "ro": True, "retour": retour,
        })
        await _journaliser_activite(action="started", admin=admin, cible_id=cible["id"],
                                    label=f"Voir en tant que : {cible_nom} ({cible_role})")
        jeton = _jeton_cible(cible, admin["id"], admin_nom, True, session_id,
                             int(maintenant.timestamp()), int(fin_prevue.timestamp()))
        return {"access_token": jeton, "token_type": "bearer", "session_id": session_id, "ro": True,
                "expire_le": _iso(fin_prevue), "accueil": _accueil(cible), "retour": retour,
                "admin_nom": admin_nom, "cible": {"id": cible["id"], "nom": cible_nom, "role": cible_role},
                "user": _public(cible)}

    # -----------------------------------------------------------------------
    # Routes de la session (appelées avec le jeton « en tant que »)
    # -----------------------------------------------------------------------
    def _exiger_claims_imp(request: Request) -> Dict[str, Any]:
        claims = _claims(request)
        if not claims or not claims.get("imp"):
            raise HTTPException(status_code=400, detail="Aucune session « Voir en tant que » en cours.")
        return claims

    @api.get("/voir-en-tant-que/etat", tags=["Voir en tant que"])
    async def etat(request: Request):
        claims = _claims(request) or {}
        if not claims.get("imp"):
            return {"actif": False}
        session = await _session_de(claims)
        if not session or session.get("fin"):
            return {"actif": False}
        return {"actif": True, "session_id": session["id"], "admin_nom": session.get("admin_nom"),
                "cible_nom": session.get("cible_nom"), "cible_role": session.get("cible_role"),
                "ro": bool(session.get("ro", True)), "expire_le": session.get("expire_le"),
                "retour": session.get("retour")}

    @api.post("/voir-en-tant-que/mode", tags=["Voir en tant que"])
    async def mode(payload: ModeIn, request: Request, user: dict = Depends(get_current_user)):
        claims = _exiger_claims_imp(request)
        session = await _session_de(claims)
        if not session or session.get("fin"):
            raise HTTPException(status_code=401, detail="Session « Voir en tant que » terminée.")
        await db.impersonation_journal.update_one({"id": session["id"]}, {"$set": {"ro": payload.ro}})
        await _noter_action(session, request, type_action="mode", statut=200,
                            detail="Lecture seule activée" if payload.ro else "Lecture seule désactivée")
        # Nouveau jeton : même session, même fin, seul `ro` change.
        jeton = _jeton_cible(user, claims["imp"], claims.get("imp_nom") or "", payload.ro,
                             session["id"], int(_maintenant().timestamp()), int(claims["exp"]))
        return {"access_token": jeton, "ro": payload.ro, "expire_le": session.get("expire_le")}

    @api.post("/voir-en-tant-que/fin", tags=["Voir en tant que"])
    async def fin(request: Request):
        claims = _exiger_claims_imp(request)
        session = await _session_de(claims)
        if not session:
            return {"ok": True, "retour": "/admin"}
        if session.get("fin"):
            return {"ok": True, "deja_terminee": True, "retour": session.get("retour") or "/admin"}
        await db.impersonation_journal.update_one(
            {"id": session["id"]}, {"$set": {"fin": _iso(_maintenant()), "fin_motif": "retour"}})
        await _journaliser_activite(action="ended", admin={"id": session.get("admin_id"),
                                                           "full_name": session.get("admin_nom")},
                                    cible_id=session.get("cible_id"),
                                    label=f"Fin de « Voir en tant que » : {session.get('cible_nom')}")
        return {"ok": True, "retour": session.get("retour") or "/admin"}

    # -----------------------------------------------------------------------
    # Journal des sessions (Admin)
    # -----------------------------------------------------------------------
    @api.get("/admin/voir-en-tant-que/journal", tags=["Admin — Voir en tant que"])
    async def journal(limit: int = 50, _: dict = Depends(get_current_admin)):
        limit = max(1, min(int(limit or 50), 200))
        sessions = await db.impersonation_journal.find({"type": "session"}, {"_id": 0}) \
            .sort("debut", -1).to_list(limit)
        ids = [s["id"] for s in sessions]
        actions = await db.impersonation_journal.find(
            {"type": "action", "session_id": {"$in": ids}}, {"_id": 0}).sort("horodatage", 1).to_list(5000)
        par_session: Dict[str, List[dict]] = {}
        for a in actions:
            par_session.setdefault(a["session_id"], []).append(a)
        maintenant = _iso(_maintenant())
        for s in sessions:
            if s.get("fin"):
                s["statut"] = "terminée"
            elif (s.get("expire_le") or "") <= maintenant:
                s["statut"] = "expirée"
            else:
                s["statut"] = "en cours"
            s["actions"] = par_session.get(s["id"], [])
        return {"items": sessions}

    # -----------------------------------------------------------------------
    # Comptes de test
    # -----------------------------------------------------------------------
    async def _domaine_interne() -> str:
        """Premier domaine interne (Paramètres), même lecture que la page de connexion."""
        s = await db.settings.find_one({"_id": "global"}, {"internal_domains": 1}) or {}
        domaines = [d.strip().lower().lstrip("@")
                    for d in (s.get("internal_domains") or "sawalismartsystems.com").split(",") if d.strip()]
        return domaines[0] if domaines else "sawalismartsystems.com"

    def _roles_test() -> List[str]:
        roles = list(dict.fromkeys(list(roles_suivi) + [ROLE_DEMO]))
        return roles

    def _lien(request: Request, email: str) -> str:
        base = ""
        if base_publique is not None:
            try:
                base = (base_publique(request) or "").rstrip("/")
            except Exception:  # noqa: BLE001
                base = ""
        return f"{base}/login?email={email}"

    @api.post("/admin/comptes-test", tags=["Admin — Comptes de test"])
    async def creer_comptes_test(payload: ComptesTestIn, request: Request,
                                 admin: dict = Depends(get_current_admin)):
        mdp = payload.mot_de_passe
        if len(mdp.strip()) < 10:
            raise HTTPException(status_code=400, detail="Mot de passe trop court (10 caractères minimum).")
        domaine = await _domaine_interne()
        email_client = f"test.client@{domaine}"
        roles = _roles_test()
        emails = {r: f"test.{_slug_role(r)}@{domaine}" for r in roles}

        # Aucune adresse ni code client ne doit appartenir à un vrai compte : on vérifie tout AVANT d'écrire.
        conflits = await db.users.find(
            {"email": {"$in": [email_client] + list(emails.values())}, "est_test": {"$ne": True}},
            {"_id": 0, "email": 1}).to_list(50)
        if conflits:
            raise HTTPException(status_code=409, detail=(
                "Adresse déjà utilisée par un vrai compte : " + ", ".join(c["email"] for c in conflits)))
        if await db.users.find_one({"client_code": CODE_CLIENT_TEST, "est_test": {"$ne": True}}, {"_id": 0, "id": 1}):
            raise HTTPException(status_code=409, detail="Le code client TEST est déjà utilisé par un vrai compte.")

        # Un seul calcul de hachage (bcrypt ~0,25 s) dans un thread, réutilisé pour tous les comptes.
        empreinte = await asyncio.to_thread(hash_password, mdp)
        maintenant = _iso(_maintenant())

        # 1) Compte client TEST SAWALI (créé ou remis à neuf)
        client = await db.users.find_one({"email": email_client}, {"_id": 0, "id": 1})
        champs_client = {
            "email": email_client, "full_name": NOM_CLIENT_TEST, "company": NOM_CLIENT_TEST,
            "client_code": CODE_CLIENT_TEST, "role": "client", "account_status": "active",
            "password_hash": empreinte, "features": dict(FONCTIONS_TEST), "est_test": True,
            "is_primary_client": False, "parent_client_id": None, "client_id": None,
            "updated_at": maintenant,
        }
        if client:
            client_id = client["id"]
            await db.users.update_one({"id": client_id}, {"$set": champs_client})
        else:
            client_id = str(uuid.uuid4())
            await db.users.insert_one({"id": client_id, "created_at": maintenant, **champs_client})

        comptes = [{"email": email_client, "role": "Compte client", "nom": NOM_CLIENT_TEST,
                    "lien": _lien(request, email_client)}]

        # 2) Un utilisateur suivi par rôle de suivi (fiche suivie + compte de connexion)
        for role in roles:
            email = emails[role]
            nom = f"Test {role}"
            suivi = await db.tracked_users.find_one({"email": email, "est_test": True}, {"_id": 0, "id": 1})
            champs_suivi = {
                "client_id": client_id, "name": nom, "email": email, "role": role, "status": "active",
                "company": NOM_CLIENT_TEST, "est_test": True, "has_password": True, "updated_at": maintenant,
            }
            if role == "Traducteur":
                champs_suivi["translator_languages"] = ["en"]
            if suivi:
                suivi_id = suivi["id"]
                await db.tracked_users.update_one({"id": suivi_id}, {"$set": champs_suivi})
            else:
                suivi_id = str(uuid.uuid4())
                await db.tracked_users.insert_one({"id": suivi_id, "created_at": maintenant, **champs_suivi})
            compte = await db.users.find_one({"email": email}, {"_id": 0, "id": 1})
            champs_compte = {
                "email": email, "full_name": nom, "role": "client", "company": NOM_CLIENT_TEST,
                "account_status": "active", "password_hash": empreinte, "tracked_user_id": suivi_id,
                "tracked_role": role, "parent_client_id": client_id, "client_id": client_id,
                "est_test": True, "updated_at": maintenant,
            }
            if role == "Traducteur":
                champs_compte["translator_languages"] = ["en"]
            if compte:
                compte_id = compte["id"]
                await db.users.update_one({"id": compte_id}, {"$set": champs_compte})
            else:
                compte_id = str(uuid.uuid4())
                await db.users.insert_one({"id": compte_id, "created_at": maintenant, **champs_compte})
            await db.tracked_users.update_one({"id": suivi_id}, {"$set": {"user_account_id": compte_id}})
            comptes.append({"email": email, "role": role, "nom": nom, "lien": _lien(request, email)})

        await _journaliser_activite(action="created", admin=admin, cible_id=client_id,
                                    label=f"Comptes de test créés / remis à neuf ({len(comptes)})")
        return {"ok": True, "client_id": client_id, "domaine": domaine, "comptes": comptes,
                "fonctions_activees": sorted(FONCTIONS_TEST.keys())}

    @api.get("/admin/comptes-test", tags=["Admin — Comptes de test"])
    async def lister_comptes_test(request: Request, _: dict = Depends(get_current_admin)):
        items = await db.users.find({"est_test": True}, {"_id": 0, "id": 1, "email": 1, "full_name": 1,
                                                         "role": 1, "tracked_role": 1}).to_list(200)
        return {"comptes": [{"id": u["id"], "email": u.get("email"), "nom": u.get("full_name"),
                             "role": u.get("tracked_role") or "Compte client",
                             "lien": _lien(request, u.get("email") or "")} for u in items]}

    # Collections jamais purgées par la suppression des comptes de test (traçabilité).
    COLLECTIONS_CONSERVEES = {"impersonation_journal", "activity_events", "settings", "users", "tracked_users"}
    CHAMPS_PROPRIETAIRE = ("client_id", "user_id", "owner_id", "tenant_id", "created_by_id",
                           "parent_client_id", "user_account_id")

    @api.delete("/admin/comptes-test", tags=["Admin — Comptes de test"])
    async def supprimer_comptes_test(admin: dict = Depends(get_current_admin)):
        ids = [u["id"] for u in await db.users.find({"est_test": True}, {"_id": 0, "id": 1}).to_list(500)]
        ids += [t["id"] for t in await db.tracked_users.find({"est_test": True}, {"_id": 0, "id": 1}).to_list(500)]
        donnees: Dict[str, int] = {}
        # Données créées par ces comptes : tout document dont un champ « propriétaire » vaut
        # l'identifiant d'un compte de test (identifiants uniques : aucun vrai compte touché).
        if ids:
            filtre = {"$or": [{c: {"$in": ids}} for c in CHAMPS_PROPRIETAIRE]}
            try:
                noms = await db.list_collection_names()
            except Exception:  # noqa: BLE001
                noms = []
            for nom in noms:
                if nom in COLLECTIONS_CONSERVEES or nom.startswith("system."):
                    continue
                try:
                    r = await db[nom].delete_many(filtre)
                    if r.deleted_count:
                        donnees[nom] = r.deleted_count
                except Exception:  # noqa: BLE001
                    continue
        n_suivis = (await db.tracked_users.delete_many({"est_test": True})).deleted_count
        n_comptes = (await db.users.delete_many({"est_test": True})).deleted_count
        await _journaliser_activite(action="deleted", admin=admin, cible_id=None,
                                    label=f"Comptes de test supprimés ({n_comptes})")
        return {"ok": True, "comptes_supprimes": n_comptes, "suivis_supprimes": n_suivis,
                "donnees_supprimees": donnees}

    return {"controle": controle, "raison_interdiction": raison_interdiction}


__all__ = ["attach_voir_en_tant_que_routes", "raison_interdiction", "POST_LECTURE",
           "INTERDITS_PERMANENTS", "FONCTIONS_TEST", "DUREE_MINUTES"]
