# routes/serveurs_locaux.py — Serveurs locaux remontés par Loois (lot 480). Logique et stockage : backend/serveurs_locaux.py.
#   POST /api/loois/serveur-local                         (service Windows Loois, clé CLIENT) signale serveur HFSQL, IP locales, port de la passerelle, zone, base ; reçoit le secret de passerelle
#   GET  /api/admin/serveurs-locaux                       (administrateur) clients, machines, adresses ; jamais le secret
#   POST /api/admin/serveurs-locaux/{code}/regenerer      (administrateur) nouveau secret : tickets et sessions existants deviennent invalides
# Aucun mot de passe ne circule : seulement des adresses du réseau local (contrôlées : 10.x, 172.16-31.x, 192.168.x).
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict
from urllib.parse import unquote

from fastapi import Depends, HTTPException, Request

import serveurs_locaux as sl
from routes.liluvine_partage import est_admin

_signaux: Dict[str, Deque[float]] = defaultdict(deque)
SIGNALEMENTS_PAR_HEURE = 120            # un service se signale au démarrage puis toutes les 10 minutes : très largement assez


def setup_serveurs_locaux_routes(*, db, api, get_current_user, identifier_cle=None) -> None:
    if identifier_cle is None:
        from routes.loois_cles_clients import identifier_cle as _identifier
        identifier_cle = _identifier

    async def _admin(user: dict = Depends(get_current_user)) -> dict:
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        return user

    @api.post("/loois/serveur-local", tags=["Loois mobile (serveurs locaux)"])
    async def signaler(request: Request):
        identite = await identifier_cle(db, request.headers.get("X-Loois-Cle"))
        if not identite or identite.get("type") != "client":
            raise HTTPException(status_code=401, detail="Clé client Loois requise")
        from routes.loois_sql_distant import code_client
        code = code_client(unquote(request.headers.get("X-Loois-Base", "")))
        poste = sl.nom_poste(unquote(request.headers.get("X-Loois-Poste", "")))
        if not code or not poste:
            raise HTTPException(status_code=422, detail="Machine et base requises")
        file = _signaux[f"{code}|{poste}"]
        maintenant = time.monotonic()
        while file and maintenant - file[0] > 3600:
            file.popleft()
        if len(file) >= SIGNALEMENTS_PAR_HEURE:
            raise HTTPException(status_code=429, detail="Trop de signalements : réessayez plus tard.")
        file.append(maintenant)
        try:
            corps = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="Corps JSON invalide")
        infos, erreur = sl.valider_infos(corps)
        if erreur:
            raise HTTPException(status_code=422, detail=erreur)
        if not await sl.enregistrer_machine(db, code, poste, infos):
            raise HTTPException(status_code=409, detail=f"Trop de machines pour le client {code} ({sl.MAX_MACHINES_PAR_CLIENT} au plus).")
        secret = await sl.secret_client(db, code, creer=True)
        return {"secret_passerelle": secret, "ticket_ttl_h": sl.TICKET_TTL_H, "session_ttl_h": sl.SESSION_TTL_H, "client": code}

    @api.get("/admin/serveurs-locaux", tags=["Loois mobile (serveurs locaux)"])
    async def liste(_: dict = Depends(_admin)):
        fiche = await sl.lire_fiche(db)
        clients = []
        for code, c in sorted((fiche.get("clients") or {}).items()):
            machines = sorted(({k: v for k, v in m.items()} for m in (c.get("machines") or {}).values() if isinstance(m, dict)), key=lambda m: m.get("vu_le") or "", reverse=True)
            clients.append({"client": code, "secret_defini": bool(c.get("secret")), "secret_cree_le": c.get("secret_cree_le"), "machines": machines, "urls": sl.urls_locales(c)})
        return {"clients": clients, "ticket_ttl_h": sl.TICKET_TTL_H}

    @api.post("/admin/serveurs-locaux/{code}/regenerer", tags=["Loois mobile (serveurs locaux)"])
    async def regenerer(code: str, _: dict = Depends(_admin)):
        from routes.loois_sql_distant import code_client
        c = code_client(code)
        if not c or not (await sl.lire_client(db, c)):
            raise HTTPException(status_code=404, detail="Client inconnu")
        await sl.regenerer_secret(db, c)
        return {"ok": True, "client": c, "message": "Nouveau secret créé : les tickets et sessions existants sont invalides ; les services le récupèrent à leur prochain signalement."}
