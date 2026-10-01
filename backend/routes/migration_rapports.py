"""Lot 48 — Rapports de sauvegarde ARCHIVÉS, envoi et renvoi à la demande, journal des envois.

Complète routes/migration_programmation.py (rédaction du rapport, envois WhatsApp / e-mail)
et routes/migration_render.py (sauvegardes, collection `migration_jobs`).

1. ARCHIVAGE — collection `migration_rapports` (exclue de la copie vers Atlas), un document
   par rapport :
     id, type (sauvegarde | purge | echec), job_id et prefixe (sauvegarde), programmee,
     cree_le, maj_le, source (automatique | recalcule), sujet, texte (rapport complet),
     donnees (chiffres : statut, durée, collections, documents, fichiers copiés / absents /
     médias ignorés / vraies erreurs, taille, préfixe, purge, prochaine exécution),
     important, non_envoye (motif quand le rapport automatique n'a pas été demandé),
     envois (journal, voir 3), a_verifier (WhatsApp accepté par Meta, issue encore inconnue).
   Rapport d'une sauvegarde : id = « sauvegarde-<id de la sauvegarde> » (un seul par sauvegarde).
   Une sauvegarde plus ancienne, sans rapport archivé, a son rapport RECALCULÉ à la volée depuis
   son document de suivi (même fonction de rédaction), puis archivé dès qu'on l'ouvre (si elle
   est finie) ; le résultat d'envoi du lot 47 (`rapport` du suivi) est repris dans le journal.

2. ENVOI / RENVOI À LA DEMANDE (Admin uniquement) — canal WhatsApp, e-mail ou les deux,
   destinataires pré-remplis (destinataires du prochain rapport) et modifiables.
   WhatsApp : texte libre si le destinataire a écrit depuis moins de 24 h, sinon le modèle Meta
   réglé (ou un autre modèle choisi) ; e-mail : SMTP existant (HTML lisible + texte).

3. JOURNAL DES ENVOIS (`envois`, 200 lignes au plus par rapport) : date, auteur (auto ou
   e-mail de l'admin), canal, destinataire, mode (texte / modèle + nom / smtp), résultat, code
   et message d'erreur Meta avec leur explication en clair (131042 : paiement du compte
   WhatsApp Business...). Meta accepte souvent un modèle puis le refuse plus tard (statut
   « failed » reçu par le webhook) : ces WhatsApp restent « à vérifier » 72 h ; leur issue est
   relue dans `whatsapp_messages` / `wa_pending_statuses` (planificateur et ouverture du
   rapport). Si TOUS les WhatsApp d'un envoi AUTOMATIQUE sont finalement refusés et qu'aucun
   e-mail n'est parti, l'e-mail de repli est tenté et noté.

  GET  /api/admin/migration/rapports                    résumés (badges de l'Historique)
  GET  /api/admin/migration/rapports/destinataires      destinataires par défaut et leur source
  GET  /api/admin/migration/rapports/{ident}            rapport complet + journal
                                                        (ident = id du rapport ou de la sauvegarde)
  POST /api/admin/migration/rapports/{ident}/envoyer    envoi / renvoi à la demande
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_admin
from routes import migration_programmation as mp
from routes import migration_render as mr

router = APIRouter(prefix="/admin/migration/rapports", tags=["Migration vers Render"])

ENVOIS_MAX = 200  # lignes de journal gardées par rapport
VERIFICATION_MAX = timedelta(hours=72)  # au-delà, l'issue d'un WhatsApp accepté n'est plus recherchée
LISTE_MAX = 100  # résumés renvoyés pour l'Historique
# Projection du suivi d'une sauvegarde utile au rapport (sans les listes volumineuses ni les secrets)
PROJECTION_JOB = {"_id": 0, "secrets_chiffres": 0, "echecs_fichiers": 0, "absents_fichiers": 0,
                  "resultats_collections": 0}


def _id_sauvegarde(job_id: str) -> str:
    return f"sauvegarde-{job_id}"


# ---------------------------------------------------------------------------
# Données chiffrées des rapports (gardées à côté du texte)
# ---------------------------------------------------------------------------
def _resume_purge(purge: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not purge:
        return None
    if purge.get("erreur"):
        return {"erreur": purge["erreur"]}
    return {"supprimees": [s.get("prefixe") for s in purge.get("supprimees") or []],
            "objets": purge.get("objets", 0), "octets": purge.get("octets", 0),
            "erreurs": purge.get("erreurs", 0), "gardees": purge.get("gardees", 0)}


def donnees_sauvegarde(job: Dict[str, Any], purge: Optional[Dict[str, Any]],
                       prochaine: Optional[str]) -> Dict[str, Any]:
    """Chiffres d'une sauvegarde (mêmes champs que le texte du rapport)."""
    opts, cible = job.get("options") or {}, job.get("cible") or {}
    debut, fin = mp._lire_date(job.get("debut")), mp._lire_date(job.get("fin"))
    octets = int(job.get("octets_archives") or 0) + int(job.get("octets_fichiers") or 0)
    return {
        "statut": job.get("statut"), "statut_texte": mp.STATUTS_TEXTE.get(job.get("statut"), job.get("statut")),
        "programmee": bool(job.get("programmee")), "lance_par": job.get("lance_par"),
        "debut": job.get("debut"), "fin": job.get("fin"),
        "duree_s": int((fin - debut).total_seconds()) if debut and fin else None,
        "duree": mp._duree(job.get("debut"), job.get("fin")),
        "base": bool(opts.get("base")), "fichiers": bool(opts.get("fichiers")), "medias": opts.get("medias"),
        "collections_faites": job.get("collections_faites", 0), "collections_total": job.get("collections_total", 0),
        "documents_copies": job.get("documents_copies", 0), "fichiers_total": job.get("fichiers_total", 0),
        "fichiers_copies": job.get("fichiers_copies", 0), "fichiers_absents": job.get("fichiers_absents", 0),
        "fichiers_medias_ignores": job.get("fichiers_medias_ignores", 0),
        "fichiers_echecs": job.get("fichiers_echecs", 0), "references_ignorees": job.get("references_ignorees"),
        "octets": octets, "taille": mp._taille(octets),
        "bucket": cible.get("r2_bucket"), "prefixe": cible.get("prefixe"),
        "purge": _resume_purge(purge), "purgee": bool(job.get("purgee")), "purgee_le": job.get("purgee_le"),
        "prochaine_execution": prochaine,
    }


def donnees_echec(erreur: str, debut: datetime, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Chiffres d'une sauvegarde programmée qui n'a pas pu démarrer."""
    return {"statut": "ECHEC", "statut_texte": mp.STATUTS_TEXTE["ECHEC"], "programmee": True,
            "debut": mp._iso(debut), "erreur": erreur[:300], "prochaine_execution": cfg.get("prochaine_execution")}


def donnees_purge(resultat: Dict[str, Any]) -> Dict[str, Any]:
    """Chiffres d'une purge (« Purger maintenant »)."""
    return {"le": resultat.get("le"), "bucket": resultat.get("bucket"), "examinees": resultat.get("examinees"),
            **(_resume_purge(resultat) or {}), "raisons": resultat.get("raisons")}


# ---------------------------------------------------------------------------
# Archivage et journal
# ---------------------------------------------------------------------------
async def archiver(type_: str, sujet: str, texte: str, donnees: Dict[str, Any], *,
                   job: Optional[Dict[str, Any]] = None, important: bool = False,
                   maintenant: Optional[datetime] = None, source: str = "automatique") -> Dict[str, Any]:
    """Range (ou met à jour) un rapport dans `migration_rapports` ; son journal est conservé."""
    maintenant = maintenant or mp._maintenant()
    rid = _id_sauvegarde(job["id"]) if job else f"{type_}-{mp._iso(maintenant)[:19].replace(':', '')}-{secrets.token_hex(3)}"
    champs = {"type": type_, "sujet": sujet, "texte": texte, "donnees": donnees, "important": bool(important),
              "source": source, "maj_le": mp._iso(maintenant)}
    if job:
        champs.update(job_id=job["id"], prefixe=(job.get("cible") or {}).get("prefixe"),
                      programmee=bool(job.get("programmee")))
    await mr.db.migration_rapports.update_one(
        {"id": rid}, {"$set": champs, "$setOnInsert": {"cree_le": mp._iso(maintenant), "envois": []}},
        upsert=True)
    if job:
        await mr.db.migration_jobs.update_one({"id": job["id"]}, {"$set": {"rapport_archive": True}})
    return {"id": rid, **champs}


def _sujet_sauvegarde(job: Dict[str, Any]) -> str:
    genre = "programmée" if job.get("programmee") else "manuelle"
    return f"Sauvegarde {genre} : {mp.STATUTS_TEXTE.get(job.get('statut'), job.get('statut') or '')}"


async def archiver_sauvegarde(job: Dict[str, Any], purge: Optional[Dict[str, Any]], cfg: Dict[str, Any],
                              prochaine: Optional[str], *, important: bool = False,
                              maintenant: Optional[datetime] = None, recalcule: bool = False) -> Dict[str, Any]:
    """Rédige (texte_rapport_sauvegarde) et archive le rapport d'une sauvegarde."""
    texte = mp.texte_rapport_sauvegarde(job, purge, cfg, prochaine, recalcule=recalcule)
    important = important or job.get("statut") != "TERMINEE"
    return await archiver("sauvegarde", _sujet_sauvegarde(job), texte,
                          donnees_sauvegarde(job, purge, None if recalcule else prochaine), job=job,
                          important=important, maintenant=maintenant,
                          source="recalcule" if recalcule else "automatique")


async def noter_envois(rid: str, lignes: List[Dict[str, Any]], motif: Optional[str] = None) -> None:
    """Ajoute des lignes au journal des envois d'un rapport (200 dernières gardées)."""
    maj: Dict[str, Any] = {}
    if lignes:
        maj["$push"] = {"envois": {"$each": lignes, "$slice": -ENVOIS_MAX}}
        if any(x["canal"] == "whatsapp" and x["etat"] in ("accepte", "envoye") for x in lignes):
            maj["$set"] = {"a_verifier": True}
    elif motif:
        maj["$set"] = {"non_envoye": motif}
    if maj:
        await mr.db.migration_rapports.update_one({"id": rid}, maj)


def _envois_lot47(rapport: Optional[Dict[str, Any]], job: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Résultat d'envoi gardé par le lot 47 dans le suivi -> lignes du journal (reprise)."""
    if not isinstance(rapport, dict) or not (rapport.get("whatsapp") or rapport.get("email")):
        return []
    quand = mp._lire_date(rapport.get("le")) or mp._lire_date(job.get("fin")) or mp._maintenant()
    lot = f"auto-{mp._iso(quand)}"
    lignes = []
    for w in rapport.get("whatsapp") or []:
        code, explication = mp.traduire_erreur_meta(w.get("code"), w.get("erreur"))
        lignes.append(mp._ligne_journal("whatsapp", w.get("a"), "auto", lot, quand,
                                        mode={"modèle": "modele"}.get(w.get("mode"), w.get("mode")),
                                        ok=bool(w.get("ok")), etat="envoye" if w.get("ok") else "echec",
                                        erreur=w.get("erreur"), code=code, explication=explication))
    e = rapport.get("email") or {}
    if e.get("a"):
        lignes.append(mp._ligne_journal("email", e["a"], "auto", lot, quand, mode="smtp", ok=bool(e.get("ok")),
                                        etat="envoye" if e.get("ok") else "echec", erreur=e.get("erreur")))
    return lignes


async def rapport_de(ident: str, maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Rapport archivé (par son id ou celui de sa sauvegarde) ; sinon RECALCULÉ depuis le suivi
    de la sauvegarde, et archivé si elle est finie (sinon rendu « provisoire »). 404 sinon."""
    doc = await mr.db.migration_rapports.find_one({"$or": [{"id": ident}, {"job_id": ident}]}, {"_id": 0})
    if doc:
        return doc
    job = await mr.db.migration_jobs.find_one({"id": ident}, PROJECTION_JOB)
    if not job:
        raise HTTPException(404, "Rapport introuvable")
    cfg = await mp.lire_reglage()
    if job.get("statut") not in mp.FINAUX:
        texte = mp.texte_rapport_sauvegarde(job, None, cfg, None, recalcule=True)
        return {"id": _id_sauvegarde(job["id"]), "type": "sauvegarde", "job_id": job["id"],
                "prefixe": (job.get("cible") or {}).get("prefixe"), "programmee": bool(job.get("programmee")),
                "sujet": _sujet_sauvegarde(job), "texte": texte, "donnees": donnees_sauvegarde(job, None, None),
                "source": "recalcule", "provisoire": True, "envois": []}
    archive = await archiver_sauvegarde(job, None, cfg, None, maintenant=maintenant, recalcule=True)
    await noter_envois(archive["id"], _envois_lot47(job.get("rapport"), job))
    return await mr.db.migration_rapports.find_one({"id": archive["id"]}, {"_id": 0})


# ---------------------------------------------------------------------------
# Issue des WhatsApp acceptés par Meta (statuts reçus par le webhook)
# ---------------------------------------------------------------------------
ETATS_META = {"sent": "envoye", "delivered": "remis", "read": "lu", "failed": "echec"}


async def _statut_meta(message_id: str) -> Optional[Dict[str, Any]]:
    """Dernier statut connu d'un message envoyé (webhook Meta), ou None."""
    projection = {"_id": 0, "wa_status": 1, "wa_error_code": 1, "wa_error_message": 1}
    doc = await mr.db.whatsapp_messages.find_one(
        {"$or": [{"message_id": message_id}, {"wa_message_id": message_id}]}, projection)
    if not (doc and doc.get("wa_status")):
        doc = await mr.db.wa_pending_statuses.find_one({"message_id": message_id}, projection)
    return doc if doc and doc.get("wa_status") else None


async def rapprocher(doc: Dict[str, Any], maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Met à jour le journal d'un rapport avec l'issue connue de ses WhatsApp ; repli e-mail pour un
    envoi automatique dont tous les WhatsApp ont été refusés après coup. -> document à jour."""
    maintenant = maintenant or mp._maintenant()
    envois = list(doc.get("envois") or [])
    change, refuses = False, set()
    for e in envois:
        if e.get("canal") != "whatsapp" or e.get("etat") not in ("accepte", "envoye") or not e.get("message_id"):
            continue
        st = await _statut_meta(e["message_id"])
        etat = ETATS_META.get((st or {}).get("wa_status"))
        if not etat or etat == e["etat"]:
            continue
        change = True
        e["etat"] = etat
        if etat == "echec":
            code, explication = mp.traduire_erreur_meta(st.get("wa_error_code"), st.get("wa_error_message"))
            e.update(ok=False, code=code, explication=explication,
                     erreur=str(st.get("wa_error_message") or "refusé par Meta après envoi")[:300])
            refuses.add(e.get("lot"))
    # Repli e-mail : envoi automatique sans aucun WhatsApp remis ni e-mail tenté
    for lot in refuses:
        du_lot = [e for e in envois if e.get("lot") == lot]
        if not str(lot).startswith("auto") or any(e["ok"] for e in du_lot if e["canal"] == "whatsapp") \
                or any(e["canal"] == "email" for e in du_lot):
            continue
        globaux = await mr.db.settings.find_one({"_id": "global"}) or {}
        for adresse in mp.destinataires_rapport(globaux, await mp.lire_reglage())["emails"]:
            envois.append(await mp.envoyer_email(adresse, doc.get("sujet") or "Rapport de sauvegarde",
                                                 doc.get("texte") or "", par="auto (repli)", lot=lot,
                                                 maintenant=maintenant))
    limite = mp._iso(maintenant - VERIFICATION_MAX)
    a_verifier = any(e.get("canal") == "whatsapp" and e.get("etat") in ("accepte", "envoye") and e.get("message_id")
                     and (e.get("le") or "") >= limite for e in envois)
    if change or a_verifier != bool(doc.get("a_verifier")):
        await mr.db.migration_rapports.update_one({"id": doc["id"]}, {"$set": {"envois": envois[-ENVOIS_MAX:],
                                                                             "a_verifier": a_verifier}})
    return {**doc, "envois": envois[-ENVOIS_MAX:], "a_verifier": a_verifier}


async def verifier_envois_en_attente(maintenant: Optional[datetime] = None, limite: int = 20) -> int:
    """Passage du planificateur : rapports dont un WhatsApp attend encore son issue."""
    docs = await mr.db.migration_rapports.find({"a_verifier": True}, {"_id": 0}).to_list(limite)
    for doc in docs:
        await rapprocher(doc, maintenant)
    return len(docs)


# ---------------------------------------------------------------------------
# Badge de l'Historique (dernier envoi)
# ---------------------------------------------------------------------------
def badge(envois: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Résumé du DERNIER envoi (même lot) : jamais | whatsapp | email | echec | attente."""
    if not envois:
        return {"etat": "jamais", "libelle": "jamais envoyé"}
    lot = envois[-1].get("lot")
    dernier = [e for e in envois if e.get("lot") == lot]
    wa = [e for e in dernier if e["canal"] == "whatsapp" and e["ok"]]
    mail = [e for e in dernier if e["canal"] == "email" and e["ok"]]
    echecs = [e for e in dernier if not e["ok"]]
    resume = {"le": envois[-1].get("le"), "par": envois[-1].get("par"), "echecs": len(echecs),
              "erreur": next((e.get("explication") or e.get("erreur") for e in echecs), None)}
    if wa and all(e["etat"] == "accepte" for e in wa) and not mail:
        return {**resume, "etat": "attente", "libelle": "WhatsApp accepté par Meta (remise non confirmée)"}
    if wa:
        return {**resume, "etat": "whatsapp", "libelle": "envoyé WhatsApp" + (" + e-mail" if mail else "")}
    if mail:
        return {**resume, "etat": "email", "libelle": "envoyé e-mail"}
    return {**resume, "etat": "echec", "libelle": "échec d'envoi"}


def _public(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {**{k: v for k, v in doc.items() if k != "_id"}, "badge": badge(doc.get("envois") or [])}


# ---------------------------------------------------------------------------
# Routes (Admin uniquement)
# ---------------------------------------------------------------------------
class EnvoiIn(BaseModel):
    canal: str = Field("whatsapp", pattern="^(whatsapp|email|les_deux)$")
    numeros: Union[List[str], str] = Field(default_factory=list)
    emails: Union[List[str], str] = Field(default_factory=list)
    modele: str = Field("", max_length=120)  # vide = modèle réglé dans le bloc
    langue: str = Field("", max_length=12)
    forcer_modele: bool = False  # modèle même si la fenêtre de 24 h est ouverte


async def _destinataires(maintenant: datetime) -> Dict[str, Any]:
    """Destinataires par défaut (ceux du prochain rapport), fenêtre de 24 h de chaque numéro et
    modèle Meta réglé : pré-remplissage de la fenêtre « Envoyer »."""
    cfg = await mp.lire_reglage()
    dest = mp.destinataires_rapport(await mr.db.settings.find_one({"_id": "global"}) or {}, cfg)
    dest["fenetres"] = {n: await mp._fenetre_ouverte(n, maintenant) for n in dest["whatsapp"]}
    dest["modele_wa"], dest["modele_wa_langue"] = cfg.get("modele_wa") or "", cfg.get("modele_wa_langue") or "fr"
    return dest


@router.get("")
async def lister_rapports(_: dict = Depends(get_current_admin)):
    """Résumés des derniers rapports (sans le texte) avec le badge du dernier envoi."""
    docs = await mr.db.migration_rapports.find({}, {"_id": 0, "texte": 0}).sort("cree_le", -1).to_list(LISTE_MAX)
    sortie = []
    for doc in docs:
        if doc.get("a_verifier"):
            # Document complet (le repli e-mail éventuel a besoin du texte), puis résumé
            complet = await rapprocher(await mr.db.migration_rapports.find_one({"id": doc["id"]}, {"_id": 0}))
            doc = {k: v for k, v in complet.items() if k != "texte"}
        envois = doc.pop("envois", None) or []
        sortie.append({**doc, "nb_envois": len(envois), "badge": badge(envois)})
    return sortie


@router.get("/destinataires")
async def lire_destinataires(_: dict = Depends(get_current_admin)):
    return await _destinataires(mp._maintenant())


@router.get("/{ident}")
async def lire_rapport(ident: str, _: dict = Depends(get_current_admin)):
    """Rapport complet + journal des envois + destinataires par défaut."""
    maintenant = mp._maintenant()
    doc = await rapport_de(ident, maintenant)
    if doc.get("a_verifier"):
        doc = await rapprocher(doc, maintenant)
    return {**_public(doc), "destinataires": await _destinataires(maintenant)}


@router.post("/{ident}/envoyer")
async def envoyer(ident: str, corps: EnvoiIn, admin: dict = Depends(get_current_admin)):
    """Envoi / renvoi à la demande, journalisé (auteur = e-mail de l'admin)."""
    maintenant = mp._maintenant()
    doc = await rapport_de(ident, maintenant)
    if doc.get("provisoire"):
        raise HTTPException(409, "Sauvegarde en cours : le rapport pourra être envoyé une fois terminée")
    numeros = mp.liste_numeros(corps.numeros) if corps.canal in ("whatsapp", "les_deux") else []
    emails = mp.liste_emails(corps.emails) if corps.canal in ("email", "les_deux") else []
    if corps.canal in ("whatsapp", "les_deux") and not numeros:
        raise HTTPException(400, "Indiquez au moins un numéro WhatsApp (indicatif pays + numéro)")
    if corps.canal in ("email", "les_deux") and not emails:
        raise HTTPException(400, "Indiquez au moins une adresse e-mail valide")
    if len(numeros) > mp.DESTINATAIRES_WA_MAX or len(emails) > mp.EMAILS_MAX:
        raise HTTPException(400, f"{mp.DESTINATAIRES_WA_MAX} numéros et {mp.EMAILS_MAX} e-mails au plus")
    cfg = await mp.lire_reglage()
    modele = corps.modele.strip() or cfg.get("modele_wa") or ""
    langue = corps.langue.strip() or (cfg.get("modele_wa_langue") or "fr")
    par, lot = admin.get("email") or "admin", f"admin-{mp._iso(maintenant)}"
    lignes = []
    for numero in numeros:
        lignes.append(await mp.envoyer_wa(numero, doc["texte"], modele=modele, langue=langue, par=par, lot=lot,
                                          maintenant=maintenant, forcer_modele=corps.forcer_modele))
    for adresse in emails:
        lignes.append(await mp.envoyer_email(adresse, doc.get("sujet") or "Rapport de sauvegarde", doc["texte"],
                                             par=par, lot=lot, maintenant=maintenant))
    await noter_envois(doc["id"], lignes)
    doc = await mr.db.migration_rapports.find_one({"id": doc["id"]}, {"_id": 0})
    return {**_public(doc), "resultats": lignes, "destinataires": await _destinataires(maintenant)}
