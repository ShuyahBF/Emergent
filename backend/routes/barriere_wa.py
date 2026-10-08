# barriere_wa.py — Lot 63 : « barrière » anti-rafale sur les messages WhatsApp reçus.
#
# Principe : un correspondant qui écrit plusieurs fois SANS avoir reçu de réponse d'un
# humain de SAWALI est arrêté au bout d'un nombre de messages paramétrable (ex. 2) :
#   - message n° 1 … seuil-1 : reçus normalement ;
#   - message n° seuil      : reçu normalement, PUIS réponse automatique « barrière »
#                              (texte + image facultative, paramétrables) ;
#   - messages suivants     : RETENUS (enregistrés avec la marque barriere_retenu, sans
#                              notification, sans non-lu, sans réponse de Liluvine).
# La barrière se lève dès qu'un utilisateur de SAWALI répond à ce correspondant.
#
# Réglages (Administration → Paramètres → « 🚧 Barrière anti-rafale WhatsApp ») :
#   wa_barriere_active (bool), wa_barriere_seuil (int, défaut 2),
#   wa_barriere_message (texte), wa_barriere_image_url (image facultative),
#   wa_barriere_fenetre_heures (messages pris en compte : dernières N heures, défaut 24),
#   wa_barriere_liluvine_compte (les réponses automatiques de Liluvine lèvent aussi la barrière),
#   wa_barriere_exemptes (numéros jamais bloqués).
# Ne sont jamais concernés : les commandes « ! » / « / », les réponses à des boutons,
# formulaires ou autorisations d'appel.
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

MESSAGE_DEFAUT = ("Sans réponse de votre correspondant, tout autre message de votre part ne sera pas "
                  "transmis. Instructions de l'Administrateur. Attendez une réponse avant de poursuivre SVP.")
# Types de messages concernés (les réponses à des boutons / formulaires restent libres)
logger = logging.getLogger("sawali.barriere_wa")
TYPES_CONCERNES = {"text", "image", "audio", "video", "document", "sticker", "location", "contacts"}


def _chiffres(valeur: Any) -> str:
    """Garde uniquement les chiffres d'un numéro."""
    return re.sub(r"\D", "", str(valeur or ""))


def reglages_barriere(s: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Réglages de la barrière (None si elle est désactivée)."""
    if not s.get("wa_barriere_active"):
        return None
    try:
        seuil = max(1, int(s.get("wa_barriere_seuil") or 2))
    except (TypeError, ValueError):
        seuil = 2
    try:
        fenetre = max(1, int(s.get("wa_barriere_fenetre_heures") or 24))
    except (TypeError, ValueError):
        fenetre = 24
    exemptes_brut = s.get("wa_barriere_exemptes") or []
    if isinstance(exemptes_brut, str):
        exemptes_brut = re.split(r"[,;\n]+", exemptes_brut)   # « +226 70 00 00 00 » garde ses espaces
    return {
        "seuil": seuil,
        "fenetre_heures": fenetre,
        "message": (s.get("wa_barriere_message") or "").strip() or MESSAGE_DEFAUT,
        "image_url": (s.get("wa_barriere_image_url") or "").strip(),
        "liluvine_compte": bool(s.get("wa_barriere_liluvine_compte")),
        "exemptes": {_chiffres(x)[-8:] for x in exemptes_brut if len(_chiffres(x)) >= 8},
    }


def est_concerne(reglages: Dict[str, Any], chiffres: str, mtype: str, texte: Optional[str]) -> bool:
    """Ce message entre-t-il dans le décompte de la barrière ?"""
    if mtype not in TYPES_CONCERNES:
        return False
    t = (texte or "").strip()
    if mtype == "text" and (t.startswith("!") or t.startswith("/")):
        return False                       # commandes Liluvine : jamais bloquées par la barrière
    return _chiffres(chiffres)[-8:] not in reglages["exemptes"]


def _filtre_reponse(fin: str, reglages: Dict[str, Any]) -> Dict[str, Any]:
    """Filtre MongoDB des messages qui « répondent » au correspondant et lèvent la barrière.

    Lot 64.2 — correction : avant, tout message sortant SANS la marque ai_generated comptait
    comme une réponse humaine. Or plusieurs réponses automatiques de Liluvine (VIDAL, boutons,
    réponses de secours…) sont enregistrées sans cette marque : chacune levait la barrière,
    qui ne se déclenchait donc jamais. Désormais, seule une réponse portant l'identifiant de
    l'utilisateur qui l'a envoyée (sender_id) compte comme réponse humaine.
    """
    filtre: Dict[str, Any] = {
        "direction": "outbound",
        "barriere_auto": {"$ne": True},          # la réponse de la barrière ne lève jamais la barrière
        "$or": [{"phone_digits": {"$regex": fin + "$"}}, {"to": {"$regex": fin + "$"}},
                {"to_number": {"$regex": fin + "$"}}],
    }
    if not reglages["liluvine_compte"]:
        # Réponse d'un humain uniquement : message envoyé depuis le portail par un utilisateur
        filtre["sender_id"] = {"$nin": [None, ""]}
        filtre["ai_generated"] = {"$ne": True}
    return filtre


async def etat_correspondant(db, chiffres: str, reglages: Dict[str, Any]) -> Dict[str, Any]:
    """État de la barrière pour un correspondant : dernière réponse prise en compte et
    nombre de messages reçus depuis (dans la fenêtre de temps), message en cours NON compris."""
    fin = re.escape(_chiffres(chiffres)[-8:])
    if not fin:
        return {"sans_reponse": 0, "derniere_reponse": None}
    depuis = (datetime.now(timezone.utc) - timedelta(hours=reglages["fenetre_heures"])).isoformat()
    derniere = await db.whatsapp_messages.find_one(
        _filtre_reponse(fin, reglages),
        {"_id": 0, "created_at": 1, "sender_label": 1, "body": 1, "text": 1},
        sort=[("created_at", -1)])
    borne = max(depuis, (derniere or {}).get("created_at") or "")
    n = await db.whatsapp_messages.count_documents({
        "direction": "inbound", "phone_digits": {"$regex": fin + "$"},
        "created_at": {"$gt": borne}, "barriere_exclu": {"$ne": True},
    })
    # Lot 64.5 — l'avertissement a-t-il déjà été envoyé depuis la dernière réponse ?
    deja_averti = bool(await db.whatsapp_messages.count_documents({
        "direction": "outbound", "barriere_auto": True, "created_at": {"$gt": borne},
        "$or": [{"phone_digits": {"$regex": fin + "$"}}, {"to": {"$regex": fin + "$"}}],
    }))
    return {"sans_reponse": n, "derniere_reponse": derniere, "compte_depuis": borne, "deja_averti": deja_averti}


async def messages_sans_reponse(db, chiffres: str, reglages: Dict[str, Any]) -> int:
    """Nombre de messages reçus de ce correspondant depuis la dernière réponse de SAWALI
    (dans la fenêtre de temps paramétrée), message en cours NON compris."""
    return (await etat_correspondant(db, chiffres, reglages))["sans_reponse"]


async def decision(db, chiffres: str, mtype: str, texte: Optional[str], s: Dict[str, Any]) -> str:
    """« normal » (laisser passer), « avertir » (laisser passer + réponse barrière)
    ou « retenir » (ne pas transmettre).

    Lot 64.4 — chaque décision est tracée dans les journaux du serveur (4 derniers chiffres
    du numéro seulement) pour pouvoir expliquer un comportement inattendu."""
    reglages = reglages_barriere(s)
    fin4 = _chiffres(chiffres)[-4:]
    if not reglages:
        logger.info("[barriere_wa] …%s : barrière désactivée", fin4)
        return "normal"
    if not est_concerne(reglages, chiffres, mtype, texte):
        logger.info("[barriere_wa] …%s : message non concerné (type=%s)", fin4, mtype)
        return "normal"
    etat = await etat_correspondant(db, chiffres, reglages)
    rang = etat["sans_reponse"] + 1                     # rang du message en cours
    # Lot 64.5 — correction : avant, l'avertissement ne partait qu'au message PILE au seuil ;
    # si le compteur avait déjà dépassé le seuil (messages antérieurs), il ne partait jamais.
    # Désormais : seuil atteint ou dépassé → avertissement s'il n'a pas encore été envoyé
    # depuis la dernière réponse, sinon message retenu.
    if rang < reglages["seuil"]:
        resultat = "normal"
    else:
        resultat = "retenir" if etat.get("deja_averti") else "avertir"
    derniere = etat.get("derniere_reponse") or {}
    logger.info("[barriere_wa] …%s : message n° %s sans réponse (seuil %s) → %s ; dernière réponse : %s (%s)",
                fin4, rang, reglages["seuil"], resultat, derniere.get("created_at") or "aucune",
                derniere.get("sender_label") or "—")
    return resultat


def setup_barriere_wa_routes(*, db, api, get_current_user, resolve_visible_client_ids=None) -> None:
    """Lot 64.2 — diagnostic de la barrière pour un numéro (administrateurs et superviseurs)."""
    from fastapi import Depends, HTTPException

    @api.get("/admin/barriere-wa/diagnostic", tags=["Admin — WhatsApp"])
    async def diagnostic(numero: str, user: dict = Depends(get_current_user)):
        """Que ferait la barrière au prochain message texte de ce numéro, et pourquoi ?"""
        if user.get("role") not in ("admin", "superviseur") and user.get("tracked_role") not in ("Administrateur", "Superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs et superviseurs")
        chiffres = _chiffres(numero)
        if len(chiffres) < 8:
            raise HTTPException(status_code=422, detail="Numéro trop court (8 chiffres au moins)")
        s = await db.settings.find_one({"_id": "global"}) or {}
        reglages = reglages_barriere(s)
        if not reglages:
            return {"active": False, "decision": "normal",
                    "explication": "La barrière est désactivée : cochez « Activer la barrière » puis enregistrez."}
        if chiffres[-8:] in reglages["exemptes"]:
            return {"active": True, "decision": "normal",
                    "explication": "Ce numéro fait partie des numéros jamais bloqués."}
        etat = await etat_correspondant(db, chiffres, reglages)
        rang = etat["sans_reponse"] + 1
        decision_suivante = "normal" if rang < reglages["seuil"] else ("retenir" if etat.get("deja_averti") else "avertir")
        derniere = etat["derniere_reponse"]
        explication = {
            "normal": f"Prochain message : n° {rang} sans réponse, sous le seuil ({reglages['seuil']}) — transmis normalement.",
            "avertir": f"Prochain message : n° {rang} (seuil {reglages['seuil']} atteint) — transmis, puis réponse automatique de la barrière.",
            "retenir": f"Prochain message : n° {rang} au-delà du seuil, avertissement déjà envoyé — retenu jusqu'à votre réponse.",
        }[decision_suivante]
        # Lot 64.11 — périmètre visible par l'utilisateur (pour signaler un message rangé ailleurs)
        perimetre = set(await resolve_visible_client_ids(user)) if resolve_visible_client_ids else None
        # Lot 64.4 — 10 derniers échanges avec ce numéro, et leur effet sur la barrière
        fin = re.escape(chiffres[-8:])
        filtre_rep = _filtre_reponse(fin, reglages)
        echanges = []
        async for m in db.whatsapp_messages.find(
                {"$or": [{"phone_digits": {"$regex": fin + "$"}}, {"to": {"$regex": fin + "$"}},
                         {"to_number": {"$regex": fin + "$"}}]},
                {"_id": 0, "id": 1, "direction": 1, "created_at": 1, "body": 1, "text": 1, "sender_label": 1,
                 "sender_id": 1, "ai_generated": 1, "auto_reply": 1, "barriere_auto": 1, "barriere_retenu": 1,
                 "source": 1, "message_type": 1, "client_id": 1, "contact_name": 1}).sort("created_at", -1).limit(10):
            leve = False
            if m.get("direction") == "outbound":
                leve = bool(await db.whatsapp_messages.count_documents({**filtre_rep, "id": m.get("id")})) if m.get("id") else False
            echanges.append({
                "le": m.get("created_at"), "sens": "reçu" if m.get("direction") == "inbound" else "envoyé",
                "texte": (m.get("body") or m.get("text") or "")[:80],
                "par": m.get("sender_label") or ("Liluvine" if m.get("ai_generated") or m.get("auto_reply") else ""),
                "retenu": bool(m.get("barriere_retenu")), "leve_la_barriere": leve,
                # Lot 64.11 — fiche contact rattachée et visibilité dans VOTRE Centre de messagerie
                "contact": m.get("contact_name") or "",
                "visible": None if perimetre is None else (m.get("client_id") in perimetre),
            })
        return {
            "echanges": echanges,
            "active": True, "seuil": reglages["seuil"], "fenetre_heures": reglages["fenetre_heures"],
            "messages_sans_reponse": etat["sans_reponse"], "decision": decision_suivante,
            "derniere_reponse_le": (derniere or {}).get("created_at"),
            "derniere_reponse_par": (derniere or {}).get("sender_label"),
            "explication": explication,
        }


    # Lot 64.14 — « Rattacher à ma fiche » : les messages de ce numéro rangés sur la fiche d'un
    # AUTRE compte (invisibles pour l'utilisateur) sont rattachés à SA fiche, qui devient la
    # fiche prioritaire pour ce numéro (les prochains messages y arrivent directement).
    @api.post("/admin/barriere-wa/rattacher", tags=["Admin — WhatsApp"])
    async def rattacher(numero: str, user: dict = Depends(get_current_user)):
        """Rattache à la fiche de l'utilisateur les messages de ce numéro rangés ailleurs."""
        if user.get("role") not in ("admin", "superviseur") and user.get("tracked_role") not in ("Administrateur", "Superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs et superviseurs")
        chiffres = _chiffres(numero)
        if len(chiffres) < 8:
            raise HTTPException(status_code=422, detail="Numéro trop court (8 chiffres au moins)")
        if not resolve_visible_client_ids:
            raise HTTPException(status_code=503, detail="Périmètre indisponible")
        perimetre = list(await resolve_visible_client_ids(user))
        fin = re.escape(chiffres[-8:]) + "$"
        # Numéro de fiche saisi avec des espaces ou des tirets (« 70 11 22 33 ») : reconnu aussi
        fin_souple = r"\D*".join(re.escape(ch) for ch in chiffres[-8:]) + r"\D*$"
        par_numero = [{"whatsapp": {"$regex": fin_souple}}, {"phone": {"$regex": fin_souple}},
                      {"phone_digits": {"$regex": fin_souple}}]
        # Fiche de l'utilisateur pour ce numéro (la plus ancienne)
        fiche = await db.directory_contacts.find_one(
            {"client_id": {"$in": perimetre}, "$or": par_numero}, {"_id": 0}, sort=[("created_at", 1)])
        if not fiche:
            raise HTTPException(status_code=404, detail="Aucune fiche de votre carnet n'a ce numéro : créez d'abord le contact.")
        # Cette fiche devient prioritaire pour ce numéro (une seule fiche prioritaire par numéro)
        await db.directory_contacts.update_many({"$or": par_numero, "id": {"$ne": fiche["id"]}},
                                                {"$unset": {"wa_prioritaire": ""}})
        await db.directory_contacts.update_one({"id": fiche["id"]}, {"$set": {"wa_prioritaire": True}})
        # Messages (reçus et envoyés) de ce numéro rangés hors du périmètre → rattachés à la fiche
        res = await db.whatsapp_messages.update_many(
            {"client_id": {"$nin": perimetre},
             "$or": [{"phone_digits": {"$regex": fin}}, {"to": {"$regex": fin_souple}}, {"to_number": {"$regex": fin_souple}}]},
            {"$set": {"client_id": fiche.get("client_id"), "contact_id": fiche["id"],
                      "contact_name": fiche.get("name"),
                      "rattache_le": datetime.now(timezone.utc).isoformat(),
                      "rattache_par": user.get("full_name") or user.get("email")}},
        )
        logger.info("[barriere_wa] …%s : %s message(s) rattaché(s) à la fiche %s", chiffres[-4:],
                    getattr(res, "modified_count", 0), fiche["id"])
        return {"ok": True, "rattaches": int(getattr(res, "modified_count", 0) or 0),
                "fiche": fiche.get("name") or fiche["id"]}


# ---------------------------------------------------------------------------
# Lot 79.6 — « Messages bloqués » : liste de TOUS les correspondants dont des messages sont
# retenus par la barrière (menu Liluvine), en plus du bandeau de chaque conversation du
# Centre de messagerie. Fonctions séparées des routes pour être testées sans serveur.
# ---------------------------------------------------------------------------
async def lister_retenus(db, perimetre: Optional[list], jours_liberes: int = 7, limite: int = 3000) -> Dict[str, Any]:
    """Regroupe par correspondant les messages RETENUS (barriere_retenu) du périmètre de l'utilisateur.
    perimetre : liste des client_id visibles (None = tout, réservé aux tests).
    -> {"bloques": [...], "liberes": [...]} ; « liberes » = retenues levées depuis `jours_liberes` jours."""
    filtre: Dict[str, Any] = {"direction": "inbound", "barriere_retenu": True}
    if perimetre is not None:
        filtre["client_id"] = {"$in": list(perimetre)}
    champs = {"_id": 0, "phone_digits": 1, "contact_id": 1, "contact_name": 1, "created_at": 1, "body": 1,
              "text": 1, "message_type": 1, "client_id": 1}
    groupes: Dict[str, Dict[str, Any]] = {}
    # Du plus récent au plus ancien : le premier message vu d'un correspondant est son dernier
    async for m in db.whatsapp_messages.find(filtre, champs).sort("created_at", -1).limit(limite):
        chiffres = _chiffres(m.get("phone_digits"))
        cle = chiffres[-8:] or (m.get("contact_id") or "?")
        g = groupes.get(cle)
        if g is None:
            g = groupes[cle] = {
                "numero": chiffres, "contact_id": m.get("contact_id"), "nom": m.get("contact_name") or "",
                "retenus": 0, "dernier_le": m.get("created_at"), "premier_le": m.get("created_at"),
                "dernier_texte": (m.get("body") or m.get("text") or f"[{m.get('message_type') or 'message'}]")[:120],
            }
        g["retenus"] += 1
        g["premier_le"] = m.get("created_at")          # le plus ancien vu jusqu'ici
        g["contact_id"] = g["contact_id"] or m.get("contact_id")
        g["nom"] = g["nom"] or m.get("contact_name") or ""
    bloques = sorted(groupes.values(), key=lambda g: g["dernier_le"] or "", reverse=True)
    # Date de l'avertissement automatique de la barrière (dernier envoyé à ce correspondant)
    for g in bloques:
        fin = g["numero"][-8:]
        if len(fin) == 8:
            av = await db.whatsapp_messages.find_one(
                {"direction": "outbound", "barriere_auto": True,
                 "$or": [{"to": {"$regex": re.escape(fin) + "$"}}, {"phone_digits": {"$regex": re.escape(fin) + "$"}}]},
                {"_id": 0, "created_at": 1}, sort=[("created_at", -1)])
            g["averti_le"] = (av or {}).get("created_at")
    # Retenues récemment levées (traçabilité : qui a libéré, quand)
    depuis = (datetime.now(timezone.utc) - timedelta(days=jours_liberes)).isoformat()
    filtre_lib: Dict[str, Any] = {"direction": "inbound", "barriere_libere_le": {"$gte": depuis}}
    if perimetre is not None:
        filtre_lib["client_id"] = {"$in": list(perimetre)}
    liberes: Dict[str, Dict[str, Any]] = {}
    async for m in db.whatsapp_messages.find(
            filtre_lib, {"_id": 0, "phone_digits": 1, "contact_name": 1, "barriere_libere_le": 1,
                         "barriere_libere_par": 1}).sort("barriere_libere_le", -1).limit(limite):
        cle = _chiffres(m.get("phone_digits"))[-8:] or "?"
        lib = liberes.setdefault(cle, {"numero": _chiffres(m.get("phone_digits")), "nom": m.get("contact_name") or "",
                                     "messages": 0, "libere_le": m.get("barriere_libere_le"),
                                     "libere_par": m.get("barriere_libere_par") or ""})
        lib["messages"] += 1
    return {"bloques": bloques, "liberes": list(liberes.values()),
            "total_retenus": sum(g["retenus"] for g in bloques)}


async def liberer_numero(db, perimetre: Optional[list], numero: str, par: str) -> int:
    """Remet dans la conversation les messages retenus de ce numéro (périmètre de l'utilisateur).
    La trace de la retenue est gardée (barriere_libere_le / barriere_libere_par). -> nombre libéré."""
    fin = _chiffres(numero)[-8:]
    if len(fin) < 8:
        return 0
    filtre: Dict[str, Any] = {"direction": "inbound", "barriere_retenu": True,
                              "phone_digits": {"$regex": re.escape(fin) + "$"}}
    if perimetre is not None:
        filtre["client_id"] = {"$in": list(perimetre)}
    res = await db.whatsapp_messages.update_many(
        filtre, {"$set": {"barriere_retenu": False, "barriere_libere_le": datetime.now(timezone.utc).isoformat(),
                          "barriere_libere_par": par}})
    logger.info("[barriere_wa] …%s : %s message(s) retenu(s) libéré(s) par %s", fin[-4:],
                getattr(res, "modified_count", 0), par)
    return int(getattr(res, "modified_count", 0) or 0)


def setup_messages_bloques_routes(*, db, api, get_current_user, resolve_visible_client_ids) -> None:
    """Lot 79.6 — routes du sous-menu Liluvine « Messages bloqués » (admin et superviseurs ;
    un superviseur restreint doit avoir reçu l'élément « bloques » dans le partage de Liluvine)."""
    from fastapi import Depends, HTTPException
    from routes.liluvine_partage import verifier_element

    async def _controle(user: dict) -> list:
        """Rôle autorisé + élément partagé ; renvoie le périmètre visible de l'utilisateur."""
        if user.get("role") not in ("admin", "super_admin", "superviseur") \
                and user.get("tracked_role") not in ("Administrateur", "Superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs et superviseurs")
        await verifier_element(db, user, "bloques")
        return list(await resolve_visible_client_ids(user))

    @api.get("/liluvine/messages-bloques", tags=["Liluvine — messages bloqués"])
    async def messages_bloques(user: dict = Depends(get_current_user)):
        """Correspondants dont des messages WhatsApp sont retenus par la barrière anti-rafale."""
        perimetre = await _controle(user)
        s = await db.settings.find_one({"_id": "global"}) or {}
        reglages = reglages_barriere(s)
        resultat = await lister_retenus(db, perimetre)
        resultat["barriere_active"] = reglages is not None
        resultat["seuil"] = (reglages or {}).get("seuil")
        return resultat

    @api.post("/liluvine/messages-bloques/liberer", tags=["Liluvine — messages bloqués"])
    async def liberer(numero: str, user: dict = Depends(get_current_user)):
        """« Remettre dans la conversation » les messages retenus d'un numéro."""
        perimetre = await _controle(user)
        if len(_chiffres(numero)) < 8:
            raise HTTPException(status_code=422, detail="Numéro trop court (8 chiffres au moins)")
        n = await liberer_numero(db, perimetre, numero, user.get("full_name") or user.get("email") or "")
        return {"ok": True, "liberes": n}
