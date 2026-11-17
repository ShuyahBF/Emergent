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
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Request  # au niveau du module : l'annotation de la route doit être résolue (from __future__)

from routes.contrats_plateformes import signature_valide

TYPES = ("correction", "nouveaute")
# Lot 429 : « remontee » = En attente ; « en_cours » = SAWALI y travaille ; « point_mort » = travail arrêté (raison obligatoire) ; puis réalisée / refusée.
STATUTS = ("remontee", "en_cours", "point_mort", "realisee", "refusee")
OUVERTS = ("remontee", "en_cours", "point_mort")          # statuts « non terminés »
# Durée estimée : unité → nombre de jours (mois = 30 j, année = 365 j : estimation de planning, pas un calendrier)
UNITES_JOURS = {"jour": 1, "semaine": 7, "mois": 30, "annee": 365}
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


def duree_en_jours(valeur: Any, unite: Any) -> Optional[int]:
    """Durée estimée convertie en jours ; None si absente ou invalide."""
    try:
        v = int(valeur)
    except (TypeError, ValueError):
        return None
    if unite not in UNITES_JOURS or v < 1:
        return None
    return v * UNITES_JOURS[unite]


def _jour(valeur: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(valeur)[:10]) if valeur else None
    except ValueError:
        return None


def planifier(demandes: List[Dict[str, Any]], aujourdhui: date) -> Dict[str, Dict[str, Any]]:
    """PLANNING (diagramme de Gantt) : logique pure, testée. Entrée : demandes de TOUTES les plateformes (clés : cle, statut, recue_le,
    duree_valeur, duree_unite, debut_le). Sortie : cle → {debut, fin, jours, retard_jours} (dates ISO).
      - « en_cours » : commence à `debut_le` (aujourd'hui si absent) et dure sa durée estimée ; sans durée, pas de fin connue.
      - « remontee » (en attente) avec un début imposé (`debut_le`) : placée à cette date, EN PARALLÈLE (les barres peuvent se chevaucher), sans décaler la file ;
      - « remontee » (en attente) : mises en file dans l'ordre d'arrivée ; la 1re commence quand le travail en cours est fini (ou aujourd'hui),
        chacune commence à la fin de la précédente. Sans durée estimée, une demande ne peut pas être placée (et n'avance pas la file).
      - « point_mort » : sort de la file (le travail est arrêté) ; ne décale personne ; seul son début connu est rendu.
      - réalisées et refusées : absentes."""
    plan: Dict[str, Dict[str, Any]] = {}
    curseur = aujourdhui
    for d in sorted((x for x in demandes if x.get("statut") == "en_cours"), key=lambda x: (x.get("debut_le") or "", x.get("recue_le") or "")):
        debut = _jour(d.get("debut_le")) or aujourdhui
        jours = duree_en_jours(d.get("duree_valeur"), d.get("duree_unite"))
        fin = debut + timedelta(days=jours) if jours else None
        plan[d["cle"]] = {"debut": debut.isoformat(), "fin": fin.isoformat() if fin else None, "jours": jours,
                          "retard_jours": (aujourdhui - fin).days if fin and fin < aujourdhui else 0}
        if fin and fin > curseur:
            curseur = fin
    for d in sorted((x for x in demandes if x.get("statut") == "remontee"), key=lambda x: x.get("recue_le") or ""):
        jours = duree_en_jours(d.get("duree_valeur"), d.get("duree_unite"))
        if not jours:
            continue                                        # sans durée : pas de place dans la file
        imposee = _jour(d.get("debut_le"))
        if imposee:                                         # début IMPOSÉ : travail en parallèle (chevauchement possible), ne décale pas la file
            fin = imposee + timedelta(days=jours)
            plan[d["cle"]] = {"debut": imposee.isoformat(), "fin": fin.isoformat(), "jours": jours, "retard_jours": 0}
            continue
        fin = curseur + timedelta(days=jours)
        plan[d["cle"]] = {"debut": curseur.isoformat(), "fin": fin.isoformat(), "jours": jours, "retard_jours": 0}
        curseur = fin
    for d in demandes:
        if d.get("statut") == "point_mort":
            debut = _jour(d.get("debut_le"))
            plan[d["cle"]] = {"debut": debut.isoformat() if debut else None, "fin": None, "jours": duree_en_jours(d.get("duree_valeur"), d.get("duree_unite")), "retard_jours": 0}
    return plan


def vue_pour_plateforme(d: Dict[str, Any], plan: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Ce que la plateforme relit pour chaque demande (jamais de note interne). La date prévue est celle du PLANNING quand une durée est connue."""
    p = plan or {}
    return {"ref_locale": d.get("ref_locale"), "numero": d.get("numero"), "statut": d.get("statut") or "remontee",
            "commentaire": d.get("commentaire"), "realisee_le": d.get("realisee_le"),
            "prevue_le": p.get("fin") or d.get("prevue_le"), "debut_prevu_le": p.get("debut"),
            "duree_valeur": d.get("duree_valeur"), "duree_unite": d.get("duree_unite"),
            "historique": d.get("historique") or []}


def modifiable(demande: Dict[str, Any]) -> bool:
    """Une demande reste modifiable / supprimable par la plateforme tant que SAWALI ne l'a pas VALIDÉE (réalisée ou refusée)."""
    return (demande.get("statut") or "remontee") == "remontee"


def valider_traitement(corps: Dict[str, Any], aujourdhui: date) -> Dict[str, Any]:
    """Champs à enregistrer quand l'administrateur traite une demande ; ValueError (message lisible) si incohérent."""
    statut = corps.get("statut")
    if statut not in STATUTS:
        raise ValueError("Statut attendu : remontee, en_cours, point_mort, realisee ou refusee")
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
    # Durée estimée (lot 429) : un nombre entier de jours, semaines, mois ou années ; vide = non estimée
    duree_valeur, duree_unite = corps.get("duree_valeur"), corps.get("duree_unite")
    if duree_valeur in (None, ""):
        duree_valeur = duree_unite = None
    else:
        if duree_unite not in UNITES_JOURS:
            raise ValueError("Unité de durée attendue : jour, semaine, mois ou annee")
        try:
            duree_valeur = int(duree_valeur)
        except (TypeError, ValueError):
            raise ValueError("La durée doit être un nombre entier")
        if not 1 <= duree_valeur <= 999:
            raise ValueError("La durée doit être comprise entre 1 et 999")
    debut_le = jour("debut_le")
    if statut == "remontee" and not duree_valeur:
        debut_le = None                                     # un début imposé n'a de sens qu'avec une durée estimée
    if statut == "en_cours":
        debut_le = debut_le or aujourdhui.isoformat()
        realisee_le = prevue_le = None
    elif statut == "point_mort":
        if not commentaire:
            raise ValueError("Indiquez la raison du point mort dans le commentaire")
        realisee_le = prevue_le = None
    elif statut == "realisee":
        realisee_le = realisee_le or aujourdhui.isoformat()
        prevue_le = None
    elif statut == "refusee":
        if not commentaire:
            raise ValueError("Indiquez la raison du refus dans le commentaire")
        realisee_le = prevue_le = None
    else:
        realisee_le = None
    return {"statut": statut, "commentaire": commentaire, "realisee_le": realisee_le, "prevue_le": prevue_le,
            "duree_valeur": duree_valeur, "duree_unite": duree_unite, "debut_le": debut_le}


# =====================================================================================
# Routes
# =====================================================================================

def setup_demandes_plateformes_routes(*, db, api, get_current_user) -> None:
    """Branche les routes du lot 384 (appelée depuis server_parts/p20)."""
    from fastapi import Depends, HTTPException

    def _admin(user: dict) -> None:
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")

    async def _planning_global() -> Dict[str, Dict[str, Any]]:
        """Planning de TOUTES les demandes ouvertes de toutes les plateformes (une seule chaîne : le travail se fait l'un après l'autre)."""
        toutes: List[Dict[str, Any]] = []
        async for e in db.liluvine_emetteurs.find({"demandes.0": {"$exists": True}}, {"_id": 0, "demandes": 1}):
            toutes += [{**d, "cle": d.get("numero")} for d in e.get("demandes") or [] if d.get("statut", "remontee") in OUVERTS]
        return planifier(toutes, date.today())

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
        refus: List[Dict[str, Any]] = []
        # Lot 385 : modifications et suppressions demandées par la plateforme, acceptées seulement si SAWALI n'a pas encore validé
        for m in nettoyer_envoi((donnees or {}).get("modifications")):
            cible = next((d for d in existantes if d.get("ref_locale") == m["ref_locale"]), None)
            if cible is None or not modifiable(cible):
                refus.append({"ref_locale": m["ref_locale"], "motif": "Demande introuvable ou déjà validée par SAWALI"})
                continue
            await db.liluvine_emetteurs.update_one({"code": code, "demandes.ref_locale": m["ref_locale"]},
                                                   {"$set": {"demandes.$.texte": m["texte"], "demandes.$.type": m["type"],
                                                             "demandes.$.modifiee_le": datetime.now(timezone.utc).isoformat()}})
            cible["texte"], cible["type"] = m["texte"], m["type"]
        for ref in [str(r).strip()[:80] for r in ((donnees or {}).get("suppressions") or [])[:MAX_PAR_ENVOI]]:
            cible = next((d for d in existantes if d.get("ref_locale") == ref), None)
            if cible is None:
                continue                                   # déjà supprimée : rien à faire
            if not modifiable(cible):
                refus.append({"ref_locale": ref, "motif": "Demande déjà validée par SAWALI : suppression impossible"})
                continue
            await db.liluvine_emetteurs.update_one({"code": code}, {"$pull": {"demandes": {"ref_locale": ref}}})
            existantes = [d for d in existantes if d.get("ref_locale") != ref]
        deja = {d.get("ref_locale") for d in existantes}
        nouvelles = [d for d in nettoyer_envoi((donnees or {}).get("demandes")) if d["ref_locale"] not in deja]
        if nouvelles:
            # Compteur atomique : jamais deux demandes avec le même numéro, même en envois simultanés
            apres = await db.liluvine_emetteurs.find_one_and_update(
                {"code": code}, {"$inc": {"demandes_compteur": len(nouvelles)}}, return_document=True)
            premier = int((apres or {}).get("demandes_compteur") or len(nouvelles)) - len(nouvelles) + 1
            maintenant = datetime.now(timezone.utc).isoformat()
            ajout = [{**d, "numero": numero_demande(code, premier + i), "statut": "remontee", "recue_le": maintenant,
                      "commentaire": None, "realisee_le": None, "prevue_le": None,
                      "duree_valeur": None, "duree_unite": None, "debut_le": None, "historique": []} for i, d in enumerate(nouvelles)]
            await db.liluvine_emetteurs.update_one({"code": code}, {"$push": {"demandes": {"$each": ajout}}})
            existantes = existantes + ajout
        plan = await _planning_global()
        return {"demandes": [vue_pour_plateforme(d, plan.get(d.get("numero"))) for d in existantes], "refus": refus}

    @api.get("/admin/plateformes/demandes", tags=["Plateformes — demandes"])
    async def lister(q: str = "", user: dict = Depends(get_current_user)):
        """Demandes de toutes les plateformes (rubrique « Demandes des plateformes » des Paramètres), recherche libre."""
        _admin(user)
        mots = [m for m in re.split(r"\s+", q.lower().strip()) if m]
        sortie: List[Dict[str, Any]] = []
        plan = await _planning_global()
        async for e in db.liluvine_emetteurs.find({"demandes.0": {"$exists": True}}, {"_id": 0, "secret": 0}):
            for d in e.get("demandes") or []:
                botte = " ".join(str(x or "") for x in (e.get("code"), e.get("nom"), d.get("numero"), d.get("texte"),
                                                         d.get("commentaire"), d.get("statut"), d.get("type"))).lower()
                if all(m in botte for m in mots):
                    p = plan.get(d.get("numero")) or {}
                    sortie.append({**d, "plateforme": e.get("code"), "plateforme_nom": e.get("nom") or e.get("code"),
                                   "debut_prevu_le": p.get("debut"), "fin_prevue_le": p.get("fin"), "retard_jours": p.get("retard_jours", 0)})
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
        maintenant = datetime.now(timezone.utc).isoformat()
        champs["traitee_le"] = maintenant
        # un début déjà connu n'est effacé que pour une demande « en attente » (début imposé retiré) ; sinon on le garde
        ajout = {k: v for k, v in champs.items() if not (k == "debut_le" and v is None and champs["statut"] != "remontee")}
        filtre = {"code": code.strip().lower(), "demandes.numero": numero}
        avant = await db.liluvine_emetteurs.find_one({"code": filtre["code"]}, {"_id": 0, "demandes": 1})
        cible = next((x for x in ((avant or {}).get("demandes") or []) if x.get("numero") == numero), None)
        if cible is None:
            raise HTTPException(status_code=404, detail="Demande introuvable")
        ancien = cible.get("statut") or "remontee"
        await db.liluvine_emetteurs.update_one(filtre, {"$set": {f"demandes.$.{k}": v for k, v in ajout.items()}})
        # Historique des changements de statut (lot 429) : permet de voir les arrêts et les REPRISES dans le diagramme de Gantt
        if champs["statut"] != ancien:
            rang = ((avant or {}).get("demandes") or []).index(cible)          # position dans la liste (chemin sans « $ » : même effet, plus portable)
            await db.liluvine_emetteurs.update_one({"code": filtre["code"]}, {"$push": {f"demandes.{rang}.historique": {"statut": champs["statut"], "le": maintenant}}})
        return {"ok": True, **champs}
