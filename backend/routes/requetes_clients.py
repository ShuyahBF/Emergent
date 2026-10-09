# requetes_clients.py — Lot 86 : REQUÊTES DES CLIENTS (dysfonctionnements, remarques, logiciels, équipements…).
#
# Demande du propriétaire (09/10/2026) : « Permettre à mes clients, contractuels ou pas, de me soumettre des points
# (dysfonctionnements, remarques, par logiciel ou sur leurs équipements…). Ces notifications écrites ou vocales sont
# horodatées et numérotées par client. De mon côté j'apprécie par une note/observation (date/heure auto), un état
# (en cours, terminé…) et le client évalue. Toutes ces requêtes sont organisées par lots ; quand c'est corrigé ou
# déployé, l'utilisateur revient pour évaluer. »
#
# En résumé (pour un développeur WinDev) :
#   - collections : db.requetes_clients (une fiche par requête) et db.requetes_lots (lots de correction) ;
#   - numéro par client : REQ-<code client>-0001, 0002… (compteur db.counters « requetes_<client> ») ;
#   - client (portail) : dépose une requête écrite et/ou vocale (fichier audio stocké, transcription automatique si la
#     clé Whisper est réglée), suit l'état et les observations, puis ÉVALUE (note 1 à 5 + commentaire) une fois la
#     requête terminée ou déployée ;
#   - SAWALI (administrateur) : ajoute des observations datées, change l'état, range la requête dans un lot ; quand un
#     lot passe à « Déployé », toutes ses requêtes passent à « Déployée » et chaque client est prévenu (e-mail et
#     WhatsApp, au mieux) qu'il peut évaluer.
from __future__ import annotations

import logging
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import File, Form, UploadFile   # au niveau du module : annotations des routes résolues (from __future__)

logger = logging.getLogger("sawali.requetes_clients")

CATEGORIES = {
    "dysfonctionnement": "Dysfonctionnement",
    "remarque": "Remarque / suggestion",
    "logiciel": "Logiciel",
    "equipement": "Équipement",
    "autre": "Autre",
}
ETATS = {
    "nouvelle": "Nouvelle",
    "en_cours": "En cours",
    "attente_client": "En attente du client",
    "terminee": "Terminée",
    "deployee": "Déployée",
    "rejetee": "Rejetée",
}
ETATS_A_EVALUER = {"terminee", "deployee", "rejetee"}   # le client peut alors évaluer
ETATS_LOT = {"ouvert": "Ouvert", "en_cours": "En cours", "deploye": "Déployé"}
TAILLE_MAX_AUDIO = 15 * 1024 * 1024   # 15 Mo


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


# =====================================================================================
# Logique pure (testée : tests/test_lot86_requetes_clients.py)
# =====================================================================================

def code_client(client: Optional[Dict[str, Any]]) -> str:
    """Code court du client pour la numérotation : client_code, sinon initiales de la société, sinon « CLI »."""
    c = client or {}
    code = re.sub(r"[^A-Z0-9]", "", str(c.get("client_code") or "").upper())
    if code:
        return code[:10]
    nom = re.sub(r"[^A-Za-z0-9 ]", " ", str(c.get("company") or c.get("full_name") or ""))
    mots = [m for m in nom.upper().split() if m]
    if not mots:
        return "CLI"
    return ("".join(m[0] for m in mots) if len(mots) > 1 else mots[0])[:6]


def numero_requete(code: str, seq: int) -> str:
    """« REQ-ALBRK-0007 »."""
    return f"REQ-{code}-{int(seq):04d}"


def tenant_de(user: Dict[str, Any]) -> str:
    """Client (tenant) d'un utilisateur : son compte principal, sinon lui-même."""
    return user.get("parent_client_id") or user.get("client_id") or user.get("id") or ""


def est_admin_sawali(user: Dict[str, Any]) -> bool:
    """Administrateur de SAWALI (traite les requêtes de tous les clients)."""
    return user.get("role") == "admin" and not user.get("parent_client_id")


def nettoyer_requete(categorie: Any, titre: Any, texte: Any, a_audio: bool) -> Dict[str, str]:
    """Contrôle d'une nouvelle requête ; ValueError avec message clair."""
    cat = str(categorie or "").strip().lower()
    if cat not in CATEGORIES:
        raise ValueError("Catégorie inconnue")
    titre = str(titre or "").strip()[:160]
    texte = str(texte or "").strip()[:5000]
    if not titre and not texte and not a_audio:
        raise ValueError("Écrivez votre requête ou enregistrez un message vocal")
    return {"categorie": cat, "titre": titre or (texte[:80] if texte else "Message vocal"), "texte": texte}


def evaluation_valide(note: Any, commentaire: Any) -> Dict[str, Any]:
    """Note entière de 1 à 5 + commentaire facultatif ; ValueError sinon."""
    try:
        n = int(note)
    except (TypeError, ValueError):
        raise ValueError("Note de 1 à 5 attendue")
    if not 1 <= n <= 5:
        raise ValueError("Note de 1 à 5 attendue")
    return {"note": n, "commentaire": str(commentaire or "").strip()[:1000]}


def resume(requetes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compte par état, requêtes à évaluer et moyenne des évaluations."""
    par_etat = {e: 0 for e in ETATS}
    notes = []
    for r in requetes:
        par_etat[r.get("etat") or "nouvelle"] = par_etat.get(r.get("etat") or "nouvelle", 0) + 1
        if (r.get("evaluation") or {}).get("note"):
            notes.append(r["evaluation"]["note"])
    return {"total": len(requetes), "par_etat": par_etat, "evaluees": len(notes),
            "moyenne": round(sum(notes) / len(notes), 2) if notes else None,
            "a_evaluer": sum(1 for r in requetes if r.get("a_evaluer"))}


# =====================================================================================
# Routes
# =====================================================================================

def setup_requetes_clients_routes(*, db, api, get_current_user, send_email=None, wa_send_text=None,
                                  transcrire=None, upload_dir=None) -> None:
    """Branche les routes du lot 86 (appelée depuis server_parts/p20)."""
    from fastapi import Depends, HTTPException
    from fastapi.responses import Response

    def _admin(user: dict) -> None:
        if not est_admin_sawali(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur de SAWALI")

    async def _client_doc(tenant_id: str) -> dict:
        return await db.users.find_one({"id": tenant_id}, {"_id": 0, "id": 1, "client_code": 1, "company": 1,
                                                          "full_name": 1, "email": 1, "whatsapp_number": 1,
                                                          "phone": 1}) or {}

    async def _prochain_numero(tenant_id: str, client: dict) -> str:
        doc = await db.counters.find_one_and_update({"_id": f"requetes_{tenant_id}"}, {"$inc": {"seq": 1}},
                                                    upsert=True, return_document=True)
        seq = (doc or {}).get("seq") or 1
        return numero_requete(code_client(client), seq)

    async def _stocker_audio(req_id: str, data: bytes, mime: str, nom: str) -> dict:
        """Enregistre le message vocal (stockage R2 si disponible, sinon dossier local)."""
        ext = os.path.splitext(nom or "")[1] or ".webm"
        try:
            from storage import aupload_bytes, astorage_available
            if await astorage_available():
                chemin = await aupload_bytes(f"requetes/{req_id}{ext}", data, mime)
                return {"storage_path": chemin, "mime": mime, "taille": len(data)}
        except Exception:  # noqa: BLE001 — repli sur le disque local
            logger.warning("[requetes] stockage R2 indisponible, enregistrement local", exc_info=True)
        dossier = Path(upload_dir or tempfile.gettempdir()) / "requetes"
        dossier.mkdir(parents=True, exist_ok=True)
        (dossier / f"{req_id}{ext}").write_bytes(data)
        return {"local": f"requetes/{req_id}{ext}", "mime": mime, "taille": len(data)}

    async def _transcrire(data: bytes, nom: str) -> Optional[str]:
        if not transcrire:
            return None
        try:
            with tempfile.NamedTemporaryFile(suffix=os.path.splitext(nom or "")[1] or ".webm", delete=False) as f:
                f.write(data)
                chemin = Path(f.name)
            try:
                return await transcrire(chemin, "fr")
            finally:
                chemin.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001 — la transcription est un plus, jamais bloquante
            return None

    async def _prevenir_client(tenant_id: str, texte: str, sujet: str) -> None:
        """Prévient le client (e-mail + WhatsApp), au mieux : une panne n'empêche jamais la mise à jour."""
        client = await _client_doc(tenant_id)
        if send_email and client.get("email"):
            try:
                await send_email(client["email"], sujet, f"<p>{texte}</p>", texte)
            except Exception:  # noqa: BLE001
                logger.warning("[requetes] e-mail au client non envoyé", exc_info=True)
        numero = client.get("whatsapp_number") or client.get("phone")
        if wa_send_text and numero:
            try:
                await wa_send_text(str(numero), texte, tenant_id=tenant_id)
            except Exception:  # noqa: BLE001
                logger.warning("[requetes] WhatsApp au client non envoyé", exc_info=True)

    def _public(r: dict) -> dict:
        """Fiche renvoyée (sans le chemin interne du fichier audio)."""
        r = dict(r)
        r.pop("_id", None)
        audio = r.pop("audio", None)
        r["a_audio"] = bool(audio)
        r["libelle_etat"] = ETATS.get(r.get("etat"), r.get("etat"))
        r["libelle_categorie"] = CATEGORIES.get(r.get("categorie"), r.get("categorie"))
        return r

    # ------------------------------------------------------------------ côté client (portail)
    @api.get("/me/requetes", tags=["Requêtes clients"])
    async def mes_requetes(user: dict = Depends(get_current_user)):
        """Requêtes du client (tous ses utilisateurs), les plus récentes d'abord."""
        lignes = [r async for r in db.requetes_clients.find({"tenant_id": tenant_de(user)}, {"_id": 0})
                  .sort("cree_le", -1).limit(500)]
        return {"requetes": [_public(r) for r in lignes], "categories": CATEGORIES, "etats": ETATS,
                "resume": resume(lignes)}

    @api.post("/me/requetes", tags=["Requêtes clients"])
    async def nouvelle_requete(categorie: str = Form(...), titre: str = Form(""), texte: str = Form(""),
                               logiciel: str = Form(""), equipement: str = Form(""),
                               audio: Optional[UploadFile] = File(None), user: dict = Depends(get_current_user)):
        """Dépôt d'une requête écrite et/ou vocale : numérotée par client et horodatée automatiquement."""
        data = await audio.read() if audio is not None else b""
        if len(data) > TAILLE_MAX_AUDIO:
            raise HTTPException(status_code=413, detail="Message vocal trop long (15 Mo au plus)")
        try:
            champs = nettoyer_requete(categorie, titre, texte, bool(data))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        tenant_id = tenant_de(user)
        client = await _client_doc(tenant_id)
        req_id = str(uuid.uuid4())
        maintenant = _maintenant()
        doc = {
            "id": req_id, "numero": await _prochain_numero(tenant_id, client), "tenant_id": tenant_id,
            "client_nom": client.get("company") or client.get("full_name") or user.get("company") or "",
            "auteur_id": user.get("id"), "auteur_nom": user.get("full_name") or user.get("email"),
            **champs, "logiciel": str(logiciel or "").strip()[:120], "equipement": str(equipement or "").strip()[:120],
            "cree_le": maintenant, "etat": "nouvelle", "lot_id": None, "lot_numero": None,
            "observations": [], "historique": [{"etat": "nouvelle", "le": maintenant, "par": user.get("full_name")}],
            "evaluation": None, "a_evaluer": False,
        }
        if data:
            mime = audio.content_type or "audio/webm"
            doc["audio"] = await _stocker_audio(req_id, data, mime, audio.filename or "")
            doc["transcription"] = await _transcrire(data, audio.filename or "")
        await db.requetes_clients.insert_one(dict(doc))
        return _public(doc)

    @api.post("/me/requetes/{req_id}/evaluation", tags=["Requêtes clients"])
    async def evaluer(req_id: str, corps: dict, user: dict = Depends(get_current_user)):
        """Évaluation par le client d'une requête terminée, déployée ou rejetée."""
        r = await db.requetes_clients.find_one({"id": req_id, "tenant_id": tenant_de(user)}, {"_id": 0})
        if not r:
            raise HTTPException(status_code=404, detail="Requête introuvable")
        if r.get("etat") not in ETATS_A_EVALUER:
            raise HTTPException(status_code=409, detail="La requête n'est pas encore traitée")
        try:
            ev = evaluation_valide((corps or {}).get("note"), (corps or {}).get("commentaire"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        ev.update(le=_maintenant(), par=user.get("full_name") or user.get("email"))
        await db.requetes_clients.update_one({"id": req_id}, {"$set": {"evaluation": ev, "a_evaluer": False}})
        return {"ok": True, "evaluation": ev}

    @api.get("/requetes/{req_id}/audio", tags=["Requêtes clients"])
    async def ecouter(req_id: str, user: dict = Depends(get_current_user)):
        """Message vocal d'une requête (le client concerné ou l'administrateur de SAWALI)."""
        r = await db.requetes_clients.find_one({"id": req_id}, {"_id": 0, "audio": 1, "tenant_id": 1})
        if not r or not r.get("audio") or not (est_admin_sawali(user) or r.get("tenant_id") == tenant_de(user)):
            raise HTTPException(status_code=404, detail="Message vocal introuvable")
        a = r["audio"]
        if a.get("storage_path"):
            from storage import afetch_bytes
            data, ct = await afetch_bytes(a["storage_path"])
        else:
            chemin = Path(upload_dir or tempfile.gettempdir()) / a.get("local", "")
            if not chemin.is_file():
                raise HTTPException(status_code=404, detail="Message vocal introuvable")
            data, ct = chemin.read_bytes(), a.get("mime")
        return Response(content=data, media_type=ct or a.get("mime") or "audio/webm",
                        headers={"Cache-Control": "private, max-age=86400"})

    # ------------------------------------------------------------------ côté SAWALI (administrateur)
    @api.get("/admin/requetes", tags=["Requêtes clients"])
    async def toutes(etat: str = "", tenant_id: str = "", lot_id: str = "", user: dict = Depends(get_current_user)):
        """Requêtes de tous les clients (filtres : état, client, lot)."""
        _admin(user)
        filtre: Dict[str, Any] = {}
        if etat:
            filtre["etat"] = etat
        if tenant_id:
            filtre["tenant_id"] = tenant_id
        if lot_id:
            filtre["lot_id"] = None if lot_id == "aucun" else lot_id
        lignes = [r async for r in db.requetes_clients.find(filtre, {"_id": 0}).sort("cree_le", -1).limit(1000)]
        tous = [r async for r in db.requetes_clients.find({}, {"_id": 0, "etat": 1, "evaluation": 1, "a_evaluer": 1})]
        clients = sorted({(r["tenant_id"], r.get("client_nom") or "") for r in lignes}, key=lambda x: x[1])
        return {"requetes": [_public(r) for r in lignes], "resume": resume(tous), "etats": ETATS,
                "categories": CATEGORIES, "clients": [{"id": i, "nom": n} for i, n in clients]}

    @api.patch("/admin/requetes/{req_id}", tags=["Requêtes clients"])
    async def traiter(req_id: str, corps: dict, user: dict = Depends(get_current_user)):
        """Observation datée, changement d'état, rangement dans un lot."""
        _admin(user)
        r = await db.requetes_clients.find_one({"id": req_id}, {"_id": 0})
        if not r:
            raise HTTPException(status_code=404, detail="Requête introuvable")
        corps = corps or {}
        maintenant, par = _maintenant(), user.get("full_name") or user.get("email")
        maj: Dict[str, Any] = {}
        pousser: Dict[str, Any] = {}
        obs = str(corps.get("observation") or "").strip()[:3000]
        if obs:
            pousser["observations"] = {"texte": obs, "le": maintenant, "par": par}
        etat = corps.get("etat")
        if etat and etat != r.get("etat"):
            if etat not in ETATS:
                raise HTTPException(status_code=422, detail="État inconnu")
            maj["etat"] = etat
            pousser["historique"] = {"etat": etat, "le": maintenant, "par": par}
            if etat in ETATS_A_EVALUER and not r.get("evaluation"):
                maj["a_evaluer"] = True
        if "lot_id" in corps:
            lot_id = corps.get("lot_id") or None
            lot = await db.requetes_lots.find_one({"id": lot_id}, {"_id": 0}) if lot_id else None
            if lot_id and not lot:
                raise HTTPException(status_code=404, detail="Lot introuvable")
            maj.update(lot_id=lot_id, lot_numero=(lot or {}).get("numero"))
        if not maj and not pousser:
            return _public(r)
        operation: Dict[str, Any] = {}
        if maj:
            operation["$set"] = maj
        if pousser:
            operation["$push"] = pousser
        await db.requetes_clients.update_one({"id": req_id}, operation)
        if maj.get("a_evaluer"):
            await _prevenir_client(r["tenant_id"],
                                   f"SAWALI : votre requête {r['numero']} est « {ETATS[etat]} ». Merci de l'évaluer "
                                   f"dans votre espace SAWALI → Mes requêtes.", f"Requête {r['numero']} : {ETATS[etat]}")
        return _public(await db.requetes_clients.find_one({"id": req_id}, {"_id": 0}))

    @api.get("/admin/requetes-lots", tags=["Requêtes clients"])
    async def lots(user: dict = Depends(get_current_user)):
        """Lots de correction, avec le nombre de requêtes de chacun."""
        _admin(user)
        sortie = []
        async for lot in db.requetes_lots.find({}, {"_id": 0}).sort("numero", -1):
            lot["requetes"] = await db.requetes_clients.count_documents({"lot_id": lot["id"]})
            lot["libelle_etat"] = ETATS_LOT.get(lot.get("etat"), lot.get("etat"))
            sortie.append(lot)
        return {"lots": sortie, "etats": ETATS_LOT}

    @api.post("/admin/requetes-lots", tags=["Requêtes clients"])
    async def nouveau_lot(corps: dict, user: dict = Depends(get_current_user)):
        """Nouveau lot (numéro automatique)."""
        _admin(user)
        titre = str((corps or {}).get("titre") or "").strip()[:160]
        if not titre:
            raise HTTPException(status_code=422, detail="Donnez un titre au lot")
        doc = await db.counters.find_one_and_update({"_id": "requetes_lots"}, {"$inc": {"seq": 1}},
                                                    upsert=True, return_document=True)
        lot = {"id": str(uuid.uuid4()), "numero": (doc or {}).get("seq") or 1, "titre": titre,
               "description": str((corps or {}).get("description") or "").strip()[:2000], "etat": "ouvert",
               "cree_le": _maintenant(), "deploye_le": None}
        await db.requetes_lots.insert_one(dict(lot))
        return lot

    @api.patch("/admin/requetes-lots/{lot_id}", tags=["Requêtes clients"])
    async def maj_lot(lot_id: str, corps: dict, user: dict = Depends(get_current_user)):
        """Titre / état du lot. « Déployé » : toutes ses requêtes passent à « Déployée » et les clients sont prévenus."""
        _admin(user)
        lot = await db.requetes_lots.find_one({"id": lot_id}, {"_id": 0})
        if not lot:
            raise HTTPException(status_code=404, detail="Lot introuvable")
        corps = corps or {}
        maj: Dict[str, Any] = {}
        if corps.get("titre"):
            maj["titre"] = str(corps["titre"]).strip()[:160]
        etat = corps.get("etat")
        prevenus = 0
        if etat and etat != lot.get("etat"):
            if etat not in ETATS_LOT:
                raise HTTPException(status_code=422, detail="État de lot inconnu")
            maj["etat"] = etat
            if etat == "deploye":
                maintenant, par = _maintenant(), user.get("full_name") or user.get("email")
                maj["deploye_le"] = maintenant
                requetes = [r async for r in db.requetes_clients.find(
                    {"lot_id": lot_id, "etat": {"$nin": ["deployee", "rejetee"]}}, {"_id": 0})]
                for r in requetes:
                    await db.requetes_clients.update_one({"id": r["id"]}, {
                        "$set": {"etat": "deployee", "a_evaluer": not r.get("evaluation")},
                        "$push": {"historique": {"etat": "deployee", "le": maintenant, "par": par,
                                                 "lot": lot["numero"]}}})
                # Un message par client : ses requêtes déployées dans ce lot
                par_client: Dict[str, List[str]] = {}
                for r in requetes:
                    par_client.setdefault(r["tenant_id"], []).append(r["numero"])
                for tenant_id, numeros in par_client.items():
                    await _prevenir_client(
                        tenant_id,
                        f"SAWALI : le lot {lot['numero']} « {lot['titre']} » est déployé. Vos requêtes "
                        f"{', '.join(numeros)} sont traitées. Merci de les évaluer dans votre espace SAWALI → Mes requêtes.",
                        f"Lot {lot['numero']} déployé — merci d'évaluer vos requêtes")
                    prevenus += 1
        if maj:
            await db.requetes_lots.update_one({"id": lot_id}, {"$set": maj})
        return {**lot, **maj, "clients_prevenus": prevenus}
