# routes/pointage_telephone.py — Lots 496 et 497 : routes du POINTAGE D'INVENTAIRE PAR TÉLÉPHONE (logique dans backend/pointage_telephone.py).
#
# Lot 497 (28/11/2026) — le propriétaire : « Cela peut être une officine ou n'importe quel lieu de commerce » ; « Pour les collections MongoDB
# tu peux en créer des nouvelles » (nouveau service MongoDB). Donc :
#   - STRUCTURE = client Loois (clé client), officine de SAWALI, ou commerce déclaré ici (clé de suivi « CS-… » générée) ;
#   - LISTE DES PRODUITS = export JSON d'Aizenta, ou CSV (Excel, autre logiciel de caisse) ;
#   - trois collections : pointage_inventaires, pointage_saisies (index unique inventaire + uid), pointage_structures.
#     Les inventaires du lot 496 (fiches `settings` « pointage_inv:… ») sont repris une fois, au premier appel.
#
# Administration (Paramètres → « 📱 Pointage d'inventaire par téléphone », administrateur seul) :
#   GET  /api/admin/pointage-inventaires                 → liste (résumés)
#   GET  /api/admin/pointage-inventaires/structures?q=   → recherche : clients Loois, officines, commerces déclarés (40 au plus)
#   POST /api/admin/pointage-structures                  → déclare un commerce {nom, type, ville} → clé de suivi CS-…
#   POST /api/admin/pointage-inventaires                 → création {structure{source,id}, lieux[], nom_fichier, contenu}
#   GET  /api/admin/pointage-inventaires/{id}            → avancement, alertes, lignes, jeton du QR code
#   POST /api/admin/pointage-inventaires/{id}/jeton | /cloturer | /rouvrir
#   GET  /api/admin/pointage-inventaires/{id}/export?format=json|csv → JSON WinDev (Aizenta) ou CSV (Excel)
# Téléphones (page publique /pointage/<jeton>, sans compte : le jeton du QR code EST l'accès, limité à cet inventaire) :
#   GET  /api/public/pointage/{jeton} ; POST …/saisies (envoi groupé, sans double comptage) ; POST …/annuler (saisie de CE téléphone)
#
# Sécurité (règle 21) : jeton aléatoire long, expirant (3 jours) et révocable ; le prénom est « déclaré, non vérifiable » ; chaque saisie
# garde l'heure du serveur, l'appareil et l'adresse IP ; un appareil n'annule que ses propres saisies.
from __future__ import annotations

import asyncio
import json
import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

import pointage_telephone as pt
from routes.liluvine_partage import est_admin


# Modèles au NIVEAU DU MODULE (FastAPI ne retrouve pas ceux déclarés dans une fonction : 422)
class Lieu(BaseModel):
    nom: str = Field(min_length=1, max_length=40)
    colonne: str = Field(min_length=2, max_length=2)


class RefStructure(BaseModel):
    source: str = Field(pattern="^(loois|officine|commerce)$")
    id: str = Field(min_length=1, max_length=80)


class Creation(BaseModel):
    structure: RefStructure
    lieux: List[Lieu] = Field(default_factory=list)
    nom_fichier: Optional[str] = Field(default=None, max_length=200)
    contenu: str = Field(min_length=2, max_length=15_000_000)      # texte du fichier déposé (JSON d'Aizenta ou CSV)


class Commerce(BaseModel):
    nom: str = Field(min_length=2, max_length=120)
    type: str = Field(min_length=1, max_length=60)
    ville: Optional[str] = Field(default=None, max_length=80)


class Envoi(BaseModel):
    prenom: str = Field(min_length=1, max_length=40)
    appareil: str = Field(min_length=8, max_length=64)
    saisies: List[Dict[str, Any]] = Field(default_factory=list, max_length=200)


class Annulation(BaseModel):
    appareil: str = Field(min_length=8, max_length=64)
    uid: str = Field(min_length=8, max_length=64)


def setup_pointage_telephone_routes(*, db, api, get_current_user) -> None:
    inventaires, saisies, structures_col = db[pt.COL_INVENTAIRES], db[pt.COL_SAISIES], db[pt.COL_STRUCTURES]
    etat_init = {"fait": False}

    async def _preparer() -> None:
        """Une fois par démarrage : index (règle 7) puis reprise des inventaires du lot 496 rangés dans `settings`."""
        if etat_init["fait"]:
            return
        await inventaires.create_index("jeton", sparse=True, name="ix_pointage_jeton")
        await inventaires.create_index([("cree_le", -1)], name="ix_pointage_cree")
        await saisies.create_index([("inventaire_id", 1), ("uid", 1)], unique=True, name="ux_pointage_saisie_uid")
        await saisies.create_index([("inventaire_id", 1), ("chrono", 1), ("lieu", 1)], name="ix_pointage_saisie_ligne")
        await structures_col.create_index("cle_suivi", unique=True, name="ux_pointage_cle_suivi")
        async for ancien in db.settings.find({"_id": {"$regex": "^" + re.escape(pt.PREFIXE_ID)}}):
            anciennes = ancien.pop("saisies", []) or []
            ident = ancien.get("id") or ancien["_id"][len(pt.PREFIXE_ID):]
            ancien.update({"_id": ident, "id": ident, "format": ancien.get("format") or "aizenta"})
            ancien.setdefault("structure", {})["source"] = (ancien.get("structure") or {}).get("source") or "loois"
            await inventaires.replace_one({"_id": ident}, ancien, upsert=True)
            for s in anciennes:
                try:
                    await saisies.insert_one(s | {"inventaire_id": ident})
                except DuplicateKeyError:
                    pass
            await db.settings.delete_one({"_id": ancien.get("_id_origine") or pt.PREFIXE_ID + ident})
        etat_init["fait"] = True

    async def _admin(user: dict = Depends(get_current_user)) -> dict:
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        await _preparer()
        return user

    async def _avec_saisies(doc: dict) -> dict:
        """L'inventaire avec la liste de ses saisies (lecture en bloc, une seule requête : règle 7)."""
        liste = [s async for s in saisies.find({"inventaire_id": doc["id"]}, {"_id": 0})]
        return doc | {"saisies": liste}

    async def _fiche(ident: str, projection: Optional[dict] = None) -> dict:
        doc = await inventaires.find_one({"_id": ident}, projection)
        if not doc:
            raise HTTPException(status_code=404, detail="Inventaire introuvable")
        return doc

    async def _par_jeton(jeton: str, projection: Optional[dict] = None) -> dict:
        """Inventaire ouvert correspondant au jeton du QR code ; 404 sinon (jeton inconnu, expiré ou inventaire clôturé)."""
        await _preparer()
        if not jeton or len(jeton) < 20 or len(jeton) > 64:
            raise HTTPException(status_code=404, detail="QR code inconnu ou expiré")
        doc = await inventaires.find_one({"jeton": jeton}, projection)
        if not pt.jeton_valide(doc):
            raise HTTPException(status_code=404, detail="QR code inconnu, expiré, ou inventaire clôturé")
        return doc

    async def _structure(ref: RefStructure) -> Dict[str, Any]:
        """Structure choisie → {source, id, code (clé de suivi), libelle, type} ; 400 si inconnue."""
        if ref.source == "loois":
            f = await db.loois_cles_clients.find_one({"id": ref.id, "actif": {"$ne": False}}, {"_id": 0, "id": 1, "code": 1, "libelle": 1})
            if f:
                return {"source": "loois", "id": f["id"], "code": f.get("code"), "libelle": f.get("libelle") or f.get("code"), "type": "Client Loois"}
        elif ref.source == "officine":
            f = await db.officines.find_one({"id": ref.id}, {"_id": 0, "id": 1, "name": 1, "city": 1})
            if f:
                return {"source": "officine", "id": f["id"], "code": f["id"][:8].upper(), "libelle": f.get("name"), "type": "Officine"}
        else:
            f = await structures_col.find_one({"id": ref.id}, {"_id": 0})
            if f:
                return {"source": "commerce", "id": f["id"], "code": f["cle_suivi"], "libelle": f["nom"], "type": f.get("type")}
        raise HTTPException(status_code=400, detail="Structure inconnue : choisissez-la dans la liste ou déclarez le commerce")

    # ------------------------------------------------------------------ administration
    @api.get("/admin/pointage-inventaires", tags=["Pointage par téléphone"])
    async def liste(_: dict = Depends(_admin)):
        # Lecture légère (règle 7) : jamais l'export ni le jeton ; nombre de lignes comptées par une seule agrégation
        docs = [d async for d in inventaires.find({}, {"jeton": 0, "export": 0}).sort("cree_le", -1).limit(100)]
        comptes = {r["_id"]: r["n"] async for r in saisies.aggregate([
            {"$match": {"inventaire_id": {"$in": [d["id"] for d in docs]}, "annulee": {"$ne": True}}},
            {"$group": {"_id": {"i": "$inventaire_id", "c": "$chrono"}}},
            {"$group": {"_id": "$_id.i", "n": {"$sum": 1}}}])}
        sortie = []
        for d in docs:
            f = pt.fiche_liste(d | {"saisies": []})
            f["lignes_comptees"] = comptes.get(d["id"], 0)
            f["progression"] = round(100 * f["lignes_comptees"] / f["lignes_total"], 1) if f["lignes_total"] else 0
            sortie.append(f)
        return {"inventaires": sortie, "types_commerce": pt.TYPES_COMMERCE}

    @api.get("/admin/pointage-inventaires/structures", tags=["Pointage par téléphone"])
    async def structures(q: str = "", _: dict = Depends(_admin)):
        # Recherche dans les trois sources EN PARALLÈLE (règle 7), 40 résultats au plus, sans casse ni accents côté Mongo (regex insensible)
        motif = {"$regex": re.escape(q.strip()[:60]), "$options": "i"} if q.strip() else None
        f_loois = {"actif": {"$ne": False}} | ({"$or": [{"libelle": motif}, {"code": motif}, {"client_nom": motif}]} if motif else {})
        f_off = {"$or": [{"name": motif}, {"city": motif}]} if motif else {}
        f_com = {"$or": [{"nom": motif}, {"cle_suivi": motif}, {"ville": motif}, {"type": motif}]} if motif else {}

        async def lire(col, filtre, proj, n):
            return [x async for x in col.find(filtre, proj).limit(n)]
        loois, officines, commerces = await asyncio.gather(
            lire(db.loois_cles_clients, f_loois, {"_id": 0, "id": 1, "code": 1, "libelle": 1}, 15),
            lire(db.officines, f_off, {"_id": 0, "id": 1, "name": 1, "city": 1}, 15),
            lire(structures_col, f_com, {"_id": 0}, 15))
        resultats = [{"source": "commerce", "id": c["id"], "libelle": c["nom"], "code": c["cle_suivi"], "type": c.get("type"), "ville": c.get("ville")} for c in commerces] \
            + [{"source": "loois", "id": c["id"], "libelle": c.get("libelle") or c.get("code"), "code": c.get("code"), "type": "Client Loois"} for c in loois] \
            + [{"source": "officine", "id": o["id"], "libelle": o.get("name"), "code": o["id"][:8].upper(), "type": "Officine", "ville": o.get("city")} for o in officines]
        return {"structures": resultats[:40], "types_commerce": pt.TYPES_COMMERCE}

    @api.post("/admin/pointage-structures", tags=["Pointage par téléphone"])
    async def declarer_commerce(corps: Commerce, user: dict = Depends(_admin)):
        try:
            propre = pt.valider_commerce(corps.model_dump())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        for _ in range(5):                       # clé de suivi unique (index unique : nouvel essai en cas de collision)
            fiche = propre | {"id": uuid.uuid4().hex[:12], "cle_suivi": pt.generer_cle_suivi(),
                              "cree_le": pt.maintenant().isoformat(), "cree_par": user.get("email")}
            try:
                await structures_col.insert_one(dict(fiche))
                return {"source": "commerce", "id": fiche["id"], "libelle": fiche["nom"], "code": fiche["cle_suivi"],
                        "type": fiche["type"], "ville": fiche["ville"]}
            except DuplicateKeyError:
                continue
        raise HTTPException(status_code=500, detail="Clé de suivi impossible à générer : réessayez")

    @api.post("/admin/pointage-inventaires", tags=["Pointage par téléphone"])
    async def creer(corps: Creation, user: dict = Depends(_admin)):
        structure = await _structure(corps.structure)
        try:
            export, format_ = pt.lire_liste_produits(corps.contenu, corps.nom_fichier)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Liste des produits refusée : {e}")
        compteur = await db.settings.find_one_and_update({"_id": pt.ID_COMPTEUR}, {"$inc": {"valeur": 1}},
                                                         upsert=True, return_document=True)
        try:
            doc = pt.creer_inventaire(ident=uuid.uuid4().hex[:12], numero=pt.numero_suivant(compteur.get("valeur") or 1),
                                      structure=structure, lieux=[l.model_dump() for l in corps.lieux], export=export,
                                      nom_fichier=corps.nom_fichier, par=user.get("email") or user.get("name") or "admin", format_=format_)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        await inventaires.insert_one(dict(doc))
        return pt.fiche_liste(doc | {"saisies": []})

    @api.get("/admin/pointage-inventaires/{ident}", tags=["Pointage par téléphone"])
    async def detail(ident: str, _: dict = Depends(_admin)):
        doc = await _avec_saisies(await _fiche(ident))
        etat = await asyncio.to_thread(pt.etat, doc)            # calcul en mémoire, hors de la boucle d'événements
        return pt.fiche_liste(doc) | {"jeton": doc.get("jeton") if doc.get("etat") == "ouvert" else None,
                                      "jeton_valide": pt.jeton_valide(doc), "nom_fichier": doc.get("nom_fichier")} | etat

    @api.post("/admin/pointage-inventaires/{ident}/jeton", tags=["Pointage par téléphone"])
    async def nouveau_jeton(ident: str, _: dict = Depends(_admin)):
        doc = await _fiche(ident, {"etat": 1})
        if doc.get("etat") != "ouvert":
            raise HTTPException(status_code=409, detail="Inventaire clôturé : le rouvrir d'abord")
        jeton, expire = pt.nouveau_jeton()
        await inventaires.update_one({"_id": ident}, {"$set": {"jeton": jeton, "jeton_expire": expire}})
        return {"jeton": jeton, "jeton_expire": expire}

    @api.post("/admin/pointage-inventaires/{ident}/cloturer", tags=["Pointage par téléphone"])
    async def cloturer(ident: str, user: dict = Depends(_admin)):
        await _fiche(ident, {"_id": 1})
        await inventaires.update_one({"_id": ident}, {"$set": {"etat": "cloture", "jeton": None,
                                                               "cloture_le": pt.maintenant().isoformat(), "cloture_par": user.get("email")}})
        return {"etat": "cloture"}

    @api.post("/admin/pointage-inventaires/{ident}/rouvrir", tags=["Pointage par téléphone"])
    async def rouvrir(ident: str, _: dict = Depends(_admin)):
        await _fiche(ident, {"_id": 1})
        jeton, expire = pt.nouveau_jeton()
        await inventaires.update_one({"_id": ident}, {"$set": {"etat": "ouvert", "jeton": jeton, "jeton_expire": expire}})
        return {"etat": "ouvert", "jeton": jeton, "jeton_expire": expire}

    @api.get("/admin/pointage-inventaires/{ident}/export", tags=["Pointage par téléphone"])
    async def export(ident: str, format: str = "json", _: dict = Depends(_admin)):
        doc = await _avec_saisies(await _fiche(ident))
        if format == "csv":
            contenu, type_ = await asyncio.to_thread(pt.exporter_csv, doc), "text/csv; charset=utf-8"
        elif doc.get("format", "aizenta") == "aizenta":
            sortie = await asyncio.to_thread(pt.exporter, doc)
            # Même style que l'export WinDev : ASCII pur (accents en é), ordre des champs conservé
            contenu, type_ = json.dumps(sortie, ensure_ascii=True, separators=(", ", ":")).encode("ascii"), "application/json"
        else:
            raise HTTPException(status_code=400, detail="Liste importée en CSV : exportez en CSV (format=csv)")
        nom = pt.nom_export(doc, "csv" if format == "csv" else "json").encode("ascii", "replace").decode().replace("?", "_")
        return Response(content=contenu, media_type=type_, headers={"Content-Disposition": f'attachment; filename="{nom}"'})

    # ------------------------------------------------------------------ téléphones (QR code)
    @api.get("/public/pointage/{jeton}", tags=["Pointage par téléphone"])
    async def ouvrir(jeton: str):
        doc = await _par_jeton(jeton)
        lignes = [{"c": x["Chrono"], "l": x.get("Libellé"), "m": x.get("Mesure")}
                  for x in (doc.get("export") or {}).get(pt.CLE_TABLE) or []]
        return {"numero": doc.get("numero"), "code_inv": doc.get("code_inv"),
                "structure": (doc.get("structure") or {}).get("libelle") or (doc.get("structure") or {}).get("code"),
                "lieux": [{"id": l["id"], "nom": l["nom"]} for l in doc.get("lieux") or []], "lignes": lignes,
                "jeton_expire": doc.get("jeton_expire")}

    @api.post("/public/pointage/{jeton}/saisies", tags=["Pointage par téléphone"])
    async def saisir(jeton: str, corps: Envoi, request: Request):
        doc = await _par_jeton(jeton, {"id": 1, "export." + pt.CLE_TABLE + ".Chrono": 1, "lieux": 1, "etat": 1, "jeton_expire": 1})
        try:
            prenom = pt.nettoyer_prenom(corps.prenom)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if await saisies.count_documents({"inventaire_id": doc["id"]}) >= pt.MAX_SAISIES:
            raise HTTPException(status_code=409, detail="Nombre maximal de saisies atteint pour cet inventaire")
        chronos = {x["Chrono"] for x in (doc.get("export") or {}).get(pt.CLE_TABLE) or []}
        acceptees, refusees, doublons = [], [], []
        for brute in corps.saisies:
            try:
                s = pt.nettoyer_saisie(brute, lieux=doc.get("lieux") or [], chronos=chronos)
            except ValueError as e:
                refusees.append({"uid": str((brute or {}).get("uid") or ""), "erreur": str(e)})
                continue
            # Ligne déjà comptée dans ce lieu (par n'importe quel téléphone) : la quantité s'ajoute, le téléphone le signale
            deja = await saisies.find_one({"inventaire_id": doc["id"], "chrono": s["chrono"], "lieu": s["lieu"], "annulee": {"$ne": True}}, {"_id": 1})
            s |= {"inventaire_id": doc["id"], "prenom": prenom, "appareil": corps.appareil, "le": pt.maintenant().isoformat(),
                  "ip": (request.client.host if request.client else None)}
            try:
                await saisies.insert_one(s)
                if deja:
                    doublons.append({"uid": s["uid"], "chrono": s["chrono"]})
            except DuplicateKeyError:
                pass                              # même uid renvoyé après une coupure réseau : déjà compté, jamais deux fois
            acceptees.append(s["uid"])
        return {"acceptees": acceptees, "refusees": refusees, "doublons": doublons}

    @api.post("/public/pointage/{jeton}/annuler", tags=["Pointage par téléphone"])
    async def annuler(jeton: str, corps: Annulation):
        doc = await _par_jeton(jeton, {"id": 1, "etat": 1, "jeton_expire": 1})
        r = await saisies.update_one({"inventaire_id": doc["id"], "uid": corps.uid, "appareil": corps.appareil},
                                     {"$set": {"annulee": True, "annulee_le": pt.maintenant().isoformat()}})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Saisie introuvable sur ce téléphone")
        return {"annulee": corps.uid}
