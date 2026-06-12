"""Iter40 (2026-02) — Liluvine PRO Business RAG (RAG sur données structurées).

Enrichit Liluvine PRO d'un accès en LECTURE aux modules métier (RDV, Tickets,
HR, Caisse, Paiements, Contacts) ainsi qu'à un petit ensemble d'actions
limitées (`!ticket open motif`). L'accès est gouverné par une **liste blanche
par module** : pour chaque module, l'administrateur déclare les numéros de
téléphone (digits) autorisés à interroger ce module depuis WhatsApp.

Stockage de l'ACL : `settings.liluvine_module_acl` (dict module → [digits]).
Exemple : `{"rdv": ["22890123456"], "hr": ["22890123456"], "tickets": []}`.

Modules supportés :
  - `rdv`       : prochains rendez-vous du tenant (top 10)
  - `tickets`   : tickets actifs du tenant
  - `hr`        : récap RH de l'employé (absences/avances/dernière paie)
  - `caisse`    : total caisse du jour (admin uniquement, scope tenant)
  - `payments`  : 10 derniers paiements du tenant
  - `contacts`  : recherche contact par nom (top 5)

Détection d'intention : regex simple sur la query utilisateur. Le LLM voit
le contexte injecté entre les marqueurs `--- CONTEXTE MÉTIER ---`.

Actions limitées :
  - `!ticket <motif…>`            → crée un ticket support (acl=tickets)

Le composant est conçu pour être appelé depuis :
  - `liluvine_wa_autoreply.py` (WhatsApp inbound)
  - `liluvine_hr_wa.py` (déjà autonome)
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sawali.liluvine_business_rag")


MODULES = ("rdv", "tickets", "hr", "caisse", "payments", "contacts", "errors")

# Patterns d'intention par module (large, casse-insensible)
INTENT_PATTERNS: Dict[str, re.Pattern] = {
    "rdv": re.compile(r"\b(rdv|rendez.?vous|appointment|r[ée]unions?|meeting)\b", re.IGNORECASE),
    "tickets": re.compile(r"\b(tickets?|incidents?|interventions?|demandes?|pannes?|probl[èe]mes?)\b", re.IGNORECASE),
    "hr": re.compile(r"\b(rh|grh|absences?|avances?|cong[ée]s?|paie|salaires?|bulletins?|payslip)\b", re.IGNORECASE),
    "caisse": re.compile(r"\b(caisse|recettes?|encaissements?|journ[ée]e|chiffre.?d.?affaire|ca\s+du\s+jour)\b", re.IGNORECASE),
    "payments": re.compile(r"\b(paiements?|payments?|pawapay|mobile.?money|stripe|encaiss[ée]s?|r[èe]glements?)\b", re.IGNORECASE),
    "contacts": re.compile(r"\b(contacts?|annuaire|clients?|fiches?)\b", re.IGNORECASE),
    # Iter43-fix2 (2026-03) — Module "errors" : Liluvine peut interroger le
    # Registre des Erreurs (erreurs remontées par les logiciels métier
    # Aizenta, Biolog, etc.).
    "errors": re.compile(r"\b(erreurs?|exceptions?|crashes?|plantages?|registre.?des.?erreurs?|bugs?|stack.?traces?|fatales?|critiques?)\b", re.IGNORECASE),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


async def _load_acl(db) -> Dict[str, List[str]]:
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "liluvine_module_acl": 1}) or {}
    raw = s.get("liluvine_module_acl") or {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, List[str]] = {}
    for k, v in raw.items():
        if k not in MODULES:
            continue
        if isinstance(v, list):
            out[k] = [_digits(x) for x in v if _digits(x)]
        elif isinstance(v, str):
            out[k] = [_digits(p) for p in re.split(r"[\s,;]+", v) if _digits(p)]
        else:
            out[k] = []
    return out


def _phone_in_acl(phone_digits: str, allowed: List[str]) -> bool:
    if not phone_digits or not allowed:
        return False
    # Comparaison sur les 9 derniers chiffres (ignore le pays)
    tail = phone_digits[-9:]
    for x in allowed:
        if x and (x.endswith(tail) or tail.endswith(x[-9:])):
            return True
    return False


def detect_intents(text: str) -> List[str]:
    if not text:
        return []
    out: List[str] = []
    for module, pat in INTENT_PATTERNS.items():
        if pat.search(text):
            out.append(module)
    return out


async def _resolve_tenant_for_phone(db, phone_digits: str) -> Optional[str]:
    """Find the canonical tenant_id that should be used to scope queries.

    Tries to match an `hr_employees` entry → use its tenant_id. Otherwise
    falls back to the user matching the phone, then to the broadest admin.
    """
    if not phone_digits or len(phone_digits) < 6:
        return None
    tail = phone_digits[-9:]
    user = await db.users.find_one(
        {
            "$or": [
                {"phone": {"$regex": tail + "$"}},
                {"whatsapp": {"$regex": tail + "$"}},
                {"whatsapp_number": {"$regex": tail + "$"}},
            ],
        },
        {"_id": 0, "id": 1, "parent_client_id": 1, "client_id": 1, "role": 1},
    )
    if not user:
        return None
    return (
        user.get("parent_client_id")
        or user.get("client_id")
        or (user.get("id") if user.get("role") in ("admin", "superviseur") else None)
        or user["id"]
    )


# ============================================================
# Module fetchers
# ============================================================
async def _fetch_rdv(db, tenant_id: str) -> str:
    cutoff = datetime.now(timezone.utc).isoformat()
    cursor = db.appointments.find(
        {
            "$or": [{"client_id": tenant_id}, {"created_by": tenant_id}],
            "status": {"$in": ["pending", "confirmed"]},
            "scheduled_at": {"$gte": cutoff},
        },
        {"_id": 0, "title": 1, "scheduled_at": 1, "duration_min": 1, "contact_name": 1, "status": 1},
    ).sort("scheduled_at", 1).limit(10)
    rows = await cursor.to_list(10)
    if not rows:
        return "Aucun rendez-vous à venir."
    lines = []
    for a in rows:
        when = (a.get("scheduled_at") or "")[:16].replace("T", " ")
        lines.append(f"- {when} · {(a.get('title') or a.get('contact_name') or '—')[:60]} · {a.get('status')}")
    return "**Prochains RDV (10 max)** :\n" + "\n".join(lines)


async def _fetch_tickets(db, tenant_id: str) -> str:
    cursor = db.support_tickets.find(
        {
            "client_id": tenant_id,
            "archived_at": {"$in": [None, ""]},
            "status": {"$in": ["open", "in_progress", "pending"]},
        },
        {"_id": 0, "number": 1, "motif": 1, "status": 1, "priority": 1, "opened_at": 1, "contact_name": 1},
    ).sort("opened_at", -1).limit(10)
    rows = await cursor.to_list(10)
    if not rows:
        return "Aucun ticket actif."
    lines = []
    for t in rows:
        lines.append(
            f"- {t.get('number','?')} · {(t.get('motif') or '—')[:60]} · "
            f"{t.get('status','?')} · prio={t.get('priority') or '—'}"
        )
    return "**Tickets actifs (10 max)** :\n" + "\n".join(lines)


async def _fetch_hr_self(db, phone_digits: str) -> str:
    """Renvoie les absences/avances/dernière paie de l'employé identifié par phone."""
    tail = phone_digits[-9:]
    user = await db.users.find_one(
        {"$or": [
            {"phone": {"$regex": tail + "$"}},
            {"whatsapp": {"$regex": tail + "$"}},
            {"whatsapp_number": {"$regex": tail + "$"}},
        ]},
        {"_id": 0, "id": 1, "full_name": 1, "email": 1},
    )
    if not user:
        return "Numéro non reconnu pour la GRH."
    emp = await db.hr_employees.find_one(
        {"user_id": user["id"], "deleted_at": None},
        {"_id": 0, "id": 1, "tenant_id": 1, "matricule": 1, "full_name": 1, "monthly_hours_baseline": 1, "hourly_rate": 1, "monthly_salary": 1},
    )
    if not emp:
        return "Vous n'êtes pas enregistré(e) comme employé(e)."
    lines = [f"**Fiche RH** — {emp.get('matricule') or '—'} — {emp.get('full_name') or user.get('full_name') or '—'}"]
    # Absences en cours / récentes
    last_60 = (datetime.now(timezone.utc) - timedelta(days=60)).date().isoformat()
    cursor = db.hr_absences.find(
        {"employee_id": emp["id"], "start_date": {"$gte": last_60}},
        {"_id": 0, "start_date": 1, "end_date": 1, "abs_type": 1, "status": 1, "justification": 1},
    ).sort("start_date", -1).limit(5)
    abs_rows = await cursor.to_list(5)
    if abs_rows:
        lines.append("Absences récentes :")
        for a in abs_rows:
            lines.append(
                f"  - {a.get('start_date')}→{a.get('end_date')} · {a.get('abs_type')} · {a.get('status') or 'enregistrée'}"
            )
    else:
        lines.append("Aucune absence récente (60 j).")
    # Avances en cours
    cursor = db.hr_advances.find(
        {"employee_id": emp["id"], "status": {"$ne": "repaid"}},
        {"_id": 0, "amount": 1, "currency": 1, "motive": 1, "repaid_amount": 1, "status": 1, "granted_at": 1},
    ).sort("granted_at", -1).limit(5)
    adv_rows = await cursor.to_list(5)
    if adv_rows:
        lines.append("Avances en cours :")
        for a in adv_rows:
            remaining = float(a.get("amount") or 0) - float(a.get("repaid_amount") or 0)
            lines.append(
                f"  - {a.get('granted_at')} · {a.get('amount'):,.0f} {a.get('currency','XOF')} "
                f"(reste {remaining:,.0f}) · {a.get('status')}"
            )
    else:
        lines.append("Aucune avance en cours.")
    return "\n".join(lines)


async def _fetch_caisse(db, tenant_id: str) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    pipeline = [
        {"$match": {"tenant_id": tenant_id, "created_at": {"$gte": today}, "deleted_at": None}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}, "count": {"$sum": 1}}},
    ]
    res = await db.cashier_entries.aggregate(pipeline).to_list(1)
    if not res:
        return "Aucune entrée caisse aujourd'hui."
    r = res[0]
    return f"**Caisse du jour** : {r.get('total', 0):,.0f} XOF · {r.get('count', 0)} entrée(s)"


async def _fetch_payments(db, tenant_id: str) -> str:
    cursor = db.payments.find(
        {"client_id": tenant_id},
        {"_id": 0, "amount": 1, "currency": 1, "status": 1, "mno": 1, "description": 1, "created_at": 1},
    ).sort("created_at", -1).limit(10)
    rows = await cursor.to_list(10)
    if not rows:
        return "Aucun paiement enregistré."
    lines = []
    for p in rows:
        lines.append(
            f"- {(p.get('created_at') or '')[:10]} · {p.get('amount')} {p.get('currency','XOF')} · "
            f"{p.get('status')} · {(p.get('description') or '—')[:40]}"
        )
    return "**10 derniers paiements** :\n" + "\n".join(lines)


async def _fetch_contacts(db, tenant_id: str, query: str) -> str:
    # Extract a tentative name token (length>=3 letters) from the query
    name_match = re.findall(r"[A-Za-zÀ-ÿ]{3,}", query or "")
    if not name_match:
        return ""
    needle = name_match[-1]
    cursor = db.directory_contacts.find(
        {
            "client_id": tenant_id,
            "$or": [
                {"name": {"$regex": needle, "$options": "i"}},
                {"company": {"$regex": needle, "$options": "i"}},
            ],
        },
        {"_id": 0, "name": 1, "phone": 1, "whatsapp": 1, "email": 1, "company": 1},
    ).limit(5)
    rows = await cursor.to_list(5)
    if not rows:
        return f"Aucun contact « {needle} »."
    lines = [f"**Contacts « {needle} » (top 5)** :"]
    for c in rows:
        lines.append(
            f"- {c.get('name','?')} · {c.get('company') or '—'} · "
            f"{c.get('phone') or c.get('whatsapp') or c.get('email') or '—'}"
        )
    return "\n".join(lines)


async def _fetch_errors(db, tenant_id: str) -> str:
    """Iter43-fix2 (2026-03) — Résumé Registre des Erreurs pour Liluvine.

    Le `Code_Client` envoyé par les logiciels métier correspond au tenant
    Sawali (champ `client_code` ou `company` côté User). On résout les
    valeurs candidates, puis on récupère les erreurs récentes (30 derniers
    jours) regroupées par sévérité.
    """
    tenant = await db.users.find_one(
        {"id": tenant_id},
        {"_id": 0, "client_code": 1, "company": 1, "full_name": 1},
    )
    if not tenant:
        return ""
    codes = {(tenant.get("client_code") or "").strip().upper(),
             (tenant.get("company") or "").strip().upper()}
    codes.discard("")
    if not codes:
        return ""
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    q = {
        "deleted_at": None,
        "Code_Client": {"$in": list(codes)},
        "DateHeure_Création": {"$gte": since},
    }
    total = await db.error_registry.count_documents(q)
    if total == 0:
        return f"**Registre des Erreurs (30j)** : aucune erreur pour {tenant.get('company') or tenant_id}."
    # Compteurs par sévérité (mapped_severity OU heuristique sur StatutEnCours)
    crit = await db.error_registry.count_documents({**q, "$or": [
        {"mapped_severity": "critical"},
        {"mapped_severity": {"$exists": False}, "StatutEnCours": {"$regex": "^(fatale|fatal|critical|critique)$", "$options": "i"}},
    ]})
    high = await db.error_registry.count_documents({**q, "$or": [
        {"mapped_severity": "high"},
        {"mapped_severity": {"$exists": False}, "StatutEnCours": {"$regex": "^(exception|erreur|error)$", "$options": "i"}},
    ]})
    unack = await db.error_registry.count_documents({**q, "acknowledged": {"$ne": True}, "estActif": True})
    # Top 5 récentes
    cur = db.error_registry.find(q, {"_id": 0, "DateHeure_Création": 1, "CodeApplicatif": 1, "StatutEnCours": 1, "Motif": 1, "Numéro_Généré": 1, "mapped_severity": 1}).sort("DateHeure_Création", -1).limit(5)
    rows = await cur.to_list(5)
    lines = [
        f"**Registre des Erreurs — 30 derniers jours pour {tenant.get('company') or tenant_id}** :",
        f"- Total : {total} · 🔴 Critical : {crit} · 🟠 High : {high} · 🔔 Non lues : {unack}",
        "Dernières erreurs :",
    ]
    for r in rows:
        d = (r.get("DateHeure_Création") or "")[:16].replace("T", " ")
        motif = (r.get("Motif") or "").splitlines()[0][:120]
        sev = (r.get("mapped_severity") or r.get("StatutEnCours") or "—")
        app = r.get("CodeApplicatif") or "?"
        num = r.get("Numéro_Généré") or ""
        lines.append(f"- {d} · [{app}] · {sev} · {num} · {motif}")
    return "\n".join(lines)



# ============================================================
# Build the full RAG context for a given phone+query
# ============================================================
async def build_business_rag_context(
    db,
    *,
    phone_digits: str,
    query: str,
) -> str:
    """Inspecte la query, vérifie l'ACL par module et concatène le contexte
    disponible. Retourne `""` si rien à injecter."""
    intents = detect_intents(query or "")
    if not intents:
        return ""
    acl = await _load_acl(db)
    if not acl:
        return ""
    snippets: List[str] = []
    tenant_id: Optional[str] = None
    for module in intents:
        allowed = acl.get(module) or []
        if not _phone_in_acl(phone_digits, allowed):
            continue
        if module == "hr":
            try:
                snippets.append(await _fetch_hr_self(db, phone_digits))
            except Exception:  # noqa: BLE001
                logger.exception("[business_rag.hr] fetch failed")
            continue
        # Modules nécessitant un tenant_id
        if tenant_id is None:
            tenant_id = await _resolve_tenant_for_phone(db, phone_digits)
        if not tenant_id:
            continue
        try:
            if module == "rdv":
                snippets.append(await _fetch_rdv(db, tenant_id))
            elif module == "tickets":
                snippets.append(await _fetch_tickets(db, tenant_id))
            elif module == "caisse":
                snippets.append(await _fetch_caisse(db, tenant_id))
            elif module == "payments":
                snippets.append(await _fetch_payments(db, tenant_id))
            elif module == "contacts":
                snip = await _fetch_contacts(db, tenant_id, query)
                if snip:
                    snippets.append(snip)
            elif module == "errors":
                # Iter43-fix2 — Liluvine accède au Registre des Erreurs
                snippets.append(await _fetch_errors(db, tenant_id))
        except Exception:  # noqa: BLE001
            logger.exception("[business_rag.%s] fetch failed", module)
    snippets = [s for s in snippets if s]
    if not snippets:
        return ""
    return "\n\n--- CONTEXTE MÉTIER ---\n" + "\n\n".join(snippets) + "\n--- FIN CONTEXTE MÉTIER ---"


# ============================================================
# Action limitée : !ticket open <motif>
# ============================================================
TICKET_CMD_RE = re.compile(r"^[!/]\s*ticket(?:\s+(?:open|nouveau|new))?\s+(.+)$", re.IGNORECASE)


def detect_ticket_command(text: str) -> bool:
    return bool(text and TICKET_CMD_RE.match(text.strip()))


async def handle_ticket_command(
    db,
    *,
    phone_digits: str,
    text: str,
    wa_send_text=None,
) -> Dict[str, Any]:
    """Crée un ticket de support depuis WhatsApp. ACL = module `tickets`."""
    m = TICKET_CMD_RE.match((text or "").strip())
    if not m:
        return {"ok": False, "reason": "regex_mismatch"}
    motif = (m.group(1) or "").strip()
    if len(motif) < 5:
        return {
            "ok": False,
            "reason": "motif_too_short",
            "user_reply": "❌ Motif trop court. Format : !ticket <description courte>.",
        }
    acl = await _load_acl(db)
    if not _phone_in_acl(phone_digits, acl.get("tickets") or []):
        return {
            "ok": False,
            "reason": "acl_denied",
            "user_reply": "❌ Vous n'êtes pas autorisé(e) à ouvrir des tickets via WhatsApp.",
        }
    tenant_id = await _resolve_tenant_for_phone(db, phone_digits)
    if not tenant_id:
        return {
            "ok": False,
            "reason": "no_tenant",
            "user_reply": "❌ Numéro non rattaché à un tenant.",
        }
    # Auto-number : TKT-YYYY-NNN per tenant per year
    try:
        from ._counters import next_seq
        year = datetime.now(timezone.utc).year
        seq = await next_seq(db, f"support_tickets-{tenant_id}-{year}")
        number = f"TKT-{year}-{str(seq).zfill(3)}"
    except Exception:
        number = f"TKT-WA-{uuid.uuid4().hex[:6].upper()}"
    user = await db.users.find_one(
        {"$or": [
            {"phone": {"$regex": phone_digits[-9:] + "$"}},
            {"whatsapp": {"$regex": phone_digits[-9:] + "$"}},
        ]},
        {"_id": 0, "id": 1, "full_name": 1, "email": 1},
    ) or {}
    doc = {
        "id": str(uuid.uuid4()),
        "client_id": tenant_id,
        "tenant_id": tenant_id,
        "number": number,
        "motif": motif[:500],
        "description": motif,
        "status": "open",
        "priority": "medium",
        "opened_at": _now_iso(),
        "contact_name": user.get("full_name") or f"WA +{phone_digits}",
        "contact_email": user.get("email"),
        "contact_phone": f"+{phone_digits}",
        "source": "whatsapp_wa_command",
        "wa_from_phone": phone_digits,
        "wa_user_id": user.get("id"),
        "created_at": _now_iso(),
        "created_by": user.get("id"),
    }
    await db.support_tickets.insert_one(doc.copy())
    return {
        "ok": True,
        "command": "ticket",
        "id": doc["id"],
        "number": number,
        "user_reply": (
            f"✅ Ticket {number} créé.\n"
            f"📝 {motif[:120]}\n\n"
            "Un agent va le prendre en charge."
        ),
    }


from pydantic import BaseModel
from typing import Dict as _DictT, List as _ListT


class _ModuleAclPayload(BaseModel):
    acl: _DictT[str, _ListT[str]] = {}


# ============================================================
# Admin endpoints (mounted by liluvine_pro setup)
# ============================================================
def attach_admin_acl_routes(*, api, db, get_current_user):
    """Mount GET/PUT /api/admin/liluvine-pro/module-acl."""
    from fastapi import Body, Depends, HTTPException

    @api.get("/admin/liluvine-pro/module-acl", tags=["Admin — Liluvine PRO"])
    async def admin_get_acl(user: dict = Depends(get_current_user)):
        if (user.get("role") or "") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé admin/superviseur")
        acl = await _load_acl(db)
        return {"modules": MODULES, "acl": {m: acl.get(m, []) for m in MODULES}}

    @api.put("/admin/liluvine-pro/module-acl", tags=["Admin — Liluvine PRO"])
    async def admin_set_acl(payload: _ModuleAclPayload = Body(...), user: dict = Depends(get_current_user)):
        if (user.get("role") or "") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé admin/superviseur")
        clean: Dict[str, List[str]] = {}
        for module, phones in (payload.acl or {}).items():
            if module not in MODULES:
                continue
            if not isinstance(phones, list):
                continue
            normalized = sorted({_digits(p) for p in phones if _digits(p)})
            clean[module] = normalized
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {
                "liluvine_module_acl": clean,
                "liluvine_module_acl_updated_at": _now_iso(),
                "liluvine_module_acl_updated_by": user.get("email"),
            }},
            upsert=True,
        )
        return {"ok": True, "modules": MODULES, "acl": {m: clean.get(m, []) for m in MODULES}}


__all__ = [
    "MODULES",
    "build_business_rag_context",
    "detect_intents",
    "detect_ticket_command",
    "handle_ticket_command",
    "attach_admin_acl_routes",
]
