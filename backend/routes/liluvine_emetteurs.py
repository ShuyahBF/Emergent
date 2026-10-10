"""Lot 57.4 — « Transmission WA Universelle Liluvine » : gestion des plateformes
émettrices (une clé HMAC propre à chacune) et journal des transmissions.

Routes (administrateur SAWALI) :
    GET    /api/admin/liluvine-emetteurs                 liste (jamais les clés) + envois du jour
    POST   /api/admin/liluvine-emetteurs                 créer {code, nom, quota_jour} -> clé affichée UNE fois
    POST   /api/admin/liluvine-emetteurs/{code}/regenerer nouvelle clé -> affichée UNE fois
    PATCH  /api/admin/liluvine-emetteurs/{code}          {nom, actif, quota_jour}
    DELETE /api/admin/liluvine-emetteurs/{code}
    GET    /api/admin/liluvine-transmissions?limite=100  journal (sans le texte des messages)

La clé n'est renvoyée qu'au moment de sa création / régénération, pour être
copiée dans la variable d'environnement LILUVINE_WA_HMAC de la plateforme.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

CODE_VALIDE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,29}$")   # ex. ster, adlyn, albarka, beauthentik


class NouvelEmetteur(BaseModel):
    code: str
    nom: str
    quota_jour: Optional[int] = 500
    url_retour: Optional[str] = None   # https://<plateforme>/api/webhooks/liluvine-retour (lot 57.5)
    url_stats: Optional[str] = None    # lot 62 — statistiques internes (vide = URL de retour)
    url_assistant: Optional[str] = None  # lot 102 — assistant de la plateforme (Liluvine lui pose les questions des clients)


class ModifEmetteur(BaseModel):
    nom: Optional[str] = None
    actif: Optional[bool] = None
    quota_jour: Optional[int] = None
    url_retour: Optional[str] = None
    url_stats: Optional[str] = None    # lot 62
    # Lot 84 : réponses des clients (« Répondre » sur un message de la plateforme) transmises ou non
    reponses_transmises: Optional[bool] = None
    # Lot 102 : adresse de l'assistant de la plateforme (ex. ZandGo : https://…/api/liluvine/question) ;
    # vide = Liluvine ne l'interroge pas
    url_assistant: Optional[str] = None


def _url_retour_valide(url: Optional[str]) -> str:
    """URL de retour : vide (pas de retour) ou adresse HTTPS."""
    url = (url or "").strip()
    if url and not url.startswith("https://"):
        raise HTTPException(status_code=422, detail="L'URL de retour doit commencer par https://")
    return url[:300]


def _nouvelle_cle() -> str:
    """Clé aléatoire forte : 48 octets -> 64 caractères (base64 URL)."""
    return secrets.token_urlsafe(48)


# ---------------------------------------------------------------------- lot 104 : modèle OTP (authentification)
NOM_MODELE_OTP = "code_connexion_plateformes"
WA_GRAPH_VERSION = "v21.0"


def corps_modele_otp(nom: str, langue: str = "fr") -> dict:
    """Corps POST /{waba}/message_templates d'un modèle d'AUTHENTIFICATION Meta : texte imposé par Meta
    (« *123456* est votre code de vérification »), rappel « ne le partagez pas », expiration 5 min,
    bouton « Copier le code ». Ce type de modèle part même hors de la fenêtre de 24 h."""
    return {"name": nom, "language": langue, "category": "AUTHENTICATION", "components": [
        {"type": "BODY", "add_security_recommendation": True},
        {"type": "FOOTER", "code_expiration_minutes": 5},
        {"type": "BUTTONS", "buttons": [{"type": "OTP", "otp_type": "COPY_CODE", "text": "Copier le code"}]},
    ]}


# ---------------------------------------------------------------------- lot 104.2 : modèle de la Transmission
NOM_MODELE_TRANSMISSION = "transmission_plateformes"
CORPS_TRANSMISSION = ("Le {{1}}, {{2}} vous écrit :\n\n{{3}}\n\n"
                      "Pour répondre, faites « Répondre » sur ce message.")


def corps_modele_transmission(nom: str, langue: str = "fr") -> dict:
    """Corps POST /{waba}/message_templates du modèle UTILITAIRE à 3 variables de la Transmission WA Universelle :
    {{1}} date/heure, {{2}} plateforme émettrice, {{3}} message. Le corps ne commence ni ne finit par une variable
    (règle Meta) ; exemples fournis pour l'approbation. Permet d'écrire hors de la fenêtre de 24 h."""
    return {"name": nom, "language": langue, "category": "UTILITY", "components": [
        {"type": "BODY", "text": CORPS_TRANSMISSION,
         "example": {"body_text": [["10/10/2026 14:30", "ZandGo", "Votre commande ZG-261006 est arrivée à Ouagadougou."]]}},
    ]}


async def creer_modele_meta(db, corps: dict, cle_nom: str, cle_langue: str) -> dict:
    """Envoie un modèle à Meta (POST message_templates) puis l'enregistre dans les Paramètres.
    Un modèle qui existe déjà chez Meta est simplement enregistré. Jamais de 401/403 renvoyé tel quel (502)."""
    reg = await db.settings.find_one({"_id": "global"}, {"_id": 0, "wa_access_token": 1, "wa_business_account_id": 1}) or {}
    if not reg.get("wa_access_token") or not reg.get("wa_business_account_id"):
        raise HTTPException(status_code=400, detail="WhatsApp non configuré (WABA ID et Access Token dans Paramètres)")
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.post(f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{reg['wa_business_account_id']}/message_templates",
                                json=corps, headers={"Authorization": f"Bearer {reg['wa_access_token']}"})
        brut = r.json() if r.content else {}
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=504, detail=f"Meta injoignable ({type(exc).__name__})")
    deja = "already exists" in str(brut).lower() or "existe" in str(brut).lower()
    if r.status_code >= 300 and not deja:
        msg = ((brut.get("error") or {}).get("error_user_msg") or (brut.get("error") or {}).get("message")) if isinstance(brut, dict) else None
        raise HTTPException(status_code=502, detail=f"Meta {r.status_code} : {msg or 'refus'}")
    await db.settings.update_one({"_id": "global"}, {"$set": {cle_nom: corps["name"], cle_langue: corps["language"]}}, upsert=True)
    return {"ok": True, "nom": corps["name"], "langue": corps["language"],
            "statut_meta": brut.get("status") or ("EXISTANT" if deja else "PENDING")}


async def statut_modele_meta(reg: dict, nom: str) -> Optional[str]:
    """État d'un modèle chez Meta (APPROVED, PENDING, REJECTED…), None si Meta ne répond pas."""
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get(f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{reg['wa_business_account_id']}/message_templates",
                               params={"name": nom, "fields": "name,status,language"},
                               headers={"Authorization": f"Bearer {reg['wa_access_token']}"})
        donnees = (r.json() or {}).get("data") or [] if r.status_code < 300 else []
        return donnees[0].get("status") if donnees else "INTROUVABLE"
    except (httpx.HTTPError, ValueError):
        return None


def make_liluvine_emetteurs_router(*, db, get_current_admin) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["Liluvine — Transmission WA Universelle"])

    @router.get("/liluvine-emetteurs")
    async def lister(admin: dict = Depends(get_current_admin)):
        """Plateformes émettrices, sans leurs clés, avec le nombre d'envois réussis du jour."""
        debut_jour = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        sortie = []
        async for e in db.liluvine_emetteurs.find({}, {"_id": 0, "secret": 0}).sort("code", 1):
            e["envois_du_jour"] = await db.liluvine_transmissions.count_documents(
                {"emetteur": e["code"], "ok": True, "date": {"$gte": debut_jour}})
            sortie.append(e)
        return {"emetteurs": sortie}

    @router.post("/liluvine-emetteurs")
    async def creer(donnees: NouvelEmetteur = Body(...), admin: dict = Depends(get_current_admin)):
        """Nouvelle plateforme émettrice : la clé est renvoyée cette seule fois."""
        code = donnees.code.strip().lower()
        if not CODE_VALIDE.match(code):
            raise HTTPException(status_code=422, detail="Code invalide (minuscules, chiffres, - ou _ ; 2 à 30 caractères)")
        if await db.liluvine_emetteurs.find_one({"code": code}):
            raise HTTPException(status_code=409, detail="Ce code existe déjà")
        cle = _nouvelle_cle()
        maintenant = datetime.now(timezone.utc).isoformat()
        await db.liluvine_emetteurs.insert_one({
            "code": code, "nom": donnees.nom.strip()[:60] or code, "secret": cle, "actif": True,
            "quota_jour": max(1, int(donnees.quota_jour or 500)), "cree_le": maintenant,
            "url_retour": _url_retour_valide(donnees.url_retour),
            "url_stats": _url_retour_valide(donnees.url_stats),   # lot 62
            "url_assistant": _url_retour_valide(donnees.url_assistant),   # lot 102
            "cle_regeneree_le": maintenant, "cree_par": admin.get("email"),
        })
        return {"code": code, "cle": cle}

    @router.post("/liluvine-emetteurs/{code}/regenerer")
    async def regenerer(code: str, admin: dict = Depends(get_current_admin)):
        """Nouvelle clé : l'ancienne cesse aussitôt de fonctionner."""
        cle = _nouvelle_cle()
        r = await db.liluvine_emetteurs.update_one(
            {"code": code}, {"$set": {"secret": cle, "cle_regeneree_le": datetime.now(timezone.utc).isoformat(),
                                      "cle_regeneree_par": admin.get("email")}})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Émetteur introuvable")
        return {"code": code, "cle": cle}

    @router.patch("/liluvine-emetteurs/{code}")
    async def modifier(code: str, donnees: ModifEmetteur = Body(...), admin: dict = Depends(get_current_admin)):
        """Nom, activation / désactivation, quota journalier."""
        changements = {}
        if donnees.nom is not None:
            changements["nom"] = donnees.nom.strip()[:60] or code
        if donnees.actif is not None:
            changements["actif"] = bool(donnees.actif)
        if donnees.quota_jour is not None:
            changements["quota_jour"] = max(1, int(donnees.quota_jour))
        if donnees.url_retour is not None:
            changements["url_retour"] = _url_retour_valide(donnees.url_retour)
        if donnees.url_stats is not None:   # lot 62 — adresse des statistiques internes
            changements["url_stats"] = _url_retour_valide(donnees.url_stats)
        if donnees.reponses_transmises is not None:   # lot 84
            changements["reponses_transmises"] = bool(donnees.reponses_transmises)
        if donnees.url_assistant is not None:   # lot 102 — assistant de la plateforme
            changements["url_assistant"] = _url_retour_valide(donnees.url_assistant)
        if not changements:
            return {"ok": True}
        r = await db.liluvine_emetteurs.update_one({"code": code}, {"$set": changements})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Émetteur introuvable")
        return {"ok": True}

    @router.delete("/liluvine-emetteurs/{code}")
    async def supprimer(code: str, admin: dict = Depends(get_current_admin)):
        r = await db.liluvine_emetteurs.delete_one({"code": code})
        if not r.deleted_count:
            raise HTTPException(status_code=404, detail="Émetteur introuvable")
        return {"ok": True}

    # ------------------------------------------------------------------ lot 104 : modèle des codes de connexion
    @router.get("/liluvine-modele-otp")
    async def modele_otp(admin: dict = Depends(get_current_admin)):
        """Modèle WhatsApp d'AUTHENTIFICATION utilisé pour les codes de connexion des plateformes,
        avec son état chez Meta (APPROVED, PENDING, REJECTED…) quand il est connu."""
        reg = await db.settings.find_one({"_id": "global"}, {"_id": 0, "liluvine_modele_otp": 1,
                                                             "liluvine_modele_otp_langue": 1,
                                                             "wa_access_token": 1, "wa_business_account_id": 1}) or {}
        nom = (reg.get("liluvine_modele_otp") or "").strip()
        sortie = {"nom": nom, "langue": reg.get("liluvine_modele_otp_langue") or "fr", "statut_meta": None,
                  "nom_propose": NOM_MODELE_OTP}
        if nom and reg.get("wa_access_token") and reg.get("wa_business_account_id"):
            sortie["statut_meta"] = await statut_modele_meta(reg, nom)
        return sortie

    @router.post("/liluvine-modele-otp/creer")
    async def creer_modele_otp(donnees: dict = Body(default={}), admin: dict = Depends(get_current_admin)):
        """Crée chez Meta le modèle d'AUTHENTIFICATION (catégorie AUTHENTICATION, bouton « Copier le code »,
        rappel de sécurité, expiration 5 min) puis l'enregistre comme modèle des codes de connexion.
        Meta l'approuve en général en quelques minutes."""
        reg = await db.settings.find_one({"_id": "global"}, {"_id": 0, "wa_access_token": 1, "wa_business_account_id": 1}) or {}
        if not reg.get("wa_access_token") or not reg.get("wa_business_account_id"):
            raise HTTPException(status_code=400, detail="WhatsApp non configuré (WABA ID et Access Token dans Paramètres)")
        nom = re.sub(r"[^a-z0-9_]", "", str(donnees.get("nom") or NOM_MODELE_OTP).lower())[:60] or NOM_MODELE_OTP
        langue = str(donnees.get("langue") or "fr")[:10]
        corps = corps_modele_otp(nom, langue)
        try:
            async with httpx.AsyncClient(timeout=15) as http:
                r = await http.post(f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{reg['wa_business_account_id']}/message_templates",
                                    json=corps, headers={"Authorization": f"Bearer {reg['wa_access_token']}"})
            brut = r.json() if r.content else {}
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=504, detail=f"Meta injoignable ({type(exc).__name__})")
        deja = "already exists" in str(brut).lower() or "existe" in str(brut).lower()
        if r.status_code >= 300 and not deja:
            # Jamais de 401/403 renvoyé tel quel (l'interface déconnecterait l'administrateur) : 502
            msg = ((brut.get("error") or {}).get("error_user_msg") or (brut.get("error") or {}).get("message")) if isinstance(brut, dict) else None
            raise HTTPException(status_code=502, detail=f"Meta {r.status_code} : {msg or 'refus'}")
        await db.settings.update_one({"_id": "global"}, {"$set": {"liluvine_modele_otp": nom, "liluvine_modele_otp_langue": langue}},
                                     upsert=True)
        return {"ok": True, "nom": nom, "langue": langue, "statut_meta": brut.get("status") or ("EXISTANT" if deja else "PENDING")}

    # ------------------------------------------------------------------ lot 104.2 : modèle de la Transmission
    @router.get("/liluvine-modele-transmission")
    async def modele_transmission(admin: dict = Depends(get_current_admin)):
        """Modèle à 3 variables (Date/Heure, Émetteur, Message) des messages transmis, avec son état chez Meta."""
        reg = await db.settings.find_one({"_id": "global"}, {"_id": 0, "liluvine_transmission_modele": 1,
                                                             "liluvine_transmission_langue": 1,
                                                             "wa_access_token": 1, "wa_business_account_id": 1}) or {}
        nom = (reg.get("liluvine_transmission_modele") or "").strip()
        sortie = {"nom": nom, "langue": reg.get("liluvine_transmission_langue") or "fr", "statut_meta": None,
                  "nom_propose": NOM_MODELE_TRANSMISSION, "corps": CORPS_TRANSMISSION}
        if nom and reg.get("wa_access_token") and reg.get("wa_business_account_id"):
            sortie["statut_meta"] = await statut_modele_meta(reg, nom)
        return sortie

    @router.post("/liluvine-modele-transmission/creer")
    async def creer_modele_transmission(donnees: dict = Body(default={}), admin: dict = Depends(get_current_admin)):
        """Crée chez Meta le modèle UTILITAIRE de la Transmission (3 variables) et l'enregistre dans les Paramètres."""
        nom = re.sub(r"[^a-z0-9_]", "", str(donnees.get("nom") or NOM_MODELE_TRANSMISSION).lower())[:60] or NOM_MODELE_TRANSMISSION
        langue = str(donnees.get("langue") or "fr")[:10]
        return await creer_modele_meta(db, corps_modele_transmission(nom, langue),
                                       "liluvine_transmission_modele", "liluvine_transmission_langue")

    @router.get("/liluvine-transmissions")
    async def journal(limite: int = 100, emetteur: Optional[str] = None, admin: dict = Depends(get_current_admin)):
        """Dernières transmissions (le texte des messages n'est jamais conservé).
        Lot 104.1 : filtre facultatif sur une plateforme (code de l'émetteur)."""
        limite = max(1, min(int(limite), 500))
        filtre = {"emetteur": emetteur.strip().lower()} if emetteur else {}
        lignes = await db.liluvine_transmissions.find(filtre, {"_id": 0}).sort("date", -1).to_list(limite)
        return {"transmissions": lignes}

    @router.get("/liluvine-transmissions/synthese")
    async def synthese(jours: int = 7, admin: dict = Depends(get_current_admin)):
        """Lot 104.1 — par plateforme, sur les N derniers jours : envois refusés par Meta, puis statut RÉEL
        de remise (envoyé, remis, lu, échoué) et dernier motif d'échec donné par Meta."""
        depuis = (datetime.now(timezone.utc) - timedelta(days=max(1, min(int(jours), 90)))).isoformat()
        par: dict = {}
        async for t in db.liluvine_transmissions.find({"date": {"$gte": depuis}}, {"_id": 0}).sort("date", -1):
            p = par.setdefault(t.get("emetteur") or "liluvine", {
                "emetteur": t.get("emetteur") or "liluvine", "source": t.get("source"), "total": 0, "refuses": 0,
                "envoye": 0, "remis": 0, "lu": 0, "echec": 0, "sans_statut": 0, "dernier_echec": None})
            p["total"] += 1
            if not t.get("ok"):
                p["refuses"] += 1
                motif = t.get("erreur")
            else:
                cle = {"sent": "envoye", "delivered": "remis", "read": "lu", "failed": "echec"}.get(t.get("statut"), "sans_statut")
                p[cle] += 1
                motif = t.get("erreur_remise") if t.get("statut") == "failed" else None
            if motif and not p["dernier_echec"]:          # les plus récents d'abord : premier motif = dernier échec
                p["dernier_echec"] = {"date": t.get("date"), "to": t.get("to"), "mode": t.get("mode"), "motif": motif}
        return {"jours": jours, "plateformes": sorted(par.values(), key=lambda x: x["emetteur"])}

    @router.get("/liluvine-desinscriptions")
    async def desinscriptions(admin: dict = Depends(get_current_admin)):
        """Numéros qui ont répondu STOP (par plateforme)."""
        lignes = await db.liluvine_desinscriptions.find({"actif": True}, {"_id": 0}).sort("date", -1).to_list(500)
        return {"desinscriptions": lignes}

    @router.post("/liluvine-desinscriptions/reinscrire")
    async def reinscrire(donnees: dict = Body(...), admin: dict = Depends(get_current_admin)):
        """Réinscription manuelle d'un numéro pour une plateforme {emetteur, numero}."""
        numero = "".join(c for c in str(donnees.get("numero") or "") if c.isdigit())
        r = await db.liluvine_desinscriptions.update_one(
            {"emetteur": donnees.get("emetteur"), "numero": numero, "actif": True},
            {"$set": {"actif": False, "reprise_le": datetime.now(timezone.utc).isoformat(), "reprise_par": admin.get("email")}})
        return {"ok": bool(r.modified_count)}

    @router.get("/liluvine-reponses")
    async def reponses(admin: dict = Depends(get_current_admin)):
        """Dernières réponses de clients relayées aux plateformes."""
        lignes = await db.liluvine_reponses.find({}, {"_id": 0}).sort("date", -1).to_list(100)
        return {"reponses": lignes}

    return router


__all__ = ["make_liluvine_emetteurs_router"]
