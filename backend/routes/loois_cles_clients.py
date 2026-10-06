# loois_cles_clients.py — Lot 68.1 : CLÉS CLIENTS LOOIS (une clé différente par client, au lieu de la seule clé commune).
#
# Demande du propriétaire (06/10/2026) : « oui prépare ces clés différentes par client ».
#
# En résumé (pour un développeur WinDev) :
#   - AVANT : tous les postes Loois de tous les clients envoyaient la MÊME clé (variable LOOIS_SUPPORT_CLE sur Render).
#     Une clé divulguée chez un client ouvrait l'accès aux données de tous les autres ;
#   - MAINTENANT : chaque client (code du site, ex. e-Kol « LYCEE-PRIVE-X », Aizenta / Biolog « SCF ») reçoit SA clé,
#     créée sur SAWALI → Plateformes → Loois → Synchro → onglet « Clés clients ». Format : « LK- » + 32 caractères
#     aléatoires (secrets.token_urlsafe). La clé n'est affichée qu'UNE SEULE FOIS, à la création (ou à la
#     régénération) : SAWALI n'en garde que l'EMPREINTE (SHA-256), jamais la clé en clair ;
#   - POIVRE (facultatif, recommandé) : variable d'environnement LOOIS_CLES_PEPPER (valeur aléatoire longue, saisie
#     par le propriétaire sur Render). Si elle existe, l'empreinte est un HMAC-SHA256(clé, poivre) : même une copie
#     volée de la base ne permet pas de tester des clés. ATTENTION : changer ou retirer le poivre invalide les clés
#     créées avec lui (il faudrait les régénérer). Les clés créées AVANT la pose du poivre restent reconnues ;
#   - VÉRIFICATION (identifier_cle) utilisée PARTOUT où une clé Loois est contrôlée :
#       · clé client valide et active → le client est IDENTIFIÉ (code, libellé, applications autorisées) ;
#       · sinon, clé commune LOOIS_SUPPORT_CLE (ancienne méthode, conservée pour que les postes existants continuent
#         de fonctionner) → acceptée pour le chat du support et le signal de présence ;
#       · pour la SYNCHRO DES TABLES (/api/loois/synchro/*), la clé commune est REFUSÉE par défaut ; elle n'est
#         acceptée que si le réglage « Accepter encore la clé commune pour la synchro (transition) » est coché ;
#   - RÉVOCATION : une clé révoquée (ou régénérée) est refusée immédiatement (aucun cache).
#
# Collections MongoDB :
#   loois_cles_clients : une fiche par client {id, code, libelle, applications, tenant_id, client_nom, cle_hash,
#                        cle_poivree, prefixe, actif, cree_le, cree_par, derniere_utilisation, derniere_machine,
#                        revoquee_le, historique[]}
#   loois_reglages     : {id: "cles_clients", accepter_cle_commune_synchro: bool}
#
# Routes d'administration (rôle admin uniquement) :
#   GET  /api/admin/loois-cles-clients                       → liste + réglages + codes de sites déjà vus
#   POST /api/admin/loois-cles-clients                       → création (renvoie la clé UNE fois)
#   PUT  /api/admin/loois-cles-clients/{id}                  → libellé, applications, compte client
#   POST /api/admin/loois-cles-clients/{id}/regenerer        → nouvelle clé (l'ancienne est révoquée), renvoyée UNE fois
#   POST /api/admin/loois-cles-clients/{id}/revoquer         → clé refusée désormais
#   POST /api/admin/loois-cles-clients/{id}/reactiver        → clé de nouveau acceptée
#   PUT  /api/admin/loois-cles-clients-reglages              → réglage de transition (clé commune pour la synchro)
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Request  # au niveau du module : l'annotation de la route doit être résolue (from __future__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
PREFIXE_CLE = "LK-"                    # toutes les clés clients commencent par « LK- »
LONGUEUR_ALEATOIRE = 32                # caractères aléatoires après « LK- » (token_urlsafe(24) = 32 caractères)
LONGUEUR_PREFIXE_AFFICHE = 6           # « LK-a1B… » : seul ce début est montré dans la liste (jamais la clé entière)
MAX_CLES = 1000                        # plafond de fiches (protection)
MAX_LONGUEUR_CLE = 200                 # une clé reçue plus longue est refusée sans calcul
INTERVALLE_MAJ_UTILISATION = 60        # secondes : « dernière utilisation » mise à jour au plus une fois par minute
ID_REGLAGES = "cles_clients"
APPLICATIONS_CONNUES = ("eKol", "Aizenta", "Biolog")   # mêmes codes que la synchro (loois_synchro.APPLICATIONS)

# En-tête ajouté aux refus LIÉS À LA CLÉ (401 / 403) : Loois affiche alors une seule fois
# « Clé client Loois manquante ou invalide — contactez le support » (les autres 403, ex. table non
# configurée, ne déclenchent pas ce message).
EN_TETE_REFUS = {"X-Cle-Loois-Refus": "1"}

# Mémoire du processus : vrai dès qu'au moins une clé client active a été vue. Sert à `support_loois.actif()`
# (fonction synchrone) : le support reste ouvert même si la clé commune est un jour retirée de Render.
ETAT = {"clients_actifs": False}

_ID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")


def _maintenant() -> datetime:
    """Date et heure actuelles (UTC)."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Logique pure (testée) : génération, empreinte, clé commune
# ---------------------------------------------------------------------------
def generer_cle() -> str:
    """Nouvelle clé client : « LK- » + 32 caractères aléatoires sûrs pour une adresse (A-Z, a-z, 0-9, « - », « _ »)."""
    return PREFIXE_CLE + secrets.token_urlsafe(24)[:LONGUEUR_ALEATOIRE]


def poivre() -> str:
    """Poivre du serveur (variable LOOIS_CLES_PEPPER), vide s'il n'est pas défini. Jamais affiché ni journalisé."""
    return (os.environ.get("LOOIS_CLES_PEPPER") or "").strip()


def hacher_cle(cle: str, valeur_poivre: Optional[str] = None) -> str:
    """Empreinte stockée d'une clé : HMAC-SHA256(clé, poivre) si un poivre est fourni, sinon SHA-256 simple.
    La clé en clair n'est JAMAIS enregistrée."""
    donnees = (cle or "").strip().encode("utf-8")
    if valeur_poivre:
        return hmac.new(valeur_poivre.encode("utf-8"), donnees, hashlib.sha256).hexdigest()
    return hashlib.sha256(donnees).hexdigest()


def empreintes_candidates(cle: str) -> List[str]:
    """Empreintes à chercher pour une clé reçue : avec le poivre actuel (s'il existe), puis sans poivre (clés créées
    avant la pose du poivre)."""
    p = poivre()
    sortie = [hacher_cle(cle, p)] if p else []
    sortie.append(hacher_cle(cle, None))
    return list(dict.fromkeys(sortie))


def prefixe_affiche(cle: str) -> str:
    """Début de la clé montré dans la liste (« LK-a1B ») pour reconnaître la clé saisie sur un poste."""
    return (cle or "")[:LONGUEUR_PREFIXE_AFFICHE]


def cle_commune_valide(cle_recue: Optional[str]) -> bool:
    """Vrai si la clé reçue est la clé COMMUNE LOOIS_SUPPORT_CLE (ancienne méthode) — comparaison à temps constant."""
    attendue = (os.environ.get("LOOIS_SUPPORT_CLE") or "").strip()
    recue = (cle_recue or "").strip()
    return bool(attendue and recue) and hmac.compare_digest(attendue.encode("utf-8"), recue.encode("utf-8"))


def application_autorisee(identite: Optional[Dict[str, Any]], application: str) -> bool:
    """Une clé client limitée à certaines applications (liste non vide) ne sert que pour celles-ci ; la clé commune
    et une clé client sans liste valent pour toutes."""
    if not identite:
        return False
    if identite.get("type") != "client":
        return True
    autorisees = identite.get("applications") or []
    return not autorisees or application in autorisees


def libelle_identite(identite: Optional[Dict[str, Any]]) -> Optional[str]:
    """Texte « vérifié · <client> » : libellé du client (sinon son code) pour une clé client, None sinon."""
    if not identite or identite.get("type") != "client":
        return None
    return identite.get("libelle") or identite.get("code")


def nettoyer_fiche(corps: Any, *, creation: bool) -> Dict[str, Any]:
    """Valide la saisie de la page « Clés clients ». Lève ValueError (message clair) si le code manque ou si une
    application est inconnue. Le code est normalisé comme le fait Loois (« Lycée Privé X » → « LYCEE-PRIVE-X »)."""
    from routes.loois_synchro import code_site, normaliser_application   # import tardif (évite une boucle d'imports)

    if not isinstance(corps, dict):
        raise ValueError("objet JSON attendu")
    propre: Dict[str, Any] = {}
    if creation or "code" in corps:
        code = code_site(corps.get("code"))
        if not code:
            raise ValueError("code client manquant (code du site envoyé par Loois, ex. LYCEE-PRIVE-X ou SCF)")
        propre["code"] = code
    if creation or "libelle" in corps:
        propre["libelle"] = str(corps.get("libelle") or "").strip()[:120] or propre.get("code")
    if creation or "applications" in corps:
        applications = []
        liste = corps.get("applications") or []
        if not isinstance(liste, list):
            raise ValueError("liste d'applications attendue")
        for a in liste:
            app = normaliser_application(a)
            if not app:
                raise ValueError(f"application « {a} » inconnue (eKol, Aizenta ou Biolog)")
            if app not in applications:
                applications.append(app)
        propre["applications"] = applications
    if creation or "tenant_id" in corps:
        propre["tenant_id"] = (str(corps.get("tenant_id") or "").strip()[:80] or None)
        propre["client_nom"] = (str(corps.get("client_nom") or "").strip()[:160] or None)
    return propre


def fiche_publique(fiche: Dict[str, Any]) -> Dict[str, Any]:
    """Fiche renvoyée à la page : SANS l'empreinte (ni, évidemment, la clé)."""
    return {k: v for k, v in fiche.items() if k not in ("_id", "cle_hash")}


# ---------------------------------------------------------------------------
# Vérification (avec la base) : utilisée par la synchro, la présence et le support
# ---------------------------------------------------------------------------
async def identifier_cle(db, cle_recue: Optional[str], *, machine: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Identifie l'émetteur d'une clé Loois.

    Renvoie :
      {"type": "client", "id", "code", "libelle", "applications"} — clé client valide et active ;
      {"type": "commune"}                                          — clé commune LOOIS_SUPPORT_CLE ;
      None                                                         — clé absente, inconnue, révoquée.
    Met à jour « dernière utilisation » (au plus une fois par minute) ; ne lève jamais pour une base indisponible
    (la clé est alors simplement refusée, sauf la clé commune)."""
    cle = (cle_recue or "").strip()
    if not cle or len(cle) > MAX_LONGUEUR_CLE:
        return None
    if cle.startswith(PREFIXE_CLE):
        try:
            for empreinte in empreintes_candidates(cle):
                fiche = await db.loois_cles_clients.find_one({"cle_hash": empreinte, "actif": True},
                                                             {"_id": 0, "cle_hash": 0, "historique": 0})
                if not fiche:
                    continue
                ETAT["clients_actifs"] = True
                maintenant = _maintenant()
                seuil = (maintenant - timedelta(seconds=INTERVALLE_MAJ_UTILISATION)).isoformat()
                # Dernière utilisation : écrite seulement si l'ancienne date a plus d'une minute (pas une écriture par requête)
                await db.loois_cles_clients.update_one(
                    {"id": fiche["id"], "$or": [{"derniere_utilisation": None}, {"derniere_utilisation": {"$lt": seuil}}]},
                    {"$set": {"derniere_utilisation": maintenant.isoformat(),
                              "derniere_machine": (str(machine or "").strip()[:80] or fiche.get("derniere_machine"))}})
                return {"type": "client", "id": fiche["id"], "code": fiche["code"], "libelle": fiche.get("libelle") or fiche["code"],
                        "applications": fiche.get("applications") or []}
        except Exception:  # noqa: BLE001 — base indisponible : la clé client ne peut pas être vérifiée
            pass
    if cle_commune_valide(cle):
        return {"type": "commune"}
    return None


async def lire_reglages(db) -> Dict[str, Any]:
    """Réglages des clés clients (valeurs par défaut si rien n'est enregistré)."""
    doc = await db.loois_reglages.find_one({"id": ID_REGLAGES}, {"_id": 0}) or {}
    return {"accepter_cle_commune_synchro": bool(doc.get("accepter_cle_commune_synchro", False)),
            "maj_le": doc.get("maj_le"), "maj_par": doc.get("maj_par")}


async def accepter_commune_pour_synchro(db) -> bool:
    """Réglage de transition « Accepter encore la clé commune pour la synchro » (NON par défaut)."""
    return (await lire_reglages(db))["accepter_cle_commune_synchro"]


async def rafraichir_etat(db) -> None:
    """Met à jour ETAT["clients_actifs"] (au moins une clé client active existe)."""
    try:
        ETAT["clients_actifs"] = bool(await db.loois_cles_clients.find_one({"actif": True}, {"_id": 1}))
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Routes d'administration
# ---------------------------------------------------------------------------
def setup_loois_cles_clients_routes(*, db, api, get_current_user) -> None:
    """Branche les routes du lot 68.1 (appelée depuis server_parts/p20)."""
    from fastapi import Depends, HTTPException

    def admin(user: dict) -> None:
        """Réservé à l'administrateur (les clés donnent accès aux données d'élèves et de patients)."""
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")

    def auteur(user: dict) -> str:
        """Nom affiché de l'administrateur qui agit (historique de la fiche)."""
        return user.get("full_name") or user.get("email") or user.get("id") or "admin"

    async def fiche_ou_404(id_fiche: str) -> Dict[str, Any]:
        """Fiche d'une clé par son identifiant, sinon 404."""
        if not _ID.match(id_fiche or ""):
            raise HTTPException(status_code=404, detail="Clé inconnue")
        fiche = await db.loois_cles_clients.find_one({"id": id_fiche}, {"_id": 0})
        if not fiche:
            raise HTTPException(status_code=404, detail="Clé inconnue")
        return fiche

    async def index() -> None:
        """Index : empreinte unique (recherche rapide), code unique (une clé par client)."""
        try:
            await db.loois_cles_clients.create_index("cle_hash", unique=True)
            await db.loois_cles_clients.create_index("code", unique=True)
        except Exception:  # noqa: BLE001 — index déjà présent ou base simulée
            pass

    def nouvelle_empreinte() -> Dict[str, Any]:
        """Génère une clé, renvoie (en mémoire seulement) la clé en clair et les champs à enregistrer."""
        cle = generer_cle()
        p = poivre()
        return {"cle": cle, "champs": {"cle_hash": hacher_cle(cle, p), "cle_poivree": bool(p), "prefixe": prefixe_affiche(cle)}}

    @api.get("/admin/loois-cles-clients", tags=["Loois clés clients"])
    async def liste(user: dict = Depends(get_current_user)):
        """Liste des clés (sans empreinte), réglages, et codes de sites déjà vus par la synchro et le support."""
        admin(user)
        cles = [fiche_publique(f) async for f in db.loois_cles_clients.find({}, {"_id": 0, "cle_hash": 0}).sort("code", 1)]
        ETAT["clients_actifs"] = any(f.get("actif") for f in cles)
        # Codes déjà vus : postes de la synchro (code du site calculé par Loois) — aide à saisir le bon code
        sites = set()
        async for p in db.loois_synchro_postes.find({}, {"_id": 0, "site": 1, "application": 1}):
            if p.get("site"):
                sites.add((p["site"], p.get("application") or ""))
        sites_connus = [{"code": s, "application": a, "a_une_cle": any(c["code"] == s for c in cles)} for s, a in sorted(sites)]
        return {"cles": cles, "reglages": await lire_reglages(db), "poivre_configure": bool(poivre()),
                "cle_commune_configuree": bool((os.environ.get("LOOIS_SUPPORT_CLE") or "").strip()),
                "applications": list(APPLICATIONS_CONNUES), "sites_connus": sites_connus}

    @api.post("/admin/loois-cles-clients", tags=["Loois clés clients"])
    async def creer(request: Request, user: dict = Depends(get_current_user)):
        """Crée la clé d'un client. La clé en clair est renvoyée UNE SEULE FOIS (seule l'empreinte est gardée)."""
        admin(user)
        try:
            propre = nettoyer_fiche(await request.json(), creation=True)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        if await db.loois_cles_clients.find_one({"code": propre["code"]}, {"_id": 1}):
            raise HTTPException(status_code=409, detail=f"Le client {propre['code']} a déjà une clé : utilisez « Régénérer »")
        if await db.loois_cles_clients.count_documents({}) >= MAX_CLES:
            raise HTTPException(status_code=429, detail="trop de clés enregistrées")
        await index()
        nouvelle = nouvelle_empreinte()
        maintenant = _maintenant().isoformat()
        fiche = {"id": str(uuid.uuid4()), **propre, **nouvelle["champs"], "actif": True, "cree_le": maintenant,
                 "cree_par": auteur(user), "derniere_utilisation": None, "derniere_machine": None, "revoquee_le": None,
                 "historique": [{"action": "creation", "le": maintenant, "par": auteur(user), "prefixe": nouvelle["champs"]["prefixe"]}]}
        await db.loois_cles_clients.insert_one(dict(fiche))
        ETAT["clients_actifs"] = True
        return {"ok": True, "cle": nouvelle["cle"], "fiche": fiche_publique(fiche)}

    @api.put("/admin/loois-cles-clients/{id_fiche}", tags=["Loois clés clients"])
    async def modifier(id_fiche: str, request: Request, user: dict = Depends(get_current_user)):
        """Modifie le libellé, les applications autorisées ou le compte client lié (jamais la clé elle-même)."""
        admin(user)
        fiche = await fiche_ou_404(id_fiche)
        try:
            propre = nettoyer_fiche(await request.json(), creation=False)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        if "code" in propre and propre["code"] != fiche["code"] and await db.loois_cles_clients.find_one({"code": propre["code"]}, {"_id": 1}):
            raise HTTPException(status_code=409, detail=f"Le code {propre['code']} est déjà utilisé")
        maintenant = _maintenant().isoformat()
        await db.loois_cles_clients.update_one({"id": id_fiche}, {
            "$set": {**propre, "maj_le": maintenant, "maj_par": auteur(user)},
            "$push": {"historique": {"action": "modification", "le": maintenant, "par": auteur(user)}}})
        return {"ok": True, "fiche": fiche_publique(await fiche_ou_404(id_fiche))}

    @api.post("/admin/loois-cles-clients/{id_fiche}/regenerer", tags=["Loois clés clients"])
    async def regenerer(id_fiche: str, user: dict = Depends(get_current_user)):
        """Nouvelle clé pour ce client : l'ancienne est révoquée immédiatement (son empreinte est remplacée).
        La nouvelle clé est renvoyée UNE SEULE FOIS."""
        admin(user)
        fiche = await fiche_ou_404(id_fiche)
        nouvelle = nouvelle_empreinte()
        maintenant = _maintenant().isoformat()
        await db.loois_cles_clients.update_one({"id": id_fiche}, {
            "$set": {**nouvelle["champs"], "actif": True, "revoquee_le": None, "regeneree_le": maintenant,
                     "derniere_utilisation": None, "derniere_machine": None},
            "$push": {"historique": {"action": "regeneration", "le": maintenant, "par": auteur(user),
                                     "ancien_prefixe": fiche.get("prefixe"), "prefixe": nouvelle["champs"]["prefixe"]}}})
        ETAT["clients_actifs"] = True
        return {"ok": True, "cle": nouvelle["cle"], "fiche": fiche_publique(await fiche_ou_404(id_fiche))}

    @api.post("/admin/loois-cles-clients/{id_fiche}/revoquer", tags=["Loois clés clients"])
    async def revoquer(id_fiche: str, user: dict = Depends(get_current_user)):
        """Révoque la clé : tous les postes de ce client sont refusés dès la requête suivante."""
        admin(user)
        await fiche_ou_404(id_fiche)
        maintenant = _maintenant().isoformat()
        await db.loois_cles_clients.update_one({"id": id_fiche}, {
            "$set": {"actif": False, "revoquee_le": maintenant},
            "$push": {"historique": {"action": "revocation", "le": maintenant, "par": auteur(user)}}})
        await rafraichir_etat(db)
        return {"ok": True, "fiche": fiche_publique(await fiche_ou_404(id_fiche))}

    @api.post("/admin/loois-cles-clients/{id_fiche}/reactiver", tags=["Loois clés clients"])
    async def reactiver(id_fiche: str, user: dict = Depends(get_current_user)):
        """Réactive une clé révoquée (la même clé redevient valable sur les postes qui l'ont gardée)."""
        admin(user)
        await fiche_ou_404(id_fiche)
        maintenant = _maintenant().isoformat()
        await db.loois_cles_clients.update_one({"id": id_fiche}, {
            "$set": {"actif": True, "revoquee_le": None},
            "$push": {"historique": {"action": "reactivation", "le": maintenant, "par": auteur(user)}}})
        ETAT["clients_actifs"] = True
        return {"ok": True, "fiche": fiche_publique(await fiche_ou_404(id_fiche))}

    @api.put("/admin/loois-cles-clients-reglages", tags=["Loois clés clients"])
    async def enregistrer_reglages(request: Request, user: dict = Depends(get_current_user)):
        """Réglage de transition : accepter encore la clé commune pour la synchro des tables (NON par défaut)."""
        admin(user)
        try:
            corps = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        valeur = bool((corps or {}).get("accepter_cle_commune_synchro"))
        await db.loois_reglages.update_one({"id": ID_REGLAGES}, {"$set": {
            "id": ID_REGLAGES, "accepter_cle_commune_synchro": valeur,
            "maj_le": _maintenant().isoformat(), "maj_par": auteur(user)}}, upsert=True)
        return {"ok": True, "reglages": await lire_reglages(db)}
