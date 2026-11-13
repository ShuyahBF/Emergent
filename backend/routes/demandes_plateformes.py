# demandes_plateformes.py — Lot 384 : DEMANDES des plateformes clientes (ALBARKA…) : corrections et nouvelles fonctionnalités.
#
# Demande du propriétaire (13/11/2026) : « Pour les requêtes à SAWALI venant d'ALBARKA, gère une liste horodatée de demandes
# de corrections ou nouvelles fonctionnalités. La série de points est remontée à SAWALI, qui attribue un numéro et le retourne
# à ALBARKA, avec un commentaire quand cela a été réalisé (date), sinon à partir de quand ce sera réalisé. Cela permet
# d'organiser le suivi des implémentations. »
#
# En résumé (pour un développeur WinDev) :
#   - la plateforme envoie ses demandes par POST /api/webhook/plateforme-demandes, SIGNÉ comme la transmission universelle
#     (X-Emetteur, X-Timestamp, X-Signature = HMAC-SHA256(clé, "<timestamp>.<corps>")) : aucune nouvelle clé ;
#   - SAWALI attribue à chaque nouvelle demande un numéro « DEM-<CODE>-0001 » (compteur atomique) et répond avec TOUTES les
#     demandes de la plateforme : numéro, statut, commentaire, date de réalisation, date prévue (la plateforme se met ainsi à jour) ;
#   - AUCUNE nouvelle collection (cluster MongoDB plein) : les demandes sont rangées dans le document de la plateforme
#     (db.liluvine_emetteurs, champ `demandes`, compteur `demandes_compteur`) ;
#   - côté SAWALI, l'administrateur traite les demandes (rubrique des Paramètres « Demandes des plateformes ») :
#     statut « remontee » (en attente, avec date prévue facultative), « realisee » (date de réalisation + commentaire),
#     « refusee » (commentaire) ; la plateforme les relit à chaque échange.
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Request  # au niveau du module : l'annotation de la route doit être résolue (from __future__)

from routes.contrats_plateformes import signature_valide

TYPES = ("correction", "nouveaute")
STATUTS = ("remontee", "realisee", "refusee")
MAX_PAR_ENVOI = 100
MAX_TEXTE = 2000


# =====================================================================================
# Logique pure (testée : tests/test_lot384_demandes_plateformes.py)
# =====================================================================================

def numero_demande(code: str, n: int) -> str:
    """« albarka », 7 → « DEM-ALBARKA-0007 »."""
    return f"DEM-{re.sub(r'[^A-Z0-9]', '', (code or '').upper())}-{int(n):04d}"


def nettoyer_envoi(brut: Any) -> List[Dict[str, Any]]:
    """Demandes reçues de la plateforme, nettoyées ; une demande sans identifiant local, sans texte ou de type inconnu est ignorée."""
    sortie = []
    for d in (brut or [])[:MAX_PAR_ENVOI]:
        if not isinstance(d, dict):
            continue
        ref = str(d.get("ref_locale") or "").strip()[:80]
        texte = str(d.get("texte") or "").strip()[:MAX_TEXTE]
        type_ = d.get("type") if d.get("type") in TYPES else None
        if ref and texte and type_:
            sortie.append({"ref_locale": ref, "type": type_, "texte": texte,
                           "demandee_le": str(d.get("demandee_le") or "")[:40] or None,
                           "demandee_par": str(d.get("demandee_par") or "").strip()[:80] or None})
    return sortie


def vue_pour_plateforme(d: Dict[str, Any]) -> Dict[str, Any]:
    """Ce que la plateforme relit pour chaque demande (jamais de note interne)."""
    return {"ref_locale": d.get("ref_locale"), "numero": d.get("numero"), "statut": d.get("statut") or "remontee",
            "commentaire": d.get("commentaire"), "realisee_le": d.get("realisee_le"), "prevue_le": d.get("prevue_le")}


def valider_traitement(corps: Dict[str, Any], aujourdhui: date) -> Dict[str, Any]:
    """Champs à enregistrer quand l'administrateur traite une demande ; ValueError (message lisible) si incohérent."""
    statut = corps.get("statut")
    if statut not in STATUTS:
        raise ValueError("Statut attendu : remontee, realisee ou refusee")
    commentaire = str(corps.get("commentaire") or "").strip()[:MAX_TEXTE] or None

    def jour(cle: str) -> Optional[str]:
        v = corps.get(cle)
        if not v:
            return None
        try:
            return date.fromisoformat(str(v)[:10]).isoformat()
        except ValueError:
            raise ValueError(f"Date « {cle} » invalide (AAAA-MM-JJ)")
    realisee_le, prevue_le = jour("realisee_le"), jour("prevue_le")
    if statut == "realisee":
        realisee_le = realisee_le or aujourdhui.isoformat()
        prevue_le = None
    elif statut == "refusee":
        if not commentaire:
            raise ValueError("Indiquez la raison du refus dans le commentaire")
        realisee_le = prevue_le = None
    else:
        realisee_le = None
    return {"statut": statut, "commentaire": commentaire, "realisee_le": realisee_le, "prevue_le": prevue_le}


# =====================================================================================
# Routes
# =====================================================================================

def setup_demandes_plateformes_routes(*, db, api, get_current_user) -> None:
    """Branche les routes du lot 384 (appelée depuis server_parts/p20)."""
    from fastapi import Depends, HTTPException

    def _admin(user: dict) -> None:
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")

    @api.post("/webhook/plateforme-demandes", tags=["Plateformes — demandes"])
    async def recevoir(request: Request):
        """La plateforme remonte ses nouvelles demandes (peut être vide : simple relecture) — requête signée avec sa clé d'émetteur."""
        code = (request.headers.get("X-Emetteur") or "").strip().lower()
        emetteur = await db.liluvine_emetteurs.find_one({"code": code}, {"_id": 0}) if code else None
        if not emetteur or not emetteur.get("actif", True):
            raise HTTPException(status_code=401, detail="Émetteur inconnu ou désactivé")
        corps = await request.body()
        if not signature_valide(emetteur.get("secret") or "", request.headers.get("X-Timestamp") or "", corps,
                                request.headers.get("X-Signature") or "", datetime.now(timezone.utc)):
            raise HTTPException(status_code=401, detail="Signature refusée")
        try:
            donnees = json.loads(corps.decode("utf-8") or "{}") if corps else {}
        except ValueError:
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        existantes = emetteur.get("demandes") or []
        deja = {d.get("ref_locale") for d in existantes}
        nouvelles = [d for d in nettoyer_envoi((donnees or {}).get("demandes")) if d["ref_locale"] not in deja]
        if nouvelles:
            # Compteur atomique : jamais deux demandes avec le même numéro, même en envois simultanés
            apres = await db.liluvine_emetteurs.find_one_and_update(
                {"code": code}, {"$inc": {"demandes_compteur": len(nouvelles)}}, return_document=True)
            premier = int((apres or {}).get("demandes_compteur") or len(nouvelles)) - len(nouvelles) + 1
            maintenant = datetime.now(timezone.utc).isoformat()
            ajout = [{**d, "numero": numero_demande(code, premier + i), "statut": "remontee", "recue_le": maintenant,
                      "commentaire": None, "realisee_le": None, "prevue_le": None} for i, d in enumerate(nouvelles)]
            await db.liluvine_emetteurs.update_one({"code": code}, {"$push": {"demandes": {"$each": ajout}}})
            existantes = existantes + ajout
        return {"demandes": [vue_pour_plateforme(d) for d in existantes]}

    @api.get("/admin/plateformes/demandes", tags=["Plateformes — demandes"])
    async def lister(q: str = "", user: dict = Depends(get_current_user)):
        """Demandes de toutes les plateformes (rubrique « Demandes des plateformes » des Paramètres), recherche libre."""
        _admin(user)
        mots = [m for m in re.split(r"\s+", q.lower().strip()) if m]
        sortie: List[Dict[str, Any]] = []
        async for e in db.liluvine_emetteurs.find({"demandes.0": {"$exists": True}}, {"_id": 0, "secret": 0}):
            for d in e.get("demandes") or []:
                botte = " ".join(str(x or "") for x in (e.get("code"), e.get("nom"), d.get("numero"), d.get("texte"),
                                                         d.get("commentaire"), d.get("statut"), d.get("type"))).lower()
                if all(m in botte for m in mots):
                    sortie.append({**d, "plateforme": e.get("code"), "plateforme_nom": e.get("nom") or e.get("code")})
        sortie.sort(key=lambda d: d.get("recue_le") or "", reverse=True)
        return {"demandes": sortie}

    @api.put("/admin/plateformes/{code}/demandes/{numero}", tags=["Plateformes — demandes"])
    async def traiter(code: str, numero: str, request: Request, user: dict = Depends(get_current_user)):
        """Traite une demande : en attente (date prévue), réalisée (date + commentaire) ou refusée (raison)."""
        _admin(user)
        try:
            corps = await request.json()
            champs = valider_traitement(corps if isinstance(corps, dict) else {}, date.today())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        champs["traitee_le"] = datetime.now(timezone.utc).isoformat()
        res = await db.liluvine_emetteurs.update_one(
            {"code": code.strip().lower(), "demandes.numero": numero},
            {"$set": {f"demandes.$.{k}": v for k, v in champs.items()}})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Demande introuvable")
        return {"ok": True, **champs}
