# routes/pointage_telephone.py — Lot 496 : routes du POINTAGE D'INVENTAIRE PAR TÉLÉPHONE (logique dans backend/pointage_telephone.py).
#
# Administration (Paramètres → « 📱 Pointage D'Inventaire Par Téléphone », administrateur seul) :
#   GET  /api/admin/pointage-inventaires                 → liste (résumés)
#   GET  /api/admin/pointage-inventaires/structures      → structures ayant une clé de suivi SAWALI (fiches « clés clients » actives)
#   POST /api/admin/pointage-inventaires                 → création {structure_id, lieux[], nom_fichier, export}
#   GET  /api/admin/pointage-inventaires/{id}            → avancement, alertes, lignes, jeton du QR code
#   POST /api/admin/pointage-inventaires/{id}/jeton      → nouveau QR code (l'ancien est refusé aussitôt)
#   POST /api/admin/pointage-inventaires/{id}/cloturer   → clôture (le QR code ne sert plus)
#   POST /api/admin/pointage-inventaires/{id}/rouvrir    → réouverture (nouveau QR code)
#   GET  /api/admin/pointage-inventaires/{id}/export     → JSON complété, format WinDev (réimportable dans Aizenta)
# Téléphones (page publique /pointage/<jeton>, sans compte : le jeton du QR code EST l'accès, limité à cet inventaire) :
#   GET  /api/public/pointage/{jeton}                    → structure, lieux, lignes (N°, libellé, mesure) pour l'affichage hors connexion
#   POST /api/public/pointage/{jeton}/saisies            → envoi groupé (file d'attente du téléphone), sans double comptage (uid)
#   POST /api/public/pointage/{jeton}/annuler            → annule une saisie de CE téléphone
#
# Sécurité (règle 21) : jeton aléatoire long, expirant (3 jours) et révocable ; le prénom est « déclaré, non vérifiable » et affiché
# comme tel ; chaque saisie garde l'heure du serveur et l'identifiant de l'appareil ; un appareil ne peut annuler que ses propres saisies.
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

import pointage_telephone as pt
from routes.liluvine_partage import est_admin


# Modèles au NIVEAU DU MODULE (FastAPI ne retrouve pas ceux déclarés dans une fonction : 422)
class Lieu(BaseModel):
    nom: str = Field(min_length=1, max_length=40)
    colonne: str = Field(min_length=2, max_length=2)


class Creation(BaseModel):
    structure_id: str = Field(min_length=1, max_length=80)
    lieux: List[Lieu] = Field(default_factory=list)
    nom_fichier: Optional[str] = Field(default=None, max_length=200)
    export: Dict[str, Any]


class Envoi(BaseModel):
    prenom: str = Field(min_length=1, max_length=40)
    appareil: str = Field(min_length=8, max_length=64)
    saisies: List[Dict[str, Any]] = Field(default_factory=list, max_length=200)


class Annulation(BaseModel):
    appareil: str = Field(min_length=8, max_length=64)
    uid: str = Field(min_length=8, max_length=64)


def setup_pointage_telephone_routes(*, db, api, get_current_user) -> None:
    async def _admin(user: dict = Depends(get_current_user)) -> dict:
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        return user

    async def _fiche(ident: str, projection: Optional[dict] = None) -> dict:
        doc = await db.settings.find_one({"_id": pt.PREFIXE_ID + ident}, projection)
        if not doc:
            raise HTTPException(status_code=404, detail="Inventaire introuvable")
        return doc

    async def _par_jeton(jeton: str, projection: Optional[dict] = None) -> dict:
        """Inventaire ouvert correspondant au jeton du QR code ; 404 sinon (jamais de détail sur la raison : jeton inconnu ou expiré)."""
        if not jeton or len(jeton) < 20 or len(jeton) > 64:
            raise HTTPException(status_code=404, detail="QR code inconnu ou expiré")
        doc = await db.settings.find_one({"_id": {"$regex": "^" + pt.PREFIXE_ID}, "jeton": jeton}, projection)
        if not pt.jeton_valide(doc):
            raise HTTPException(status_code=404, detail="QR code inconnu, expiré, ou inventaire clôturé")
        return doc

    # ------------------------------------------------------------------ administration
    @api.get("/admin/pointage-inventaires", tags=["Pointage par téléphone"])
    async def liste(_: dict = Depends(_admin)):
        # Projection : jamais l'export complet ni le jeton dans la liste (règle 7 : lecture légère)
        curseur = db.settings.find({"_id": {"$regex": "^" + pt.PREFIXE_ID}},
                                   {"jeton": 0, "export": 0}).sort("cree_le", -1).limit(100)
        return {"inventaires": [pt.fiche_liste(d) async for d in curseur]}

    @api.get("/admin/pointage-inventaires/structures", tags=["Pointage par téléphone"])
    async def structures(_: dict = Depends(_admin)):
        # Structures ayant une clé de suivi SAWALI : fiches « clés clients » actives (Plateformes → Loois → Synchro → Clés clients)
        curseur = db.loois_cles_clients.find({"actif": {"$ne": False}}, {"_id": 0, "id": 1, "code": 1, "libelle": 1, "client_nom": 1})
        fiches = [f async for f in curseur]
        return {"structures": sorted(fiches, key=lambda f: str(f.get("libelle") or f.get("code") or "").lower())}

    @api.post("/admin/pointage-inventaires", tags=["Pointage par téléphone"])
    async def creer(corps: Creation, user: dict = Depends(_admin)):
        structure = await db.loois_cles_clients.find_one({"id": corps.structure_id, "actif": {"$ne": False}},
                                                          {"_id": 0, "id": 1, "code": 1, "libelle": 1})
        if not structure:
            raise HTTPException(status_code=400, detail="Structure inconnue : elle doit avoir une clé de suivi active sur SAWALI")
        compteur = await db.settings.find_one_and_update({"_id": pt.ID_COMPTEUR}, {"$inc": {"valeur": 1}},
                                                         upsert=True, return_document=True)
        try:
            doc = pt.creer_inventaire(ident=uuid.uuid4().hex[:12], numero=pt.numero_suivant(compteur.get("valeur") or 1),
                                      structure=structure, lieux=[l.model_dump() for l in corps.lieux], export=corps.export,
                                      nom_fichier=corps.nom_fichier, par=user.get("email") or user.get("name") or "admin")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        await db.settings.insert_one(doc)
        return pt.fiche_liste(doc)

    @api.get("/admin/pointage-inventaires/{ident}", tags=["Pointage par téléphone"])
    async def detail(ident: str, _: dict = Depends(_admin)):
        doc = await _fiche(ident)
        # Calcul en mémoire (une seule lecture) ; 5000 lignes × 30 000 saisies au plus : rapide, mais hors de la boucle d'événements
        etat = await asyncio.to_thread(pt.etat, doc)
        return pt.fiche_liste(doc) | {"jeton": doc.get("jeton") if doc.get("etat") == "ouvert" else None,
                                      "jeton_valide": pt.jeton_valide(doc), "nom_fichier": doc.get("nom_fichier")} | etat

    @api.post("/admin/pointage-inventaires/{ident}/jeton", tags=["Pointage par téléphone"])
    async def nouveau_jeton(ident: str, _: dict = Depends(_admin)):
        doc = await _fiche(ident, {"etat": 1})
        if doc.get("etat") != "ouvert":
            raise HTTPException(status_code=409, detail="Inventaire clôturé : le rouvrir d'abord")
        jeton, expire = pt.nouveau_jeton()
        await db.settings.update_one({"_id": pt.PREFIXE_ID + ident}, {"$set": {"jeton": jeton, "jeton_expire": expire}})
        return {"jeton": jeton, "jeton_expire": expire}

    @api.post("/admin/pointage-inventaires/{ident}/cloturer", tags=["Pointage par téléphone"])
    async def cloturer(ident: str, user: dict = Depends(_admin)):
        await _fiche(ident, {"_id": 1})
        await db.settings.update_one({"_id": pt.PREFIXE_ID + ident}, {"$set": {
            "etat": "cloture", "jeton": None, "cloture_le": pt.maintenant().isoformat(), "cloture_par": user.get("email")}})
        return {"etat": "cloture"}

    @api.post("/admin/pointage-inventaires/{ident}/rouvrir", tags=["Pointage par téléphone"])
    async def rouvrir(ident: str, _: dict = Depends(_admin)):
        await _fiche(ident, {"_id": 1})
        jeton, expire = pt.nouveau_jeton()
        await db.settings.update_one({"_id": pt.PREFIXE_ID + ident}, {"$set": {"etat": "ouvert", "jeton": jeton, "jeton_expire": expire}})
        return {"etat": "ouvert", "jeton": jeton, "jeton_expire": expire}

    @api.get("/admin/pointage-inventaires/{ident}/export", tags=["Pointage par téléphone"])
    async def export(ident: str, _: dict = Depends(_admin)):
        doc = await _fiche(ident)
        sortie = await asyncio.to_thread(pt.exporter, doc)
        # Même style que l'export WinDev : ASCII pur (accents en é), ordre des champs conservé
        contenu = json.dumps(sortie, ensure_ascii=True, separators=(", ", ":")).encode("ascii")
        nom = pt.nom_export(doc).encode("ascii", "replace").decode().replace("?", "_")
        return Response(content=contenu, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{nom}"'})

    # ------------------------------------------------------------------ téléphones (QR code)
    @api.get("/public/pointage/{jeton}", tags=["Pointage par téléphone"])
    async def ouvrir(jeton: str):
        doc = await _par_jeton(jeton, {"saisies": 0})
        lignes = [{"c": x["Chrono"], "l": x.get("Libellé"), "m": x.get("Mesure")}
                  for x in (doc.get("export") or {}).get(pt.CLE_TABLE) or []]
        return {"numero": doc.get("numero"), "code_inv": doc.get("code_inv"),
                "structure": (doc.get("structure") or {}).get("libelle") or (doc.get("structure") or {}).get("code"),
                "lieux": [{"id": l["id"], "nom": l["nom"]} for l in doc.get("lieux") or []], "lignes": lignes,
                "jeton_expire": doc.get("jeton_expire")}

    @api.post("/public/pointage/{jeton}/saisies", tags=["Pointage par téléphone"])
    async def saisir(jeton: str, corps: Envoi, request: Request):
        doc = await _par_jeton(jeton, {"export." + pt.CLE_TABLE + ".Chrono": 1, "lieux": 1, "etat": 1, "jeton_expire": 1})
        try:
            prenom = pt.nettoyer_prenom(corps.prenom)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        chronos = {x["Chrono"] for x in (doc.get("export") or {}).get(pt.CLE_TABLE) or []}
        cle = {"_id": doc["_id"]}
        acceptees, refusees, doublons = [], [], []
        for brute in corps.saisies:
            try:
                s = pt.nettoyer_saisie(brute, lieux=doc.get("lieux") or [], chronos=chronos)
            except ValueError as e:
                refusees.append({"uid": str((brute or {}).get("uid") or ""), "erreur": str(e)})
                continue
            # Ligne déjà comptée dans ce lieu (par n'importe quel téléphone) : la quantité s'ajoute, le téléphone le signale
            deja = await db.settings.find_one(cle | {"saisies": {"$elemMatch": {"chrono": s["chrono"], "lieu": s["lieu"], "annulee": {"$ne": True}}}}, {"_id": 1})
            s |= {"prenom": prenom, "appareil": corps.appareil, "le": pt.maintenant().isoformat(),
                  "ip": (request.client.host if request.client else None)}
            # $push conditionnel : une saisie renvoyée après une coupure réseau (même uid) n'est JAMAIS comptée deux fois
            r = await db.settings.update_one(cle | {"saisies.uid": {"$ne": s["uid"]}, f"saisies.{pt.MAX_SAISIES - 1}": {"$exists": False}},
                                             {"$push": {"saisies": s}})
            acceptees.append(s["uid"])
            if r.modified_count and deja:
                doublons.append({"uid": s["uid"], "chrono": s["chrono"]})
        return {"acceptees": acceptees, "refusees": refusees, "doublons": doublons}

    @api.post("/public/pointage/{jeton}/annuler", tags=["Pointage par téléphone"])
    async def annuler(jeton: str, corps: Annulation):
        doc = await _par_jeton(jeton, {"_id": 1, "etat": 1, "jeton_expire": 1})
        r = await db.settings.update_one(
            {"_id": doc["_id"], "saisies": {"$elemMatch": {"uid": corps.uid, "appareil": corps.appareil}}},
            {"$set": {"saisies.$.annulee": True, "saisies.$.annulee_le": pt.maintenant().isoformat()}})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Saisie introuvable sur ce téléphone")
        return {"annulee": corps.uid}
