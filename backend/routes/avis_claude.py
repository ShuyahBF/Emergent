# avis_claude.py — Lot 91 : avis de Claude sur les demandes de fonctionnalités reçues au support.
#
# Demande du propriétaire (09/10/2026) :
#   « Quand un client en ligne soumet une requête concernant un ajout ou une correction de module, Liluvine te la
#     transmet, tu analyses la complexité, le temps que ça pourrait prendre et donc sa faisabilité. Ce n'est que
#     quand tu approuves que le message me parvient. »
#   « Dès qu'elle détecte que cela concerne des fonctionnalités d'un logiciel / plateforme / site, elle demande à
#     l'utilisateur de patienter, simule une réflexion, te transmet le message et, dès le retour de ta réponse,
#     elle retourne à l'utilisateur. »
#
# En résumé (pour un développeur WinDev) :
#   1. un message arrive dans un chat du support (Support Loois ou « <plateforme> - Support ») ;
#   2. FILTRE rapide par mots-clés (ajouter, module, écran, corriger, bug…) : sans mot-clé, rien ne se passe ;
#   3. CLASSEMENT par un petit modèle : est-ce une demande d'ajout / de correction de fonctionnalité ?
#   4. si oui : Liluvine écrit « je transmets à l'équipe technique, patientez… » (la « réflexion ») ;
#   5. ANALYSE par Claude : il lit le code du dépôt GitHub de la plateforme (lecture seule, jeton GITHUB_TOKEN
#      saisi sur Render) et rend un avis : verdict, complexité, durée estimée, réponse pour le client ;
#   6. Liluvine envoie la réponse au client dans le même chat ;
#   7. verdict « approuvé » → le PROPRIÉTAIRE est prévenu (chat + e-mail) et décide (accepter / refuser /
#      en attente) dans Paramètres → « 🧠 Avis Claude sur les demandes ». Verdict « à préciser » : Liluvine pose
#      les questions de Claude, la réponse du client relance l'analyse. « Non faisable » : réponse polie au client,
#      demande archivée (consultable), le propriétaire n'est pas dérangé.
#
# Collections : demandes_fonctionnalites (une fiche par demande) ; réglages dans settings {_id: "avis_claude"}.
# Aucun secret n'est stocké ni renvoyé : clé IA (ANTHROPIC_API_KEY) et jeton GitHub (GITHUB_TOKEN) restent dans
# les variables d'environnement.
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx

log = logging.getLogger("sawali.avis_claude")

LILUVINE_ID = "liluvine"
LILUVINE_NOM = "🤖 Liluvine"
MODELE_CLASSEMENT = "claude-haiku-4-5-20251001"     # rapide et économique : « est-ce une demande de fonctionnalité ? »
MODELE_ANALYSE = "claude-sonnet-4-5-20250929"       # analyse du code (modifiable dans les réglages)
TOURS_MAX = 14                                      # nombre maximal d'aller-retours avec les outils GitHub
LECTURE_MAX = 24_000                                # caractères lus au plus par fichier
DELAI_GITHUB = 15
VERDICTS = ("approuve", "a_preciser", "non_faisable")
LIBELLES_VERDICT = {"approuve": "✅ Approuvé", "a_preciser": "❓ À préciser", "non_faisable": "⛔ Non faisable"}
DECISIONS = ("acceptee", "refusee", "en_attente")
LIBELLES_DECISION = {"acceptee": "Acceptée", "refusee": "Refusée", "en_attente": "En attente"}

# Dépôts GitHub par plateforme (code de l'émetteur SAWALI ou « loois ») — modifiables dans les réglages
DEPOTS_DEFAUT: Dict[str, str] = {
    "loois": "ShuyahBF/loois",
    "sawali": "ShuyahBF/emergent",
    "ster": "ShuyahBF/dentalcare",
    "dentalcare": "ShuyahBF/dentalcare",
    "adlyn": "ShuyahBF/telecom-boutique",
    "beauthentik": "ShuyahBF/site-meetafrican",
    "bfmobility": "ShuyahBF/sawali-bfmobility",
    "albarka": "ShuyahBF/albarka-portal",
}

# Mots qui signalent une demande sur une fonctionnalité (filtre avant tout appel au modèle)
_MOTS = re.compile(
    r"\b(ajout\w*|rajout\w*|ajouter|nouvel(le)?s?\s+(module|fonction\w*|écran|ecran|option|champ|colonne|rapport|état|etat|menu|bouton)"
    r"|module\w*|fonctionnalit\w*|fonction\w*|écran\w*|ecran\w*|corrig\w*|correction\w*|bug\w*|bogue\w*|anomalie\w*"
    r"|modifi\w*|amélior\w*|amelior\w*|évolution\w*|evolution\w*|développ\w*|developp\w*|intégr\w*|integr\w*"
    r"|personnalis\w*|paramétr\w*|parametr\w*|impression|imprimer|export\w*|import\w*|statistique\w*|tableau de bord"
    r"|il faudrait|serait[- ]il possible|est[- ]il possible|pouvez[- ]vous (ajouter|faire|prévoir|prevoir|créer|creer))\b",
    re.IGNORECASE)

SYSTEME_CLASSEMENT = (
    "Tu tries les messages reçus au support d'un éditeur de logiciels (SAWALI : Loois, sTer, adLyn, beAuthentik, "
    "bfmobility…). Réponds UNIQUEMENT par un objet JSON : {\"fonctionnelle\": true|false, \"resume\": \"…\"}.\n"
    "fonctionnelle = true si l'utilisateur demande l'AJOUT, la MODIFICATION ou la CORRECTION d'une fonctionnalité, "
    "d'un module, d'un écran, d'un état/rapport ou d'un comportement du logiciel / de la plateforme / du site.\n"
    "fonctionnelle = false pour une question d'utilisation, un problème de connexion, de mot de passe, de matériel, "
    "un paiement, une salutation ou un simple remerciement.\n"
    "resume = la demande reformulée en une phrase (vide si false).")

SYSTEME_ANALYSE = (
    "Tu es Claude, l'ingénieur qui développe les logiciels de SAWALI SMART SYSTEMS (propriétaire : ShuyahBF). "
    "Un client a soumis au support une demande d'ajout ou de correction de fonctionnalité. Liluvine, l'assistante "
    "du support, te la transmet et attend ta réponse pour la donner au client.\n"
    "Ta mission : évaluer la FAISABILITÉ en lisant le code réel du dépôt avec les outils (lister_fichiers, "
    "lire_fichier, chercher_code) : repère les fichiers concernés, la complexité, le temps de développement, les "
    "risques. Reste bref dans tes explorations (quelques lectures ciblées suffisent).\n"
    "Verdicts : « approuve » (faisable et utile : le propriétaire décidera), « a_preciser » (il manque des "
    "informations : pose 1 à 3 questions précises au client), « non_faisable » (impossible, hors périmètre ou "
    "contraire aux règles : explique poliment).\n"
    "Règles : ne promets JAMAIS de date ni d'accord au client (seul le propriétaire décide) ; pas de jargon "
    "technique dans la réponse au client ; français ; aucun secret, aucune donnée personnelle.\n"
    "Termine OBLIGATOIREMENT par un objet JSON seul entre les balises <avis> et </avis> :\n"
    "<avis>{\"verdict\": \"approuve|a_preciser|non_faisable\", \"complexite\": \"faible|moyenne|elevee\", "
    "\"duree_estimee\": \"ex. 2 à 4 heures\", \"resume\": \"la demande en une phrase\", "
    "\"analyse_technique\": \"pour le propriétaire : fichiers/modules touchés, étapes, risques\", "
    "\"questions\": [\"…\"], \"reponse_client\": \"le message que Liluvine enverra au client\"}</avis>")

# Outils de lecture du dépôt proposés à Claude (lecture seule)
OUTILS_GITHUB: List[Dict[str, Any]] = [
    {"name": "lister_fichiers", "description": "Liste les fichiers et dossiers d'un chemin du dépôt ('' = racine).",
     "input_schema": {"type": "object", "properties": {"chemin": {"type": "string"}}, "required": ["chemin"]}},
    {"name": "lire_fichier", "description": "Lit le contenu texte d'un fichier du dépôt (tronqué à 24 000 caractères).",
     "input_schema": {"type": "object", "properties": {"chemin": {"type": "string"}}, "required": ["chemin"]}},
    {"name": "chercher_code", "description": "Recherche un mot ou une expression dans le code du dépôt (noms de fichiers trouvés).",
     "input_schema": {"type": "object", "properties": {"texte": {"type": "string"}}, "required": ["texte"]}},
]

# Gestionnaire WebSocket du chat (renseigné par installer) et tâches de fond en cours
_manager = None
_taches: set = set()


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


# =====================================================================
# Réglages
# =====================================================================
async def reglages(db) -> Dict[str, Any]:
    """Réglages enregistrés (actif, modèle, dépôts, e-mail) complétés par les valeurs par défaut."""
    doc = await db.settings.find_one({"_id": "avis_claude"}, {"_id": 0}) or {}
    return {
        "actif": doc.get("actif", True),
        "modele": (doc.get("modele") or os.environ.get("AVIS_CLAUDE_MODELE") or MODELE_ANALYSE).strip(),
        "depots": {**DEPOTS_DEFAUT, **(doc.get("depots") or {})},
        "email": (doc.get("email") or "").strip(),
    }


def cle_ia_presente() -> bool:
    """Vrai si la clé du fournisseur IA (Anthropic) est configurée."""
    try:
        from ia_client import cle_ia
        return bool(cle_ia("anthropic"))
    except Exception:  # noqa: BLE001
        return False


def jeton_github() -> str:
    """Jeton GitHub en lecture seule (variable GITHUB_TOKEN ou AVIS_CLAUDE_GITHUB_TOKEN) — jamais affiché."""
    return (os.environ.get("AVIS_CLAUDE_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()


def depot_de(regl: Dict[str, Any], code: str) -> str:
    """Dépôt GitHub de la plateforme (code d'émetteur insensible à la casse, sans espaces ni tirets)."""
    cle = re.sub(r"[\s_-]", "", (code or "").lower())
    return (regl.get("depots") or {}).get(cle) or (regl.get("depots") or {}).get((code or "").lower()) or ""


# =====================================================================
# Détection
# =====================================================================
def semble_demande_fonctionnelle(texte: str) -> bool:
    """Filtre rapide (sans IA) : le message contient-il un mot lié aux fonctionnalités ?"""
    return bool(texte) and len(texte.strip()) >= 12 and bool(_MOTS.search(texte))


async def appeler_texte(systeme: str, texte: str, modele: str, max_tokens: int = 400) -> str:
    """Appel simple du modèle (remplacé par une fonction factice dans les tests)."""
    from ia_client import LlmChat, UserMessage, cle_ia
    chat = LlmChat(api_key=cle_ia("anthropic"), session_id=f"avis-claude-{uuid.uuid4().hex[:8]}",
                   system_message=systeme).with_model("anthropic", modele).with_params(max_tokens=max_tokens)
    return (await chat.send_message(UserMessage(text=texte)) or "").strip()


def lire_json(texte: str) -> Dict[str, Any]:
    """Premier objet JSON trouvé dans un texte ({} si illisible)."""
    m = re.search(r"\{.*\}", texte or "", re.DOTALL)
    if not m:
        return {}
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


async def classer(texte: str, contexte: str = "") -> Dict[str, Any]:
    """Classement par le petit modèle → {fonctionnelle: bool, resume: str}."""
    brut = await appeler_texte(SYSTEME_CLASSEMENT,
                               (f"Contexte récent :\n{contexte}\n\n" if contexte else "") + f"Message :\n{texte}",
                               MODELE_CLASSEMENT, 300)
    v = lire_json(brut)
    return {"fonctionnelle": bool(v.get("fonctionnelle")), "resume": str(v.get("resume") or "")[:400]}


# =====================================================================
# Lecture du dépôt GitHub (outils de Claude)
# =====================================================================
async def executer_outil(depot: str, nom: str, entree: Dict[str, Any]) -> str:
    """Exécute un outil de lecture du dépôt et renvoie un texte (message d'erreur lisible en cas d'échec)."""
    if not depot:
        return "Aucun dépôt GitHub n'est associé à cette plateforme : analyse sans le code."
    jeton = jeton_github()
    entetes = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if jeton:
        entetes["Authorization"] = f"Bearer {jeton}"
    base = f"https://api.github.com/repos/{depot}"
    try:
        async with httpx.AsyncClient(timeout=DELAI_GITHUB, headers=entetes) as client:
            if nom == "lister_fichiers":
                chemin = str(entree.get("chemin") or "").strip("/")
                r = await client.get(f"{base}/contents/{chemin}")
                if r.status_code != 200:
                    return f"Lecture impossible ({r.status_code})."
                donnees = r.json()
                if isinstance(donnees, dict):
                    return f"{chemin} est un fichier."
                return "\n".join(f"{'📁' if e.get('type') == 'dir' else '📄'} {e.get('path')}" for e in donnees[:300])
            if nom == "lire_fichier":
                chemin = str(entree.get("chemin") or "").strip("/")
                r = await client.get(f"{base}/contents/{chemin}")
                if r.status_code != 200:
                    return f"Lecture impossible ({r.status_code})."
                donnees = r.json()
                if not isinstance(donnees, dict) or donnees.get("encoding") != "base64":
                    return "Ce chemin n'est pas un fichier texte lisible."
                texte = base64.b64decode(donnees.get("content") or "").decode("utf-8", errors="replace")
                return texte[:LECTURE_MAX] + ("\n… (tronqué)" if len(texte) > LECTURE_MAX else "")
            if nom == "chercher_code":
                q = str(entree.get("texte") or "").strip()[:120]
                if not q:
                    return "Recherche vide."
                r = await client.get("https://api.github.com/search/code", params={"q": f"{q} repo:{depot}", "per_page": 30})
                if r.status_code != 200:
                    return f"Recherche impossible ({r.status_code}) : lister puis lire les fichiers."
                return "\n".join(i.get("path") for i in r.json().get("items", [])) or "Aucun résultat."
    except httpx.HTTPError:
        return "GitHub injoignable pour l'instant."
    return "Outil inconnu."


async def appeler_analyse(systeme: str, texte: str, modele: str, depot: str) -> str:
    """Conversation avec Claude + outils GitHub jusqu'à sa réponse finale (remplacée dans les tests)."""
    from anthropic import AsyncAnthropic
    from ia_client import cle_ia
    client = AsyncAnthropic(api_key=cle_ia("anthropic"))
    messages: List[Dict[str, Any]] = [{"role": "user", "content": texte}]
    outils = OUTILS_GITHUB if depot else []
    for tour in range(TOURS_MAX):
        # Dernier tour : plus d'outils, Claude doit conclure
        params: Dict[str, Any] = {"model": modele, "max_tokens": 4000, "system": systeme, "messages": messages}
        if outils and tour < TOURS_MAX - 1:
            params["tools"] = outils
        rep = await client.messages.create(**params)
        appels = [b for b in rep.content if getattr(b, "type", "") == "tool_use"]
        if not appels:
            return "".join(getattr(b, "text", "") for b in rep.content if getattr(b, "type", "") == "text")
        # Réponse de Claude renvoyée telle quelle (texte + appels d'outils), reconstruite champ par champ
        contenu: List[Dict[str, Any]] = []
        for b in rep.content:
            if getattr(b, "type", "") == "text":
                contenu.append({"type": "text", "text": b.text})
            elif getattr(b, "type", "") == "tool_use":
                contenu.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input or {}})
        messages.append({"role": "assistant", "content": contenu})
        resultats = []
        for appel in appels:
            sortie = await executer_outil(depot, appel.name, appel.input or {})
            resultats.append({"type": "tool_result", "tool_use_id": appel.id, "content": sortie})
        messages.append({"role": "user", "content": resultats})
    return ""


def normaliser_avis(brut: str) -> Dict[str, Any]:
    """Extrait l'avis <avis>{…}</avis> et le rend sûr (verdict connu, textes bornés)."""
    m = re.search(r"<avis>(.*?)</avis>", brut or "", re.DOTALL)
    v = lire_json(m.group(1) if m else brut)
    verdict = v.get("verdict") if v.get("verdict") in VERDICTS else "a_preciser"
    questions = [str(q)[:300] for q in (v.get("questions") or []) if str(q).strip()][:3]
    reponse = str(v.get("reponse_client") or "").strip()
    if not reponse:
        reponse = ("Merci, votre demande a bien été étudiée. Pouvez-vous préciser : " + " ".join(questions)) if questions \
            else "Merci, votre demande a bien été étudiée et transmise au responsable."
    return {
        "verdict": verdict,
        "complexite": str(v.get("complexite") or "")[:20],
        "duree_estimee": str(v.get("duree_estimee") or "")[:80],
        "resume": str(v.get("resume") or "")[:400],
        "analyse_technique": str(v.get("analyse_technique") or "")[:6000],
        "questions": questions,
        "reponse_client": reponse[:1500],
    }


# =====================================================================
# Publication dans le chat (Liluvine parle au client)
# =====================================================================
async def publier(db, demande: Dict[str, Any], texte: str) -> None:
    """Message de Liluvine dans le fil du client (Support Loois ou espace de la plateforme), poussé à l'équipe."""
    from routes import support_loois
    doc = {"id": str(uuid.uuid4()), "client_id": demande["espace"], "sender_id": LILUVINE_ID, "sender_name": LILUVINE_NOM,
           "recipient_id": demande["fil"], "text": texte[:2000], "created_at": _maintenant(), "read_by": [LILUVINE_ID],
           "avis_claude": demande["id"]}
    if demande["source"] == "loois":
        doc["systeme"] = True              # même présentation que les autres messages de Liluvine dans Loois
    await db.internal_chat_messages.insert_one(doc.copy())
    doc.pop("_id", None)
    if _manager is None:
        return
    cibles = set(await support_loois.ids_admins(db))
    if demande["source"] == "loois":
        cibles.add(demande["fil"])         # le poste Loois reçoit le message en direct
    for cible in cibles:
        try:
            await _manager.send_to_user(cible, {"type": "message", "client_id": demande["espace"], "message": doc})
        except Exception:  # noqa: BLE001
            pass


async def prevenir_proprietaire(db, demande: Dict[str, Any]) -> None:
    """Demande approuvée : alerte dans le chat de l'équipe + e-mail au propriétaire."""
    from routes import support_loois
    if _manager is not None:
        for cible in await support_loois.ids_admins(db):
            try:
                await _manager.send_to_user(cible, {"type": "demande_fonctionnalite", "demande": vue(demande)})
            except Exception:  # noqa: BLE001
                pass
    regl = await reglages(db)
    glob = await db.settings.find_one({"_id": "global"}, {"_id": 0, "health_email_to": 1}) or {}
    dest = regl["email"] or (glob.get("health_email_to") or "").strip() or \
        (os.environ.get("SUPER_ADMIN_EMAIL") or "admin@sawalismartsystems.com")
    a = demande.get("avis") or {}
    try:
        from email_service import send_email
        from html import escape
        html = (
            f"<h2 style='font-family:sans-serif'>🧠 Demande approuvée par Claude — {escape(demande['plateforme_nom'])}</h2>"
            f"<p style='font-family:sans-serif'><b>{escape(demande['numero'])}</b> · {escape(demande['demandeur_nom'])}</p>"
            f"<p style='font-family:sans-serif'><b>Demande :</b> {escape(a.get('resume') or demande['texte'])}</p>"
            f"<p style='font-family:sans-serif'><b>Complexité :</b> {escape(a.get('complexite') or '—')} · "
            f"<b>Durée estimée :</b> {escape(a.get('duree_estimee') or '—')}</p>"
            f"<p style='font-family:sans-serif;white-space:pre-wrap'><b>Analyse :</b> {escape(a.get('analyse_technique') or '')}</p>"
            "<p style='font-family:sans-serif'>À vous de décider : SAWALI → Paramètres → « 🧠 Avis Claude sur les demandes ».</p>")
        await send_email(dest, f"[SAWALI] Demande à décider — {demande['numero']} ({demande['plateforme_nom']})", html)
    except Exception:  # noqa: BLE001 — l'alerte du chat suffit si l'e-mail échoue
        log.warning("[avis_claude] e-mail au propriétaire impossible", exc_info=True)


def vue(d: Dict[str, Any]) -> Dict[str, Any]:
    """Fiche affichée dans les Paramètres (sans données internes inutiles)."""
    return {k: d.get(k) for k in ("id", "numero", "source", "plateforme", "plateforme_nom", "depot", "demandeur_nom",
                                  "texte", "statut", "avis", "decision", "decision_par", "decision_le",
                                  "decision_note", "creee_le", "analysee_le", "erreur")}


# =====================================================================
# Traitement d'un message du support
# =====================================================================
async def _numero(db) -> str:
    """Numéro lisible DEM-2026-0001 (compteur annuel)."""
    annee = datetime.now(timezone.utc).year
    c = await db.counters.find_one_and_update({"_id": f"demandes_fonctionnalites_{annee}"}, {"$inc": {"seq": 1}},
                                              upsert=True, return_document=True)
    return f"DEM-{annee}-{int((c or {}).get('seq') or 1):04d}"


async def demande_a_completer(db, espace: str, fil: str) -> Optional[Dict[str, Any]]:
    """Demande du même fil restée « à préciser » depuis moins de 24 h : la réponse du client la complète."""
    limite = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    return await db.demandes_fonctionnalites.find_one(
        {"espace": espace, "fil": fil, "statut": "a_preciser", "analysee_le": {"$gte": limite}},
        {"_id": 0}, sort=[("creee_le", -1)])


async def traiter(db, *, source: str, espace: str, fil: str, plateforme: str, plateforme_nom: str,
                  demandeur_nom: str, texte: str, contexte: str = "") -> bool:
    """Point d'entrée appelé à chaque message d'un client du support.
    Renvoie True si le message est pris en charge comme demande de fonctionnalité (Liluvine ne fait alors pas
    sa réponse habituelle), False sinon."""
    regl = await reglages(db)
    if not regl["actif"] or not cle_ia_presente():
        return False
    # Un simple « ok merci » ne complète pas une demande : au moins 3 mots
    precedente = await demande_a_completer(db, espace, fil) if len(texte.split()) >= 3 else None
    if precedente:
        # Réponse aux questions de Claude : la demande est complétée puis réanalysée
        texte_complet = f"{precedente['texte']}\n\nPrécisions du client : {texte}"
        await db.demandes_fonctionnalites.update_one({"id": precedente["id"]}, {"$set": {
            "texte": texte_complet[:6000], "statut": "analyse"}})
        demande = {**precedente, "texte": texte_complet[:6000], "statut": "analyse"}
    else:
        if not semble_demande_fonctionnelle(texte):
            return False
        try:
            c = await classer(texte, contexte)
        except Exception:  # noqa: BLE001 — classement impossible : Liluvine répond normalement
            log.warning("[avis_claude] classement impossible", exc_info=True)
            return False
        if not c["fonctionnelle"]:
            return False
        demande = {
            "id": str(uuid.uuid4()), "numero": await _numero(db), "source": source, "espace": espace, "fil": fil,
            "plateforme": plateforme, "plateforme_nom": plateforme_nom, "depot": depot_de(regl, plateforme),
            "demandeur_nom": demandeur_nom, "texte": texte[:6000], "resume": c["resume"], "statut": "analyse",
            "creee_le": _maintenant()}
        await db.demandes_fonctionnalites.insert_one(demande.copy())
        demande.pop("_id", None)

    # « Réflexion » : Liluvine fait patienter le client pendant l'analyse
    await publier(db, demande, "Merci pour votre demande 🙏 Je la transmets à notre équipe technique pour étudier sa "
                               "faisabilité. Patientez un instant… ⏳")
    lancer(analyser_et_repondre(db, demande, regl))
    return True


async def analyser_et_repondre(db, demande: Dict[str, Any], regl: Dict[str, Any]) -> None:
    """Analyse par Claude, réponse de Liluvine au client, alerte du propriétaire si approuvée."""
    texte = (f"Plateforme : {demande['plateforme_nom']} (dépôt GitHub : {demande.get('depot') or 'aucun'})\n"
             f"Client : {demande['demandeur_nom']}\n\nDemande du client :\n{demande['texte']}")
    try:
        brut = await appeler_analyse(SYSTEME_ANALYSE, texte, regl["modele"], demande.get("depot") or "")
        if not brut and regl["modele"] != MODELE_ANALYSE:
            brut = await appeler_analyse(SYSTEME_ANALYSE, texte, MODELE_ANALYSE, demande.get("depot") or "")
    except Exception as exc:  # noqa: BLE001
        log.warning("[avis_claude] analyse impossible", exc_info=True)
        await db.demandes_fonctionnalites.update_one({"id": demande["id"]}, {"$set": {
            "statut": "erreur", "erreur": str(exc)[:300], "analysee_le": _maintenant()}})
        await publier(db, demande, "Votre demande est bien enregistrée : l'équipe du support l'étudiera et reviendra "
                                   "vers vous.")
        return
    avis = normaliser_avis(brut)
    statut = {"approuve": "a_decider", "a_preciser": "a_preciser", "non_faisable": "non_faisable"}[avis["verdict"]]
    maj = {"avis": avis, "statut": statut, "analysee_le": _maintenant(), "erreur": None}
    await db.demandes_fonctionnalites.update_one({"id": demande["id"]}, {"$set": maj})
    demande = {**demande, **maj}
    await publier(db, demande, avis["reponse_client"])
    if statut == "a_decider":
        await prevenir_proprietaire(db, demande)


def lancer(coro: Awaitable) -> None:
    """Tâche de fond gardée en mémoire jusqu'à sa fin."""
    tache = asyncio.ensure_future(coro)
    _taches.add(tache)
    tache.add_done_callback(_taches.discard)


# =====================================================================
# Routes (Paramètres → « 🧠 Avis Claude sur les demandes »)
# =====================================================================
def installer(*, router, db, manager, get_current_user) -> None:
    """Routes d'administration ; garde le gestionnaire WebSocket pour les messages de Liluvine."""
    global _manager
    _manager = manager
    from fastapi import Body, Depends, HTTPException
    from routes import support_loois

    async def equipe(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") != "admin" and not support_loois.est_compte_support(user):
            raise HTTPException(status_code=403, detail="Réservé à l'équipe du support")
        return user

    async def admin(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        return user

    @router.get("/admin/avis-claude", tags=["Avis Claude"])
    async def lire_tout(user: dict = Depends(equipe)):
        """Réglages, état des clés (présentes ou non, jamais leur valeur) et demandes récentes."""
        regl = await reglages(db)
        demandes = [vue(d) async for d in db.demandes_fonctionnalites.find({}, {"_id": 0}).sort("creee_le", -1).limit(200)]
        a_decider = sum(1 for d in demandes if d["statut"] == "a_decider")
        return {"reglages": regl, "cle_ia": cle_ia_presente(), "jeton_github": bool(jeton_github()),
                "demandes": demandes, "a_decider": a_decider}

    @router.put("/admin/avis-claude/reglages", tags=["Avis Claude"])
    async def enregistrer(corps: Dict[str, Any] = Body(...), user: dict = Depends(admin)):
        """Activation, modèle, dépôts par plateforme et e-mail d'alerte."""
        maj: Dict[str, Any] = {}
        if "actif" in corps:
            maj["actif"] = bool(corps["actif"])
        if "modele" in corps:
            maj["modele"] = str(corps.get("modele") or "").strip()[:80]
        if "email" in corps:
            maj["email"] = str(corps.get("email") or "").strip()[:200]
        if isinstance(corps.get("depots"), dict):
            depots = {}
            for code, depot in corps["depots"].items():
                depot = str(depot or "").strip()
                if depot and not re.fullmatch(r"[\w.-]+/[\w.-]+", depot):
                    raise HTTPException(status_code=422, detail=f"Dépôt invalide pour {code} (format propriétaire/nom)")
                depots[re.sub(r"[\s_-]", "", str(code).lower())[:40]] = depot
            maj["depots"] = depots
        await db.settings.update_one({"_id": "avis_claude"}, {"$set": maj}, upsert=True)
        return await reglages(db)

    @router.post("/admin/avis-claude/demandes/{did}/decision", tags=["Avis Claude"])
    async def decider(did: str, corps: Dict[str, Any] = Body(...), user: dict = Depends(admin)):
        """Décision du propriétaire ; un message facultatif est transmis au client par Liluvine."""
        decision = str(corps.get("decision") or "")
        if decision not in DECISIONS:
            raise HTTPException(status_code=422, detail="Décision attendue : acceptee, refusee ou en_attente")
        d = await db.demandes_fonctionnalites.find_one({"id": did}, {"_id": 0})
        if not d:
            raise HTTPException(status_code=404, detail="Demande introuvable")
        note = str(corps.get("message_client") or "").strip()[:1500]
        maj = {"decision": decision, "decision_par": user.get("full_name") or user.get("email"),
               "decision_le": _maintenant(), "decision_note": note,
               "statut": {"acceptee": "acceptee", "refusee": "refusee", "en_attente": "a_decider"}[decision]}
        await db.demandes_fonctionnalites.update_one({"id": did}, {"$set": maj})
        if note:
            await publier(db, d, note)
        return vue({**d, **maj})

    @router.post("/admin/avis-claude/demandes/{did}/reanalyser", tags=["Avis Claude"])
    async def reanalyser(did: str, user: dict = Depends(admin)):
        """Relance l'analyse (ex. après avoir ajouté le jeton GitHub ou corrigé le dépôt)."""
        d = await db.demandes_fonctionnalites.find_one({"id": did}, {"_id": 0})
        if not d:
            raise HTTPException(status_code=404, detail="Demande introuvable")
        regl = await reglages(db)
        d["depot"] = depot_de(regl, d.get("plateforme") or "") or d.get("depot") or ""
        await db.demandes_fonctionnalites.update_one({"id": did}, {"$set": {"statut": "analyse", "depot": d["depot"]}})
        lancer(analyser_et_repondre_sans_client(db, d, regl))
        return {"ok": True}


async def analyser_et_repondre_sans_client(db, demande: Dict[str, Any], regl: Dict[str, Any]) -> None:
    """Réanalyse demandée par le propriétaire : l'avis est mis à jour sans réécrire au client."""
    texte = (f"Plateforme : {demande['plateforme_nom']} (dépôt GitHub : {demande.get('depot') or 'aucun'})\n"
             f"Client : {demande['demandeur_nom']}\n\nDemande du client :\n{demande['texte']}")
    try:
        avis = normaliser_avis(await appeler_analyse(SYSTEME_ANALYSE, texte, regl["modele"], demande.get("depot") or ""))
        statut = {"approuve": "a_decider", "a_preciser": "a_preciser", "non_faisable": "non_faisable"}[avis["verdict"]]
        await db.demandes_fonctionnalites.update_one({"id": demande["id"]}, {"$set": {
            "avis": avis, "statut": statut, "analysee_le": _maintenant(), "erreur": None}})
    except Exception as exc:  # noqa: BLE001
        await db.demandes_fonctionnalites.update_one({"id": demande["id"]}, {"$set": {
            "statut": "erreur", "erreur": str(exc)[:300], "analysee_le": _maintenant()}})
