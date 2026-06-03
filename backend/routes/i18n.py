"""S046 — i18n translations management (2026-02).

Storage : single `i18n_translations` collection. Each document is one
translation key with all language variants :

    {
        "key": "nav.dashboard",
        "fr": "Tableau de bord",            # source of truth
        "en": "Dashboard",
        "ar": "لوحة القيادة",
        "lg1": "",                          # Gulmancema (filled by humans)
        "lg2": "",                          # Mooré
        "context": "Sidebar navigation",    # admin-only hint
        "updated_at": "...",
        "updated_by_id": "...",
        "updated_by_email": "...",
    }

Endpoints :

    GET   /api/i18n/languages                   — public list of supported langs
    GET   /api/i18n/translations?lang=fr        — public dictionary {key: text}
    GET   /api/admin/i18n/translations          — admin full table
    POST  /api/admin/i18n/translations          — admin upsert one row
    DELETE /api/admin/i18n/translations/{key}    — admin delete
    POST  /api/admin/i18n/translations/bulk     — admin upsert many

The Frontend i18n provider fetches `/api/i18n/translations?lang=…` once on
mount + on language change, then exposes a `t(key)` helper. Fallback to FR
when a key has no entry for the chosen lang.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.i18n")


# Supported languages — fixed list (FR is the source of truth).
SUPPORTED_LANGS = [
    {"code": "fr", "label": "Français", "native": "Français", "rtl": False, "primary": True},
    {"code": "en", "label": "Anglais", "native": "English", "rtl": False},
    {"code": "ar", "label": "Arabe", "native": "العربية", "rtl": True},
    {"code": "lg1", "label": "Gulmancema", "native": "Gulmancema", "rtl": False},
    {"code": "lg2", "label": "Mooré", "native": "Mooré", "rtl": False},
]
LANG_CODES = {lang["code"] for lang in SUPPORTED_LANGS}


# Region → preferred language map. Best-effort fallback when the browser
# doesn't advertise a language. Country codes are ISO 3166-1 alpha-2.
# Africa francophone, Maghreb arab, anglo-American etc.
COUNTRY_LANG_MAP: Dict[str, str] = {
    # West/Central Africa francophone
    "BF": "fr", "CI": "fr", "SN": "fr", "TG": "fr", "BJ": "fr", "ML": "fr",
    "NE": "fr", "GN": "fr", "CM": "fr", "GA": "fr", "TD": "fr", "CG": "fr",
    "CD": "fr", "MG": "fr", "BI": "fr", "RW": "fr", "MR": "fr", "DJ": "fr",
    "FR": "fr", "BE": "fr", "CH": "fr", "LU": "fr", "MC": "fr",
    # Maghreb / Middle East arabophone (most also speak FR but AR is primary)
    "MA": "ar", "DZ": "ar", "TN": "ar", "EG": "ar", "LY": "ar", "SD": "ar",
    "SA": "ar", "AE": "ar", "QA": "ar", "KW": "ar", "BH": "ar", "OM": "ar",
    "JO": "ar", "LB": "ar", "SY": "ar", "IQ": "ar", "YE": "ar", "PS": "ar",
    # Anglophone
    "US": "en", "GB": "en", "CA": "en", "AU": "en", "NZ": "en", "IE": "en",
    "ZA": "en", "NG": "en", "GH": "en", "KE": "en", "UG": "en", "TZ": "en",
    "ZM": "en", "ZW": "en", "BW": "en", "MW": "en", "SL": "en", "LR": "en",
    "GM": "en", "ET": "en", "IN": "en", "PK": "en", "PH": "en", "SG": "en",
}


# Seed strings — the most-visible UI labels that need translation by default.
# AR = Modern Standard Arabic. LG1 (Gulmancema) and LG2 (Mooré) are left
# empty on purpose, to be filled manually by human translators.
SEED_KEYS: List[Dict[str, str]] = [
    # --- Navigation (PortalLayout sidebar) ---
    {"key": "nav.dashboard", "fr": "Tableau de bord", "en": "Dashboard", "ar": "لوحة القيادة", "context": "Sidebar"},
    {"key": "nav.appointments", "fr": "Mes rendez-vous", "en": "My appointments", "ar": "مواعيدي", "context": "Sidebar"},
    {"key": "nav.documentation", "fr": "Documentation", "en": "Documentation", "ar": "الوثائق", "context": "Sidebar"},
    {"key": "nav.interventions", "fr": "Historique interventions", "en": "Intervention history", "ar": "سجل التدخلات", "context": "Sidebar"},
    {"key": "nav.users_tracking", "fr": "Suivi utilisateurs", "en": "Users tracking", "ar": "متابعة المستخدمين", "context": "Sidebar"},
    {"key": "nav.reports", "fr": "Mes rapports", "en": "My reports", "ar": "تقاريري", "context": "Sidebar"},
    {"key": "nav.followups", "fr": "Mes suivis", "en": "My follow-ups", "ar": "متابعاتي", "context": "Sidebar"},
    {"key": "nav.forms", "fr": "Formulaires", "en": "Forms", "ar": "النماذج", "context": "Sidebar"},
    {"key": "nav.contacts", "fr": "Centre de Messagerie", "en": "Messaging Center", "ar": "مركز المراسلة", "context": "Sidebar"},
    {"key": "nav.tickets", "fr": "Tickets", "en": "Tickets", "ar": "التذاكر", "context": "Sidebar"},
    {"key": "nav.liluvine", "fr": "Liluvine PRO (Assistant IA)", "en": "Liluvine PRO (AI Assistant)", "ar": "ليلوفين برو (مساعد الذكاء الاصطناعي)", "context": "Sidebar"},
    {"key": "nav.inbox", "fr": "Inbox unifiée (WA + Messenger)", "en": "Unified inbox (WA + Messenger)", "ar": "صندوق موحد (واتساب + ماسنجر)", "context": "Sidebar"},
    {"key": "nav.sms", "fr": "SMS — Masse & Planif.", "en": "SMS — Bulk & Schedule", "ar": "رسائل قصيرة — جماعية وجدولة", "context": "Sidebar"},
    {"key": "nav.whatsapp_bulk", "fr": "WhatsApp — Masse & Planif.", "en": "WhatsApp — Bulk & Schedule", "ar": "واتساب — جماعي وجدولة", "context": "Sidebar"},
    {"key": "nav.cash", "fr": "Caisse/Facturation", "en": "Cashier/Invoicing", "ar": "الصندوق / الفوترة", "context": "Sidebar"},
    {"key": "nav.hr", "fr": "GRH — Ressources Humaines", "en": "HRM — Human Resources", "ar": "الموارد البشرية", "context": "Sidebar"},
    {"key": "nav.meetings", "fr": "PV de réunions", "en": "Meeting Minutes", "ar": "محاضر الاجتماعات", "context": "Sidebar"},
    {"key": "nav.media_lib", "fr": "Bibliothèque de médias", "en": "Media library", "ar": "مكتبة الوسائط", "context": "Sidebar"},
    {"key": "nav.media_gen", "fr": "Générateur d'Images et Vidéos", "en": "Images & Videos generator", "ar": "مُولِّد الصور والفيديوهات", "context": "Sidebar"},
    {"key": "nav.voice_studio", "fr": "Voice Studio (Clonage)", "en": "Voice Studio (Cloning)", "ar": "استوديو الصوت (الاستنساخ)", "context": "Sidebar"},
    {"key": "nav.brochures", "fr": "Brochures & Guides", "en": "Brochures & Guides", "ar": "الكتيبات والأدلة", "context": "Sidebar"},
    {"key": "nav.catalog_stats", "fr": "Statistiques catalogue", "en": "Catalog statistics", "ar": "إحصاءات الكتالوج", "context": "Sidebar"},
    {"key": "nav.logout", "fr": "Se déconnecter", "en": "Sign out", "ar": "تسجيل الخروج", "context": "Sidebar"},
    # --- Common buttons ---
    {"key": "common.save", "fr": "Enregistrer", "en": "Save", "ar": "حفظ"},
    {"key": "common.cancel", "fr": "Annuler", "en": "Cancel", "ar": "إلغاء"},
    {"key": "common.delete", "fr": "Supprimer", "en": "Delete", "ar": "حذف"},
    {"key": "common.edit", "fr": "Modifier", "en": "Edit", "ar": "تعديل"},
    {"key": "common.create", "fr": "Créer", "en": "Create", "ar": "إنشاء"},
    {"key": "common.search", "fr": "Rechercher", "en": "Search", "ar": "بحث"},
    {"key": "common.refresh", "fr": "Actualiser", "en": "Refresh", "ar": "تحديث"},
    {"key": "common.confirm", "fr": "Confirmer", "en": "Confirm", "ar": "تأكيد"},
    {"key": "common.close", "fr": "Fermer", "en": "Close", "ar": "إغلاق"},
    {"key": "common.loading", "fr": "Chargement…", "en": "Loading…", "ar": "جارٍ التحميل…"},
    {"key": "common.yes", "fr": "Oui", "en": "Yes", "ar": "نعم"},
    {"key": "common.no", "fr": "Non", "en": "No", "ar": "لا"},
    {"key": "common.add", "fr": "Ajouter", "en": "Add", "ar": "إضافة"},
    {"key": "common.remove", "fr": "Retirer", "en": "Remove", "ar": "إزالة"},
    {"key": "common.next", "fr": "Suivant", "en": "Next", "ar": "التالي"},
    {"key": "common.previous", "fr": "Précédent", "en": "Previous", "ar": "السابق"},
    {"key": "common.download", "fr": "Télécharger", "en": "Download", "ar": "تنزيل"},
    {"key": "common.upload", "fr": "Téléverser", "en": "Upload", "ar": "رفع"},
    {"key": "common.export", "fr": "Exporter", "en": "Export", "ar": "تصدير"},
    {"key": "common.import", "fr": "Importer", "en": "Import", "ar": "استيراد"},
    {"key": "common.send", "fr": "Envoyer", "en": "Send", "ar": "إرسال"},
    {"key": "common.copy", "fr": "Copier", "en": "Copy", "ar": "نسخ"},
    {"key": "common.share", "fr": "Partager", "en": "Share", "ar": "مشاركة"},
    {"key": "common.print", "fr": "Imprimer", "en": "Print", "ar": "طباعة"},
    {"key": "common.required", "fr": "Requis", "en": "Required", "ar": "مطلوب"},
    {"key": "common.optional", "fr": "Facultatif", "en": "Optional", "ar": "اختياري"},
    {"key": "common.error", "fr": "Erreur", "en": "Error", "ar": "خطأ"},
    {"key": "common.success", "fr": "Succès", "en": "Success", "ar": "نجاح"},
    {"key": "common.warning", "fr": "Attention", "en": "Warning", "ar": "تحذير"},
    {"key": "common.info", "fr": "Information", "en": "Information", "ar": "معلومات"},
    {"key": "common.actions", "fr": "Actions", "en": "Actions", "ar": "إجراءات"},
    {"key": "common.status", "fr": "Statut", "en": "Status", "ar": "الحالة"},
    {"key": "common.filter", "fr": "Filtrer", "en": "Filter", "ar": "تصفية"},
    {"key": "common.sort", "fr": "Trier", "en": "Sort", "ar": "ترتيب"},
    {"key": "common.all", "fr": "Tous", "en": "All", "ar": "الكل"},
    {"key": "common.none", "fr": "Aucun", "en": "None", "ar": "لا شيء"},
    {"key": "common.empty", "fr": "Vide", "en": "Empty", "ar": "فارغ"},
    {"key": "common.back", "fr": "Retour", "en": "Back", "ar": "رجوع"},
    # --- Login page ---
    {"key": "login.title", "fr": "Espace Loois", "en": "Loois Space", "ar": "فضاء لوويس"},
    {"key": "login.subtitle", "fr": "Saisissez vos identifiants. Un code à usage unique vous sera envoyé.", "en": "Enter your credentials. A one-time code will be sent to you.", "ar": "أدخل بيانات اعتمادك. سيُرسَل إليك رمز لمرة واحدة."},
    {"key": "login.email", "fr": "Email", "en": "Email", "ar": "البريد الإلكتروني"},
    {"key": "login.password", "fr": "Mot de passe", "en": "Password", "ar": "كلمة المرور"},
    {"key": "login.submit", "fr": "Se connecter", "en": "Sign in", "ar": "تسجيل الدخول"},
    {"key": "login.via_whatsapp", "fr": "Se connecter via WhatsApp", "en": "Sign in via WhatsApp", "ar": "تسجيل الدخول عبر واتساب"},
    {"key": "login.no_account", "fr": "Pas encore de compte ?", "en": "No account yet?", "ar": "ليس لديك حساب بعد؟"},
    {"key": "login.request_access", "fr": "Demander un accès", "en": "Request access", "ar": "طلب الوصول"},
    {"key": "login.connexion", "fr": "Connexion", "en": "Sign in", "ar": "تسجيل الدخول"},
    {"key": "login.or", "fr": "ou", "en": "or", "ar": "أو"},
    {"key": "login.welcome_back", "fr": "Bienvenue dans votre Espace Loois sécurisé.", "en": "Welcome back to your secure Loois space.", "ar": "مرحبًا بعودتك إلى فضاء لوويس الآمن."},
    {"key": "login.tagline", "fr": "Suivez vos rendez-vous, accédez à la documentation de vos logiciels et consultez l'historique de nos interventions.", "en": "Track your appointments, access your software documentation and review our intervention history.", "ar": "تابع مواعيدك، اطّلع على وثائق برمجياتك، وراجع سجل تدخلاتنا."},
    # --- Public marketing site ---
    {"key": "public.nav.home", "fr": "Accueil", "en": "Home", "ar": "الرئيسية"},
    {"key": "public.nav.missions", "fr": "Missions", "en": "Missions", "ar": "المهام"},
    {"key": "public.nav.specialisations", "fr": "Spécialisations", "en": "Specialisations", "ar": "التخصصات"},
    {"key": "public.nav.catalogue", "fr": "Catalogue", "en": "Catalogue", "ar": "الكتالوج"},
    {"key": "public.nav.case_studies", "fr": "Études de cas", "en": "Case studies", "ar": "دراسات الحالة"},
    {"key": "public.nav.subscriptions", "fr": "Abonnements", "en": "Subscriptions", "ar": "الاشتراكات"},
    {"key": "public.nav.testimonials", "fr": "Témoignages", "en": "Testimonials", "ar": "الشهادات"},
    {"key": "public.nav.rdv", "fr": "Demande RDV", "en": "Book appointment", "ar": "حجز موعد"},
    {"key": "public.nav.contact", "fr": "Contact", "en": "Contact", "ar": "اتصل بنا"},
    {"key": "public.nav.policies", "fr": "Politiques", "en": "Policies", "ar": "السياسات"},
    {"key": "public.nav.my_space", "fr": "Mon espace", "en": "My space", "ar": "فضائي"},
    {"key": "public.nav.loois_space", "fr": "Espace Loois", "en": "Loois Space", "ar": "فضاء لوويس"},
    {"key": "public.nav.book_rdv", "fr": "Réserver un RDV", "en": "Book a meeting", "ar": "احجز اجتماعًا"},
    # --- Dashboard ---
    {"key": "dashboard.welcome", "fr": "Bienvenue", "en": "Welcome", "ar": "مرحبًا"},
    {"key": "dashboard.activity", "fr": "Activité récente", "en": "Recent activity", "ar": "النشاط الأخير"},
    {"key": "dashboard.upcoming", "fr": "À venir", "en": "Upcoming", "ar": "القادم"},
    {"key": "dashboard.notifications", "fr": "Notifications", "en": "Notifications", "ar": "الإشعارات"},
    {"key": "dashboard.no_data", "fr": "Aucune donnée à afficher.", "en": "No data to display.", "ar": "لا توجد بيانات لعرضها."},
    # --- Contacts / Messaging ---
    {"key": "contacts.title", "fr": "Centre de Messagerie", "en": "Messaging Center", "ar": "مركز المراسلة"},
    {"key": "contacts.add", "fr": "Nouveau contact", "en": "New contact", "ar": "جهة اتصال جديدة"},
    {"key": "contacts.search_placeholder", "fr": "Rechercher un contact…", "en": "Search a contact…", "ar": "ابحث عن جهة اتصال…"},
    {"key": "contacts.no_results", "fr": "Aucun contact trouvé.", "en": "No contact found.", "ar": "لم يتم العثور على جهة اتصال."},
    # --- Errors ---
    {"key": "error.generic", "fr": "Une erreur est survenue.", "en": "An error occurred.", "ar": "حدث خطأ."},
    {"key": "error.network", "fr": "Erreur réseau. Vérifiez votre connexion.", "en": "Network error. Check your connection.", "ar": "خطأ في الشبكة. تحقق من اتصالك."},
    {"key": "error.unauthorized", "fr": "Action non autorisée.", "en": "Unauthorized action.", "ar": "إجراء غير مصرّح به."},
    {"key": "error.not_found", "fr": "Élément introuvable.", "en": "Item not found.", "ar": "العنصر غير موجود."},
    # --- Language change feedback ---
    {"key": "lang.changed", "fr": "Langue changée", "en": "Language changed", "ar": "تم تغيير اللغة"},
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TranslationUpsert(BaseModel):
    key: str = Field(..., min_length=1, max_length=160, pattern=r"^[a-zA-Z][a-zA-Z0-9._-]*$")
    fr: str = Field(..., max_length=4000)
    en: Optional[str] = Field("", max_length=4000)
    ar: Optional[str] = Field("", max_length=4000)
    lg1: Optional[str] = Field("", max_length=4000)
    lg2: Optional[str] = Field("", max_length=4000)
    context: Optional[str] = Field("", max_length=400)


class TranslationBulkUpsert(BaseModel):
    rows: List[TranslationUpsert]


def attach_i18n_routes(api: APIRouter, *, db: Any, get_current_user: Any) -> None:
    """Mount the i18n routes on the provided FastAPI router."""

    async def _ensure_seed():
        """Insert SEED_KEYS rows when missing AND backfill empty language
        columns from the seed.

        Idempotent + additive : never overwrites a non-empty value that the
        admin may have edited. For each seed key :
          - If the row doesn't exist : create it from the seed.
          - If the row exists : update ONLY the columns that are empty in DB
            but present in the seed (so e.g. adding AR translations to the
            seed automatically fills rows that were missing AR).
        """
        try:
            for s in SEED_KEYS:
                existing = await db.i18n_translations.find_one(
                    {"key": s["key"]},
                    {"_id": 0, "key": 1, "fr": 1, "en": 1, "ar": 1, "lg1": 1, "lg2": 1, "context": 1},
                )
                if not existing:
                    doc = {
                        "key": s["key"],
                        "fr": s.get("fr", ""),
                        "en": s.get("en", ""),
                        "ar": s.get("ar", ""),
                        "lg1": s.get("lg1", ""),
                        "lg2": s.get("lg2", ""),
                        "context": s.get("context", ""),
                        "updated_at": _now(),
                        "updated_by_email": "_system_",
                    }
                    await db.i18n_translations.insert_one(doc)
                    continue
                # Backfill : update only EMPTY DB columns with non-empty seed values.
                patch: Dict[str, Any] = {}
                for field in ("en", "ar", "lg1", "lg2", "context"):
                    db_val = (existing.get(field) or "").strip()
                    seed_val = (s.get(field) or "").strip()
                    if not db_val and seed_val:
                        patch[field] = seed_val
                if patch:
                    patch["updated_at"] = _now()
                    patch["updated_by_email"] = "_system_"
                    await db.i18n_translations.update_one(
                        {"key": s["key"]}, {"$set": patch},
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[i18n] seed upsert failed: %s", exc)

    # --------- Public ---------
    @api.get("/i18n/languages", tags=["i18n"])
    async def i18n_languages():
        return {"items": SUPPORTED_LANGS, "default": "fr"}

    @api.get("/i18n/translations", tags=["i18n"])
    async def i18n_public_dictionary(lang: str = "fr"):
        """Return {key: text} for the requested language. Falls back to FR
        when the row has an empty value for that language."""
        if lang not in LANG_CODES:
            raise HTTPException(status_code=400, detail=f"Langue non supportée : {lang}")
        await _ensure_seed()
        out: Dict[str, str] = {}
        async for row in db.i18n_translations.find({}, {"_id": 0, "key": 1, "fr": 1, lang: 1}):
            value = (row.get(lang) or "").strip()
            if not value:
                value = row.get("fr") or row.get("key") or ""
            out[row["key"]] = value
        return {"lang": lang, "translations": out, "count": len(out)}

    # ----------------------------------------------------------
    # S046 (2026-02) — Public language detection. The Frontend calls this
    # endpoint on the very first visit (no `sawali_lang` cookie yet) so we
    # can suggest a language based on the visitor's IP region. This
    # complements `navigator.language` (which still wins when available).
    # ----------------------------------------------------------
    @api.get("/i18n/detect", tags=["i18n"])
    async def i18n_detect_region(request: Request):
        """Return {"suggested_lang": "fr|en|ar"} based on Cloudflare / CDN
        country headers or `Accept-Language`. Best-effort — defaults to FR."""
        country = (
            request.headers.get("cf-ipcountry")
            or request.headers.get("x-vercel-ip-country")
            or request.headers.get("x-country-code")
            or ""
        ).upper()
        suggested = COUNTRY_LANG_MAP.get(country, "")

        # If no country header, parse Accept-Language as a secondary hint
        if not suggested:
            accept = (request.headers.get("accept-language") or "").lower()
            for tag in re.split(r"[,;\s]+", accept):
                base = tag.split("-")[0]
                if base in LANG_CODES and base != "fr":
                    suggested = base
                    break
            if not suggested and accept.startswith("fr"):
                suggested = "fr"

        return {
            "suggested_lang": suggested or "fr",
            "country": country or None,
            "accept_language": request.headers.get("accept-language") or None,
            "supported": [lang_def["code"] for lang_def in SUPPORTED_LANGS],
        }

    # --------- Admin ---------
    def _is_admin_or_sup(user: dict) -> bool:
        return (user.get("role") or "") in ("admin", "superviseur")

    @api.get("/admin/i18n/translations", tags=["Admin — i18n"])
    async def admin_list_translations(user: dict = Depends(get_current_user)):
        if not _is_admin_or_sup(user):
            raise HTTPException(status_code=403, detail="Réservé admin/superviseur")
        await _ensure_seed()
        rows: List[Dict[str, Any]] = []
        async for r in db.i18n_translations.find({}, {"_id": 0}).sort("key", 1):
            rows.append(r)
        return {"items": rows, "count": len(rows), "languages": SUPPORTED_LANGS}

    @api.post("/admin/i18n/translations", tags=["Admin — i18n"])
    async def admin_upsert_translation(
        payload: TranslationUpsert, user: dict = Depends(get_current_user)
    ):
        if not _is_admin_or_sup(user):
            raise HTTPException(status_code=403, detail="Réservé admin/superviseur")
        update = {
            "key": payload.key,
            "fr": payload.fr,
            "en": payload.en or "",
            "ar": payload.ar or "",
            "lg1": payload.lg1 or "",
            "lg2": payload.lg2 or "",
            "context": payload.context or "",
            "updated_at": _now(),
            "updated_by_id": user.get("id"),
            "updated_by_email": user.get("email"),
        }
        await db.i18n_translations.update_one(
            {"key": payload.key}, {"$set": update}, upsert=True,
        )
        update.pop("_id", None)
        return {"ok": True, "row": update}

    @api.delete("/admin/i18n/translations/{key}", tags=["Admin — i18n"])
    async def admin_delete_translation(
        key: str, user: dict = Depends(get_current_user)
    ):
        if not _is_admin_or_sup(user):
            raise HTTPException(status_code=403, detail="Réservé admin/superviseur")
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9._-]*$", key):
            raise HTTPException(status_code=400, detail="Clé invalide")
        res = await db.i18n_translations.delete_one({"key": key})
        return {"ok": True, "deleted": res.deleted_count}

    @api.post("/admin/i18n/translations/bulk", tags=["Admin — i18n"])
    async def admin_bulk_upsert(
        payload: TranslationBulkUpsert, user: dict = Depends(get_current_user)
    ):
        if not _is_admin_or_sup(user):
            raise HTTPException(status_code=403, detail="Réservé admin/superviseur")
        n = 0
        for row in payload.rows:
            update = {
                "key": row.key,
                "fr": row.fr,
                "en": row.en or "",
                "ar": row.ar or "",
                "lg1": row.lg1 or "",
                "lg2": row.lg2 or "",
                "context": row.context or "",
                "updated_at": _now(),
                "updated_by_id": user.get("id"),
                "updated_by_email": user.get("email"),
            }
            await db.i18n_translations.update_one(
                {"key": row.key}, {"$set": update}, upsert=True,
            )
            n += 1
        return {"ok": True, "upserted": n}

    # ----------------------------------------------------------
    # S046 (2026-02) — CSV export / import for offline translation work.
    # ----------------------------------------------------------
    @api.get("/admin/i18n/translations.csv", tags=["Admin — i18n"])
    async def admin_export_csv(user: dict = Depends(get_current_user)):
        if not _is_admin_or_sup(user):
            raise HTTPException(status_code=403, detail="Réservé admin/superviseur")
        await _ensure_seed()
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf, fieldnames=["key", "fr", "en", "ar", "lg1", "lg2", "context"],
            extrasaction="ignore", quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        async for r in db.i18n_translations.find({}, {"_id": 0}).sort("key", 1):
            writer.writerow({
                "key": r.get("key", ""),
                "fr": r.get("fr", ""),
                "en": r.get("en", ""),
                "ar": r.get("ar", ""),
                "lg1": r.get("lg1", ""),
                "lg2": r.get("lg2", ""),
                "context": r.get("context", ""),
            })
        buf.seek(0)
        # Prefix with UTF-8 BOM so Excel opens it with correct encoding.
        content = "\ufeff" + buf.getvalue()
        filename = f"sawali_translations_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        return StreamingResponse(
            iter([content]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @api.post("/admin/i18n/translations/import-csv", tags=["Admin — i18n"])
    async def admin_import_csv(
        file: UploadFile = File(...),
        user: dict = Depends(get_current_user),
    ):
        if not _is_admin_or_sup(user):
            raise HTTPException(status_code=403, detail="Réservé admin/superviseur")
        if not file.filename or not file.filename.lower().endswith(".csv"):
            raise HTTPException(status_code=400, detail="Veuillez téléverser un fichier .csv.")
        raw = (await file.read()).decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(raw))
        required = {"key", "fr"}
        if not required.issubset(set((reader.fieldnames or []))):
            raise HTTPException(
                status_code=400,
                detail=f"Colonnes requises absentes : {', '.join(required)}. Colonnes lues : {reader.fieldnames}",
            )
        upserts = 0
        errors: List[str] = []
        for i, row in enumerate(reader, start=2):  # start=2 because of header line
            key = (row.get("key") or "").strip()
            fr_val = (row.get("fr") or "").strip()
            if not key:
                errors.append(f"Ligne {i} : clé vide — ignorée")
                continue
            if not re.match(r"^[a-zA-Z][a-zA-Z0-9._-]*$", key):
                errors.append(f"Ligne {i} : clé invalide '{key}' — ignorée")
                continue
            if not fr_val:
                errors.append(f"Ligne {i} ({key}) : FR vide — ignorée")
                continue
            update = {
                "key": key,
                "fr": fr_val,
                "en": (row.get("en") or "").strip(),
                "ar": (row.get("ar") or "").strip(),
                "lg1": (row.get("lg1") or "").strip(),
                "lg2": (row.get("lg2") or "").strip(),
                "context": (row.get("context") or "").strip(),
                "updated_at": _now(),
                "updated_by_id": user.get("id"),
                "updated_by_email": user.get("email"),
            }
            await db.i18n_translations.update_one(
                {"key": key}, {"$set": update}, upsert=True,
            )
            upserts += 1
        return {"ok": True, "upserted": upserts, "errors": errors, "errors_count": len(errors)}
