"""Iter43-fix22 (2026-06) — Tableau de suivi des requêtes WhatsApp à Liluvine.

Vue d'ensemble :
  - Listing des messages WA entrants groupés par numéro
  - Pour chaque numéro : nom affiché, identité Profile WA, total requêtes,
    dernière requête, temps moyen de réponse (corrélation inbound→outbound)
  - Sélection multiple → import en lot dans `db.contacts` (groupe « Interrogations WA »)
  - Sélection multiple → export PDF

Endpoints :
  GET  /api/admin/liluvine-pro/wa-requests
       ?search=&group_by_phone=true&since=ISO&limit=200
  POST /api/admin/liluvine-pro/wa-requests/import-to-contacts
       Body: { phones: [...], group_name?: "Interrogations WA" }
  GET  /api/admin/liluvine-pro/wa-requests/export.pdf?phones=...,...
"""
from __future__ import annotations

import io
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

from fastapi import Body, Depends, HTTPException, Query
from fastapi.responses import Response

logger = logging.getLogger("sawali.liluvine_wa_requests")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def setup_liluvine_wa_requests_routes(*, db, api, get_user_with_roles):
    """Wire les routes WA Requests.

    Le middleware `get_user_with_roles` doit retourner un user dict si le user
    a l'un des rôles : 'admin', 'moderator', 'superviseur'.
    """

    @api.get("/admin/liluvine-pro/wa-requests", tags=["Admin — Liluvine PRO"])
    async def list_wa_requests(
        search: Optional[str] = Query(None),
        group_by_phone: bool = Query(True),
        since: Optional[str] = Query(None),
        limit: int = Query(500, ge=1, le=2000),
        only_unknown: bool = Query(False, description="Si True, ne renvoie que les commandes non-supportées (audit roadmap)"),
        user: dict = Depends(get_user_with_roles),
    ):
        """Iter43-fix24d — Liste les **exclamations** (`!commandes`) reçues.

        Cette table ne contient QUE les messages WhatsApp/SMS entrants
        commençant par `!` (ex. `!Garde`, `!Meteo`, `!Aizenta`). Les conversations
        Liluvine classiques (sans `!`) vont dans `liluvine_pro_messages` et ne
        sont PAS listées ici.

        Si `group_by_phone=True` (défaut), agrège par numéro avec stats.
        """
        # Filtre temporel
        q: Dict[str, Any] = {"direction": "inbound"}
        if since:
            since_dt = _parse_iso(since)
            if since_dt:
                q["created_at"] = {"$gte": since_dt.isoformat()}
        if only_unknown:
            q["is_known_command"] = False
        # Filtre texte
        if search:
            s = search.strip()
            q["$or"] = [
                {"phone_digits": {"$regex": s, "$options": "i"}},
                {"from": {"$regex": s, "$options": "i"}},
                {"from_profile_name": {"$regex": s, "$options": "i"}},
                {"contact_name": {"$regex": s, "$options": "i"}},
                {"body": {"$regex": s, "$options": "i"}},
                {"command": {"$regex": s, "$options": "i"}},
            ]
        # On charge les exclamations récentes
        inbound: List[Dict[str, Any]] = []
        async for m in db.liluvine_exclamations.find(q, {"_id": 0}).sort("created_at", -1).limit(limit):
            inbound.append(m)
        if not group_by_phone:
            for m in inbound:
                m["response_time_seconds"] = await _compute_response_time(db, m)
            return {"items": inbound, "count": len(inbound), "grouped": False}
        # Agrégation par phone_digits
        grouped: Dict[str, Dict[str, Any]] = {}
        for m in inbound:
            phone = m.get("phone_digits") or m.get("from") or "unknown"
            g = grouped.setdefault(phone, {
                "phone": phone,
                "from_raw": m.get("from"),
                "profile_name": m.get("from_profile_name"),
                "contact_name": m.get("contact_name"),
                "first_seen": m.get("created_at"),
                "last_seen": m.get("created_at"),
                "request_count": 0,
                "last_message": (m.get("body") or "")[:200],
                "last_command": m.get("command"),
                "commands": {},
                "unknown_count": 0,
                "response_times": [],
                "contact_id": m.get("contact_id"),
            })
            g["request_count"] += 1
            cmd = m.get("command") or "?"
            g["commands"][cmd] = g["commands"].get(cmd, 0) + 1
            if not m.get("is_known_command"):
                g["unknown_count"] += 1
            if m.get("from_profile_name") and not g["profile_name"]:
                g["profile_name"] = m.get("from_profile_name")
            try:
                cur = _parse_iso(m.get("created_at"))
                first = _parse_iso(g["first_seen"])
                last = _parse_iso(g["last_seen"])
                if cur and (not first or cur < first):
                    g["first_seen"] = m.get("created_at")
                if cur and (not last or cur > last):
                    g["last_seen"] = m.get("created_at")
                    g["last_message"] = (m.get("body") or "")[:200]
                    g["last_command"] = m.get("command")
            except Exception:
                pass
            rt = await _compute_response_time(db, m)
            if rt is not None:
                g["response_times"].append(rt)
        items = []
        for phone, g in grouped.items():
            rts = g.pop("response_times")
            g["avg_response_time_seconds"] = (sum(rts) / len(rts)) if rts else None
            g["responded_count"] = len(rts)
            items.append(g)
        items.sort(key=lambda x: x["request_count"], reverse=True)
        return {"items": items, "count": len(items), "grouped": True}

    # Iter43-fix24e — Auto-generate a Liluvine handler stub for an unknown !command
    @api.post("/admin/liluvine-pro/exclamations/{command}/auto-handler", tags=["Admin — Liluvine PRO"])
    async def generate_handler_stub(
        command: str,
        user: dict = Depends(get_user_with_roles),
    ):
        """Appelle Claude Sonnet pour proposer un handler Python complet pour la commande `!<command>`.

        L'IA reçoit en contexte :
          - Le nom de la commande
          - Les 3 derniers exemples reçus (body + args) extraits de `liluvine_exclamations`
          - Le pattern existant (`_build_garde_reply` / `_build_meteo_reply`) pour cohérence

        Elle renvoie du code Python prêt à coller dans `liluvine_wa_autoreply.py`,
        avec une explication des points d'attention (DB collections, secrets, etc.).
        """
        cmd_lower = command.lower().strip()
        if not cmd_lower or not cmd_lower.replace("_", "").replace("-", "").isalnum():
            raise HTTPException(status_code=400, detail="Nom de commande invalide")

        # Récupère 3 exemples concrets
        samples = []
        async for ex in db.liluvine_exclamations.find(
            {"command": cmd_lower, "direction": "inbound"},
            {"_id": 0, "body": 1, "command_args": 1, "from": 1, "from_profile_name": 1, "created_at": 1},
        ).sort("created_at", -1).limit(3):
            samples.append(ex)

        api_key = os.environ.get("EMERGENT_LLM_KEY")
        if not api_key:
            raise HTTPException(status_code=503, detail="EMERGENT_LLM_KEY non disponible côté serveur.")

        sys_prompt = (
            "Tu es un expert Python/FastAPI/MongoDB et l'auteur du module liluvine_wa_autoreply.py de SAWALI. "
            "L'utilisateur veut ajouter un nouveau handler pour une commande WhatsApp publique préfixée par `!`. "
            "Produis du code Python concis, idiomatique et drop-in dans le fichier `routes/liluvine_wa_autoreply.py`. "
            "Respecte STRICTEMENT le pattern existant :\n"
            "  1. Fonction async `_build_<command>_reply(db, args: str) -> str` qui retourne le texte de la réponse WhatsApp\n"
            "  2. Ajout dans la condition `is_public_cmd` (ligne ~155) avec le prefix correspondant\n"
            "  3. Ajout d'un branchement après le check `is_public_cmd` (où on dispatche vers _build_garde_reply ou _build_meteo_reply)\n"
            "  4. Pas plus de 150 lignes au total\n"
            "  5. Utiliser `datetime.now(timezone.utc)` (pas utcnow()), `motor` async API, et `from typing import Optional`\n"
            "Format de sortie OBLIGATOIRE — Markdown structuré :\n"
            "## 1. Fonction principale\n```python\n<code>\n```\n"
            "## 2. Modifications de la fonction maybe_handle_liluvine_wa_command\n```python\n<diff/code>\n```\n"
            "## 3. Points d'attention\n- ...\n- ...\n"
            "Ne génère AUCUN texte hors de ce format."
        )

        user_prompt = (
            f"Commande à implémenter : `!{cmd_lower}`\n\n"
            f"Exemples reçus ({len(samples)}) :\n"
            + ("\n".join(
                f"- de {s.get('from_profile_name') or s.get('from')} : "
                f"body=`{(s.get('body') or '')[:200]}` args=`{(s.get('command_args') or '')[:100]}`"
                for s in samples
            ) if samples else "(aucun exemple en base — devine l'intent du nom de la commande)")
            + "\n\nObjectif : produire le handler `_build_" + cmd_lower + "_reply(db, args)` "
            "qui retourne une réponse texte (max 1500 chars) cohérente avec le nom de commande. "
            "Si la commande requiert une donnée externe (ex. météo, base, …), utilise les collections MongoDB "
            "existantes (`officines`, `garde_plannings`, etc.) ou décris l'API à appeler."
        )

        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            chat = LlmChat(
                api_key=api_key,
                session_id=f"handler-gen:{cmd_lower}",
                system_message=sys_prompt,
            ).with_model("anthropic", "claude-sonnet-4-5-20250929")
            code = await chat.send_message(UserMessage(text=user_prompt))
        except Exception as exc:  # noqa: BLE001
            logger.exception("[handler-gen] LLM error")
            raise HTTPException(status_code=502, detail=f"Échec génération IA : {exc}") from exc

        # Audit
        try:
            await db.liluvine_handler_suggestions.insert_one({
                "id": str(uuid.uuid4()),
                "command": cmd_lower,
                "samples_count": len(samples),
                "generated_code": code,
                "model": "claude-sonnet-4-5-20250929",
                "generated_by": user.get("email"),
                "generated_at": _now_iso(),
                "applied": False,
            })
        except Exception:  # noqa: BLE001
            pass

        return {
            "ok": True,
            "command": cmd_lower,
            "samples_count": len(samples),
            "generated_code": code,
            "model": "claude-sonnet-4-5-20250929",
        }

    @api.post("/admin/liluvine-pro/wa-requests/import-to-contacts", tags=["Admin — Liluvine PRO"])
    async def import_wa_requests_to_contacts(
        payload: Dict[str, Any] = Body(...),
        user: dict = Depends(get_user_with_roles),
    ):
        """Importe les numéros sélectionnés dans le carnet de contacts du user.

        Body : { phones: ["22501020304", ...], group_name?: "Interrogations WA" }
        """
        phones = payload.get("phones") or []
        if not isinstance(phones, list) or not phones:
            raise HTTPException(status_code=400, detail="`phones` doit être une liste non vide")
        group_name = (payload.get("group_name") or "Interrogations WA").strip()
        client_id = user.get("client_id") or user.get("id")
        if not client_id:
            raise HTTPException(status_code=400, detail="client_id introuvable pour cet utilisateur")
        # Trouve ou crée le groupe
        group = await db.contact_groups.find_one({"client_id": client_id, "name": group_name}, {"_id": 0})
        if not group:
            group = {
                "id": str(uuid.uuid4()), "client_id": client_id, "name": group_name,
                "created_at": _now_utc().isoformat(),
                "created_by": user.get("email"),
                "auto_generated": True,
            }
            await db.contact_groups.insert_one(group.copy())
        gid = group["id"]
        created, updated, skipped = 0, 0, 0
        for phone in phones:
            digits = "".join(c for c in str(phone) if c.isdigit())
            if not digits or len(digits) < 6:
                skipped += 1
                continue
            # Cherche le profile_name / contact_name le plus parlant
            last_inbound = await db.whatsapp_messages.find_one(
                {"phone_digits": digits, "direction": "inbound"},
                {"from_profile_name": 1, "contact_name": 1, "_id": 0},
                sort=[("created_at", -1)],
            ) or {}
            display_name = (
                last_inbound.get("from_profile_name")
                or last_inbound.get("contact_name")
                or f"+{digits}"
            )
            existing = await db.contacts.find_one(
                {"client_id": client_id, "$or": [{"phone_digits": digits}, {"whatsapp_digits": digits}]},
                {"_id": 0},
            )
            if existing:
                # Ajoute au groupe si pas déjà
                groups_list = existing.get("group_ids") or []
                if gid not in groups_list:
                    groups_list.append(gid)
                    await db.contacts.update_one(
                        {"id": existing["id"]},
                        {"$set": {"group_ids": groups_list, "updated_at": _now_utc().isoformat()}},
                    )
                    updated += 1
                else:
                    skipped += 1
            else:
                new_contact = {
                    "id": str(uuid.uuid4()), "client_id": client_id,
                    "name": display_name,
                    "phone": f"+{digits}", "phone_digits": digits,
                    "whatsapp": f"+{digits}", "whatsapp_digits": digits,
                    "email": None, "company": None,
                    "group_ids": [gid],
                    "source": "wa_request_import",
                    "created_at": _now_utc().isoformat(),
                    "created_by": user.get("email"),
                }
                await db.contacts.insert_one(new_contact.copy())
                created += 1
        return {
            "ok": True,
            "group_id": gid,
            "group_name": group_name,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "total": len(phones),
        }

    @api.get("/admin/liluvine-pro/wa-requests/export.pdf", tags=["Admin — Liluvine PRO"])
    async def export_wa_requests_pdf(
        phones: str = Query(..., description="Liste de numéros séparés par virgules"),
        user: dict = Depends(get_user_with_roles),
    ):
        """Exporte une liste de numéros sélectionnés en PDF (avec stats par numéro)."""
        phone_list = [p.strip() for p in phones.split(",") if p.strip()]
        if not phone_list:
            raise HTTPException(status_code=400, detail="Aucun numéro fourni")
        # Récupère les agrégats pour ces phones
        rows: List[Dict[str, Any]] = []
        for phone in phone_list[:500]:
            cnt = await db.whatsapp_messages.count_documents(
                {"phone_digits": phone, "direction": "inbound"}
            )
            last = await db.whatsapp_messages.find_one(
                {"phone_digits": phone, "direction": "inbound"},
                {"_id": 0}, sort=[("created_at", -1)],
            ) or {}
            first = await db.whatsapp_messages.find_one(
                {"phone_digits": phone, "direction": "inbound"},
                {"_id": 0}, sort=[("created_at", 1)],
            ) or {}
            rows.append({
                "phone": phone,
                "profile_name": last.get("from_profile_name") or last.get("contact_name") or "—",
                "request_count": cnt,
                "first_seen": (first.get("created_at") or "")[:19].replace("T", " "),
                "last_seen": (last.get("created_at") or "")[:19].replace("T", " "),
                "last_message": (last.get("body") or "")[:80],
            })
        # Génération PDF avec reportlab
        try:
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib import colors
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.lib.units import cm
        except ImportError:
            raise HTTPException(status_code=500, detail="reportlab non installé sur le serveur")
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                                leftMargin=1.5*cm, rightMargin=1.5*cm,
                                topMargin=1.5*cm, bottomMargin=1.5*cm)
        styles = getSampleStyleSheet()
        title_st = ParagraphStyle("title", parent=styles["Title"], fontSize=18, alignment=0)
        meta_st = ParagraphStyle("meta", parent=styles["Normal"], fontSize=9, textColor=colors.grey)
        story = [
            Paragraph("Interrogations WhatsApp — Liluvine PRO", title_st),
            Spacer(1, 0.2*cm),
            Paragraph(
                f"Exporté le {_now_utc().strftime('%d/%m/%Y à %H:%M UTC')} · "
                f"{len(rows)} numéro(s) sélectionné(s) · "
                f"Exporté par {user.get('email','admin')}", meta_st,
            ),
            Spacer(1, 0.5*cm),
        ]
        # Tableau
        data = [["#", "Numéro", "Identité affichée", "Requêtes", "1ère",
                 "Dernière", "Dernier message"]]
        for i, r in enumerate(rows, 1):
            data.append([
                str(i),
                r["phone"],
                Paragraph(r["profile_name"][:50], styles["Normal"]),
                str(r["request_count"]),
                r["first_seen"],
                r["last_seen"],
                Paragraph((r["last_message"] or "")[:120], styles["Normal"]),
            ])
        table = Table(data, colWidths=[0.8*cm, 3.5*cm, 4.5*cm, 1.8*cm, 3.5*cm, 3.5*cm, 9*cm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0e1d36")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(table)
        doc.build(story)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="liluvine-wa-requests-{_now_utc().strftime("%Y%m%d-%H%M")}.pdf"',
            },
        )


async def _compute_response_time(db, msg_in: Dict[str, Any]) -> Optional[float]:
    """Calcule le temps de réponse (sec) entre un message inbound et la
    prochaine réponse outbound vers le même numéro, dans une fenêtre de 30 min.
    """
    phone = msg_in.get("phone_digits")
    if not phone:
        return None
    inbound_at = _parse_iso(msg_in.get("created_at"))
    if not inbound_at:
        return None
    # Cherche la 1ère outbound vers ce phone après inbound_at
    next_out = await db.whatsapp_messages.find_one(
        {
            "phone_digits": phone,
            "direction": "outbound",
            "created_at": {"$gt": inbound_at.isoformat()},
        },
        {"_id": 0, "created_at": 1}, sort=[("created_at", 1)],
    )
    if not next_out:
        return None
    out_at = _parse_iso(next_out.get("created_at"))
    if not out_at:
        return None
    delta = (out_at - inbound_at).total_seconds()
    # Ignorer si > 30 min (pas une vraie « réponse »)
    if delta < 0 or delta > 1800:
        return None
    return round(delta, 1)
