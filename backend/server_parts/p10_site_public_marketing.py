# server_parts/p10_site_public_marketing.py — Témoignages NPS, sitemap/robots, études de cas, blog, newsletter, pastilles du menu, fil d'activité.
# Morceau de l'ancien server.py (lignes 13225 à 14060), recopié à l'identique.
# Exécuté par server.py via _inclure_partie() dans SON espace de noms : les
# noms utilisés ici (db, api, get_current_user, helpers…) sont ceux de server.py.
# Ne pas importer ce fichier directement.

# ====================================================================
# TESTIMONIALS / NPS Feedback
# ====================================================================
@api.get("/testimonials", tags=["Public"])
async def list_published_testimonials():
    """Liste les témoignages clients publiés (pour le site public)."""
    items = await db.testimonials.find(
        {"status": "published"}, {"_id": 0}
    ).to_list(200)
    return sorted(items, key=lambda x: x.get("published_at", x.get("created_at", "")), reverse=True)


@api.get("/testimonials/stats", tags=["Public"])
async def testimonials_stats():
    """Statistiques NPS publiques (basées uniquement sur les témoignages publiés)."""
    items = await db.testimonials.find({"status": "published"}, {"_id": 0}).to_list(500)
    if not items:
        return {"count": 0, "nps": None, "average_score": None, "promoters": 0, "passives": 0, "detractors": 0}
    promoters = sum(1 for x in items if x["score"] >= 9)
    passives = sum(1 for x in items if 7 <= x["score"] <= 8)
    detractors = sum(1 for x in items if x["score"] <= 6)
    total = len(items)
    nps = round(((promoters - detractors) / total) * 100)
    return {
        "count": total,
        "nps": nps,
        "average_score": round(sum(x["score"] for x in items) / total, 1),
        "promoters": promoters,
        "passives": passives,
        "detractors": detractors,
    }


@api.get("/feedback/{token}", tags=["Public"])
async def get_feedback_form(token: str):
    """Récupère les infos d'un RDV via son feedback_token (formulaire NPS public)."""
    appt = await db.appointments.find_one({"feedback_token": token}, {"_id": 0})
    if not appt:
        raise HTTPException(status_code=404, detail="Lien invalide")
    if appt.get("feedback_status") == "submitted":
        raise HTTPException(status_code=400, detail="Avis déjà soumis pour ce rendez-vous")
    return {
        "appointment_id": appt["id"],
        "client_name": appt["name"],
        "company": appt.get("company"),
        "subject": appt["subject"],
        "scheduled_at": appt["scheduled_at"],
    }


@api.post("/feedback/{token}", tags=["Public"])
async def submit_feedback(token: str, payload: dict):
    """Soumet un témoignage NPS via le feedback_token. payload: {score:int, comment:str, allow_publish:bool}"""
    appt = await db.appointments.find_one({"feedback_token": token}, {"_id": 0})
    if not appt:
        raise HTTPException(status_code=404, detail="Lien invalide")
    if appt.get("feedback_status") == "submitted":
        raise HTTPException(status_code=400, detail="Avis déjà soumis")
    score = int(payload.get("score", -1))
    if not 0 <= score <= 10:
        raise HTTPException(status_code=400, detail="Score invalide (0-10)")
    rating_5 = payload.get("rating_5")
    if rating_5 is not None and rating_5 != "":
        rating_5 = float(rating_5)
        if not 0 <= rating_5 <= 5:
            raise HTTPException(status_code=400, detail="Note /5 doit être entre 0 et 5")
    else:
        rating_5 = None
    comment = (payload.get("comment") or "").strip()
    allow_publish = bool(payload.get("allow_publish", True))

    doc = {
        "id": _uuid(),
        "appointment_id": appt["id"],
        "client_id": appt.get("client_id"),
        "client_name": appt["name"],
        "client_company": appt.get("company"),
        "city": payload.get("city") or "",
        "country": payload.get("country") or "",
        "photo_url": payload.get("photo_url") or "",
        "subject": appt["subject"],
        "score": score,
        "rating_5": rating_5,
        "comment": comment,
        "allow_publish": allow_publish,
        "status": "pending",  # admin must moderate before publishing
        "source": "feedback",
        "created_at": _now(),
        "published_at": None,
    }
    await db.testimonials.insert_one(doc.copy())
    await db.appointments.update_one(
        {"id": appt["id"]}, {"$set": {"feedback_status": "submitted", "feedback_score": score}}
    )
    doc.pop("_id", None)
    return {"ok": True, "id": doc["id"]}


@api.get("/admin/testimonials", tags=["Admin"])
async def admin_list_testimonials(_: dict = Depends(get_current_admin)):
    items = await db.testimonials.find({}, {"_id": 0}).to_list(2000)
    return sorted(items, key=lambda x: x["created_at"], reverse=True)


@api.post("/admin/testimonials", tags=["Admin"])
async def admin_create_testimonial(payload: dict, _: dict = Depends(get_current_admin)):
    """Création manuelle d'un témoignage par l'admin.

    Champs : client_name (req), comment, score (0-10), rating_5 (1-5),
    client_company, city, country, photo_url, subject, status (default published),
    allow_publish (default True).
    """
    name = (payload.get("client_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Identité requise")
    score = int(payload.get("score", 10))
    if not 0 <= score <= 10:
        raise HTTPException(status_code=400, detail="Score doit être entre 0 et 10")
    rating_5 = payload.get("rating_5")
    if rating_5 is not None:
        rating_5 = float(rating_5)
        if not 0 <= rating_5 <= 5:
            raise HTTPException(status_code=400, detail="Note /5 doit être entre 0 et 5")
    status = payload.get("status", "published")
    if status not in ("pending", "published", "hidden"):
        status = "published"
    doc = {
        "id": _uuid(),
        "appointment_id": None,
        "client_id": payload.get("client_id"),
        "client_name": name,
        "client_company": payload.get("client_company") or "",
        "city": payload.get("city") or "",
        "country": payload.get("country") or "",
        "photo_url": payload.get("photo_url") or "",
        "subject": payload.get("subject") or "",
        "score": score,
        "rating_5": rating_5,
        "comment": (payload.get("comment") or "").strip(),
        "allow_publish": bool(payload.get("allow_publish", True)),
        "status": status,
        "source": "manual",
        "created_at": _now(),
        "published_at": _now() if status == "published" else None,
    }
    await db.testimonials.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/testimonials/{tid}", tags=["Admin"])
async def admin_update_testimonial(tid: str, payload: dict, _: dict = Depends(get_current_admin)):
    """Modère ou modifie un témoignage. Champs supportés : status, comment, client_name,
    client_company, city, country, photo_url, score, rating_5, subject, allow_publish."""
    update = {}
    for k in ("client_name", "client_company", "city", "country", "photo_url",
              "comment", "subject", "allow_publish"):
        if k in payload:
            update[k] = payload[k]
    if "score" in payload:
        score = int(payload["score"])
        if not 0 <= score <= 10:
            raise HTTPException(status_code=400, detail="Score 0-10")
        update["score"] = score
    if "rating_5" in payload:
        r = payload["rating_5"]
        if r is None or r == "":
            update["rating_5"] = None
        else:
            r = float(r)
            if not 0 <= r <= 5:
                raise HTTPException(status_code=400, detail="Note /5 doit être 0-5")
            update["rating_5"] = r
    if "status" in payload and payload["status"] in ("pending", "published", "hidden"):
        update["status"] = payload["status"]
        if payload["status"] == "published":
            update["published_at"] = _now()
    if not update:
        return {"ok": True}
    update["updated_at"] = _now()
    await db.testimonials.update_one({"id": tid}, {"$set": update})
    return {"ok": True}


@api.delete("/admin/testimonials/{tid}", tags=["Admin"])
async def admin_delete_testimonial(tid: str, _: dict = Depends(get_current_admin)):
    await db.testimonials.delete_one({"id": tid})
    return {"ok": True}


@api.post("/admin/testimonials/request/{appt_id}", tags=["Admin"])
async def admin_request_feedback(appt_id: str, _: dict = Depends(get_current_admin)):
    """Génère/regénère un feedback_token pour un RDV (le admin peut ensuite copier le lien et l'envoyer)."""
    appt = await db.appointments.find_one({"id": appt_id}, {"_id": 0})
    if not appt:
        raise HTTPException(status_code=404, detail="RDV introuvable")
    token = appt.get("feedback_token") or generate_session_token()
    await db.appointments.update_one(
        {"id": appt_id},
        {"$set": {"feedback_token": token, "feedback_status": "pending", "updated_at": _now()}},
    )
    return {"ok": True, "feedback_token": token, "feedback_url": f"/feedback/{token}"}


# ====================================================================
# Iter43-fix18 (2026-06) — Dynamic sitemap.xml + robots.txt support
# ====================================================================
@api.api_route("/sitemap.xml", methods=["GET", "HEAD"], tags=["Public"], response_class=Response)
async def public_sitemap(request: Request):
    """Génère un sitemap XML dynamique conforme au protocole sitemaps.org.

    Inclut :
      - Pages publiques statiques (accueil, missions, spécialisations,
        catalogue, contact, RDV, témoignages, blog, études de cas,
        abonnements, documentation, politiques, privacy).
      - Articles de blog publiés (`/blog/:slug`).
      - Études de cas publiées (`/etudes-de-cas/:slug`).
      - Pages politiques (`/politiques/:slug`).

    L'URL de base est résolue dans cet ordre :
      1. Header `Origin`/`Host` de la requête (≈ domaine d'accès actuel).
      2. Settings DB `public_base_url`.
      3. Variable d'env `PUBLIC_BASE_URL`.
    """
    base = _public_base_url(request) or "https://sawalismartsystems.com"
    base = base.rstrip("/")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # --- Pages statiques publiques ---
    static_pages = [
        ("/", 1.0, "weekly"),
        ("/missions", 0.8, "monthly"),
        ("/specialisations", 0.8, "monthly"),
        ("/catalogue", 0.9, "weekly"),
        ("/garde", 0.9, "daily"),  # Iter43-fix22b — page hebdo, change-freq élevée pour SEO local
        ("/etudes-de-cas", 0.8, "weekly"),
        ("/blog", 0.8, "weekly"),
        ("/temoignages", 0.7, "monthly"),
        ("/subscriptions", 0.8, "monthly"),
        ("/rdv", 0.7, "monthly"),
        ("/contact", 0.7, "monthly"),
        ("/documentation", 0.5, "monthly"),
        ("/politiques", 0.4, "yearly"),
        ("/politiques/confidentialite", 0.5, "yearly"),
        ("/politiques/services", 0.4, "yearly"),
        ("/politiques/suppression", 0.4, "yearly"),
        ("/privacy", 0.5, "yearly"),
        ("/uptime", 0.3, "weekly"),
    ]

    urls: List[Dict[str, Any]] = []
    for path, prio, freq in static_pages:
        urls.append({"loc": f"{base}{path}", "lastmod": now_iso, "changefreq": freq, "priority": prio})

    # --- Blog posts publiés ---
    try:
        posts = await db.blog_posts.find(
            {"is_published": True},
            {"_id": 0, "slug": 1, "updated_at": 1, "published_at": 1, "created_at": 1},
        ).to_list(2000)
        for p in posts:
            slug = p.get("slug")
            if not slug:
                continue
            lm = (p.get("updated_at") or p.get("published_at") or p.get("created_at") or now_iso)[:10]
            urls.append({"loc": f"{base}/blog/{slug}", "lastmod": lm, "changefreq": "monthly", "priority": 0.6})
    except Exception:  # noqa: BLE001
        logger.warning("[sitemap] failed to load blog posts", exc_info=True)

    # --- Études de cas publiées ---
    try:
        cases = await db.case_studies.find(
            {"is_published": True},
            {"_id": 0, "slug": 1, "updated_at": 1, "created_at": 1},
        ).to_list(2000)
        for c in cases:
            slug = c.get("slug")
            if not slug:
                continue
            lm = (c.get("updated_at") or c.get("created_at") or now_iso)[:10]
            urls.append({"loc": f"{base}/etudes-de-cas/{slug}", "lastmod": lm, "changefreq": "monthly", "priority": 0.7})
    except Exception:  # noqa: BLE001
        logger.warning("[sitemap] failed to load case studies", exc_info=True)

    # --- Build XML ---
    from xml.sax.saxutils import escape as _xml_escape
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for u in urls:
        lines.append("  <url>")
        lines.append(f"    <loc>{_xml_escape(u['loc'])}</loc>")
        if u.get("lastmod"):
            lines.append(f"    <lastmod>{u['lastmod']}</lastmod>")
        if u.get("changefreq"):
            lines.append(f"    <changefreq>{u['changefreq']}</changefreq>")
        if u.get("priority") is not None:
            lines.append(f"    <priority>{u['priority']:.1f}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    xml = "\n".join(lines)
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@api.api_route("/robots.txt", methods=["GET", "HEAD"], tags=["Public"], response_class=PlainTextResponse)
async def public_robots(request: Request):
    """Robots.txt dynamique pointant vers le sitemap.xml généré côté backend.
    Note : un fichier statique `/app/frontend/public/robots.txt` est également
    servi par le frontend (utile car Google va le chercher à la racine du
    domaine, hors préfixe `/api`). Les deux ont le même contenu pour cohérence.
    """
    base = _public_base_url(request) or "https://sawalismartsystems.com"
    base = base.rstrip("/")
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /portal\n"
        "Disallow: /officines\n"
        "Disallow: /api/admin\n"
        "Disallow: /remote/support\n"
        f"\nSitemap: {base}/api/sitemap.xml\n"
    )
    return PlainTextResponse(body, media_type="text/plain")


# ====================================================================
# CASE STUDIES (Études de cas)
# ====================================================================
@api.get("/case-studies", tags=["Public"])
async def list_case_studies():
    items = await db.case_studies.find({"is_published": True}, {"_id": 0}).to_list(500)
    return sorted(items, key=lambda x: (not x.get("featured"), x.get("created_at", "")), reverse=False)@api.get("/case-studies/{slug}", tags=["Public"])
async def get_case_study(slug: str):
    item = await db.case_studies.find_one({"slug": slug, "is_published": True}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Étude de cas introuvable")
    return item


@api.get("/admin/case-studies", tags=["Admin"])
async def admin_list_case_studies(_: dict = Depends(get_current_admin)):
    items = await db.case_studies.find({}, {"_id": 0}).to_list(2000)
    return sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)


def _slugify(s: str) -> str:
    import re
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"[\s-]+", "-", s)
    return s[:80] or _uuid()[:8]


@api.post("/admin/case-studies", tags=["Admin"])
async def admin_create_case_study(payload: dict, _: dict = Depends(get_current_admin)):
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Titre requis")
    slug = (payload.get("slug") or _slugify(title)).strip()
    # Ensure unique slug
    if await db.case_studies.find_one({"slug": slug}):
        slug = f"{slug}-{_uuid()[:6]}"
    doc = {
        "id": _uuid(),
        "slug": slug,
        "title": title,
        "client_name": payload.get("client_name") or "",
        "sector": payload.get("sector") or "",
        "summary": payload.get("summary") or "",
        "challenge": payload.get("challenge") or "",
        "solution": payload.get("solution") or "",
        "results": payload.get("results") or "",
        "cover_image_url": payload.get("cover_image_url") or "",
        "before_image_url": payload.get("before_image_url") or "",
        "after_image_url": payload.get("after_image_url") or "",
        "gallery": payload.get("gallery") or [],
        "kpis": payload.get("kpis") or [],
        "tags": payload.get("tags") or [],
        "duration": payload.get("duration") or "",
        "year": payload.get("year") or "",
        "is_published": bool(payload.get("is_published", True)),
        "featured": bool(payload.get("featured", False)),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.case_studies.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/case-studies/{cs_id}", tags=["Admin"])
async def admin_update_case_study(cs_id: str, payload: dict, _: dict = Depends(get_current_admin)):
    allowed = {"title", "slug", "client_name", "sector", "summary", "challenge", "solution",
               "results", "cover_image_url", "before_image_url", "after_image_url",
               "gallery", "kpis", "tags", "duration", "year", "is_published", "featured"}
    update = {k: v for k, v in payload.items() if k in allowed}
    if not update:
        return {"ok": True}
    update["updated_at"] = _now()
    await db.case_studies.update_one({"id": cs_id}, {"$set": update})
    return {"ok": True}


@api.delete("/admin/case-studies/{cs_id}", tags=["Admin"])
async def admin_delete_case_study(cs_id: str, _: dict = Depends(get_current_admin)):
    await db.case_studies.delete_one({"id": cs_id})
    return {"ok": True}


# ====================================================================
# BLOG (Articles techniques)
# ====================================================================
@api.get("/blog", tags=["Public"])
async def list_blog_posts(tag: Optional[str] = None):
    q = {"is_published": True}
    if tag:
        q["tags"] = tag
    items = await db.blog_posts.find(q, {"_id": 0, "body_html": 0}).to_list(500)
    return sorted(items, key=lambda x: x.get("published_at") or x.get("created_at", ""), reverse=True)


@api.get("/blog/tags", tags=["Public"])
async def list_blog_tags():
    items = await db.blog_posts.find({"is_published": True}, {"_id": 0, "tags": 1}).to_list(2000)
    counts: dict[str, int] = {}
    for it in items:
        for t in it.get("tags") or []:
            counts[t] = counts.get(t, 0) + 1
    return [{"tag": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: x[1], reverse=True)]


@api.get("/blog/{slug}", tags=["Public"])
async def get_blog_post(slug: str):
    item = await db.blog_posts.find_one({"slug": slug, "is_published": True}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Article introuvable")
    await db.blog_posts.update_one({"slug": slug}, {"$inc": {"views": 1}})
    item["views"] = (item.get("views") or 0) + 1
    return item


@api.get("/admin/blog", tags=["Admin"])
async def admin_list_blog(_: dict = Depends(get_current_admin)):
    items = await db.blog_posts.find({}, {"_id": 0, "body_html": 0}).to_list(2000)
    return sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)


@api.get("/admin/blog/{post_id}", tags=["Admin"])
async def admin_get_blog(post_id: str, _: dict = Depends(get_current_admin)):
    item = await db.blog_posts.find_one({"id": post_id}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Article introuvable")
    return item


@api.post("/admin/blog", tags=["Admin"])
async def admin_create_blog(payload: dict, _: dict = Depends(get_current_admin)):
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Titre requis")
    slug = (payload.get("slug") or _slugify(title)).strip()
    if await db.blog_posts.find_one({"slug": slug}):
        slug = f"{slug}-{_uuid()[:6]}"
    is_pub = bool(payload.get("is_published", True))
    doc = {
        "id": _uuid(),
        "slug": slug,
        "title": title,
        "excerpt": payload.get("excerpt") or "",
        "body_html": payload.get("body_html") or "",
        "cover_image_url": payload.get("cover_image_url") or "",
        "author_name": payload.get("author_name") or "Équipe SAWALI",
        "author_role": payload.get("author_role") or "",
        "author_photo_url": payload.get("author_photo_url") or "",
        "tags": payload.get("tags") or [],
        "reading_time_min": int(payload.get("reading_time_min") or 0),
        "is_published": is_pub,
        "featured": bool(payload.get("featured", False)),
        "views": 0,
        "created_at": _now(),
        "updated_at": _now(),
        "published_at": _now() if is_pub else None,
    }
    await db.blog_posts.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api.put("/admin/blog/{post_id}", tags=["Admin"])
async def admin_update_blog(post_id: str, payload: dict, _: dict = Depends(get_current_admin)):
    allowed = {"title", "slug", "excerpt", "body_html", "cover_image_url",
               "author_name", "author_role", "author_photo_url",
               "tags", "reading_time_min", "is_published", "featured"}
    update = {k: v for k, v in payload.items() if k in allowed}
    if "reading_time_min" in update:
        try:
            update["reading_time_min"] = int(update["reading_time_min"] or 0)
        except Exception:
            update.pop("reading_time_min")
    if update.get("is_published"):
        existing = await db.blog_posts.find_one({"id": post_id}, {"_id": 0})
        if existing and not existing.get("published_at"):
            update["published_at"] = _now()
    if not update:
        return {"ok": True}
    update["updated_at"] = _now()
    await db.blog_posts.update_one({"id": post_id}, {"$set": update})
    return {"ok": True}


@api.delete("/admin/blog/{post_id}", tags=["Admin"])
async def admin_delete_blog(post_id: str, _: dict = Depends(get_current_admin)):
    await db.blog_posts.delete_one({"id": post_id})
    return {"ok": True}


# ====================================================================
# NEWSLETTER
# ====================================================================
@api.post("/newsletter/subscribe", tags=["Public"])
async def newsletter_subscribe(payload: dict):
    email = (payload.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Email invalide")
    existing = await db.newsletter.find_one({"email": email})
    if existing:
        if existing.get("status") == "unsubscribed":
            await db.newsletter.update_one({"email": email}, {"$set": {"status": "active", "resubscribed_at": _now()}})
            return {"ok": True, "message": "Inscription réactivée"}
        return {"ok": True, "message": "Déjà abonné"}
    doc = {
        "id": _uuid(),
        "email": email,
        "name": (payload.get("name") or "").strip(),
        "source": payload.get("source") or "footer",
        "status": "active",
        "created_at": _now(),
    }
    await db.newsletter.insert_one(doc.copy())
    return {"ok": True, "message": "Merci pour votre inscription !"}


@api.post("/newsletter/unsubscribe", tags=["Public"])
async def newsletter_unsubscribe(payload: dict):
    email = (payload.get("email") or "").strip().lower()
    await db.newsletter.update_one({"email": email}, {"$set": {"status": "unsubscribed", "unsubscribed_at": _now()}})
    return {"ok": True}


@api.get("/admin/newsletter", tags=["Admin"])
async def admin_list_newsletter(_: dict = Depends(get_current_admin)):
    items = await db.newsletter.find({}, {"_id": 0}).to_list(10000)
    return sorted(items, key=lambda x: x["created_at"], reverse=True)


@api.delete("/admin/newsletter/{sub_id}", tags=["Admin"])
async def admin_delete_newsletter(sub_id: str, _: dict = Depends(get_current_admin)):
    await db.newsletter.delete_one({"id": sub_id})
    return {"ok": True}


@api.get("/admin/newsletter/export", tags=["Admin"])
async def admin_export_newsletter(_: dict = Depends(get_current_admin)):
    """Export CSV de tous les abonnés (séparateur virgule)."""
    items = await db.newsletter.find({}, {"_id": 0}).to_list(50000)
    import io
    import csv
    from fastapi.responses import StreamingResponse
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["email", "name", "status", "source", "created_at"])
    for it in sorted(items, key=lambda x: x["created_at"], reverse=True):
        writer.writerow([it.get("email", ""), it.get("name", ""), it.get("status", ""), it.get("source", ""), it.get("created_at", "")])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=newsletter_subscribers.csv"},
    )


# ====================================================================
# PHASE 5 — Notification badges on menu links
# For each module, count items created/updated since the user last visited
# that module's page. Uses collection `user_module_visits` ({user_id, module, last_visited_at}).
# ====================================================================
MODULE_COUNT_QUERIES = {
    # (module_key, collection, date_field, user_scope_field)
    # user_scope_field == "owner_id" means filter where field == user['id']
    # user_scope_field == "client_id" means use user's client_id (or self if client)
    "appointments": ("appointments", "created_at", "client_id"),
    "documents": ("documents", "created_at", "client_id"),
    "interventions": ("interventions", "created_at", "client_id"),
    "reports": ("user_notes_reports", "created_at", "owner_id"),
    "suivis": ("user_notes_suivis", "created_at", "owner_id"),
    "formations": ("formation_enrollments", "created_at", "user_id"),
    # Iter34aa — Module Paiements (était envoyé par le sidebar mais absent du dict
    # → /me/notifications/mark-seen retournait 400 "Module inconnu : payments")
    "payments": ("payment_links", "created_at", "client_id"),
    # Admin-only
    "admin_clients": ("users", "created_at", "_ADMIN_"),
    "admin_appointments": ("appointments", "created_at", "_ADMIN_"),
    "admin_interventions": ("interventions", "created_at", "_ADMIN_"),
    "admin_contacts": ("contacts", "created_at", "_ADMIN_"),
    "admin_testimonials": ("testimonials", "created_at", "_ADMIN_"),
    "admin_visits": ("visits", "datetime", "_ADMIN_"),
    "admin_access_logs": ("access_logs", "created_at", "_ADMIN_"),
    "admin_api_traces": ("api_traces", "created_at", "_ADMIN_"),
}


async def _resolve_client_id(user: dict) -> Optional[str]:
    """Return the client_id scope for a user: themselves if role=client, or parent_client_id if tracked."""
    if user.get("role") == "client":
        return user.get("id")
    if user.get("role") == "admin":
        return None  # admin has no client scope
    # tracked user — find the parent client
    return user.get("parent_client_id") or user.get("client_id")


async def _resolve_visible_client_ids(user: dict) -> List[str]:
    """Iter34 — Resolve ALL client_ids whose contacts/messages this user
    legitimately sees. Bridges historical client_id misalignments by including:
      • the user's canonical client_id and parent_client_id
      • their own id (legacy contacts created when the row was self-owned)
      • every other admin/parent user sharing the SAME `company` (case-insensitive)

    This guarantees that two users typed with the same employer name see each
    other's directory even if their client_id pointers were never re-aligned.
    """
    ids: set[str] = set()
    for k in ("client_id", "parent_client_id", "id"):
        v = user.get(k)
        if v:
            ids.add(v)
    company = (user.get("company") or "").strip()
    if company:
        try:
            cursor = db.users.find(
                {"company": {"$regex": f"^{re.escape(company)}$", "$options": "i"}},
                {"_id": 0, "id": 1, "client_id": 1, "parent_client_id": 1},
            )
            async for u in cursor:
                for k in ("id", "client_id", "parent_client_id"):
                    v = u.get(k)
                    if v:
                        ids.add(v)
        except Exception:
            pass
    return list(ids) if ids else [user.get("id")]


# ============================================================
# Iter34x — Real-time activity feed (polling-based).
# Every CUD on Contact, Rapport, Suivi, SMS, WhatsApp is logged into
# `activity_events` with `{client_id, kind, action, label, actor, ts}`.
# Connected clients poll /me/recent-activity every 8 seconds to learn
# what happened since their `since` cursor; the frontend then shows a
# Sonner toast (suppressing actions performed by the polling user itself).
# ============================================================
async def _log_activity(*, client_id: str, kind: str, action: str, label: str, actor: dict, target_id: Optional[str] = None):
    """Best-effort write of a single activity event. Never raises."""
    try:
        await db.activity_events.insert_one({
            "id": _uuid(),
            "client_id": client_id,
            "kind": kind,         # contact | rapport | suivi | sms | whatsapp
            "action": action,     # created | updated | deleted | received | sent
            "label": (label or "")[:160],
            "target_id": target_id,
            "actor_id": actor.get("id"),
            "actor_label": actor.get("full_name") or actor.get("email") or "—",
            "ts": _now(),
        })
    except Exception:
        pass


# Iter38r-fix9w — Fire-and-forget hook to the Home Assistant voice
# notifications pipeline. The tenant must (a) have the gateway enabled and
# (b) have a rule.enabled=True for the given event_key. trigger_voice_event
# never raises, so this helper is safe to call after critical mutations.
async def _voice_notify(tenant_id: str, event_key: str, context: Dict[str, Any]) -> None:
    try:
        from routes.voice_notifications import trigger_voice_event
        await trigger_voice_event(db, tenant_id, event_key, context)
    except Exception:
        pass


@api.get("/me/recent-activity", tags=["Portail Client"])
async def me_recent_activity(
    since: Optional[str] = None,
    limit: int = 20,
    user: dict = Depends(get_current_user),
):
    """Return new activity events for the user's visible scope since the
    `since` ISO timestamp. The frontend uses this to display floating
    toasts in near real-time. Events triggered by the requester are
    returned so the client can decide to suppress them locally."""
    visible_scope = await _resolve_visible_client_ids(user)
    q: Dict[str, Any] = {"client_id": {"$in": visible_scope}}
    if since:
        try:
            # The `ts` field on activity_events is an ISO string (from _now()),
            # so the comparison is string-based.
            q["ts"] = {"$gt": since}
        except Exception:
            pass
    items = await db.activity_events.find(q, {"_id": 0}).sort("ts", -1).to_list(min(max(limit, 1), 100))
    items.reverse()  # chronological order for toast stacking
    return {
        "events": items,
        "server_now": _now(),
        "viewer_id": user.get("id"),
    }


@api.get("/me/notifications/counts", tags=["Portail Client"])
async def me_notifications_counts(user: dict = Depends(get_current_user)):
    """Return the count of new items per module since the user last visited that module."""
    now = datetime.now(timezone.utc)
    # Default lookback window: 30 days for modules the user has never visited
    default_since = (now - timedelta(days=30)).isoformat()

    visits_cursor = db.user_module_visits.find({"user_id": user["id"]}, {"_id": 0, "module": 1, "last_visited_at": 1})
    visits = {v["module"]: v["last_visited_at"] async for v in visits_cursor}

    is_admin = user.get("role") == "admin"
    client_scope = await _resolve_client_id(user)
    counts: dict[str, int] = {}

    async def _count(module_key: str, spec: tuple) -> int:
        coll_name, date_field, scope = spec
        since = visits.get(module_key, default_since)
        query: dict = {date_field: {"$gt": since}}
        if scope == "_ADMIN_":
            if not is_admin:
                return 0
        elif scope == "owner_id":
            query["owner_id"] = user["id"]
        elif scope == "user_id":
            query["user_id"] = user["id"]
        elif scope == "client_id":
            if client_scope is None and not is_admin:
                return 0
            if client_scope:
                query["client_id"] = client_scope
        try:
            return await db[coll_name].count_documents(query)
        except Exception:
            return 0

    for key, spec in MODULE_COUNT_QUERIES.items():
        counts[key] = await _count(key, spec)
    # Special: WhatsApp inbound unread (not based on last_visited_at — uses read_by_us_at).
    # Lot 23 — MÊME calcul que les pastilles du Centre de Messagerie
    # (_wa_unread_summary) : avant, le badge comptait sur un autre périmètre
    # (un seul client_id, ou tous les tenants pour l'admin) et incluait des
    # messages qu'aucune conversation ne permettait de marquer comme lus.
    try:
        counts["contacts_unread"] = (await _wa_unread_summary(user))["total"]
    except Exception:
        counts["contacts_unread"] = 0
    # Iter34l — Admin-only: pending profile-update requests (status-driven, not visit-driven)
    try:
        if is_admin:
            counts["admin_profile_requests"] = await db.profile_update_requests.count_documents({"status": "pending"})
        else:
            counts["admin_profile_requests"] = 0
    except Exception:
        counts["admin_profile_requests"] = 0
    # Iter40 (2026-02) → Iter43-fix (2026-03) — Registre des erreurs :
    # 2 badges (high + critical) basés sur le nouveau champ `mapped_severity`
    # (Iter43-fix). Fallback heuristique sur StatutEnCours pour les anciennes
    # entrées sans mapped_severity (pré-Iter43).
    try:
        from routes.error_registry import ALLOWED_ROLES as _ER_ALLOWED
        role_ok = (user.get("role") or "").lower() in _ER_ALLOWED
        if role_ok:
            base_q = {"deleted_at": None, "acknowledged": False, "estActif": True}
            counts["errors_unack"] = await db.error_registry.count_documents(base_q)
            # Récupère la table de mapping admin pour traduire les anciennes entrées
            s_doc = await db.settings.find_one({"_id": "global"}, {"_id": 0, "error_severity_mapping": 1}) or {}
            mapping_lc = {k.lower(): v for k, v in (s_doc.get("error_severity_mapping") or {}).items()}
            # Branche A — entrées avec mapped_severity déjà résolu
            mapped_high = await db.error_registry.count_documents({**base_q, "mapped_severity": "high"})
            mapped_critical = await db.error_registry.count_documents({**base_q, "mapped_severity": "critical"})
            # Branche B — entrées legacy (pas de mapped_severity) — on applique
            # l'heuristique sur StatutEnCours pour chaque entrée pertinente.
            legacy_high = 0
            legacy_critical = 0
            legacy_filter = {**base_q, "mapped_severity": {"$exists": False}}
            async for d in db.error_registry.find(legacy_filter, {"_id": 0, "StatutEnCours": 1}):
                statut = ((d.get("StatutEnCours") or "")).strip().lower()
                mapped = mapping_lc.get(statut)
                if not mapped:
                    if statut in ("fatale", "fatal", "critical", "critique"):
                        mapped = "critical"
                    elif statut in ("exception", "erreur", "error"):
                        mapped = "high"
                if mapped == "high":
                    legacy_high += 1
                elif mapped == "critical":
                    legacy_critical += 1
            counts["errors_high"] = mapped_high + legacy_high
            counts["errors_critical"] = mapped_critical + legacy_critical
            # Backward compat — alias avec les anciens noms (sidebar pré-fix)
            counts["errors_exception"] = counts["errors_high"]
            counts["errors_fatale"] = counts["errors_critical"]
        else:
            counts["errors_unack"] = 0
            counts["errors_high"] = 0
            counts["errors_critical"] = 0
            counts["errors_exception"] = 0
            counts["errors_fatale"] = 0
    except Exception:
        counts["errors_unack"] = 0
        counts["errors_high"] = 0
        counts["errors_critical"] = 0
        counts["errors_exception"] = 0
        counts["errors_fatale"] = 0
    return {"counts": counts, "generated_at": _now()}


class MarkSeenRequest(BaseModel):
    module: str
