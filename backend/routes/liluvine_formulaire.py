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

Lot 37 :
  - JOURNAL pour l'Admin et le Superviseur : chaque commande (y compris refus et mode
    d'emploi) avec date/heure, numéro, nom du contact, référence du formulaire, livré ou
    non, erreurs, et « intervention humaine requise » (message non délivré, erreur
    technique, paiement reçu mais liens non délivrés…) avec « Renvoyer les liens » et
    « Marquer traité » ;
  - SONDAGE DE SATISFACTION envoyé au contact une fois le formulaire livré (sondage
    WhatsApp choisi par l'Admin ou le Superviseur, lien personnel /s/<jeton>), puis
    RELANCES tant qu'il n'a pas répondu (délai et nombre réglables ; WhatsApp, repli SMS).

Collections : liluvine_formulaires (une commande par document reçu), payment_links
(champ liluvine_formulaire_id), forms (champs liluvine_*), form_submissions.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
import secrets
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
# Lot 37 — sondage de satisfaction après livraison (réglages dans settings « global »)
CLE_SONDAGE, CLE_DELAI, CLE_RELANCES = ("liluvine_formulaire_sondage_id", "liluvine_formulaire_relance_heures",
                                        "liluvine_formulaire_relances_max")
DELAI_PAR_DEFAUT, RELANCES_PAR_DEFAUT = 24, 2
PERIODE_RELANCES = 30 * 60                                    # vérification des relances toutes les 30 min
ROLES_CLIENTS = ["client", "pharmacien", "medecin", "regulateur", "editeur_vidal", "moderateur", "moderator"]
MODE_EMPLOI = ("📝 *Commande !formulaire*\n"
               "Envoyez-moi votre questionnaire en pièce jointe (Word, Excel, PDF ou photo) avec la légende "
               "*!formulaire*. Je le transforme en formulaire en ligne à faire remplir, avec un lien sécurisé.")


class Reponse(BaseModel):
    data: Dict[str, Any] = Field(default_factory=dict)
    geo: Optional[Dict[str, Any]] = None
    respondent_name: Optional[str] = None
    respondent_email: Optional[str] = None


class ParametresSondage(BaseModel):
    sondage_id: Optional[str] = None                   # None : pas de sondage après livraison
    relance_heures: int = Field(DELAI_PAR_DEFAUT, ge=1, le=24 * 30)
    relances_max: int = Field(RELANCES_PAR_DEFAUT, ge=0, le=10)


class NoteIntervention(BaseModel):
    note: Optional[str] = Field(None, max_length=500)


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
                                      mnos: List[str], secret: str, analyser=None, sms_send=None,
                                      dormir=asyncio.sleep) -> Dict[str, Any]:
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

    async def _repondre(numero: str, texte: str) -> bool:
        """Envoie un message WhatsApp ; renvoie True s'il est parti (pour le journal)."""
        try:
            res = await wa_send_text(numero, texte)
            return not isinstance(res, dict) or bool(res.get("ok", True))
        except Exception:  # noqa: BLE001
            logger.warning("[!formulaire] réponse WhatsApp impossible", exc_info=True)
            return False

    async def _evenement(cmd_id: str, etape: str, detail: str = "", ok: bool = True) -> None:
        """Lot 37 — ligne du journal de la commande (50 dernières)."""
        await db.liluvine_formulaires.update_one({"id": cmd_id}, {
            "$push": {"journal": {"$each": [{"le": _now(), "etape": etape, "detail": detail[:300], "ok": ok}],
                                  "$slice": -50}},
            "$set": {"maj_le": _now()}})

    async def _intervention(cmd_id: str, motif: str) -> None:
        """Lot 37 — signale qu'une intervention humaine est nécessaire."""
        await db.liluvine_formulaires.update_one({"id": cmd_id}, {"$set": {
            "intervention_requise": True, "intervention_motif": motif, "intervention_le": _now(),
            "intervention_faite_le": None, "intervention_par": None}})
        await _evenement(cmd_id, "intervention", motif, ok=False)

    async def _nouvelle(from_num: str, profile_name: Optional[str], statut: str, **extra) -> dict:
        """Lot 37 — toute commande entre au journal, même un refus ou un simple mode d'emploi."""
        cmd = {"id": uuid_fn(), "telephone": from_num, "chiffres": "".join(ch for ch in from_num if ch.isdigit()),
               "nom_contact": profile_name, "statut": statut, "cree_le": _now(), "livre": False,
               "intervention_requise": False, "journal": [], **extra}
        await db.liluvine_formulaires.insert_one(cmd.copy())
        return cmd

    async def _message(cmd: dict, texte: str, etape: str, motif_si_echec: Optional[str]) -> bool:
        """Envoie au contact, trace au journal ; échec → intervention humaine (si motif donné)."""
        ok = await _repondre(cmd["telephone"], texte)
        await _evenement(cmd["id"], etape, "message WhatsApp envoyé" if ok else "message WhatsApp NON délivré", ok)
        if not ok and motif_si_echec:
            await _intervention(cmd["id"], motif_si_echec)
        return ok

    # --- 1. Commande reçue ----------------------------------------------------------
    async def commande(*, from_num: str, profile_name: Optional[str], mtype: str, media_info: Optional[dict],
                       nom_fichier: Optional[str], compte_par_defaut: Optional[str]) -> Dict[str, Any]:
        """Message « !formulaire » reçu (texte seul, document ou photo). Répond toujours au contact."""
        chiffres = "".join(ch for ch in from_num if ch.isdigit())
        if mtype == "text":
            cmd = await _nouvelle(from_num, profile_name, "mode_emploi")
            await _message(cmd, MODE_EMPLOI, "mode_emploi", None)
            return {"ok": True, "etape": "mode_emploi"}
        if mtype not in ("document", "image") or not media_info:
            motif = ("je n'ai pas pu récupérer votre pièce jointe, renvoyez-la" if mtype in ("document", "image")
                     else "seuls les documents Word, Excel, PDF et les photos sont acceptés")
            cmd = await _nouvelle(from_num, profile_name, "refuse", erreur=motif)
            await _message(cmd, f"❌ Impossible de traiter votre demande : {motif}.\n\n{MODE_EMPLOI}", "refus",
                           "Refus non délivré au contact : le prévenir")
            return {"ok": False, "etape": "refus", "motif": motif}
        mime = (media_info.get("mime_type") or "").split(";")[0].strip().lower()
        ext = EXT_PAR_MIME.get(mime) or (nom_fichier.rsplit(".", 1)[-1].lower() if nom_fichier and "." in nom_fichier else "")
        nom = nom_fichier if nom_fichier and nom_fichier.lower().endswith("." + ext) else f"document.{ext or 'inconnu'}"
        try:
            imp.verifier_fichier(nom)                     # refus immédiat : .doc, .xls, format inconnu…
        except ValueError as exc:
            cmd = await _nouvelle(from_num, profile_name, "refuse", fichier=nom, erreur=str(exc))
            await _message(cmd, f"❌ Impossible de traiter votre document : {exc}", "refus",
                           "Refus non délivré au contact : le prévenir")
            return {"ok": False, "etape": "refus", "motif": str(exc)}
        qui = await _type_client(chiffres)
        cmd = await _nouvelle(from_num, profile_name, "analyse", type_client=qui["type"],
                              compte_id=qui["compte_id"] or compte_par_defaut, compte_libelle=qui["libelle"], fichier=nom)
        await _evenement(cmd["id"], "reçu", f"{nom} ({qui['type']})")
        await _message(cmd, "📄 Document reçu. Je prépare votre formulaire, cela prend environ une minute…",
                       "accusé de réception", None)
        try:
            data = lire_media(media_info)
        except Exception:  # noqa: BLE001
            await _echec(cmd, "le fichier reçu n'a pas pu être lu, renvoyez-le", technique=True)
            return {"ok": False, "etape": "refus"}
        tache = asyncio.create_task(_traiter(cmd, nom, data))
        taches.add(tache)
        tache.add_done_callback(taches.discard)
        return {"ok": True, "etape": "analyse", "commande_id": cmd["id"], "tache": tache}

    async def _echec(cmd: dict, motif: str, technique: bool = False) -> None:
        """Erreur : le contact reçoit le motif. Erreur technique (pas de sa faute) → intervention humaine."""
        await db.liluvine_formulaires.update_one({"id": cmd["id"]}, {"$set": {"statut": "erreur", "erreur": motif,
                                                                            "maj_le": _now()}})
        await _evenement(cmd["id"], "erreur", motif, ok=False)
        await _message(cmd, f"❌ Je n'ai pas pu créer le formulaire : {motif}\n\n{MODE_EMPLOI}", "motif envoyé",
                       "Erreur non délivrée au contact : le prévenir")
        if technique:
            await _intervention(cmd["id"], f"Erreur technique : {motif} — relancer le traitement ou créer le "
                                            "formulaire à la main")

    # --- 2. Analyse, création du formulaire privé, tarif et lien de paiement --------
    async def _traiter(cmd: dict, nom: str, data: bytes) -> None:
        try:
            res = await analyser([(nom, data)], "formulaire", None, uuid_fn, avec_donnees=False)
        except ValueError as exc:
            await _echec(cmd, str(exc))
            return
        except Exception:  # noqa: BLE001
            logger.exception("[!formulaire] analyse impossible %s", cmd["id"])
            await _echec(cmd, "le service d'analyse est momentanément indisponible, réessayez dans quelques minutes.",
                         technique=True)
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
            "statut": "en_attente_paiement", "maj_le": _now(),
            "reference": f"{form['number']} · {titre}"}})
        await _evenement(cmd["id"], "formulaire créé", f"{form['number']} · {titre} — {len(champs)} champ(s)")
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
            await _echec(cmd, "le lien de paiement n'a pas pu être créé, réessayez dans quelques minutes.",
                         technique=True)
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
        await _message(cmd, (
            f"{resume}\n\n💰 Tarif : *{prix_lisible(prix)} FCFA*"
            f"\nPayez par Mobile Money (Orange, Moov, Telecel) : {_base()}/pay/{slug}\n"
            "Dès que le paiement est confirmé, je vous envoie le lien sécurisé du formulaire à faire remplir."),
            f"tarif {prix_lisible(prix)} FCFA + lien de paiement",
            "Tarif et lien de paiement non délivrés : les envoyer au contact")

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
        await db.liluvine_formulaires.update_one({"id": commande_id}, {"$set": {"expire_le": expire.isoformat()}})
        await _evenement(commande_id, "mis en ligne", "paiement confirmé" if cmd.get("prix_xof") else "service gratuit")
        if await _envoyer_liens(cmd, expire, premier_envoi=True):
            await _envoyer_sondage(cmd)
        return True

    async def _envoyer_liens(cmd: dict, expire: datetime, premier_envoi: bool) -> bool:
        """Envoie les liens cryptés ; « livré » si le message est parti, sinon intervention humaine."""
        saisie = f"{_base()}/fr/{_jeton('form_fill', cmd['form_id'], expire)}"
        reponses = f"{_base()}/fr-resultats/{_jeton('form_results', cmd['form_id'], expire)}"
        entete = ((f"🎉 Paiement reçu, merci ! " if cmd.get("prix_xof") else "🎉 ")
                  + f"Votre formulaire *{cmd.get('titre')}* est en ligne.") if premier_envoi else \
            f"🔁 Voici à nouveau les liens de votre formulaire *{cmd.get('titre')}*."
        ok = await _message(cmd, (
            f"{entete}\n\n🔗 Lien à partager pour le faire remplir :\n{saisie}\n\n"
            f"📊 Vos réponses (lien privé, ne le partagez pas) :\n{reponses}\n\n"
            f"Liens valables jusqu'au {expire.strftime('%d/%m/%Y')}."),
            "liens envoyés" if premier_envoi else "liens renvoyés",
            "Formulaire payé et en ligne, mais les liens n'ont pas été délivrés : utiliser « Renvoyer les liens »")
        if ok:
            await db.liluvine_formulaires.update_one({"id": cmd["id"]}, {"$set": {"livre": True, "livre_le": _now()}})
        return ok

    async def renvoyer_liens(commande_id: str) -> bool:
        cmd = await db.liluvine_formulaires.find_one({"id": commande_id, "statut": "publie"}, {"_id": 0})
        if not cmd:
            raise HTTPException(status_code=400, detail="Seul un formulaire en ligne peut avoir ses liens renvoyés")
        expire = datetime.fromisoformat(cmd["expire_le"])
        if expire <= datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="Les liens de ce formulaire ont expiré")
        ok = await _envoyer_liens(cmd, expire, premier_envoi=False)
        if ok and not (cmd.get("sondage") or {}).get("invite_id"):
            await _envoyer_sondage(cmd)
        return ok

    # --- Lot 37 : sondage de satisfaction après livraison, avec relances ------------
    async def parametres_sondage() -> Dict[str, Any]:
        g = await db.settings.find_one({"_id": "global"}, {"_id": 0, CLE_SONDAGE: 1, CLE_DELAI: 1, CLE_RELANCES: 1}) or {}
        sid = g.get(CLE_SONDAGE)
        sondage = await db.wa_surveys.find_one({"id": sid}, {"_id": 0, "title": 1, "status": 1}) if sid else None
        return {"sondage_id": sid if sondage else None, "sondage_titre": (sondage or {}).get("title"),
                "sondage_statut": (sondage or {}).get("status"),
                "relance_heures": int(g.get(CLE_DELAI) or DELAI_PAR_DEFAUT),
                "relances_max": int(g.get(CLE_RELANCES) if g.get(CLE_RELANCES) is not None else RELANCES_PAR_DEFAUT)}

    async def _joindre(cmd: dict, texte: str) -> Optional[str]:
        """WhatsApp, puis SMS si WhatsApp refuse (fenêtre de 24 h fermée) ; renvoie le canal utilisé."""
        if await _repondre(cmd["telephone"], texte):
            return "whatsapp"
        if sms_send is not None:
            try:
                res = await sms_send(cmd["telephone"], texte)
                if res.get("ok"):
                    return "sms"
            except Exception:  # noqa: BLE001
                logger.warning("[!formulaire] SMS du sondage impossible", exc_info=True)
        return None

    async def _envoyer_sondage(cmd: dict) -> None:
        p = await parametres_sondage()
        if not p["sondage_id"]:
            return                                          # aucun sondage choisi
        if p["sondage_statut"] == "closed":
            await _evenement(cmd["id"], "sondage", f"« {p['sondage_titre']} » est clôturé : non envoyé", ok=False)
            return
        survey = await db.wa_surveys.find_one({"id": p["sondage_id"]}, {"_id": 0})
        contact_id = f"liluvine:{cmd['chiffres']}"
        inv = await db.wa_survey_invites.find_one({"survey_id": survey["id"], "contact_id": contact_id}, {"_id": 0})
        if not inv:                                         # un lien personnel par contact et par sondage
            inv = {"id": uuid_fn(), "token": secrets.token_urlsafe(9), "survey_id": survey["id"],
                   "contact_id": contact_id, "client_id": survey.get("client_id"),
                   "name": cmd.get("nom_contact") or cmd["telephone"], "company": "", "email": "", "unique_code": "",
                   "phone": cmd["telephone"], "status": "queued", "sent_count": 0, "opened_at": None,
                   "answered_at": None, "campaign_ids": [], "created_at": _now(), "source": "liluvine_formulaire"}
            await db.wa_survey_invites.insert_one(inv.copy())
        if survey.get("status") == "draft":
            await db.wa_surveys.update_one({"id": survey["id"]}, {"$set": {"status": "active", "updated_at": _now()}})
        lien = f"{_base()}/s/{inv['token']}"
        canal = await _joindre(cmd, f"🙏 Merci d'avoir utilisé !formulaire. Votre avis compte : répondez en une minute "
                                    f"à notre sondage « {survey.get('title')} » : {lien}")
        delai = timedelta(hours=p["relance_heures"])
        await db.wa_survey_invites.update_one({"id": inv["id"]}, {
            "$set": {"status": "sent" if canal else "failed", "last_sent_at": _now(), "channel": canal},
            "$inc": {"sent_count": 1 if canal else 0}})
        await db.liluvine_formulaires.update_one({"id": cmd["id"]}, {"$set": {"sondage": {
            "id": survey["id"], "titre": survey.get("title"), "invite_id": inv["id"], "envoye_le": _now(),
            "canal": canal, "relances": 0, "prochaine_relance": (datetime.now(timezone.utc) + delai).isoformat(),
            "repondu": bool(inv.get("answered_at"))}}})
        await _evenement(cmd["id"], "sondage", f"« {survey.get('title')} » envoyé par {canal}" if canal
                         else f"« {survey.get('title')} » NON délivré", ok=bool(canal))

    async def relancer_sondages() -> int:
        """Relance les contacts qui n'ont pas répondu au sondage (délai et nombre réglables)."""
        p = await parametres_sondage()
        maintenant = datetime.now(timezone.utc)
        n = 0
        async for cmd in db.liluvine_formulaires.find({"sondage.repondu": False,
                                                       "sondage.prochaine_relance": {"$lte": maintenant.isoformat()}},
                                                      {"_id": 0}):
            s = cmd["sondage"]
            inv = await db.wa_survey_invites.find_one({"id": s["invite_id"]}, {"_id": 0}) or {}
            if inv.get("answered_at"):
                await db.liluvine_formulaires.update_one({"id": cmd["id"]}, {"$set": {"sondage.repondu": True}})
                await _evenement(cmd["id"], "sondage", "réponse reçue")
                continue
            if s.get("relances", 0) >= p["relances_max"]:
                await db.liluvine_formulaires.update_one({"id": cmd["id"]}, {"$set": {"sondage.prochaine_relance": None}})
                continue
            canal = await _joindre(cmd, f"⏰ Petit rappel : votre avis sur !formulaire nous aide beaucoup. "
                                        f"Répondez au sondage « {s.get('titre')} » : {_base()}/s/{inv.get('token')}")
            await db.liluvine_formulaires.update_one({"id": cmd["id"]}, {"$set": {
                "sondage.relances": s.get("relances", 0) + 1, "sondage.derniere_relance": _now(),
                "sondage.prochaine_relance": (maintenant + timedelta(hours=p["relance_heures"])).isoformat()}})
            await _evenement(cmd["id"], "relance sondage", f"relance n°{s.get('relances', 0) + 1} par {canal}"
                             if canal else f"relance n°{s.get('relances', 0) + 1} NON délivrée", ok=bool(canal))
            n += 1
        return n

    async def boucle_relances() -> None:
        """Tâche de fond (démarrage du serveur) : relances toutes les 30 minutes."""
        while True:
            try:
                await relancer_sondages()
            except Exception:  # noqa: BLE001
                logger.warning("[!formulaire] relances du sondage en échec", exc_info=True)
            await dormir(PERIODE_RELANCES)

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
    async def suivi(filtre: str = "tous", _: dict = Depends(get_admin_or_supervisor)):
        """Journal des commandes « !formulaire » (300 dernières). Filtres : tous, intervention
        (intervention humaine à faire), erreurs, non_livres (formulaire en ligne mais liens non délivrés)."""
        q: Dict[str, Any] = {}
        if filtre == "intervention":
            q = {"intervention_requise": True, "intervention_faite_le": None}
        elif filtre == "erreurs":
            q = {"statut": {"$in": ["erreur", "refuse"]}}
        elif filtre == "non_livres":
            q = {"statut": "publie", "livre": False}
        commandes = await db.liluvine_formulaires.find(q, {"_id": 0, "usage": 0, "compte_rendu": 0}).sort(
            "cree_le", -1).to_list(300)
        a_traiter = await db.liluvine_formulaires.count_documents({"intervention_requise": True,
                                                                   "intervention_faite_le": None})
        return {"tarifs": await tarifs(), "sondage": await parametres_sondage(), "a_traiter": a_traiter,
                "commandes": commandes}

    @api.get("/supervision/liluvine-formulaire/sondages", tags=["Admin"])
    async def sondages_disponibles(_: dict = Depends(get_admin_or_supervisor)):
        """Sondages WhatsApp qu'on peut choisir comme sondage de satisfaction."""
        return await db.wa_surveys.find({"status": {"$ne": "closed"}}, {"_id": 0, "id": 1, "title": 1, "status": 1}).sort(
            "updated_at", -1).to_list(300)

    @api.put("/supervision/liluvine-formulaire/sondage", tags=["Admin"])
    async def regler_sondage(payload: ParametresSondage, _: dict = Depends(get_admin_or_supervisor)):
        """Choix du sondage envoyé après livraison + relances (Admin ET Superviseur)."""
        if payload.sondage_id and not await db.wa_surveys.find_one({"id": payload.sondage_id}, {"_id": 1}):
            raise HTTPException(status_code=404, detail="Sondage introuvable")
        await db.settings.update_one({"_id": "global"}, {"$set": {
            CLE_SONDAGE: payload.sondage_id, CLE_DELAI: payload.relance_heures, CLE_RELANCES: payload.relances_max}},
            upsert=True)
        return await parametres_sondage()

    @api.post("/supervision/liluvine-formulaire/{commande_id}/renvoyer-liens", tags=["Admin"])
    async def action_renvoyer(commande_id: str, qui: dict = Depends(get_admin_or_supervisor)):
        ok = await renvoyer_liens(commande_id)
        if ok:
            await db.liluvine_formulaires.update_one({"id": commande_id, "intervention_requise": True}, {"$set": {
                "intervention_faite_le": _now(), "intervention_par": qui.get("email") or qui["id"],
                "intervention_note": "Liens renvoyés"}})
        return {"ok": ok, "detail": None if ok else "Le message WhatsApp n'est toujours pas délivré"}

    @api.post("/supervision/liluvine-formulaire/{commande_id}/intervention", tags=["Admin"])
    async def action_traite(commande_id: str, payload: NoteIntervention, qui: dict = Depends(get_admin_or_supervisor)):
        r = await db.liluvine_formulaires.update_one({"id": commande_id}, {"$set": {
            "intervention_faite_le": _now(), "intervention_par": qui.get("email") or qui["id"],
            "intervention_note": (payload.note or "").strip() or None}})
        if not r.matched_count:
            raise HTTPException(status_code=404, detail="Commande introuvable")
        await _evenement(commande_id, "intervention faite", (payload.note or "").strip() or "marqué traité")
        return {"ok": True}

    @api.put("/supervision/liluvine-formulaire/tarifs", tags=["Admin"])
    async def modifier_tarifs(payload: Tarifs, _: dict = Depends(get_current_admin)):
        await db.settings.update_one({"_id": "global"}, {"$set": {
            CLES_PRIX["client"]: payload.prix_client_xof, CLES_PRIX["inconnu"]: payload.prix_inconnu_xof}}, upsert=True)
        return await tarifs()

    return {"commande": commande, "apres_paiement": apres_paiement, "publier": publier, "tarifs": tarifs,
            "renvoyer_liens": renvoyer_liens, "relancer_sondages": relancer_sondages, "boucle_relances": boucle_relances}
