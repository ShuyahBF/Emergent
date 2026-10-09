# synthese_support.py — Lot 92 : synthèse du support pour l'administrateur et le superviseur.
#
# Demande du propriétaire (09/10/2026) : « permettre à Superviseur et Admin d'avoir les synthèses des demandes au
# support non répondues, le nombre total et les requêtes assistance transmises à Claude ».
#
# En résumé (pour un développeur WinDev) — une seule route en lecture seule, GET /api/support/synthese?jours=30 :
#   1. « non répondues » : demandes du Support Loois et des plateformes web (sTer, adLyn…) qui attendent le support :
#        - en attente : personne n'a encore pris la demande ;
#        - sans réponse : demande prise, mais le DERNIER message du fil vient du client (le support n'a pas répondu) ;
#      avec l'attente en minutes et le dernier message du client ;
#   2. « totaux » sur la période choisie : demandes reçues, terminées, non répondues, par espace (Support Loois,
#      sTer - Support…) ;
#   3. « Claude » : demandes de fonctionnalités transmises à Claude par Liluvine (lot 91) : nombre par état et liste.
# Accès : rôles admin et superviseur. Rien n'est modifié.
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

TEXTE_APERCU = 160          # caractères du dernier message affichés dans la synthèse
JOURS_MAX = 366


def _date(v: Any) -> Optional[datetime]:
    """Date ISO → datetime UTC (None si illisible)."""
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def minutes_depuis(v: Any, maintenant: datetime) -> Optional[int]:
    """Minutes écoulées depuis une date ISO (None si inconnue)."""
    d = _date(v)
    return None if d is None else max(0, int((maintenant - d).total_seconds() // 60))


async def _dernier_message(db, espace: str, fil: str) -> Optional[Dict[str, Any]]:
    """Dernier message d'un fil (messages du client OU qui lui sont adressés)."""
    return await db.internal_chat_messages.find_one(
        {"client_id": espace, "$or": [{"sender_id": fil}, {"recipient_id": fil}]},
        {"_id": 0, "sender_id": 1, "text": 1, "created_at": 1}, sort=[("created_at", -1)])


async def non_repondues(db, maintenant: datetime) -> List[Dict[str, Any]]:
    """Demandes qui attendent le support (Support Loois + plateformes web), la plus ancienne en premier."""
    from routes import support_loois, support_plateformes as sp
    noms = {e["code"]: sp.libelle_espace(e) async for e in db.liluvine_emetteurs.find({}, {"_id": 0, "code": 1, "nom": 1})}
    out: List[Dict[str, Any]] = []

    async def ajouter(espace: str, espace_nom: str, fil: str, nom: str, numero: str, statut: str, ouverte: Any) -> None:
        """Ajoute la demande si elle attend le support (en attente, ou dernier message venant du client)."""
        dernier = await _dernier_message(db, espace, fil)
        du_client = bool(dernier) and dernier.get("sender_id") == fil
        if statut != "attente" and not du_client:
            return   # le support a répondu en dernier
        depuis = dernier["created_at"] if du_client else ouverte
        out.append({
            "espace": espace, "espace_nom": espace_nom, "fil": fil, "nom": nom, "numero": numero or "",
            "etat": "attente" if statut == "attente" else "sans_reponse",
            "depuis": depuis, "attente_min": minutes_depuis(depuis, maintenant),
            "dernier_message": ((dernier or {}).get("text") or "")[:TEXTE_APERCU] if du_client else "",
        })

    # Plateformes web : requêtes en attente ou en cours (une requête close d'elle-même est ignorée)
    async for r in db.support_plateformes_requetes.find({"statut": {"$in": list(sp.STATUTS_EN_COURS)}}, {"_id": 0}):
        if await sp.requete_en_cours(db, r["demandeur_id"]) is None:
            continue
        await ajouter(sp.espace_id(r["plateforme"]), noms.get(r["plateforme"], r["plateforme"]), r["demandeur_id"],
                      r.get("demandeur_nom") or r["demandeur_id"], r.get("numero"), r["statut"], r.get("ouverte_le"))
    # Support Loois : sessions en attente ou actives
    async for s in db.support_loois_sessions.find({"en_cours": True}, {"_id": 0}):
        await ajouter(support_loois.ESPACE_ID, support_loois.ESPACE_NOM, s.get("poste_id") or "",
                      s.get("poste_nom") or s.get("poste_id") or "", s.get("ticket_number"), s.get("statut") or "",
                      s.get("demande_le"))
    out.sort(key=lambda x: x["depuis"] or "")
    return out


async def totaux(db, depuis: str, attente: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Demandes reçues / terminées sur la période, par espace, et nombre de demandes non répondues."""
    from routes import support_loois, support_plateformes as sp
    noms = {e["code"]: sp.libelle_espace(e) async for e in db.liluvine_emetteurs.find({}, {"_id": 0, "code": 1, "nom": 1})}
    par_espace: Dict[str, Dict[str, Any]] = {}

    def ligne(espace_nom: str) -> Dict[str, Any]:
        return par_espace.setdefault(espace_nom, {"espace_nom": espace_nom, "recues": 0, "terminees": 0, "non_repondues": 0})

    async for r in db.support_plateformes_requetes.find({"ouverte_le": {"$gte": depuis}}, {"_id": 0, "plateforme": 1, "statut": 1}):
        l = ligne(noms.get(r["plateforme"], r["plateforme"]))
        l["recues"] += 1
        l["terminees"] += 1 if r.get("statut") == "terminee" else 0
    async for s in db.support_loois_sessions.find({"demande_le": {"$gte": depuis}}, {"_id": 0, "statut": 1}):
        l = ligne(support_loois.ESPACE_NOM)
        l["recues"] += 1
        l["terminees"] += 1 if s.get("statut") == "terminee" else 0
    for a in attente:
        ligne(a["espace_nom"])["non_repondues"] += 1
    lignes = sorted(par_espace.values(), key=lambda x: x["espace_nom"].lower())
    return {
        "recues": sum(x["recues"] for x in lignes),
        "terminees": sum(x["terminees"] for x in lignes),
        "non_repondues": len(attente),
        "en_attente": sum(1 for a in attente if a["etat"] == "attente"),
        "sans_reponse": sum(1 for a in attente if a["etat"] == "sans_reponse"),
        "par_espace": lignes,
    }


async def transmises_a_claude(db, depuis: str) -> Dict[str, Any]:
    """Demandes de fonctionnalités transmises à Claude (lot 91) sur la période : nombre par état et liste."""
    from routes import avis_claude
    demandes = [avis_claude.vue(d) async for d in db.demandes_fonctionnalites.find(
        {"creee_le": {"$gte": depuis}}, {"_id": 0}).sort("creee_le", -1).limit(200)]
    par_statut: Dict[str, int] = {}
    for d in demandes:
        par_statut[d.get("statut") or "?"] = par_statut.get(d.get("statut") or "?", 0) + 1
    return {"total": len(demandes), "par_statut": par_statut, "a_decider": par_statut.get("a_decider", 0),
            "demandes": demandes}


def installer(*, router, db, get_current_user) -> None:
    """Route GET /support/synthese (administrateur et superviseur)."""
    from fastapi import Depends, HTTPException, Query

    async def admin_ou_superviseur(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur et au superviseur")
        return user

    @router.get("/support/synthese", tags=["Synthèse du support"])
    async def synthese(jours: int = Query(30, ge=1, le=JOURS_MAX), user: dict = Depends(admin_ou_superviseur)):
        """Synthèse : demandes non répondues, totaux de la période, demandes transmises à Claude."""
        maintenant = datetime.now(timezone.utc)
        depuis = (maintenant - timedelta(days=jours)).isoformat()
        attente = await non_repondues(db, maintenant)
        return {
            "jours": jours, "genere_le": maintenant.isoformat(),
            "non_repondues": attente,
            "totaux": await totaux(db, depuis, attente),
            "claude": await transmises_a_claude(db, depuis),
        }
