# routes/historique_conversations.py — Lot 466 : sous-menu Liluvine « Historique Conversation ». Logique et mise en forme : backend/historique_conversations.py.
#   POST /me/liluvine-historique        messages JSON (contacts cochés, période facultative) : du plus récent au plus ancien, sans les messages bloqués
#   POST /me/liluvine-historique/pdf    le même contenu en PDF (date et heure d'édition, « Liluvine » vertical sur chaque page)
#   POST /me/liluvine-historique/csv    le même contenu en CSV (Excel français : « ; », UTF-8 avec BOM)
# Lot 467 — bloc « Chat interne » (support Loois, avec la durée de l'assistance) : historique_support.py
#   GET  /me/liluvine-historique-support/clients           clients ayant eu des sessions d'assistance
#   GET  /me/liluvine-historique-support/postes?client=   postes ayant eu des sessions d'assistance pour ce client
#   POST /me/liluvine-historique-support[/pdf|/csv]       sessions (avec durées) et messages des postes cochés, du plus récent au plus ancien
# Accès : administrateur, et superviseur auquel l'élément « Historique des conversations WhatsApp » est partagé (Paramètres → Liluvine — partage avec les superviseurs).
# Périmètre : EXACTEMENT celui du Centre de Messagerie (clients visibles, lignes WhatsApp autorisées, contacts bloqués absents, communications anonymisées).
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List

from fastapi import Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

import historique_conversations as hc
import historique_support as hs
from routes.liluvine_partage import est_admin, est_superviseur, verifier_element


class DemandeSupport(BaseModel):
    """Corps des routes du bloc « Chat interne » : client, postes cochés, période facultative."""
    client: str = Field(default="", max_length=200)
    poste_ids: List[str] = Field(default_factory=list, max_length=hs.MAX_POSTES)
    du: str = ""
    au: str = ""


class DemandeHistorique(BaseModel):
    contact_ids: List[str] = Field(default_factory=list, max_length=hc.MAX_CONTACTS)
    du: str = ""                       # AAAA-MM-JJ (facultatif)
    au: str = ""
    client: str = Field(default="", max_length=200)    # libellé du client, pour l'en-tête du PDF et la colonne « Client » du CSV


def setup_historique_conversations_routes(*, db, api, get_current_user, resolve_visible_client_ids, resolve_content_restrictions) -> None:
    async def _autoriser(user: dict) -> None:
        if not (est_admin(user) or est_superviseur(user)):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs et superviseurs")
        await verifier_element(db, user, "historique_conversations")

    async def _preparer(demande: DemandeHistorique, user: dict) -> dict:
        """Contrôle d'accès, contacts réellement visibles (comme le Centre de Messagerie), puis messages."""
        await _autoriser(user)
        ids = list(dict.fromkeys(i for i in demande.contact_ids if i))            # sans doublon, ordre gardé
        if not ids:
            raise HTTPException(status_code=422, detail="Cochez au moins un contact.")
        scope = await resolve_visible_client_ids(user)
        contacts = await db.directory_contacts.find({"id": {"$in": ids}, "client_id": {"$in": scope}}, {"_id": 0, "notes_systeme": 0}).to_list(hc.MAX_CONTACTS)
        # lignes WhatsApp autorisées à l'utilisateur, les contacts bloqués restent inclus : seuls leurs messages de la période de blocage sont écartés
        from routes.numeros_wa import telephone_visible
        visibles = [c for c in contacts if await telephone_visible(db, user, c.get("whatsapp") or c.get("phone"), c)]
        restrictions = await resolve_content_restrictions(user)
        du, au = hc.jour_valide(demande.du), hc.jour_valide(demande.au)
        lignes, tronque = await hc.collecter(db, contacts_visibles=visibles, visible_scope=scope, du=du, au=au, client=demande.client,
                                             seulement_utilisateur=user["id"] if restrictions.get("anon_communications") else None)
        noms = sorted({(c.get("name") or c.get("whatsapp") or c.get("phone") or "Contact sans nom") for c in visibles})
        return {"lignes": lignes, "tronque": tronque, "contacts": noms, "du": du, "au": au, "ignores": len(ids) - len(visibles), "genere_le": datetime.now(timezone.utc)}

    @api.post("/me/liluvine-historique", tags=["Liluvine — historique des conversations"])
    async def historique(demande: DemandeHistorique, user: dict = Depends(get_current_user)):
        r = await _preparer(demande, user)
        return {"total": len(r["lignes"]), "tronque": r["tronque"], "maximum": hc.MAX_MESSAGES, "contacts": r["contacts"], "ignores": r["ignores"], "messages": r["lignes"],
                "genere_le": r["genere_le"].isoformat()}

    @api.post("/me/liluvine-historique/pdf", tags=["Liluvine — historique des conversations"])
    async def historique_pdf(demande: DemandeHistorique, user: dict = Depends(get_current_user)):
        r = await _preparer(demande, user)
        pdf = hc.construire_pdf(r["lignes"], client=demande.client, contacts=r["contacts"], du=r["du"], au=r["au"], genere_le=r["genere_le"], tronque=r["tronque"])
        nom = f"historique-conversations-{r['genere_le'].strftime('%Y%m%d-%H%M')}.pdf"
        return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{nom}"'})

    @api.post("/me/liluvine-historique/csv", tags=["Liluvine — historique des conversations"])
    async def historique_csv(demande: DemandeHistorique, user: dict = Depends(get_current_user)):
        r = await _preparer(demande, user)
        nom = f"historique-conversations-{r['genere_le'].strftime('%Y%m%d-%H%M')}.csv"
        return Response(content=hc.construire_csv(r["lignes"]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{nom}"'})


    # ------------------------------------------------------------------------------------------------------------------ Chat interne (lot 467)
    async def _preparer_support(demande: DemandeSupport, user: dict) -> dict:
        """Contrôle d'accès (mêmes droits que l'historique WhatsApp), puis sessions d'assistance et messages des postes choisis."""
        await _autoriser(user)
        ids = list(dict.fromkeys(i for i in demande.poste_ids if i))
        if not demande.client.strip() or not ids:
            raise HTTPException(status_code=422, detail="Choisissez un client et cochez au moins un poste.")
        du, au = hc.jour_valide(demande.du), hc.jour_valide(demande.au)
        sessions, lignes, tronque = await hs.collecter(db, client=demande.client, poste_ids=ids, du=du, au=au)
        postes = sorted({x["poste"] for x in sessions})
        return {"sessions": sessions, "lignes": lignes, "tronque": tronque, "postes": postes, "du": du, "au": au, "genere_le": datetime.now(timezone.utc)}

    @api.get("/me/liluvine-historique-support/clients", tags=["Liluvine — historique des conversations"])
    async def historique_support_clients(user: dict = Depends(get_current_user)):
        await _autoriser(user)
        return await hs.clients_avec_sessions(db)

    @api.get("/me/liluvine-historique-support/postes", tags=["Liluvine — historique des conversations"])
    async def historique_support_postes(client: str = "", user: dict = Depends(get_current_user)):
        await _autoriser(user)
        return await hs.postes_du_client(db, client)

    @api.post("/me/liluvine-historique-support", tags=["Liluvine — historique des conversations"])
    async def historique_support(demande: DemandeSupport, user: dict = Depends(get_current_user)):
        r = await _preparer_support(demande, user)
        return {"total": len(r["lignes"]), "tronque": r["tronque"], "maximum": hs.MAX_MESSAGES, "postes": r["postes"], "sessions": r["sessions"], "messages": r["lignes"],
                "duree_totale_s": hs.total_durees(r["sessions"]), "duree_totale": hs.duree_fr(hs.total_durees(r["sessions"])), "genere_le": r["genere_le"].isoformat()}

    @api.post("/me/liluvine-historique-support/pdf", tags=["Liluvine — historique des conversations"])
    async def historique_support_pdf(demande: DemandeSupport, user: dict = Depends(get_current_user)):
        r = await _preparer_support(demande, user)
        pdf = hc.construire_pdf(r["lignes"], client=demande.client, contacts=r["postes"], du=r["du"], au=r["au"], genere_le=r["genere_le"], tronque=r["tronque"],
                                titre="Historique du chat interne — Support Loois", libelle_contacts="Postes",
                                note="Sessions d'assistance avec leur durée (de l'acceptation par l'agent à la fin), puis les messages du plus récent au plus ancien.",
                                recap=hs.recap_pdf(r["sessions"]), entetes=("Date et heure", "Poste", "Émetteur", "Message"), largeurs_mm=(28, 34, 28, 92))
        nom = f"historique-chat-interne-{r['genere_le'].strftime('%Y%m%d-%H%M')}.pdf"
        return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{nom}"'})

    @api.post("/me/liluvine-historique-support/csv", tags=["Liluvine — historique des conversations"])
    async def historique_support_csv(demande: DemandeSupport, user: dict = Depends(get_current_user)):
        r = await _preparer_support(demande, user)
        nom = f"historique-chat-interne-{r['genere_le'].strftime('%Y%m%d-%H%M')}.csv"
        return Response(content=hs.construire_csv(r["lignes"], r["sessions"]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{nom}"'})
