# routes/pointage_telephone.py — Lots 496 à 498 : routes du POINTAGE D'INVENTAIRE PAR TÉLÉPHONE (logique dans backend/pointage_telephone.py).
#
# Lot 497 : tout lieu de commerce (client Loois, officine, commerce déclaré), liste des produits en JSON d'Aizenta ou CSV, collections dédiées.
# Lot 498 (28/11/2026) — le propriétaire : « chaque commerce même nouveau doit avoir sa clé pour le pointage inventaires. Les officines déjà connues
# de SAWALI doivent avoir aussi une clé générée et un mot de passe pour être autorisées à faire le pointage » ; choix : « Les deux » (espace du
# responsable ET mot de passe sur chaque téléphone), clés des commerces déjà connus générées « une à une, par vous ».
#   - pointage_acces : une fiche par commerce autorisé {id, structure{source,id,libelle,type,code}, cle « CP-… », mdp_hash (bcrypt), version, actif,
#     echecs, bloque_jusqu, derniere_connexion}. Sans clé ACTIVE : ni création d'inventaire, ni pointage.
#   - ESPACE POINTAGE (/pointage-espace) : le responsable se connecte avec clé + mot de passe → jeton signé (12 h, en-tête X-Pointage-Jeton) ;
#     il gère SES inventaires (création, QR code, suivi, clôture, export), jamais ceux d'un autre commerce.
#   - TÉLÉPHONE : après le QR code, le mot de passe du commerce est demandé → jeton du téléphone (en-tête X-Pointage-Telephone), lié à
#     l'inventaire et à la version du mot de passe (un nouveau mot de passe ou une clé révoquée coupe aussitôt les téléphones).
#   - Essais : 5 mots de passe faux → commerce bloqué 15 min ; 20 échecs par adresse IP en 15 min → IP refusée (HTTP 429).
#
# Lot 499 : chaque commerce précise son PAYS et la LANGUE de l'interface (français ou anglais) à sa création (déclaration, ou génération de
#   sa clé pour un commerce déjà connu ; modifiables ensuite) ; les fichiers fusionnés par Loois mobile gardent le prénom de chaque saisie.
# Lot 500 : SOUSCRIPTION AU POINTAGE (semaine, mois, année, illimité) par commerce, vérifiée (référence du paiement mobile rapprochée du SMS reçu,
#   ou validée par l'administrateur) ; sans souscription valide : pas de nouvel inventaire dans l'Espace, pas de téléchargement par un téléphone,
#   pas de nouvelle saisie (une saisie comptée PENDANT une période payée peut encore être envoyée après l'expiration). Collection pointage_souscriptions.
# Administration (Paramètres → « 📱 Pointage d'inventaire par téléphone », administrateur seul) : /api/admin/pointage-…
# Espace du responsable : /api/pointage-espace/… ; Téléphones : /api/public/pointage/{jeton}/…
from __future__ import annotations

import asyncio
import json
import os
import re
import time
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
    structure: Optional[RefStructure] = None                         # imposée par le jeton dans l'Espace pointage
    lieux: List[Lieu] = Field(default_factory=list)
    nom_fichier: Optional[str] = Field(default=None, max_length=200)
    contenu: str = Field(min_length=2, max_length=15_000_000)      # texte du fichier déposé (JSON d'Aizenta ou CSV)


class Commerce(BaseModel):
    nom: str = Field(min_length=2, max_length=120)
    type: str = Field(min_length=1, max_length=60)
    ville: Optional[str] = Field(default=None, max_length=80)
    pays: Optional[str] = Field(default=None, max_length=60)
    langue: str = Field(default="fr", pattern="^(fr|en)$")


class GenerationAcces(RefStructure):
    pays: Optional[str] = Field(default=None, max_length=60)
    langue: str = Field(default="fr", pattern="^(fr|en)$")


class PaysLangue(BaseModel):
    pays: Optional[str] = Field(default=None, max_length=60)
    langue: str = Field(default="fr", pattern="^(fr|en)$")


class Connexion(BaseModel):
    cle: str = Field(min_length=3, max_length=20)
    mot_de_passe: str = Field(min_length=4, max_length=40)


class MotDePasse(BaseModel):
    mot_de_passe: str = Field(min_length=4, max_length=40)


class Envoi(BaseModel):
    prenom: str = Field(min_length=1, max_length=40)
    appareil: str = Field(min_length=8, max_length=64)
    saisies: List[Dict[str, Any]] = Field(default_factory=list, max_length=200)


class Tarifs(BaseModel):
    tarifs: Dict[str, Any] = Field(default_factory=dict)
    codes: Dict[str, Any] = Field(default_factory=dict)
    devise: Optional[str] = Field(default="FCFA", max_length=10)


class DemandeSouscription(BaseModel):
    formule: str = Field(pattern="^(semaine|mois|annee|illimite)$")
    operateur: str = Field(pattern="^(orange|moov|telecel)$")
    reference: str = Field(min_length=4, max_length=60)


class SouscriptionManuelle(BaseModel):
    acces_id: str = Field(min_length=4, max_length=40)
    formule: str = Field(pattern="^(semaine|mois|annee|illimite)$")
    note: Optional[str] = Field(default=None, max_length=200)


class Annulation(BaseModel):
    appareil: str = Field(min_length=8, max_length=64)
    uid: str = Field(min_length=8, max_length=64)


def setup_pointage_telephone_routes(*, db, api, get_current_user) -> None:
    inventaires, saisies, structures_col, acces_col = (db[pt.COL_INVENTAIRES], db[pt.COL_SAISIES], db[pt.COL_STRUCTURES], db[pt.COL_ACCES])
    souscriptions_col = db[pt.COL_SOUSCRIPTIONS]
    etat_init = {"fait": False}
    echecs_ip: Dict[str, List[float]] = {}          # adresse IP → instants des mots de passe faux (15 dernières minutes)

    def _secret() -> str:
        s = os.environ.get("JWT_SECRET") or ""
        if not s:
            raise HTTPException(status_code=503, detail="Pointage indisponible : secret des sessions absent sur le serveur")
        return s

    async def _preparer() -> None:
        """Une fois par démarrage : index (règle 7) puis reprise des inventaires du lot 496 rangés dans `settings`."""
        if etat_init["fait"]:
            return
        await inventaires.create_index("jeton", sparse=True, name="ix_pointage_jeton")
        await inventaires.create_index([("structure.source", 1), ("structure.id", 1), ("cree_le", -1)], name="ix_pointage_structure")
        await saisies.create_index([("inventaire_id", 1), ("uid", 1)], unique=True, name="ux_pointage_saisie_uid")
        await saisies.create_index([("inventaire_id", 1), ("chrono", 1), ("lieu", 1)], name="ix_pointage_saisie_ligne")
        await structures_col.create_index("cle_suivi", unique=True, name="ux_pointage_cle_suivi")
        await acces_col.create_index("cle", unique=True, name="ux_pointage_acces_cle")
        await acces_col.create_index([("structure.source", 1), ("structure.id", 1)], unique=True, name="ux_pointage_acces_structure")
        await souscriptions_col.create_index([("acces_id", 1), ("demandee_le", -1)], name="ix_pointage_souscription_commerce")
        await souscriptions_col.create_index("sms_k", unique=True, sparse=True, name="ux_pointage_souscription_sms")
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
            await db.settings.delete_one({"_id": pt.PREFIXE_ID + ident})
        etat_init["fait"] = True

    async def _admin(user: dict = Depends(get_current_user)) -> dict:
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        await _preparer()
        return user

    # ------------------------------------------------------------------ outils communs
    def _ip(request: Request) -> str:
        return (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or (request.client.host if request.client else "?")

    def _ip_bloquee(ip: str) -> bool:
        maintenant = time.time()
        echecs_ip[ip] = [t for t in echecs_ip.get(ip, []) if maintenant - t < pt.BLOCAGE_MIN * 60]
        return len(echecs_ip[ip]) >= 20

    async def _verifier_mot_de_passe(acces: Optional[dict], mot_de_passe: str, request: Request) -> dict:
        """Contrôle du mot de passe d'un commerce (Espace pointage ou téléphone). Message volontairement identique si la clé est inconnue."""
        ip = _ip(request)
        if _ip_bloquee(ip):
            raise HTTPException(status_code=429, detail=f"Trop d'essais depuis cet appareil : réessayez dans {pt.BLOCAGE_MIN} minutes")
        if acces and pt.est_bloque(acces):
            raise HTTPException(status_code=429, detail=f"Trop de mots de passe faux pour ce commerce : réessayez dans {pt.BLOCAGE_MIN} minutes")
        bon = bool(acces and acces.get("actif") and acces.get("mdp_hash")) and \
            await asyncio.to_thread(pt.verifier_mot_de_passe, mot_de_passe, acces["mdp_hash"])
        if not bon:
            echecs_ip.setdefault(ip, []).append(time.time())
            if acces:
                await acces_col.update_one({"id": acces["id"]}, {"$set": pt.apres_echec(acces)})
            raise HTTPException(status_code=401, detail="Clé ou mot de passe incorrect, ou commerce non autorisé au pointage")
        await acces_col.update_one({"id": acces["id"]}, {"$set": {"echecs": 0, "bloque_jusqu": None, "derniere_connexion": pt.maintenant().isoformat()}})
        return acces

    async def _acces_de(structure: dict) -> Optional[dict]:
        return await acces_col.find_one({"structure.source": structure.get("source"), "structure.id": structure.get("id")}, {"_id": 0})

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

    async def _creer_acces(structure: dict, par: str, pays_langue: Optional[dict] = None) -> Dict[str, Any]:
        """Génère la clé de pointage et le mot de passe d'un commerce ; le mot de passe n'est renvoyé qu'ICI (jamais relisible)."""
        mdp = pt.generer_mot_de_passe()
        empreinte = await asyncio.to_thread(pt.hacher_mot_de_passe, mdp)
        for _ in range(5):
            fiche = {"id": uuid.uuid4().hex[:12], "structure": structure, "cle": pt.generer_cle_pointage(), "mdp_hash": empreinte,
                     "version": 1, "actif": True, "echecs": 0, "cree_le": pt.maintenant().isoformat(), "cree_par": par}
            fiche |= pays_langue or pt.valider_pays_langue({})
            try:
                await acces_col.insert_one(dict(fiche))
                return {"id": fiche["id"], "cle": fiche["cle"], "mot_de_passe": mdp, "structure": structure, "actif": True,
                        "pays": fiche["pays"], "langue": fiche["langue"]}
            except DuplicateKeyError as e:
                if "structure" in str(e):
                    raise HTTPException(status_code=409, detail="Ce commerce a déjà sa clé de pointage (générez un nouveau mot de passe)")
        raise HTTPException(status_code=500, detail="Clé de pointage impossible à générer : réessayez")

    def _acces_public(a: dict) -> dict:
        return {k: a.get(k) for k in ("id", "cle", "structure", "actif", "cree_le", "derniere_connexion", "bloque_jusqu", "pays")} | {"langue": a.get("langue") or "fr"}

    async def _avec_saisies(doc: dict) -> dict:
        """L'inventaire avec la liste de ses saisies (lecture en bloc, une seule requête : règle 7)."""
        liste = [s async for s in saisies.find({"inventaire_id": doc["id"]}, {"_id": 0})]
        return doc | {"saisies": liste}

    async def _fiche(ident: str, structure: Optional[dict] = None, projection: Optional[dict] = None) -> dict:
        """Inventaire par son id ; dans l'Espace pointage, seulement s'il appartient au commerce connecté (404 sinon)."""
        filtre = {"_id": ident}
        if structure:
            filtre |= {"structure.source": structure["source"], "structure.id": structure["id"]}
        doc = await inventaires.find_one(filtre, projection)
        if not doc:
            raise HTTPException(status_code=404, detail="Inventaire introuvable")
        return doc

    # ------------------------------------------------------------------ souscriptions (lot 500)
    async def _souscriptions(acces_id: Optional[str]) -> List[dict]:
        if not acces_id:
            return []
        return [x async for x in souscriptions_col.find({"acces_id": acces_id}, {"_id": 0}).sort("demandee_le", -1).limit(200)]

    async def _etat_souscription(acces: Optional[dict]) -> Dict[str, Any]:
        return pt.etat_souscription(await _souscriptions((acces or {}).get("id")))

    async def _exiger_souscription(acces: Optional[dict]) -> None:
        """402 si le commerce n'a pas de souscription au pointage valide (message clair, dans la langue du commerce)."""
        if not (await _etat_souscription(acces))["valide"]:
            en = (acces or {}).get("langue") == "en"
            raise HTTPException(status_code=402, detail="Stock count subscription expired or not yet verified: renew it in the Count area."
                                if en else "Souscription au pointage expirée ou pas encore vérifiée : renouvelez-la dans l'Espace pointage.")

    async def _tarifs() -> Dict[str, Any]:
        f = await db.settings.find_one({"_id": pt.ID_TARIFS}, {"_id": 0}) or {}
        return {"tarifs": f.get("tarifs") or {}, "codes": f.get("codes") or {}, "devise": f.get("devise") or "FCFA"}

    async def _transactions_recentes() -> List[dict]:
        """Paiements reçus (SMS lus par Concentration, module Transactions SMS) du mois en cours et du mois précédent."""
        t = pt.maintenant()
        mois = {t.strftime("%Y-%m"), (t.replace(day=1) - pt.timedelta(days=1)).strftime("%Y-%m")}
        sortie: List[dict] = []
        async for d in db.settings.find({"_id": {"$in": [f"transactions-sms:{m}" for m in mois]}}, {"items": 1}):
            sortie += d.get("items") or []
        return sortie

    async def _verifier_automatiquement(sous: dict) -> dict:
        """Cherche le SMS de paiement de cette demande ; s'il existe : souscription vérifiée, période enchaînée. Renvoie la fiche à jour."""
        utilisees = {x["sms_k"] async for x in souscriptions_col.find({"sms_k": {"$ne": None}}, {"_id": 0, "sms_k": 1})}
        p = pt.rapprocher(sous["reference"], sous["montant"], await _transactions_recentes(), utilisees)
        if not p:
            return sous
        return await _activer(sous, par="SMS de paiement (automatique)", sms_k=p.get("k"))

    async def _activer(sous: dict, *, par: str, sms_k: Optional[str] = None) -> dict:
        debut, fin = pt.periode_suivante(await _souscriptions(sous["acces_id"]), sous["formule"])
        maj = {"statut": "verifiee", "debut": debut, "fin": fin, "verifiee_le": pt.maintenant().isoformat(), "verifiee_par": par}
        if sms_k:
            maj["sms_k"] = sms_k
        try:
            await souscriptions_col.update_one({"id": sous["id"], "statut": "en_attente"}, {"$set": maj})
        except DuplicateKeyError:                          # même SMS déjà utilisé par une autre demande (course) : reste en attente
            return sous
        return await souscriptions_col.find_one({"id": sous["id"]}, {"_id": 0})

    def _sequences(tarifs: dict, formule: Optional[str] = None) -> List[dict]:
        """Pour chaque opérateur dont le code marchand est réglé : séquence USSD et lien « tel: » de chaque formule proposée."""
        sortie = []
        for op, nom in pt.OPERATEURS.items():
            code = tarifs["codes"].get(op)
            if not code:
                continue
            par_formule = {f: {"montant": m, "sequence": pt.sequence_ussd(op, code, m), "lien": pt.lien_ussd(pt.sequence_ussd(op, code, m))}
                           for f, m in tarifs["tarifs"].items() if m and (formule is None or f == formule)}
            sortie.append({"id": op, "nom": nom, "formules": par_formule})
        return sortie

    # ------------------------------------------------------------------ opérations communes (administrateur et Espace pointage)
    async def _liste(filtre: dict) -> dict:
        docs = [d async for d in inventaires.find(filtre, {"jeton": 0, "export": 0}).sort("cree_le", -1).limit(100)]
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
        return {"inventaires": sortie, "types_commerce": pt.TYPES_COMMERCE, "pays": pt.PAYS}

    async def _creer(structure: dict, corps: Creation, par: str) -> dict:
        acces = await _acces_de(structure)
        if not acces or not acces.get("actif"):
            raise HTTPException(status_code=400, detail="Ce commerce n'a pas de clé de pointage active : générez-la d'abord")
        try:
            export, format_ = pt.lire_liste_produits(corps.contenu, corps.nom_fichier)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Liste des produits refusée : {e}")
        compteur = await db.settings.find_one_and_update({"_id": pt.ID_COMPTEUR}, {"$inc": {"valeur": 1}}, upsert=True, return_document=True)
        try:
            doc = pt.creer_inventaire(ident=uuid.uuid4().hex[:12], numero=pt.numero_suivant(compteur.get("valeur") or 1),
                                      structure=structure, lieux=[l.model_dump() for l in corps.lieux], export=export,
                                      nom_fichier=corps.nom_fichier, par=par, format_=format_, langue=acces.get("langue") or "fr")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        await inventaires.insert_one(dict(doc))
        return pt.fiche_liste(doc | {"saisies": []})

    async def _detail(doc: dict) -> dict:
        doc = await _avec_saisies(doc)
        etat = await asyncio.to_thread(pt.etat, doc)            # calcul en mémoire, hors de la boucle d'événements
        acces = await _acces_de(doc.get("structure") or {})
        return pt.fiche_liste(doc) | {"jeton": doc.get("jeton") if doc.get("etat") == "ouvert" else None, "jeton_valide": pt.jeton_valide(doc),
                                      "nom_fichier": doc.get("nom_fichier"), "cle_pointage": (acces or {}).get("cle")} | etat

    async def _nouveau_jeton(doc: dict) -> dict:
        if doc.get("etat") != "ouvert":
            raise HTTPException(status_code=409, detail="Inventaire clôturé : le rouvrir d'abord")
        jeton, expire = pt.nouveau_jeton()
        await inventaires.update_one({"_id": doc["id"]}, {"$set": {"jeton": jeton, "jeton_expire": expire}})
        return {"jeton": jeton, "jeton_expire": expire}

    async def _cloturer(doc: dict, par: str) -> dict:
        await inventaires.update_one({"_id": doc["id"]}, {"$set": {"etat": "cloture", "jeton": None, "cloture_le": pt.maintenant().isoformat(), "cloture_par": par}})
        return {"etat": "cloture"}

    async def _rouvrir(doc: dict) -> dict:
        jeton, expire = pt.nouveau_jeton()
        await inventaires.update_one({"_id": doc["id"]}, {"$set": {"etat": "ouvert", "jeton": jeton, "jeton_expire": expire}})
        return {"etat": "ouvert", "jeton": jeton, "jeton_expire": expire}

    async def _export(doc: dict, format: str) -> Response:
        doc = await _avec_saisies(doc)
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

    # ------------------------------------------------------------------ administration
    @api.get("/admin/pointage-inventaires", tags=["Pointage par téléphone"])
    async def liste(_: dict = Depends(_admin)):
        return await _liste({})

    @api.get("/admin/pointage-inventaires/structures", tags=["Pointage par téléphone"])
    async def structures(q: str = "", _: dict = Depends(_admin)):
        # Recherche dans les trois sources EN PARALLÈLE (règle 7), 40 résultats au plus ; chaque résultat dit s'il a sa clé de pointage
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
        resultats = resultats[:40]
        # Clé de pointage de chaque résultat : UNE lecture en bloc (pas de boucle N+1, règle 7)
        cles = {(a["structure"]["source"], a["structure"]["id"]): a async for a in acces_col.find(
            {"structure.id": {"$in": [r["id"] for r in resultats]}}, {"_id": 0, "mdp_hash": 0})}
        for r in resultats:
            a = cles.get((r["source"], r["id"]))
            r["acces"] = {"cle": a["cle"], "actif": a.get("actif")} if a else None
        return {"structures": resultats, "types_commerce": pt.TYPES_COMMERCE, "pays": pt.PAYS}

    @api.post("/admin/pointage-structures", tags=["Pointage par téléphone"])
    async def declarer_commerce(corps: Commerce, user: dict = Depends(_admin)):
        """Déclare un commerce ET lui génère aussitôt sa clé de pointage et son mot de passe (montré une seule fois)."""
        try:
            propre = pt.valider_commerce(corps.model_dump())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        for _ in range(5):                       # clé de suivi unique (index unique : nouvel essai en cas de collision)
            fiche = propre | {"id": uuid.uuid4().hex[:12], "cle_suivi": pt.generer_cle_suivi(),
                              "cree_le": pt.maintenant().isoformat(), "cree_par": user.get("email")}
            try:
                await structures_col.insert_one(dict(fiche))
                break
            except DuplicateKeyError:
                continue
        else:
            raise HTTPException(status_code=500, detail="Clé de suivi impossible à générer : réessayez")
        structure = {"source": "commerce", "id": fiche["id"], "code": fiche["cle_suivi"], "libelle": fiche["nom"], "type": fiche["type"]}
        acces = await _creer_acces(structure, user.get("email") or "admin", {"pays": fiche["pays"], "langue": fiche["langue"]})
        return structure | {"ville": fiche["ville"], "pays": fiche["pays"], "langue": fiche["langue"],
                            "acces": {"id": acces["id"], "cle": acces["cle"], "actif": True}, "mot_de_passe": acces["mot_de_passe"]}

    @api.get("/admin/pointage-acces", tags=["Pointage par téléphone"])
    async def liste_acces(_: dict = Depends(_admin)):
        liste = [_acces_public(a) async for a in acces_col.find({}, {"_id": 0, "mdp_hash": 0}).sort("cree_le", -1).limit(500)]
        # État de la souscription de chaque commerce : UNE lecture en bloc (règle 7)
        par_acces: Dict[str, List[dict]] = {}
        async for x in souscriptions_col.find({"acces_id": {"$in": [a["id"] for a in liste]}}, {"_id": 0}):
            par_acces.setdefault(x["acces_id"], []).append(x)
        for a in liste:
            a["souscription"] = pt.etat_souscription(par_acces.get(a["id"], []))
        return {"acces": liste}

    # ---------------- souscriptions : tarifs, demandes, validation (lot 500)
    @api.get("/admin/pointage-tarifs", tags=["Pointage par téléphone"])
    async def lire_tarifs(_: dict = Depends(_admin)):
        return await _tarifs() | {"formules": pt.LIBELLES_FORMULES, "operateurs": pt.OPERATEURS}

    @api.put("/admin/pointage-tarifs", tags=["Pointage par téléphone"])
    async def ecrire_tarifs(corps: Tarifs, _: dict = Depends(_admin)):
        try:
            propre = pt.valider_tarifs(corps.model_dump())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        await db.settings.update_one({"_id": pt.ID_TARIFS}, {"$set": propre}, upsert=True)
        return propre

    @api.get("/admin/pointage-souscriptions", tags=["Pointage par téléphone"])
    async def liste_souscriptions(_: dict = Depends(_admin)):
        liste = [x async for x in souscriptions_col.find({}, {"_id": 0}).sort("demandee_le", -1).limit(300)]
        noms = {a["id"]: a async for a in acces_col.find({"id": {"$in": list({x["acces_id"] for x in liste})}}, {"_id": 0, "id": 1, "cle": 1, "structure": 1})}
        for x in liste:
            a = noms.get(x["acces_id"]) or {}
            x["commerce"] = (a.get("structure") or {}).get("libelle")
            x["cle"] = a.get("cle")
        liste.sort(key=lambda x: (x.get("statut") != "en_attente", ""))      # demandes à vérifier EN HAUT (règle 8)
        return {"souscriptions": liste, "formules": pt.LIBELLES_FORMULES}

    @api.post("/admin/pointage-souscriptions", tags=["Pointage par téléphone"])
    async def souscription_manuelle(corps: SouscriptionManuelle, user: dict = Depends(_admin)):
        """Souscription enregistrée par l'administrateur (paiement en espèces, virement…) : vérifiée aussitôt."""
        if not await acces_col.find_one({"id": corps.acces_id}, {"_id": 1}):
            raise HTTPException(status_code=404, detail="Commerce introuvable")
        tarifs = await _tarifs()
        sous = {"id": uuid.uuid4().hex[:12], "acces_id": corps.acces_id, "formule": corps.formule, "montant": tarifs["tarifs"].get(corps.formule) or 0,
                "devise": tarifs["devise"], "operateur": None, "reference": (corps.note or "Enregistrée par l'administrateur")[:60],
                "statut": "en_attente", "demandee_le": pt.maintenant().isoformat(), "demandee_par": user.get("email")}
        await souscriptions_col.insert_one(dict(sous))
        return await _activer(sous, par=user.get("email") or "administrateur")

    @api.post("/admin/pointage-souscriptions/{ident}/{action}", tags=["Pointage par téléphone"])
    async def decider_souscription(ident: str, action: str, user: dict = Depends(_admin)):
        sous = await souscriptions_col.find_one({"id": ident}, {"_id": 0})
        if not sous:
            raise HTTPException(status_code=404, detail="Souscription introuvable")
        if sous.get("statut") != "en_attente":
            raise HTTPException(status_code=409, detail="Cette demande a déjà été traitée")
        if action == "valider":
            return await _activer(sous, par=user.get("email") or "administrateur")
        if action == "refuser":
            await souscriptions_col.update_one({"id": ident}, {"$set": {"statut": "refusee", "refusee_le": pt.maintenant().isoformat(), "refusee_par": user.get("email")}})
            return {"statut": "refusee"}
        if action == "verifier":                          # relance du rapprochement avec les SMS reçus depuis la demande
            return await _verifier_automatiquement(sous)
        raise HTTPException(status_code=404, detail="Action inconnue")

    @api.post("/admin/pointage-acces", tags=["Pointage par téléphone"])
    async def generer_acces(corps: GenerationAcces, user: dict = Depends(_admin)):
        """Génère, une à une (choix du propriétaire), la clé de pointage d'un commerce déjà connu (officine, client Loois…), avec son pays et sa langue."""
        try:
            pays_langue = pt.valider_pays_langue(corps.model_dump())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return await _creer_acces(await _structure(RefStructure(source=corps.source, id=corps.id)), user.get("email") or "admin", pays_langue)

    @api.put("/admin/pointage-acces/{ident}", tags=["Pointage par téléphone"])
    async def modifier_pays_langue(ident: str, corps: PaysLangue, _: dict = Depends(_admin)):
        """Pays et langue d'un commerce autorisé (les inventaires suivants prennent la nouvelle langue)."""
        try:
            propre = pt.valider_pays_langue(corps.model_dump())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        r = await acces_col.update_one({"id": ident}, {"$set": propre})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Clé de pointage introuvable")
        a = await acces_col.find_one({"id": ident}, {"_id": 0, "mdp_hash": 0})
        if a["structure"].get("source") == "commerce":          # commerce déclaré ici : sa fiche garde aussi le pays et la langue
            await structures_col.update_one({"id": a["structure"]["id"]}, {"$set": propre})
        return _acces_public(a)

    @api.post("/admin/pointage-acces/{ident}/mot-de-passe", tags=["Pointage par téléphone"])
    async def nouveau_mot_de_passe(ident: str, _: dict = Depends(_admin)):
        """Nouveau mot de passe (l'ancien ne marche plus, les téléphones connectés doivent le ressaisir)."""
        mdp = pt.generer_mot_de_passe()
        r = await acces_col.update_one({"id": ident}, {"$set": {"mdp_hash": await asyncio.to_thread(pt.hacher_mot_de_passe, mdp), "echecs": 0, "bloque_jusqu": None},
                                                       "$inc": {"version": 1}})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Clé de pointage introuvable")
        a = await acces_col.find_one({"id": ident}, {"_id": 0, "mdp_hash": 0})
        return _acces_public(a) | {"mot_de_passe": mdp}

    @api.post("/admin/pointage-acces/{ident}/{action}", tags=["Pointage par téléphone"])
    async def basculer_acces(ident: str, action: str, _: dict = Depends(_admin)):
        if action not in ("revoquer", "reactiver"):
            raise HTTPException(status_code=404, detail="Action inconnue")
        r = await acces_col.update_one({"id": ident}, {"$set": {"actif": action == "reactiver"}, "$inc": {"version": 1}})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Clé de pointage introuvable")
        return {"actif": action == "reactiver"}

    @api.post("/admin/pointage-inventaires", tags=["Pointage par téléphone"])
    async def creer(corps: Creation, user: dict = Depends(_admin)):
        if not corps.structure:
            raise HTTPException(status_code=400, detail="Structure attendue")
        return await _creer(await _structure(corps.structure), corps, user.get("email") or user.get("name") or "admin")

    @api.get("/admin/pointage-inventaires/{ident}", tags=["Pointage par téléphone"])
    async def detail(ident: str, _: dict = Depends(_admin)):
        return await _detail(await _fiche(ident))

    @api.post("/admin/pointage-inventaires/{ident}/jeton", tags=["Pointage par téléphone"])
    async def nouveau_jeton(ident: str, _: dict = Depends(_admin)):
        return await _nouveau_jeton(await _fiche(ident, projection={"id": 1, "etat": 1}))

    @api.post("/admin/pointage-inventaires/{ident}/cloturer", tags=["Pointage par téléphone"])
    async def cloturer(ident: str, user: dict = Depends(_admin)):
        return await _cloturer(await _fiche(ident, projection={"id": 1}), user.get("email"))

    @api.post("/admin/pointage-inventaires/{ident}/rouvrir", tags=["Pointage par téléphone"])
    async def rouvrir(ident: str, _: dict = Depends(_admin)):
        return await _rouvrir(await _fiche(ident, projection={"id": 1}))

    @api.get("/admin/pointage-inventaires/{ident}/export", tags=["Pointage par téléphone"])
    async def export(ident: str, format: str = "json", _: dict = Depends(_admin)):
        return await _export(await _fiche(ident), format)

    # ------------------------------------------------------------------ Espace pointage du responsable (clé + mot de passe)
    async def _espace(request: Request) -> dict:
        """Commerce connecté à l'Espace pointage (jeton signé dans l'en-tête X-Pointage-Jeton) ; 401 sinon."""
        await _preparer()
        d = pt.lire_jeton(_secret(), request.headers.get("x-pointage-jeton"), "espace")
        acces = await acces_col.find_one({"id": d["acces"]}, {"_id": 0, "mdp_hash": 0}) if d else None
        if not acces or not acces.get("actif"):
            raise HTTPException(status_code=401, detail="Session de l'Espace pointage expirée : reconnectez-vous")
        return acces

    @api.post("/pointage-espace/connexion", tags=["Pointage par téléphone"])
    async def connexion_espace(corps: Connexion, request: Request):
        await _preparer()
        acces = await acces_col.find_one({"cle": pt.normaliser_cle(corps.cle)}, {"_id": 0})
        acces = await _verifier_mot_de_passe(acces, corps.mot_de_passe, request)
        return {"jeton": pt.jeton_espace(_secret(), acces), "commerce": _acces_public(acces), "types_commerce": pt.TYPES_COMMERCE}

    @api.get("/pointage-espace/moi", tags=["Pointage par téléphone"])
    async def moi(acces: dict = Depends(_espace)):
        return {"commerce": _acces_public(acces)}

    @api.get("/pointage-espace/inventaires", tags=["Pointage par téléphone"])
    async def espace_liste(acces: dict = Depends(_espace)):
        s = acces["structure"]
        return await _liste({"structure.source": s["source"], "structure.id": s["id"]})

    @api.post("/pointage-espace/inventaires", tags=["Pointage par téléphone"])
    async def espace_creer(corps: Creation, acces: dict = Depends(_espace)):
        await _exiger_souscription(acces)                          # lot 500 : pas de nouvel inventaire sans souscription vérifiée
        return await _creer(acces["structure"], corps, f"Espace pointage {acces['cle']}")      # structure imposée par la connexion

    @api.get("/pointage-espace/souscription", tags=["Pointage par téléphone"])
    async def espace_souscription(acces: dict = Depends(_espace)):
        """État de la souscription du commerce, formules et prix, séquences USSD par opérateur, historique des demandes."""
        tarifs = await _tarifs()
        liste = await _souscriptions(acces["id"])
        return {"etat": pt.etat_souscription(liste), "tarifs": tarifs["tarifs"], "devise": tarifs["devise"], "formules": pt.LIBELLES_FORMULES,
                "operateurs": _sequences(tarifs), "historique": [{k: x.get(k) for k in ("id", "formule", "montant", "devise", "operateur", "reference",
                                                                                         "statut", "debut", "fin", "demandee_le", "verifiee_le")} for x in liste]}

    @api.post("/pointage-espace/souscription", tags=["Pointage par téléphone"])
    async def espace_souscrire(corps: DemandeSouscription, acces: dict = Depends(_espace)):
        """Après le paiement mobile : la référence de la transaction est rapprochée du SMS reçu (vérification automatique), sinon l'administrateur valide."""
        tarifs = await _tarifs()
        montant = tarifs["tarifs"].get(corps.formule)
        if not montant:
            raise HTTPException(status_code=400, detail="Formule non proposée pour le moment")
        if await souscriptions_col.count_documents({"acces_id": acces["id"], "statut": "en_attente"}) >= 5:
            raise HTTPException(status_code=429, detail="Trop de demandes en attente : patientez leur vérification")
        sous = {"id": uuid.uuid4().hex[:12], "acces_id": acces["id"], "formule": corps.formule, "montant": montant, "devise": tarifs["devise"],
                "operateur": corps.operateur, "reference": corps.reference.strip()[:60], "statut": "en_attente",
                "demandee_le": pt.maintenant().isoformat(), "demandee_par": f"Espace pointage {acces['cle']}"}
        await souscriptions_col.insert_one(dict(sous))
        sous = await _verifier_automatiquement(sous)
        return {"souscription": {k: sous.get(k) for k in ("id", "formule", "montant", "devise", "statut", "debut", "fin")},
                "etat": await _etat_souscription(acces)}

    @api.get("/pointage-espace/inventaires/{ident}", tags=["Pointage par téléphone"])
    async def espace_detail(ident: str, acces: dict = Depends(_espace)):
        return await _detail(await _fiche(ident, acces["structure"]))

    @api.post("/pointage-espace/inventaires/{ident}/{action}", tags=["Pointage par téléphone"])
    async def espace_action(ident: str, action: str, acces: dict = Depends(_espace)):
        doc = await _fiche(ident, acces["structure"], {"id": 1, "etat": 1})
        if action == "jeton":
            return await _nouveau_jeton(doc)
        if action == "cloturer":
            return await _cloturer(doc, f"Espace pointage {acces['cle']}")
        if action == "rouvrir":
            return await _rouvrir(doc)
        raise HTTPException(status_code=404, detail="Action inconnue")

    @api.get("/pointage-espace/inventaires/{ident}/export", tags=["Pointage par téléphone"])
    async def espace_export(ident: str, format: str = "json", acces: dict = Depends(_espace)):
        return await _export(await _fiche(ident, acces["structure"]), format)

    # ------------------------------------------------------------------ téléphones (QR code + mot de passe du commerce)
    async def _par_jeton(jeton: str, projection: Optional[dict] = None) -> dict:
        """Inventaire ouvert correspondant au jeton du QR code ; 404 sinon (jeton inconnu, expiré ou inventaire clôturé)."""
        await _preparer()
        if not jeton or len(jeton) < 20 or len(jeton) > 64:
            raise HTTPException(status_code=404, detail="QR code inconnu ou expiré")
        doc = await inventaires.find_one({"jeton": jeton}, projection)
        if not pt.jeton_valide(doc):
            raise HTTPException(status_code=404, detail="QR code inconnu, expiré, ou inventaire clôturé")
        return doc

    async def _telephone(request: Request, doc: dict) -> None:
        """Le téléphone a-t-il saisi le mot de passe du commerce pour CET inventaire ? (401 sinon : la page redemande le mot de passe)."""
        d = pt.lire_jeton(_secret(), request.headers.get("x-pointage-telephone"), "telephone")
        acces = await acces_col.find_one({"id": d["acces"]}, {"_id": 0, "version": 1, "actif": 1}) if d and d.get("inv") == doc["id"] else None
        if not acces or not acces.get("actif") or acces.get("version", 1) != d.get("v"):
            raise HTTPException(status_code=401, detail="Mot de passe du commerce à saisir")

    @api.get("/public/pointage/{jeton}", tags=["Pointage par téléphone"])
    async def ouvrir(jeton: str):
        """Avant le mot de passe : seulement le nom du commerce et le numéro (jamais la liste des produits)."""
        doc = await _par_jeton(jeton, {"id": 1, "numero": 1, "code_inv": 1, "structure": 1, "etat": 1, "jeton_expire": 1})
        acces = await _acces_de(doc.get("structure") or {})
        return {"numero": doc.get("numero"), "code_inv": doc.get("code_inv"), "cle_pointage": (acces or {}).get("cle"),
                "langue": doc.get("langue") or (acces or {}).get("langue") or "fr", "souscription": await _etat_souscription(acces),
                "structure": (doc.get("structure") or {}).get("libelle") or (doc.get("structure") or {}).get("code"), "mot_de_passe_requis": True}

    @api.post("/public/pointage/{jeton}/acces", tags=["Pointage par téléphone"])
    async def acces_telephone(jeton: str, corps: MotDePasse, request: Request):
        """Mot de passe du commerce saisi sur le téléphone → jeton du téléphone + tout ce qu'il faut pour pointer (même hors connexion)."""
        doc = await _par_jeton(jeton)
        acces = await _acces_de(doc.get("structure") or {})
        acces = await _verifier_mot_de_passe(acces, corps.mot_de_passe, request)
        await _exiger_souscription(acces)                          # lot 500 : pas de téléchargement de l'inventaire sans souscription vérifiée
        lignes = [{"c": x["Chrono"], "l": x.get("Libellé"), "m": x.get("Mesure")} for x in (doc.get("export") or {}).get(pt.CLE_TABLE) or []]
        return {"jeton_telephone": pt.jeton_telephone(_secret(), doc, acces), "numero": doc.get("numero"), "code_inv": doc.get("code_inv"),
                "langue": doc.get("langue") or acces.get("langue") or "fr", "id": doc["id"], "cle_pointage": acces.get("cle"),
                "structure": (doc.get("structure") or {}).get("libelle") or (doc.get("structure") or {}).get("code"),
                "lieux": [{"id": l["id"], "nom": l["nom"]} for l in doc.get("lieux") or []], "lignes": lignes, "jeton_expire": doc.get("jeton_expire"),
                "souscription": await _etat_souscription(acces)}

    @api.post("/public/pointage/{jeton}/saisies", tags=["Pointage par téléphone"])
    async def saisir(jeton: str, corps: Envoi, request: Request):
        doc = await _par_jeton(jeton, {"id": 1, "export." + pt.CLE_TABLE + ".Chrono": 1, "lieux": 1, "etat": 1, "jeton_expire": 1, "structure": 1})
        await _telephone(request, doc)
        # Lot 500 : souscription. Valide → tout passe ; expirée → seules les saisies COMPTÉES pendant une période payée passent (heure du téléphone,
        # jamais dans le futur ni avant la création de l'inventaire : « finir l'envoi seulement », choix du propriétaire)
        acces_c = await _acces_de(doc.get("structure") or {})
        liste_sous = await _souscriptions((acces_c or {}).get("id"))
        valide_maintenant = pt.etat_souscription(liste_sous)["valide"]
        message_expire = ("Counted after the subscription ended: not accepted." if (acces_c or {}).get("langue") == "en"
                          else "Comptée après la fin de la souscription : non acceptée.")
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
            if not valide_maintenant:
                compte = pt._instant(s.get("compte_le"))
                if not (compte and compte <= pt.maintenant() and pt.couvert(liste_sous, compte)):
                    refusees.append({"uid": s["uid"], "erreur": message_expire})
                    continue
            # Ligne déjà comptée dans ce lieu (par n'importe quel téléphone) : la quantité s'ajoute, le téléphone le signale
            deja = await saisies.find_one({"inventaire_id": doc["id"], "chrono": s["chrono"], "lieu": s["lieu"], "annulee": {"$ne": True}}, {"_id": 1})
            # Prénom et appareil de l'envoi, sauf si la saisie porte les siens (fichier fusionné par le responsable dans Loois mobile)
            s = {"prenom": prenom, "appareil": corps.appareil} | s | {"inventaire_id": doc["id"], "le": pt.maintenant().isoformat(), "ip": _ip(request)}
            try:
                await saisies.insert_one(s)
                if deja:
                    doublons.append({"uid": s["uid"], "chrono": s["chrono"]})
            except DuplicateKeyError:
                pass                              # même uid renvoyé après une coupure réseau : déjà compté, jamais deux fois
            acceptees.append(s["uid"])
        return {"acceptees": acceptees, "refusees": refusees, "doublons": doublons}

    @api.post("/public/pointage/{jeton}/annuler", tags=["Pointage par téléphone"])
    async def annuler(jeton: str, corps: Annulation, request: Request):
        doc = await _par_jeton(jeton, {"id": 1, "etat": 1, "jeton_expire": 1})
        await _telephone(request, doc)
        r = await saisies.update_one({"inventaire_id": doc["id"], "uid": corps.uid, "appareil": corps.appareil},
                                     {"$set": {"annulee": True, "annulee_le": pt.maintenant().isoformat()}})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Saisie introuvable sur ce téléphone")
        return {"annulee": corps.uid}
