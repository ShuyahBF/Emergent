# server_parts/p11_whatsapp.py — WhatsApp Business API : répertoire de contacts, envois, médias, statistiques, rapprochement des messages.
# Morceau de l'ancien server.py (lignes 14061 à 15993), recopié à l'identique.
# Exécuté par server.py via _inclure_partie() dans SON espace de noms : les
# noms utilisés ici (db, api, get_current_user, helpers…) sont ceux de server.py.
# Ne pas importer ce fichier directement.

# ====================================================================
# PHASE 3 — WhatsApp Business API (Meta / Facebook Business Portfolio)
# Sends approved TEMPLATE messages via Meta Graph API /v{version}/{phone-number-id}/messages
# Credentials configured globally by super-admin in /admin/settings.
# ====================================================================
WA_GRAPH_VERSION = "v21.0"  # Meta Graph API version (update as Meta ships new)
# Iter43-fix24az-q — WhatsApp helpers extracted to routes/whatsapp_helpers.py.
# Import pure helpers directly and attach db-bound helpers via factory.
from routes.whatsapp_helpers import (  # noqa: E402
    _normalize_wa_phone,
    _wa_kind_for_mime,
    _wa_window_open as _wa_window_open_helper,
    _wa_apply_image_watermark_qr,
    attach_whatsapp_helpers as _attach_whatsapp_helpers,
    WA_MEDIA_KIND_BY_MIME,
    _wa_parse_flow_reply,  # Lot 27 : réponses des formulaires WhatsApp (Flow)
)


# ---------- Dynamic-variable templating for WhatsApp templates ----------
# Each entry in `variables` is a free-text string that may contain tokens
# like {{full_name}}, {{company}}, {{phone}}, {{email}}, {{client_code}},
# {{today}}, {{tomorrow}}. At send time they are resolved against the
# recipient's profile. Positional → mapped to body parameters {{1}} {{2}}…
#
# 2026-02 fork iter106 — Tokens étendus pour couvrir les cas login/relais WA :
# {{login_ip}}, {{login_time}}, {{login_email}}, {{linked_client}},
# {{identity}}, {{tracked_role}}. Ces valeurs sont peuplées via `extra_ctx`
# sur l'emit (voir `_emit_login_event`, dispatch whatsapp.received, etc.).
SUPPORTED_VAR_TOKENS = {
    "full_name", "company", "phone", "email", "client_code", "today", "tomorrow",
    # 2026-02 fork iter106 additions
    "login_ip", "login_time", "login_email", "linked_client", "identity", "tracked_role",
}

_VAR_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def _render_variable(value: str, ctx: Dict[str, str]) -> str:
    """Replace {{token}} occurrences in `value` using ctx. Unknown tokens are left blank.

    2026-02 fork iter104 — Meta refuse tout paramètre texte vide avec l'erreur
    (#131008) « Required parameter is missing — Parameter of type text is
    missing text value ». On force donc une valeur non vide (`—`) sur toute
    substitution qui résoudrait à une chaîne vide/blanks.
    """
    if not value:
        return "—"

    def _repl(m):
        key = m.group(1).lower()
        v = (ctx.get(key) or "").strip()
        return v if v else "—"

    rendered = _VAR_TOKEN_RE.sub(_repl, value)
    return rendered if rendered.strip() else "—"


def _build_recipient_ctx(kind: str, user_doc: Optional[dict], phone: str, label: Optional[str]) -> Dict[str, str]:
    """Build a substitution context dict from a resolved user/tracked-user doc."""
    u = user_doc or {}
    today = datetime.now(timezone.utc).date()
    tomorrow = today + timedelta(days=1)
    return {
        "full_name": (u.get("full_name") or u.get("name") or label or "").strip(),
        "company": (u.get("company") or "").strip(),
        "phone": phone or (u.get("phone") or "").strip(),
        "email": (u.get("email") or "").strip(),
        "client_code": (u.get("client_code") or "").strip(),
        "today": today.strftime("%d/%m/%Y"),
        "tomorrow": tomorrow.strftime("%d/%m/%Y"),
    }


def _build_components(
    variables: Optional[List[str]],
    ctx: Dict[str, str],
    *,
    header_text: Optional[str] = None,
    header_media: Optional[Dict[str, Any]] = None,
    button_vars: Optional[List[List[str]]] = None,
    button_specs: Optional[List[Dict[str, Any]]] = None,
) -> Optional[list]:
    """Build Meta template `components` array from positional variables and optional
    HEADER (text or media link) + URL-button parameters.

    Iter43-fix24aj (2026-06-17) — `button_specs` (preferred) lets the caller
    explicitly declare each button's `sub_type` (`url` / `quick_reply` / `flow`
    …) + `index` + `parameters`. Without it, the legacy `button_vars` path is
    used which hardcoded `sub_type=url` — that caused Meta error #131009
    "Components sub_type invalid at index: N" whenever the template's actual
    button was a QUICK_REPLY/FLOW.

    Each `button_specs` entry shape:
      {
        "sub_type": "url" | "quick_reply" | "flow" | "voice_call" | "copy_code",
        "index":    int | str,
        "parameters": [
            "raw {{token}} value",  # OR
            {"type": "text", "text": "..."},  # OR
            {"type": "payload", "payload": "..."},
        ],
      }
    `{{token}}` substitutions are applied per recipient via `_render_variable`.

    Returns None when nothing to send."""
    components: list = []
    # HEADER
    if header_text:
        components.append({
            "type": "header",
            "parameters": [{"type": "text", "text": _render_variable(header_text, ctx)}],
        })
    elif header_media and header_media.get("link"):
        kind = (header_media.get("kind") or "document").lower()
        link = header_media["link"]
        if kind == "image":
            components.append({"type": "header", "parameters": [{"type": "image", "image": {"link": link}}]})
        elif kind == "video":
            components.append({"type": "header", "parameters": [{"type": "video", "video": {"link": link}}]})
        else:
            components.append({"type": "header", "parameters": [{"type": "document", "document": {"link": link, "filename": header_media.get("filename") or "document.pdf"}}]})
    # BODY
    if variables:
        params = [{"type": "text", "text": _render_variable(v, ctx)} for v in variables]
        components.append({"type": "body", "parameters": params})
    # BUTTONS — preferred path: explicit specs from the caller.
    if button_specs:
        for spec in button_specs:
            sub_type = (spec.get("sub_type") or "url").lower()
            idx = spec.get("index")
            raw_params = spec.get("parameters") or []
            default_param_type = "payload" if sub_type == "quick_reply" else "text"
            rendered: list = []
            for p in raw_params:
                if isinstance(p, dict):
                    # Already shaped — render any string value through substitution.
                    new_p = dict(p)
                    for k in ("text", "payload"):
                        if k in new_p and isinstance(new_p[k], str):
                            new_p[k] = _render_variable(new_p[k], ctx)
                    rendered.append(new_p)
                else:
                    rendered.append({"type": default_param_type, default_param_type: _render_variable(str(p), ctx)})
            # Skip emitting a button component with no parameters (Meta rejects empty).
            if not rendered:
                continue
            components.append({
                "type": "button",
                "sub_type": sub_type,
                "index": str(idx) if idx is not None else "0",
                "parameters": rendered,
            })
    elif button_vars:
        # Legacy path — assumes URL buttons. Kept for backwards compat with
        # callers that haven't been updated to pass `button_specs` yet.
        for index, params in enumerate(button_vars):
            if not params:
                continue
            # Filter out fully-empty params (no template has parameters when the
            # button is static — emitting in that case yields Meta #131009).
            cleaned = [p for p in params if p and str(p).strip()]
            if not cleaned:
                continue
            components.append({
                "type": "button",
                "sub_type": "url",
                "index": str(index),
                "parameters": [{"type": "text", "text": _render_variable(p, ctx)} for p in cleaned],
            })
    return components or None


# ----- Directory of contacts (per client) -----
# NOTE : renommé en `DirectoryContactCreate/Update` (2026-02 fork bugfix) pour
# ne plus masquer `models.ContactCreate` (formulaire public /contact).
class DirectoryContactCreate(BaseModel):
    name: str
    phone: Optional[str] = ""
    whatsapp: Optional[str] = ""
    email: Optional[str] = ""
    company: Optional[str] = ""
    notes: Optional[str] = ""
    tags: Optional[List[str]] = []
    shared: bool = False
    photo_url: Optional[str] = None  # Manually uploaded avatar (à la WhatsApp profile picture)
    # Niveau VIDAL riche (nouveau champ dédié, distinct des tags) : True =
    # accès illimité aux actions VIDAL riches (!doc/!rech), False/absent =
    # accès simple avec quota quotidien. Voir routes/vidal_riche.py.
    vidal_riche: Optional[bool] = None
    # Lot Liluvine (2026-09) — contact "décisionnaire" (Responsable/DG/
    # Directeur) pour ce client/tenant : champ dédié plutôt qu'un tag libre
    # (même raisonnement que vidal_riche ci-dessus — fiable, indépendant de
    # l'orthographe/accent d'un tag). Sert à cibler les notifications
    # Liluvine liées au contrat (validité, accès restreint) — voir
    # routes/liluvine_wa_autoreply.py.
    is_decision_maker: Optional[bool] = None
    # Cible optionnelle pour un créateur élevé gérant plusieurs sociétés-
    # clientes (ex. depuis le champ Rapporteur des Interventions/Tickets) :
    # honoré uniquement si l'appelant est élevé ET si ce client existe
    # (voir me_create_contact) ; ignoré sinon (le scope reste self).
    client_id: Optional[str] = None
    # Lot 59 — ligne WhatsApp dédiée (« principal » ou Phone Number ID ; vide = automatique)
    wa_ligne: Optional[str] = None
    # Lot 67 — « Appeler le propriétaire à chaque message » (absent = oui, voir routes/appel_proprietaire.py)
    appel_proprietaire: Optional[bool] = None


class DirectoryContactUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    shared: Optional[bool] = None
    photo_url: Optional[str] = None
    vidal_riche: Optional[bool] = None
    is_decision_maker: Optional[bool] = None
    wa_ligne: Optional[str] = None   # Lot 59 — ligne WhatsApp dédiée ("" = automatique)
    appel_proprietaire: Optional[bool] = None   # Lot 67 — alerte du propriétaire à chaque message (défaut oui)


@api.get("/me/wa-lignes", tags=["Portail Client"])
async def me_wa_lignes(user: dict = Depends(get_current_user)):
    """Lot 59 — lignes WhatsApp de la plateforme (Liluvine Standard / VIP / Publicités…).

    Renvoie pour l'utilisateur : les lignes qu'il voit, et s'il peut affecter un
    contact à une ligne (réservé à ceux qui voient toutes les lignes). Aucun secret.
    """
    from routes.numeros_wa import lignes_configurees, lignes_autorisees, seuil_vip
    s = await db.settings.find_one({"_id": "global"}) or {}
    autorisees = lignes_autorisees(user, s)
    lignes = [
        {k: l[k] for k in ("cle", "libelle", "telephone", "vip", "prospects", "principale",
                           "couleur_fond", "couleur_texte")}
        for l in lignes_configurees(s) if autorisees is None or l["cle"] in autorisees
    ]
    return {"lignes": lignes, "restreint": autorisees is not None,
            "peut_affecter": autorisees is None, "seuil_vip": seuil_vip(s)}


@api.get("/me/contacts/export.csv", tags=["Portail Client"])
async def me_export_contacts_csv(user: dict = Depends(get_current_user)):
    """Iter34w — Export the directory as CSV (Excel-compatible, UTF-8 BOM)."""
    client_ids = await _resolve_visible_client_ids(user)
    items = await db.directory_contacts.find({"client_id": {"$in": client_ids}}, {"_id": 0}).sort("name", 1).to_list(5000)
    flags = await _resolve_anon_flags(user)
    if any(flags.values()):
        items = [_apply_anon_to_contact(c, flags) for c in items]
    import csv, io
    buf = io.StringIO()
    buf.write("\ufeff")  # Excel UTF-8 BOM
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["Code unique", "Nom", "Société", "Téléphone", "WhatsApp", "Email", "Tags", "Partagé", "Créé le"])
    for c in items:
        writer.writerow([
            c.get("unique_code") or "",
            c.get("name") or "",
            c.get("company") or "",
            c.get("phone") or "",
            c.get("whatsapp") or "",
            c.get("email") or "",
            ", ".join(c.get("tags") or []),
            "Oui" if c.get("shared") else "Non",
            (c.get("created_at") or ""),
        ])
    body = buf.getvalue().encode("utf-8")
    fname = f"contacts-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.csv"
    return Response(content=body, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@api.get("/me/contacts/export.json", tags=["Portail Client"])
async def me_export_contacts_json(user: dict = Depends(get_current_user)):
    client_ids = await _resolve_visible_client_ids(user)
    items = await db.directory_contacts.find({"client_id": {"$in": client_ids}}, {"_id": 0}).sort("name", 1).to_list(5000)
    flags = await _resolve_anon_flags(user)
    if any(flags.values()):
        items = [_apply_anon_to_contact(c, flags) for c in items]
    body = json.dumps({"generated_at": _now(), "count": len(items), "contacts": items}, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    fname = f"contacts-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.json"
    return Response(content=body, media_type="application/json; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@api.get("/me/contacts/export.pdf", tags=["Portail Client"])
async def me_export_contacts_pdf(user: dict = Depends(get_current_user)):
    """Iter34w — Generate a PDF listing of the visible directory (ReportLab)."""
    client_ids = await _resolve_visible_client_ids(user)
    items = await db.directory_contacts.find({"client_id": {"$in": client_ids}}, {"_id": 0}).sort("name", 1).to_list(5000)
    flags = await _resolve_anon_flags(user)
    if any(flags.values()):
        items = [_apply_anon_to_contact(c, flags) for c in items]
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    import io
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=24, bottomMargin=24, leftMargin=24, rightMargin=24, title="Liste des contacts")
    styles = getSampleStyleSheet()
    now_str = datetime.now(timezone.utc).strftime('%d/%m/%Y à %H:%M')
    story = [
        Paragraph("<b>SAWALI Smart Systems — Liste des contacts</b>", styles["Title"]),
        Paragraph(f"Généré le {now_str} — {len(items)} contact(s) — Utilisateur : {user.get('email') or user.get('id')}", styles["Normal"]),
        Spacer(1, 10),
    ]
    head = ["#", "Code", "Nom", "Société", "Téléphone", "WhatsApp", "Email"]
    data: List[List[str]] = [head]
    for i, c in enumerate(items, start=1):
        data.append([
            str(i),
            c.get("unique_code") or "",
            (c.get("name") or "")[:48],
            (c.get("company") or "")[:32],
            c.get("phone") or "",
            c.get("whatsapp") or "",
            (c.get("email") or "")[:42],
        ])
    tbl = Table(data, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E90FF")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(tbl)
    # Iter43-fix24az-l retest — Offload reportlab doc.build to thread pool
    # to avoid blocking uvicorn's single-worker event loop (CF 520 mitigation).
    await asyncio.to_thread(doc.build, story)
    body = buf.getvalue()
    fname = f"contacts-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.pdf"
    return Response(content=body, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@api.get("/me/contacts", tags=["Portail Client"])
async def me_list_contacts(user: dict = Depends(get_current_user)):
    """Liste TOUS les contacts dans le scope du client de l'utilisateur.

    Sharing model (iter29 onward, refined iter34): every contact created by
    ANY user of a client is visible to every other user of the same client
    (mirrors the shared-bank model already used by the Media Library). The
    legacy `shared` boolean is preserved on existing rows for traceability but
    no longer gates visibility. Iter34 widens the scope by also including any
    other client_id belonging to a peer user with the SAME company name —
    this bridges historical client_id misalignments without forcing a manual
    realign. RGPD: per-client anonymization flags still apply for non-
    privileged roles, regardless of who owns the contact.

    Iter43-fix5 — Enrichit chaque contact d'un champ `last_interaction_at`
    (max des timestamps WA + SMS pour les digits-10 du numéro WA/téléphone).
    Permet au frontend de trier par date d'interaction décroissante par défaut.
    """
    client_ids = await _resolve_visible_client_ids(user)
    items = await db.directory_contacts.find(
        {"client_id": {"$in": client_ids}}, {"_id": 0},
    ).sort("name", 1).to_list(2000)
    # Lot 59 — lignes WhatsApp (Liluvine Standard / VIP…) : l'utilisateur ne voit
    # que les contacts des lignes qui lui sont autorisées ; chaque contact porte
    # sa ligne (wa_ligne_cle / wa_ligne_libelle) pour l'affichage d'un badge.
    from routes.numeros_wa import VisibiliteLignes, ligne_par_cle
    vis = await VisibiliteLignes.charger(db, user, complet=True)
    if vis.restreint:
        items = [c for c in items if vis.contact_visible(c)]
    if vis.derniere_ligne or vis.tenants_vip or any(c.get("wa_ligne") for c in items):
        for c in items:
            cle = vis.cle_contact(c)
            ligne = ligne_par_cle(vis.settings, cle) or {}
            c["wa_ligne_cle"] = cle
            c["wa_ligne_libelle"] = ligne.get("libelle")
            # Lot 59.1 — couleurs de la pastille de la ligne
            c["wa_ligne_fond"] = ligne.get("couleur_fond")
            c["wa_ligne_texte"] = ligne.get("couleur_texte")
    flags = await _resolve_anon_flags(user)
    if any(flags.values()):
        items = [_apply_anon_to_contact(c, flags) for c in items]

    # Iter43-fix5 — Calcule last_interaction_at (WA + SMS) pour le tri par date d'interaction
    # Lot 23 — clé = 8 derniers chiffres (_phone_suffix), comme le comptage des
    # non-lus : un contact saisi sans indicatif (« 70 11 11 11 ») retrouve ses
    # échanges avec « 22670111111 » (avec 10 chiffres, il n'avait jamais de date).
    phone_map: Dict[str, List[Dict[str, Any]]] = {}
    for c in items:
        d10 = _phone_suffix(c.get("whatsapp") or c.get("phone"))
        if len(d10) >= 6:
            phone_map.setdefault(d10, []).append(c)

    if phone_map:
        # Lot 23 — « dernière interaction » fiable :
        #   - uniquement les messages de CE tenant (avant : tous les tenants,
        #     donc un message d'un autre client au même numéro remontait le contact) ;
        #   - hors envois en masse (`bulk`) : une campagne ne rend pas « récents »
        #     des contacts qui n'ont rien écrit ;
        #   - date = `created_at` (toujours ISO, posé par Sawali) — avant, le champ
        #     `timestamp` de Meta (secondes Unix) était parfois comparé à des dates
        #     ISO, ce qui faussait l'ordre ;
        #   - le sens du dernier échange est renvoyé (reçu / envoyé).
        last_by_phone: Dict[str, Tuple[str, str]] = {}

        def _note(msg: Dict[str, Any], direction: str) -> None:
            ts = str(msg.get("created_at") or "")
            if not ts:
                return
            for k in ("phone_digits", "from", "to"):
                d10 = _phone_suffix(msg.get(k))
                if d10 in phone_map:
                    if d10 not in last_by_phone or ts > last_by_phone[d10][0]:
                        last_by_phone[d10] = (ts, direction)
                    break

        tenant_q = {"client_id": {"$in": client_ids}, "bulk": {"$ne": True}}
        # Lot 29 (performances) — même résultat qu'avant, mais calculé par MongoDB :
        # au lieu de rapatrier jusqu'à 20 000 messages WhatsApp + 20 000 SMS et de
        # les parcourir en Python à chaque affichage de la liste, la base regroupe
        # ces mêmes 20 000 derniers messages par numéro (phone_digits, from, to) et
        # ne renvoie que le plus récent de chaque groupe (quelques centaines de
        # lignes). On les traite ensuite du plus récent au plus ancien, exactement
        # comme l'ancien parcours.
        _pipeline = [
            {"$match": tenant_q},
            {"$sort": {"created_at": -1}},
            {"$limit": 20000},
            {"$group": {"_id": {"p": "$phone_digits", "f": "$from", "t": "$to"},
                        "created_at": {"$first": "$created_at"}, "direction": {"$first": "$direction"}}},
        ]
        for _coll in (db.whatsapp_messages, db.sms_messages):
            try:
                _groups = [g async for g in _coll.aggregate(_pipeline)]
                _groups.sort(key=lambda g: str(g.get("created_at") or ""), reverse=True)
                for g in _groups:
                    _k = g.get("_id") or {}
                    _note({"phone_digits": _k.get("p"), "from": _k.get("f"), "to": _k.get("t"),
                           "created_at": g.get("created_at")},
                          "in" if g.get("direction") == "inbound" else "out")
            except Exception:
                pass
        for d10, contacts in phone_map.items():
            ts, direction = last_by_phone.get(d10, (None, None))
            for c in contacts:
                c["last_interaction_at"] = ts
                c["last_interaction_direction"] = direction
    return items


@api.post("/me/contacts", tags=["Portail Client"])
async def me_create_contact(payload: DirectoryContactCreate, user: dict = Depends(get_current_user)):
    # Iter35h — demo: enforce contact-count cap (uses live row count).
    await _enforce_demo_quota(user, QUOTA_KEY_CONTACTS, increment=1)
    # Enforce admin-configured "tag mandatory" policy: at least one tag is
    # required when settings.contacts_require_tag is True. Helps keep the
    # directory searchable / categorized.
    s = await db.settings.find_one({"_id": "global"}) or {}
    if s.get("contacts_require_tag") and not (payload.tags and any((t or "").strip() for t in payload.tags)):
        raise HTTPException(status_code=400, detail="Au moins un tag est requis (politique d'administration)")
    client_scope = (user.get("client_id") or user.get("id"))
    # A un créateur élevé peut créer un contact pour une AUTRE société-cliente
    # que la sienne (ex. "Ajouter au registre" depuis le Rapporteur d'une
    # intervention/ticket qui vise un client différent) — même règle de
    # confiance que POST /me/interventions, qui accepte déjà n'importe quel
    # client_id existant pour un créateur élevé. Ignoré pour tout le monde
    # d'autre : le scope reste self.
    if payload.client_id and _is_elevated_creator(user):
        target = await db.users.find_one({"id": payload.client_id}, {"_id": 0, "id": 1})
        if not target:
            raise HTTPException(status_code=404, detail="Client lié introuvable")
        client_scope = payload.client_id
    # Generate the inalterable unique business code (YYYY-CLIENTCODE-NNNN).
    # We pull the parent client doc to derive the prefix; fall back to a slug
    # if the parent has no `client_code` set.
    client_doc = await db.users.find_one(
        {"id": client_scope},
        {"_id": 0, "id": 1, "client_code": 1, "company": 1, "full_name": 1},
    ) or {"id": client_scope}
    unique_code = await _next_contact_unique_code(client_doc)
    payload_data = payload.model_dump()
    payload_data.pop("client_id", None)  # resolved into client_scope above — never spread raw
    # Iter29 collaborative model: every contact is shared across the client's
    # users by design. The `shared` flag is forced True so any legacy code path
    # that still inspects it (filters, exports, integrations) keeps working
    # correctly without an explicit override.
    payload_data["shared"] = True
    doc = {
        "id": _uuid(),
        "client_id": client_scope,
        "owner_id": user["id"],
        "owner_label": user.get("full_name") or user.get("email"),
        **payload_data,
        "unique_code": unique_code,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.directory_contacts.insert_one(doc.copy())
    doc.pop("_id", None)
    # Iter34x — activity feed for live toasts
    await _log_activity(client_id=doc["client_id"], kind="contact", action="created", label=doc.get("name") or "(sans nom)", actor=user, target_id=doc["id"])
    return doc


def _is_anon_masked_value(value: Any) -> bool:
    """Iter35f — Detect if a string was produced by our RGPD anonymizers
    (`_anon_name` → `J***`, `_anon_email` → `j***@gmail.com`, `_anon_phone`
    → `+22 ** ** ** 89`). Used by update endpoints to AVOID saving the
    masked sentinel back into the DB and clobbering the real value when
    the user leaves a RGPD-masked field untouched.

    Heuristic: any string containing TWO OR MORE consecutive asterisks is
    considered a mask. Real customer data should never legitimately contain
    `**` (phone masks use `**`, name/email masks use `***`).
    """
    return isinstance(value, str) and "**" in value


@api.put("/me/contacts/{cid}", tags=["Portail Client"])
async def me_update_contact(cid: str, payload: DirectoryContactUpdate, user: dict = Depends(get_current_user)):
    existing = await db.directory_contacts.find_one({"id": cid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Contact introuvable")
    # Iter29 collaborative model: any user within the same client_scope can edit
    # any contact (matches the visibility rule). Iter34 widens scope to include
    # peer users sharing the same company name. Privileged roles can edit
    # cross-client too. Legacy admin override is still respected.
    client_ids = await _resolve_visible_client_ids(user)
    if existing.get("client_id") not in client_ids and user.get("role") not in ("admin", "superviseur"):
        raise HTTPException(status_code=403, detail="Modification non autorisée")
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    # Lot 59 — l'affectation d'un contact à une ligne WhatsApp est réservée aux
    # utilisateurs qui voient toutes les lignes (superviseurs, administrateurs…)
    if "wa_ligne" in update:
        from routes.numeros_wa import lignes_autorisees, ligne_par_cle
        s_lignes = await db.settings.find_one({"_id": "global"}) or {}
        if lignes_autorisees(user, s_lignes) is not None:
            update.pop("wa_ligne")
        elif update["wa_ligne"] and not ligne_par_cle(s_lignes, update["wa_ligne"]):
            raise HTTPException(status_code=400, detail="Ligne WhatsApp inconnue")
    # Iter35f — RGPD: a frontend that displays anonymized values may resend
    # them back on save (the user didn't touch the field). Detect the
    # `***` sentinel and DROP that key so we never overwrite the real
    # value with its mask. Applies to name, company, email, phone, whatsapp.
    masked_skipped: List[str] = []
    for k in ("name", "company", "email", "phone", "whatsapp"):
        if k in update and _is_anon_masked_value(update[k]):
            update.pop(k)
            masked_skipped.append(k)
    # Same policy on update: if tags is explicitly cleared while the policy is on, reject
    s = await db.settings.find_one({"_id": "global"}) or {}
    if s.get("contacts_require_tag") and "tags" in update:
        new_tags = update.get("tags") or []
        if not any((t or "").strip() for t in new_tags):
            raise HTTPException(status_code=400, detail="Au moins un tag est requis (politique d'administration)")
    update["updated_at"] = _now()
    # Track the last-editor for auditability when the editor isn't the owner
    if existing.get("owner_id") != user["id"]:
        update["last_edited_by_id"] = user["id"]
        update["last_edited_by_label"] = user.get("full_name") or user.get("email")
        update["last_edited_at"] = _now()
    await db.directory_contacts.update_one({"id": cid}, {"$set": update})
    await _log_activity(client_id=existing.get("client_id"), kind="contact", action="updated", label=existing.get("name") or "(sans nom)", actor=user, target_id=cid)
    return {"ok": True, "masked_skipped": masked_skipped}


@api.delete("/me/contacts/{cid}", tags=["Portail Client"])
async def me_delete_contact(cid: str, user: dict = Depends(get_current_user)):
    existing = await db.directory_contacts.find_one({"id": cid}, {"_id": 0})
    if not existing:
        return {"ok": True}  # already gone, idempotent
    # Iter29 collaborative model: any user within the same client_scope can
    # delete any contact (matches the visibility/edit rules). Iter34 widens to
    # peers sharing the same company name.
    client_ids = await _resolve_visible_client_ids(user)
    if existing.get("client_id") not in client_ids and user.get("role") not in ("admin", "superviseur"):
        raise HTTPException(status_code=403, detail="Suppression non autorisée")
    await db.directory_contacts.delete_one({"id": cid})
    await _log_activity(client_id=existing.get("client_id"), kind="contact", action="deleted", label=existing.get("name") or "(sans nom)", actor=user, target_id=cid)
    return {"ok": True}


# ---------- Lot 24 — Dédoublonnage des contacts (même numéro) ----------
# Champs pris en compte pour juger qu'une fiche est « plus complète ».
_DUP_SCORE_FIELDS = ("company", "email", "phone", "whatsapp", "notes", "photo_url", "unique_code", "address", "city")


def _contact_completeness(c: Dict[str, Any]) -> int:
    """Nombre d'informations renseignées (le nom compte seulement s'il n'est
    pas un simple numéro ; étiquettes et groupes comptent chacun pour 1)."""
    score = 0
    name = (c.get("name") or "").strip()
    if name and not re.fullmatch(r"\+?[\d\s().-]+", name):
        score += 1
    for f in _DUP_SCORE_FIELDS:
        if str(c.get(f) or "").strip():
            score += 1
    if c.get("tags"):
        score += 1
    if c.get("group_ids"):
        score += 1
    return score


async def _duplicate_groups(user: dict) -> List[Dict[str, Any]]:
    """Groupes de contacts visibles partageant le même numéro (WhatsApp, sinon
    téléphone ; 8 derniers chiffres). Dans chaque groupe, on GARDE la fiche la
    plus complète — à complétude égale, la plus ancienne — et on PROPOSE les
    autres à la suppression (donc les moins complètes, et les plus récentes)."""
    visible_scope = await _resolve_visible_client_ids(user)
    contacts = await db.directory_contacts.find({"client_id": {"$in": visible_scope}}, {"_id": 0}).to_list(5000)
    by_suffix: Dict[str, List[Dict[str, Any]]] = {}
    for c in contacts:
        suffix = _phone_suffix(c.get("whatsapp") or c.get("phone"))
        if len(suffix) >= 6:
            by_suffix.setdefault(suffix, []).append(c)
    groups = []
    for suffix, items in by_suffix.items():
        if len(items) < 2:
            continue
        ranked = sorted(items, key=lambda c: (-_contact_completeness(c), str(c.get("created_at") or "")))

        def _summary(c: Dict[str, Any]) -> Dict[str, Any]:
            return {"id": c.get("id"), "name": c.get("name"), "whatsapp": c.get("whatsapp"), "phone": c.get("phone"),
                    "company": c.get("company"), "email": c.get("email"), "tags": c.get("tags") or [],
                    "created_at": c.get("created_at"), "score": _contact_completeness(c)}
        groups.append({"phone_suffix": suffix, "keep": _summary(ranked[0]),
                       "duplicates": [_summary(c) for c in ranked[1:]]})
    groups.sort(key=lambda g: g["keep"].get("name") or "")
    return groups


@api.get("/me/contacts-duplicates", tags=["Portail Client"])
async def me_contacts_duplicates(user: dict = Depends(get_current_user)):
    """Lot 24 — propose les doublons à supprimer (réservé au superviseur)."""
    if user.get("role") != "superviseur":
        raise HTTPException(status_code=403, detail="Outil de dédoublonnage réservé au superviseur")
    groups = await _duplicate_groups(user)
    return {"groups": groups, "duplicates_count": sum(len(g["duplicates"]) for g in groups)}


class ContactsDuplicatesDeleteRequest(BaseModel):
    ids: List[str]


@api.post("/me/contacts-duplicates/delete", tags=["Portail Client"])
async def me_contacts_duplicates_delete(payload: ContactsDuplicatesDeleteRequest, user: dict = Depends(get_current_user)):
    """Lot 24 — supprime les doublons COCHÉS par le superviseur. Seules les
    fiches proposées comme doublons (jamais la fiche gardée d'un groupe)
    peuvent être supprimées ; leurs messages WhatsApp/SMS sont rattachés à la
    fiche gardée avant la suppression, pour ne rien perdre de l'historique."""
    if user.get("role") != "superviseur":
        raise HTTPException(status_code=403, detail="Outil de dédoublonnage réservé au superviseur")
    wanted = set(payload.ids or [])
    keep_of: Dict[str, Dict[str, Any]] = {}
    for g in await _duplicate_groups(user):
        for d in g["duplicates"]:
            if d["id"] in wanted:
                keep_of[d["id"]] = g["keep"]
    deleted = 0
    for dup_id, keep in keep_of.items():
        await db.whatsapp_messages.update_many({"contact_id": dup_id},
                                               {"$set": {"contact_id": keep["id"], "contact_name": keep.get("name")}})
        await db.sms_messages.update_many({"contact_id": dup_id}, {"$set": {"contact_id": keep["id"]}})
        res = await db.directory_contacts.delete_one({"id": dup_id})
        if getattr(res, "deleted_count", 0):
            deleted += 1
            await _log_activity(client_id=None, kind="contact", action="deleted",
                                label=f"Doublon supprimé (gardé : {keep.get('name') or keep['id']})", actor=user, target_id=dup_id)
    return {"ok": True, "deleted": deleted, "ignored": len(wanted) - len(keep_of)}


@api.post("/me/contacts/{cid}/photo", tags=["Portail Client"])
async def me_upload_contact_photo(cid: str, request: Request, file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """Upload a profile picture for a contact (à la WhatsApp avatar). Stored in
    /api/files/ and the contact's `photo_url` field is set to the public URL.
    Owner, admin, superviseur, or any user in the same client_scope. Max 5 MiB.
    PNG/JPEG/WEBP only.
    Iter37f — Same collaborative ACL as PUT /me/contacts/{cid}."""
    existing = await db.directory_contacts.find_one({"id": cid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Contact introuvable")
    client_ids = await _resolve_visible_client_ids(user)
    if existing.get("client_id") not in client_ids and user.get("role") not in ("admin", "superviseur"):
        raise HTTPException(status_code=403, detail="Modification non autorisée")
    ctype = (file.content_type or "").lower()
    if ctype not in ("image/png", "image/jpeg", "image/jpg", "image/webp"):
        raise HTTPException(status_code=400, detail="Format invalide — PNG/JPEG/WEBP uniquement")
    file_id = _uuid()
    suffix = Path(file.filename or "").suffix.lower() or ".png"
    safe_name = f"{file_id}{suffix}"
    # 2026-02 fork iter108 — Deploy-safe upload helper (storage-first, local cache).
    from storage import asave_upload_and_cache  # lot 26 : dans un thread, sans figer le serveur
    data = await file.read()
    size = len(data)
    if size > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Photo trop lourde (max 5 Mo)")
    target, storage_path, storage_error = await asave_upload_and_cache(
        upload_dir=UPLOAD_DIR, filename=safe_name, data=data, content_type=ctype,
    )
    ext_suffix = suffix.lstrip(".")
    public_path = f"/api/files/{file_id}.{ext_suffix}" if ext_suffix else f"/api/files/{file_id}"
    if storage_error:
        logger.warning("[contact_photo] storage mirror failed: %s", storage_error)
    await db.files.insert_one({
        "id": file_id, "filename": file.filename, "stored_name": safe_name,
        "extension": ext_suffix or None, "content_type": ctype, "size": size,
        "url": public_path, "uploaded_at": _now(), "uploaded_by_id": user.get("id"),
        "storage_path": storage_path, "storage_error": storage_error,
    })
    await db.directory_contacts.update_one(
        {"id": cid},
        {"$set": {"photo_url": public_path, "photo_updated_at": _now()}},
    )
    return {"ok": True, "photo_url": public_path}


@api.delete("/me/contacts/{cid}/photo", tags=["Portail Client"])
async def me_delete_contact_photo(cid: str, user: dict = Depends(get_current_user)):
    """Remove a contact's profile picture (sets photo_url to null).
    Iter37f — Same collaborative ACL as PUT /me/contacts/{cid}."""
    existing = await db.directory_contacts.find_one({"id": cid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Contact introuvable")
    client_ids = await _resolve_visible_client_ids(user)
    if existing.get("client_id") not in client_ids and user.get("role") not in ("admin", "superviseur"):
        raise HTTPException(status_code=403, detail="Modification non autorisée")
    await db.directory_contacts.update_one(
        {"id": cid},
        {"$set": {"photo_url": None, "photo_updated_at": _now()}},
    )
    return {"ok": True}


# ---------- WhatsApp profile sync (manual button + auto on first inbound) ----------
# IMPORTANT: Meta Cloud API does NOT expose third-party profile pictures or
# `about` fields — privacy by design. The only field we can reliably retrieve
# is `profile.name` from the `contacts[]` array of inbound webhooks. The
# button below therefore reads the most recent inbound for the contact's
# phone and pulls the latest `from_profile_name` we logged. It does NOT make
# a real-time API call to Meta (no such endpoint exists).
@api.post("/me/contacts/{cid}/wa-sync", tags=["Portail Client"])
async def me_contact_wa_sync(cid: str, user: dict = Depends(get_current_user)):
    """Read the latest WhatsApp profile name we observed for this contact's
    phone in inbound messages and store it on the contact. Returns the
    suggested name so the UI can prompt the user before overwriting."""
    contact = await db.directory_contacts.find_one({"id": cid}, {"_id": 0})
    if not contact:
        raise HTTPException(status_code=404, detail="Contact introuvable")
    # Iter37f — Same collaborative ACL as PUT /me/contacts/{cid}.
    client_ids = await _resolve_visible_client_ids(user)
    if contact.get("client_id") not in client_ids and user.get("role") not in ("admin", "superviseur"):
        raise HTTPException(status_code=403, detail="Modification non autorisée")

    digits = []
    for raw in (contact.get("whatsapp") or "", contact.get("phone") or ""):
        d = "".join(ch for ch in (raw or "") if ch.isdigit())
        if d:
            digits.append(d)
    if not digits:
        raise HTTPException(status_code=400, detail="Aucun numéro de téléphone configuré sur ce contact")

    msg = await db.whatsapp_messages.find_one(
        {
            "direction": "inbound",
            "phone_digits": {"$in": digits},
            "from_profile_name": {"$nin": [None, ""]},
        },
        {"_id": 0, "from_profile_name": 1, "received_at": 1, "created_at": 1},
        sort=[("created_at", -1)],
    )
    if not msg:
        return {
            "ok": False,
            "reason": "no_inbound",
            "message": "Aucun message reçu de ce contact pour le moment. La synchronisation s'effectuera automatiquement dès qu'il vous écrira sur WhatsApp.",
        }

    suggested = (msg.get("from_profile_name") or "").strip()
    if not suggested:
        return {"ok": False, "reason": "no_profile_name", "message": "Le contact n'a pas de nom de profil WhatsApp public."}

    await db.directory_contacts.update_one(
        {"id": cid},
        {"$set": {"wa_profile_name": suggested, "wa_profile_synced_at": _now()}},
    )
    return {
        "ok": True,
        "suggested_name": suggested,
        "current_name": contact.get("name"),
        "observed_at": msg.get("received_at") or msg.get("created_at"),
        "note": "Meta Cloud API n'expose pas la photo de profil. Téléversez-la manuellement.",
    }


@api.get("/me/wa-pending-imports", tags=["Portail Client"])
async def me_list_wa_pending_imports(user: dict = Depends(get_current_user)):
    """Liste les numéros de téléphone inconnus ayant écrit à notre WhatsApp Business
    line but aren't yet in the directory. Sorted by last_seen_at desc."""
    client_scope = (user.get("client_id") or user.get("id"))
    q = {} if user.get("role") == "admin" else {"client_id": client_scope}
    items = await db.wa_pending_imports.find(q, {"_id": 0}).sort("last_seen_at", -1).to_list(50)
    # Lot 24 — un numéro déjà présent dans le carnet (créé entre-temps, par
    # exemple par l'ajout automatique de Liluvine) n'est plus proposé : son
    # entrée est supprimée, sinon « Enregistrer » créait un doublon.
    visible_scope = await _resolve_visible_client_ids(user)
    kept: List[Dict[str, Any]] = []
    seen_digits: set = set()
    # Lot 29 (performances) — avant : une recherche par expression régulière dans
    # tout le carnet POUR CHAQUE numéro en attente (jusqu'à 50), toutes les 15 s.
    # Maintenant : le carnet est lu une seule fois et on garde, pour chaque
    # numéro (WhatsApp, téléphone, phone_digits), ses 6, 7 et 8 derniers chiffres.
    # Même règle qu'avant (_find_contact_by_phone) : un contact correspond si les
    # chiffres de l'un de ces champs se terminent par ceux du numéro en attente
    # (6 à 8 chiffres, mise en forme ignorée).
    known_tails: set = set()
    if items:
        _contacts_q = {} if user.get("role") == "admin" else {"client_id": {"$in": visible_scope}}
        async for c in db.directory_contacts.find(_contacts_q, {"_id": 0, "whatsapp": 1, "phone": 1, "phone_digits": 1}):
            for raw in (c.get("whatsapp"), c.get("phone"), c.get("phone_digits")):
                if isinstance(raw, str):
                    d = "".join(ch for ch in raw if ch.isdigit())
                    for n in (6, 7, 8):
                        if len(d) >= n:
                            known_tails.add(d[-n:])
    for it in items:
        suffix = _phone_suffix(it.get("phone_digits") or it.get("from"))
        existing = len(suffix) >= 6 and suffix in known_tails
        if existing or (suffix and suffix in seen_digits):
            await db.wa_pending_imports.delete_one({"id": it.get("id")})
            continue
        seen_digits.add(suffix)
        kept.append(it)
    return kept


class WaPendingImportRequest(BaseModel):
    name: Optional[str] = None  # If empty, fallback to wa_profile_name
    company: Optional[str] = None
    email: Optional[str] = None


# Iter36a — Direct phone-based import (used by "Top expéditeurs" card on the dashboard)
class WaImportByPhoneRequest(BaseModel):
    phone_digits: str
    name: Optional[str] = None


@api.post("/me/wa-import-by-phone", tags=["Portail Client"])
async def me_wa_import_by_phone(payload: WaImportByPhoneRequest, user: dict = Depends(get_current_user)):
    """Crée un contact d'annuaire directement depuis un numéro de téléphone (utilisé par
    Dashboard's "Top expéditeurs" card when the user clicks Import on a sender
    that's not yet in the directory)."""
    digits = "".join(ch for ch in (payload.phone_digits or "") if ch.isdigit())
    if not digits:
        raise HTTPException(status_code=400, detail="Numéro invalide")
    client_scope = (user.get("client_id") or user.get("id"))
    visible_scope = await _resolve_visible_client_ids(user)
    # Iter36h — Idempotent uniqueness via Python-side digit comparison so we
    # match contacts whose phone/whatsapp uses any formatting (spaces, +, 00…).
    tail8 = digits[-8:] if len(digits) >= 8 else digits
    existing = None
    async for c in db.directory_contacts.find(
        {"client_id": {"$in": visible_scope}},
        {"_id": 0},
    ):
        for raw in (c.get("phone_digits"), c.get("whatsapp_digits"),
                    c.get("phone"), c.get("whatsapp")):
            if not raw:
                continue
            d = "".join(ch for ch in str(raw) if ch.isdigit())
            if d == digits or (len(d) >= 8 and d.endswith(tail8)):
                existing = c
                break
        if existing:
            break
    if existing:
        return {"ok": True, "already_present": True, "contact": existing}
    sample = await db.whatsapp_messages.find_one(
        {"client_id": {"$in": visible_scope}, "phone_digits": digits, "direction": "inbound"},
        {"_id": 0, "from": 1, "from_profile_name": 1, "contact_name": 1},
        sort=[("created_at", -1)],
    ) or {}
    name = (payload.name or sample.get("from_profile_name") or sample.get("contact_name")
            or sample.get("from") or f"+{digits}").strip()
    new_id = _uuid()
    contact = {
        "id": new_id,
        "client_id": client_scope,
        "owner_id": user["id"],
        "name": name,
        "phone": f"+{digits}",
        "phone_digits": digits,
        "whatsapp": f"+{digits}",
        "email": "",
        "company": "",
        "notes": "Importé depuis le Top expéditeurs WhatsApp",
        "tags": ["wa-import"],
        "shared": False,
        "photo_url": None,
        "wa_profile_name": sample.get("from_profile_name"),
        "wa_profile_synced_at": _now(),
        "created_at": _now(),
    }
    await db.directory_contacts.insert_one(contact.copy())
    await db.whatsapp_messages.update_many(
        {"client_id": client_scope, "direction": "inbound", "phone_digits": digits, "contact_id": None},
        {"$set": {"contact_id": new_id, "contact_name": name}},
    )
    contact.pop("_id", None)
    return {"ok": True, "already_present": False, "contact": contact}



@api.post("/me/wa-pending-imports/{pending_id}/import", tags=["Portail Client"])
async def me_import_wa_pending(pending_id: str, payload: WaPendingImportRequest, user: dict = Depends(get_current_user)):
    """Promote a pending WA inbound to a full directory contact. Optionally
    overrides the suggested name."""
    pending = await db.wa_pending_imports.find_one({"id": pending_id}, {"_id": 0})
    if not pending:
        raise HTTPException(status_code=404, detail="Inconnu")
    client_scope = (user.get("client_id") or user.get("id"))
    if user.get("role") != "admin" and pending.get("client_id") != client_scope:
        raise HTTPException(status_code=403, detail="Hors de votre périmètre")
    name = (payload.name or pending.get("wa_profile_name") or pending.get("from") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nom requis")
    # Lot 24 — idempotent : si ce numéro existe déjà dans le carnet (ajout
    # automatique Liluvine, double clic, entrée en double…), on NE crée PAS de
    # second contact : on rattache les messages au contact existant.
    visible_scope = await _resolve_visible_client_ids(user)
    raw_phone = pending.get("phone_digits") or pending.get("from")
    existing = await _find_contact_by_phone(visible_scope, raw_phone)
    rx = _phone_suffix_regex(raw_phone)
    if existing:
        if rx:
            await db.whatsapp_messages.update_many(
                {"client_id": {"$in": visible_scope}, "direction": "inbound", "phone_digits": {"$regex": rx}, "contact_id": None},
                {"$set": {"contact_id": existing["id"], "contact_name": existing.get("name")}},
            )
            await db.wa_pending_imports.delete_many({"phone_digits": {"$regex": rx}, "client_id": {"$in": visible_scope}})
        await db.wa_pending_imports.delete_one({"id": pending_id})
        return {"ok": True, "already_present": True, "contact": existing}
    new_id = _uuid()
    contact = {
        "id": new_id,
        "client_id": client_scope,
        "owner_id": user["id"],
        "name": name,
        "phone": pending.get("from") or "",
        "whatsapp": pending.get("from") or "",
        "email": (payload.email or "").strip(),
        "company": (payload.company or "").strip(),
        "notes": f"Importé depuis WhatsApp ({pending.get('messages_count', 0)} message(s) reçu(s))",
        "tags": ["wa-import"],
        "shared": False,
        "photo_url": None,
        "wa_profile_name": pending.get("wa_profile_name"),
        "wa_profile_synced_at": _now(),
        "created_at": _now(),
    }
    await db.directory_contacts.insert_one(contact.copy())
    # Re-link past inbound messages to the new contact
    digits = pending.get("phone_digits") or ""
    if digits:
        await db.whatsapp_messages.update_many(
            {"client_id": client_scope, "direction": "inbound", "phone_digits": digits, "contact_id": None},
            {"$set": {"contact_id": new_id, "contact_name": name}},
        )
    await db.wa_pending_imports.delete_one({"id": pending_id})
    # Lot 24 — autres entrées « inconnu » du même numéro (autre tenant visible) : devenues sans objet.
    if rx:
        await db.wa_pending_imports.delete_many({"phone_digits": {"$regex": rx}, "client_id": {"$in": visible_scope}})
    contact.pop("_id", None)
    return {"ok": True, "already_present": False, "contact": contact}


@api.delete("/me/wa-pending-imports/{pending_id}", tags=["Portail Client"])
async def me_dismiss_wa_pending(pending_id: str, user: dict = Depends(get_current_user)):
    """Permanently dismiss a pending WA inbound (won't reappear unless they
    write to us again)."""
    pending = await db.wa_pending_imports.find_one({"id": pending_id}, {"_id": 0})
    if not pending:
        raise HTTPException(status_code=404, detail="Inconnu")
    client_scope = (user.get("client_id") or user.get("id"))
    if user.get("role") != "admin" and pending.get("client_id") != client_scope:
        raise HTTPException(status_code=403, detail="Hors de votre périmètre")
    await db.wa_pending_imports.delete_one({"id": pending_id})
    return {"ok": True}


# ----- Send WhatsApp from portal -----
class WhatsAppSendRequest(BaseModel):
    to: str  # E.164 phone number (contact's whatsapp field, or tracked-user's phone)
    template_name: str
    language_code: Optional[str] = "fr"
    components: Optional[list] = None  # Template variables (body, header, button params)
    contact_id: Optional[str] = None
    tracked_user_id: Optional[str] = None
    # 2026-02 (#4) — Rendered preview computed client-side, persisted on the
    # WhatsApp log so the messaging center can display "what was delivered".
    template_rendered_body: Optional[str] = None


@api.post("/me/whatsapp/send", tags=["Portail Client"])
async def me_whatsapp_send(payload: WhatsAppSendRequest, user: dict = Depends(get_current_user)):
    # RBAC: elevated roles (Moderator/Admin/Superviseur) + the main client account + tracked users (any role)
    allowed = (
        user.get("role") in ("client", "admin")
        or _is_elevated_creator(user)
        or _is_tracked_user(user)
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Rôle non autorisé à envoyer des messages WhatsApp")
    # Iter34h — RGPD: resolve real WhatsApp number from contact_id if available,
    # to bypass any frontend-side anonymization mask.
    to = await _resolve_real_phone(payload.contact_id, "whatsapp", payload.to or "")
    if not to:
        raise HTTPException(status_code=400, detail="Numéro destinataire requis")
    # Lot 59 — correspondant d'une ligne WhatsApp non attribuée à l'utilisateur : envoi refusé
    from routes.numeros_wa import exiger_telephone_visible
    await exiger_telephone_visible(db, user, to, payload.contact_id)
    result = await _wa_send_template(to, payload.template_name, payload.language_code or "fr", payload.components)
    # Extract any /pay/{slug} URL embedded in the template variables for channel attribution
    pay_slug = None
    try:
        blob = json.dumps(payload.components or [], ensure_ascii=False)
        pay_slug = _extract_pay_slug(blob)
    except Exception:  # noqa: BLE001
        pass
    # Log the attempt
    client_scope = (user.get("client_id") or user.get("id"))
    digits_only = "".join(ch for ch in to if ch.isdigit())
    log = {
        "id": _uuid(),
        "client_id": client_scope,
        "direction": "outbound",
        "sender_id": user["id"],
        "sender_label": user.get("full_name") or user.get("email"),
        "to": to,
        "phone_digits": digits_only,
        "template_name": payload.template_name,
        "language_code": payload.language_code,
        # 2026-02 (#4) — Rendered preview of the actually delivered message,
        # so the messaging center can show it below the template name.
        "template_rendered_body": payload.template_rendered_body,
        "body": payload.template_rendered_body or None,
        "contact_id": payload.contact_id,
        "tracked_user_id": payload.tracked_user_id,
        "ok": result["ok"],
        "status": result["status"],
        "message_id": result["message_id"],
        "error": result.get("error"),
        "wa_status": "sent" if result["ok"] else "failed",
        "sent_at": _now() if result["ok"] else None,
        "failed_at": None if result["ok"] else _now(),
        "payment_link_slug": pay_slug,
        "created_at": _now(),
    }
    try: await db.whatsapp_messages.insert_one(log.copy())
    except Exception: pass
    if log.get("status") in ("sent", "queued") and log.get("client_id"):
        # 2026-02 fork bugfix — Fetch contact name if provided, else fall back to phone.
        _label = to
        if payload.contact_id:
            try:
                _cdoc = await db.directory_contacts.find_one({"id": payload.contact_id}, {"_id": 0, "name": 1}) or {}
                if _cdoc.get("name"):
                    _label = _cdoc["name"]
            except Exception:
                pass
        await _log_activity(client_id=log["client_id"], kind="whatsapp", action="sent", label=f"→ {_label}", actor=user, target_id=log.get("id"))
    log.pop("_id", None)
    return {"ok": result["ok"], "message_id": result["message_id"], "error": result.get("error"), "http_status": result["status"]}


@api.get("/me/whatsapp/history", tags=["Portail Client"])
async def me_whatsapp_history(limit: int = 100, user: dict = Depends(get_current_user)):
    client_scope = (user.get("client_id") or user.get("id"))
    query = {"client_id": client_scope} if user.get("role") != "admin" else {}
    items = await db.whatsapp_messages.find(query, {"_id": 0}).sort("created_at", -1).to_list(min(max(limit, 1), 500))
    return items


# ---------- Free-form text within Meta 24h customer service window ----------
WA_24H_WINDOW_SECONDS = 24 * 3600
WA_MEDIA_MAX_BYTES = 64 * 1024 * 1024  # Meta's hard cap: 100MB video/document, 16MB image. Safe cap 64MB.

# Iter43-fix24az-q — Attach db-bound WhatsApp helpers from routes/whatsapp_helpers.py.
# Binds returned coroutines to module globals so existing call sites work unchanged.
#
# Iter43-fix24az-w (2026-07-22) — Wire silent-drop observer. Uses a mutable
# closure so the observer can be created BEFORE wa_send_text (which it needs
# to send WA alerts) : the callback is a stub at first and gets replaced with
# the real `record_and_notify` right after wa_silent_drops routes are set up.
_wa_silent_drop_holder: Dict[str, Any] = {"cb": None}


async def _on_silent_drop(ctx: Dict[str, Any]) -> None:
    cb = _wa_silent_drop_holder.get("cb")
    if cb is not None:
        await cb(ctx)


_wa_helpers = _attach_whatsapp_helpers(
    db=db,
    wa_graph_version=WA_GRAPH_VERSION,
    wa_media_max_bytes=WA_MEDIA_MAX_BYTES,
    upload_dir=UPLOAD_DIR,
    uuid_fn=_uuid,
    now_fn=_now,
    on_silent_drop=_on_silent_drop,
)
_wa_send_template = _wa_helpers["_wa_send_template"]
_wa_send_text = _wa_helpers["_wa_send_text"]
_wa_send_interactive_button = _wa_helpers["_wa_send_interactive_button"]
_wa_send_media = _wa_helpers["_wa_send_media"]
_wa_download_inbound_media = _wa_helpers["_wa_download_inbound_media"]
_wa_transcribe_audio_file = _wa_helpers["_wa_transcribe_audio_file"]
_wa_compute_reply_window = _wa_helpers["_wa_compute_reply_window"]
_wa_last_inbound_iso = _wa_helpers["_wa_last_inbound_iso"]
# 2026-02 fork (P0.5) — Tenant Smart Comm credential resolver (WA)
_resolve_wa_credentials = _wa_helpers["_resolve_wa_credentials"]

# 2026-02 fork (P0.5 extended) — Multi-channel Smart Comm resolver
# (Meta, Instagram, LinkedIn, X, TikTok). WA still uses the specialised
# helper above because it powers extra behaviour (auto-split, silent-drop
# observer, media downloader).
from routes.smart_comm_resolver import build_smart_comm_resolver  # noqa: E402
_smart_comm_resolver = build_smart_comm_resolver(db)

# Set up wa_silent_drops routes + wire the observer. Import here to avoid
# any module-load ordering hazards with the FastAPI `api` instance.
from routes.wa_silent_drops import setup_wa_silent_drops_routes as _setup_wa_silent_drops_routes  # noqa: E402
_wa_drops_helpers = _setup_wa_silent_drops_routes(
    api=api,
    db=db,
    get_current_admin=get_current_admin,
    send_email_fn=send_email,
    wa_send_text_fn=_wa_send_text,
)
_wa_silent_drop_holder["cb"] = _wa_drops_helpers["record_and_notify"]


def _wa_window_open(last_inbound_iso: Optional[str]) -> bool:
    """Return True when the last inbound is within the 24h Meta customer service window."""
    return _wa_window_open_helper(last_inbound_iso, WA_24H_WINDOW_SECONDS)


class WhatsAppSendTextRequest(BaseModel):
    to: str
    text: str
    contact_id: Optional[str] = None
    tracked_user_id: Optional[str] = None
    # Iter37h — Optional reply-to context (WhatsApp Cloud API context.message_id)
    reply_to_message_id: Optional[str] = None


@api.post("/me/whatsapp/send-text", tags=["Portail Client"])
async def me_whatsapp_send_text(payload: WhatsAppSendTextRequest, user: dict = Depends(get_current_user)):
    """Envoie un message texte WhatsApp libre — autorisé uniquement dans la fenêtre Meta de 24h
    customer service window (i.e. the contact has written to us in the last 24h)."""
    allowed = (
        user.get("role") in ("client", "admin", "demo")
        or _is_elevated_creator(user)
        or _is_tracked_user(user)
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Rôle non autorisé à envoyer des messages WhatsApp")
    await _enforce_demo_quota(user, QUOTA_KEY_WA)  # Iter35h
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Le message ne peut pas être vide")
    if len(text) > 4096:
        raise HTTPException(status_code=400, detail="Message trop long (4096 caractères max)")
    # Iter34h — RGPD: resolve real WhatsApp number from contact_id if available
    to = await _resolve_real_phone(payload.contact_id, "whatsapp", payload.to or "")
    if not to:
        raise HTTPException(status_code=400, detail="Numéro destinataire requis")
    # Lot 59 — correspondant d'une ligne WhatsApp non attribuée à l'utilisateur : envoi refusé
    from routes.numeros_wa import exiger_telephone_visible
    await exiger_telephone_visible(db, user, to, payload.contact_id)

    client_scope = (user.get("client_id") or user.get("id"))
    digits_only = "".join(ch for ch in to if ch.isdigit())

    # Verify 24h window: must have a recent inbound from this contact/phone
    # Iter35f — widen the lookup to every visible client_id of the user
    # (the webhook may have anchored the inbound on the primary superviseur,
    # whose client_id differs from the user's own).
    visible_scope = await _resolve_visible_client_ids(user)
    last_iso = await _wa_last_inbound_iso(visible_scope, contact_id=payload.contact_id, phone_digits=digits_only)
    if not _wa_window_open(last_iso):
        raise HTTPException(
            status_code=409,
            detail="Fenêtre 24h fermée — aucun message reçu de ce contact dans les dernières 24 heures. Utilisez un template Meta approuvé.",
        )

    result = await _wa_send_text(to, text, reply_to_message_id=payload.reply_to_message_id)
    # Iter35n — Compute reply-time for the most recent unanswered inbound
    reply_window = None
    if result.get("ok"):
        try:
            reply_window = await _wa_compute_reply_window(
                visible_scope, contact_id=payload.contact_id, phone_digits=digits_only,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("WA reply-window calc failed (text): %s", exc)
    log = {
        "id": _uuid(),
        "client_id": client_scope,
        "direction": "outbound",
        "sender_id": user["id"],
        "sender_label": user.get("full_name") or user.get("email"),
        "to": to,
        "phone_digits": digits_only,
        "template_name": None,
        "language_code": None,
        "message_type": "text",
        "body": text,
        "contact_id": payload.contact_id,
        "tracked_user_id": payload.tracked_user_id,
        "ok": result["ok"],
        "status": result["status"],
        "message_id": result["message_id"],
        "error": result.get("error"),
        "wa_status": "sent" if result["ok"] else "failed",
        "sent_at": _now() if result["ok"] else None,
        "failed_at": None if result["ok"] else _now(),
        "created_at": _now(),
    }
    if reply_window:
        log["reply_to_inbound_id"] = reply_window["inbound_id"]
        log["reply_to_inbound_received_at"] = reply_window["inbound_received_at"]
        log["reply_seconds"] = reply_window["reply_seconds"]
    # Iter37h — Persist quote context for the chat thread UI
    if payload.reply_to_message_id:
        log["reply_to_message_id"] = payload.reply_to_message_id
    try:
        await db.whatsapp_messages.insert_one(log.copy())
    except Exception:
        pass
    log.pop("_id", None)
    return {"ok": result["ok"], "message_id": result["message_id"], "error": result.get("error"), "http_status": result["status"], "reply_seconds": (reply_window or {}).get("reply_seconds")}


# =====================================================================
# Iter35l — POST /me/whatsapp/send-media
# Send an image/document/audio/video to a contact (multipart upload).
# Constraints:
#   - 24h Meta customer-service window (same rule as send-text).
#   - Images: optional watermark + QR (admin-configurable in settings).
#   - Files are persisted via the media_library so each public URL is
#     stable and ext-visible (e.g. /api/files/{id}.jpg) — accepted by Meta.
# =====================================================================
WA_SEND_MEDIA_MAX_BYTES = 16 * 1024 * 1024  # 16MB — Meta image cap; safe for our PoC for all types


@api.post("/me/whatsapp/send-media", tags=["Portail Client"])
async def me_whatsapp_send_media(
    request: Request,
    to: str = Form(...),
    contact_id: Optional[str] = Form(None),
    tracked_user_id: Optional[str] = Form(None),
    caption: Optional[str] = Form(None),
    add_watermark: Optional[str] = Form(None),  # "1"/"0"/empty (defaults to admin setting)
    add_qr: Optional[str] = Form(None),         # "1"/"0"/empty (defaults to admin setting)
    reply_to_message_id: Optional[str] = Form(None),  # Iter37h — quote inbound msg
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """Envoie un message média WhatsApp libre dans la fenêtre Meta de 24h."""
    allowed = (
        user.get("role") in ("client", "admin", "demo")
        or _is_elevated_creator(user)
        or _is_tracked_user(user)
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Rôle non autorisé à envoyer des médias WhatsApp")

    # Admin-level RGPD toggle: terminal upload of media may be globally disabled
    s_root = await db.settings.find_one({"_id": "global"}) or {}
    if not bool(s_root.get("wa_allow_terminal_media", True)):
        raise HTTPException(status_code=403, detail="L'envoi de médias depuis ce terminal a été désactivé par l'administrateur.")

    await _enforce_demo_quota(user, QUOTA_KEY_WA)

    # Resolve real phone (RGPD anonymization restore)
    real_to = await _resolve_real_phone(contact_id, "whatsapp", to or "")
    if not real_to:
        raise HTTPException(status_code=400, detail="Numéro destinataire requis")
    # Lot 59 — correspondant d'une ligne WhatsApp non attribuée à l'utilisateur : envoi refusé
    from routes.numeros_wa import exiger_telephone_visible
    await exiger_telephone_visible(db, user, real_to, contact_id)

    digits_only = "".join(ch for ch in real_to if ch.isdigit())

    # 24h customer-service window
    visible_scope = await _resolve_visible_client_ids(user)
    last_iso = await _wa_last_inbound_iso(visible_scope, contact_id=contact_id, phone_digits=digits_only)
    if not _wa_window_open(last_iso):
        raise HTTPException(
            status_code=409,
            detail="Fenêtre 24h fermée — aucun message reçu de ce contact dans les dernières 24 heures.",
        )

    # Save the upload locally
    suffix = Path(file.filename or "").suffix.lower()
    content_type = (file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream").split(";", 1)[0].strip()
    kind = _wa_kind_for_mime(content_type)
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Fichier vide")
    if len(raw) > WA_SEND_MEDIA_MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"Fichier trop volumineux (max {WA_SEND_MEDIA_MAX_BYTES // (1024*1024)} Mo)")

    file_id = _uuid()
    safe_name = f"{file_id}{suffix}"
    # 2026-02 fork iter108 — Deploy-safe upload helper (storage-first, local cache).
    from storage import asave_upload_and_cache  # lot 26 : dans un thread, sans figer le serveur
    target, _wa_storage_path, _wa_storage_error = await asave_upload_and_cache(
        upload_dir=UPLOAD_DIR, filename=safe_name, data=raw, content_type=content_type,
    )
    if _wa_storage_error:
        logger.warning("[wa_send_media] storage mirror failed: %s", _wa_storage_error)

    # Optional image watermark + QR
    if kind == "image":
        wm_on = bool(s_root.get("wa_watermark_enabled", True))
        qr_on = bool(s_root.get("wa_qr_enabled", True))
        # Allow per-request override (form fields). Treat empty string as "use default".
        if isinstance(add_watermark, str) and add_watermark.strip() in ("0", "false", "no"):
            wm_on = False
        elif isinstance(add_watermark, str) and add_watermark.strip() in ("1", "true", "yes"):
            wm_on = True
        if isinstance(add_qr, str) and add_qr.strip() in ("0", "false", "no"):
            qr_on = False
        elif isinstance(add_qr, str) and add_qr.strip() in ("1", "true", "yes"):
            qr_on = True
        wm_text = (s_root.get("wa_watermark_text") or s_root.get("company_name") or "SAWALI SMART SYSTEMS").strip() if wm_on else None
        qr_payload = (s_root.get("wa_qr_payload") or s_root.get("company_website") or "").strip() if qr_on else None
        if not qr_payload and qr_on:
            # Fallback to public base url so the QR always means something
            base = _public_base_url(request) or (PUBLIC_BASE_URL or "")
            qr_payload = (base or "").rstrip("/") or None
        if wm_text or qr_payload:
            new_path = _wa_apply_image_watermark_qr(target, watermark_text=wm_text, qr_payload=qr_payload)
            if new_path != target:
                # Replace stored bytes with the watermarked version (new ext .jpg)
                try:
                    target.unlink(missing_ok=True)
                except Exception:
                    pass
                suffix = new_path.suffix
                safe_name = f"{file_id}{suffix}"
                target = UPLOAD_DIR / safe_name
                new_path.rename(target)
                content_type = "image/jpeg"
                kind = "image"
                raw = target.read_bytes()  # refresh size

    # Persist into files collection so /api/files/{id}.ext can serve it externally (Meta accesses by URL)
    ext = suffix.lstrip(".") or ""
    public_path = f"/api/files/{file_id}{('.' + ext) if ext else ''}"
    public_url = f"{(_public_base_url(request) or str(request.base_url).rstrip('/'))}{public_path}"
    # Iter38r-fix8 — Mirror to Emergent Object Storage (best-effort) so Meta
    # can still fetch the URL after a redeploy wipes the local disk.
    storage_path = None
    storage_error = None
    try:
        from storage import aupload_bytes, astorage_available  # lot 26 : non bloquant
        if await astorage_available():
            storage_path = await aupload_bytes(f"files/{safe_name}", await asyncio.to_thread(target.read_bytes), content_type)
    except Exception as exc:  # noqa: BLE001
        storage_error = str(exc)[:300]
        logger.warning("[wa_send_media] storage mirror failed: %s", storage_error)
    file_doc = {
        "id": file_id,
        "filename": file.filename or safe_name,
        "stored_name": safe_name,
        "extension": ext or None,
        "content_type": content_type,
        "size": target.stat().st_size,
        "url": public_path,
        "public_url": public_url,
        "uploaded_at": _now(),
        "uploaded_by_id": user.get("id"),
        "uploaded_by_email": user.get("email"),
        "uploaded_from_ip": _client_ip_from_request(request),
        "storage_path": storage_path,
        "storage_error": storage_error,
    }
    try:
        await db.files.insert_one(file_doc.copy())
    except Exception:
        pass

    # Send to WhatsApp Cloud API
    result = await _wa_send_media(
        real_to,
        kind,
        public_url=public_url,
        caption=caption,
        filename=file.filename,
        reply_to_message_id=reply_to_message_id,  # Iter37h
    )

    # Iter35n — Compute reply-time for the most recent unanswered inbound
    reply_window = None
    if result.get("ok"):
        try:
            reply_window = await _wa_compute_reply_window(
                visible_scope, contact_id=contact_id, phone_digits=digits_only,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("WA reply-window calc failed (media): %s", exc)

    # Log into whatsapp_messages
    client_scope = (user.get("client_id") or user.get("id"))
    log = {
        "id": _uuid(),
        "client_id": client_scope,
        "direction": "outbound",
        "sender_id": user["id"],
        "sender_label": user.get("full_name") or user.get("email"),
        "to": real_to,
        "phone_digits": digits_only,
        "template_name": None,
        "language_code": None,
        "message_type": kind,
        "body": caption or f"[{kind} envoyé]",
        "media_id": file_id,
        "media_url": public_path,
        "media_mime_type": content_type,
        "media_filename": file.filename,
        "media_size_bytes": file_doc["size"],
        "media_kind": kind,
        "media_caption": caption,
        "contact_id": contact_id,
        "tracked_user_id": tracked_user_id,
        "ok": result["ok"],
        "status": result["status"],
        "message_id": result["message_id"],
        "error": result.get("error"),
        "wa_status": "sent" if result["ok"] else "failed",
        "sent_at": _now() if result["ok"] else None,
        "failed_at": None if result["ok"] else _now(),
        "created_at": _now(),
    }
    if reply_window:
        log["reply_to_inbound_id"] = reply_window["inbound_id"]
        log["reply_to_inbound_received_at"] = reply_window["inbound_received_at"]
        log["reply_seconds"] = reply_window["reply_seconds"]
    # Iter37h — Persist quote context for the chat thread UI
    if reply_to_message_id:
        log["reply_to_message_id"] = reply_to_message_id
    try:
        await db.whatsapp_messages.insert_one(log.copy())
    except Exception:
        pass
    log.pop("_id", None)
    return {
        "ok": result["ok"],
        "message_id": result["message_id"],
        "error": result.get("error"),
        "http_status": result["status"],
        "media_url": public_path,
        "kind": kind,
    }


# =====================================================================
# Iter35m — POST /me/whatsapp/messages/{msg_id}/save-to-library
# Re-use an inbound media (typically a photo received from a contact) by
# registering it in the shared media library. Does NOT re-upload the binary
# — it just creates a media_library entry pointing at the existing files row.
# =====================================================================
class SaveToLibraryRequest(BaseModel):
    label: Optional[str] = None


# Iter35m — POST /me/whatsapp/messages/{msg_id}/save-to-library
@api.post("/me/whatsapp/messages/{msg_id}/save-to-library", tags=["Portail Client"])
async def me_whatsapp_save_to_library(
    msg_id: str,
    payload: SaveToLibraryRequest = Body(default=None),
    user: dict = Depends(get_current_user),
):
    """Register an inbound WhatsApp media in the shared client media library."""
    allowed = (
        user.get("role") in ("client", "admin", "demo")
        or _is_elevated_creator(user)
        or _is_tracked_user(user)
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Rôle non autorisé")

    visible_scope = await _resolve_visible_client_ids(user)
    msg = await db.whatsapp_messages.find_one(
        {"id": msg_id, "client_id": {"$in": visible_scope}}, {"_id": 0},
    )
    if not msg:
        raise HTTPException(status_code=404, detail="Message WhatsApp introuvable")
    if msg.get("direction") != "inbound":
        raise HTTPException(status_code=400, detail="Seuls les messages reçus peuvent être réutilisés")
    file_id = msg.get("media_id")
    media_url = msg.get("media_url")
    media_mime = msg.get("media_mime_type")
    if not file_id or not media_url:
        raise HTTPException(status_code=400, detail="Ce message ne contient pas de média téléchargé")

    # The underlying file must still exist in the files collection
    file_row = await db.files.find_one({"id": file_id}, {"_id": 0})
    if not file_row:
        raise HTTPException(status_code=410, detail="Fichier source introuvable (peut-être expiré)")

    # Idempotence: if a library entry for this file already exists in the same
    # client scope, return it instead of duplicating.
    client_scope = user.get("client_id") or user["id"]
    existing = await db.media_library.find_one(
        {"file_id": file_id, "client_id": client_scope}, {"_id": 0},
    )
    if existing:
        return {"ok": True, "media": existing, "already_existed": True}

    kind = msg.get("media_kind") or _wa_kind_for_mime(media_mime or "")
    # Build the label: user-provided OR contact name OR sender phone
    if payload and (payload.label or "").strip():
        label = payload.label.strip()[:200]
    else:
        contact_label = msg.get("contact_name") or msg.get("from_profile_name") or msg.get("from") or "WhatsApp"
        ts = (msg.get("received_at") or msg.get("created_at") or "")[:10]
        label = f"WA · {contact_label} · {ts}".strip(" ·")[:200]

    media = {
        "id": _uuid(),
        "file_id": file_id,
        "client_id": client_scope,
        "uploaded_by_id": user.get("id"),
        "uploaded_by_label": user.get("full_name") or user.get("email"),
        "label": label,
        "filename": file_row.get("filename") or msg.get("media_filename"),
        "kind": kind,
        "content_type": file_row.get("content_type") or media_mime,
        "extension": file_row.get("extension"),
        "size": file_row.get("size") or msg.get("media_size_bytes"),
        "public_url": file_row.get("public_url") or media_url,
        "source": "whatsapp_inbound",
        "source_message_id": msg_id,
        "created_at": _now(),
    }
    await db.media_library.insert_one(media.copy())
    media.pop("_id", None)
    return {"ok": True, "media": media, "already_existed": False}


# =====================================================================
# Iter35m — GET /me/dashboard/wa-media-summary?days=7|30|90
# Surface a quick overview of inbound WhatsApp media (images/audio/video/PDF)
# received in the trailing window — used by the portal dashboard card.
# =====================================================================
@api.get("/me/dashboard/wa-media-summary", tags=["Portail Client"])
async def me_wa_media_summary(
    days: int = Query(default=7, ge=1, le=365),
    user: dict = Depends(get_current_user),
):
    """Renvoie une synthèse des médias WhatsApp entrants reçus durant les `days` derniers jours.

    Shape:
      {
        days, counts: {image, audio, video, document, total},
        top_contacts: [ {phone_digits, contact_name, count} … ],
        last_items: [ {id, kind, media_url, media_filename, from, contact_name, received_at, voice_note_transcript?} … ],
      }
    """
    visible_scope = await _resolve_visible_client_ids(user)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    base_q: Dict[str, Any] = {
        "client_id": {"$in": visible_scope},
        "direction": "inbound",
        "media_url": {"$exists": True, "$ne": None},
        "$or": [
            {"received_at": {"$gte": since}},
            {"created_at": {"$gte": since}},
        ],
    }

    # Iter34u — anon_communications restriction (own messages only)
    restrictions = await _resolve_content_restrictions(user)
    if restrictions.get("anon_communications"):
        base_q["$and"] = [{"$or": [{"sender_id": user["id"]}, {"owner_id": user["id"]}]}]

    # Counts by kind
    counts = {"image": 0, "audio": 0, "video": 0, "document": 0, "total": 0}
    pipeline_kinds = [
        {"$match": base_q},
        {"$group": {"_id": "$media_kind", "n": {"$sum": 1}}},
    ]
    async for row in db.whatsapp_messages.aggregate(pipeline_kinds):
        kind = row.get("_id") or "document"
        if kind in counts:
            counts[kind] = row["n"]
        else:
            counts["document"] += row["n"]
        counts["total"] += row["n"]

    # Top 5 contacts (by phone_digits)
    pipeline_top = [
        {"$match": base_q},
        {"$group": {
            "_id": "$phone_digits",
            "count": {"$sum": 1},
            "contact_name": {"$last": "$contact_name"},
            "profile_name": {"$last": "$from_profile_name"},
            "from": {"$last": "$from"},
            "contact_id": {"$last": "$contact_id"},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    top_contacts: List[Dict[str, Any]] = []
    # Iter36h — Pre-load the directory once and build a digits → contact map
    # so we match accurately whatever formatting the phone/whatsapp fields use
    # (spaces, +, leading 00, local-only). One pass on a small collection
    # (<200 contacts typically) is cheaper than a regex per sender.
    dir_index: Dict[str, Dict[str, Any]] = {}
    async for c in db.directory_contacts.find(
        {"client_id": {"$in": visible_scope}},
        {"_id": 0, "id": 1, "name": 1, "phone": 1, "whatsapp": 1, "phone_digits": 1, "whatsapp_digits": 1},
    ):
        for raw in (c.get("phone_digits"), c.get("whatsapp_digits"),
                    c.get("phone"), c.get("whatsapp")):
            if not raw:
                continue
            digits = "".join(ch for ch in str(raw) if ch.isdigit())
            if not digits:
                continue
            # Index by the last 8 digits (national core) AND the full digits.
            # Last 8 digits handle international/local variants robustly.
            dir_index.setdefault(digits, c)
            if len(digits) >= 8:
                dir_index.setdefault(digits[-8:], c)

    async for row in db.whatsapp_messages.aggregate(pipeline_top):
        phone_digits = row.get("_id")
        in_directory = False
        directory_contact_id = row.get("contact_id")
        if phone_digits:
            tail8 = phone_digits[-8:] if len(phone_digits) >= 8 else phone_digits
            dir_match = dir_index.get(phone_digits) or dir_index.get(tail8)
            if dir_match:
                in_directory = True
                directory_contact_id = dir_match.get("id") or directory_contact_id
        # Fetch the very last message (any direction) from this number
        last_msg = await db.whatsapp_messages.find_one(
            {"client_id": {"$in": visible_scope}, "phone_digits": phone_digits},
            {"_id": 0, "id": 1, "body": 1, "media_kind": 1, "media_filename": 1, "direction": 1,
             "received_at": 1, "sent_at": 1, "created_at": 1},
            sort=[("created_at", -1)],
        ) or {}
        last_text = last_msg.get("body") or (
            f"[{last_msg.get('media_kind') or 'média'}] {last_msg.get('media_filename') or ''}".strip()
            if last_msg.get("media_kind") else ""
        )
        top_contacts.append({
            "phone_digits": phone_digits,
            "contact_name": row.get("contact_name") or row.get("profile_name") or row.get("from"),
            "count": row["count"],
            "in_directory": in_directory,
            "contact_id": directory_contact_id,
            "last_message_id": last_msg.get("id"),
            "last_message_preview": (last_text or "")[:160],
            "last_message_at": last_msg.get("received_at") or last_msg.get("sent_at") or last_msg.get("created_at"),
            "last_message_direction": last_msg.get("direction"),
        })

    # Last 5 items
    last_items_cursor = db.whatsapp_messages.find(
        base_q,
        {
            "_id": 0, "id": 1, "media_url": 1, "media_kind": 1, "media_mime_type": 1,
            "media_filename": 1, "from": 1, "contact_name": 1, "from_profile_name": 1,
            "received_at": 1, "created_at": 1, "voice_note_transcript": 1, "contact_id": 1,
        },
    ).sort("created_at", -1).limit(5)
    last_items = [doc async for doc in last_items_cursor]

    return {
        "days": days,
        "counts": counts,
        "top_contacts": top_contacts,
        "last_items": last_items,
    }


# =====================================================================
# Iter35n — GET /me/dashboard/wa-reply-stats?days=7|30|90
# Surface the WhatsApp reply-time score for the current user (and the
# team's leaderboard for elevated viewers) so the dashboard can highlight
# "dynamic" responders.
# =====================================================================
@api.get("/me/dashboard/wa-reply-stats", tags=["Portail Client"])
async def me_wa_reply_stats(
    days: int = Query(default=7, ge=1, le=365),
    user: dict = Depends(get_current_user),
):
    """Renvoie les agrégats de temps de réponse WhatsApp par utilisateur sur la fenêtre courante.

    Shape:
      {
        days,
        me: {avg_seconds, median_seconds, replies, fastest_seconds},
        team: [{user_id, label, avg_seconds, replies, fastest_seconds} …]  // elevated only
      }
    """
    visible_scope = await _resolve_visible_client_ids(user)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    base_q: Dict[str, Any] = {
        "client_id": {"$in": visible_scope},
        "direction": "outbound",
        "reply_seconds": {"$exists": True, "$ne": None, "$gt": 0},
        "$or": [
            {"sent_at": {"$gte": since}},
            {"created_at": {"$gte": since}},
        ],
    }

    # ---- Per-user (me) ----
    my_q = {**base_q, "sender_id": user["id"]}
    my_durations: List[int] = []
    async for d in db.whatsapp_messages.find(my_q, {"_id": 0, "reply_seconds": 1}):
        rs = int(d.get("reply_seconds") or 0)
        if rs > 0:
            my_durations.append(rs)
    my_durations.sort()
    me_block = {
        "avg_seconds": int(sum(my_durations) / len(my_durations)) if my_durations else None,
        "median_seconds": my_durations[len(my_durations) // 2] if my_durations else None,
        "replies": len(my_durations),
        "fastest_seconds": my_durations[0] if my_durations else None,
    }

    # ---- Team leaderboard (elevated viewers only) ----
    team: List[Dict[str, Any]] = []
    if _is_elevated_creator(user) or user.get("role") in ("admin", "superviseur"):
        pipeline = [
            {"$match": base_q},
            {"$group": {
                "_id": "$sender_id",
                "label": {"$last": "$sender_label"},
                "avg_seconds": {"$avg": "$reply_seconds"},
                "replies": {"$sum": 1},
                "fastest_seconds": {"$min": "$reply_seconds"},
            }},
            {"$sort": {"avg_seconds": 1}},
            {"$limit": 10},
        ]
        async for row in db.whatsapp_messages.aggregate(pipeline):
            if not row.get("_id"):
                continue
            team.append({
                "user_id": row["_id"],
                "label": row.get("label") or row["_id"][:8],
                "avg_seconds": int(row["avg_seconds"]) if row.get("avg_seconds") is not None else None,
                "replies": row.get("replies") or 0,
                "fastest_seconds": int(row["fastest_seconds"]) if row.get("fastest_seconds") is not None else None,
            })

    return {"days": days, "me": me_block, "team": team}


# 2026-02 fork — Delete/recall an outbound WhatsApp message the sender changed
# their mind about. WhatsApp Cloud API does NOT support "delete for everyone",
# so this is a SOFT-DELETE : the message stays on the recipient's phone but is
# marked `is_recalled=True` in our DB, hidden from our conversation view, and
# a "Message rappelé" placeholder appears in its slot. The endpoint refuses
# hard-recalls when the message has already been read (status='read').
_RECALL_MAX_AGE_MIN = 15


@api.patch("/me/whatsapp/messages/{message_id}/recall", tags=["Portail Client"])
async def me_whatsapp_recall_message(
    message_id: str,
    user: dict = Depends(get_current_user),
):
    """Soft-recall an outbound WA message.

    Business rules:
      - Must be outbound (only the sender can recall).
      - Must be in caller's visible scope.
      - Refuses if `wa_status == 'read'` (destinataire l'a déjà lu).
      - Refuses if message is older than 15 minutes (fenêtre éditeur).
      - Marks doc with `is_recalled=True`, `recalled_at=now`, `recalled_by_id`.
    """
    visible_scope = await _resolve_visible_client_ids(user)
    msg = await db.whatsapp_messages.find_one(
        {"id": message_id, "client_id": {"$in": visible_scope}},
        {"_id": 0},
    )
    if not msg:
        raise HTTPException(status_code=404, detail="Message introuvable ou hors de votre scope")
    if (msg.get("direction") or "").lower() != "outbound":
        raise HTTPException(status_code=400, detail="Seuls les messages sortants peuvent être supprimés")
    if msg.get("is_recalled"):
        return {"ok": True, "already_recalled": True}
    wa_status = (msg.get("wa_status") or "").lower()
    if wa_status == "read":
        raise HTTPException(
            status_code=409,
            detail="Impossible : le destinataire a déjà lu ce message (WhatsApp ne permet pas d'annuler après lecture).",
        )
    # Age check — accept `sent_at` if set, else `created_at`, else now
    ref_iso = msg.get("sent_at") or msg.get("created_at") or _now()
    try:
        ref_dt = datetime.fromisoformat(ref_iso)
        if ref_dt.tzinfo is None:
            ref_dt = ref_dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        ref_dt = datetime.now(timezone.utc)
    age_min = (datetime.now(timezone.utc) - ref_dt).total_seconds() / 60
    # Failed messages : always recallable (no delivery ever occurred)
    if wa_status != "failed" and age_min > _RECALL_MAX_AGE_MIN:
        raise HTTPException(
            status_code=409,
            detail=f"Impossible : au-delà de {_RECALL_MAX_AGE_MIN} min après l'envoi, le rappel n'est plus autorisé (le destinataire l'a très probablement reçu).",
        )
    await db.whatsapp_messages.update_one(
        {"id": message_id},
        {"$set": {
            "is_recalled": True,
            "recalled_at": _now(),
            "recalled_by_id": user.get("id"),
            "recalled_by_email": user.get("email"),
        }},
    )
    # Return the recall meta + a warning flag so the UI can display the
    # "Meta ne supprime pas chez le destinataire" note only when relevant.
    delivered_before_recall = wa_status in ("delivered", "sent")
    return {
        "ok": True,
        "message_id": message_id,
        "recalled_at": _now(),
        "meta_delete_supported": False,
        "delivered_before_recall": delivered_before_recall,
        "warning": "Le message reste dans WhatsApp du destinataire (limitation Meta Cloud API). Il est simplement retiré de votre vue CRM." if delivered_before_recall else None,
    }


# ---------- Unread inbound counters + mark-read ----------
# Lot 23 — rapprochement message ↔ contact par les 8 derniers chiffres du
# numéro : un contact enregistré sans indicatif (« 70 12 34 56 ») retrouve
# les messages reçus de « 22670123456 ».
WA_PHONE_SUFFIX_LEN = 8


def _phone_suffix(raw: Optional[str]) -> str:
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    return digits[-WA_PHONE_SUFFIX_LEN:] if len(digits) >= WA_PHONE_SUFFIX_LEN else digits


def _contact_phone_clauses(contact: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Critères Mongo « message de ce contact » : son id, ou son numéro
    (WhatsApp ou téléphone) reconnu sur ses 8 derniers chiffres."""
    clauses: List[Dict[str, Any]] = [{"contact_id": contact.get("id")}]
    seen = set()
    for raw in (contact.get("whatsapp") or "", contact.get("phone") or ""):
        suffix = _phone_suffix(raw)
        if len(suffix) >= 6 and suffix not in seen:
            seen.add(suffix)
            clauses.append({"phone_digits": {"$regex": f"{re.escape(suffix)}$"}})
    return clauses


# Lot 24 — un message non lu de plus de 30 jours n'est plus compté comme
# « nouveau » : l'historique jamais marqué comme lu (avant le lot 23, les
# messages reçus sans contact rattaché ne pouvaient pas l'être) ne gonfle plus
# le badge. Il reste marqué comme non lu en base, et « Tout marquer comme lu »
# le traite aussi.
WA_UNREAD_MAX_AGE_DAYS = 30


def _phone_suffix_regex(raw: Optional[str]) -> Optional[str]:
    """Lot 24 — regex Mongo « le numéro se termine par ces 8 chiffres », quelle
    que soit la mise en forme stockée (« +226 70 11 11 11 », « 70111111 »…)."""
    suffix = _phone_suffix(raw)
    if len(suffix) < 6:
        return None
    return r"\D*".join(re.escape(ch) for ch in suffix) + r"\D*$"


async def _find_contact_by_phone(scope_ids: Optional[List[str]], raw_phone: Optional[str]) -> Optional[Dict[str, Any]]:
    """Lot 24 — contact existant ayant ce numéro (WhatsApp, téléphone ou
    phone_digits, reconnu sur ses 8 derniers chiffres), le plus ancien d'abord.
    `scope_ids=None` : tous les tenants."""
    rx = _phone_suffix_regex(raw_phone)
    if not rx:
        return None
    q: Dict[str, Any] = {"$or": [{"whatsapp": {"$regex": rx}}, {"phone": {"$regex": rx}}, {"phone_digits": {"$regex": rx}}]}
    if scope_ids is not None:
        q["client_id"] = {"$in": scope_ids}
    return await db.directory_contacts.find_one(q, {"_id": 0}, sort=[("created_at", 1)])


async def _wa_visible_contact_index(user: dict) -> Tuple[List[str], set, Dict[str, str]]:
    """Périmètre visible, ids des contacts visibles et index « 8 derniers
    chiffres du numéro → id du contact » (rattachement des messages)."""
    visible_scope = await _resolve_visible_client_ids(user)
    contacts = await db.directory_contacts.find(
        {"client_id": {"$in": visible_scope}},
        {"_id": 0, "id": 1, "whatsapp": 1, "phone": 1, "client_id": 1, "wa_ligne": 1},
    ).to_list(5000)
    # Lot 59 — seuls les contacts des lignes WhatsApp autorisées à l'utilisateur
    from routes.numeros_wa import VisibiliteLignes
    vis = await VisibiliteLignes.charger(db, user)
    if vis.restreint:
        contacts = [c for c in contacts if vis.contact_visible(c)]
    ids = {c["id"] for c in contacts if c.get("id")}
    by_suffix: Dict[str, str] = {}
    for c in contacts:
        for raw in (c.get("whatsapp"), c.get("phone")):
            suffix = _phone_suffix(raw)
            if len(suffix) >= 6:
                by_suffix.setdefault(suffix, c["id"])
    return visible_scope, ids, by_suffix


def _wa_attribute(ids: set, by_suffix: Dict[str, str], contact_id: Optional[str], phone: Optional[str]) -> Optional[str]:
    """Contact visible auquel rattacher un message (son contact_id, sinon son numéro), ou None."""
    return contact_id if contact_id in ids else by_suffix.get(_phone_suffix(phone))


async def _wa_unread_summary(user: dict) -> Dict[str, Any]:
    """Non-lus WhatsApp du Centre de Messagerie — SOURCE UNIQUE pour la
    pastille de chaque contact, le total du badge de la sidebar et la cloche.

    - périmètre : _resolve_visible_client_ids (celui de /me/contacts et de
      mark-read), pour TOUS les rôles, admin compris ;
    - un message sans contact_id est rattaché au contact dont le numéro
      correspond (8 derniers chiffres) ;
    - seuls comptent les messages rattachés à un contact VISIBLE (donc
      qu'on peut ouvrir et marquer comme lus) ; les autres (expéditeurs
      inconnus) sont renvoyés à part dans `unknown`, sans gonfler le total ;
    - Lot 24 : seuls comptent les messages des 30 derniers jours ; les non-lus
      plus anciens sont renvoyés à part dans `older` (pour information)."""
    visible_scope, ids, by_suffix = await _wa_visible_contact_index(user)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=WA_UNREAD_MAX_AGE_DAYS)).isoformat()
    by_contact: Dict[str, int] = {}
    unknown = 0
    older = 0
    base = {"direction": "inbound", "read_by_us_at": None, "client_id": {"$in": visible_scope}}
    group = {"$group": {"_id": {"c": "$contact_id", "p": "$phone_digits"}, "n": {"$sum": 1}}}
    async for row in db.whatsapp_messages.aggregate([{"$match": {**base, "created_at": {"$gte": cutoff}}}, group]):
        key = row.get("_id") or {}
        n = int(row.get("n") or 0)
        cid = _wa_attribute(ids, by_suffix, key.get("c"), key.get("p"))
        if cid:
            by_contact[cid] = by_contact.get(cid, 0) + n
        else:
            unknown += n
    async for row in db.whatsapp_messages.aggregate([{"$match": {**base, "created_at": {"$lt": cutoff}}}, group]):
        key = row.get("_id") or {}
        if _wa_attribute(ids, by_suffix, key.get("c"), key.get("p")):
            older += int(row.get("n") or 0)
    return {"total": sum(by_contact.values()), "by_contact": by_contact, "unknown": unknown,
            "older": older, "max_age_days": WA_UNREAD_MAX_AGE_DAYS}


@api.post("/me/whatsapp/mark-all-read", tags=["Portail Client"])
async def me_whatsapp_mark_all_read(user: dict = Depends(get_current_user)):
    """Lot 24 — « Tout marquer comme lu » dans le Centre de Messagerie : tous
    les messages WhatsApp non lus rattachés à un contact visible, quel que soit
    leur âge. Les messages d'expéditeurs inconnus ne sont pas touchés (ils se
    traitent dans l'Inbox unifiée)."""
    visible_scope, ids, by_suffix = await _wa_visible_contact_index(user)
    to_mark: List[str] = []
    async for m in db.whatsapp_messages.find(
        {"direction": "inbound", "read_by_us_at": None, "client_id": {"$in": visible_scope}},
        {"_id": 0, "id": 1, "contact_id": 1, "phone_digits": 1},
    ):
        if m.get("id") and _wa_attribute(ids, by_suffix, m.get("contact_id"), m.get("phone_digits")):
            to_mark.append(m["id"])
    updated = 0
    now = _now()
    for i in range(0, len(to_mark), 1000):
        res = await db.whatsapp_messages.update_many(
            {"id": {"$in": to_mark[i:i + 1000]}, "read_by_us_at": None},
            {"$set": {"read_by_us_at": now, "read_by_us_id": user["id"]}},
        )
        updated += int(getattr(res, "modified_count", 0) or 0)
    return {"ok": True, "updated": updated}


@api.get("/me/whatsapp/unread", tags=["Portail Client"])
async def me_whatsapp_unread(user: dict = Depends(get_current_user)):
    """Compteurs de non-lus par contact + total (pastilles, cloche, badge).

    Lot 23 — calcul partagé avec le badge de la sidebar (_wa_unread_summary) :
    les deux nombres sont désormais toujours identiques. `unknown` = messages
    d'expéditeurs absents du carnet (visibles dans l'Inbox unifiée)."""
    return await _wa_unread_summary(user)


@api.post("/me/contacts/{cid}/messages/mark-read", tags=["Portail Client"])
async def me_contact_messages_mark_read(cid: str, user: dict = Depends(get_current_user)):
    """Marque tous les messages WA entrants d'un contact donné comme lus (fixe read_by_us_at)."""
    # Iter34p — Use the visible-scope resolution so we find the contact even
    # when its client_id is one of the historical/peer values (rabo.f-style
    # data is now legitimately accessed via the company bridge).
    visible_scope = await _resolve_visible_client_ids(user)
    contact = await db.directory_contacts.find_one(
        {"id": cid, "client_id": {"$in": visible_scope}}, {"_id": 0},
    )
    # Lot 59 — contact d'une ligne WhatsApp non autorisée : invisible pour cet utilisateur
    from routes.numeros_wa import telephone_visible
    if contact and not await telephone_visible(db, user, contact.get("whatsapp") or contact.get("phone"), contact):
        contact = None
    if not contact:
        raise HTTPException(status_code=404, detail="Contact introuvable")
    # Lot 23 — mêmes critères que le comptage (id du contact OU 8 derniers chiffres du numéro).
    or_clauses = _contact_phone_clauses(contact)
    res = await db.whatsapp_messages.update_many(
        {"client_id": {"$in": visible_scope}, "direction": "inbound", "read_by_us_at": None, "$or": or_clauses},
        {"$set": {"read_by_us_at": _now(), "read_by_us_id": user["id"]}},
    )
    return {"ok": True, "updated": int(getattr(res, "modified_count", 0) or 0)}
