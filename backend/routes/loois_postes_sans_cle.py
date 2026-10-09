# loois_postes_sans_cle.py — Lot 89 : ALERTE « postes Loois sans clé client valable » (administrateur et superviseur).
#
# Demande du propriétaire (09/10/2026) : Loois n'affiche PLUS AUCUN message sur le poste quand sa clé client manque
# ou est refusée (les utilisateurs pourraient croire qu'ils sont suivis ou contrôlés). « Donc alerter sur SAWALI à
# l'Admin et Superviseur. »
#
# En résumé (pour un développeur WinDev) :
#   - chaque poste Loois envoie déjà son SIGNAL DE PRÉSENCE toutes les 5 minutes (POST /api/presence-logiciel), avec
#     la clé enregistrée sur le poste dans l'en-tête X-Cle-Loois ;
#   - à chaque signal, SAWALI note l'ÉTAT DE LA CLÉ du poste (champ cle_statut de presences_logiciels) :
#       client  = clé client valable (tout va bien)          absente = aucune clé saisie sur le poste
#       commune = seulement la clé commune du support         refusee = clé inconnue ou révoquée
#     (« depuis » : date du passage à cet état, gardée tant que l'état ne change pas) ;
#   - GET /api/admin/loois-postes-sans-cle (admin + superviseur) : postes Loois vus depuis 7 jours dont l'état n'est
#     pas « client » ; le portail en fait un toast persistant et la rubrique des Paramètres un tableau ;
#   - réglage « Alerter l'administrateur et le superviseur » (activé par défaut), modifiable par l'administrateur.
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Request  # au niveau du module : l'annotation de la route doit être résolue (from __future__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
STATUTS_ALERTE = ("absente", "commune", "refusee")   # états qui déclenchent l'alerte
LIBELLES = {
    "client": "Clé client valable",
    "absente": "Aucune clé saisie sur le poste",
    "commune": "Clé commune du support seulement",
    "refusee": "Clé inconnue ou révoquée",
}
GRAVITE = {"refusee": 3, "absente": 2, "commune": 1, "client": 0}   # le pire état d'un poste est retenu
JOURS_SUIVI = 7                 # postes vus depuis 7 jours au plus (un poste éteint depuis longtemps n'alerte plus)
EN_LIGNE_MINUTES = 12           # même seuil que « Versions déployées »
MAX_POSTES = 500                # plafond de la liste renvoyée
ID_REGLAGE = "alerte_postes_sans_cle"
ROLES = ("admin", "superviseur")


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def est_application_loois(application: Optional[str]) -> bool:
    """Seuls les composants Loois (« Loois », « Loois Notification », « Loois Service »…) ont une clé client."""
    return str(application or "").strip().lower().startswith("loois")


def statut_cle(entete: Optional[str], identite: Optional[Dict[str, Any]]) -> str:
    """État de la clé d'un poste à partir de l'en-tête reçu et de l'identité trouvée (loois_cles_clients)."""
    if identite and identite.get("type") == "client":
        return "client"
    if identite and identite.get("type") == "commune":
        return "commune"
    return "refusee" if (entete or "").strip() else "absente"


def champs_presence(statut: str, precedent: Optional[Dict[str, Any]], maintenant_iso: str) -> Dict[str, Any]:
    """Champs à écrire dans la fiche de présence : l'état et la date depuis laquelle il dure (inchangée si même état)."""
    depuis = (precedent or {}).get("cle_statut_depuis")
    if not depuis or (precedent or {}).get("cle_statut") != statut:
        depuis = maintenant_iso
    return {"cle_statut": statut, "cle_statut_depuis": depuis}


def regrouper(fiches: List[Dict[str, Any]], maintenant: datetime) -> List[Dict[str, Any]]:
    """Une ligne par MACHINE (plusieurs composants Loois sur un poste) ; le pire état est retenu.
    Seules les machines dont le pire état déclenche l'alerte sont gardées. Tri : en ligne d'abord, puis état, puis nom."""
    limite_en_ligne = maintenant - timedelta(minutes=EN_LIGNE_MINUTES)
    postes: Dict[str, Dict[str, Any]] = {}
    for f in fiches:
        statut = f.get("cle_statut")
        if statut not in GRAVITE or not f.get("machine"):
            continue
        cle = str(f["machine"]).upper()
        try:
            vu = datetime.fromisoformat(f.get("vu_le") or "")
        except ValueError:
            continue
        p = postes.setdefault(cle, {"machine": f["machine"], "statut": statut, "depuis": f.get("cle_statut_depuis"),
                                    "vu_le": f.get("vu_le"), "en_ligne": False, "site": f.get("site") or "",
                                    "utilisateur": f.get("utilisateur") or "", "client": f.get("verifie_client") or "",
                                    "composants": []})
        p["composants"].append(f.get("composant") or f.get("application"))
        if GRAVITE[statut] > GRAVITE[p["statut"]]:
            p.update(statut=statut, depuis=f.get("cle_statut_depuis"))
        if (f.get("vu_le") or "") > (p["vu_le"] or ""):
            p["vu_le"] = f.get("vu_le")
            p["site"] = f.get("site") or p["site"]
            p["utilisateur"] = f.get("utilisateur") or p["utilisateur"]
        p["en_ligne"] = p["en_ligne"] or vu >= limite_en_ligne
    sortie = [p for p in postes.values() if p["statut"] in STATUTS_ALERTE]
    for p in sortie:
        p["libelle"] = LIBELLES[p["statut"]]
        p["composants"] = sorted({c for c in p["composants"] if c})
    sortie.sort(key=lambda p: (not p["en_ligne"], -GRAVITE[p["statut"]], p["machine"].lower()))
    return sortie[:MAX_POSTES]


async def lire_reglage(db) -> Dict[str, Any]:
    """Réglage de l'alerte (activée par défaut)."""
    doc = await db.loois_reglages.find_one({"id": ID_REGLAGE}, {"_id": 0}) or {}
    return {"actif": bool(doc.get("actif", True)), "maj_le": doc.get("maj_le"), "maj_par": doc.get("maj_par")}


async def postes_sans_cle(db, maintenant: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Postes Loois vus depuis JOURS_SUIVI jours dont la clé n'est pas une clé client valable."""
    maintenant = maintenant or _maintenant()
    seuil = (maintenant - timedelta(days=JOURS_SUIVI)).isoformat()
    fiches = [f async for f in db.presences_logiciels.find(
        {"application": {"$regex": "^loois", "$options": "i"}, "vu_le": {"$gte": seuil}, "cle_statut": {"$exists": True}},
        {"_id": 0, "machine": 1, "application": 1, "composant": 1, "site": 1, "utilisateur": 1, "vu_le": 1,
         "cle_statut": 1, "cle_statut_depuis": 1, "verifie_client": 1})]
    return regrouper(fiches, maintenant)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def setup_loois_postes_sans_cle_routes(*, db, api, get_current_user) -> None:
    """Branche les routes du lot 89 (appelée depuis server_parts/p20)."""
    from fastapi import Depends, HTTPException

    @api.get("/admin/loois-postes-sans-cle", tags=["Loois"])
    async def liste(user: dict = Depends(get_current_user)):
        """Alerte du portail et rubrique des Paramètres : postes Loois sans clé client valable."""
        if user.get("role") not in ROLES:
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur et au superviseur")
        reglage = await lire_reglage(db)
        postes = await postes_sans_cle(db)
        return {"actif": reglage["actif"], "reglage": reglage, "postes": postes, "total": len(postes),
                "en_ligne": sum(1 for p in postes if p["en_ligne"]), "jours_suivi": JOURS_SUIVI,
                "en_ligne_minutes": EN_LIGNE_MINUTES}

    @api.put("/admin/loois-postes-sans-cle/reglage", tags=["Loois"])
    async def enregistrer(request: Request, user: dict = Depends(get_current_user)):
        """Active ou désactive l'alerte (administrateur seulement)."""
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        try:
            corps = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=422, detail="corps JSON attendu")
        actif = bool((corps or {}).get("actif", True))
        await db.loois_reglages.update_one({"id": ID_REGLAGE}, {"$set": {
            "id": ID_REGLAGE, "actif": actif, "maj_le": _maintenant().isoformat(),
            "maj_par": user.get("email") or user.get("id")}}, upsert=True)
        return await lire_reglage(db)
