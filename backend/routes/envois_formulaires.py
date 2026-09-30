"""Lot 42 — Envoi du lien d'un formulaire à des contacts (WhatsApp ou SMS).

Même principe que l'envoi des sondages (routes/wa_surveys.py) :
  - destinataires choisis comme pour un sondage (clients, groupes, entreprise, contacts,
    échantillon) : le calcul de la liste est celui des sondages ;
  - WhatsApp : message libre pour les contacts qui ont écrit dans les 24 h, modèle Meta
    pour les autres (mode « auto »), ou SMS ;
  - le lien envoyé est celui du formulaire public (/f/<id>) : le formulaire doit être public ;
  - envoi immédiat ou PROGRAMMÉ (date et heure), toujours dans les plages horaires fixées
    par l'Admin (routes/plages_envoi.py) : hors plage, l'envoi attend et reprend tout seul.

Jetons du message : {{lien}}, {{formulaire}}, {{formulaire_numero}}, {{name}} / {{nom}} ;
pour un bouton lien dont l'adresse finit par une variable (…/f/{{1}}) : {{jeton}} (id du formulaire).

Collection : form_envois {id, form_id, client_id, title, channel, mode, template_name, …,
  destinataires: [{contact_id, name, company, phone, status, error, sent_at, message_id}],
  total, done, sent_ok, sent_ko, skipped, status: scheduled|waiting|running|done|cancelled,
  programme_le, reprise_a, created_by_*, created_at}

Routes (sous /api) :
  POST   /me/forms/{fid}/envois              nouvel envoi (immédiat ou programmé)
  GET    /me/forms/{fid}/envois              envois du formulaire et leur progression
  DELETE /me/forms/{fid}/envois/{eid}        annulation d'un envoi programmé, en attente ou en cours
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

from routes.wa_surveys import MAX_RECIPIENTS, MAX_SMS, SEND_PAUSE_SECONDS, RecipientsQuery

logger = logging.getLogger("sawali.envois_formulaires")

MESSAGE_PAR_DEFAUT = "Bonjour {{name}}, merci de remplir notre formulaire « {{formulaire}} » : {{lien}}"
SMS_PAR_DEFAUT = "Bonjour {{name}}, merci de remplir notre formulaire « {{formulaire}} » : {{lien}}"
RE_JETON = re.compile(r"\{\{\s*([a-zA-Z_]+)\s*\}\}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chiffres(tel: Optional[str]) -> str:
    return "".join(ch for ch in (tel or "") if ch.isdigit())


def remplir(texte: str, ctx: Dict[str, Any]) -> str:
    """Remplace les jetons {{…}} du message par leur valeur (jeton inconnu -> vide)."""
    return RE_JETON.sub(lambda m: str(ctx.get(m.group(1).lower(), "")), texte or "")


class EnvoiIn(BaseModel):
    contact_ids: List[str] = Field(default_factory=list)
    channel: str = "whatsapp"                # whatsapp | sms
    mode: str = "auto"                       # auto | template | text
    template_name: Optional[str] = None
    language_code: Optional[str] = "fr"
    variables: List[str] = Field(default_factory=list)
    header_text: Optional[str] = None
    button_specs: Optional[List[Dict[str, Any]]] = None
    text_message: Optional[str] = None
    title: Optional[str] = None
    programme_le: Optional[str] = None       # date/heure d'envoi (heure de la plateforme)


def attach_envois_formulaires_routes(
    *, api, db, get_current_user, uuid_fn: Callable[[], str], can_send_wa, is_admin_like,
    wa_enabled_for, enforce_demo_quota, wa_send_template, wa_send_text, build_recipient_ctx,
    build_components, public_base_url, resolve_contacts, open_window_digits, plages,
    is_preview_env: Callable[[], bool] = lambda: False,
    sms_enabled_for=None, sms_send=None, enforce_sms_quota=None,
) -> Dict[str, Any]:

    def _scope(user: dict) -> str:
        return user.get("parent_client_id") or user.get("client_id") or user["id"]

    async def _formulaire(fid: str, user: dict) -> dict:
        """Formulaire du client connecté (ou n'importe lequel pour l'Admin / le Superviseur)."""
        f = await db.forms.find_one({"id": fid}, {"_id": 0, "pages": 0})
        if not f:
            raise HTTPException(status_code=404, detail="Formulaire introuvable")
        if not is_admin_like(user) and f.get("client_id") not in {_scope(user), user.get("client_id"), user["id"]}:
            raise HTTPException(status_code=403, detail="Seul le propriétaire du formulaire peut l'envoyer")
        return f

    # ---- Envoi d'un message ----------------------------------------------------------
    async def _envoyer_un(envoi: dict, form: dict, d: dict, fenetre: bool) -> Dict[str, Any]:
        lien = f"{envoi.get('base_url') or ''}/f/{form['id']}"
        doc = {"full_name": d.get("name"), "company": d.get("company"), "phone": d.get("phone")}
        ctx = build_recipient_ctx("contact", doc, d.get("phone"), d.get("name"))
        ctx.update({"lien": lien, "lien_formulaire": lien, "jeton": form["id"],
                    "formulaire": form.get("title") or "", "formulaire_numero": form.get("number") or "",
                    "name": ctx.get("full_name") or d.get("name") or "", "nom": ctx.get("full_name") or d.get("name") or ""})
        if envoi.get("channel") == "sms":
            corps = remplir(envoi.get("text_message") or SMS_PAR_DEFAUT, ctx)
            if "/f/" not in corps:
                corps = f"{corps} {lien}"                      # le lien est toujours présent
            res = await sms_send(d["phone"], corps)
            return {"ok": bool(res.get("ok")), "status": res.get("status"), "provider": res.get("provider"),
                    "error": None if res.get("ok") else (res.get("api_message") or "Échec de l'envoi du SMS"),
                    "channel": "sms", "body": corps}
        mode = envoi.get("mode") or "auto"
        if mode == "text" or (mode == "auto" and fenetre):
            if not fenetre:
                return {"ok": False, "skipped": True,
                        "error": "Fenêtre 24 h fermée : ce contact ne vous a pas écrit récemment (utilisez un modèle Meta)"}
            corps = remplir(envoi.get("text_message") or MESSAGE_PAR_DEFAUT, ctx)
            if "/f/" not in corps:
                corps = f"{corps}\n{lien}"
            return {**await wa_send_text(d["phone"], corps), "channel": "text", "body": corps}
        if not envoi.get("template_name"):
            return {"ok": False, "skipped": True, "error": "Aucun modèle Meta choisi (contact hors fenêtre de 24 h)"}
        comps = build_components(envoi.get("variables") or [], ctx, header_text=envoi.get("header_text"),
                                 button_specs=envoi.get("button_specs"))
        res = await wa_send_template(d["phone"], envoi["template_name"], envoi.get("language_code") or "fr", comps)
        return {**res, "channel": "template", "body": f"[Formulaire] {form.get('title')} — {lien}"}

    async def _tracer(envoi: dict, d: dict, res: Dict[str, Any]) -> None:
        """Trace dans l'historique des SMS ou dans la conversation WhatsApp du contact."""
        ok = bool(res.get("ok"))
        try:
            if res.get("channel") == "sms":
                await db.sms_messages.insert_one({
                    "id": uuid_fn(), "client_id": envoi.get("client_id"), "user_id": envoi.get("created_by_id"),
                    "user_label": envoi.get("created_by_label"), "contact_id": d.get("contact_id"),
                    "provider": res.get("provider"), "sender": None, "msisdn": d.get("phone"),
                    "msisdn_digits": _chiffres(d.get("phone")), "message": res.get("body"),
                    "length": len(res.get("body") or ""), "status": res.get("status"),
                    "api_message": res.get("error"), "bulk": True, "form_id": envoi["form_id"], "created_at": _now()})
            elif ok or not res.get("skipped"):
                modele = res.get("channel") == "template"
                await db.whatsapp_messages.insert_one({
                    "id": uuid_fn(), "client_id": envoi.get("client_id"), "direction": "outbound",
                    "sender_id": envoi.get("created_by_id"), "sender_label": envoi.get("created_by_label"),
                    "to": d.get("phone"), "phone_digits": _chiffres(d.get("phone")),
                    "template_name": envoi.get("template_name") if modele else None,
                    "language_code": envoi.get("language_code") if modele else None,
                    "message_type": "template" if modele else "text", "body": res.get("body"),
                    "contact_id": d.get("contact_id"), "recipient_kind": "contact", "recipient_label": d.get("name"),
                    "bulk": True, "form_id": envoi["form_id"], "ok": ok, "status": res.get("status"),
                    "message_id": res.get("message_id"), "error": res.get("error"),
                    "wa_status": "sent" if ok else "failed", "sent_at": _now() if ok else None,
                    "failed_at": None if ok else _now(), "created_at": _now()})
        except Exception:  # noqa: BLE001 — la trace ne bloque jamais l'envoi
            logger.warning("[envois-formulaires] trace impossible", exc_info=True)

    # ---- Tâche d'envoi -------------------------------------------------------------------
    _en_cours: Dict[str, asyncio.Task] = {}
    _annules: set = set()

    async def _attendre_plage(eid: str) -> bool:
        """Hors plage horaire : l'envoi passe « en attente » jusqu'à la prochaine ouverture."""
        ouverture = await plages["attente"]()
        if ouverture is None:
            return False
        await db.form_envois.update_one({"id": eid, "status": "running"}, {"$set": {
            "status": "waiting", "reprise_a": ouverture.isoformat(), "updated_at": _now()}})
        return True

    async def executer(eid: str) -> None:
        """Envoie les messages restants (status « queued ») de l'envoi `eid`."""
        try:
            envoi = await db.form_envois.find_one({"id": eid}, {"_id": 0})
            if not envoi or envoi.get("status") != "running":
                return
            form = await db.forms.find_one({"id": envoi["form_id"]}, {"_id": 0, "pages": 0}) or {"id": envoi["form_id"]}
            dests = envoi.get("destinataires") or []
            fenetres = await open_window_digits([_chiffres(d.get("phone")) for d in dests if d.get("status") == "queued"])
            for i, d in enumerate(dests):
                if d.get("status") != "queued":
                    continue                                        # déjà traité (reprise)
                if eid in _annules:
                    _annules.discard(eid)
                    return
                if await _attendre_plage(eid):
                    return
                try:
                    res = await _envoyer_un(envoi, form, d, _chiffres(d.get("phone")) in fenetres)
                except Exception as exc:  # noqa: BLE001
                    res = {"ok": False, "error": str(exc)[:300]}
                ok, saute = bool(res.get("ok")), bool(res.get("skipped"))
                statut = "sent" if ok else ("skipped" if saute else "failed")
                await db.form_envois.update_one({"id": eid}, {
                    "$set": {f"destinataires.{i}.status": statut, f"destinataires.{i}.error": None if ok else res.get("error"),
                             f"destinataires.{i}.sent_at": _now() if ok else None,
                             f"destinataires.{i}.message_id": res.get("message_id"), "updated_at": _now()},
                    "$inc": {"done": 1, "sent_ok": 1 if ok else 0, "sent_ko": 0 if ok or saute else 1,
                             "skipped": 1 if saute else 0}})
                await _tracer(envoi, d, res)
                await asyncio.sleep(SEND_PAUSE_SECONDS)
            await db.form_envois.update_one({"id": eid, "status": "running"},
                                            {"$set": {"status": "done", "finished_at": _now()}})
        finally:
            _en_cours.pop(eid, None)

    def _lancer(eid: str) -> None:
        if eid in _en_cours and not _en_cours[eid].done():
            return
        _en_cours[eid] = asyncio.create_task(executer(eid))

    async def lancer_echus() -> int:
        """Démarre les envois programmés échus et reprend ceux qui attendaient une plage."""
        n = 0
        async for e in db.form_envois.find({"status": {"$in": ["scheduled", "waiting"]}, "reprise_a": {"$lte": _now()}},
                                           {"_id": 0, "id": 1}):
            r = await db.form_envois.update_one({"id": e["id"], "status": {"$in": ["scheduled", "waiting"]}},
                                                {"$set": {"status": "running", "updated_at": _now()}})
            if r.modified_count:
                _lancer(e["id"])
                n += 1
        return n

    # ---- Routes ------------------------------------------------------------------------
    @api.post("/me/forms/{fid}/envois", tags=["Formulaires"])
    async def creer_envoi(fid: str, payload: EnvoiIn, request: Request, user: dict = Depends(get_current_user)):
        par_sms = payload.channel == "sms"
        if par_sms:
            if sms_send is None:
                raise HTTPException(status_code=400, detail="Envoi par SMS indisponible")
            if sms_enabled_for is not None and not await sms_enabled_for(user):
                raise HTTPException(status_code=403, detail="SMS non autorisé pour votre compte")
            if len(payload.text_message or "") > MAX_SMS:
                raise HTTPException(status_code=400, detail=f"Message SMS trop long ({MAX_SMS} caractères au maximum)")
        else:
            if not can_send_wa(user):
                raise HTTPException(status_code=403, detail="Rôle non autorisé à envoyer des messages WhatsApp")
            if not await wa_enabled_for(user):
                raise HTTPException(status_code=403, detail="WhatsApp non autorisé pour votre compte")
        form = await _formulaire(fid, user)
        if not form.get("is_public"):
            raise HTTPException(status_code=400, detail=(
                "Ce formulaire n'est pas public : rendez-le public avant de l'envoyer, "
                "sinon le lien ne s'ouvre pas pour les destinataires"))
        quand = await plages["programme"](payload.programme_le)
        mode = "sms" if par_sms else (payload.mode if payload.mode in ("auto", "template", "text") else "auto")
        if mode == "template" and not (payload.template_name or "").strip():
            raise HTTPException(status_code=400, detail="Choisissez un modèle Meta")
        if mode in ("template", "auto") and payload.template_name:
            plat = " ".join((payload.variables or []) + [payload.header_text or ""]
                            + [str(p.get("text") if isinstance(p, dict) else p)
                               for b in (payload.button_specs or []) for p in (b.get("parameters") or [])])
            if not re.search(r"\{\{\s*(lien|lien_formulaire|jeton)\s*\}\}", plat):
                raise HTTPException(status_code=400, detail=(
                    "Placez {{lien}} dans une variable du modèle (ou {{jeton}} dans la partie variable "
                    "d'un bouton lien) : sinon le destinataire ne reçoit pas le lien du formulaire"))
        if mode == "auto" and not payload.template_name:
            mode = "text"
        if not payload.contact_ids:
            raise HTTPException(status_code=400, detail="Aucun destinataire sélectionné")
        contacts = await resolve_contacts(user, RecipientsQuery(contact_ids=payload.contact_ids))
        if not contacts:
            raise HTTPException(status_code=404, detail="Aucun contact avec un numéro de téléphone retrouvé parmi la sélection")
        if len(contacts) > MAX_RECIPIENTS:
            raise HTTPException(status_code=400, detail=f"Maximum {MAX_RECIPIENTS} destinataires par envoi")
        if par_sms:
            if enforce_sms_quota is not None:
                await enforce_sms_quota(user, len(contacts))
        else:
            await enforce_demo_quota(user, len(contacts))
        programme = bool(quand and quand > datetime.now(timezone.utc))
        envoi = {
            "id": uuid_fn(), "form_id": fid, "client_id": _scope(user),
            "form_title": form.get("title"), "title": (payload.title or "").strip()[:200] or None,
            "channel": "sms" if par_sms else "whatsapp", "mode": mode,
            "template_name": None if par_sms else ((payload.template_name or "").strip() or None),
            "language_code": payload.language_code or "fr", "variables": [] if par_sms else (payload.variables or []),
            "header_text": payload.header_text, "button_specs": payload.button_specs,
            "text_message": (payload.text_message or "").strip() or None,
            "base_url": (public_base_url(request) or "").rstrip("/"),
            "destinataires": [{"contact_id": c["id"], "name": c.get("name") or c.get("company") or c["_phone"],
                               "company": c.get("company") or "", "phone": c["_phone"], "status": "queued",
                               "error": None, "sent_at": None, "message_id": None} for c in contacts],
            "total": len(contacts), "done": 0, "sent_ok": 0, "sent_ko": 0, "skipped": 0,
            "status": "scheduled" if programme else "running",
            "programme_le": quand.isoformat() if programme else None,
            "reprise_a": quand.isoformat() if programme else None,
            "created_by_id": user["id"], "created_by_label": user.get("full_name") or user.get("email"),
            "created_at": _now(), "updated_at": _now(),
        }
        await db.form_envois.insert_one(dict(envoi))
        if envoi["status"] == "running":
            _lancer(envoi["id"])                     # hors plage horaire, il passe aussitôt « en attente »
        envoi.pop("destinataires")
        return {"ok": True, "envoi": envoi}

    @api.get("/me/forms/{fid}/envois", tags=["Formulaires"])
    async def lister_envois(fid: str, user: dict = Depends(get_current_user)):
        await _formulaire(fid, user)
        items = await db.form_envois.find({"form_id": fid}, {"_id": 0, "button_specs": 0}).sort("created_at", -1).to_list(100)
        for e in items:
            # Échecs seulement (la liste complète peut compter 1 000 lignes)
            e["echecs"] = [{"name": d.get("name"), "error": d.get("error")}
                           for d in e.pop("destinataires", []) if d.get("status") in ("failed", "skipped")][:50]
        return {"items": items}

    @api.delete("/me/forms/{fid}/envois/{eid}", tags=["Formulaires"])
    async def annuler_envoi(fid: str, eid: str, user: dict = Depends(get_current_user)):
        await _formulaire(fid, user)
        r = await db.form_envois.update_one(
            {"id": eid, "form_id": fid, "status": {"$in": ["scheduled", "waiting", "running"]}},
            {"$set": {"status": "cancelled", "cancelled_at": _now(), "updated_at": _now(),
                      "cancelled_by": user.get("full_name") or user.get("email")}})
        if not r.modified_count:
            raise HTTPException(status_code=409, detail="Cet envoi est déjà terminé ou annulé")
        if eid in _en_cours and not _en_cours[eid].done():
            _annules.add(eid)
        return {"ok": True}

    # ---- Démarrage : reprise et planificateur ---------------------------------------------
    async def _planificateur() -> None:
        while True:
            try:
                await lancer_echus()
            except Exception:  # noqa: BLE001
                logger.warning("[envois-formulaires] planificateur", exc_info=True)
            await asyncio.sleep(60)

    async def demarrer() -> None:
        """Reprend les envois interrompus par un redémarrage et lance le planificateur.
        Jamais dans la preview : sa base est une copie de la production."""
        if is_preview_env():
            return
        async for e in db.form_envois.find({"status": "running"}, {"_id": 0, "id": 1}):
            _lancer(e["id"])
        asyncio.create_task(_planificateur())

    return {"demarrer": demarrer, "executer": executer, "lancer_echus": lancer_echus, "en_cours": _en_cours}
