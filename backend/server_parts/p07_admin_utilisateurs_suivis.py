# server_parts/p07_admin_utilisateurs_suivis.py — Utilisateurs suivis, transfert, messages reçus, liste noire IP, logo du portail.
# Morceau de l'ancien server.py (lignes 10121 à 10623), recopié à l'identique.
# Exécuté par server.py via _inclure_partie() dans SON espace de noms : les
# noms utilisés ici (db, api, get_current_user, helpers…) sont ceux de server.py.
# Ne pas importer ce fichier directement.

# ====================================================================
# ADMIN - Tracked users (sub-users of clients)
# ====================================================================
@api.get("/admin/tracked-users", tags=["Admin"])
async def admin_tracked(client_id: Optional[str] = None, _: dict = Depends(get_current_admin)):
    q = {"client_id": client_id} if client_id else {}
    items = await db.tracked_users.find(q, {"_id": 0}).to_list(5000)
    return items


# S-iter39d (fix #1) — Public-ish helper for any authed user in the tenant.
# Returns the full list of people in the same tenant scope (admin/sup/moderation
# users + tracked users) so the PV editor dropdowns can be populated without
# requiring admin role. Includes a stable `value` key (user id) and a
# `label` ready for display.
@api.get("/me/tenant-users", tags=["Portail Client"])
async def me_tenant_users(user: dict = Depends(get_current_user)):
    scope_ids = await _resolve_visible_client_ids(user)
    if not scope_ids:
        return {"items": []}
    # Canonical tenant id = the broadest scope (admin/sup/client owner)
    # parent_client_id of the current user, or the user's own id.
    tenant_id = user.get("parent_client_id") or user.get("client_id") or user.get("id")
    rows: List[Dict[str, Any]] = []
    seen_ids: set = set()
    # Canonical users (admin/sup/moderateur/client) whose id == tenant_id
    # OR who have parent_client_id == tenant_id
    canonical = await db.users.find(
        {"$or": [{"id": tenant_id}, {"parent_client_id": tenant_id}, {"id": {"$in": scope_ids}}]},
        {"_id": 0, "id": 1, "full_name": 1, "email": 1, "role": 1, "company": 1, "tracked_role": 1},
    ).to_list(2000)
    for u in canonical:
        if u["id"] in seen_ids:
            continue
        seen_ids.add(u["id"])
        rows.append({
            "value": u["id"],
            "label": u.get("full_name") or u.get("email") or "—",
            "email": u.get("email"),
            "role": u.get("tracked_role") or u.get("role") or "—",
            "kind": "user",
        })
    # Tracked users in this tenant
    tracked = await db.tracked_users.find(
        {"client_id": {"$in": scope_ids}},
        {"_id": 0, "id": 1, "name": 1, "full_name": 1, "email": 1, "role": 1, "user_id": 1},
    ).to_list(5000)
    for t in tracked:
        # Skip if already in the canonical users list (their user_id was matched above)
        if t.get("user_id") and t.get("user_id") in seen_ids:
            continue
        seen_ids.add(t["id"])
        rows.append({
            "value": t.get("user_id") or t["id"],
            "label": t.get("full_name") or t.get("name") or t.get("email") or "—",
            "email": t.get("email"),
            "role": t.get("role") or "—",
            "kind": "tracked",
        })
    # Sort by label, FR locale-aware (simple .lower() fallback)
    rows.sort(key=lambda r: (r.get("label") or "").lower())
    return {"items": rows}


@api.post("/admin/tracked-users", tags=["Admin"])
async def admin_create_tracked(payload: TrackedUserCreate, _: dict = Depends(get_current_admin)):
    if payload.role and payload.role not in TRACKED_USER_ROLES:
        raise HTTPException(status_code=400, detail=f"Rôle invalide. Valeurs: {', '.join(TRACKED_USER_ROLES)}")
    if payload.email and not is_valid_email_syntax(str(payload.email)):
        raise HTTPException(status_code=400, detail="Email invalide (syntaxe)")
    from routes.tracked_user_groups import AUTO_GROUP_ROLES
    if payload.role in AUTO_GROUP_ROLES and not (payload.whatsapp_number or payload.phone):
        raise HTTPException(
            status_code=400,
            detail=f"Numéro WhatsApp obligatoire pour le rôle {payload.role} (nécessaire pour les envois groupés).",
        )
    client = await db.users.find_one({"id": payload.client_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    doc = {"id": _uuid(), **payload.model_dump(), "created_at": _now(), "updated_at": _now()}
    await db.tracked_users.insert_one(doc.copy())
    # Rattachement auto au groupe de contacts "Médecin"/"Pharmacien" (demande explicite).
    from routes.tracked_user_groups import sync_tracked_role_group
    await sync_tracked_role_group(db, doc)
    doc.pop("_id", None)
    return doc


@api.put("/admin/tracked-users/{tu_id}", tags=["Admin"])
async def admin_update_tracked(tu_id: str, payload: TrackedUserUpdate, _: dict = Depends(get_current_admin)):
    # 2026-02 fork (P4) — Visibility overrides must be settable back to null
    # (default). We keep them in `update` even when the value is None so admin
    # can reset the toggle via the "Défaut du rôle" option.
    raw = payload.model_dump()
    P4_RESETTABLE = {"show_dashboard", "show_welcome_modal", "show_messaging_notifs"}
    update = {k: v for k, v in raw.items() if v is not None or k in P4_RESETTABLE}
    if "role" in update and update["role"] not in TRACKED_USER_ROLES:
        raise HTTPException(status_code=400, detail=f"Rôle invalide. Valeurs: {', '.join(TRACKED_USER_ROLES)}")
    if "email" in update and update["email"] and not is_valid_email_syntax(str(update["email"])):
        raise HTTPException(status_code=400, detail="Email invalide (syntaxe)")
    from routes.tracked_user_groups import AUTO_GROUP_ROLES
    existing_before = await db.tracked_users.find_one({"id": tu_id}, {"_id": 0})
    final_role = update.get("role", (existing_before or {}).get("role"))
    final_whatsapp = update.get("whatsapp_number", (existing_before or {}).get("whatsapp_number"))
    final_phone = update.get("phone", (existing_before or {}).get("phone"))
    if final_role in AUTO_GROUP_ROLES and not (final_whatsapp or final_phone):
        raise HTTPException(
            status_code=400,
            detail=f"Numéro WhatsApp obligatoire pour le rôle {final_role} (nécessaire pour les envois groupés).",
        )
    update["updated_at"] = _now()
    await db.tracked_users.update_one({"id": tu_id}, {"$set": update})
    # Propagate role/name/email/status changes to the bridged users row, if any
    tu_doc = await db.tracked_users.find_one({"id": tu_id}, {"_id": 0})
    if tu_doc and tu_doc.get("user_account_id"):
        bridge_update = {"updated_at": _now()}
        if "role" in update:
            bridge_update["tracked_role"] = update["role"]
        if "name" in update and update["name"]:
            bridge_update["full_name"] = update["name"]
        if "email" in update and update["email"]:
            bridge_update["email"] = str(update["email"]).lower()
        if "status" in update and update["status"]:
            bridge_update["account_status"] = "active" if update["status"] == "active" else "inactive"
        # 2026-02 — Mirror translator fields & force_logout_on_idle to the
        # bridged user account so the /me endpoint exposes them at login.
        # 2026-02 fork (P4) — Mirror per-user visibility overrides too.
        for f in (
            "translator_languages",
            "translator_rate_per_word",
            "force_logout_on_idle",
            "show_dashboard",
            "show_welcome_modal",
            "show_messaging_notifs",
            "wa_lignes_autorisees",   # Lot 59 — lignes WhatsApp visibles dans le Centre de messagerie
        ):
            if f in update:
                bridge_update[f] = update[f]
        await db.users.update_one({"id": tu_doc["user_account_id"]}, {"$set": bridge_update})
    # Rattachement auto au groupe de contacts "Médecin"/"Pharmacien" (demande explicite) —
    # aussi utile quand le rôle change APRÈS création (ex. passage à Pharmacien).
    if tu_doc:
        from routes.tracked_user_groups import sync_tracked_role_group
        await sync_tracked_role_group(db, tu_doc)
    return {"ok": True}


@api.delete("/admin/tracked-users/{tu_id}", tags=["Admin"])
async def admin_delete_tracked(tu_id: str, _: dict = Depends(get_current_admin)):
    tu = await db.tracked_users.find_one({"id": tu_id}, {"_id": 0})
    await db.tracked_users.delete_one({"id": tu_id})
    # Also remove the bridged users row (if any) so the email can no longer log in
    if tu and tu.get("user_account_id"):
        await db.users.delete_one({"id": tu["user_account_id"]})
    return {"ok": True}


# ============================================================
# Iter35g — Bulk transfer of tracked users to another client.
# Admin selects a list of tracked-user IDs and a target client_id; we
# update both `tracked_users.client_id` AND the bridged
# `users.parent_client_id` + `users.client_id` so the next login picks up
# the new scope. Returns a per-row summary so the UI can show which rows
# moved (and which were skipped because already there or unknown).
# ============================================================
class BulkTransferTrackedRequest(BaseModel):
    tracked_user_ids: List[str]
    target_client_id: str


@api.post("/admin/tracked-users/bulk-transfer", tags=["Admin"])
async def admin_bulk_transfer_tracked(
    payload: BulkTransferTrackedRequest,
    admin_user: dict = Depends(get_current_admin),
):
    if not payload.tracked_user_ids:
        raise HTTPException(status_code=400, detail="Aucun utilisateur sélectionné")
    if len(payload.tracked_user_ids) > 200:
        raise HTTPException(status_code=400, detail="Maximum 200 utilisateurs par transfert")
    target_id = (payload.target_client_id or "").strip()
    if not target_id:
        raise HTTPException(status_code=400, detail="Client cible requis")
    target = await db.users.find_one(
        {"id": target_id, "role": {"$in": ["client", "superviseur"]}},
        {"_id": 0, "id": 1, "email": 1, "full_name": 1, "company": 1},
    )
    if not target:
        raise HTTPException(status_code=404, detail="Client cible introuvable")

    moved: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    now_iso = _now()
    for tu_id in payload.tracked_user_ids:
        tu = await db.tracked_users.find_one({"id": tu_id}, {"_id": 0})
        if not tu:
            skipped.append({"id": tu_id, "reason": "introuvable"})
            continue
        old_client_id = tu.get("client_id")
        if old_client_id == target_id:
            skipped.append({"id": tu_id, "name": tu.get("name") or tu.get("email"), "reason": "déjà sur ce client"})
            continue
        # Update tracked_users row
        await db.tracked_users.update_one(
            {"id": tu_id},
            {"$set": {
                "client_id": target_id,
                "previous_client_id": old_client_id,
                "transferred_at": now_iso,
                "transferred_by_id": admin_user.get("id"),
                "transferred_by_label": admin_user.get("full_name") or admin_user.get("email"),
                "updated_at": now_iso,
            }},
        )
        # Update bridged users row if any (so login next time picks up the new scope)
        if tu.get("user_account_id"):
            await db.users.update_one(
                {"id": tu["user_account_id"]},
                {"$set": {
                    "client_id": target_id,
                    "parent_client_id": target_id,
                    "client_id_legacy": old_client_id,
                    "parent_client_id_legacy": old_client_id,
                    "updated_at": now_iso,
                }},
            )
        moved.append({
            "id": tu_id,
            "name": tu.get("name") or tu.get("email"),
            "from": old_client_id,
            "to": target_id,
        })
    # Audit log
    try:
        await db.tracked_user_transfers.insert_one({
            "id": _uuid(),
            "created_at": now_iso,
            "actor_id": admin_user.get("id"),
            "actor_email": admin_user.get("email"),
            "target_client_id": target_id,
            "target_company": target.get("company"),
            "moved_count": len(moved),
            "skipped_count": len(skipped),
            "moved": moved,
            "skipped": skipped,
        })
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "target": {"id": target_id, "company": target.get("company"), "email": target.get("email")},
        "moved": moved,
        "skipped": skipped,
        "moved_count": len(moved),
        "skipped_count": len(skipped),
    }


@api.post("/admin/tracked-users/{tu_id}/set-password", tags=["Admin"])
async def admin_set_tracked_password(
    tu_id: str,
    payload: TrackedUserSetPassword,
    _: dict = Depends(get_current_admin),
):
    """Provisionne (ou réinitialise) un identifiant pour un utilisateur suivi.

    Creates/updates a row in `users` (role=client, account_status=active) bridged via
    `tracked_user_id`. The tracked user can then log in with their email + this password
    through the standard /auth/login → OTP flow.
    """
    if not payload.password or len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Mot de passe trop court (min 8 caractères)")
    tu = await db.tracked_users.find_one({"id": tu_id}, {"_id": 0})
    if not tu:
        raise HTTPException(status_code=404, detail="Utilisateur suivi introuvable")
    email = (tu.get("email") or "").strip().lower()
    if not email or not is_valid_email_syntax(email):
        raise HTTPException(status_code=400, detail="L'utilisateur suivi doit avoir un email valide pour se connecter")

    # Make sure email is not already used by another (non-bridged) account
    other = await db.users.find_one({"email": email}, {"_id": 0})
    if other and other.get("tracked_user_id") and other.get("tracked_user_id") != tu_id:
        raise HTTPException(status_code=409, detail="Email déjà associé à un autre utilisateur suivi")
    if other and not other.get("tracked_user_id"):
        raise HTTPException(status_code=409, detail="Email déjà utilisé par un compte client/admin existant")

    # Resolve parent client to inherit company/logo
    parent = await db.users.find_one({"id": tu.get("client_id")}, {"_id": 0}) or {}
    pwd_hash = hash_password(payload.password)

    if other:
        # Update existing bridged users row
        await db.users.update_one(
            {"id": other["id"]},
            {"$set": {
                "password_hash": pwd_hash,
                "full_name": tu.get("name") or other.get("full_name"),
                "phone": tu.get("phone") or other.get("phone"),
                "company": parent.get("company") or other.get("company"),
                "logo_url": parent.get("logo_url"),
                "tracked_user_id": tu_id,
                "tracked_role": tu.get("role"),
                "parent_client_id": tu.get("client_id"),
                # Mirror the parent client id on the legacy `client_id` field so
                # every endpoint that resolves scope via `user.client_id or
                # user.id` (50+ call sites) correctly inherits the parent's
                # feature flags + RGPD toggles + shared contacts.
                "client_id": tu.get("client_id"),
                # 2026-02 fork (P4) — Mirror per-user visibility overrides so
                # /me exposes them without needing the tracked_users lookup.
                "show_dashboard": tu.get("show_dashboard"),
                "show_welcome_modal": tu.get("show_welcome_modal"),
                "show_messaging_notifs": tu.get("show_messaging_notifs"),
                "wa_lignes_autorisees": tu.get("wa_lignes_autorisees"),   # Lot 59
                "account_status": "active",
                "updated_at": _now(),
            }},
        )
        user_id = other["id"]
    else:
        user_id = _uuid()
        await db.users.insert_one({
            "id": user_id,
            "email": email,
            "password_hash": pwd_hash,
            "full_name": tu.get("name") or email.split("@")[0],
            "role": "client",
            "phone": tu.get("phone"),
            "company": parent.get("company"),
            "logo_url": parent.get("logo_url"),
            "account_status": "active",
            "tracked_user_id": tu_id,
            "tracked_role": tu.get("role"),
            "parent_client_id": tu.get("client_id"),
            # Mirror the parent client id (see comment above).
            "client_id": tu.get("client_id"),
            # 2026-02 fork (P4) — Mirror per-user visibility overrides
            "show_dashboard": tu.get("show_dashboard"),
            "show_welcome_modal": tu.get("show_welcome_modal"),
            "show_messaging_notifs": tu.get("show_messaging_notifs"),
            "wa_lignes_autorisees": tu.get("wa_lignes_autorisees"),   # Lot 59
            "created_at": _now(),
            "updated_at": _now(),
        })

    await db.tracked_users.update_one(
        {"id": tu_id},
        {"$set": {
            "user_account_id": user_id,
            "has_password": True,
            "updated_at": _now(),
        }},
    )
    return {"ok": True, "user_id": user_id, "email": email}


@api.post("/admin/tracked-users/{tu_id}/revoke-password", tags=["Admin"])
async def admin_revoke_tracked_password(tu_id: str, _: dict = Depends(get_current_admin)):
    tu = await db.tracked_users.find_one({"id": tu_id}, {"_id": 0})
    if not tu:
        raise HTTPException(status_code=404, detail="Utilisateur suivi introuvable")
    if tu.get("user_account_id"):
        await db.users.delete_one({"id": tu["user_account_id"]})
    await db.tracked_users.update_one(
        {"id": tu_id},
        {"$set": {"user_account_id": None, "has_password": False, "updated_at": _now()}},
    )
    return {"ok": True}


# ====================================================================
# ADMIN - Contacts inbox
# ====================================================================
@api.get("/admin/contacts", tags=["Admin"])
async def admin_contacts(_: dict = Depends(get_current_admin)):
    items = await db.contacts.find({}, {"_id": 0}).to_list(5000)
    return sorted(items, key=lambda x: x["created_at"], reverse=True)


@api.post("/admin/contacts/{contact_id}/save-as-tracked-user", tags=["Admin"])
async def admin_save_contact_as_tracked(
    contact_id: str,
    payload: SaveContactAsTrackedUser,
    _: dict = Depends(get_current_admin),
):
    contact = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    if not contact:
        raise HTTPException(status_code=404, detail="Message introuvable")

    email = (contact.get("email") or "").strip()
    if not is_valid_email_syntax(email):
        raise HTTPException(status_code=400, detail="Email du message invalide (syntaxe)")

    if payload.role not in TRACKED_USER_ROLES:
        raise HTTPException(status_code=400, detail=f"Rôle invalide. Valeurs: {', '.join(TRACKED_USER_ROLES)}")

    client = await db.users.find_one({"id": payload.client_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")

    # Avoid duplicate (same email + same client)
    existing = await db.tracked_users.find_one(
        {"email": email, "client_id": payload.client_id}, {"_id": 0}
    )
    if existing:
        raise HTTPException(status_code=409, detail="Cet utilisateur est déjà enregistré pour ce client")

    doc = {
        "id": _uuid(),
        "client_id": payload.client_id,
        "name": contact.get("name") or email,
        "email": email,
        "role": payload.role,
        "department": payload.department,
        "phone": contact.get("phone"),
        "company": contact.get("company"),
        "status": "active",
        "source_contact_id": contact_id,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.tracked_users.insert_one(doc.copy())
    await db.contacts.update_one(
        {"id": contact_id},
        {"$set": {"saved_as_tracked_user_id": doc["id"], "updated_at": _now()}},
    )
    doc.pop("_id", None)
    return doc


@api.get("/admin/meta/tracked-roles", tags=["Admin"])
async def admin_tracked_roles(_: dict = Depends(get_current_admin)):
    return {"roles": TRACKED_USER_ROLES}


# ====================================================================
# IP BLACKLIST (admin)
# ====================================================================
@api.get("/admin/blacklisted-ips", tags=["Admin"])
async def admin_list_blacklist(_: dict = Depends(get_current_admin)):
    items = await db.blacklisted_ips.find({}, {"_id": 0}).to_list(5000)
    return sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)


@api.post("/admin/blacklisted-ips", tags=["Admin"])
async def admin_add_blacklist(payload: BlacklistedIPCreate, request: Request, _: dict = Depends(get_current_admin)):
    cidr = (payload.cidr or "").strip()
    if not cidr:
        raise HTTPException(status_code=400, detail="IP/CIDR requis")
    try:
        ipaddress.ip_network(cidr if "/" in cidr else (f"{cidr}/32" if "." in cidr else f"{cidr}/128"), strict=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"IP/CIDR invalide : {exc}") from exc
    # Lot 25 — Anti-verrouillage : on refuse une entrée qui contient l'adresse IP
    # de la personne qui fait la demande (sinon tout /api lui serait refusé).
    current_ip = _client_ip_from_request(request)
    if current_ip and _ip_in_cidr(current_ip, cidr):
        raise HTTPException(
            status_code=400,
            detail=f"Impossible de bloquer {cidr} : cette entrée contient votre propre adresse IP ({current_ip}). "
                   "Vous perdriez l'accès à l'application.",
        )
    existing = await db.blacklisted_ips.find_one({"cidr": cidr})
    if existing:
        raise HTTPException(status_code=409, detail="Cette entrée existe déjà")
    doc = {
        "id": _uuid(),
        "cidr": cidr,
        "reason": payload.reason,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.blacklisted_ips.insert_one(doc.copy())
    await _reload_blacklist()
    doc.pop("_id", None)
    return doc


@api.delete("/admin/blacklisted-ips/{ip_id}", tags=["Admin"])
async def admin_delete_blacklist(ip_id: str, _: dict = Depends(get_current_admin)):
    await db.blacklisted_ips.delete_one({"id": ip_id})
    await _reload_blacklist()
    return {"ok": True}


# ====================================================================
# PORTAL BRANDING — logo per client (used in sidebar)
# ====================================================================
@api.get("/me/branding", tags=["Portail Client"])
async def me_branding(user: dict = Depends(get_current_user)):
    """Renvoie le branding à afficher dans la sidebar du portail connecté.
    Tracked-users inherit from their client_id; clients/superviseurs use their own logo."""
    logo_url = None
    company = user.get("company")
    if user.get("logo_url"):
        logo_url = user["logo_url"]
    else:
        # Tracked users have no logo; look up parent client by tracked_users.client_id
        tu = await db.tracked_users.find_one({"email": user.get("email")}, {"_id": 0})
        if tu and tu.get("client_id"):
            parent = await db.users.find_one({"id": tu["client_id"]}, {"_id": 0})
            if parent:
                logo_url = parent.get("logo_url")
                company = parent.get("company") or company
    return {"logo_url": logo_url, "company": company}
