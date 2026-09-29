"""Lot 36 — Commande WhatsApp « !formulaire » envoyée à Liluvine.

Parcours :
  1. Le contact envoie à Liluvine un document (Word .docx, Excel .xlsx, PDF) ou une photo
     avec la légende « !formulaire ». Tout numéro WhatsApp peut le faire.
  2. Liluvine accuse réception, puis l'IA en déduit la structure (même module que
     « Créer depuis un document », lot 33). Document illisible ou non pris en charge :
     Liluvine répond au contact avec le MOTIF de l'erreur.
  3. Formulaire créé PRIVÉ, nommé « FORM_<numéro du contact>_<AAAAMMJJ-HHMM> », en
     attente de paiement. Liluvine annonce le TARIF (selon le type de client : client
     SAWALI enregistré ou numéro inconnu, deux montants réglables) et envoie un lien de
     paiement Mobile Money (PawaPay, pré-rempli avec son numéro).
  4. Dès que le paiement est confirmé (webhook PawaPay ou suivi de la page de paiement),
     le formulaire passe en production et Liluvine envoie :
       - le LIEN CRYPTÉ de saisie, à partager : n'importe qui peut remplir le formulaire ;
       - un second lien crypté, privé, pour consulter les réponses (et les télécharger).
     Les deux liens sont valables 30 jours (jeton signé, pas d'identifiant en clair).

Rattachement : client SAWALI enregistré (numéro connu d'un compte client) → son compte ;
sinon → le compte SAWALI qui reçoit les messages WhatsApp. Le formulaire reste privé :
il n'est accessible au public QUE par le lien crypté.

Collections : liluvine_formulaires (une commande par document reçu), payment_links
(champ liluvine_formulaire_id), forms (champs liluvine_*), form_submissions.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

import import_formulaire as imp

logger = logging.getLogger("sawali.liluvine_formulaire")

PRIX_PAR_DEFAUT = {"client": 2000, "inconnu": 3000}          # FCFA, réglables par l'Admin
CLES_PRIX = {"client": "liluvine_formulaire_prix_client_xof", "inconnu": "liluvine_formulaire_prix_inconnu_xof"}
DUREE_LIENS = timedelta(days=30)
DUREE_PAIEMENT = timedelta(days=7)
# Type MIME reçu de WhatsApp → extension attendue par import_formulaire
EXT_PAR_MIME = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
    "application/msword": "doc", "application/vnd.ms-excel": "xls",
}
ROLES_CLIENTS = ["client", "pharmacien", "medecin", "regulateur", "editeur_vidal", "moderateur", "moderator"]
MODE_EMPLOI = ("📝 *Commande !formulaire*\n"
               "Envoyez-moi votre questionnaire en pièce jointe (Word, Excel, PDF ou photo) avec la légende "
               "*!formulaire*. Je le transforme en formulaire en ligne à faire remplir, avec un lien sécurisé.")


class Reponse(BaseModel):
    data: Dict[str, Any] = Field(default_factory=dict)
    geo: Optional[Dict[str, Any]] = None
    respondent_name: Optional[str] = None
    respondent_email: Optional[str] = None


class Tarifs(BaseModel):
    prix_client_xof: int = Field(..., ge=0, le=10_000_000)
    prix_inconnu_xof: int = Field(..., ge=0, le=10_000_000)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def prix_lisible(prix: int) -> str:
    """2500 → « 2 500 » (séparateur des milliers à la française)."""
    return f"{int(prix):,}".replace(",", " ")


def nom_formulaire(chiffres: str, quand: datetime) -> str:
    """« FORM_ » + numéro du contact + date/heure : FORM_22670000001_20260929-1432."""
    return f"FORM_{chiffres}_{quand.strftime('%Y%m%d-%H%M')}"


def attach_liluvine_formulaire_routes(*, api, db, uuid_fn: Callable[[], str], get_admin_or_supervisor, get_current_admin,
                                      wa_send_text, lire_media: Callable[[dict], bytes], public_base_url,
                                      next_form_number, slugify_code, gen_slug: Callable[[int], str],
                                      mnos: List[str], secret: str, analyser=None) -> Dict[str, Any]:
    """Branche les routes et renvoie {commande, apres_paiement} (appelés par le webhook
    WhatsApp et par la confirmation des paiements PawaPay)."""
    import jwt  # PyJWT, déjà utilisé par les liens cryptés du lot 25

    analyser = analyser or imp.analyser
    taches: set = set()

    # --- Outils ---------------------------------------------------------------
    def _base() -> str:
        return (public_base_url(None) or "").rstrip("/")

    def _jeton(action: str, form_id: str, expire: datetime) -> str:
        return jwt.encode({"action": action, "target_id": form_id, "iat": int(datetime.now(timezone.utc).timestamp()),
                           "exp": int(expire.timestamp())}, secret, algorithm="HS256")

    def _lire_jeton(jeton: str, action: str) -> str:
        try:
            claims = jwt.decode(jeton, secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError as exc:
            raise HTTPException(status_code=410, detail="Ce lien a expiré.") from exc
        except jwt.InvalidTokenError as exc:
            raise HTTPException(status_code=404, detail="Lien invalide.") from exc
        if claims.get("action") != action or not claims.get("target_id"):
            raise HTTPException(status_code=404, detail="Lien invalide.")
        return claims["target_id"]

    async def tarifs() -> Dict[str, int]:
        g = await db.settings.find_one({"_id": "global"}, {"_id": 0, **{c: 1 for c in CLES_PRIX.values()}}) or {}
        return {t: int(g.get(c, PRIX_PAR_DEFAUT[t]) or 0) for t, c in CLES_PRIX.items()}

    async def _type_client(chiffres: str) -> Dict[str, Any]:
        """Client SAWALI enregistré (numéro d'un compte client) ou numéro inconnu."""
        # 8 derniers chiffres, quels que soient les espaces ou séparateurs enregistrés (« +226 70 11 22 33 »)
        fin = r"\D*".join(chiffres[-8:]) + r"\D*$"
        compte = await db.users.find_one(
            {"role": {"$in": ROLES_CLIENTS}, "$or": [{"phone": {"$regex": fin}}, {"whatsapp": {"$regex": fin}}]},
            {"_id": 0, "id": 1, "client_id": 1, "parent_client_id": 1, "company": 1, "full_name": 1})
        if compte:
            return {"type": "client", "compte_id": compte.get("parent_client_id") or compte.get("client_id") or compte["id"],
                    "libelle": compte.get("company") or compte.get("full_name")}
        return {"type": "inconnu", "compte_id": None, "libelle": None}

    async def _repondre(numero: str, texte: str) -> None:
        try:
            await wa_send_text(numero, texte)
        except Exception:  # noqa: BLE001
            logger.warning("[!formulaire] réponse WhatsApp impossible", exc_info=True)

    # --- 1. Commande reçue ----------------------------------------------------------
    async def commande(*, from_num: str, profile_name: Optional[str], mtype: str, media_info: Optional[dict],
                       nom_fichier: Optional[str], compte_par_defaut: Optional[str]) -> Dict[str, Any]:
        """Message « !formulaire » reçu (texte seul, document ou photo). Répond toujours au contact."""
        chiffres = "".join(ch for ch in from_num if ch.isdigit())
        if mtype == "text":
            await _repondre(from_num, MODE_EMPLOI)
            return {"ok": True, "etape": "mode_emploi"}
        if mtype not in ("document", "image") or not media_info:
            motif = ("je n'ai pas pu récupérer votre pièce jointe, renvoyez-la" if mtype in ("document", "image")
                     else "seuls les documents Word, Excel, PDF et les photos sont acceptés")
            await _repondre(from_num, f"❌ Impossible de traiter votre demande : {motif}.\n\n{MODE_EMPLOI}")
            return {"ok": False, "etape": "refus", "motif": motif}
        mime = (media_info.get("mime_type") or "").split(";")[0].strip().lower()
        ext = EXT_PAR_MIME.get(mime) or (nom_fichier.rsplit(".", 1)[-1].lower() if nom_fichier and "." in nom_fichier else "")
        nom = nom_fichier if nom_fichier and nom_fichier.lower().endswith("." + ext) else f"document.{ext or 'inconnu'}"
        try:
            imp.verifier_fichier(nom)                     # refus immédiat : .doc, .xls, format inconnu…
        except ValueError as exc:
            await _repondre(from_num, f"❌ Impossible de traiter votre document : {exc}")
            return {"ok": False, "etape": "refus", "motif": str(exc)}
        qui = await _type_client(chiffres)
        cmd = {"id": uuid_fn(), "telephone": from_num, "chiffres": chiffres, "nom_contact": profile_name,
               "type_client": qui["type"], "compte_id": qui["compte_id"] or compte_par_defaut,
               "compte_libelle": qui["libelle"], "fichier": nom, "statut": "analyse", "cree_le": _now()}
        await db.liluvine_formulaires.insert_one(cmd.copy())
        await _repondre(from_num, "📄 Document reçu. Je prépare votre formulaire, cela prend environ une minute…")
        try:
            data = lire_media(media_info)
        except Exception:  # noqa: BLE001
            await _echec(cmd, "le fichier reçu n'a pas pu être lu, renvoyez-le")
            return {"ok": False, "etape": "refus"}
        tache = asyncio.create_task(_traiter(cmd, nom, data))
        taches.add(tache)
        tache.add_done_callback(taches.discard)
        return {"ok": True, "etape": "analyse", "commande_id": cmd["id"], "tache": tache}

    async def _echec(cmd: dict, motif: str) -> None:
        await db.liluvine_formulaires.update_one({"id": cmd["id"]}, {"$set": {"statut": "erreur", "erreur": motif,
                                                                            "maj_le": _now()}})
        await _repondre(cmd["telephone"], f"❌ Je n'ai pas pu créer le formulaire : {motif}\n\n{MODE_EMPLOI}")

    # --- 2. Analyse, création du formulaire privé, tarif et lien de paiement --------
    async def _traiter(cmd: dict, nom: str, data: bytes) -> None:
        try:
            res = await analyser([(nom, data)], "formulaire", None, uuid_fn, avec_donnees=False)
        except ValueError as exc:
            await _echec(cmd, str(exc))
            return
        except Exception:  # noqa: BLE001
            logger.exception("[!formulaire] analyse impossible %s", cmd["id"])
            await _echec(cmd, "le service d'analyse est momentanément indisponible, réessayez dans quelques minutes.")
            return
        structure = res["structure"]
        quand = datetime.now(timezone.utc)
        titre = nom_formulaire(cmd["chiffres"], quand)
        compte = await db.users.find_one({"id": cmd["compte_id"]}, {"_id": 0, "client_code": 1, "company": 1,
                                                                    "full_name": 1}) or {}
        code = compte.get("client_code") or slugify_code(compte.get("company") or compte.get("full_name") or "LIL")
        while await db.forms.find_one({"client_id": cmd["compte_id"], "title": titre}, {"_id": 1}):
            titre += "-2"                                   # deux documents dans la même minute
        numero = await next_form_number(code)
        champs = [c for p in structure["pages"] for c in p["fields"]]
        form = {
            "id": uuid_fn(), "client_id": cmd["compte_id"], "client_code": code, "number": f"FORM-{code}-{numero:04d}",
            "title": titre,
            # Visible par les répondants : le titre lu dans le document, JAMAIS le numéro du demandeur
            # (l'origine est gardée en interne dans imported_from_document / liluvine_commande_id).
            "description": structure.get("title") or "",
            "is_public": False, "category_id": None, "access_client_ids": [], "pages": structure["pages"],
            "created_by_id": "liluvine", "created_by_label": "Liluvine (WhatsApp)",
            "created_at": _now(), "updated_at": _now(), "uses_count": 0,
            "imported_from_document": {"fichiers": [cmd["fichier"]], "liluvine_commande_id": cmd["id"],
                                       "telephone": cmd["telephone"], "le": _now()},
            "liluvine_commande_id": cmd["id"], "liluvine_statut": "en_attente_paiement",
        }
        await db.forms.insert_one(form.copy())
        prix = (await tarifs())[cmd["type_client"]]
        await db.liluvine_formulaires.update_one({"id": cmd["id"]}, {"$set": {
            "form_id": form["id"], "titre": titre, "prix_xof": prix, "champs": len(champs),
            "pages": len(structure["pages"]), "compte_rendu": res["compte_rendu"], "usage": res["usage"],
            "statut": "en_attente_paiement", "maj_le": _now()}})
        resume = (f"✅ Votre formulaire *{titre}* est prêt : {len(champs)} question(s) sur "
                  f"{len(structure['pages'])} page(s).")
        points = [l[2:] for l in res["compte_rendu"].splitlines() if l.startswith("• ")][:5]
        if points:
            resume += "\n\nÀ vérifier :\n" + "\n".join(f"• {p[:160]}" for p in points)
        if prix <= 0:
            await publier(cmd["id"])                        # service gratuit : publication immédiate
            return
        slug = None
        for _ in range(8):                                  # adresse /pay/<slug> libre
            candidat = gen_slug(8)
            if not await db.payment_links.find_one({"slug": candidat}, {"_id": 1}):
                slug = candidat
                break
        if not slug:
            await _echec(cmd, "le lien de paiement n'a pas pu être créé, réessayez dans quelques minutes.")
            return
        lien = {
            "id": uuid_fn(), "slug": slug, "client_id": cmd["compte_id"], "owner_user_id": None, "owner_email": None,
            "owner_label": "Liluvine !formulaire", "label": f"Formulaire {titre}", "amount": float(prix),
            "currency": "XOF", "description": f"Mise en ligne du formulaire {titre}", "allowed_mnos": list(mnos),
            "expires_at": (quand + DUREE_PAIEMENT).isoformat(), "max_uses": 1, "uses_count": 0, "disabled": False,
            "liluvine_formulaire_id": cmd["id"], "prefill_phone": cmd["telephone"],
            "prefill_name": cmd.get("nom_contact") or "", "created_at": _now(), "updated_at": _now(),
        }
        await db.payment_links.insert_one(lien.copy())
        await db.liluvine_formulaires.update_one({"id": cmd["id"]}, {"$set": {"payment_link_id": lien["id"],
                                                                            "payment_link_slug": slug}})
        await _repondre(cmd["telephone"], (
            f"{resume}\n\n💰 Tarif : *{prix_lisible(prix)} FCFA*"
            f"\nPayez par Mobile Money (Orange, Moov, Telecel) : {_base()}/pay/{slug}\n"
            "Dès que le paiement est confirmé, je vous envoie le lien sécurisé du formulaire à faire remplir."))

    # --- 3. Paiement confirmé → mise en production + liens cryptés ------------------
    async def publier(commande_id: str) -> bool:
        """Met le formulaire en production et envoie les liens (une seule fois)."""
        cmd = await db.liluvine_formulaires.find_one_and_update(
            {"id": commande_id, "statut": {"$ne": "publie"}, "form_id": {"$exists": True}},
            {"$set": {"statut": "publie", "publie_le": _now()}})
        if not cmd:
            return False
        expire = datetime.now(timezone.utc) + DUREE_LIENS
        await db.forms.update_one({"id": cmd["form_id"]}, {"$set": {
            "liluvine_statut": "publie", "liluvine_expire_le": expire.isoformat(), "updated_at": _now()}})
        saisie = f"{_base()}/fr/{_jeton('form_fill', cmd['form_id'], expire)}"
        reponses = f"{_base()}/fr-resultats/{_jeton('form_results', cmd['form_id'], expire)}"
        await db.liluvine_formulaires.update_one({"id": commande_id}, {"$set": {"expire_le": expire.isoformat()}})
        await _repondre(cmd["telephone"], (
            f"🎉 Paiement reçu, merci ! Votre formulaire *{cmd.get('titre')}* est en ligne.\n\n"
            f"🔗 Lien à partager pour le faire remplir :\n{saisie}\n\n"
            f"📊 Vos réponses (lien privé, ne le partagez pas) :\n{reponses}\n\n"
            f"Liens valables jusqu'au {expire.strftime('%d/%m/%Y')}."))
        return True

    async def apres_paiement(payment: dict) -> None:
        """Appelé quand un paiement passe à « completed » (webhook PawaPay ou suivi)."""
        if (payment or {}).get("status") != "completed" or not payment.get("payment_link_id"):
            return
        lien = await db.payment_links.find_one({"id": payment["payment_link_id"]}, {"_id": 0, "liluvine_formulaire_id": 1})
        if lien and lien.get("liluvine_formulaire_id"):
            await publier(lien["liluvine_formulaire_id"])

    # --- 4. Pages publiques par lien crypté ---------------------------------------------
    async def _formulaire_publie(form_id: str) -> dict:
        form = await db.forms.find_one({"id": form_id, "liluvine_statut": "publie"}, {"_id": 0})
        if not form:
            raise HTTPException(status_code=404, detail="Ce formulaire n'est pas (ou plus) en ligne.")
        return form

    @api.get("/public/forms/jeton/{jeton}", tags=["Public"])
    async def formulaire_par_jeton(jeton: str):
        form = await _formulaire_publie(_lire_jeton(jeton, "form_fill"))
        # Le nom technique « FORM_<numéro>_<date> » contient le numéro du demandeur : les
        # répondants voient à la place le titre lu dans le document.
        return {"number": form.get("number"), "title": form.get("description") or "Formulaire", "description": "",
                "pages": form.get("pages"), "client_code": form.get("client_code")}

    @api.post("/public/forms/jeton/{jeton}/submission", tags=["Public"])
    async def repondre_par_jeton(jeton: str, payload: Reponse, request: Request):
        form = await _formulaire_publie(_lire_jeton(jeton, "form_fill"))
        ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or (request.client.host if request.client else "")
        doc = {"id": uuid_fn(), "form_id": form["id"], "client_id": form.get("client_id"),
               "user_id": f"anon-{uuid_fn()[:8]}", "data": payload.data, "geo": payload.geo,
               "user_label": (payload.respondent_name or payload.respondent_email or f"Anonyme · {ip}")[:120],
               "respondent_email": payload.respondent_email, "anonymous": True, "source_ip": ip,
               "via": "lien_crypte", "created_at": _now(), "updated_at": _now(), "revisions_count": 1}
        await db.form_submissions.insert_one(doc.copy())
        await db.forms.update_one({"id": form["id"]}, {"$inc": {"uses_count": 1}})
        return {"ok": True, "id": doc["id"]}

    async def _resultats(jeton: str) -> Dict[str, Any]:
        form = await _formulaire_publie(_lire_jeton(jeton, "form_results"))
        champs = [{"id": c["id"], "label": c.get("label"), "type": c.get("type"),
                   "columns": c.get("columns")} for p in form.get("pages") or [] for c in p.get("fields") or []]
        reps = await db.form_submissions.find({"form_id": form["id"]}, {"_id": 0, "user_label": 1, "created_at": 1,
                                                                        "data": 1}).sort("created_at", 1).to_list(5000)
        return {"title": form.get("title"), "number": form.get("number"), "expire_le": form.get("liluvine_expire_le"),
                "champs": champs, "reponses": reps}

    @api.get("/public/forms/resultats/{jeton}", tags=["Public"])
    async def resultats_par_jeton(jeton: str):
        return await _resultats(jeton)

    @api.get("/public/forms/resultats/{jeton}/export.csv", tags=["Public"])
    async def resultats_csv(jeton: str):
        r = await _resultats(jeton)
        sortie = io.StringIO()
        w = csv.writer(sortie, delimiter=";")
        w.writerow(["Date", "Répondant"] + [c["label"] for c in r["champs"]])
        for rep in r["reponses"]:
            ligne = [rep.get("created_at", "")[:16].replace("T", " "), rep.get("user_label", "")]
            for c in r["champs"]:
                v = (rep.get("data") or {}).get(c["id"])
                if isinstance(v, list):
                    v = " | ".join(", ".join(f"{k}: {x}" for k, x in e.items()) if isinstance(e, dict) else str(e) for e in v)
                elif isinstance(v, bool):
                    v = "Oui" if v else "Non"
                elif isinstance(v, str) and v.startswith("data:image"):
                    v = "[signature]"
                ligne.append("" if v is None else str(v))
            w.writerow(ligne)
        return Response(content="﻿" + sortie.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{r["title"]}.csv"'})

    # --- 5. Suivi et tarifs (Admin et Superviseur ; tarifs modifiables par l'Admin) ----------
    @api.get("/supervision/liluvine-formulaire", tags=["Admin"])
    async def suivi(_: dict = Depends(get_admin_or_supervisor)):
        commandes = await db.liluvine_formulaires.find({}, {"_id": 0, "usage": 0, "compte_rendu": 0}).sort(
            "cree_le", -1).to_list(100)
        return {"tarifs": await tarifs(), "commandes": commandes}

    @api.put("/supervision/liluvine-formulaire/tarifs", tags=["Admin"])
    async def modifier_tarifs(payload: Tarifs, _: dict = Depends(get_current_admin)):
        await db.settings.update_one({"_id": "global"}, {"$set": {
            CLES_PRIX["client"]: payload.prix_client_xof, CLES_PRIX["inconnu"]: payload.prix_inconnu_xof}}, upsert=True)
        return await tarifs()

    return {"commande": commande, "apres_paiement": apres_paiement, "publier": publier, "tarifs": tarifs}
