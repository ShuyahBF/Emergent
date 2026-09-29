"""Lot 27 — Sondages WhatsApp.

On conçoit un sondage (questions à choix, notes, recommandation, oui/non,
réponse libre), on l'envoie par WhatsApp à un ou plusieurs contacts — par
exemple tous les contacts d'un client — et on mesure les retours.

Principe :
  - chaque destinataire reçoit un LIEN PERSONNEL (/s/<jeton>) : on sait qui a
    ouvert et qui a répondu, sans qu'il ait besoin d'un compte ;
  - l'envoi se fait par un MODÈLE META approuvé (obligatoire hors de la
    fenêtre de 24 h ; le lien est placé dans une variable du texte, ou dans la
    partie variable d'un bouton URL) ou, pour les contacts qui ont écrit dans
    les dernières 24 h, par un MESSAGE LIBRE ; le mode « auto » choisit ;
  - l'envoi tourne en tâche de fond (quelques centaines de destinataires
    prennent plusieurs minutes) ; la page suit la progression ;
  - un destinataire n'a qu'UNE invitation par sondage : une relance renvoie
    le même lien, et sa réponse peut être corrigée tant que le sondage est ouvert ;
  - échantillon aléatoire possible (ex. 100 contacts tirés au hasard parmi 800).
  - lot 35 : le même lien personnel peut aussi partir par SMS (canal « sms » :
    pas de modèle Meta ni de fenêtre de 24 h ; module SMS du client requis).

Collections Mongo :
  wa_surveys            {id, client_id, title, description, thank_you, questions[], status,
                         anonymous, closes_at, message_text, created_by_*, created_at, updated_at}
  wa_survey_invites     {id, token, survey_id, contact_id, client_id, name, company, phone,
                         status: queued|sent|failed|skipped, opened_at, answered_at,
                         sent_count, last_sent_at, message_id, error, campaign_ids[]}
  wa_survey_responses   {id, survey_id, invite_id, contact_id, answers{qid: valeur},
                         created_at, updated_at, revisions}
  wa_survey_campaigns   {id, survey_id, kind: send|reminder, mode, template_name, …,
                         invite_ids[], total, done, sent_ok, sent_ko, skipped, status, …}

Routes (sous /api) :
  GET/POST        /me/wa-surveys                      liste / création
  GET/PUT/DELETE  /me/wa-surveys/{id}                 détail / modification / suppression
  POST            /me/wa-surveys/{id}/duplicate       copie (brouillon)
  POST            /me/wa-surveys/recipients/preview   destinataires (clients, groupes, contacts, échantillon)
  POST            /me/wa-surveys/{id}/send            envoi (ou relance des non-répondants)
  GET             /me/wa-surveys/{id}/campaigns       envois et leur progression
  GET             /me/wa-surveys/{id}/results         taux et statistiques par question
  GET             /me/wa-surveys/{id}/invites         destinataires et leur état
  GET             /me/wa-surveys/{id}/export.csv      réponses (Excel)
  GET/POST        /public/surveys/{token}             page de réponse (sans compte)
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import random
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.wa_surveys")

# Types de questions : clé -> libellé (repris par l'éditeur)
QUESTION_TYPES = {
    "single": "Choix unique",
    "multi": "Choix multiples",
    "yesno": "Oui / Non",
    "rating": "Note de 1 à 5",
    "nps": "Recommandation (0 à 10)",
    "text": "Réponse libre",
}
MAX_QUESTIONS = 30
MAX_RECIPIENTS = 1000                   # par envoi
SEND_PAUSE_SECONDS = 0.25               # pause entre deux messages (limites Meta)
DEFAULT_MESSAGE = ("Bonjour {{name}}, votre avis compte pour nous ! "
                   "Merci de répondre à notre court sondage « {{sondage}} » : {{lien}}")
# Lot 35 — envoi par SMS : message court (un SMS = 160 caractères), lien personnel inclus.
DEFAULT_SMS = "Bonjour {{name}}, merci de repondre a notre sondage « {{sondage}} » : {{lien}}"
MAX_SMS = 800                                   # même limite que l'envoi de SMS en masse


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Modèles
# ---------------------------------------------------------------------------
class SurveyQuestion(BaseModel):
    id: Optional[str] = None
    type: str = "single"
    label: str = ""
    required: bool = True
    options: List[str] = Field(default_factory=list)   # choix unique / multiples
    help: Optional[str] = None                         # précision sous la question


class SurveyIn(BaseModel):
    title: str
    description: Optional[str] = ""
    thank_you: Optional[str] = ""
    questions: List[SurveyQuestion] = Field(default_factory=list)
    status: Optional[str] = None                       # draft | active | closed
    anonymous: bool = False                            # résultats sans nom des répondants
    closes_at: Optional[str] = None                    # date limite de réponse (facultative)
    message_text: Optional[str] = None                 # message libre proposé à l'envoi
    client_id: Optional[str] = None                    # admin/Superviseur : client propriétaire (facturation)


class RecipientsQuery(BaseModel):
    contact_ids: List[str] = Field(default_factory=list)
    group_ids: List[str] = Field(default_factory=list)
    client_ids: List[str] = Field(default_factory=list)   # comptes clients (tous leurs contacts)
    company: Optional[str] = None                          # entreprise du contact (contient)
    survey_id: Optional[str] = None                        # pour signaler « déjà invité »
    exclude_invited: bool = True
    sample_size: Optional[int] = None                      # tirage aléatoire


class SendRequest(BaseModel):
    contact_ids: List[str] = Field(default_factory=list)
    reminder: bool = False              # relance : destinataires invités qui n'ont pas répondu
    reminder_campaign_id: Optional[str] = None
    renvoi_echecs: bool = False         # lot 41 : renvoyer aux invitations en échec (ou non envoyées) sans réponse
    mode: str = "auto"                  # auto | template | text
    template_name: Optional[str] = None
    language_code: Optional[str] = "fr"
    variables: List[str] = Field(default_factory=list)
    header_text: Optional[str] = None
    button_specs: Optional[List[Dict[str, Any]]] = None
    text_message: Optional[str] = None
    title: Optional[str] = None
    channel: str = "whatsapp"           # lot 35 : whatsapp | sms (text_message = texte du SMS)


class PublicAnswer(BaseModel):
    answers: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Fonctions pures (testées sans base)
# ---------------------------------------------------------------------------
def normalize_questions(questions: List[Any], new_id: Callable[[], str]) -> List[Dict[str, Any]]:
    """Nettoie et contrôle les questions ; lève ValueError avec un message clair."""
    out = []
    if len(questions) > MAX_QUESTIONS:
        raise ValueError(f"{MAX_QUESTIONS} questions au maximum")
    seen = set()
    for i, q in enumerate(questions, start=1):
        q = q if isinstance(q, dict) else q.model_dump()
        qtype = (q.get("type") or "single").strip()
        if qtype not in QUESTION_TYPES:
            raise ValueError(f"Question {i} : type inconnu « {qtype} »")
        label = (q.get("label") or "").strip()
        if not label:
            raise ValueError(f"Question {i} : l'intitulé est vide")
        options = []
        if qtype in ("single", "multi"):
            options = [str(o).strip()[:200] for o in (q.get("options") or []) if str(o).strip()]
            options = list(dict.fromkeys(options))            # sans doublons, ordre gardé
            if len(options) < 2:
                raise ValueError(f"Question {i} : au moins 2 choix")
            if len(options) > 20:
                raise ValueError(f"Question {i} : 20 choix au maximum")
        qid = (q.get("id") or "").strip() or new_id()
        if qid in seen:
            qid = new_id()
        seen.add(qid)
        out.append({"id": qid, "type": qtype, "label": label[:500], "required": bool(q.get("required", True)),
                    "options": options, "help": (q.get("help") or "").strip()[:300] or None})
    return out


def validate_answers(questions: List[Dict[str, Any]], answers: Dict[str, Any]) -> Dict[str, Any]:
    """Contrôle les réponses d'un destinataire ; renvoie les réponses propres.
    Lève ValueError (message pour le répondant) si une réponse manque ou est invalide."""
    clean: Dict[str, Any] = {}
    for i, q in enumerate(questions, start=1):
        v = answers.get(q["id"])
        t = q["type"]
        empty = v is None or v == "" or v == []
        if empty:
            if q.get("required"):
                raise ValueError(f"Merci de répondre à la question {i} : « {q['label']} »")
            continue
        if t == "single":
            if v not in q["options"]:
                raise ValueError(f"Question {i} : choix invalide")
        elif t == "multi":
            if not isinstance(v, list) or any(x not in q["options"] for x in v):
                raise ValueError(f"Question {i} : choix invalide")
            v = [o for o in q["options"] if o in v]          # ordre du sondage
        elif t == "yesno":
            if v not in ("oui", "non"):
                raise ValueError(f"Question {i} : répondez Oui ou Non")
        elif t in ("rating", "nps"):
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise ValueError(f"Question {i} : note invalide")
            lo, hi = (1, 5) if t == "rating" else (0, 10)
            if not lo <= v <= hi:
                raise ValueError(f"Question {i} : note entre {lo} et {hi}")
        elif t == "text":
            v = str(v).strip()[:2000]
            if not v:
                if q.get("required"):
                    raise ValueError(f"Merci de répondre à la question {i} : « {q['label']} »")
                continue
        clean[q["id"]] = v
    return clean


def compute_question_stats(questions: List[Dict[str, Any]], responses: List[Dict[str, Any]],
                           anonymous: bool = False) -> List[Dict[str, Any]]:
    """Statistiques par question à partir des réponses."""
    stats = []
    for q in questions:
        vals = [r.get("answers", {}).get(q["id"]) for r in responses]
        vals = [v for v in vals if v not in (None, "", [])]
        s: Dict[str, Any] = {"id": q["id"], "type": q["type"], "label": q["label"], "answered": len(vals)}
        t = q["type"]
        if t in ("single", "multi", "yesno"):
            opts = q["options"] if t != "yesno" else ["oui", "non"]
            counts = {o: 0 for o in opts}
            for v in vals:
                for x in (v if isinstance(v, list) else [v]):
                    if x in counts:
                        counts[x] += 1
            n = len(vals) or 1
            s["options"] = [{"label": (o.capitalize() if t == "yesno" else o), "count": c,
                             "pct": round(100 * c / n, 1)} for o, c in counts.items()]
        elif t == "rating":
            nums = [int(v) for v in vals]
            s["average"] = round(sum(nums) / len(nums), 2) if nums else None
            s["distribution"] = [{"label": str(k), "count": nums.count(k)} for k in range(1, 6)]
        elif t == "nps":
            nums = [int(v) for v in vals]
            prom = sum(1 for x in nums if x >= 9)
            det = sum(1 for x in nums if x <= 6)
            n = len(nums)
            s["promoters"], s["passives"], s["detractors"] = prom, n - prom - det, det
            # Score NPS = % promoteurs − % détracteurs (de −100 à +100)
            s["nps"] = round(100 * (prom - det) / n) if n else None
            s["average"] = round(sum(nums) / n, 2) if n else None
            s["distribution"] = [{"label": str(k), "count": nums.count(k)} for k in range(0, 11)]
        elif t == "text":
            items = []
            for r in responses:
                v = r.get("answers", {}).get(q["id"])
                if v:
                    items.append({"text": v, "at": r.get("updated_at") or r.get("created_at"),
                                  "name": None if anonymous else r.get("name")})
            items.sort(key=lambda x: x["at"] or "", reverse=True)
            s["answers"] = items[:300]
        stats.append(s)
    return stats


def in_period(iso: Optional[str], date_from: Optional[str], date_to: Optional[str]) -> bool:
    """Date ISO comprise dans la période [date_from ; date_to] (jours AAAA-MM-JJ inclus).
    Sert aux bilans de période (statistiques livrées et facturées au client)."""
    d = (iso or "")[:10]
    if date_from and (not d or d < date_from[:10]):
        return False
    if date_to and (not d or d > date_to[:10]):
        return False
    return True


def rank_contributors(invites: List[Dict[str, Any]], limit: int = 20) -> List[Dict[str, Any]]:
    """Classement des meilleurs contributeurs aux sondages.
    Une ligne par contact (à défaut, par numéro) : sondages reçus, réponses,
    taux de réponse, délai moyen de réponse (heures) et dernière réponse.
    Tri : réponses, puis taux, puis rapidité."""
    by: Dict[str, Dict[str, Any]] = {}
    for i in invites:
        key = i.get("contact_id") or i.get("phone") or i.get("id")
        row = by.setdefault(key, {"contact_id": i.get("contact_id"), "name": i.get("name") or "", "company": i.get("company") or "",
                                  "tenant_id": i.get("tenant_id"), "phone": i.get("phone") or "", "received": 0,
                                  "answered": 0, "_delays": [], "last_answer_at": None, "surveys": set()})
        if i.get("status") == "sent" or i.get("answered_at"):
            row["received"] += 1
        if i.get("answered_at"):
            row["answered"] += 1
            row["surveys"].add(i.get("survey_id"))
            if not row["last_answer_at"] or i["answered_at"] > row["last_answer_at"]:
                row["last_answer_at"] = i["answered_at"]
            try:
                sent = datetime.fromisoformat(str(i.get("first_sent_at") or i.get("last_sent_at") or i.get("created_at")).replace("Z", "+00:00"))
                ans = datetime.fromisoformat(str(i["answered_at"]).replace("Z", "+00:00"))
                if ans >= sent:
                    row["_delays"].append((ans - sent).total_seconds() / 3600)
            except (TypeError, ValueError):
                pass
    out = []
    for row in by.values():
        if not row["answered"]:
            continue
        d = row.pop("_delays")
        row["surveys"] = len(row["surveys"])
        row["response_rate"] = round(100 * row["answered"] / row["received"], 1) if row["received"] else None
        row["avg_delay_hours"] = round(sum(d) / len(d), 1) if d else None
        out.append(row)
    out.sort(key=lambda r: (-r["answered"], -(r["response_rate"] or 0), r["avg_delay_hours"] if r["avg_delay_hours"] is not None else 1e9))
    for n, r in enumerate(out, start=1):
        r["rank"] = n
    return out[:limit]


def mask_phone(phone: str) -> str:
    """+226 70 12 34 56 -> 226701•••56 (affichage dans les listes)."""
    d = "".join(ch for ch in (phone or "") if ch.isdigit())
    return d if len(d) < 7 else f"{d[:5]}•••{d[-2:]}"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def attach_wa_survey_routes(
    *,
    api,
    db,
    get_current_user,
    uuid_fn: Callable[[], str],
    can_send_wa: Callable[[dict], bool],
    is_admin_like: Callable[[dict], bool],
    resolve_visible_client_ids,
    wa_enabled_for,                      # async (user) -> bool : module WhatsApp autorisé
    enforce_demo_quota,                  # async (user, increment) -> None
    wa_send_template,
    wa_send_text,
    wa_window_open: Callable[[Optional[str]], bool],
    build_recipient_ctx,
    build_components,
    public_base_url,                     # (request) -> str
    is_preview_env: Callable[[], bool] = lambda: False,
    owner_enabled=None,                  # lot 34 — async (client_id) -> bool : fonction activée pour le propriétaire
    sms_enabled_for=None,                # lot 35 — async (user) -> bool : module SMS autorisé
    sms_send=None,                       # lot 35 — async (numéro, texte) -> {ok, status, api_message, provider}
    enforce_sms_quota=None,              # lot 35 — async (user, nombre) -> None
    on_reponse=None,                     # lot 41 — async (sondage, invitation) : automatisation « survey.responded »
) -> Dict[str, Any]:
    """Branche les routes des sondages WhatsApp. Renvoie {"resume": coroutine}
    à lancer au démarrage (reprise d'un envoi interrompu par un redémarrage)."""

    def _scope(user: dict) -> str:
        # Même rattachement que les groupes de contacts : le compte client parent
        return user.get("parent_client_id") or user.get("client_id") or user["id"]

    async def _get_survey(sid: str, user: dict) -> dict:
        s = await db.wa_surveys.find_one({"id": sid}, {"_id": 0})
        if not s:
            raise HTTPException(status_code=404, detail="Sondage introuvable")
        if not is_admin_like(user):
            allowed = {_scope(user), user.get("client_id"), user["id"]}
            if s.get("client_id") not in allowed:
                raise HTTPException(status_code=404, detail="Sondage introuvable")
        return s

    async def _owner_for(user: dict, wanted: Optional[str]) -> str:
        """Client propriétaire du sondage : celui de l'utilisateur ; l'admin et le
        Superviseur peuvent le créer pour un client (il lui est alors facturé)."""
        if wanted and is_admin_like(user):
            if not await db.users.find_one({"id": wanted}, {"_id": 0, "id": 1}):
                raise HTTPException(status_code=400, detail="Client inconnu")
            return wanted
        return _scope(user)

    def _clean_in(payload: SurveyIn) -> Dict[str, Any]:
        title = (payload.title or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="Donnez un titre au sondage")
        try:
            questions = normalize_questions(payload.questions, uuid_fn)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        status = payload.status or "draft"
        if status not in ("draft", "active", "closed"):
            raise HTTPException(status_code=400, detail="Statut invalide")
        if status == "active" and not questions:
            raise HTTPException(status_code=400, detail="Ajoutez au moins une question avant d'ouvrir le sondage")
        return {
            "title": title[:200],
            "description": (payload.description or "").strip()[:2000],
            "thank_you": (payload.thank_you or "").strip()[:1000],
            "questions": questions,
            "status": status,
            "anonymous": bool(payload.anonymous),
            "closes_at": payload.closes_at or None,
            "message_text": (payload.message_text or "").strip()[:1000] or None,
        }

    # ---- Liste / CRUD -----------------------------------------------------
    @api.get("/me/wa-surveys", tags=["Sondages WhatsApp"])
    async def list_surveys(user: dict = Depends(get_current_user)):
        q = {} if is_admin_like(user) else {"client_id": {"$in": list({_scope(user), user.get("client_id") or user["id"], user["id"]})}}
        items = await db.wa_surveys.find(q, {"_id": 0}).sort("updated_at", -1).to_list(500)
        ids = [s["id"] for s in items]
        # Compteurs par sondage en 2 agrégations (invités, ouverts, répondus)
        counts: Dict[str, Dict[str, int]] = {i: {"invited": 0, "sent": 0, "answered": 0, "opened": 0} for i in ids}
        async for row in db.wa_survey_invites.aggregate([
            {"$match": {"survey_id": {"$in": ids}}},
            {"$group": {"_id": "$survey_id", "invited": {"$sum": 1},
                        "sent": {"$sum": {"$cond": [{"$eq": ["$status", "sent"]}, 1, 0]}},
                        "opened": {"$sum": {"$cond": [{"$ifNull": ["$opened_at", False]}, 1, 0]}},
                        "answered": {"$sum": {"$cond": [{"$ifNull": ["$answered_at", False]}, 1, 0]}}}},
        ]):
            counts[row["_id"]] = {k: row.get(k, 0) for k in ("invited", "sent", "opened", "answered")}
        owners = {}
        async for u in db.users.find({"id": {"$in": list({s.get("client_id") for s in items if s.get("client_id")})}},
                                     {"_id": 0, "id": 1, "company": 1, "full_name": 1}):
            owners[u["id"]] = u.get("company") or u.get("full_name") or u["id"]
        for s in items:
            s["client_name"] = owners.get(s.get("client_id"), "")
            c = counts.get(s["id"]) or {}
            s["stats"] = {**c, "response_rate": round(100 * c.get("answered", 0) / c["sent"], 1) if c.get("sent") else None}
            s["questions_count"] = len(s.get("questions") or [])
            s.pop("questions", None)
        return {"items": items, "question_types": QUESTION_TYPES}

    @api.post("/me/wa-surveys", tags=["Sondages WhatsApp"])
    async def create_survey(payload: SurveyIn, user: dict = Depends(get_current_user)):
        doc = {
            "id": uuid_fn(), **_clean_in(payload), "client_id": await _owner_for(user, payload.client_id),
            "created_by_id": user["id"], "created_by_label": user.get("full_name") or user.get("email"),
            "created_at": _now(), "updated_at": _now(),
        }
        await db.wa_surveys.insert_one(doc.copy())
        return doc

    @api.get("/me/wa-surveys/{sid}", tags=["Sondages WhatsApp"])
    async def get_survey(sid: str, user: dict = Depends(get_current_user)):
        s = await _get_survey(sid, user)
        s["answered_count"] = await db.wa_survey_responses.count_documents({"survey_id": sid})
        return s

    @api.put("/me/wa-surveys/{sid}", tags=["Sondages WhatsApp"])
    async def update_survey(sid: str, payload: SurveyIn, user: dict = Depends(get_current_user)):
        await _get_survey(sid, user)
        upd = {**_clean_in(payload), "updated_at": _now()}
        if payload.client_id and is_admin_like(user):
            upd["client_id"] = await _owner_for(user, payload.client_id)     # changement de client propriétaire
        await db.wa_surveys.update_one({"id": sid}, {"$set": upd})
        return await _get_survey(sid, user)

    @api.delete("/me/wa-surveys/{sid}", tags=["Sondages WhatsApp"])
    async def delete_survey(sid: str, user: dict = Depends(get_current_user)):
        await _get_survey(sid, user)
        await db.wa_surveys.delete_one({"id": sid})
        for coll in (db.wa_survey_invites, db.wa_survey_responses, db.wa_survey_campaigns):
            await coll.delete_many({"survey_id": sid})
        return {"ok": True}

    @api.post("/me/wa-surveys/{sid}/duplicate", tags=["Sondages WhatsApp"])
    async def duplicate_survey(sid: str, user: dict = Depends(get_current_user)):
        s = await _get_survey(sid, user)
        doc = {**s, "id": uuid_fn(), "title": f"{s['title']} (copie)"[:200], "status": "draft",
               "client_id": _scope(user), "created_by_id": user["id"],
               "created_by_label": user.get("full_name") or user.get("email"),
               "created_at": _now(), "updated_at": _now()}
        doc.pop("answered_count", None)
        await db.wa_surveys.insert_one(doc.copy())
        return doc

    # ---- Destinataires ----------------------------------------------------
    async def _client_contact_filter(client_id: str) -> Optional[dict]:
        """Contacts d'un compte client : ceux enregistrés par ce compte (et les
        comptes de la même entreprise) + ceux dont l'entreprise porte son nom."""
        u = await db.users.find_one({"id": client_id}, {"_id": 0, "id": 1, "client_id": 1,
                                                        "parent_client_id": 1, "company": 1})
        if not u:
            return None
        ids = {v for v in (u.get("id"), u.get("client_id"), u.get("parent_client_id")) if v}
        company = (u.get("company") or "").strip()
        ors: List[dict] = []
        if company:
            async for peer in db.users.find({"company": {"$regex": f"^{re.escape(company)}$", "$options": "i"}},
                                            {"_id": 0, "id": 1, "client_id": 1}):
                ids.update(v for v in (peer.get("id"), peer.get("client_id")) if v)
            ors.append({"company": {"$regex": f"^{re.escape(company)}$", "$options": "i"}})
        ors.append({"client_id": {"$in": list(ids)}})
        return {"$or": ors}

    async def _resolve_contacts(user: dict, q: RecipientsQuery) -> List[dict]:
        visible = None if is_admin_like(user) else await resolve_visible_client_ids(user)
        ors: List[dict] = []
        if q.contact_ids:
            ors.append({"id": {"$in": q.contact_ids[:5000]}})
        if q.group_ids:
            gq: Dict[str, Any] = {"id": {"$in": q.group_ids}}
            if visible is not None:
                gq["$or"] = [{"client_id": {"$in": visible + [_scope(user)]}}, {"shared_with_tenant": True}]
            ids: List[str] = []
            async for g in db.contact_groups.find(gq, {"_id": 0, "contact_ids": 1}):
                ids.extend(g.get("contact_ids") or [])
            if ids:
                ors.append({"id": {"$in": list(dict.fromkeys(ids))}})
        for cid in q.client_ids[:50]:
            f = await _client_contact_filter(cid)
            if f:
                ors.append(f)
        if (q.company or "").strip():
            ors.append({"company": {"$regex": re.escape(q.company.strip()), "$options": "i"}})
        if not ors:
            return []
        query: Dict[str, Any] = {"$or": ors}
        if visible is not None:
            query = {"$and": [query, {"client_id": {"$in": visible}}]}     # jamais hors de son périmètre
        rows = await db.directory_contacts.find(query, {"_id": 0}).to_list(20000)
        # Un seul envoi par numéro WhatsApp
        out, seen = [], set()
        for c in rows:
            phone = (c.get("whatsapp") or c.get("phone") or "").strip()
            digits = "".join(ch for ch in phone if ch.isdigit())
            if not digits or digits in seen:
                continue
            seen.add(digits)
            out.append({**c, "_phone": phone, "_digits": digits})
        return out

    async def _open_window_digits(digits: List[str]) -> set:
        """Numéros qui ont écrit dans les dernières 24 h (message libre possible)."""
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        found = set()
        async for m in db.whatsapp_messages.find(
                {"direction": "inbound", "phone_digits": {"$in": digits}, "created_at": {"$gte": since}},
                {"_id": 0, "phone_digits": 1, "created_at": 1}):
            if wa_window_open(m.get("created_at")):
                found.add(m.get("phone_digits"))
        return found

    @api.post("/me/wa-surveys/recipients/preview", tags=["Sondages WhatsApp"])
    async def preview_recipients(payload: RecipientsQuery, user: dict = Depends(get_current_user)):
        contacts = await _resolve_contacts(user, payload)
        invited: Dict[str, dict] = {}
        if payload.survey_id:
            async for inv in db.wa_survey_invites.find({"survey_id": payload.survey_id},
                                                      {"_id": 0, "contact_id": 1, "status": 1, "answered_at": 1}):
                invited[inv.get("contact_id")] = inv
        total_found = len(contacts)
        excluded = 0
        if payload.exclude_invited and invited:
            before = len(contacts)
            contacts = [c for c in contacts if c["id"] not in invited]
            excluded = before - len(contacts)
        sampled = False
        if payload.sample_size and 0 < payload.sample_size < len(contacts):
            contacts = random.sample(contacts, payload.sample_size)     # échantillon aléatoire
            sampled = True
        window = await _open_window_digits([c["_digits"] for c in contacts])
        items = [{
            "id": c["id"], "name": c.get("name") or c.get("company") or c["_phone"],
            "company": c.get("company") or "", "phone": mask_phone(c["_phone"]),
            "window_open": c["_digits"] in window,
            "already_invited": c["id"] in invited,
            "already_answered": bool((invited.get(c["id"]) or {}).get("answered_at")),
        } for c in contacts]
        items.sort(key=lambda x: (x["company"].lower(), x["name"].lower()))
        return {"items": items, "total_found": total_found, "excluded_invited": excluded,
                "sampled": sampled, "window_open_count": sum(1 for i in items if i["window_open"])}

    # ---- Envoi ------------------------------------------------------------
    _running: Dict[str, asyncio.Task] = {}

    async def _send_one(camp: dict, survey: dict, inv: dict) -> Dict[str, Any]:
        """Envoie l'invitation `inv` (modèle Meta ou message libre)."""
        link = f"{camp.get('base_url') or ''}/s/{inv['token']}"
        contact_doc = {"full_name": inv.get("name"), "company": inv.get("company"),
                       "phone": inv.get("phone"), "email": inv.get("email"),
                       "client_code": inv.get("unique_code")}
        ctx = build_recipient_ctx("contact", contact_doc, inv.get("phone"), inv.get("name"))
        # Jetons propres aux sondages : {{lien}}, {{jeton}}, {{sondage}}, {{name}}
        ctx.update({"lien": link, "lien_sondage": link, "jeton": inv["token"],
                    "sondage": survey.get("title") or "", "name": ctx.get("full_name") or "",
                    "nom": ctx.get("full_name") or ""})
        mode = camp.get("mode") or "auto"
        if mode == "sms":
            # Lot 35 — SMS : même lien personnel, pas de fenêtre de 24 h ni de modèle Meta.
            text = camp.get("text_message") or DEFAULT_SMS
            body = re.sub(r"\{\{\s*([a-zA-Z_]+)\s*\}\}", lambda m: str(ctx.get(m.group(1).lower(), "")), text)
            if "/s/" not in body:
                body = f"{body} {link}"                      # le lien est toujours présent
            res = await sms_send(inv["phone"], body)
            return {"ok": bool(res.get("ok")), "status": res.get("status"), "provider": res.get("provider"),
                    "error": None if res.get("ok") else (res.get("api_message") or "Échec de l'envoi du SMS"),
                    "channel": "sms", "body": body}
        use_text = mode == "text" or (mode == "auto" and inv.get("_window_open"))
        if use_text:
            if not inv.get("_window_open"):
                return {"ok": False, "skipped": True,
                        "error": "Fenêtre 24 h fermée : ce contact ne vous a pas écrit récemment (utilisez un modèle Meta)"}
            text = camp.get("text_message") or survey.get("message_text") or DEFAULT_MESSAGE
            body = re.sub(r"\{\{\s*([a-zA-Z_]+)\s*\}\}", lambda m: str(ctx.get(m.group(1).lower(), "")), text)
            if "/s/" not in body:
                body = f"{body}\n{link}"                     # le lien est toujours présent
            res = await wa_send_text(inv["phone"], body)
            return {**res, "channel": "text", "body": body}
        if not camp.get("template_name"):
            return {"ok": False, "skipped": True, "error": "Aucun modèle Meta choisi (contact hors fenêtre de 24 h)"}
        components = build_components(camp.get("variables") or [], ctx, header_text=camp.get("header_text"),
                                      button_specs=camp.get("button_specs"))
        res = await wa_send_template(inv["phone"], camp["template_name"], camp.get("language_code") or "fr", components)
        return {**res, "channel": "template", "body": f"[Sondage] {survey.get('title')} — {link}"}

    async def _run_campaign(camp_id: str) -> None:
        """Tâche de fond : envoie les invitations en attente de la campagne."""
        camp = await db.wa_survey_campaigns.find_one({"id": camp_id}, {"_id": 0})
        if not camp:
            return
        survey = await db.wa_surveys.find_one({"id": camp["survey_id"]}, {"_id": 0}) or {}
        pending = await db.wa_survey_invites.find(
            {"id": {"$in": camp.get("invite_ids") or []}, "pending_campaign_id": camp_id}, {"_id": 0}).to_list(None)
        window = await _open_window_digits(["".join(ch for ch in (i.get("phone") or "") if ch.isdigit()) for i in pending])
        for inv in pending:
            inv["_window_open"] = "".join(ch for ch in (inv.get("phone") or "") if ch.isdigit()) in window
            try:
                res = await _send_one(camp, survey, inv)
            except Exception as exc:  # noqa: BLE001
                res = {"ok": False, "error": str(exc)[:300]}
            ok = bool(res.get("ok"))
            skipped = bool(res.get("skipped"))
            upd: Dict[str, Any] = {"pending_campaign_id": None, "error": None if ok else (res.get("error") or "Échec")}
            inc: Dict[str, int] = {}
            if ok:
                upd.update({"status": "sent", "last_sent_at": _now(), "message_id": res.get("message_id"),
                            "channel": res.get("channel")})
                if not inv.get("first_sent_at"):
                    upd["first_sent_at"] = upd["last_sent_at"]
                inc["sent_count"] = 1
            elif inv.get("status") != "sent":
                upd["status"] = "skipped" if skipped else "failed"   # une relance ratée garde « envoyé »
            await db.wa_survey_invites.update_one({"id": inv["id"]}, {"$set": upd, **({"$inc": inc} if inc else {})})
            await db.wa_survey_campaigns.update_one(
                {"id": camp_id},
                {"$inc": {"done": 1, "sent_ok": 1 if ok else 0, "sent_ko": 0 if ok or skipped else 1,
                          "skipped": 1 if skipped else 0},
                 "$set": {"updated_at": _now()}})
            if res.get("channel") == "sms":
                # Lot 35 — trace dans l'historique des SMS (même forme que l'envoi de SMS en masse)
                try:
                    await db.sms_messages.insert_one({
                        "id": uuid_fn(), "client_id": camp.get("client_id"), "user_id": camp.get("created_by_id"),
                        "user_label": camp.get("created_by_label"), "contact_id": inv.get("contact_id"),
                        "provider": res.get("provider"), "sender": None, "msisdn": inv.get("phone"),
                        "msisdn_digits": "".join(ch for ch in (inv.get("phone") or "") if ch.isdigit()),
                        "message": res.get("body"), "length": len(res.get("body") or ""),
                        "status": res.get("status"), "api_message": res.get("error"), "bulk": True,
                        "survey_id": camp["survey_id"], "created_at": _now(),
                    })
                except Exception:  # noqa: BLE001
                    logger.warning("[wa-surveys] trace du SMS impossible", exc_info=True)
            elif ok or not skipped:
                # Trace dans la conversation du contact (Centre de Messagerie)
                digits = "".join(ch for ch in (inv.get("phone") or "") if ch.isdigit())
                try:
                    await db.whatsapp_messages.insert_one({
                        "id": uuid_fn(), "client_id": camp.get("client_id"), "direction": "outbound",
                        "sender_id": camp.get("created_by_id"), "sender_label": camp.get("created_by_label"),
                        "to": inv.get("phone"), "phone_digits": digits,
                        "template_name": camp.get("template_name") if res.get("channel") == "template" else None,
                        "language_code": camp.get("language_code") if res.get("channel") == "template" else None,
                        "message_type": "text" if res.get("channel") == "text" else "template",
                        "body": res.get("body"), "contact_id": inv.get("contact_id"),
                        "recipient_kind": "contact", "recipient_label": inv.get("name"),
                        "bulk": True, "survey_id": camp["survey_id"], "ok": ok, "status": res.get("status"),
                        "message_id": res.get("message_id"), "error": res.get("error"),
                        "wa_status": "sent" if ok else "failed",
                        "sent_at": _now() if ok else None, "failed_at": None if ok else _now(),
                        "created_at": _now(),
                    })
                except Exception:  # noqa: BLE001
                    logger.warning("[wa-surveys] trace du message impossible", exc_info=True)
            await asyncio.sleep(SEND_PAUSE_SECONDS)
        await db.wa_survey_campaigns.update_one({"id": camp_id}, {"$set": {"status": "done", "finished_at": _now()}})
        _running.pop(camp_id, None)

    def _launch(camp_id: str) -> None:
        if camp_id in _running and not _running[camp_id].done():
            return
        _running[camp_id] = asyncio.create_task(_run_campaign(camp_id))

    @api.post("/me/wa-surveys/{sid}/send", tags=["Sondages WhatsApp"])
    async def send_survey(sid: str, payload: SendRequest, request: Request, user: dict = Depends(get_current_user)):
        par_sms = payload.channel == "sms"                  # lot 35 : envoi du lien par SMS
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
        survey = await _get_survey(sid, user)
        if not survey.get("questions"):
            raise HTTPException(status_code=400, detail="Ce sondage n'a aucune question")
        if survey.get("status") == "closed":
            raise HTTPException(status_code=400, detail="Ce sondage est clôturé : rouvrez-le avant de l'envoyer")
        mode = payload.mode if payload.mode in ("auto", "template", "text") else "auto"
        if par_sms:
            mode = "sms"                                    # ni modèle Meta, ni fenêtre de 24 h
        if mode == "template" and not (payload.template_name or "").strip():
            raise HTTPException(status_code=400, detail="Choisissez un modèle Meta")
        # Le lien doit figurer dans le message modèle
        if mode in ("template", "auto") and payload.template_name and not par_sms:
            flat = " ".join((payload.variables or []) + [payload.header_text or ""]
                            + [str(p.get("text") if isinstance(p, dict) else p)
                               for b in (payload.button_specs or []) for p in (b.get("parameters") or [])])
            if not re.search(r"\{\{\s*(lien|lien_sondage|jeton)\s*\}\}", flat):
                raise HTTPException(status_code=400, detail=(
                    "Placez {{lien}} dans une variable du modèle (ou {{jeton}} dans la partie variable "
                    "d'un bouton lien) : sinon le destinataire ne reçoit pas le lien du sondage"))
        if mode == "auto" and not payload.template_name:
            mode = "text"                                   # sans modèle : seulement les fenêtres ouvertes

        # Destinataires : relance (non-répondants) ou contacts choisis
        invites: List[dict] = []
        if payload.renvoi_echecs:
            # Lot 41 — nouvel essai pour les invitations en échec ou non envoyées (ex. erreur
            # Meta #132000 corrigée, fenêtre de 24 h fermée : cette fois avec un modèle).
            invites = await db.wa_survey_invites.find(
                {"survey_id": sid, "answered_at": None, "status": {"$in": ["failed", "skipped"]}},
                {"_id": 0}).to_list(MAX_RECIPIENTS + 1)
            if not invites:
                raise HTTPException(status_code=400, detail="Aucune invitation en échec à renvoyer")
        elif payload.reminder:
            iq: Dict[str, Any] = {"survey_id": sid, "answered_at": None, "status": "sent"}
            if payload.reminder_campaign_id:
                iq["campaign_ids"] = payload.reminder_campaign_id
            invites = await db.wa_survey_invites.find(iq, {"_id": 0}).to_list(MAX_RECIPIENTS + 1)
            if not invites:
                raise HTTPException(status_code=400, detail="Personne à relancer : tous les destinataires ont répondu")
        else:
            if not payload.contact_ids:
                raise HTTPException(status_code=400, detail="Aucun destinataire sélectionné")
            contacts = await _resolve_contacts(user, RecipientsQuery(contact_ids=payload.contact_ids))
            if not contacts:
                raise HTTPException(status_code=404, detail="Aucun contact avec un numéro de téléphone retrouvé parmi la sélection")
            existing = {i["contact_id"]: i async for i in db.wa_survey_invites.find(
                {"survey_id": sid, "contact_id": {"$in": [c["id"] for c in contacts]}}, {"_id": 0})}
            for c in contacts:
                inv = existing.get(c["id"])
                if not inv:
                    # Une invitation (un lien personnel) par contact et par sondage
                    inv = {"id": uuid_fn(), "token": secrets.token_urlsafe(9), "survey_id": sid,
                           "contact_id": c["id"], "client_id": c.get("client_id"),
                           "name": c.get("name") or c.get("company") or c["_phone"],
                           "company": c.get("company") or "", "email": c.get("email") or "",
                           "unique_code": c.get("unique_code") or "", "phone": c["_phone"],
                           "status": "queued", "sent_count": 0, "opened_at": None, "answered_at": None,
                           "campaign_ids": [], "created_at": _now()}
                    await db.wa_survey_invites.insert_one(inv.copy())
                invites.append(inv)
        if len(invites) > MAX_RECIPIENTS:
            raise HTTPException(status_code=400, detail=f"Maximum {MAX_RECIPIENTS} destinataires par envoi")
        if par_sms:
            if enforce_sms_quota is not None:
                await enforce_sms_quota(user, len(invites))
        else:
            await enforce_demo_quota(user, len(invites))
        if survey.get("status") == "draft":
            await db.wa_surveys.update_one({"id": sid}, {"$set": {"status": "active", "updated_at": _now()}})

        camp = {
            "id": uuid_fn(), "survey_id": sid, "client_id": _scope(user),
            "kind": "resend" if payload.renvoi_echecs else ("reminder" if payload.reminder else "send"),
            "title": (payload.title or "").strip()[:200] or None, "mode": mode,
            "template_name": None if par_sms else ((payload.template_name or "").strip() or None),
            "language_code": payload.language_code or "fr", "variables": [] if par_sms else (payload.variables or []),
            "header_text": payload.header_text, "button_specs": payload.button_specs,
            "text_message": (payload.text_message or "").strip() or None,
            "base_url": (public_base_url(request) or "").rstrip("/"),
            "invite_ids": [i["id"] for i in invites], "total": len(invites),
            "done": 0, "sent_ok": 0, "sent_ko": 0, "skipped": 0, "status": "running",
            "created_by_id": user["id"], "created_by_label": user.get("full_name") or user.get("email"),
            "created_at": _now(), "updated_at": _now(),
        }
        await db.wa_survey_campaigns.insert_one(camp.copy())
        await db.wa_survey_invites.update_many(
            {"id": {"$in": camp["invite_ids"]}},
            {"$set": {"pending_campaign_id": camp["id"]}, "$addToSet": {"campaign_ids": camp["id"]}})
        _launch(camp["id"])
        camp.pop("invite_ids", None)
        return {"ok": True, "campaign": camp}

    @api.get("/me/wa-surveys/{sid}/campaigns", tags=["Sondages WhatsApp"])
    async def list_campaigns(sid: str, user: dict = Depends(get_current_user)):
        await _get_survey(sid, user)
        items = await db.wa_survey_campaigns.find({"survey_id": sid}, {"_id": 0, "invite_ids": 0,
                                                                      "button_specs": 0}).sort("created_at", -1).to_list(200)
        return {"items": items}

    # ---- Résultats --------------------------------------------------------
    @api.get("/me/wa-surveys/{sid}/results", tags=["Sondages WhatsApp"])
    async def survey_results(sid: str, campaign_id: Optional[str] = None, date_from: Optional[str] = None,
                             date_to: Optional[str] = None, user: dict = Depends(get_current_user)):
        s = await _get_survey(sid, user)
        iq: Dict[str, Any] = {"survey_id": sid}
        if campaign_id:
            iq["campaign_ids"] = campaign_id
        invites = await db.wa_survey_invites.find(iq, {"_id": 0}).to_list(None)
        inv_by_id = {i["id"]: i for i in invites}
        responses = await db.wa_survey_responses.find({"survey_id": sid}, {"_id": 0}).to_list(None)
        if campaign_id:
            responses = [r for r in responses if r.get("invite_id") in inv_by_id]
        if date_from or date_to:
            # Période : invitations envoyées et réponses reçues pendant la période
            invites = [i for i in invites if in_period(i.get("last_sent_at") or i.get("created_at"), date_from, date_to)]
            responses = [r for r in responses if in_period(r.get("created_at"), date_from, date_to)]
            answered_ids = {r.get("invite_id") for r in responses}
            invites = [{**i, "answered_at": i.get("answered_at") if i["id"] in answered_ids else None} for i in invites]
        for r in responses:
            r["name"] = (inv_by_id.get(r.get("invite_id")) or {}).get("name")
        sent = sum(1 for i in invites if i.get("status") == "sent")
        opened = sum(1 for i in invites if i.get("opened_at"))
        answered = sum(1 for i in invites if i.get("answered_at"))
        # Taux par entreprise (échantillonnage)
        by_company: Dict[str, Dict[str, int]] = {}
        for i in invites:
            k = i.get("company") or "(sans entreprise)"
            b = by_company.setdefault(k, {"invited": 0, "sent": 0, "answered": 0})
            b["invited"] += 1
            b["sent"] += 1 if i.get("status") == "sent" else 0
            b["answered"] += 1 if i.get("answered_at") else 0
        companies = sorted(({"company": k, **v, "rate": round(100 * v["answered"] / v["sent"], 1) if v["sent"] else None}
                            for k, v in by_company.items()), key=lambda x: -x["invited"])[:50]
        # Réponses par jour
        per_day: Dict[str, int] = {}
        for r in responses:
            d = (r.get("created_at") or "")[:10]
            per_day[d] = per_day.get(d, 0) + 1
        return {
            "survey": {k: s.get(k) for k in ("id", "title", "status", "anonymous", "closes_at")},
            "period": {"date_from": date_from, "date_to": date_to},
            "totals": {"invited": len(invites), "sent": sent, "failed": sum(1 for i in invites if i.get("status") == "failed"),
                       "skipped": sum(1 for i in invites if i.get("status") == "skipped"),
                       "opened": opened, "answered": answered,
                       "open_rate": round(100 * opened / sent, 1) if sent else None,
                       "response_rate": round(100 * answered / sent, 1) if sent else None},
            "questions": compute_question_stats(s.get("questions") or [], responses, bool(s.get("anonymous"))),
            "by_company": companies,
            "timeline": [{"date": d, "count": c} for d, c in sorted(per_day.items())],
        }

    @api.get("/me/wa-surveys-contributors", tags=["Sondages WhatsApp"])
    async def top_contributors(client_id: Optional[str] = None, survey_id: Optional[str] = None,
                               date_from: Optional[str] = None, date_to: Optional[str] = None,
                               limit: int = 20, user: dict = Depends(get_current_user)):
        """Meilleurs contributeurs aux sondages WhatsApp : pour un client (tenant)
        ou, pour l'admin/Superviseur, pour tous les clients (« globalement »).
        Renvoie aussi le classement des clients (tenants) par nombre de réponses."""
        limit = max(1, min(int(limit or 20), 200))
        sq: Dict[str, Any] = {}
        if not is_admin_like(user):
            sq["client_id"] = {"$in": list({_scope(user), user.get("client_id") or user["id"], user["id"]})}
        elif client_id:
            sq["client_id"] = client_id
        if survey_id:
            sq["id"] = survey_id
        surveys = await db.wa_surveys.find(sq, {"_id": 0, "id": 1, "client_id": 1, "title": 1, "anonymous": 1}).to_list(5000)
        tenant_of = {s["id"]: s.get("client_id") for s in surveys}
        anonymous_ids = {s["id"] for s in surveys if s.get("anonymous")}
        invites = await db.wa_survey_invites.find({"survey_id": {"$in": list(tenant_of)}}, {"_id": 0}).to_list(None)
        if date_from or date_to:
            invites = [i for i in invites if in_period(i.get("answered_at") or i.get("last_sent_at") or i.get("created_at"),
                                                       date_from, date_to)]
            invites = [{**i, "answered_at": i.get("answered_at") if in_period(i.get("answered_at"), date_from, date_to) else None}
                       for i in invites]
        # Les réponses aux sondages anonymes comptent, mais sans nom
        for i in invites:
            i["tenant_id"] = tenant_of.get(i["survey_id"])
        named = [i for i in invites if i["survey_id"] not in anonymous_ids]
        rows = rank_contributors(named, limit)
        for r in rows:
            r["phone"] = mask_phone(r.get("phone"))
        # Classement des clients (tenants) : réponses reçues et taux
        tenants: Dict[str, Dict[str, Any]] = {}
        for i in invites:
            t = tenants.setdefault(i["tenant_id"] or "—", {"tenant_id": i["tenant_id"], "sent": 0, "answered": 0, "respondents": set()})
            t["sent"] += 1 if (i.get("status") == "sent" or i.get("answered_at")) else 0
            if i.get("answered_at"):
                t["answered"] += 1
                t["respondents"].add(i.get("contact_id") or i.get("phone"))
        names = {}
        if tenants:
            async for u in db.users.find({"id": {"$in": [k for k in tenants if k != "—"]}},
                                         {"_id": 0, "id": 1, "company": 1, "full_name": 1, "client_code": 1}):
                names[u["id"]] = u.get("company") or u.get("full_name") or u["id"]
        tenant_rows = sorted(({"tenant_id": t["tenant_id"], "name": names.get(t["tenant_id"], t["tenant_id"] or "—"),
                               "sent": t["sent"], "answered": t["answered"], "respondents": len(t["respondents"]),
                               "response_rate": round(100 * t["answered"] / t["sent"], 1) if t["sent"] else None}
                              for t in tenants.values()), key=lambda x: -x["answered"])
        for r in rows:
            r["tenant_name"] = names.get(r.get("tenant_id"), "")
        return {"items": rows, "tenants": tenant_rows[:100], "scope": "global" if is_admin_like(user) and not client_id else "tenant",
                "anonymous_excluded": sum(1 for i in invites if i["survey_id"] in anonymous_ids and i.get("answered_at"))}

    @api.get("/me/wa-surveys/{sid}/invites", tags=["Sondages WhatsApp"])
    async def survey_invites(sid: str, status: Optional[str] = None, user: dict = Depends(get_current_user)):
        s = await _get_survey(sid, user)
        q: Dict[str, Any] = {"survey_id": sid}
        if status == "answered":
            q["answered_at"] = {"$ne": None}
        elif status == "waiting":
            q.update({"answered_at": None, "status": "sent"})
        elif status in ("failed", "skipped", "queued"):
            q["status"] = status
        rows = await db.wa_survey_invites.find(q, {"_id": 0}).sort("created_at", -1).to_list(5000)
        items = [{
            "id": r["id"], "contact_id": r.get("contact_id"),
            "name": "Répondant anonyme" if s.get("anonymous") and r.get("answered_at") else r.get("name"),
            "company": r.get("company"), "phone": mask_phone(r.get("phone")), "status": r.get("status"),
            "sent_count": r.get("sent_count", 0), "last_sent_at": r.get("last_sent_at"),
            "opened_at": r.get("opened_at"), "answered_at": r.get("answered_at"), "error": r.get("error"),
        } for r in rows]
        return {"items": items}

    @api.get("/me/wa-surveys/{sid}/export.csv", tags=["Sondages WhatsApp"])
    async def export_csv(sid: str, date_from: Optional[str] = None, date_to: Optional[str] = None,
                         user: dict = Depends(get_current_user)):
        s = await _get_survey(sid, user)
        questions = s.get("questions") or []
        invites = {i["id"]: i for i in await db.wa_survey_invites.find({"survey_id": sid}, {"_id": 0}).to_list(None)}
        responses = await db.wa_survey_responses.find({"survey_id": sid}, {"_id": 0}).sort("created_at", 1).to_list(None)
        responses = [r for r in responses if in_period(r.get("created_at"), date_from, date_to)]
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        head = ["Date"] + ([] if s.get("anonymous") else ["Nom", "Entreprise", "Téléphone"]) + [q["label"] for q in questions]
        w.writerow(head)
        for r in responses:
            inv = invites.get(r.get("invite_id")) or {}
            row = [(r.get("updated_at") or r.get("created_at") or "")[:16].replace("T", " ")]
            if not s.get("anonymous"):
                row += [inv.get("name") or "", inv.get("company") or "", inv.get("phone") or ""]
            for q in questions:
                v = (r.get("answers") or {}).get(q["id"])
                row.append(", ".join(v) if isinstance(v, list) else ("" if v is None else str(v)))
            w.writerow(row)
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", s.get("title") or "sondage")[:60] or "sondage"
        # BOM UTF-8 : Excel ouvre les accents correctement
        return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})

    # ---- Page publique (sans compte) --------------------------------------
    async def _public_ctx(token: str):
        inv = await db.wa_survey_invites.find_one({"token": token}, {"_id": 0})
        if not inv:
            raise HTTPException(status_code=404, detail="Lien de sondage invalide")
        s = await db.wa_surveys.find_one({"id": inv["survey_id"]}, {"_id": 0})
        if not s:
            raise HTTPException(status_code=404, detail="Ce sondage n'existe plus")
        # Lot 34 — « Formulaires et Sondages » désactivé pour le client propriétaire : lien inactif.
        if owner_enabled is not None and not await owner_enabled(s.get("client_id")):
            raise HTTPException(status_code=404, detail="Ce sondage n'est plus disponible")
        closed = s.get("status") == "closed"
        if not closed and s.get("closes_at"):
            try:
                end = datetime.fromisoformat(str(s["closes_at"]).replace("Z", "+00:00"))
                if end.tzinfo is None:
                    end = end.replace(tzinfo=timezone.utc)
                closed = datetime.now(timezone.utc) > end
            except ValueError:
                pass
        return inv, s, closed

    @api.get("/public/surveys/{token}", tags=["Sondages WhatsApp"])
    async def public_get(token: str):
        inv, s, closed = await _public_ctx(token)
        if not inv.get("opened_at"):
            await db.wa_survey_invites.update_one({"id": inv["id"]}, {"$set": {"opened_at": _now()}})
        resp = await db.wa_survey_responses.find_one({"invite_id": inv["id"]}, {"_id": 0, "answers": 1})
        first = (inv.get("name") or "").split(" ")[0] if not s.get("anonymous") else ""
        return {
            "title": s.get("title"), "description": s.get("description"), "thank_you": s.get("thank_you"),
            "questions": s.get("questions") or [], "closed": closed, "anonymous": bool(s.get("anonymous")),
            "respondent": first, "already_answered": bool(resp), "answers": (resp or {}).get("answers") or {},
        }

    @api.post("/public/surveys/{token}", tags=["Sondages WhatsApp"])
    async def public_answer(token: str, payload: PublicAnswer):
        inv, s, closed = await _public_ctx(token)
        if closed:
            raise HTTPException(status_code=409, detail="Ce sondage est clôturé : les réponses ne sont plus acceptées")
        try:
            answers = validate_answers(s.get("questions") or [], payload.answers or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        existing = await db.wa_survey_responses.find_one({"invite_id": inv["id"]}, {"_id": 0, "id": 1})
        if existing:
            await db.wa_survey_responses.update_one(
                {"id": existing["id"]}, {"$set": {"answers": answers, "updated_at": _now()}, "$inc": {"revisions": 1}})
        else:
            await db.wa_survey_responses.insert_one({
                "id": uuid_fn(), "survey_id": s["id"], "invite_id": inv["id"], "contact_id": inv.get("contact_id"),
                "answers": answers, "created_at": _now(), "updated_at": _now(), "revisions": 0})
            if on_reponse is not None:                 # lot 41 : nouvelle réponse (pas une modification)
                try:
                    await on_reponse(s, inv)
                except Exception:  # noqa: BLE001 — l'automatisation ne bloque jamais la réponse
                    pass
        await db.wa_survey_invites.update_one(
            {"id": inv["id"]}, {"$set": {"answered_at": inv.get("answered_at") or _now(),
                                         "opened_at": inv.get("opened_at") or _now()}})
        return {"ok": True, "thank_you": s.get("thank_you") or "Merci pour vos réponses !"}

    # ---- Reprise après redémarrage ----------------------------------------
    async def resume() -> None:
        """Relance les envois interrompus (redémarrage du serveur pendant un envoi).
        Jamais dans la preview : sa base est une copie de la production."""
        if is_preview_env():
            return
        try:
            await db.wa_survey_invites.create_index("token", unique=True)
            await db.wa_survey_invites.create_index([("survey_id", 1), ("contact_id", 1)])
            await db.wa_survey_responses.create_index("invite_id", unique=True)
        except Exception:  # noqa: BLE001
            pass
        async for c in db.wa_survey_campaigns.find({"status": "running"}, {"_id": 0, "id": 1}):
            _launch(c["id"])

    return {"resume": resume, "run_campaign": _run_campaign, "running": _running}
