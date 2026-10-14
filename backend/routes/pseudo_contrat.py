# pseudo_contrat.py — Lot 159 : case « Pseudo contrat VALIDE » sur la fiche client.
#
# Demande du propriétaire (14/10/2026) : « il peut arriver que les paiements d'un client sous contrat n'aient pas pu
# être mis à jour. Dans la fiche client, à côté des informations de contrat, une case "Pseudo contrat VALIDE" qui
# retournera toujours un contrat VALIDE quelles que soient les infos du contrat : pas de retard de paiement constaté.
# Dans la liste des clients, marquer en rouge les clients identifiés "PSEUDO contrat VALIDE". Cette option, si elle
# est cochée, n'est valable que 5 jours avant de revenir à la normale. »
#
# En résumé (pour un développeur WinDev) :
#   - cocher la case = champ `pseudo_contrat_valide_jusqu_au` (date-heure UTC) = maintenant + 5 jours sur la fiche du
#     compte PRINCIPAL du client ; décocher = champ vidé. Aucun traitement planifié : « actif » se calcule à chaque
#     lecture (date de fin dans le futur), donc l'option s'éteint seule au bout de 5 jours ;
#   - effet : le contrat est traité comme VALIDE (puce verte du Centre de messagerie, accès à la ligne Liluvine VIP,
#     statut du contrat envoyé à Loois = pas d'anonymisation), sans modifier les informations du contrat lui-même ;
#   - ne change PAS les alertes de retard, la suspension automatique ni le blocage d'accès à la plateforme (cycle de vie).
# Route : PUT /api/admin/clients/{id}/pseudo-contrat  {actif: bool}  → {actif, jusqu_au}.
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel

CHAMP = "pseudo_contrat_valide_jusqu_au"
DUREE_JOURS = 5


def _instant(valeur: Any) -> Optional[datetime]:
    """Date-heure ISO (texte ou datetime) → datetime UTC, None si absente ou illisible."""
    if isinstance(valeur, datetime):
        return valeur if valeur.tzinfo else valeur.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(valeur).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def pseudo_actif(client: Optional[Dict[str, Any]], maintenant: Optional[datetime] = None) -> bool:
    """Vrai si la case « Pseudo contrat VALIDE » est cochée et n'a pas encore expiré (5 jours)."""
    fin = _instant((client or {}).get(CHAMP))
    return bool(fin and fin > (maintenant or datetime.now(timezone.utc)))


def jusqu_au(client: Optional[Dict[str, Any]]) -> Optional[str]:
    """Date-heure de fin (ISO) tant que l'option est active, sinon None."""
    return _instant((client or {}).get(CHAMP)).isoformat() if pseudo_actif(client) else None


class PseudoContratIn(BaseModel):
    actif: bool = False


def setup_pseudo_contrat_routes(*, db, api, get_current_admin) -> None:
    """Branche la route du lot 159 (appelée depuis server_parts/p20)."""
    from fastapi import Depends, HTTPException

    @api.put("/admin/clients/{cid}/pseudo-contrat", tags=["Admin"])
    async def definir_pseudo_contrat(cid: str, data: PseudoContratIn, admin: dict = Depends(get_current_admin)):
        """Coche (5 jours) ou décoche « Pseudo contrat VALIDE » sur un compte client PRINCIPAL."""
        client = await db.users.find_one({"id": cid}, {"_id": 0, "id": 1, "parent_client_id": 1})
        if not client:
            raise HTTPException(status_code=404, detail="Client introuvable")
        if client.get("parent_client_id"):
            raise HTTPException(status_code=422, detail="Le contrat est porté par le compte principal du client : utilisez sa fiche.")
        fin = (datetime.now(timezone.utc) + timedelta(days=DUREE_JOURS)).isoformat() if data.actif else None
        await db.users.update_one({"id": cid}, {"$set": {
            CHAMP: fin, "pseudo_contrat_modifie_le": datetime.now(timezone.utc).isoformat(),
            "pseudo_contrat_modifie_par": admin.get("email") or admin.get("id")}})
        try:                                   # la puce du Centre de messagerie relit les comptes (cache de 60 s)
            from routes.vip_contrat import vider_cache
            vider_cache()
        except Exception:  # noqa: BLE001
            pass
        return {"actif": bool(fin), "jusqu_au": fin}
