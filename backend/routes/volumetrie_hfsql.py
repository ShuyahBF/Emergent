# routes/volumetrie_hfsql.py — Lot 482 : volumétrie des tables HFSQL (administrateur). Logique : backend/volumetrie_hfsql.py.
#   GET  /api/admin/volumetrie/plateformes       plateformes (Biolog, Aizenta, e-Kol) et clients connus avec leur état (en ligne ou non)
#   GET  /api/admin/volumetrie/tables?plateforme=   tables d'une plateforme : colonnes, octets par ligne, colonne de date
#   POST /api/admin/volumetrie/compter           deux comptages en LECTURE SEULE chez le client : total et N derniers jours (une table par appel)
# Les comptages passent par la file « SQL à distance » (une machine du client les exécute) : rien n'est modifié ni gardé.
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

import volumetrie_hfsql as vh
from routes.liluvine_partage import est_admin

ATTENTE_S = 40.0
PAS_S = 0.5


class DemandeComptage(BaseModel):
    client: str = Field(min_length=1, max_length=20)
    plateforme: str = Field(min_length=1, max_length=20)
    table: str = Field(min_length=1, max_length=80)
    jours: int = 7


def setup_volumetrie_hfsql_routes(*, db, api, get_current_user) -> None:
    async def _admin(user: dict = Depends(get_current_user)) -> dict:
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        return user

    def _interne() -> Dict[str, Any]:
        from routes.loois_sql_distant import INTERNE
        if not INTERNE:
            raise HTTPException(status_code=503, detail="Service SQL à distance indisponible.")
        return INTERNE

    async def _compter(client: str, sql: str, auteur: str) -> Dict[str, Any]:
        """Dépose un comptage et attend son résultat : {valeur, erreur, ms}."""
        interne = _interne()
        debut = time.monotonic()
        try:
            vue = await interne["creer"]({"client": client, "sql": sql, "ephemere": True}, "admin", auteur)
        except HTTPException as e:
            return {"valeur": None, "erreur": str(e.detail), "ms": 0}
        while time.monotonic() - debut < ATTENTE_S:
            etat = await interne["detail"](vue["id"])
            if etat.get("etat") in ("terminee", "echec", "expiree", "sans_reponse"):
                ms = int((time.monotonic() - debut) * 1000)
                if etat.get("etat") == "terminee" and etat.get("ok"):
                    v = vh.premiere_valeur(etat.get("lignes") or [])
                    return {"valeur": v, "erreur": "" if v is not None else "Réponse illisible.", "ms": ms}
                return {"valeur": None, "erreur": (etat.get("message") or "Comptage impossible.")[:300], "ms": ms}
            await asyncio.sleep(PAS_S)
        return {"valeur": None, "erreur": "Aucune machine du client n'a répondu à temps.", "ms": int(ATTENTE_S * 1000)}

    @api.get("/admin/volumetrie/plateformes", tags=["Volumétrie HFSQL"])
    async def plateformes(_: dict = Depends(_admin)):
        clients = []
        try:
            clients = [{"code": c.get("code"), "en_ligne": bool(c.get("en_ligne"))} for c in ((await _interne()["clients"]()).get("clients") or [])]
        except HTTPException:
            pass
        return {"plateformes": vh.plateformes(), "clients": sorted(clients, key=lambda c: (not c["en_ligne"], str(c["code"]))), "jours_max": vh.JOURS_MAX}

    @api.get("/admin/volumetrie/tables", tags=["Volumétrie HFSQL"])
    async def liste_tables(plateforme: str = "biolog", _: dict = Depends(_admin)):
        t = vh.tables(plateforme)
        if not t:
            raise HTTPException(status_code=404, detail="Plateforme inconnue")
        return {"plateforme": plateforme, "tables": t}

    @api.post("/admin/volumetrie/compter", tags=["Volumétrie HFSQL"])
    async def compter(corps: DemandeComptage, user: dict = Depends(_admin)):
        from routes.loois_sql_distant import code_client
        client = code_client(corps.client)
        if not client:
            raise HTTPException(status_code=422, detail="Client invalide (lettres, chiffres, « _ » ou « - », 20 au plus).")
        t = vh.table_connue(corps.plateforme, corps.table)
        if t is None:
            raise HTTPException(status_code=422, detail="Table inconnue pour cette plateforme (schémas de l'Explorateur de schéma).")
        jours = vh.jours_valides(corps.jours)
        auteur = f"Volumétrie {user.get('email') or user.get('id') or ''}"[:120]
        total = await _compter(client, vh.sql_total(t["nom"]), auteur)
        recents: Optional[Dict[str, Any]] = None
        if t["colonne_date"] and total["valeur"] is not None:
            depuis = (datetime.now(timezone.utc) - timedelta(days=jours - 1)).date()
            recents = await _compter(client, vh.sql_recents(t["nom"], t["colonne_date"], depuis), auteur)
        n_recents = recents["valeur"] if recents else None
        base = n_recents if t["colonne_date"] else None
        return {"table": t["nom"], "total": total["valeur"], "erreur_total": total["erreur"], "recents": n_recents, "erreur_recents": (recents or {}).get("erreur", ""), "jours": jours,
                "colonne_date": t["colonne_date"], "octets_hfsql": t["octets_hfsql"], "octets_atlas": t["octets_atlas"], "memos": t["memos"],
                "taille_cache": vh.estimation_octets(base, t["octets_atlas"]), "taille_totale": vh.estimation_octets(total["valeur"], t["octets_hfsql"]),
                "ms": total["ms"] + (recents or {}).get("ms", 0)}
