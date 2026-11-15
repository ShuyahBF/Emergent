"""Lot 418 — Télé des familles : projeter des vidéos sur un téléviseur depuis l'application Personnel de maison.

Règles du propriétaire (15/11/2026) :
  - SEUL LE DÉTENTEUR DE L'APPAREIL lance sa projection sur la télé : les ordres passent par l'identité de l'appareil (en-têtes X-Famille-Compte /
    X-Famille-Jeton) ; l'administrateur de SAWALI et les autres membres de la famille ne peuvent pas piloter la télé d'un appareil ;
  - ABONNEMENT NÉCESSAIRE, et prix selon le nombre d'APPAREILS du foyer et de POSTES TV (téléviseurs) : chaque formule (créée dans Paramètres → « Formules des
    plateformes », plateforme « Personnel de maison », fonction « Télé ») porte deux limites : « appareils » (le titulaire compris) et « postes_tv ».

Pour un développeur WinDev (le « foyer » sans nouveau fichier) :
  - le TITULAIRE est celui qui paie la formule (même circuit que les autres formules : PawaPay / PI-SPI, parrainage, cumul des durées) ;
  - les appareils COUVERTS sont les proches ayant un lien VÉRIFIÉ avec le titulaire (« Ma famille »), dans l'ordre de création des liens, jusqu'à
    « appareils − 1 » ; le calcul est refait à chaque demande, rien n'est stocké en plus ;
  - les postes TV de la formule sont partagés par le titulaire et ses appareils couverts ;
  - une télé est appairée par le détenteur avec le CODE affiché par la page /tv de la télé (comme pour les écrans TV de l'administration) ;
    l'écran enregistré porte « proprietaire_compte » : la télécommande de l'administrateur ne le voit pas et ne le commande pas.
Lot 419 (propriétaire, 15/11/2026) : APPROBATION DE SAWALI TOUJOURS EXIGÉE, même pour un seul téléviseur (comme pour l'agenda Google) : le détenteur DEMANDE l'accès
(en indiquant où se trouve la télé), l'administrateur l'ACCEPTE ou le REFUSE (Paramètres → « Télé des familles »). L'ABONNEMENT n'est nécessaire qu'à partir de
2 télés SIMULTANÉES : une télé est offerte (réglable) à tout appareil approuvé ; au-delà, la formule fixe le nombre de postes TV.
Les vidéos proposées sont celles de la Bibliothèque de médias que l'administrateur a marquées « Visible dans Personnel de maison ».
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, Header, HTTPException, Request
from pydantic import BaseModel

import famille_tv_dossier as fd
from routes.ecran_tv import VALIDITE_CODE_MIN, modules_valides
from routes.formules_plateformes import AchatIn, AcheterIn, Utilisateur
from routes.tv_video import ACTIONS, DELTA_MAX_S, EN_LIGNE_S, PREFIXE

logger = logging.getLogger("sawali.famille_tv")

PLATEFORME = "personnelmaison"
FONCTION = "tv_video"
ID_CONFIG = "famille-tv-config"   # { approbation: bool (défaut True), postes_gratuits: int (défaut 1), demandes: [ {id, compte_id, nom, lieu, etat, cree_le, decide_le} ] }
MAX_DEMANDES = 500                # plafond : jamais de croissance illimitée par des demandes en rafale


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def meilleur_abonnement(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Abonnement « télé » actif du membre qui couvre le plus d'appareils (à égalité : le plus long). Limites par défaut : 1 appareil, 1 poste TV."""
    maintenant = _maintenant().isoformat()
    candidats = []
    for a in (m.get("abonnements") or {}).values():
        if FONCTION in (a.get("fonctions") or []) and (a.get("expire_le") or "") > maintenant:
            lim = a.get("limites") or {}
            candidats.append({"nom": a.get("nom") or "Formule", "expire_le": a["expire_le"], "appareils": max(1, int(lim.get("appareils") or 1)),
                              "postes_tv": max(1, int(lim.get("postes_tv") or 1))})
    return max(candidats, key=lambda c: (c["appareils"], c["expire_le"])) if candidats else None


def setup_famille_tv_routes(*, db, api, outils, authentifier, get_current_admin, envoyer_email=None):
    async def _envoyer(to: str, sujet: str, html: str, texte: str) -> bool:
        if envoyer_email is not None:
            return await envoyer_email(to, sujet, html, texte)
        from email_service import send_email
        return await send_email(to, sujet, html, texte)

    async def _compte(x_famille_compte: Optional[str] = Header(None), x_famille_jeton: Optional[str] = Header(None)) -> dict:
        compte = await authentifier(db, x_famille_compte, x_famille_jeton)
        if not compte:
            raise HTTPException(status_code=401, detail="Compte famille non reconnu.")
        return compte

    def _utilisateur(compte: dict) -> Utilisateur:
        return Utilisateur(id=str(compte["_id"]), nom=str(compte.get("nom") or "")[:120])

    async def _liens_verifies(compte_id: str) -> List[str]:
        """Comptes liés (lien VÉRIFIÉ) à ce compte, dans l'ordre de création des liens."""
        liens = await db.famille_liens.find({"comptes": compte_id, "statut": "verifie"}).sort("cree_le", 1).to_list(200)
        return [next(c for c in l["comptes"] if c != compte_id) for l in liens]

    async def _abonnement_de(compte_id: str) -> Optional[Dict[str, Any]]:
        m = await db.membres_plateformes.find_one({"plateforme": PLATEFORME, "utilisateur_id": compte_id}, {"_id": 0})
        return meilleur_abonnement(m) if m else None

    async def _groupe(titulaire_id: str, appareils: int) -> List[str]:
        """Le titulaire + ses appareils couverts (les « appareils − 1 » premiers liens vérifiés)."""
        return [titulaire_id] + (await _liens_verifies(titulaire_id))[:max(0, appareils - 1)]

    async def couverture(compte_id: str) -> Optional[Dict[str, Any]]:
        """Comment ce compte a droit à la télé : abonnement propre (« titulaire ») ou couvert par l'abonnement d'un proche (« couvert »)."""
        propre = await _abonnement_de(compte_id)
        if propre:
            return {"role": "titulaire", "titulaire_id": compte_id, **propre}
        for autre in await _liens_verifies(compte_id):
            abo = await _abonnement_de(autre)
            if abo and compte_id in (await _groupe(autre, abo["appareils"])):
                return {"role": "couvert", "titulaire_id": autre, **abo}
        return None

    # ------------------------------------------------------------------ approbation par l'administrateur (comme l'agenda Google)
    async def _config() -> Dict[str, Any]:
        d = await db.settings.find_one({"_id": ID_CONFIG}) or {}
        return {"approbation": d.get("approbation") is not False, "postes_gratuits": max(1, int(d.get("postes_gratuits") or 1)), "demandes": d.get("demandes") or []}

    async def _enregistrer_config(cfg: Dict[str, Any]) -> None:
        await db.settings.update_one({"_id": ID_CONFIG}, {"$set": {"approbation": cfg["approbation"], "postes_gratuits": cfg["postes_gratuits"], "demandes": cfg["demandes"]}}, upsert=True)

    def _demande_de(cfg: Dict[str, Any], compte_id: str) -> Optional[Dict[str, Any]]:
        return next((d for d in cfg["demandes"] if d["id"] == compte_id), None)

    async def _etat_approbation(compte_id: str) -> str:
        """« accepte » (ou approbation désactivée), « attente », « refuse » ou « aucune »."""
        cfg = await _config()
        if not cfg["approbation"]:
            return "accepte"
        return (_demande_de(cfg, compte_id) or {}).get("etat") or "aucune"

    async def _exiger_approbation(compte: dict) -> None:
        etat = await _etat_approbation(str(compte["_id"]))
        if etat != "accepte":
            texte = {"aucune": "Demandez d'abord l'accès à la télé : SAWALI doit l'approuver.", "attente": "Votre demande est en attente de l'approbation de SAWALI.",
                     "refuse": "Votre demande d'accès à la télé a été refusée par SAWALI."}[etat]
            raise HTTPException(status_code=403, detail={"code": "approbation_requise", "etat": etat, "message": texte})

    async def _droits(compte_id: str) -> Dict[str, Any]:
        """Droits effectifs : ceux de la formule (titulaire ou couvert), sinon l'offre de base (1 appareil, « postes_gratuits » télé(s))."""
        c = await couverture(compte_id)
        if c:
            return {"abonne": True, "couverture": c, "groupe": await _groupe(c["titulaire_id"], c["appareils"]), "postes_tv": c["postes_tv"], "appareils": c["appareils"]}
        return {"abonne": False, "couverture": None, "groupe": [compte_id], "postes_tv": (await _config())["postes_gratuits"], "appareils": 1}

    async def _ecrans_autorises(droits: Dict[str, Any]) -> List[str]:
        """Les télés utilisables : les plus anciennes du foyer, jusqu'au nombre de postes TV permis (si l'abonnement s'arrête, les plus récentes sont suspendues)."""
        liste = sorted((e for e in await _ecrans() if e.get("proprietaire_compte") in droits["groupe"]), key=lambda e: e.get("cree_le") or "")
        return [e["id"] for e in liste[:droits["postes_tv"]]]

    async def _ecrans() -> List[Dict[str, Any]]:
        g = await db.settings.find_one({"_id": "global"}, {"tv_ecrans": 1}) or {}
        return g.get("tv_ecrans") or []

    async def _mon_ecran(compte_id: str, ecran_id: str) -> Dict[str, Any]:
        """Écran appairé par CE compte ; les écrans des autres (et ceux de l'administration) sont refusés."""
        e = next((x for x in await _ecrans() if x.get("id") == ecran_id), None)
        if not e:
            raise HTTPException(status_code=404, detail="Télé introuvable")
        if e.get("proprietaire_compte") != compte_id:
            raise HTTPException(status_code=403, detail="Seul le détenteur de l'appareil qui a appairé cette télé peut lancer une projection.")
        return e

    async def _postes_utilises(groupe: List[str]) -> int:
        return sum(1 for e in await _ecrans() if e.get("proprietaire_compte") in groupe)

    async def _doc(ecran_id: str) -> Dict[str, Any]:
        d = await db.settings.find_one({"_id": PREFIXE + ecran_id}) or {"_id": PREFIXE + ecran_id}
        d.setdefault("seq", 0); d.setdefault("commande", None); d.setdefault("etat", None)
        return d

    def _en_ligne(d: Dict[str, Any], ecran: Dict[str, Any]) -> bool:
        limite = (_maintenant() - timedelta(seconds=EN_LIGNE_S)).isoformat()
        return any(v and v >= limite for v in (d.get("vu"), (d.get("etat") or {}).get("maj"), ecran.get("vu_le")))

    # ------------------------------------------------------------------ abonnement
    @api.get("/famille/tv/abonnement", tags=["Ma famille — Télé"])
    async def abonnement(compte: dict = Depends(_compte)):
        """Mon droit à la télé, les appareils et postes TV utilisés, et les formules proposées (prix selon appareils et postes TV)."""
        cid = str(compte["_id"])
        cat = await outils.catalogue_coeur(PLATEFORME, _utilisateur(compte))
        formules = [f for f in cat["formules"] if FONCTION in (f.get("fonctions") or [])]
        c = await couverture(cid)
        droits = await _droits(cid)
        cfg = await _config()
        sortie: Dict[str, Any] = {"actif": bool(c), "formules": formules, "approbation": await _etat_approbation(cid), "approbation_requise": cfg["approbation"],
                                  "effectif": {"postes_tv": droits["postes_tv"], "postes_utilises": await _postes_utilises(droits["groupe"]), "abonne": droits["abonne"]},
                                  "postes_gratuits": cfg["postes_gratuits"]}
        if c:
            groupe = await _groupe(c["titulaire_id"], c["appareils"])
            noms = {str(x["_id"]): x.get("nom", "?") async for x in db.famille_comptes.find({"_id": {"$in": groupe}}, {"nom": 1})}
            expire = datetime.fromisoformat(c["expire_le"])
            sortie.update({"role": c["role"], "formule": c["nom"], "expire_le": c["expire_le"], "jours_restants": max(0, (expire - _maintenant()).days),
                           "limites": {"appareils": c["appareils"], "postes_tv": c["postes_tv"]}, "titulaire": noms.get(c["titulaire_id"], "?"),
                           "appareils_couverts": [noms.get(g, "?") for g in groupe], "postes_utilises": await _postes_utilises(groupe)})
        return sortie

    @api.post("/famille/tv/acheter", tags=["Ma famille — Télé"])
    async def acheter(donnees: Dict[str, Any] = Body(...), compte: dict = Depends(_compte)):
        """Page de paiement (PawaPay) d'une formule « télé » : seules les formules qui débloquent la télé sont achetables ici."""
        await _exiger_approbation(compte)
        fid = str(donnees.get("formule_id") or "")
        f = await db.formules_plateformes.find_one({"id": fid, "plateforme": PLATEFORME, "actif": True}, {"_id": 0})
        if not f or FONCTION not in (f.get("fonctions") or []):
            raise HTTPException(status_code=422, detail="Formule inconnue")
        retour = str(donnees.get("retour") or "")[:400]
        return await outils.acheter_coeur(PLATEFORME, AcheterIn(utilisateur=_utilisateur(compte), formule_id=fid, retour=retour))

    @api.post("/famille/tv/achat", tags=["Ma famille — Télé"])
    async def achat(donnees: Dict[str, Any] = Body(...), compte: dict = Depends(_compte)):
        return await outils.achat_coeur(PLATEFORME, AchatIn(utilisateur=_utilisateur(compte), deposit_id=str(donnees.get("deposit_id") or "")))

    # ------------------------------------------------------------------ mes télés
    @api.get("/famille/tv/ecrans", tags=["Ma famille — Télé"])
    async def mes_ecrans(compte: dict = Depends(_compte)):
        cid = str(compte["_id"])
        sortie = []
        for e in await _ecrans():
            if e.get("proprietaire_compte") != cid:
                continue
            d = await _doc(e["id"])
            sortie.append({"id": e["id"], "nom": e.get("nom") or "Télé", "en_ligne": _en_ligne(d, e), "etat": d.get("etat")})
        return {"ecrans": sortie}

    @api.post("/famille/tv/appairer", tags=["Ma famille — Télé"])
    async def appairer(donnees: Dict[str, Any] = Body(...), compte: dict = Depends(_compte)):
        """Associe la télé qui affiche ce code (page /tv) à CET appareil. Abonnement actif et poste TV disponible exigés."""
        cid = str(compte["_id"])
        await _exiger_approbation(compte)
        droits = await _droits(cid)
        if await _postes_utilises(droits["groupe"]) >= droits["postes_tv"]:
            if not droits["abonne"]:
                # Une télé est offerte ; la 2e simultanée demande un abonnement : message avec le nom et le prix de la formule la moins chère
                m = await outils.membre(PLATEFORME, _utilisateur(compte))
                await outils.exiger_abonnement(PLATEFORME, m, FONCTION, "La projection sur plusieurs télés", refus=f"{droits['postes_tv']} télé(s) offerte(s) : un abonnement est nécessaire à partir de {droits['postes_tv'] + 1} télés simultanées.")
            raise HTTPException(status_code=409, detail=f"Limite atteinte : votre formule « {droits['couverture']['nom']} » permet {droits['postes_tv']} téléviseur(s). "
                                                        "Retirez une télé ou choisissez une formule avec plus de postes TV.")
        code = str(donnees.get("code") or "").strip().upper().replace(" ", "").replace("-", "")
        nom = str(donnees.get("nom") or "").strip()[:60] or "Télévision"
        g = await db.settings.find_one({"_id": "global"}, {"tv_appairages": 1}) or {}
        limite = (_maintenant() - timedelta(minutes=VALIDITE_CODE_MIN)).isoformat()
        appairage = next((a for a in g.get("tv_appairages") or [] if a.get("code") == code and a.get("cree_le", "") >= limite), None)
        if not appairage:
            raise HTTPException(status_code=404, detail="Code inconnu ou expiré : relancez la page /tv sur la télé pour obtenir un nouveau code.")
        ecran = {"id": uuid.uuid4().hex, "nom": nom, "code": code, "client_id": "", "client_nom": "", "modules": modules_valides({"video": True}),
                 "rdv_portee": "tous", "rdv_clair": False, "rdv_medecin": "", "empreinte": appairage["empreinte"], "cree_le": _maintenant().isoformat(),
                 "cree_par": "famille:" + cid, "vu_le": None, "proprietaire_compte": cid, "proprietaire_nom": str(compte.get("nom") or "")[:80]}
        await db.settings.update_one({"_id": "global"}, {"$push": {"tv_ecrans": ecran}, "$pull": {"tv_appairages": {"id": appairage["id"]}}})
        return {"ok": True, "ecran": {"id": ecran["id"], "nom": nom}}

    @api.delete("/famille/tv/ecrans/{ecran_id}", tags=["Ma famille — Télé"])
    async def retirer(ecran_id: str, compte: dict = Depends(_compte)):
        await _mon_ecran(str(compte["_id"]), ecran_id)
        await db.settings.update_one({"_id": "global"}, {"$pull": {"tv_ecrans": {"id": ecran_id}}})
        await db.settings.delete_one({"_id": PREFIXE + ecran_id})
        return {"ok": True}

    # ------------------------------------------------------------------ vidéos et télécommande
    @api.get("/famille/tv/videos", tags=["Ma famille — Télé"])
    async def videos(compte: dict = Depends(_compte)):
        """Vidéos proposées aux familles (marquées « Visible dans Personnel de maison » par l'administrateur)."""
        await _exiger_approbation(compte)
        cur = db.media_library.find({"kind": "video", "pour_familles": True, "is_deleted": {"$ne": True}}, {"_id": 0, "id": 1, "title": 1, "description": 1, "size": 1}).sort("created_at", -1).limit(100)
        return {"videos": await cur.to_list(length=100)}

    @api.post("/famille/tv/commande", tags=["Ma famille — Télé"])
    async def commande(corps: Dict[str, Any] = Body(...), compte: dict = Depends(_compte)):
        """Ordre à MA télé : lire (vidéo), pause, reprendre, avancer / reculer (delta), position, stop. Détenteur de l'appareil et abonnement actif exigés."""
        cid = str(compte["_id"])
        ecran = await _mon_ecran(cid, str(corps.get("ecran_id") or ""))
        await _exiger_approbation(compte)
        if ecran["id"] not in await _ecrans_autorises(await _droits(cid)):
            m = await outils.membre(PLATEFORME, _utilisateur(compte))
            await outils.exiger_abonnement(PLATEFORME, m, FONCTION, "Cette télé", refus="Cette télé dépasse les postes TV de votre offre (abonnement arrêté ou insuffisant).")
        action = str(corps.get("action") or "")
        if action not in ACTIONS:
            raise HTTPException(status_code=422, detail="Action inconnue")
        ordre: Dict[str, Any] = {"action": action, "par": "famille:" + cid, "le": _maintenant().isoformat()}
        if action == "lire":
            m = await db.media_library.find_one({"id": str(corps.get("video_id") or ""), "kind": "video", "pour_familles": True, "is_deleted": {"$ne": True}}, {"_id": 0})
            if not m or not m.get("storage_path"):
                raise HTTPException(status_code=404, detail="Vidéo introuvable")
            ordre.update({"video_id": m["id"], "titre": m.get("title") or m.get("filename") or "Vidéo"})
        elif action in ("avancer", "reculer"):
            ordre["delta"] = max(1, min(int(corps.get("delta") or 10), DELTA_MAX_S))
        elif action == "position":
            ordre["position"] = max(0.0, float(corps.get("position") or 0))
        from pymongo import ReturnDocument
        r = await db.settings.find_one_and_update({"_id": PREFIXE + ecran["id"]}, {"$inc": {"seq": 1}, "$set": {"commande": ordre}}, upsert=True, return_document=ReturnDocument.AFTER)
        return {"ok": True, "seq": (r or {}).get("seq", 1)}

    @api.get("/famille/tv/etat/{ecran_id}", tags=["Ma famille — Télé"])
    async def etat(ecran_id: str, compte: dict = Depends(_compte)):
        ecran = await _mon_ecran(str(compte["_id"]), ecran_id)
        d = await _doc(ecran_id)
        return {"seq": d["seq"], "etat": d.get("etat"), "en_ligne": _en_ligne(d, ecran)}

    # ------------------------------------------------------------------ demande d'accès (le détenteur) : captcha, e-mail vérifié, dossier
    def _iso(v: Any) -> str:
        return v.isoformat() if hasattr(v, "isoformat") else str(v or "")

    async def _liste_horodatee(ident: str, maintenant: datetime, fenetre: timedelta, ajouter: bool) -> int:
        """Compteur glissant (envois de codes) : liste d'horodatages dans un document « famille-tv-env:<clé> » ; rend le nombre d'envois dans la fenêtre (avant ajout)."""
        d = await db.settings.find_one({"_id": ident}) or {}
        limite = (maintenant - fenetre).isoformat()
        recents = [t for t in d.get("envois") or [] if t >= limite]
        if ajouter:
            await db.settings.update_one({"_id": ident}, {"$set": {"envois": recents + [maintenant.isoformat()]}}, upsert=True)
        return len(recents)

    def _cle_ip(ip: str) -> str:
        import hashlib
        return "famille-tv-env:ip:" + hashlib.sha256(ip.encode()).hexdigest()[:16]

    @api.get("/famille/tv/captcha", tags=["Ma famille — Télé"])
    async def captcha(compte: dict = Depends(_compte)):
        """Image de 5 caractères à recopier (limite les robots) ; le jeton signé accompagne la réponse."""
        jeton, _texte, png = fd.fabriquer_captcha()
        return {"jeton": jeton, "image": fd.png_en_data_url(png), "validite_s": fd.CAPTCHA_VALIDITE_S}

    @api.post("/famille/tv/verification", tags=["Ma famille — Télé"])
    async def verification(request: Request, donnees: Dict[str, Any] = Body(...), compte: dict = Depends(_compte)):
        """Étape 1 de la demande : téléphone + e-mail + captcha ; un CODE est envoyé à l'adresse e-mail (15 minutes, 5 essais)."""
        cid = str(compte["_id"])
        tel = fd.normaliser_telephone(str(donnees.get("telephone") or ""))
        if not tel:
            raise HTTPException(status_code=422, detail="Numéro de téléphone invalide (8 à 15 chiffres, avec ou sans l'indicatif du pays).")
        email = str(donnees.get("email") or "").strip()
        if not fd.email_valide(email):
            raise HTTPException(status_code=422, detail="Adresse e-mail invalide.")
        jeton = str(donnees.get("captcha_jeton") or "")
        if not fd.captcha_valide(jeton, str(donnees.get("captcha_reponse") or "")):
            raise HTTPException(status_code=422, detail="Image recopiée incorrecte ou expirée : recopiez les caractères de la nouvelle image.")
        nonce, expire = fd.lire_jeton_captcha(jeton)
        cap = await db.settings.find_one({"_id": "famille-tv-captcha"}) or {}
        maintenant = _maintenant()
        utilises = [u for u in cap.get("utilises") or [] if u["e"] >= int(maintenant.timestamp())]
        if any(u["n"] == nonce for u in utilises):
            raise HTTPException(status_code=422, detail="Cette image a déjà servi : recopiez les caractères de la nouvelle image.")
        await db.settings.update_one({"_id": "famille-tv-captcha"}, {"$set": {"utilises": (utilises + [{"n": nonce, "e": expire}])[-500:]}}, upsert=True)      # usage unique
        # limites contre les rafales : par compte et par adresse IP
        ip = fd.ip_client({k.lower(): v for k, v in request.headers.items()}, request.client.host if request.client else "")
        if await _liste_horodatee("famille-tv-env:" + cid, maintenant, timedelta(hours=1), False) >= fd.LIMITE_ENVOIS_CODE_COMPTE_H or \
                await _liste_horodatee(_cle_ip(ip), maintenant, timedelta(hours=1), False) >= fd.LIMITE_ENVOIS_CODE_IP_H:
            raise HTTPException(status_code=429, detail="Trop de codes demandés : réessayez dans une heure.")
        code = fd.nouveau_code()
        corps = (f"<p>Votre code de vérification pour demander l'accès à la télé (Personnel de maison) : <b style='font-size:22px;letter-spacing:3px'>{code}</b></p>"
                 "<p>Il est valable 15 minutes. Si vous n'êtes pas à l'origine de cette demande, ignorez ce message.</p>")
        envoye = await _envoyer(email, f"Votre code SAWALI : {code}", corps, f"Votre code de vérification SAWALI : {code} (valable 15 minutes).")
        if not envoye:
            raise HTTPException(status_code=502, detail="L'e-mail n'a pas pu être envoyé : vérifiez l'adresse puis réessayez, ou contactez l'administrateur.")
        await _liste_horodatee("famille-tv-env:" + cid, maintenant, timedelta(hours=1), True)
        await _liste_horodatee(_cle_ip(ip), maintenant, timedelta(hours=1), True)
        await db.settings.update_one({"_id": "famille-tv-verif:" + cid}, {"$set": {"email": email, "telephone": tel, "code_hash": fd.empreinte_code(cid, code), "essais": 0,
                                                                                    "expire": (maintenant + timedelta(seconds=fd.CODE_EMAIL_VALIDITE_S)).isoformat()}}, upsert=True)
        return {"ok": True, "email_masque": fd.masquer_email(email), "validite_minutes": fd.CODE_EMAIL_VALIDITE_S // 60}

    async def _dossier_complet(demande: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Évaluation à jour d'une demande (les doublons se calculent sur les demandes des AUTRES comptes)."""
        autres = [d for d in cfg["demandes"] if d["id"] != demande["id"]]
        return fd.evaluer(demande, autres, _maintenant().isoformat())

    @api.post("/famille/tv/demander", tags=["Ma famille — Télé"])
    async def demander(request: Request, donnees: Dict[str, Any] = Body(...), compte: dict = Depends(_compte)):
        """Étape 2 : le CODE reçu par e-mail prouve l'adresse ; le dossier (téléphone, e-mail vérifié, adresse IP et sa localisation, appareil, ancienneté du compte,
        proches vérifiés, indicateurs) part à SAWALI avec le lieu de la télé. Une demande acceptée n'est pas écrasée."""
        cid = str(compte["_id"])
        cfg = await _config()
        ancienne = _demande_de(cfg, cid)
        if ancienne and ancienne["etat"] == "accepte":
            return {"ok": True, "etat": "accepte"}
        maintenant = _maintenant()
        if ancienne and ancienne["etat"] == "attente":
            raise HTTPException(status_code=409, detail="Votre demande est déjà en attente de l'approbation de SAWALI.")
        if ancienne and ancienne["etat"] == "refuse" and ancienne.get("decide_le") and ancienne["decide_le"] > (maintenant - timedelta(hours=24)).isoformat():
            raise HTTPException(status_code=429, detail="Votre dernière demande a été refusée : une nouvelle demande sera possible dans 24 heures.")
        verif = await db.settings.find_one({"_id": "famille-tv-verif:" + cid})
        if not verif:
            raise HTTPException(status_code=422, detail="Vérifiez d'abord votre adresse e-mail : demandez le code.")
        if verif["expire"] < maintenant.isoformat():
            raise HTTPException(status_code=422, detail="Le code a expiré : demandez-en un nouveau.")
        if int(verif.get("essais") or 0) >= fd.CODE_EMAIL_ESSAIS:
            raise HTTPException(status_code=429, detail="Trop d'essais : demandez un nouveau code.")
        if verif["code_hash"] != fd.empreinte_code(cid, str(donnees.get("code_email") or "")):
            await db.settings.update_one({"_id": verif["_id"]}, {"$inc": {"essais": 1}})
            raise HTTPException(status_code=422, detail="Code incorrect.")
        ip = fd.ip_client({k.lower(): v for k, v in request.headers.items()}, request.client.host if request.client else "")
        recentes = [d for d in cfg["demandes"] if d.get("ip") == ip and d["id"] != cid and d["cree_le"] > (maintenant - timedelta(hours=24)).isoformat()]
        if ip and len(recentes) >= fd.LIMITE_DEMANDES_IP_24H:
            raise HTTPException(status_code=429, detail="Trop de demandes depuis cette connexion : réessayez demain.")
        liens = await db.famille_liens.count_documents({"comptes": cid, "statut": "verifie"})
        nouvelle = {"id": cid, "compte_id": cid, "nom": str(compte.get("nom") or "")[:80], "lieu": str(donnees.get("lieu") or "").strip()[:120], "etat": "attente",
                    "cree_le": maintenant.isoformat(), "decide_le": None, "telephone": verif["telephone"], "email": verif["email"], "email_verifie": True, "ip": ip,
                    "ip_infos": await fd.localiser_ip(ip), "appareil": fd.nettoyer_appareil(donnees.get("appareil")), "compte_cree_le": _iso(compte.get("cree_le")),
                    "liens_verifies": liens}
        nouvelle["evaluation"] = await _dossier_complet(nouvelle, cfg)
        cfg["demandes"] = ([x for x in cfg["demandes"] if x["id"] != cid] + [nouvelle])[-MAX_DEMANDES:]
        await _enregistrer_config(cfg)
        await db.settings.delete_one({"_id": verif["_id"]})
        return {"ok": True, "etat": "attente"}

    @api.get("/admin/famille-tv/etat", tags=["Admin — Télé des familles"])
    async def admin_etat(user: dict = Depends(get_current_admin)):
        cfg = await _config()
        ecrans = await _ecrans()
        demandes = []
        for d in cfg["demandes"]:
            ev = await _dossier_complet(d, cfg)
            a = d.get("appareil") or {}
            demandes.append({**{k: d.get(k) for k in ("id", "nom", "lieu", "etat", "cree_le", "decide_le", "email", "email_verifie", "ip")},
                             "postes": sum(1 for e in ecrans if e.get("proprietaire_compte") == d["id"]), "tel": (d.get("telephone") or {}).get("e164"),
                             "pays_ip": (d.get("ip_infos") or {}).get("code_pays"), "niveau": ev["niveau"], "score": ev["score"],
                             "appareil_resume": " ".join(x for x in (a.get("marque"), a.get("modele")) if x) + (f" · Android {a['android']}" if a.get("android") else "")})
        return {"approbation": cfg["approbation"], "postes_gratuits": cfg["postes_gratuits"], "demandes": sorted(demandes, key=lambda d: d.get("cree_le") or "", reverse=True),
                "postes_appaires": sum(1 for e in ecrans if e.get("proprietaire_compte"))}

    @api.get("/admin/famille-tv/demandes/{ident}/dossier", tags=["Admin — Télé des familles"])
    async def admin_dossier(ident: str, user: dict = Depends(get_current_admin)):
        """Dossier complet du demandeur : coordonnées, e-mail vérifié, adresse IP localisée, appareil, ancienneté, indicateurs de risque et demandes liées."""
        cfg = await _config()
        d = _demande_de(cfg, ident)
        if not d:
            raise HTTPException(status_code=404, detail="Demande introuvable")
        ev = await _dossier_complet(d, cfg)
        liees = [{"id": a["id"], "nom": a.get("nom"), "etat": a.get("etat"), "cree_le": a.get("cree_le"), "raison": [r for r, ok in (("même IP", d.get("ip") and a.get("ip") == d.get("ip")),
                 ("même téléphone", (a.get("telephone") or {}).get("e164") == (d.get("telephone") or {}).get("e164")), ("même e-mail", (a.get("email") or "").lower() == (d.get("email") or "").lower())) if ok]}
                 for a in cfg["demandes"] if a["id"] != ident]
        liees = [x for x in liees if x["raison"]]
        champs = ("id", "nom", "lieu", "etat", "cree_le", "decide_le", "decide_par", "telephone", "email", "email_verifie", "ip", "ip_infos", "appareil", "compte_cree_le", "liens_verifies")
        return {**{k: d.get(k) for k in champs}, **ev, "demandes_liees": liees}

    @api.post("/admin/famille-tv/demandes/{ident}", tags=["Admin — Télé des familles"])
    async def admin_decider(ident: str, corps: Dict[str, Any] = Body(...), user: dict = Depends(get_current_admin)):
        decision = str((corps or {}).get("decision") or "")
        if decision not in ("accepte", "refuse"):
            raise HTTPException(status_code=422, detail="Décision attendue : accepte ou refuse")
        cfg = await _config()
        d = _demande_de(cfg, ident)
        if not d:
            raise HTTPException(status_code=404, detail="Demande introuvable")
        d["etat"] = decision; d["decide_le"] = _maintenant().isoformat(); d["decide_par"] = user.get("email") or ""
        await _enregistrer_config(cfg)
        if decision == "refuse":                       # accès retiré : les télés de cet appareil sont déliées
            ids = [e["id"] for e in await _ecrans() if e.get("proprietaire_compte") == ident]
            if ids:
                await db.settings.update_one({"_id": "global"}, {"$pull": {"tv_ecrans": {"id": {"$in": ids}}}})
                for i in ids:
                    await db.settings.delete_one({"_id": PREFIXE + i})
        return {"ok": True, "etat": decision}

    @api.put("/admin/famille-tv/reglages", tags=["Admin — Télé des familles"])
    async def admin_reglages(corps: Dict[str, Any] = Body(...), user: dict = Depends(get_current_admin)):
        cfg = await _config()
        if "approbation" in (corps or {}):
            cfg["approbation"] = bool(corps["approbation"])
        if "postes_gratuits" in (corps or {}):
            try:
                n = int(corps["postes_gratuits"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail="Nombre de télés offertes invalide")
            if not 1 <= n <= 10:
                raise HTTPException(status_code=422, detail="Télés offertes : de 1 à 10")
            cfg["postes_gratuits"] = n
        await _enregistrer_config(cfg)
        return {"approbation": cfg["approbation"], "postes_gratuits": cfg["postes_gratuits"]}
