"""Iter38r-fix9a — Liluvine PRO native WhatsApp auto-reply.

Hooked into the WhatsApp Meta webhook (`/api/whatsapp/webhook`). When a new
inbound TEXT message lands, this helper decides whether Liluvine PRO should
answer it automatically (no n8n required) — and if so, generates a reply via
Claude Sonnet (with the same keyword-RAG injection as the chat UI) and pushes
it back via Meta Graph API.

Decision rules (admin-configurable in settings) :
  - Global toggle  : `liluvine_wa_autoreply_enabled` (bool, default False)
  - Allow-list     : `liluvine_wa_autoreply_allow_phones` (list of msisdn digits)
  - Deny-list      : `liluvine_wa_autoreply_deny_phones` (list of msisdn digits)
  - Allow-mode     : `liluvine_wa_autoreply_allow_mode` (`any` | `whitelist`)
  - Schedule       : `liluvine_wa_autoreply_schedule`  ∈
                       `always` | `outside_hours` | `business_hours`
  - Keywords       : `liluvine_wa_autoreply_keywords` (list of triggers; empty=any)
  - Anti-flood     : `liluvine_wa_autoreply_cooldown_seconds` (default 60s)
  - Signature      : `liluvine_wa_autoreply_signature`
                     (default "🤖 Réponse automatique Liluvine PRO")

Anti-flood works per-(client_id, phone_digits) — we store the last reply time
in `liluvine_wa_autoreply_state`.

Every outgoing auto-reply is logged in `liluvine_pro_messages` with
`external_source = "whatsapp_native"` so it appears in the audit history.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from ia_client import cle_ia as _cle_ia  # noqa: E402 — lot 53 : clé du fournisseur IA

logger = logging.getLogger("sawali.liluvine_wa_autoreply")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _norm_keywords(raw: Any) -> List[str]:
    if isinstance(raw, list):
        return [str(x).strip().lower() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        return [p.strip().lower() for p in raw.split(",") if p.strip()]
    return []


def _norm_phones(raw: Any) -> List[str]:
    if isinstance(raw, list):
        return [_digits(x) for x in raw if _digits(x)]
    if isinstance(raw, str):
        return [_digits(p) for p in raw.split(",") if _digits(p)]
    return []


def _hour_in_range(now_h: int, open_h: int, close_h: int) -> bool:
    """Inclusive open / exclusive close. Wraps over midnight if needed."""
    if open_h <= close_h:
        return open_h <= now_h < close_h
    return now_h >= open_h or now_h < close_h  # wraps midnight


def _in_business_window(business_days: Any, open_h: int, close_h: int) -> bool:
    """Jour ouvré (business_days, liste d'entiers 0=lundi comme
    settings.global.business_days) ET heure ouvrée (_hour_in_range).

    Lot Liluvine (2026-09) — corrige un gap trouvé à l'exploration : le
    calendrier des heures ouvrées existant a AUSSI une notion de jours
    (business_days), mais le mode "business_hours"/"outside_hours" de
    l'auto-réponse WA ne vérifiait jusqu'ici QUE l'heure (UTC), jamais le
    jour de la semaine — un tenant en "business_hours" recevait donc des
    réponses automatiques le week-end dès lors que l'heure UTC tombait
    dans la plage horaire configurée."""
    if not isinstance(business_days, list) or not business_days:
        business_days = [0, 1, 2, 3, 4]  # défaut lundi-vendredi, comme server.py
    now_utc = datetime.now(timezone.utc)
    if now_utc.weekday() not in business_days:
        return False
    return _hour_in_range(now_utc.hour, open_h, close_h)


COOLDOWN_MAX_SECONDS = 8      # au-delà, une vraie conversation resterait sans réponse
COOLDOWN_DEFAUT_SECONDS = 5   # réglage absent ou illisible


def delai_anti_repetition(valeur: Any) -> int:
    """Lot 179 — délai (secondes) pendant lequel un même numéro ne reçoit pas deux réponses automatiques.
    Réglage absent / illisible → 5 s ; 0 → aucun délai ; toute valeur est plafonnée à 8 s. Fonction pure."""
    if valeur is None or str(valeur).strip() == "":
        return COOLDOWN_DEFAUT_SECONDS
    try:
        return max(0, min(int(float(str(valeur).strip())), COOLDOWN_MAX_SECONDS))
    except (TypeError, ValueError):
        return COOLDOWN_DEFAUT_SECONDS


def prompt_selon_contrat(settings_doc: Optional[Dict[str, Any]], etat: Optional[str]) -> str:
    """Lot 183 — prompt réglé pour un client dont le contrat est « valide » ou en « retard » / « aucun » ; vide si l'état
    est inconnu ou si le prompt n'est pas rempli (le prompt du compte s'applique alors). Fonction pure."""
    cle = {"valide": "liluvine_wa_client_prompt", "retard": "liluvine_wa_client_retard_prompt",
           "aucun": "liluvine_wa_client_retard_prompt"}.get(str(etat or ""))
    return str((settings_doc or {}).get(cle) or "").strip() if cle else ""


# Lot 191 — signatures de fin de message : lignes commençant par un tiret long (« — visitez notre site … », « — Illiass
# (Commercial), assistant Liluvine 🤖 », « — 🤖 Réponse automatique Liluvine PRO ») et adresses web isolées qui les suivent.
_LIGNE_SIGNATURE = re.compile(
    r"[ \t]*[—–-][ \t]*(?:visitez notre site|.*assistant Liluvine|.*Réponse automatique Liluvine).*", re.IGNORECASE)
_LIGNE_URL = re.compile(r"[ \t]*(?:https?://|www\.)\S+[ \t]*", re.IGNORECASE)


def retirer_signatures_fin(texte: str, signatures: Any = ()) -> str:
    """Lot 191 — retire du texte TOUTES les signatures de fin de message (connues ou reconnaissables) et renvoie le texte nu.
    Avant : les réponses étaient mémorisées AVEC leur signature, rejouées au modèle (lot 182) qui la recopiait dans son
    texte, puis le code l'ajoutait encore : « — visitez notre site » apparaissait 2 ou 3 fois. La signature est ajoutée UNE
    fois, à l'envoi. Fonction pure."""
    t = str(texte or "")
    for sig in signatures or ():
        sig = str(sig or "").strip()
        if sig:
            t = t.replace(sig, "")
    lignes = t.rstrip().split("\n")
    while lignes and (not lignes[-1].strip() or _LIGNE_SIGNATURE.fullmatch(lignes[-1]) or _LIGNE_URL.fullmatch(lignes[-1])):
        lignes.pop()
    return "\n".join(lignes).rstrip()


HISTORIQUE_MAX_MESSAGES = 12      # derniers échanges rejoués au modèle
HISTORIQUE_HEURES = 12            # au-delà, on repart d'une conversation neuve
HISTORIQUE_MAX_CARACTERES = 1200  # par message rejoué


def historique_pour_llm(docs: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Lot 182 — messages déjà échangés (liluvine_pro_messages, du plus ancien au plus récent) mis au format du modèle.
    Avant ce lot, CHAQUE message WhatsApp était traité comme le premier : Liluvine oubliait la question précédente
    (« Quel est le nom de votre logiciel ? » → « Koloko » → nouvelle salutation). Règles : rôles user / assistant seulement,
    texte tronqué, l'historique commence par un message du correspondant, deux messages de même rôle de suite sont fusionnés.
    Fonction pure."""
    sortie: List[Dict[str, str]] = []
    for d in docs or []:
        role = d.get("role")
        texte = str(d.get("content") or "").strip()
        if role == "assistant":
            texte = retirer_signatures_fin(texte)        # lot 191 : sans signature (sinon le modèle la recopie)
        texte = texte[:HISTORIQUE_MAX_CARACTERES]
        if role not in ("user", "assistant") or not texte:
            continue
        if not sortie and role != "user":
            continue                                   # le modèle attend un premier message du correspondant
        if sortie and sortie[-1]["role"] == role:
            sortie[-1]["content"] += "\n" + texte
        else:
            sortie.append({"role": role, "content": texte})
    # l'historique rejoué se termine par une réponse de Liluvine (le nouveau message du correspondant vient ensuite)
    while sortie and sortie[-1]["role"] != "assistant":
        sortie.pop()
    return sortie


def consignes_conversation(offre_connue: bool, texte_regle: Optional[str] = None) -> str:
    """Lots 179/184 — consignes de conduite de la conversation, ajoutées à CHAQUE réponse WhatsApp. Le texte de base est
    RÉGLABLE (`liluvine_wa_consignes_conversation`, vide = texte par défaut) ; seules les phrases sur l'offre du client
    restent ici : offre connue → ne parler que de SES logiciels (et signaler un logiciel absent de l'offre) ; offre inconnue
    → poser une seule question sans énumérer. Fonction pure."""
    from routes.liluvine_pro import DEFAULT_WA_CONSIGNES_CONVERSATION
    texte = "\n\n" + ((texte_regle or "").strip() or DEFAULT_WA_CONSIGNES_CONVERSATION) + "\n"
    if offre_connue:
        texte += ("- Ne parle que des logiciels, produits et services de l'offre de ce client ; s'il n'en a qu'un, "
                  "considère que « mon logiciel » désigne celui-là et passe tout de suite à son problème. Si le client cite un logiciel "
                  "ABSENT de cette offre, dis-lui que tu ne le trouves pas dans son offre, demande-lui de confirmer le nom "
                  "et ne classe pas encore la demande. "
                  "Lot 337 : ne cite JAMAIS un logiciel que le client n'a pas nommé lui-même dans cette conversation, sauf s'il est le seul de l'offre ; "
                  "si l'offre en compte plusieurs et que le message (« Ok », « merci », « la liste »…) ne dit pas lequel, demande-lui de quel logiciel il parle, "
                  "sans en proposer un de toi-même. Un ancien message de l'assistant peut être faux : ne le reprends pas comme un fait.")
    else:
        texte += ("- Si le client dit « mon logiciel » sans le nommer, pose UNE seule question courte (« Quel est le nom de "
                  "votre logiciel ? ») SANS proposer ni énumérer aucun nom de logiciel, même entre parenthèses ; commence "
                  "directement par la question, sans « Bonjour ».")
    return texte


_CHOIX_SEUL = re.compile(r"^\s*(?:n\s*°\s*|no\.?\s*|numero\s*|numéro\s*|choix\s*|option\s*)?(\d{1,2})\s*[.)!]*\s*$", re.IGNORECASE)
_OPTION_NUMEROTEE = re.compile(r"^\s*(\d{1,2})\s*(?:\ufe0f?\u20e3|[.)\-–:])\s*(.+?)\s*$", re.MULTILINE)


def traduire_choix_numerique(text: str, historique: List[Dict[str, str]]) -> str:
    """Lot 185 — le correspondant répond « 2 » à une liste numérotée de Liluvine : on y ajoute l'option choisie, lue dans
    le dernier message de Liluvine (« 2 (option 2 : Comptabilité) »). Sans liste numérotée ou numéro inconnu, le texte est
    rendu tel quel. Fonction pure."""
    m = _CHOIX_SEUL.match(text or "")
    if not m:
        return text
    dernier = next((x["content"] for x in reversed(historique or []) if x.get("role") == "assistant"), "")
    options = {int(n): re.sub(r"[*_`]", "", lib).strip() for n, lib in _OPTION_NUMEROTEE.findall(dernier)}
    libelle = options.get(int(m.group(1)))
    return f"{text.strip()} (option {int(m.group(1))} : {libelle})" if libelle else text


def requete_recherche(text: str, historique: List[Dict[str, str]]) -> str:
    """Lot 184 — texte envoyé à la base de connaissances (Qdrant) : le message du correspondant PRÉCÉDÉ de ses deux messages
    précédents. Un message court comme « Koloko » ou « Historique » ne retrouve rien seul ; avec la question d'avant, oui.
    Fonction pure."""
    avant = [m["content"] for m in (historique or []) if m.get("role") == "user"][-2:]
    return " ".join([*avant, text or ""]).strip()[:500]


async def should_autoreply(
    db, *, settings: Dict[str, Any], phone_digits: str, text: str, contact: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Return {"ok": bool, "reason": str}. Inspects all rules without sending."""
    if not bool(settings.get("liluvine_wa_autoreply_enabled")):
        return {"ok": False, "reason": "disabled"}
    if not (text or "").strip():
        return {"ok": False, "reason": "empty_text"}
    # Allow / deny
    allow_list = _norm_phones(settings.get("liluvine_wa_autoreply_allow_phones"))
    deny_list = _norm_phones(settings.get("liluvine_wa_autoreply_deny_phones"))
    mode = (settings.get("liluvine_wa_autoreply_allow_mode") or "any").lower()
    if phone_digits in deny_list:
        return {"ok": False, "reason": "denylisted"}
    if mode == "whitelist" and allow_list and phone_digits not in allow_list:
        return {"ok": False, "reason": "not_whitelisted"}
    # Schedule
    schedule = (settings.get("liluvine_wa_autoreply_schedule") or "always").lower()
    if schedule in ("outside_hours", "business_hours"):
        try:
            open_h = int(str(settings.get("business_open_time") or "09:00").split(":", 1)[0])
            close_h = int(str(settings.get("business_close_time") or "18:00").split(":", 1)[0])
            # Lot Liluvine (2026-09) — vérifie désormais aussi business_days
            # (voir _in_business_window), pas seulement l'heure.
            in_hours = _in_business_window(settings.get("business_days"), open_h, close_h)
            if schedule == "business_hours" and not in_hours:
                return {"ok": False, "reason": "outside_business_hours"}
            if schedule == "outside_hours" and in_hours:
                return {"ok": False, "reason": "inside_business_hours"}
        except Exception:
            pass
    # Keywords
    keywords = _norm_keywords(settings.get("liluvine_wa_autoreply_keywords"))
    if keywords:
        low = text.lower()
        if not any(k in low for k in keywords):
            return {"ok": False, "reason": "no_keyword_match"}
    # Anti-flood : sert seulement à éviter une boucle de réponses (deux robots qui se répondent). Lot 179 : le délai
    # réglé est PLAFONNÉ (COOLDOWN_MAX_SECONDS) et la valeur 0 est respectée ; avant, un client qui écrivait un 2e message
    # dans les 60 s suivant la réponse d'accueil restait SANS réponse (« cooldown »), ce qui est inacceptable en conversation.
    cooldown = delai_anti_repetition(settings.get("liluvine_wa_autoreply_cooldown_seconds"))
    if cooldown > 0:
        state = await db.liluvine_wa_autoreply_state.find_one(
            {"phone_digits": phone_digits}, {"_id": 0, "last_replied_at": 1}
        )
        if state and state.get("last_replied_at"):
            try:
                last = datetime.fromisoformat(state["last_replied_at"].replace("Z", "+00:00"))
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                delta = (datetime.now(timezone.utc) - last).total_seconds()
                if delta < cooldown:
                    return {"ok": False, "reason": f"cooldown ({int(cooldown - delta)}s left)"}
            except Exception:
                pass
    return {"ok": True, "reason": "matched"}


def _tenant_contract_validity(tenant_doc: Dict[str, Any], default_threshold: int) -> Dict[str, Any]:
    """Validité de contrat pour la gate WA — calcul autonome, PAS un import
    depuis server.py (les fichiers routes/*.py n'importent server.py qu'en
    lazy/local à l'intérieur d'une fonction, jamais au niveau module, pour
    éviter un import circulaire — voir plus bas `import server as
    _server_module`). Reprend volontairement la même logique jour-de-retard
    que `_run_contract_overdue_alerts` (server.py), dupliquée ici en
    quelques lignes plutôt que de faire dépendre ce module de server.py.

    "Contrat valable" = un numéro de contrat existe ET (aucune date de
    référence n'est encore enregistrée OU le retard est sous le seuil) ET le
    compte n'est pas déjà suspendu par le cron quotidien.
    """
    has_contract = bool((tenant_doc.get("contract_number") or "").strip())
    account_suspended = (tenant_doc.get("account_status") or "active").lower() == "suspended"
    # Lot 129 — retard compté depuis l'ÉCHÉANCE (dernier règlement + périodicité), même règle que la puce de contrat
    from retard_echeance import retard_client
    retard = retard_client(tenant_doc)
    if not retard:
        return {
            "has_contract": has_contract, "days_overdue": None, "threshold_days": None,
            "valid": has_contract and not account_suspended,
        }
    days_overdue = retard["jours"]
    threshold = int(tenant_doc.get("contract_overdue_days") or default_threshold)
    valid = has_contract and days_overdue < threshold and not account_suspended
    return {
        "has_contract": has_contract, "days_overdue": days_overdue,
        "threshold_days": threshold, "valid": valid,
    }


async def _is_prospect_sender(db, contact: Optional[Dict[str, Any]]) -> bool:
    """Lot 21 — Vrai si l'expéditeur WhatsApp n'est pas un client sous contrat :
      - numéro inconnu : aucune fiche contact et aucun compte utilisateur
        (le webhook passe alors `contact=None` et rattache le message au
        tenant principal, c.-à-d. le compte SAWALI lui-même) ;
      - OU fiche contact portant l'étiquette « prospect » (posée à la main
        dans le carnet, insensible à la casse).
    """
    if not contact:
        return True
    tags = contact.get("tags")
    if tags is None and contact.get("id"):
        # Le webhook ne transmet pas les étiquettes : on relit la fiche.
        doc = await db.directory_contacts.find_one({"id": contact["id"]}, {"_id": 0, "tags": 1}) or {}
        tags = doc.get("tags")
    return any(str(t).strip().lower() == "prospect" for t in (tags or []))


def offre_du_client_applicable(is_prospect: bool, platform_tenant: bool) -> bool:
    """Lot 178 — l'offre du client (lot 163) concerne les CLIENTS DE SAWALI qui écrivent sur la ligne de la plateforme SAWALI
    (tenant admin / superviseur) : c'est là que le contact est relié à son client (société, e-mail, téléphone). Avant, la
    condition était inversée (tout SAUF la plateforme) : l'offre n'était jamais injectée et Liluvine redemandait « de quel
    logiciel s'agit-il ? ». Un prospect n'a pas d'offre. Fonction pure."""
    return bool(platform_tenant) and not is_prospect


ROLES_EQUIPE = ("admin", "superviseur", "moderateur")


def est_membre_equipe(chiffres: str, comptes: List[Dict[str, Any]], scope_uid: Optional[str]) -> bool:
    """Lot 189 — l'expéditeur WhatsApp est-il un membre de l'équipe de la plateforme ? Oui si un compte administrateur /
    superviseur / modérateur, ou un compte rattaché au compte qui reçoit la conversation, porte son numéro (8 derniers
    chiffres, espaces et signes ignorés). Les clients (contacts du carnet) n'ont AUCUN rôle sur la plateforme : ils ne
    reçoivent donc jamais les données internes du compte. Fonction pure."""
    fin = re.sub(r"\D", "", chiffres or "")[-8:]
    if len(fin) < 8:
        return False
    for c in comptes or []:
        equipe = c.get("role") in ROLES_EQUIPE or scope_uid in (c.get("id"), c.get("client_id"), c.get("parent_client_id"))
        if not equipe:
            continue
        for champ in ("phone", "whatsapp"):
            if re.sub(r"\D", "", str(c.get(champ) or ""))[-8:] == fin:
                return True
    return False


async def _expediteur_equipe(db, chiffres: str, scope_uid: Optional[str]) -> bool:
    """Lot 189 — lit les comptes de l'équipe (peu nombreux) et applique `est_membre_equipe`. Jamais d'exception : en cas
    d'erreur l'expéditeur est considéré comme extérieur (aucune donnée du compte)."""
    try:
        comptes = await db.users.find(
            {"$or": [{"role": {"$in": list(ROLES_EQUIPE)}}, {"id": scope_uid}, {"client_id": scope_uid}, {"parent_client_id": scope_uid}]},
            {"_id": 0, "id": 1, "role": 1, "client_id": 1, "parent_client_id": 1, "phone": 1, "whatsapp": 1}).to_list(2000)
        return est_membre_equipe(chiffres, comptes, scope_uid)
    except Exception:  # noqa: BLE001
        logger.warning("[wa_autoreply] lecture de l'équipe impossible", exc_info=True)
        return False


def _is_platform_tenant(tenant_doc: Dict[str, Any]) -> bool:
    """Lot 21 — Le tenant est le compte de la plateforme SAWALI (admin ou
    superviseur), et non un client : il n'a pas de contrat avec lui-même, les
    contrôles de contrat/accès restreint ne le concernent donc pas. Sans cette
    exception, un compte SAWALI sans `contract_number` bloquait toute réponse
    IA aux numéros inconnus (et notifiait ses décisionnaires à chaque message)."""
    return (tenant_doc.get("role") or "") in ("admin", "superviseur")


async def _find_decision_maker_contacts(db, client_id: str) -> List[Dict[str, Any]]:
    """Contacts marqués "décisionnaire" (Responsable/DG/Directeur, voir
    is_decision_maker sur DirectoryContactCreate/Update) pour ce tenant —
    destinataires des notifications Liluvine liées au contrat."""
    if not client_id:
        return []
    cursor = db.directory_contacts.find(
        {"client_id": client_id, "is_decision_maker": True},
        {"_id": 0, "id": 1, "name": 1, "phone": 1, "whatsapp": 1},
    )
    return await cursor.to_list(length=50)


def _fill_placeholders(template: str, **values: Any) -> str:
    out = template
    for key, val in values.items():
        out = out.replace("{" + key + "}", str(val if val is not None else ""))
    return out


def _tenant_effective_access_mode(tenant_doc: Dict[str, Any], settings_doc: Dict[str, Any]) -> Optional[str]:
    """Point 4 — Ouvert (24/7) vs Restreint (jours+heures ouvrées uniquement).

    Le seuil de montant de contrat (contract_min_amount_full_access, défaut
    65 000 FCFA) force "restricted" quel que soit le choix manuel de l'admin.
    Sinon on retourne le mode explicite du tenant s'il est défini, ou None
    (= pas de règle spécifique, on s'en remet entièrement à la fenêtre
    globale liluvine_wa_autoreply_schedule déjà appliquée dans should_autoreply).
    """
    threshold = settings_doc.get("contract_min_amount_full_access")
    try:
        threshold = float(threshold) if threshold not in (None, "") else 65000.0
    except (TypeError, ValueError):
        threshold = 65000.0
    amount = tenant_doc.get("contract_amount")
    try:
        amount = float(amount) if amount not in (None, "") else None
    except (TypeError, ValueError):
        amount = None
    if amount is not None and amount < threshold:
        return "restricted"
    mode = (tenant_doc.get("contract_access_mode") or "").strip().lower()
    if mode in ("open", "restricted"):
        return mode
    return None


# -----------------------------------------------------------------
# Point 5 — bouton "Souscrire temporairement" (voir plus haut, section
# contrat invalide). Webhook helper appelée depuis le dispatch WhatsApp de
# server.py ("button" ET "interactive"), même pattern que
# routes/download_approvals.py::handle_button_payload. Le tenant est encodé
# dans le button_id (liluvine_temp_subscribe_{scope_uid}) plutôt que dans un
# token en base, puisqu'il n'y a pas d'état à faire évoluer ici — on répond
# juste avec l'explication admin-configurable.
# -----------------------------------------------------------------
LILUVINE_TEMP_SUBSCRIBE_BUTTON_PAYLOAD_RE = re.compile(r"^liluvine_temp_subscribe_([A-Za-z0-9_\-]{6,64})$")


async def handle_temp_subscribe_button_payload(*, db, payload: str, from_phone: Optional[str]) -> bool:
    m = LILUVINE_TEMP_SUBSCRIBE_BUTTON_PAYLOAD_RE.match(payload or "")
    if not m:
        return False
    scope_uid = m.group(1)
    if not from_phone:
        return True  # matched but nowhere to reply — suppress regular processing anyway
    settings_doc = await db.settings.find_one({"_id": "global"}) or {}
    tenant_doc = await db.users.find_one({"id": scope_uid}, {"_id": 0, "full_name": 1, "company": 1}) or {}
    template = (
        settings_doc.get("liluvine_temp_subscription_explanation")
        or "La « souscription temporaire » vous permet de réactiver immédiatement les "
        "réponses automatiques Liluvine pour {client_name} en attendant la "
        "régularisation de votre contrat. Contactez votre conseiller SAWALI pour "
        "l'activer."
    )
    message = _fill_placeholders(
        template,
        client_name=tenant_doc.get("company") or tenant_doc.get("full_name") or "votre société",
    )
    try:
        import server as _server_module
        await _server_module._wa_send_text(from_phone, message)
    except Exception:  # noqa: BLE001
        logger.exception("[wa_autoreply] échec envoi explication souscription temporaire vers %s", from_phone)
    return True


def message_commande_a_corriger(texte: str, commande: str) -> str:
    """Lot 351 — message envoyé quand un texte SANS « ! » ressemble à une commande : on n'exécute rien, on dit quoi corriger.
    Fonction pure. `commande` est le nom de la commande devinée (sans « ! »)."""
    extrait = (texte or "").strip().replace("\n", " ")[:60]
    return (f"« {extrait} » n'est pas une commande : une commande commence toujours par « ! ». "
            f"Si vous cherchiez « !{commande} », envoyez exactement !{commande} (le point d'exclamation puis le mot, sans espace). "
            "Sinon, posez votre question en une phrase complète et je vous répondrai.")


async def autoreply_to_inbound(
    db,
    *,
    inbound_doc: Dict[str, Any],
    contact: Optional[Dict[str, Any]],
    settings_doc: Dict[str, Any],
    wa_send_text,  # callable(to_e164, text, reply_to_message_id=None)
    wa_send_interactive_button=None,  # callable(to_e164, body_text, button_id, button_title)
) -> Dict[str, Any]:
    """Top-level entrypoint called from the webhook handler. Decides + sends.

    Args:
      inbound_doc: the freshly-inserted whatsapp_messages doc (must have
                   `from`, `phone_digits`, `body`, `wa_message_id`, `client_id`).
      contact:     the matched directory_contacts row (or None).
      settings_doc: the cached `settings` doc.
      wa_send_text: a coroutine to send a text WA message.

    Returns a status dict (logged into wa_webhook_logs as `autoreply`).
    """
    phone_digits = inbound_doc.get("phone_digits") or _digits(inbound_doc.get("from", ""))
    text = (inbound_doc.get("body") or "").strip()
    # Lot 200 : un clic sur un bouton (texte du bouton dans `body`) est aussi traité ; image, vocal… restent ignorés
    clic_bouton = (inbound_doc.get("message_type") or "text") in ("button", "interactive") and bool(text)
    if (inbound_doc.get("message_type") or "text") != "text" and not clic_bouton:
        return {"ok": False, "reason": "non_text_message"}
    # Skip if the message is a Liluvine remote command (! / / prefix already handled)
    # EXCEPT for the public commands `!Garde` and `!Meteo`/`!Météo` (handled below).
    cmd_lower = text.lower()

    # Iter43-fix24az-o (2026-07-21) — Liluvine Reactions integration :
    # PRIORITÉ 1 : match d'un template Ad configuré → répondre + compter.
    # PRIORITÉ 2 : `!reactions` command → afficher les stats.
    # PRIORITÉ 3 : Fuzzy command detection (ex: "pharmacies de garde" → `!garde`).
    # PRIORITÉ 4 : Auto-add nouveau contact au groupe par défaut.
    from_num = inbound_doc.get("from") or ""

    # Lot 24 — envoi + copie dans le fil de discussion (`whatsapp_messages`).
    # Les réponses aux modèles d'annonce, les messages de correction de
    # commande et `!reactions` partaient sur WhatsApp sans être enregistrés :
    # elles n'apparaissaient donc pas dans la conversation du contact.
    async def _send_mirrored(to, text, command, **kw):
        res = await wa_send_text(to, text, **kw)
        try:
            await db.whatsapp_messages.insert_one({
                "id": uuid.uuid4().hex, "direction": "outbound",
                "to": to, "phone_digits": phone_digits, "body": text,
                "client_id": inbound_doc.get("client_id"), "contact_id": (contact or {}).get("id"),
                "wa_message_id": (res or {}).get("message_id") if isinstance(res, dict) else None,
                "auto_reply": True, "ai_generated": True, "ai_source": "liluvine_pro_autoreply",
                "command": command, "status": "sent", "wa_status": "sent",
                "sent_at": _now_iso(), "created_at": _now_iso(),
            })
        except Exception:  # noqa: BLE001 — la réponse est partie, la copie est secondaire
            logger.warning("[wa_autoreply] copie dans le fil échouée (%s)", command, exc_info=True)
        return res

    # Lot 287 — un patient qui répond à un rappel de RDV (demande de report…) reçoit le message réglé pour la
    # clinique (code_clinique) de SON rendez-vous ; sans réglage ou sans rappel récent, le traitement habituel continue.
    if not text.startswith(("!", "/")):
        try:
            from routes.planning_report_rdv import repondre_report_rdv
            res_report = await repondre_report_rdv(
                db, phone_digits=phone_digits, texte=text, reglages=settings_doc or {},
                envoyer=lambda to, msg: _send_mirrored(to, msg, "report_rdv"), numero_destinataire=from_num,
            )
            if res_report:
                return res_report
        except Exception as exc:  # noqa: BLE001 — une panne ici ne doit jamais bloquer la réponse habituelle
            logger.warning("[wa_autoreply] réponse report RDV échouée : %s", exc)

    try:
        import server as _server_module
        reactions_helpers = getattr(_server_module, "LILUVINE_REACTIONS_HELPERS", None) or {}
    except Exception:  # noqa: BLE001
        reactions_helpers = {}

    # Auto-add nouveau contact (silencieux, en tâche annexe)
    if reactions_helpers.get("auto_add_new_contact_if_enabled"):
        try:
            await reactions_helpers["auto_add_new_contact_if_enabled"](
                phone_digits,
                inbound_doc.get("from_profile_name") or inbound_doc.get("contact_name"),
                inbound_doc.get("client_id"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[wa_autoreply] auto_add_contact failed: %s", exc)

    # !reactions — commande spéciale : stats Liluvine Reactions
    if cmd_lower.startswith("!reactions") or cmd_lower.startswith("!réactions"):
        if reactions_helpers.get("build_reactions_summary_reply"):
            summary = await reactions_helpers["build_reactions_summary_reply"]()
            try:
                await _send_mirrored(from_num, summary, "!reactions")
                return {"ok": True, "command": "!reactions", "reply": summary[:120]}
            except Exception as exc:  # noqa: BLE001
                logger.warning("[wa_autoreply] !reactions send failed: %s", exc)

    # Ad template match (message issu de FB Ads pré-défini par l'annonceur)
    if reactions_helpers.get("try_reply_ad_template"):
        try:
            match = await reactions_helpers["try_reply_ad_template"](
                text, (lambda to, body, **kw: _send_mirrored(to, body, "ad_template", **kw)), from_num,
                phone_digits=phone_digits,
                contact=contact,
                tenant_id=inbound_doc.get("client_id"),
                wa_inbound_id=inbound_doc.get("wa_message_id"),
            )
            if match and match.get("sent"):
                return {
                    "ok": True,
                    "command": f"ad_template:{match['template'].get('id', '')[:8]}",
                    "reply": (match["template"].get("response_text") or "")[:120],
                }
        except Exception as exc:  # noqa: BLE001
            logger.warning("[wa_autoreply] ad_template match failed: %s", exc)

    # Fuzzy command detection (texte sans !, ou avec faute de frappe)
    if reactions_helpers.get("try_fuzzy_command_correction") and not text.startswith("!"):
        try:
            fuzzy = await reactions_helpers["try_fuzzy_command_correction"](text)
            # Lot 339 — « Ok je regarde » était pris pour « !garde » et la liste des pharmacies de garde était renvoyée à chaque message.
            # Une commande DEVINÉE (sans « ! ») n'est plus exécutée si la liste a déjà été envoyée à ce contact dans le délai réglé
            # (3 h par défaut) : ni correction, ni liste. Seule la demande explicite « !garde » renvoie la liste.
            if fuzzy and str(fuzzy.get("cmd") or "").lower().startswith(("garde", "pharmacie")) \
                    and await garde_deja_envoyee_recemment(db, phone_digits, settings_doc):
                logger.info("[wa_autoreply] liste de garde déjà envoyée récemment à %s…, commande devinée ignorée (%r)", phone_digits[:5], text[:40])
                if reactions_helpers.get("log_fuzzy_correction"):
                    try:
                        await reactions_helpers["log_fuzzy_correction"](
                            phone_digits=phone_digits, contact=contact, tenant_id=inbound_doc.get("client_id"), cmd=fuzzy["cmd"],
                            score=float(fuzzy.get("score") or 0), inbound_text=text,
                            correction_prefix="(ignorée : la liste de garde a déjà été envoyée récemment, demande non explicite)",
                            wa_inbound_id=inbound_doc.get("wa_message_id"),
                        )
                    except Exception:  # noqa: BLE001
                        pass
                return {"ok": True, "command": "!garde", "skipped": "garde_deja_envoyee_recemment", "send": None}
            if fuzzy and fuzzy.get("cmd"):
                # Lot 351 (règle du propriétaire, 29/10/2026) : une commande n'est EXÉCUTÉE que si le message commence par « ! ».
                # Un message sans « ! » qui ressemble à une commande n'est plus exécuté : Liluvine explique ce qu'il faut corriger
                # (le « ! » manquant ou le nom de la commande) et ne répond rien d'autre.
                correction = message_commande_a_corriger(text, str(fuzzy["cmd"]))
                try:
                    await _send_mirrored(from_num, correction, "fuzzy_correction")
                except Exception:  # noqa: BLE001
                    pass
                # Iter43-fix24az-p — journalise le match dans la timeline du contact
                if reactions_helpers.get("log_fuzzy_correction"):
                    try:
                        await reactions_helpers["log_fuzzy_correction"](
                            phone_digits=phone_digits,
                            contact=contact,
                            tenant_id=inbound_doc.get("client_id"),
                            cmd=fuzzy["cmd"],
                            score=float(fuzzy.get("score") or 0),
                            inbound_text=text,
                            correction_prefix=correction,
                            wa_inbound_id=inbound_doc.get("wa_message_id"),
                        )
                    except Exception:  # noqa: BLE001
                        pass
                logger.info("[wa_autoreply] commande devinée NON exécutée (sans « ! ») : %s (score=%.1f)", fuzzy["cmd"], fuzzy.get("score", 0))
                return {"ok": True, "command": "fuzzy_correction", "reply": correction[:120], "skipped": "commande_sans_point_exclamation"}
        except Exception as exc:  # noqa: BLE001
            logger.warning("[wa_autoreply] fuzzy correction failed: %s", exc)

    # Iter43-fix24az-p — Capture les messages non-traités (free-text sans !, sans template
    # match, sans fuzzy). Le hook alimente le panneau "Suggestions" dans AdminSettings.
    if not text.startswith("!") and not text.startswith("/") and reactions_helpers.get("record_unmatched_message"):
        try:
            await reactions_helpers["record_unmatched_message"](
                inbound_text=text,
                phone_digits=phone_digits,
                contact_name=(contact or {}).get("name") or inbound_doc.get("from_profile_name"),
                tenant_id=inbound_doc.get("client_id"),
            )
        except Exception:  # noqa: BLE001
            pass

    is_public_cmd = (
        cmd_lower.startswith("!garde") or cmd_lower.startswith("!pharmacie")
        or cmd_lower.startswith("!meteo") or cmd_lower.startswith("!météo")
        or cmd_lower.startswith("!adresse") or cmd_lower.startswith("!contact")
        or cmd_lower.startswith("!horaire") or cmd_lower.startswith("!horaires")
        or cmd_lower.startswith("!stock") or cmd_lower.startswith("!dispo")
    )
    # Iter43-fix24d (2026-06) — Stocker TOUTES les exclamations (`!xxx`) dans la table
    # dédiée `liluvine_exclamations`, qu'on sache ou non les traiter. Cela permet :
    #   - Audit des commandes inconnues (ex. `!Aizenta` sans handler côté code)
    #   - Roadmap : décider lesquelles automatiser plus tard
    if text.startswith("!"):
        try:
            cmd_match = re.match(r"^!\s*([\w\.\-]+)", text)
            command_token = (cmd_match.group(1) if cmd_match else "").lower()
            tail = text[(cmd_match.end() if cmd_match else 1):].strip()
            await db.liluvine_exclamations.insert_one({
                "id": uuid.uuid4().hex,
                "channel": "whatsapp",
                "direction": "inbound",
                "from": inbound_doc.get("from"),
                "phone_digits": phone_digits,
                "body": text,
                "command": command_token,
                "command_args": tail,
                "from_profile_name": inbound_doc.get("from_profile_name"),
                "contact_id": inbound_doc.get("contact_id"),
                "contact_name": inbound_doc.get("contact_name"),
                "client_id": inbound_doc.get("client_id"),
                "wa_message_id": inbound_doc.get("wa_message_id"),
                "inbound_doc_id": inbound_doc.get("id"),
                "is_known_command": is_public_cmd,
                "handled": False,  # mis à True après envoi de la réponse
                "reply": None,
                "created_at": _now_iso(),
            })
        except Exception:  # noqa: BLE001
            logger.exception("[wa_autoreply] persist exclamation failed")

    # Iter43-fix24i (2026-06) — DECOUPLAGE : les commandes publiques `!xxx` doivent
    # TOUJOURS fonctionner indépendamment du toggle `liluvine_wa_autoreply_enabled`
    # (qui ne contrôle QUE l'auto-reply LLM basé sur le contenu).
    # Auparavant : si l'admin n'avait pas activé l'auto-reply LLM, `!garde`/`!meteo`
    # restaient muettes (decision.ok = False sur `disabled`).
    # Maintenant : les `!commandes` (connues ET inconnues) passent par leur propre
    # branche AVANT le gate `should_autoreply`. Seul filtre commun : denylist phones.
    if text.startswith("!") or text.startswith("/"):
        # Filtre denylist (même pour les commandes — un admin peut vouloir
        # bloquer un harceleur même sur les commandes utilitaires).
        deny_list_cmd = _norm_phones(settings_doc.get("liluvine_wa_autoreply_deny_phones"))
        if phone_digits in deny_list_cmd:
            return {"ok": False, "reason": "denylisted"}
        # Lot 61 — liste noire des commandes « ! » (commande éventuellement issue de la
        # correction automatique d'un texte libre) : refus, avec le message de refus
        try:
            from routes.liste_noire_commandes import refuser_si_bloque
            if await refuser_si_bloque(db, phone_digits, text, envoyer=wa_send_text):
                return {"ok": False, "reason": "liste_noire_commandes"}
        except Exception:  # noqa: BLE001
            logger.warning("[wa_autoreply] contrôle de la liste noire des commandes impossible", exc_info=True)

        # Iter43-fix24ac (2026-06-16) — Configurable VIDAL `!commands`.
        # On essaie d'abord de matcher avec une action VIDAL configurée
        # (Admin → Settings → VIDAL Actions). Si la commande correspond,
        # on exécute l'action et on répond. Sinon on continue vers les
        # handlers existants (`!garde`, `!adresse`, etc.).
        vidal_cmd_token = None
        vidal_cmd_args = ""
        m_v = re.match(r"^!\s*([\w\-]+)\s*(.*)$", text)
        if m_v:
            vidal_cmd_token = (m_v.group(1) or "").lower()
            vidal_cmd_args = m_v.group(2) or ""
        if vidal_cmd_token:
            # `!doc` / `!rech` — synonymes, recherche riche DCI + équivalences
            # (routes/vidal_riche.py), distincte des actions VIDAL génériques
            # configurables ci-dessous (str.format_map sur un endpoint REST).
            if vidal_cmd_token in ("doc", "rech"):
                try:
                    from routes.vidal_riche import build_riche_command_reply
                    vidal_res = await build_riche_command_reply(
                        db, vidal_cmd_args, phone_digits, contact,
                        send_wa_fn=wa_send_text,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("[wa_autoreply][vidal_riche] failed for !%s", vidal_cmd_token)
                    vidal_res = None
            else:
                vidal_res = await _build_vidal_reply(
                    db, vidal_cmd_token, vidal_cmd_args, phone_digits,
                )
            if vidal_res is not None:
                # The command matched a configured VIDAL action — send reply.
                reply_v = vidal_res.get("text") or "…"
                to_e164_v = inbound_doc.get("from") or f"+{phone_digits}"
                try:
                    send_v = await wa_send_text(
                        to_e164_v, reply_v,
                        reply_to_message_id=inbound_doc.get("wa_message_id"),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[wa_autoreply][vidal] send failed: %s", exc)
                    send_v = {"ok": False, "error": str(exc)}
                # !doc/!rech avec équivalents disponibles → bouton WA de suivi
                # "Équivalences" (ne bloque jamais la réponse principale).
                if vidal_res.get("vmp_id") and wa_send_interactive_button is not None:
                    try:
                        equiv_btn_id = f"vidal_equiv:{vidal_res['vmp_id']}:{vidal_res.get('product_id') or ''}"
                        await wa_send_interactive_button(
                            to_e164_v,
                            "Des produits équivalents (même DCI + dosage) sont disponibles.",
                            equiv_btn_id,
                            "Équivalences",
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[wa_autoreply][vidal_riche] equivalents button send failed: %s", exc)
                try:
                    await db.whatsapp_messages.insert_one({
                        "id": uuid.uuid4().hex, "direction": "outbound",
                        "to": to_e164_v, "phone_digits": phone_digits,
                        "body": reply_v, "client_id": inbound_doc.get("client_id"),
                        "wa_message_id": (send_v or {}).get("message_id"),
                        "auto_reply": True,
                        "command": f"!{vidal_cmd_token} [vidal:{vidal_res.get('action_id')}]",
                        "vidal_action_id": vidal_res.get("action_id"),
                        "vidal_denied": bool(vidal_res.get("denied")),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
                except Exception:  # noqa: BLE001
                    pass
                try:
                    await db.liluvine_exclamations.update_one(
                        {"wa_message_id": inbound_doc.get("wa_message_id"), "direction": "inbound"},
                        {"$set": {
                            "handled": True,
                            "reply": reply_v[:500],
                            "handled_at": _now_iso(),
                            "vidal_action_id": vidal_res.get("action_id"),
                            "send_ok": bool((send_v or {}).get("ok") if isinstance(send_v, dict) else True),
                        }},
                    )
                except Exception:  # noqa: BLE001
                    pass
                return {
                    "ok": True,
                    "command": f"!{vidal_cmd_token}",
                    "vidal_action_id": vidal_res.get("action_id"),
                    "denied": bool(vidal_res.get("denied")),
                    "send": send_v,
                    "reply": reply_v,
                }
            # vidal_res is None → no matching VIDAL action, fall through.

        if is_public_cmd:
            # Commandes publiques — TOUJOURS exécutées.
            # Sécurisées par try/except : même si le builder plante, on répond.
            location_payload = None  # type=location WA à envoyer en plus du texte
            try:
                if cmd_lower.startswith("!garde") or cmd_lower.startswith("!pharmacie"):
                    reply_pc = await _build_garde_reply(db)
                    cmd_label = "!garde"
                elif cmd_lower.startswith("!adresse") or cmd_lower.startswith("!contact"):
                    addr_res = await _build_adresse_reply(db)
                    reply_pc = addr_res["text"]
                    location_payload = addr_res.get("location")
                    cmd_label = "!adresse"
                elif cmd_lower.startswith("!horaire"):  # couvre !horaire ET !horaires
                    reply_pc = await _build_horaires_reply(db)
                    cmd_label = "!horaires"
                elif cmd_lower.startswith("!stock") or cmd_lower.startswith("!dispo"):
                    # Extract args after the command word
                    m_stock = re.match(r"^!(?:stock|dispo)\s*(.*)$", text, re.IGNORECASE)
                    stock_args = (m_stock.group(1).strip() if m_stock else "")
                    reply_pc = await _build_stock_reply(db, stock_args)
                    cmd_label = "!stock"
                else:
                    reply_pc = await _build_meteo_reply(db, cmd_lower, phone_digits)
                    cmd_label = "!meteo"
                if not reply_pc or not str(reply_pc).strip():
                    reply_pc = "…"
            except Exception:  # noqa: BLE001
                logger.exception("[wa_autoreply][cmd] builder failed for %s", cmd_lower)
                reply_pc = (
                    "⚠️ Désolé, je n'arrive pas à traiter cette commande pour le moment. "
                    "Réessayez dans quelques instants."
                )
                cmd_label = cmd_lower.split()[0] if cmd_lower.split() else "!unknown"
            to_e164_pc = inbound_doc.get("from") or f"+{phone_digits}"
            try:
                send_pc = await wa_send_text(
                    to_e164_pc, reply_pc, reply_to_message_id=inbound_doc.get("wa_message_id"),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[wa_autoreply][cmd] send failed: %s", exc)
                send_pc = {"ok": False, "error": str(exc)}
            # Iter43-fix24al + 24aq (2026-06-17) — Pour TOUTES les commandes
            # WhatsApp (`!garde`, `!produits`, `!adresse`, etc.), envoie aussi
            # une image après le texte si configurée dans settings :
            #   - Image SPÉCIFIQUE à la commande : `wa_cmd_<id>_image_url`
            #     (où <id> est l'`id` de l'action sans `!`, ex: `garde`, `produits`)
            #     + `wa_cmd_<id>_image_caption`.
            #   - Image PAR DÉFAUT (fallback) : `wa_default_cmd_image_url`
            #     + `wa_default_cmd_image_caption`.
            #   - Compatibilité ascendante : `garde_reply_image_url` (utilisé
            #     historiquement pour !garde) est encore reconnue.
            # No-op silencieux si aucune image n'est configurée.
            try:
                cmd_id = (cmd_label or "").lstrip("!").lower().strip()
                s_img = await db.settings.find_one(
                    {"_id": "global"},
                    {"_id": 0,
                     f"wa_cmd_{cmd_id}_image_url": 1,
                     f"wa_cmd_{cmd_id}_image_caption": 1,
                     "wa_default_cmd_image_url": 1,
                     "wa_default_cmd_image_caption": 1,
                     "garde_reply_image_url": 1,
                     "garde_reply_image_caption": 1},
                ) or {}
                # Priority order : per-command override → legacy garde → default
                img_url = (
                    s_img.get(f"wa_cmd_{cmd_id}_image_url")
                    or (s_img.get("garde_reply_image_url") if cmd_id == "garde" else "")
                    or s_img.get("wa_default_cmd_image_url")
                    or ""
                )
                img_caption = (
                    s_img.get(f"wa_cmd_{cmd_id}_image_caption")
                    or (s_img.get("garde_reply_image_caption") if cmd_id == "garde" else "")
                    or s_img.get("wa_default_cmd_image_caption")
                    or None
                )
                if img_url:
                    img_res = await _wa_send_image(
                        to_e164_pc, img_url,
                        caption=img_caption, db_ref=db,
                    )
                    logger.info("[wa_autoreply][!%s] image sent: %s", cmd_id, img_res)
            except Exception:  # noqa: BLE001
                logger.exception("[wa_autoreply][!%s] image send failed", cmd_label)
            # Iter43-fix24j — Pour !adresse avec lat/lon configurés, envoie aussi
            # une "carte" WhatsApp type=location (UX native : preview map cliquable).
            if location_payload is not None:
                try:
                    s_local = await db.settings.find_one({"_id": "global"}) or {}
                    loc_res = await _wa_send_location(
                        to_e164_pc,
                        latitude=location_payload["latitude"],
                        longitude=location_payload["longitude"],
                        name=location_payload.get("name"),
                        address=location_payload.get("address"),
                        settings_doc=s_local,
                    )
                    logger.info("[wa_autoreply][!adresse] location sent: %s", loc_res)
                except Exception:  # noqa: BLE001
                    logger.exception("[wa_autoreply][!adresse] location send failed")
            try:
                await db.whatsapp_messages.insert_one({
                    "id": uuid.uuid4().hex, "direction": "outbound",
                    "to": to_e164_pc, "phone_digits": phone_digits,
                    "body": reply_pc, "client_id": inbound_doc.get("client_id"),
                    "wa_message_id": (send_pc or {}).get("message_id"),
                    "auto_reply": True, "command": cmd_label,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception:  # noqa: BLE001
                pass
            try:
                await db.liluvine_exclamations.update_one(
                    {"wa_message_id": inbound_doc.get("wa_message_id"), "direction": "inbound"},
                    {"$set": {
                        "handled": True, "reply": reply_pc[:500],
                        "handled_at": _now_iso(),
                        "send_ok": bool((send_pc or {}).get("ok") if isinstance(send_pc, dict) else True),
                    }},
                )
            except Exception:  # noqa: BLE001
                pass
            return {"ok": True, "command": cmd_label, "send": send_pc, "reply": reply_pc}

        # Catch-all pour `!xxx` inconnu / `/xxx` — TOUJOURS exécuté SAUF si
        # l'admin l'a explicitement désactivé via `liluvine_wa_unknown_cmd_fallback_enabled`.
        # Le `True` par défaut garantit qu'aucune commande n'est silencieuse.
        fb_enabled = settings_doc.get("liluvine_wa_unknown_cmd_fallback_enabled")
        if fb_enabled is False:  # explicitement False uniquement (None / absent = True)
            return {"ok": False, "reason": "unknown_fallback_disabled"}
        fallback_reply = (settings_doc.get("liluvine_wa_unknown_cmd_reply") or "…").strip() or "…"
        to_e164_fb = inbound_doc.get("from") or f"+{phone_digits}"
        try:
            send_res_fb = await wa_send_text(
                to_e164_fb, fallback_reply, reply_to_message_id=inbound_doc.get("wa_message_id"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[wa_autoreply][fallback] send failed: %s", exc)
            send_res_fb = {"ok": False, "error": str(exc)}
        try:
            await db.whatsapp_messages.insert_one({
                "id": uuid.uuid4().hex, "direction": "outbound",
                "to": to_e164_fb, "phone_digits": phone_digits,
                "body": fallback_reply, "client_id": inbound_doc.get("client_id"),
                "wa_message_id": (send_res_fb or {}).get("message_id"),
                "auto_reply": True, "command": "unknown_fallback",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:  # noqa: BLE001
            pass
        try:
            await db.liluvine_exclamations.update_one(
                {"wa_message_id": inbound_doc.get("wa_message_id"), "direction": "inbound"},
                {"$set": {
                    "handled": True, "reply": fallback_reply[:500],
                    "handled_at": _now_iso(),
                    "send_ok": bool((send_res_fb or {}).get("ok") if isinstance(send_res_fb, dict) else True),
                    "fallback": True,
                }},
            )
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "command": "unknown_fallback", "send": send_res_fb}

    decision = await should_autoreply(
        db, settings=settings_doc, phone_digits=phone_digits, text=text, contact=contact
    )
    if not decision["ok"]:
        return decision

    # Iter38r-fix9i — "Reprendre la conversation" : if a human has taken
    # over this WA session, skip auto-reply until the takeover expires (or
    # is manually released).
    scope_uid_pre = inbound_doc.get("client_id")
    if scope_uid_pre:
        session_id_pre = f"wa:{scope_uid_pre}:{phone_digits}"
        existing = await db.liluvine_pro_sessions.find_one(
            {"id": session_id_pre},
            {"_id": 0, "human_takeover": 1, "human_takeover_until": 1},
        )
        if existing and existing.get("human_takeover"):
            until = existing.get("human_takeover_until")
            still_active = True
            if until:
                try:
                    until_dt = datetime.fromisoformat(str(until).replace("Z", "+00:00"))
                    if until_dt.tzinfo is None:
                        until_dt = until_dt.replace(tzinfo=timezone.utc)
                    still_active = datetime.now(timezone.utc) < until_dt
                except Exception:
                    still_active = True
            if still_active:
                return {"ok": False, "reason": "human_takeover_active"}

    # Tenant feature gate — only if Liluvine PRO is enabled on the parent admin
    # OR the inbound number is matched to a user whose email is in the bypass list.
    scope_uid = inbound_doc.get("client_id")

    # Iter43-fix24i (2026-06) — La gestion des commandes publiques `!Garde`/`!Meteo`
    # est désormais effectuée AVANT `should_autoreply` (voir bloc ci-dessus, ligne ~145).
    # Cette branche est conservée vide pour la lisibilité — toute exclamation `!xxx`
    # a déjà été return-ée par le bloc principal.

    if scope_uid:
        parent = await db.users.find_one({"id": scope_uid}, {"_id": 0, "features": 1})
        feats = (parent or {}).get("features") or {}
        if not feats.get("ai_liluvine_pro"):
            # Bypass check : settings.liluvine_pro_bypass_emails may grant
            # access to specific user emails matched via their phone number.
            settings_doc_local = await db.settings.find_one({"_id": "global"}) or {}
            bypass_raw = settings_doc_local.get("liluvine_pro_bypass_emails") or ""
            bypass = set()
            if isinstance(bypass_raw, list):
                bypass = {str(x).strip().lower() for x in bypass_raw if str(x).strip()}
            else:
                bypass = {p.strip().lower() for p in re.split(r"[\s,;]+", str(bypass_raw)) if p.strip()}
            phone_user = None
            if phone_digits and bypass:
                phone_user = await db.users.find_one(
                    {"phone": {"$regex": phone_digits}},
                    {"_id": 0, "email": 1},
                )
            sender_email = ((phone_user or {}).get("email") or "").lower().strip()
            if not (sender_email and sender_email in bypass):
                return {"ok": False, "reason": "liluvine_pro_not_enabled"}

    # Build the LLM context (reuse the same RAG helper as the chat UI)
    try:
        from routes.liluvine_pro import (
            DEFAULT_WA_MODE_INSTRUCTIONS, DEFAULT_WA_PROSPECT_SYSTEM_PROMPT,
            _fetch_context_snippets, _resolve_base_system_prompt,
        )
    except Exception as exc:
        logger.warning("[wa_autoreply] could not import liluvine helpers: %s", exc)
        return {"ok": False, "reason": f"liluvine_import_failed: {exc!r}"}

    # The "user" for context scoping = the parent admin (so the assistant
    # sees their tenant's data exactly like the dashboard does).
    if not scope_uid:
        return {"ok": False, "reason": "no_tenant_scope"}
    user_doc = await db.users.find_one({"id": scope_uid}, {"_id": 0})
    if not user_doc:
        return {"ok": False, "reason": "tenant_user_not_found"}

    # Lot 21 — Prospect (expéditeur non contractuel) : prompt dédié, aucune
    # donnée du tenant dans le contexte, et possibilité de couper ces réponses
    # (Admin → Paramètres → Auto-réponse WhatsApp → « Prospects »).
    is_prospect = await _is_prospect_sender(db, contact)
    # Lot 59 — message reçu sur une ligne « prospects » (ex. numéro des publicités Meta) :
    # l'expéditeur est traité en prospect (prompt prospects, aucune donnée du tenant).
    try:
        from routes.numeros_wa import ligne_recue_prospects
        is_prospect = is_prospect or ligne_recue_prospects(settings_doc)
    except Exception:  # noqa: BLE001
        pass
    if is_prospect and settings_doc.get("liluvine_wa_prospect_enabled") is False:
        return {"ok": False, "reason": "prospect_replies_disabled"}
    # Lot 21 — le compte de la plateforme n'est pas soumis aux contrôles de contrat.
    platform_tenant = _is_platform_tenant(user_doc)

    # Lot Liluvine (2026-09, point 3) — contrat invalide/expiré : plutôt que
    # de générer une réponse IA normale, on notifie le(s) contact(s)
    # décisionnaire(s) du tenant avec un message admin-configurable, et on
    # s'arrête là (pas de réponse IA à l'expéditeur dans ce cas).
    default_overdue_threshold = int(settings_doc.get("contract_overdue_days_default") or 5)
    contract_status = _tenant_contract_validity(user_doc, default_overdue_threshold)
    if not platform_tenant and not contract_status["valid"]:
        decision_makers = await _find_decision_maker_contacts(db, scope_uid)
        if not decision_makers:
            logger.warning(
                "[wa_autoreply] contrat invalide pour tenant %s mais aucun contact décisionnaire à notifier",
                scope_uid,
            )
            return {"ok": False, "reason": "contract_invalid_no_decision_maker"}
        template = (
            settings_doc.get("liluvine_contract_invalid_message")
            or "Bonjour, le contrat de {client_name} avec SAWALI n'est plus valide "
            "(paiement en attente ou contrat absent). Les réponses automatiques "
            "Liluvine sont suspendues jusqu'à régularisation."
        )
        message = _fill_placeholders(
            template,
            client_name=user_doc.get("company") or user_doc.get("full_name") or "votre société",
            days_overdue=contract_status.get("days_overdue"),
        )
        notified = 0
        for dm in decision_makers:
            dm_phone = _digits(dm.get("whatsapp") or dm.get("phone") or "")
            if not dm_phone:
                continue
            try:
                if wa_send_interactive_button is not None:
                    # Point 5 — bouton "Souscrire temporairement" sur ce message.
                    # Le tenant (scope_uid) est encodé dans le button_id pour
                    # que handle_temp_subscribe_button_payload() sache à quel
                    # client répondre lors du clic (voir plus bas).
                    await wa_send_interactive_button(
                        dm_phone, message, f"liluvine_temp_subscribe_{scope_uid}", "Souscrire temporairement",
                    )
                else:
                    await wa_send_text(dm_phone, message)
                notified += 1
            except Exception:  # noqa: BLE001
                logger.exception("[wa_autoreply] échec notification contrat invalide vers %s", dm_phone)
        return {"ok": False, "reason": "contract_invalid", "notified_decision_makers": notified}

    # Lot Liluvine (2026-09, point 4) — contrat valable mais accès "restreint"
    # (montant de contrat sous le seuil, ou mode explicitement "restricted") :
    # hors jours/heures ouvrées, on notifie les décisionnaires au lieu de
    # répondre normalement.
    access_mode = None if platform_tenant else _tenant_effective_access_mode(user_doc, settings_doc)
    if access_mode == "restricted":
        try:
            open_h = int(str(settings_doc.get("business_open_time") or "09:00").split(":", 1)[0])
            close_h = int(str(settings_doc.get("business_close_time") or "18:00").split(":", 1)[0])
            in_hours = _in_business_window(settings_doc.get("business_days"), open_h, close_h)
        except Exception:
            in_hours = True  # fail-open : erreur de parsing => ne pas bloquer
        if not in_hours:
            decision_makers = await _find_decision_maker_contacts(db, scope_uid)
            notified = 0
            if decision_makers:
                template = (
                    settings_doc.get("liluvine_access_restricted_message")
                    or "Bonjour, les réponses automatiques Liluvine pour {client_name} "
                    "sont disponibles uniquement pendant les heures/jours ouvrés avec "
                    "votre formule actuelle. Un conseiller vous répondra dès la reprise."
                )
                message = _fill_placeholders(
                    template,
                    client_name=user_doc.get("company") or user_doc.get("full_name") or "votre société",
                )
                for dm in decision_makers:
                    dm_phone = _digits(dm.get("whatsapp") or dm.get("phone") or "")
                    if not dm_phone:
                        continue
                    try:
                        await wa_send_text(dm_phone, message)
                        notified += 1
                    except Exception:  # noqa: BLE001
                        logger.exception("[wa_autoreply] échec notification accès restreint vers %s", dm_phone)
            else:
                logger.warning(
                    "[wa_autoreply] accès restreint hors heures pour tenant %s mais aucun contact décisionnaire",
                    scope_uid,
                )
            return {"ok": False, "reason": "access_restricted_outside_hours", "notified_decision_makers": notified}

    # Lot 163 — Offre du client (logiciels, produits, services) : le contact est relié à son client ; Liluvine connaît
    # son offre (plus de questions inutiles) et, si le contrat du client n'est pas à jour, REFUSE l'assistance demandée
    # (texte exact du propriétaire, signé par l'assistant IA) en ouvrant un ticket et en escaladant. Jamais bloquant.
    offre_bloc = ""
    client_lie = None   # lot 181 : client relié au contact (ticket du classement)
    client_eff = None   # lot 187 : client retenu = client relié, sinon client par défaut (contact du carnet sans société)
    client_defaut_utilise = False
    logiciels_hors_offre: set = set()   # lot 337 : logiciels connus de SAWALI mais absents de l'offre de CE client
    etat_contrat_cl = None   # lot 183 : « valide » | « retard » | « aucun » (prompt propre à chaque cas)
    # Lot 180 — pourquoi l'offre est connue ou non (affiché dans le journal des réponses automatiques) : prospect,
    # ligne autre que la plateforme, contact sans client lié, client sans offre saisie, ou offre connue.
    offre_statut = "prospect" if is_prospect else ("ligne_non_plateforme" if not platform_tenant else "contact_sans_client")
    # Lot 188 — un numéro INCONNU du carnet relève lui aussi du client par défaut (SAWALI-2S) : offre, prompt « client » et
    # tickets. Il reste privé de toutes les données du compte (contacts, paiements… : voir plus bas) et de Qdrant.
    inconnu_du_carnet = bool(platform_tenant) and not contact
    if offre_du_client_applicable(is_prospect, platform_tenant) or inconnu_du_carnet:
        try:
            from routes import offre_client as _offre
            client_lie = await _offre.client_du_contact(db, contact)
            client_eff = client_lie
            if not client_lie:
                # Lot 187 — un contact du carnet est forcément celui d'un client : sans société reconnue, c'est le client par
                # défaut (client primaire, SAWALI-2S) dont on lit l'offre. Pas de refus d'assistance : pas de retard de paiement.
                client_eff = await _offre.client_par_defaut(db, settings_doc, scope_uid)
                client_defaut_utilise = bool(client_eff)
            if client_eff:
                offre_bloc = _offre.bloc_prompt(client_eff.get("company") or "", client_eff.get("offre_client") or [])
                if offre_bloc:
                    # Lot 337 : logiciels des autres clients (ex. Aizenta) absents de l'offre de celui-ci
                    logiciels_hors_offre = (await _offre.logiciels_connus(db)) - _offre.mots_logiciels(client_eff.get("offre_client") or [])
                if client_defaut_utilise:
                    offre_statut = "client_defaut" if offre_bloc else "client_defaut_sans_offre"
                    etat_contrat_cl = "valide"
                else:
                    offre_statut = "offre_connue" if offre_bloc else "client_sans_offre"
            if client_lie:
                from routes.vip_contrat import etat_contrat_contact
                etat_ct = await etat_contrat_contact(db, contact, settings_doc)
                etat_contrat_cl = etat_ct
                signature_refus = (settings_doc.get("liluvine_wa_autoreply_signature") or "").strip() or "— 🤖 Réponse automatique Liluvine PRO"
                refus = await _offre.refuser_assistance(
                    db, settings_doc, contact=contact, texte=text, etat_contrat=etat_ct, client=client_lie,
                    phone_digits=phone_digits, envoyer=wa_send_text, signature=signature_refus,
                    reply_to=inbound_doc.get("wa_message_id"))
                if refus["refuse"]:
                    # le refus apparaît dans la conversation (Centre de messagerie) comme une réponse automatique
                    try:
                        await db.whatsapp_messages.insert_one({
                            "id": secrets.token_urlsafe(12), "client_id": scope_uid, "tenant_id": scope_uid,
                            "direction": "outbound", "from": "liluvine-pro", "to": inbound_doc.get("from") or f"+{phone_digits}",
                            "phone_digits": phone_digits, "message_type": "text",
                            "body": f"{_offre.texte_refus(settings_doc, refus['objet'])}\n\n{signature_refus}",
                            "status": "sent", "wa_status": "sent", "sent_at": _now_iso(), "created_at": _now_iso(),
                            "ai_generated": True, "ai_source": "liluvine_offre_client",
                            "contact_id": (contact or {}).get("id"),
                            "ticket_id": (refus.get("ticket") or {}).get("id"),
                            "ticket_number": (refus.get("ticket") or {}).get("number"),
                        })
                    except Exception:  # noqa: BLE001
                        logger.warning("[wa_autoreply] miroir du refus d'assistance impossible", exc_info=True)
                    return {"ok": bool(refus["envoye"]), "reason": "assistance_refusee_contrat",
                            "objet": refus["objet"], "ticket": refus.get("ticket")}
        except Exception:  # noqa: BLE001
            logger.warning("[wa_autoreply] offre du client ignorée", exc_info=True)

    # Lot 21 — Un prospect ne reçoit AUCUNE donnée du tenant : avant ce lot,
    # un inconnu qui écrivait « mes contacts » ou « paiements » recevait dans
    # le contexte de l'IA les 10 derniers contacts/paiements du compte SAWALI.
    # Seule la base de connaissance (plus bas) reste injectée.
    if is_prospect:
        ctx, biz_ctx = "", ""
    else:
        # Lot 189 — sur la ligne de la plateforme, seuls les membres de l'équipe reçoivent les données du compte (contacts,
        # tickets, paiements, rendez-vous, notes) : les clients n'ont aucun rôle sur la plateforme. Les comptes clients
        # (leurs propres lignes WhatsApp) gardent leur comportement.
        if platform_tenant and not await _expediteur_equipe(db, phone_digits, scope_uid):
            ctx = ""
        else:
            ctx = await _fetch_context_snippets(db, user_doc, text)
        # Iter40 (2026-02) — Business RAG : queries on RDV/Tickets/HR/Caisse…
        # Filtré par ACL (liste blanche par module/numéro).
        try:
            from routes.liluvine_business_rag import build_business_rag_context
            biz_ctx = await build_business_rag_context(db, phone_digits=phone_digits, query=text)
        except Exception:  # noqa: BLE001
            biz_ctx = ""
    # Lot 184 — historique chargé AVANT la recherche : la requête Qdrant tient compte des messages précédents.
    session_id = f"wa:{scope_uid}:{phone_digits}"
    try:
        depuis = (datetime.now(timezone.utc) - timedelta(hours=HISTORIQUE_HEURES)).isoformat()
        recents = await db.liluvine_pro_messages.find(
            {"session_id": session_id, "created_at": {"$gte": depuis}}, {"_id": 0, "role": 1, "content": 1, "created_at": 1},
        ).sort("created_at", -1).limit(HISTORIQUE_MAX_MESSAGES).to_list(HISTORIQUE_MAX_MESSAGES)
        # Lot 337 : une ancienne réponse citant un logiciel hors offre n'est pas rejouée (sinon elle se répète à chaque message)
        from routes.offre_client import retirer_mentions_hors_offre
        historique = historique_pour_llm(retirer_mentions_hors_offre(list(reversed(recents)), logiciels_hors_offre))
    except Exception:  # noqa: BLE001 — sans historique, Liluvine répond comme avant
        logger.warning("[wa_autoreply] historique de la conversation illisible", exc_info=True)
        historique = []
    # Lot 185 — « 2 » répond à la liste numérotée de Liluvine : le modèle et la recherche reçoivent l'option choisie
    text_modele = traduire_choix_numerique(text, historique)
    # Iter38r-fix9c — Also inject the Knowledge Base for WhatsApp auto-reply
    try:
        from routes.liluvine_kb import build_kb_context
        # Lot 23 — un prospect ne reçoit que les entrées « tous » et « prospects » de la base.
        kb = await build_kb_context(db, max_chars=4000, query=requete_recherche(text_modele, historique),
                                    audience="prospects" if is_prospect else "clients")  # smaller budget for WA
    except Exception:
        kb = ""
    # Lot 344 — mémoire des conversations (Qdrant) : extraits pertinents des anciens échanges de CE numéro (jamais d'un autre client)
    try:
        from routes.wa_memoire_qdrant import contexte_pour_ia
        memoire_ctx = await contexte_pour_ia(db, phone_digits=phone_digits, client_id=scope_uid,
                                             requete=requete_recherche(text_modele, historique))
    except Exception:  # noqa: BLE001
        memoire_ctx = ""
    contact_tag = ""
    if contact and contact.get("name"):
        contact_tag = f"\n\nContact qui écrit : {contact['name']} ({contact.get('code') or phone_digits})"
    # Lot Liluvine (2026-09) — prompt système du tenant (liluvine_pro_system_prompt),
    # jusqu'ici seulement appliqué au chat web malgré la doc UI qui prétendait
    # le contraire (voir LiluvineSystemPromptSection.jsx) — désormais partagé
    # avec l'auto-réponse WhatsApp. Version SANS règle d'escalade (celle du
    # chat web) : la réponse WA a déjà son propre marqueur d'escalade
    # `[ESCALATE: ...]`, ajouté séparément juste plus bas via ESCALATE_PROMPT_HINT.
    # Lot 21 — Prospect : prompt dédié (settings.global
    # `liluvine_wa_prospect_system_prompt`, sinon le prompt prospect par défaut).
    # Client : prompt du tenant, comme avant.
    if is_prospect:
        base_prompt = (
            (settings_doc.get("liluvine_wa_prospect_system_prompt") or "").strip()
            or DEFAULT_WA_PROSPECT_SYSTEM_PROMPT
        )
        # Lot 188 — numéro inconnu rattaché au client par défaut : prompt « client à jour » s'il est rempli
        if client_defaut_utilise:
            base_prompt = prompt_selon_contrat(settings_doc, "valide") or base_prompt
    else:
        base_prompt = await _resolve_base_system_prompt(db, scope_uid)
        # Lot 183 — prompt propre aux clients à jour / en retard (vide = prompt du compte, comme avant)
        base_prompt = prompt_selon_contrat(settings_doc, etat_contrat_cl) or base_prompt
    # Lot 21 — consignes « Mode WhatsApp » modifiables (vide = texte d'origine).
    mode_instructions = (
        (settings_doc.get("liluvine_wa_mode_instructions") or "").strip()
        or DEFAULT_WA_MODE_INSTRUCTIONS
    )
    # Lot 316 — niveaux de service (contrat / standard / EXPRESS) : questions, délais, tarif, prévenir le propriétaire (vide si non configuré)
    try:
        from routes import niveaux_service_liluvine as _nsl
        express_bloc = await _nsl.bloc_pour_prompt(db, client_eff, etat_contrat_cl)
    except Exception:  # noqa: BLE001
        express_bloc = ""
    sys_text = (
        base_prompt
        + "\n\n[IMPORTANT — Mode auto-réponse WhatsApp]\n"
        + mode_instructions
        + (("\n" + ctx) if ctx else "")
        + (("\n" + biz_ctx) if biz_ctx else "")
        + (("\n\n" + kb) if kb else "")
        + (("\n\n" + memoire_ctx) if memoire_ctx else "")     # lot 344 : mémoire des conversations
        + contact_tag
        + offre_bloc          # lot 163 : offre du client lié (vide si aucune)
        + consignes_conversation(bool(offre_bloc), settings_doc.get("liluvine_wa_consignes_conversation"))   # lots 179/184
        + express_bloc        # lot 316 : niveaux de service et EXPRESS (vide si la rubrique n'est pas activée)
    )
    # Lot 59 — consignes propres à la ligne qui a reçu le message (ex. accueil VIP)
    try:
        from routes.numeros_wa import complement_prompt_ligne
        sys_text = sys_text + await complement_prompt_ligne(settings_doc)
    except Exception:  # noqa: BLE001
        pass
    # S036 — Allow Liluvine to flag herself as needing human help. The
    # marker [ESCALATE: <reason>] will be stripped from the user-facing
    # reply and trigger a WhatsApp notification to the admin.
    try:
        from routes.liluvine_escalation import ESCALATE_PROMPT_HINT
        sys_text = sys_text + ESCALATE_PROMPT_HINT
    except Exception:  # noqa: BLE001
        pass

    # Lot 199 — publication de SAWALI (modèle, carrousel, formulaire, sondage, campagne…) à laquelle le client répond :
    # son type et son titre sont donnés à Liluvine, qui peut ainsi répondre à une question sans redemander l'objet.
    try:
        from routes import wa_publication_contexte as _pub
        sys_text = sys_text + _pub.texte_contexte(await _pub.contexte_reponse(db, inbound_doc))
        if clic_bouton:
            sys_text = sys_text + (f"\n\nLe client n'a pas écrit : il a cliqué sur le bouton « {text[:60]} » d'un message de SAWALI. "
                                   "Remercie-le de sa réponse en UNE phrase courte, confirme que sa réponse est bien prise en compte "
                                   "si le contexte le permet, et propose-lui de poser sa question s'il a besoin d'une précision. "
                                   "Ne le classe pas et n'ouvre aucune demande.")
    except Exception:  # noqa: BLE001
        logger.warning("[wa_autoreply] contexte de la publication indisponible", exc_info=True)

    # Call the LLM
    api_key = _cle_ia()
    if not api_key:
        try:
            from routes.llm_health import record_llm_outcome
            await record_llm_outcome(db, ok=False, error="ANTHROPIC_API_KEY missing", context="liluvine_wa_autoreply")
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "reason": "ANTHROPIC_API_KEY missing"}
    try:
        from ia_client import LlmChat, UserMessage
    except Exception as exc:
        return {"ok": False, "reason": f"llm_import_failed: {exc!r}"}
    # Reuse a stable session per phone so the bot keeps context if the user
    # writes again within the same conversation.
    # Lot 181 — classement de la conversation (Technique, Comptabilité…) : consignes + conversation déjà classée ?
    from routes import liluvine_classement as _clas
    classement_actif = _clas.actif(settings_doc)
    cats_classement = _clas.categories(settings_doc)
    if classement_actif:
        deja_classe = None
        try:
            sess = await db.liluvine_pro_sessions.find_one({"id": session_id}, {"_id": 0, "classement": 1, "updated_at": 1}) or {}
            deja_classe = _clas.classement_encore_valide(sess.get("classement"), sess.get("updated_at"))   # lot 190
        except Exception:  # noqa: BLE001
            deja_classe = None
        sys_text = sys_text + _clas.consignes_classement(cats_classement, deja_classe)
    else:
        deja_classe = None
    try:
        chat = LlmChat(
            api_key=api_key, session_id=session_id, system_message=sys_text, initial_messages=historique,
        ).with_model("anthropic", "claude-haiku-4-5-20251001")
        reply = await chat.send_message(UserMessage(text=text_modele))
        try:
            from routes.llm_health import record_llm_outcome
            await record_llm_outcome(db, ok=True, context="liluvine_wa_autoreply")
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:
        logger.exception("[wa_autoreply] LLM error")
        try:
            from routes.llm_health import record_llm_outcome
            await record_llm_outcome(db, ok=False, error=str(exc), context="liluvine_wa_autoreply")
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "reason": f"llm_error: {str(exc)[:160]}"}
    reply = (reply or "").strip()
    if not reply:
        return {"ok": False, "reason": "empty_reply"}

    # S036 — Parse escalation marker, strip from user-facing reply,
    # and trigger an async notification to the admin.
    escalation_reason: Optional[str] = None
    try:
        from routes.liluvine_escalation import strip_escalation_marker, notify_admin
        reply, escalation_reason = strip_escalation_marker(reply)
        if escalation_reason:
            await notify_admin(
                db,
                contact_name=(contact or {}).get("name") if contact else None,
                contact_phone_digits=phone_digits,
                last_user_message=text,
                reason=escalation_reason,
                send_wa=wa_send_text,
                session_id=session_id,
                history=[{"role": "user", "text": text}, {"role": "assistant", "text": reply}],
            )
    except Exception:  # noqa: BLE001
        logger.exception("[wa_autoreply] escalation hook failed")
    # Lot 320 — marqueur [NIVEAUX] : retiré du texte ; les 3 boutons « Avec contrat / Sans contrat / En express » suivent la réponse
    afficher_niveaux = False
    try:
        from routes.niveaux_boutons import retirer_marqueur as _retirer_niveaux
        reply, afficher_niveaux = _retirer_niveaux(reply)
    except Exception:  # noqa: BLE001
        logger.exception("[wa_autoreply] marqueur niveaux ignoré")
    # If after stripping the marker the reply is empty, fall back to a
    # safe "we'll get back to you" message and still consider it a success.
    if not reply.strip():
        reply = "Merci pour votre message. Un agent humain va vous recontacter rapidement."

    # Lot 181 — marqueur [CLASSE: catégorie | motif] : retiré du texte ; si la conversation n'est pas déjà classée,
    # ticket (client connu) + mise en relation avec l'assistant IA de la catégorie (prénom et fonction).
    classement: Optional[Dict[str, Any]] = None
    agent_classe = None
    if classement_actif:
        reply, marque = _clas.extraire_classement(reply, cats_classement)
        if marque and not deja_classe:
            classement = dict(marque)
            try:
                from routes.liluvine_agents import get_agents, match_agent_for_message as match_agent_for_message_cl
                agents_cl = await get_agents(db)
                # catégorie → assistant ; à défaut, assistant dont la fonction correspond au sujet (même choix pour le texte et la signature)
                agent_classe = _clas.agent_pour_categorie(agents_cl, marque["categorie"]) \
                    or match_agent_for_message_cl(agents_cl, f"{marque['motif']} {text}")
            except Exception:  # noqa: BLE001
                agent_classe = None
            ticket_cl = None
            from routes import offre_client as _offre_cl
            client_ticket = client_lie or client_eff
            if not client_ticket:
                # Lot 186 — expéditeur non relié à un client (numéro inconnu) : ticket au client par défaut (SAWALI-2S, réglable)
                client_ticket = await _offre_cl.client_par_defaut(db, settings_doc, scope_uid)
            classement["client_defaut"] = bool(client_ticket) and not client_lie
            if client_ticket:
                contact_tk = contact or {"name": inbound_doc.get("from_profile_name") or inbound_doc.get("contact_name") or f"+{phone_digits}",
                                         "whatsapp": f"+{phone_digits}"}
                ticket_cl = await _offre_cl.ouvrir_ticket(
                    db, client_ticket, contact_tk, marque["motif"], text, motif=f"[{marque['categorie']}] {marque['motif']}",
                    categorie=marque["categorie"], source="liluvine_classement", nouveau=not client_lie)
                classement["ticket_statut"] = ("rattache" if (ticket_cl or {}).get("rattache") else "ouvert") if ticket_cl else "echec"
            else:
                classement["ticket_statut"] = "aucun_client"      # ni client relié ni client par défaut trouvé : pas de ticket
            classement["ticket"] = (ticket_cl or {}).get("number")
            classement["agent"] = (agent_classe or {}).get("prenom")
            # mise en relation (+ n° de ticket), puis la réponse tirée de la base de connaissances si Liluvine en a écrit une
            reponse_kb = reply.strip()
            reply = _clas.texte_mise_en_relation(agent_classe, marque["motif"], classement["ticket"])
            if reponse_kb:
                reply = f"{reply}\n\n{reponse_kb}"
            # Lot 195 — un seul flux : une demande technique devient aussi la requête REQ-… du client (liée au ticket) ;
            # le lien pour la préciser part vers Loois si le poste est en ligne, sinon il est ajouté à cette réponse WhatsApp.
            if client_ticket:
                from routes import liluvine_requete as _lreq
                req_cl = await _lreq.requete_depuis_classement(
                    db, client=client_ticket, contact_nom=(contact_tk or {}).get("name") or "", categorie_classement=marque["categorie"],
                    motif=marque["motif"], texte=text, ticket_numero=classement["ticket"],
                    base_url=os.environ.get("SAWALI_SITE_URL") or "https://sawalismartsystems.com")
                if req_cl:
                    classement["requete"] = req_cl["numero"]
                    classement["lien_via"] = "loois" if req_cl["via_loois"] else "whatsapp"
                    if req_cl["nouvelle"]:
                        reply = f"{reply}\n\n{_lreq.texte_lien(req_cl['numero'], req_cl['url'], req_cl['via_loois'])}"

    reply = retirer_signatures_fin(reply)    # lot 191 : la signature est ajoutée UNE seule fois, plus bas

    # Signature nominative : jusqu'à 5 agents (prénom + spécialité), paramétrés
    # par l'admin. L'agent dont le rôle correspond au contenu du message signe
    # la réponse à la place de la signature générique — même si c'est bien
    # l'IA qui a exécuté le prompt système et rédigé le texte. Les commandes
    # `!...` ne passent JAMAIS ici (interceptées plus haut, avant should_autoreply).
    persona_signature = None
    matched_agent = None      # lot 303 : défini avant le try (le prénom est enregistré avec le message pour l'écran TV)
    try:
        from routes.liluvine_agents import get_agents, match_agent_for_message, build_signature
        agents = await get_agents(db)
        matched_agent = agent_classe or match_agent_for_message(agents, text)   # lot 181 : l'assistant du classement signe
        if matched_agent:
            persona_signature = build_signature(matched_agent)
    except Exception:  # noqa: BLE001
        logger.exception("[wa_autoreply][agents] persona matching failed")
    signature = persona_signature or (settings_doc.get("liluvine_wa_autoreply_signature") or "").strip()
    if not signature:
        signature = "— 🤖 Réponse automatique Liluvine PRO"
    final_text = f"{reply}\n\n{signature}" if signature else reply

    # Send via Meta Graph API
    quote_mid = inbound_doc.get("wa_message_id")
    send_res = await wa_send_text(inbound_doc.get("from") or f"+{phone_digits}", final_text,
                                  reply_to_message_id=quote_mid)
    if not send_res.get("ok"):
        return {"ok": False, "reason": f"send_failed: {send_res.get('error')}", "send": send_res}
    if afficher_niveaux and wa_send_interactive_button is not None:
        try:
            from routes.niveaux_boutons import BOUTONS as _BTN_NIV, TEXTE_CHOIX as _TXT_NIV
            await wa_send_interactive_button(inbound_doc.get("from") or f"+{phone_digits}", _TXT_NIV, _BTN_NIV[0][0], _BTN_NIV[0][1],
                                             extra_buttons=_BTN_NIV[1:])
        except Exception:  # noqa: BLE001 — les boutons sont un confort : la réponse est déjà partie
            logger.warning("[wa_autoreply] boutons des niveaux non envoyés", exc_info=True)

    # Quota tracking
    tokens = max(int((len(sys_text) + len(text) + len(final_text)) / 4), 1)
    try:
        from routes.ai_quotas import track_ai_usage
        # Lot 224 — la consommation est rattachée à la LIGNE qui a reçu le message (suivi par ligne et par période)
        from routes.numeros_wa import numero_recu_courant
        _numero_ligne = numero_recu_courant()
        _suivi_ia = await track_ai_usage(
            db, user=user_doc, resource="chat", units=tokens,
            model="claude-haiku-4-5-20251001",
            metadata={"source": "whatsapp_native", "phone_digits": phone_digits, "wa_numero_id": _numero_ligne},
        )
        if _numero_ligne:
            from routes.wa_usage_lignes import noter as _noter_usage
            await _noter_usage(db, phone_number_id=_numero_ligne, sens="out", type_msg="ia", destinataire=phone_digits,
                               ia={"tokens": tokens, "cout_xof": float((_suivi_ia or {}).get("cost_xof") or 0)})
    except Exception:
        pass

    # Persist the conversation (creates/updates a Liluvine session)
    session_doc = await db.liluvine_pro_sessions.find_one(
        {"id": session_id}, {"_id": 0, "id": 1}
    )
    if not session_doc:
        await db.liluvine_pro_sessions.insert_one({
            "id": session_id,
            "client_id": scope_uid,
            "user_id": user_doc["id"],
            "user_label": (contact or {}).get("name") or f"WA +{phone_digits}",
            "title": f"WA · +{phone_digits} · {text[:40]}",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "message_count": 0,
            "external_source": "whatsapp_native",
            "external_payload": {"phone_digits": phone_digits, "contact_id": (contact or {}).get("id")},
            "prospect": is_prospect,  # Lot 21
        })
    await db.liluvine_pro_messages.insert_one({
        "id": secrets.token_urlsafe(12),
        "session_id": session_id, "client_id": scope_uid,
        "user_id": user_doc["id"], "role": "user", "content": text,
        "external_source": "whatsapp_native",
        "wa_message_id_quoted": quote_mid,
        "created_at": _now_iso(),
    })
    out_msg_id = secrets.token_urlsafe(12)
    await db.liluvine_pro_messages.insert_one({
        "id": out_msg_id,
        "session_id": session_id, "client_id": scope_uid,
        "user_id": user_doc["id"], "role": "assistant", "content": final_text,
        "tokens": tokens, "model": "claude-haiku-4-5-20251001",
        "context_injected": bool(ctx),
        "prospect": is_prospect,  # Lot 21 — réponse faite avec le prompt prospect
        "external_source": "whatsapp_native",
        "wa_message_id_out": send_res.get("message_id"),
        "created_at": _now_iso(),
    })
    await db.liluvine_pro_sessions.update_one(
        {"id": session_id},
        {"$inc": {"message_count": 2}, "$set": {"updated_at": _now_iso(),
                                                **({"classement": {**classement, "at": _now_iso()}} if classement else {})}},
    )
    # Anti-flood state
    await db.liluvine_wa_autoreply_state.update_one(
        {"phone_digits": phone_digits},
        {"$set": {
            "phone_digits": phone_digits, "last_replied_at": _now_iso(),
            "last_message_in": text[:200], "last_message_out": final_text[:200],
            "tenant_id": scope_uid,
        }},
        upsert=True,
    )

    # Iter38r-fix9i — Also mirror the outgoing message into `whatsapp_messages`
    # so the conversation thread (Inbox Unifié, Centre de Messages, contact
    # detail panel) shows Liluvine's auto-reply inline with human messages.
    try:
        wa_log = {
            "id": secrets.token_urlsafe(12),
            "client_id": scope_uid,
            "tenant_id": scope_uid,
            "direction": "outbound",
            "from": "liluvine-pro",
            "to": inbound_doc.get("from") or f"+{phone_digits}",
            "phone_digits": phone_digits,
            "message_type": "text",
            "body": final_text,
            "wa_message_id": send_res.get("message_id"),
            "status": "sent",
            "wa_status": "sent",
            "sent_at": _now_iso(),
            "created_at": _now_iso(),
            "ai_generated": True,
            "ai_source": "liluvine_pro_autoreply",
            "ai_session_id": session_id,
            "agent_ia": (matched_agent or {}).get("prenom") or "Liluvine",   # lot 303 : pastille de l'agent sur l'écran TV
            "reply_to_wa_message_id": quote_mid,
            "contact_id": (contact or {}).get("id"),
        }
        await db.whatsapp_messages.insert_one(wa_log.copy())
    except Exception:  # noqa: BLE001
        logger.warning("[wa_autoreply] mirror to whatsapp_messages failed", exc_info=True)

    # Lot 184.1 — décision détaillée dans les journaux du serveur (diagnostic : qui est l'expéditeur, quel client est relié,
    # état du contrat, offre lue ou non, classement, ticket). Aucun secret : seulement des identifiants et des états.
    logger.info(
        "[wa_autoreply] decision tel=%s contact=%r societe=%r prospect=%s ligne_plateforme=%s client_lie=%r contrat=%s "
        "offre=%s classement=%s ticket=%s assistant=%s deja_classe=%s",
        phone_digits, (contact or {}).get("name"), (contact or {}).get("company"), is_prospect, platform_tenant,
        (client_eff or {}).get("company"), etat_contrat_cl, offre_statut,
        (classement or {}).get("categorie"), (classement or {}).get("ticket_statut"), (classement or {}).get("agent"), deja_classe)
    return {
        "ok": True, "reason": "sent",
        "wa_out_message_id": send_res.get("message_id"),
        "session_id": session_id, "reply_message_id": out_msg_id,
        "tokens": tokens, "prospect": is_prospect, "offre_statut": offre_statut,
        "classement": classement,
    }



# ====================================================================
# Iter43-fix22 (2026-06) — Public WA commands : !Garde, !Meteo
# ====================================================================
DELAI_GARDE_DEFAUT_HEURES = 3     # lot 339 : délai d'anti-répétition de la liste des pharmacies de garde


async def garde_deja_envoyee_recemment(db, phone_digits: str, settings_doc: Dict[str, Any], maintenant: Optional[datetime] = None) -> bool:
    """Lot 339 — vrai si la liste des pharmacies de garde (commande « !garde ») a déjà été envoyée à ce numéro dans les N dernières heures.
    N = réglage `garde_reply_anti_repetition_heures` (défaut 3 ; 0 = anti-répétition désactivée). Ne sert qu'aux demandes NON explicites."""
    try:
        heures = (settings_doc or {}).get("garde_reply_anti_repetition_heures")
        heures = DELAI_GARDE_DEFAUT_HEURES if heures in (None, "") else int(heures)
        if heures <= 0 or not phone_digits:
            return False
        depuis = ((maintenant or datetime.now(timezone.utc)) - timedelta(hours=heures)).isoformat()
        envoye = await db.whatsapp_messages.find_one(
            {"direction": "outbound", "phone_digits": phone_digits, "command": "!garde", "created_at": {"$gte": depuis}}, {"_id": 1})
        return envoye is not None
    except Exception:  # noqa: BLE001 — en cas de doute on répond (jamais de silence à cause d'une erreur de base)
        return False


async def _build_garde_reply(db) -> str:
    """Construit la réponse pour la commande `!Garde` : liste des officines
    de garde de la semaine en cours + message de prompt rétablissement.

    Iter43-fix24ah (2026-06-17) — Le filtre `status="active"` est retiré :
    si un admin a affecté un `groupe_garde` à une officine, elle fait partie
    de la rotation, quel que soit son statut de modération. Le filtre exclut
    désormais uniquement `suspended`.

    Iter43-fix24ai (2026-06-17) — Template configurable depuis Admin Settings
    (`settings.garde_reply_template`) avec syntaxe :
      - `{champ}`  → valeur texte du champ (ex: `{name}`)
      - `[champ]`  → lien cliquable (ex: `[phone]` → `tel:+226…`,
                     `[latitude,longitude]` → maps URL, `[whatsapp]` → wa.me/…)
      - Espace      → séparateur de champs
      - Saut de ligne → nouvelle officine
    Fallback sur le template hardcodé si non configuré.
    """
    today = datetime.now(timezone.utc).date()
    # Iter43-fix24az-e (2026-02-26) — Use centralized garde period resolver so
    # the `!Garde` header dates show the ACTUAL guard period boundaries
    # (Sat → Sat) instead of the ISO week's Mon → Sun in saturday_noon mode.
    try:
        from routes.garde_planning import _current_garde_period as _gp
        period = await _gp(db, now=datetime.now(timezone.utc))
        year, week = period["year"], period["week"]
        period_start, period_end = period["period_start"], period["period_end"]
    except Exception:  # noqa: BLE001
        iso = today.isocalendar()
        year, week = iso[0], iso[1]
        period_start = date.fromisocalendar(year, week, 1)
        period_end = date.fromisocalendar(year, week, 7)
    # Récupère le planning pour cette semaine
    entry = await db.garde_planning.find_one({"year": year, "week_number": week}, {"_id": 0})
    assist_group = None
    if not entry:
        # Calcule la rotation auto
        groups_set: set = set()
        async for o in db.officines.find({"groupe_garde": {"$nin": [None, ""]}}, {"groupe_garde": 1, "_id": 0}):
            try:
                groups_set.add(int(o["groupe_garde"]))
            except (TypeError, ValueError):
                continue
        if not groups_set:
            return ("📅 Aucun groupe de garde n'est encore configuré.\n\n"
                    "Pour configurer le planning des gardes, rendez-vous sur "
                    "https://sawalismartsystems.com/admin/garde-planning.")
        groups = sorted(groups_set)
        gg = groups[(week - 1) % len(groups)]
    else:
        gg = entry.get("groupe_garde")
        # Iter43-fix24az-r (2026-07-22) — Groupe d'assistance hebdo
        assist_group = entry.get("assist_group")
    # Liste des officines (status != suspended)
    officines: List[Dict[str, Any]] = []
    async for o in db.officines.find(
        {"groupe_garde": gg, "status": {"$ne": "suspended"}},
        {"_id": 0, "name": 1, "intitule": 1, "phone": 1, "whatsapp": 1,
         "address": 1, "city": 1, "location_hint": 1,
         "latitude": 1, "longitude": 1, "contact_name": 1, "email": 1},
    ).sort("name", 1):
        officines.append(o)
    # Iter43-fix24az-r — Officines du groupe d'assistance (si défini et distinct)
    assist_officines: List[Dict[str, Any]] = []
    if assist_group is not None and assist_group != gg:
        async for o in db.officines.find(
            {"groupe_garde": assist_group, "status": {"$ne": "suspended"}},
            {"_id": 0, "name": 1, "intitule": 1, "phone": 1, "whatsapp": 1,
             "address": 1, "city": 1, "location_hint": 1,
             "latitude": 1, "longitude": 1, "contact_name": 1, "email": 1},
        ).sort("name", 1):
            assist_officines.append(o)
    try:
        monday = period_start.strftime("%d/%m")
        sunday = period_end.strftime("%d/%m")
    except (AttributeError, ValueError):
        monday, sunday = "?", "?"
    # Lookup template configurable + CMS footer/site link (Iter43-fix24al)
    s = await db.settings.find_one(
        {"_id": "global"},
        {"_id": 0, "garde_reply_header": 1, "garde_reply_template": 1,
         "garde_reply_footer": 1, "garde_reply_site_url": 1},
    ) or {}
    template = s.get("garde_reply_template") or DEFAULT_GARDE_REPLY_TEMPLATE
    header_tpl = s.get("garde_reply_header") or DEFAULT_GARDE_REPLY_HEADER
    footer_tpl = s.get("garde_reply_footer") or DEFAULT_GARDE_REPLY_FOOTER
    site_url = s.get("garde_reply_site_url") or "https://sawalismartsystems.com"
    header = _render_garde_header(header_tpl, week=week, year=year, monday=monday,
                                  sunday=sunday, gg=gg, count=len(officines))
    # Iter43-fix24az-v (2026-07-22) — Import split hint constant so the
    # centralised auto-splitter in `_wa_send_text` breaks at the right seam
    # (between the main officines block and the assist officines block).
    try:
        from routes.whatsapp_helpers import _WA_SPLIT_HINT, _WA_TEXT_MAX
    except Exception:  # noqa: BLE001
        _WA_SPLIT_HINT = "\u2063\u2063"
        _WA_TEXT_MAX = 3800
    # Per-section budget: leave ~600 chars margin for header + footer + link.
    _section_budget = _WA_TEXT_MAX - 600
    lines = [header, ""]
    if not officines:
        lines.append("_Aucune officine dans ce groupe pour cette semaine._")
    else:
        rendered_count = 0
        current_len = sum(len(l_) + 1 for l_ in lines)
        for o in officines:
            rendered = _render_garde_officine(template, o)
            if not rendered.strip():
                continue
            piece_len = len(rendered) + 1
            if current_len + piece_len > _section_budget:
                # Budget reached — append site link and stop.
                remaining = len(officines) - rendered_count
                lines.append("")
                lines.append(f"_…et {remaining} autre(s) officine(s) — liste complète :_ {site_url}/garde")
                break
            lines.append(rendered)
            current_len += piece_len
            rendered_count += 1
    # Iter43-fix24az-r (2026-07-22) — Groupe d'assistance hebdo en italique
    # (nouvelle réglementation : chaque semaine un groupe standard est appuyé
    # par un « groupe d'appui » choisi parmi les groupes standards).
    #
    # Iter43-fix24az-s (2026-07-22) — FIX : ne PAS wrapper chaque ligne
    # d'officine dans `_..._` (italique WA), car les noms d'officines
    # contiennent des underscores (`Off_07968122`, `Off_8059c1ee`, ...) qui
    # cassent le pattern d'italique WhatsApp et rendent le message vide côté
    # client. Solution : garder l'italique UNIQUEMENT sur le titre de section
    # (safe, aucun `_` dans le libellé), puis préfixer chaque officine avec
    # `↳ ` pour indiquer visuellement l'appartenance au groupe d'appui.
    #
    # Iter43-fix24az-v (2026-07-22) — Insert an INVISIBLE SPLIT HINT before
    # the assist section so `_wa_send_text` can break the payload into two
    # sequential WhatsApp messages (main / assist) whenever the combined
    # length would exceed the 4096-char cap.
    if assist_officines:
        lines.append("")
        lines.append(_WA_SPLIT_HINT)  # semantic seam for auto-splitter
        lines.append(f"🤝 _Groupe d'appui G{assist_group} — {len(assist_officines)} officine(s) :_")
        assist_rendered = 0
        assist_len = 0
        for o in assist_officines:
            rendered = _render_garde_officine(template, o)
            if not rendered.strip():
                continue
            # Préfixe la 1re ligne avec `↳ ` et indente les suivantes de 2 espaces
            # pour un rendu visuel cohérent (comme une continuation).
            parts = [p for p in rendered.split("\n") if p.strip()]
            if not parts:
                continue
            block_lines = [f"↳ {parts[0].strip()}"]
            for sub in parts[1:]:
                block_lines.append(f"   {sub.strip()}")
            block_text = "\n".join(block_lines)
            piece_len = len(block_text) + 1
            if assist_len + piece_len > _section_budget:
                remaining = len(assist_officines) - assist_rendered
                lines.append(f"↳ _…et {remaining} autre(s) officine(s) d'appui — liste complète :_ {site_url}/garde")
                break
            lines.extend(block_lines)
            assist_len += piece_len
            assist_rendered += 1
    # Iter43-fix24al — Configurable footer (replaces hardcoded "Prompt rétablissement").
    # Also ALWAYS include the site link so contacts can navigate to /garde.
    footer = _render_garde_header(footer_tpl, week=week, year=year, monday=monday,
                                   sunday=sunday, gg=gg, count=len(officines))
    if footer.strip():
        lines.append("")
        lines.append(footer)
    lines.append("")
    lines.append(f"🌐 {site_url}/garde")
    return "\n".join(lines)


# ====================================================================
# Iter43-fix24ai (2026-06-17) — Template configurable pour `!garde`
# ====================================================================
DEFAULT_GARDE_REPLY_HEADER = (
    "🏥 *Officines de garde — Semaine {week}* ({monday} au {sunday})\n"
    "*Groupe {gg}* — {count} officine{plural}"
)

# Template par défaut : nom en gras, adresse, téléphone cliquable, géoloc cliquable.
# `{x}` = valeur texte ; `[x]` = lien cliquable (tel:, wa.me, maps).
# `[latitude,longitude]` est une forme spéciale → ouvre Google Maps.
DEFAULT_GARDE_REPLY_TEMPLATE = (
    "• *{name}*\n"
    "  📍 {location_hint} {city}\n"
    "  📞 [phone]\n"
    "  📍 [latitude,longitude]"
)

# Iter43-fix24al (2026-06-17) — Default footer (used when admin hasn't
# configured `settings.garde_reply_footer`).
DEFAULT_GARDE_REPLY_FOOTER = (
    "💚 _Prompt rétablissement et bonne santé !_\n"
    "_— Liluvine PRO 🤖_"
)


def _render_garde_header(template: str, *, week: int, year: int, monday: str,
                          sunday: str, gg: Any, count: int) -> str:
    """Render header with `{week}`, `{year}`, `{monday}`, `{sunday}`, `{gg}`,
    `{count}`, `{plural}` placeholders."""
    plural = "s" if count > 1 else ""
    ctx = {
        "week": week, "year": year, "monday": monday, "sunday": sunday,
        "gg": gg or "?", "count": count, "plural": plural,
    }
    def _repl(m: "re.Match") -> str:
        k = m.group(1)
        return str(ctx.get(k, m.group(0)))
    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", _repl, template)


def _format_phone_link(value: str) -> str:
    """Render a phone number as a WhatsApp-friendly clickable link.
    WhatsApp auto-links phone numbers in messages, so we just keep the value.
    For display we also prefix `tel:` is not necessary — WhatsApp clients
    handle phone numbers natively."""
    digits = re.sub(r"[^\d+]", "", value or "")
    if not digits:
        return value
    return digits  # WhatsApp auto-detects this as tappable


def _format_maps_link(lat: Any, lng: Any) -> str:
    """Build a Google Maps URL from lat,lng. WhatsApp will preview the link."""
    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (TypeError, ValueError):
        return ""
    return f"https://maps.google.com/?q={lat_f},{lng_f}"


def _render_garde_officine(template: str, o: Dict[str, Any]) -> str:
    """Render one officine line(s) using the configurable template.

    Syntax:
      - `{field}`  → plain text value of the field (empty string if missing)
      - `[field]`  → "link" version : phone → just the digits (WhatsApp auto-links),
                     whatsapp → `https://wa.me/<digits>`, email → `mailto:`,
                     latitude,longitude → maps URL.
      - any other text is kept as-is.

    Example template:
        "• *{name}* — [phone] — [latitude,longitude]"
    """
    # Build a lookup that combines plain fields with sensible defaults.
    name = o.get("intitule") or o.get("name") or "—"
    phone = o.get("phone") or ""
    whatsapp = o.get("whatsapp") or ""
    address = o.get("address") or ""
    city = o.get("city") or ""
    location_hint = o.get("location_hint") or ""
    email = o.get("email") or ""
    contact_name = o.get("contact_name") or ""
    latitude = o.get("latitude")
    longitude = o.get("longitude")
    plain = {
        "name": name,
        "phone": phone,
        "whatsapp": whatsapp,
        "address": address,
        "city": city,
        "location_hint": location_hint,
        "email": email,
        "contact_name": contact_name,
        "latitude": "" if latitude is None else str(latitude),
        "longitude": "" if longitude is None else str(longitude),
    }
    # Replace `[latitude,longitude]` first (composite) before single-field [x]
    def _bracket_repl(m: "re.Match") -> str:
        key = m.group(1).strip()
        # Composite: lat,lng → maps URL
        if "," in key:
            keys = [k.strip() for k in key.split(",")]
            if set(keys) == {"latitude", "longitude"} or keys == ["latitude", "longitude"]:
                return _format_maps_link(latitude, longitude)
            # Fallback: join with comma
            return ",".join(plain.get(k, "") for k in keys)
        # Single field link forms
        if key == "phone":
            return _format_phone_link(phone)
        if key == "whatsapp":
            digits = re.sub(r"[^\d]", "", whatsapp or "")
            return f"https://wa.me/{digits}" if digits else ""
        if key == "email":
            return f"mailto:{email}" if email else ""
        if key in ("latitude", "longitude"):
            return _format_maps_link(latitude, longitude)
        return plain.get(key, "")

    def _brace_repl(m: "re.Match") -> str:
        key = m.group(1).strip()
        return str(plain.get(key, ""))

    rendered = re.sub(r"\[([^\[\]]+)\]", _bracket_repl, template)
    rendered = re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", _brace_repl, rendered)
    # Clean up: collapse multiple spaces (introduced when a field was empty)
    # but preserve newlines.
    cleaned_lines = []
    for line in rendered.split("\n"):
        cleaned_lines.append(re.sub(r" +", " ", line).strip())
    # Drop empty lines that resulted purely from missing fields
    return "\n".join(l for l in cleaned_lines if l)


async def _build_meteo_reply(db, cmd_text: str, phone_digits: str) -> str:
    """Construit la réponse pour la commande `!Meteo [+N]`.

    `!Meteo`     → météo actuelle de la ville détectée du visiteur
    `!Meteo +3`  → prévisions à +1h, +2h, +3h (max +5h)
    """
    # Parse offset
    m = re.match(r"^[!/](?:meteo|météo)\s*(?:\+\s*(\d+))?\s*(.*)$", cmd_text.strip(), re.IGNORECASE)
    offset = 0
    explicit_city = ""
    if m:
        if m.group(1):
            try:
                offset = max(0, min(5, int(m.group(1))))
            except (TypeError, ValueError):
                offset = 0
        explicit_city = (m.group(2) or "").strip()
    # Ville par défaut depuis settings
    settings_doc = await db.settings.find_one({"_id": "global"}, {"_id": 0,
        "weather_widget_default_city": 1, "weather_widget_default_country": 1,
        "company_city": 1, "company_country": 1}) or {}
    city = explicit_city or settings_doc.get("weather_widget_default_city") \
           or settings_doc.get("company_city") or "Ouagadougou"
    # Geocode + weather
    try:
        async with httpx.AsyncClient(timeout=6.0) as http:
            geo_r = await http.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "fr"},
            )
            if geo_r.status_code >= 300:
                return f"☁️ Impossible de localiser la ville « {city} »."
            geo = geo_r.json().get("results") or []
            if not geo:
                return f"☁️ Ville inconnue : « {city} ». Essayez `!meteo Ouagadougou` ou `!meteo Paris`."
            top = geo[0]
            lat, lon = top["latitude"], top["longitude"]
            city_name = top.get("name") or city
            country = top.get("country_code") or ""
            w_r = await http.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat, "longitude": lon,
                    "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
                    "hourly": "temperature_2m,weather_code,precipitation_probability",
                    "forecast_days": 1,
                    "temperature_unit": "celsius",
                    "wind_speed_unit": "kmh",
                    "timezone": "auto",
                },
            )
            if w_r.status_code >= 300:
                return "☁️ Service météo indisponible. Réessayez plus tard."
            data = w_r.json() or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[wa_meteo] HTTP error: %s", exc)
        return "☁️ Erreur réseau lors de la récupération de la météo. Réessayez."
    cur = data.get("current") or {}
    code = int(cur.get("weather_code") or 0)
    # Mini map des codes WMO → emoji + libellé FR
    icon_label = {
        0: ("☀️", "ensoleillé"), 1: ("🌤️", "principalement clair"),
        2: ("⛅", "partiellement nuageux"), 3: ("☁️", "couvert"),
        45: ("🌫️", "brouillard"), 48: ("🌫️", "brouillard givrant"),
        51: ("🌦️", "bruine légère"), 53: ("🌦️", "bruine"), 55: ("🌦️", "bruine dense"),
        61: ("🌧️", "pluie légère"), 63: ("🌧️", "pluie modérée"), 65: ("🌧️", "pluie forte"),
        71: ("🌨️", "neige légère"), 73: ("🌨️", "neige"), 75: ("🌨️", "neige forte"),
        80: ("🌦️", "averses"), 81: ("🌧️", "averses modérées"), 82: ("⛈️", "averses violentes"),
        95: ("⛈️", "orage"), 96: ("⛈️", "orage + grêle"), 99: ("⛈️", "orage violent"),
    }
    emo, label = icon_label.get(code, ("☁️", "conditions inconnues"))
    lines = [
        f"{emo} *Météo {city_name}* ({country})" if country else f"{emo} *Météo {city_name}*",
        f"*{round(cur.get('temperature_2m') or 0)}°C* · {label}",
        f"_Ressenti {round(cur.get('apparent_temperature') or 0)}°C · "
        f"Vent {round(cur.get('wind_speed_10m') or 0)} km/h · "
        f"Humidité {cur.get('relative_humidity_2m')}%_",
    ]
    if offset > 0:
        hourly = data.get("hourly") or {}
        times = hourly.get("time") or []
        temps = hourly.get("temperature_2m") or []
        codes = hourly.get("weather_code") or []
        probs = hourly.get("precipitation_probability") or []
        # Trouver l'index "current hour" dans la liste horaire
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00")
        try:
            idx = next(i for i, t in enumerate(times) if t >= now_iso)
        except StopIteration:
            idx = 0
        lines.append("\n*Prochaines heures :*")
        for h in range(1, offset + 1):
            i = idx + h
            if i >= len(times):
                break
            t = times[i].split("T")[-1]
            c = codes[i] if i < len(codes) else 0
            emo_h, lbl_h = icon_label.get(int(c), ("☁️", ""))
            p = probs[i] if i < len(probs) else 0
            lines.append(f"  • {t} · {emo_h} {round(temps[i])}°C · pluie {p}%")
    lines.append("\n_— Liluvine PRO 🤖_")
    return "\n".join(lines)



# ====================================================================
# Iter43-fix24j (2026-06) — Commandes publiques étendues : !adresse / !horaires / !stock
# ====================================================================
async def _wa_send_location(
    to_e164: str,
    *,
    latitude: float,
    longitude: float,
    name: Optional[str] = None,
    address: Optional[str] = None,
    settings_doc: Optional[Dict[str, Any]] = None,
    db_ref: Any = None,
) -> Dict[str, Any]:
    """Envoie un message WhatsApp de type `location` (carte avec aperçu Google Maps).

    Utilisé par `!adresse` pour partager la géolocalisation cliquable de l'enseigne
    — l'utilisateur peut ouvrir directement dans son app de cartographie.
    """
    s = settings_doc
    if s is None and db_ref is not None:
        s = await db_ref.settings.find_one({"_id": "global"}) or {}
    s = s or {}
    access_token = s.get("wa_access_token")
    # Lot 59 — réponse depuis le numéro qui a reçu le message (Standard / VIP…)
    from routes.numeros_wa import numero_reponse
    phone_number_id = numero_reponse(s)
    wa_graph_version = s.get("wa_graph_version") or "v22.0"
    if not access_token or not phone_number_id:
        return {"ok": False, "error": "WhatsApp non configuré (token ou phone_number_id manquant)"}
    to_clean = "".join(ch for ch in (to_e164 or "") if ch.isdigit())
    if len(to_clean) < 6:
        return {"ok": False, "error": f"Numéro invalide « {to_e164} »"}
    body = {
        "messaging_product": "whatsapp",
        "to": to_clean,
        "type": "location",
        "location": {
            "latitude": str(latitude),
            "longitude": str(longitude),
        },
    }
    if name:
        body["location"]["name"] = str(name)[:200]
    if address:
        body["location"]["address"] = str(address)[:500]
    url = f"https://graph.facebook.com/{wa_graph_version}/{phone_number_id}/messages"
    try:
        async with httpx.AsyncClient(timeout=12) as http:
            r = await http.post(
                url, json=body,
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            )
            try:
                raw = r.json()
            except Exception:
                raw = {"text": r.text[:500]}
            if r.status_code < 300:
                mid = (raw.get("messages") or [{}])[0].get("id") if isinstance(raw, dict) else None
                return {"ok": True, "message_id": mid, "raw": raw}
            return {"ok": False, "error": str(raw)[:300], "status": r.status_code, "raw": raw}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}


# ====================================================================
# Iter43-fix24al (2026-06-17) — `_wa_send_image` helper used by `!garde`
# to send the optional "click-here" capture image as a 2nd WA message.
#
# Accepts either an HTTPS URL (preferred — Meta downloads it) OR a
# data:image/...;base64,... URI (we strip the prefix and POST the bytes
# to /media first to get a media_id, then send by media_id).
# ====================================================================
async def _wa_send_image(
    to_e164: str,
    image_src: str,
    *,
    caption: Optional[str] = None,
    settings_doc: Optional[Dict[str, Any]] = None,
    db_ref=None,
) -> Dict[str, Any]:
    """Send a WhatsApp `image` message.

    Returns {"ok": bool, "message_id"?: str, "error"?: str}.
    Silently no-ops (returns ok=False) when WhatsApp is not configured —
    callers should not crash on this.
    """
    s = settings_doc
    if s is None and db_ref is not None:
        s = await db_ref.settings.find_one({"_id": "global"}) or {}
    s = s or {}
    access_token = s.get("wa_access_token")
    # Lot 59 — réponse depuis le numéro qui a reçu le message (Standard / VIP…)
    from routes.numeros_wa import numero_reponse
    phone_number_id = numero_reponse(s)
    wa_graph_version = s.get("wa_graph_version") or "v22.0"
    if not access_token or not phone_number_id:
        return {"ok": False, "error": "WhatsApp non configuré"}
    to_clean = "".join(ch for ch in (to_e164 or "") if ch.isdigit())
    if len(to_clean) < 6:
        return {"ok": False, "error": f"Numéro invalide « {to_e164} »"}
    if not image_src:
        return {"ok": False, "error": "image_src vide"}

    image_block: Dict[str, Any] = {}
    # data: URI → upload first to /media
    if image_src.startswith("data:image/"):
        try:
            import base64 as _b64
            header_part, b64_part = image_src.split(",", 1)
            mime = header_part.split(";")[0][5:]  # "image/png"
            blob = _b64.b64decode(b64_part)
            upload_url = f"https://graph.facebook.com/{wa_graph_version}/{phone_number_id}/media"
            async with httpx.AsyncClient(timeout=20) as http:
                files = {"file": ("garde.png", blob, mime)}
                data = {"messaging_product": "whatsapp", "type": mime}
                ru = await http.post(
                    upload_url, headers={"Authorization": f"Bearer {access_token}"},
                    files=files, data=data,
                )
                try:
                    ru_json = ru.json()
                except Exception:
                    ru_json = {"text": ru.text[:500]}
                if ru.status_code >= 300:
                    return {"ok": False, "error": f"media upload failed: {ru_json}", "status": ru.status_code}
                media_id = ru_json.get("id")
                if not media_id:
                    return {"ok": False, "error": f"media upload: no id in {ru_json}"}
                image_block = {"id": media_id}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"data URI parse failed: {exc}"}
    elif image_src.startswith("http://") or image_src.startswith("https://"):
        image_block = {"link": image_src}
    else:
        return {"ok": False, "error": "image_src must be http(s):// or data:image/...;base64,..."}

    if caption:
        image_block["caption"] = str(caption)[:1024]

    body = {
        "messaging_product": "whatsapp",
        "to": to_clean,
        "type": "image",
        "image": image_block,
    }
    url = f"https://graph.facebook.com/{wa_graph_version}/{phone_number_id}/messages"
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.post(
                url, json=body,
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            )
            try:
                raw = r.json()
            except Exception:
                raw = {"text": r.text[:500]}
            if r.status_code < 300:
                mid = (raw.get("messages") or [{}])[0].get("id") if isinstance(raw, dict) else None
                return {"ok": True, "message_id": mid, "raw": raw}
            return {"ok": False, "error": str(raw)[:300], "status": r.status_code, "raw": raw}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}


def _resolve_brand_info(settings_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Compose le profil "marque/HQ" affiché par les commandes publiques.

    Mélange les nouveaux champs `liluvine_wa_brand_*` (prioritaires) avec
    les anciens champs génériques (`company_phone`, `public_brand_name`, etc.).
    """
    s = settings_doc or {}

    def _pick(*keys: str) -> str:
        for k in keys:
            v = s.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    def _num(v: Any) -> Optional[float]:
        try:
            if v in (None, ""):
                return None
            return float(v)
        except (TypeError, ValueError):
            return None

    return {
        "name": _pick("liluvine_wa_brand_name", "public_brand_name") or "SAWALI SMART SYSTEMS",
        "phone": _pick("liluvine_wa_brand_phone", "company_phone"),
        "whatsapp": _pick("liluvine_wa_brand_whatsapp", "liluvine_wa_brand_phone", "company_phone"),
        "email": _pick("liluvine_wa_brand_email"),
        "address": _pick("liluvine_wa_brand_address"),
        "city": _pick("liluvine_wa_brand_city"),
        "country": _pick("liluvine_wa_brand_country"),
        "location_hint": _pick("liluvine_wa_brand_location_hint"),
        "latitude": _num(s.get("liluvine_wa_brand_latitude")),
        "longitude": _num(s.get("liluvine_wa_brand_longitude")),
        "hours": _pick("liluvine_wa_brand_hours"),
        "maps_url": _pick("liluvine_wa_brand_maps_url"),
    }


def _build_maps_url(brand: Dict[str, Any]) -> str:
    """Génère l'URL Google Maps (priorité au champ personnalisé, sinon coords, sinon recherche texte)."""
    if brand.get("maps_url"):
        return brand["maps_url"]
    lat = brand.get("latitude")
    lon = brand.get("longitude")
    if lat is not None and lon is not None:
        return f"https://www.google.com/maps?q={lat},{lon}"
    bits = [brand.get("address"), brand.get("city"), brand.get("country")]
    q = ", ".join([b for b in bits if b])
    if q:
        import urllib.parse as _urlp
        return f"https://www.google.com/maps/search/?api=1&query={_urlp.quote(q)}"
    return ""


async def _build_adresse_reply(db) -> Dict[str, Any]:
    """Construit la réponse pour `!adresse`.

    Retourne un dict `{text, location}` :
      - `text` : message texte avec nom + phone + WA + adresse + lien maps
      - `location` : si lat/lon configurés → dict pour l'envoi WA type=location
    """
    s = await db.settings.find_one({"_id": "global"}) or {}
    brand = _resolve_brand_info(s)
    lines = [f"📍 *{brand['name']}*"]
    if brand["address"] or brand["city"]:
        addr_bits = [brand.get("address"), brand.get("city"), brand.get("country")]
        addr_full = ", ".join([b for b in addr_bits if b])
        lines.append(f"🏠 {addr_full}")
    if brand["location_hint"]:
        lines.append(f"🧭 {brand['location_hint']}")
    if brand["phone"]:
        lines.append(f"📞 {brand['phone']}")
    if brand["whatsapp"] and brand["whatsapp"] != brand["phone"]:
        lines.append(f"💬 WhatsApp : {brand['whatsapp']}")
    if brand["email"]:
        lines.append(f"✉️ {brand['email']}")
    maps_url = _build_maps_url(brand)
    if maps_url:
        lines.append(f"\n🗺️ Itinéraire : {maps_url}")
    if brand["hours"]:
        lines.append(f"\n🕒 *Horaires :*\n{brand['hours']}")
    lines.append("\n_— Liluvine PRO 🤖_")
    text = "\n".join(lines)
    location = None
    if brand["latitude"] is not None and brand["longitude"] is not None:
        location = {
            "latitude": brand["latitude"],
            "longitude": brand["longitude"],
            "name": brand["name"],
            "address": ", ".join(
                [b for b in [brand.get("address"), brand.get("city"), brand.get("country")] if b]
            ) or brand["location_hint"] or None,
        }
    return {"text": text, "location": location, "brand": brand}


_DAY_NAMES_FR = {
    0: "Lundi", 1: "Mardi", 2: "Mercredi", 3: "Jeudi",
    4: "Vendredi", 5: "Samedi", 6: "Dimanche",
}


async def _build_horaires_reply(db) -> str:
    """Construit la réponse pour `!horaires`.

    Lit `liluvine_wa_brand_hours` (texte libre multi-lignes ou format `lun:08-19`).
    Marque visuellement le jour courant (➡️).
    """
    s = await db.settings.find_one({"_id": "global"}) or {}
    brand = _resolve_brand_info(s)
    today_idx = datetime.now(timezone.utc).weekday()  # 0=Mon ... 6=Sun
    if not brand["hours"]:
        return (
            f"🕒 *Horaires d'ouverture — {brand['name']}*\n\n"
            "_Les horaires ne sont pas encore configurés. "
            "Contactez-nous au "
            f"{brand['phone'] or '_(non renseigné)_'} pour plus d'info._\n\n"
            "_— Liluvine PRO 🤖_"
        )
    today_lbl = _DAY_NAMES_FR[today_idx].lower()
    out_lines = [f"🕒 *Horaires d'ouverture — {brand['name']}*", ""]
    found_today = False
    for raw in brand["hours"].splitlines():
        line = raw.strip()
        if not line:
            continue
        lower = line.lower()
        if today_lbl in lower or lower.startswith(today_lbl[:3]):
            out_lines.append(f"➡️ *{line}*  ← _aujourd'hui_")
            found_today = True
        else:
            out_lines.append(f"   {line}")
    if not found_today:
        out_lines.append(f"\n_Nous sommes {_DAY_NAMES_FR[today_idx]}._")
    out_lines.append("\n_— Liluvine PRO 🤖_")
    return "\n".join(out_lines)


async def _build_stock_reply(db, args: str) -> str:
    """Construit la réponse pour `!stock <médicament>`.

    Recherche `args` (case-insensitive) dans `officine_inventory_items.product_name`,
    join avec `officines` pour récupérer le contact, retourne au max 5 résultats
    classés par quantité décroissante. Ne retourne que les items `available=True`
    avec `quantity > 0` et n'appartenant pas à une officine `suspended`.
    """
    query = (args or "").strip()
    if len(query) < 2:
        return (
            "❓ *Recherche de stock*\n\n"
            "Utilisation : `!stock <nom du médicament>`\n"
            "Exemple : `!stock paracétamol`\n\n"
            "_— Liluvine PRO 🤖_"
        )
    pattern = re.escape(query)
    items: List[Dict[str, Any]] = []
    cursor = db.officine_inventory_items.find(
        {
            "product_name": {"$regex": pattern, "$options": "i"},
            "available": True,
            "quantity": {"$gt": 0},
        },
        {"_id": 0, "officine_id": 1, "product_name": 1, "quantity": 1, "unit_price": 1, "currency": 1, "expiry_date": 1, "cip": 1},
    ).sort("quantity", -1).limit(20)
    async for it in cursor:
        items.append(it)
    if not items:
        return (
            f"🔎 *Recherche : « {query[:50]} »*\n\n"
            "❌ Aucune officine n'a ce produit en stock actuellement.\n\n"
            "_Conseil : essayez avec un nom plus court ou la marque générique._\n\n"
            "_— Liluvine PRO 🤖_"
        )
    officine_ids = list({it["officine_id"] for it in items})
    officines_map: Dict[str, Dict[str, Any]] = {}
    async for o in db.officines.find(
        {"id": {"$in": officine_ids}, "status": {"$ne": "suspended"}},
        {"_id": 0, "id": 1, "name": 1, "phone": 1, "whatsapp": 1, "city": 1, "location_hint": 1, "latitude": 1, "longitude": 1},
    ):
        officines_map[o["id"]] = o
    items = [it for it in items if it["officine_id"] in officines_map]
    if not items:
        return (
            f"🔎 *Recherche : « {query[:50]} »*\n\n"
            "❌ Le produit existe mais aucune officine active ne le propose actuellement.\n\n"
            "_— Liluvine PRO 🤖_"
        )
    items = items[:5]
    lines = [f"💊 *Stock — « {query[:50]} »*", f"_{len(items)} officine{'s' if len(items) > 1 else ''} avec ce produit_", ""]
    for it in items:
        off = officines_map[it["officine_id"]]
        name = off.get("name") or "—"
        qty = it.get("quantity") or 0
        price = it.get("unit_price")
        currency = it.get("currency") or "XOF"
        line_bits = [f"🏥 *{name}*"]
        addr = ", ".join([b for b in [off.get("location_hint"), off.get("city")] if b])
        if addr:
            line_bits.append(f"  📍 {addr}")
        line_bits.append(f"  📦 {it.get('product_name')} — *{qty}* en stock")
        if price is not None:
            line_bits.append(f"  💰 {price:.0f} {currency}")
        ph = off.get("whatsapp") or off.get("phone")
        if ph:
            line_bits.append(f"  📞 {ph}")
        lines.append("\n".join(line_bits))
        lines.append("")
    lines.append("_💚 Prompt rétablissement !_")
    lines.append("\n_— Liluvine PRO 🤖_")
    return "\n".join(lines)



# ===========================================================================
# Iter43-fix24ac (2026-06-16) — Configurable VIDAL `!commands`
# ===========================================================================
async def _contact_has_vidal_subscription(db, phone_digits: str) -> bool:
    """Returns True if the contact identified by `phone_digits` carries
    the tag "Abonné VIDAL" in `db.contacts`. Used to gate access to
    non-public VIDAL actions over WhatsApp.

    The tag match is case-insensitive and tolerates the diacritic é/e.
    """
    if not phone_digits:
        return False
    # Normalize: VIDAL tag may be stored as "Abonné VIDAL" or "Abonne VIDAL".
    targets = {"abonné vidal", "abonne vidal"}
    contact = await db.contacts.find_one({"phone_digits": phone_digits}) or {}
    if not contact:
        contact = await db.contacts.find_one({"phone": {"$regex": phone_digits[-9:] if len(phone_digits) >= 9 else phone_digits}})
        contact = contact or {}
    tags = contact.get("tags") or contact.get("labels") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    norm = {(t or "").strip().lower() for t in tags if t}
    return bool(norm & targets)


async def _build_vidal_reply(db, command_token: str, command_args: str,
                              phone_digits: str) -> Optional[Dict[str, Any]]:
    """Try to resolve and execute a VIDAL action for an inbound `!cmd args`.

    Returns:
      - None if the command does NOT match any configured VIDAL action
        (so the caller falls through to other handlers)
      - {"text": str, "action_id": str, "denied": bool} if matched
    """
    try:
        from routes.vidal_actions import get_vidal_actions, find_action_by_command, render_action
        from routes.vidal import _load_config, _vidal_call, _ensure_active
    except Exception:  # noqa: BLE001
        logger.exception("[wa_autoreply][vidal] failed to import VIDAL modules")
        return None
    actions = await get_vidal_actions(db)
    action = find_action_by_command(actions, command_token)
    if not action:
        return None
    # Access control : public OR contact has "Abonné VIDAL" tag.
    is_public = bool(action.get("is_public"))
    if not is_public:
        subscribed = await _contact_has_vidal_subscription(db, phone_digits)
        if not subscribed:
            return {
                "text": (
                    f"🔒 La commande `!{command_token}` est réservée aux abonnés VIDAL.\n\n"
                    "Pour y accéder, contactez votre pharmacien afin de souscrire "
                    "à l'option **Abonné VIDAL**."
                ),
                "action_id": action.get("id"),
                "denied": True,
            }
    # Build the user_input dict from the trailing args.
    args_clean = (command_args or "").strip()
    input_param = action.get("input_param") or "q"
    user_input: Dict[str, Any] = {input_param: args_clean}
    # Special case : `interactions` needs two ids → split on whitespace.
    if action.get("id") == "interactions":
        parts = args_clean.split()
        user_input = {"id1": parts[0] if len(parts) >= 1 else "", "id2": parts[1] if len(parts) >= 2 else ""}
    # Execute the call.
    try:
        cfg = await _load_config(db)
        _ensure_active(cfg)
        rendered = render_action(action, user_input)
        data = await _vidal_call(
            cfg, rendered["method"], rendered["path"],
            params=rendered["params"], body=rendered["body"],
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[wa_autoreply][vidal] call failed for %s", command_token)
        return {
            "text": (
                f"⚠️ Désolé, impossible d'interroger VIDAL pour `!{command_token}` "
                f"actuellement.\n_Erreur : {str(exc)[:120]}_"
            ),
            "action_id": action.get("id"),
            "denied": False,
        }
    # Format the response : prefer Atom entries, else short JSON snippet.
    if (data or {}).get("_error"):
        err = data["_error"]
        return {
            "text": (
                f"❌ VIDAL a refusé la requête `!{command_token}` "
                f"(HTTP {err.get('status')}).\n\n_{err.get('message') or '—'}_"
            ),
            "action_id": action.get("id"),
            "denied": False,
        }
    text = _format_vidal_data_for_wa(action, data)
    return {"text": text, "action_id": action.get("id"), "denied": False}


def _format_vidal_data_for_wa(action: Dict[str, Any], data: Dict[str, Any]) -> str:
    """Format a VIDAL response into a short WhatsApp-friendly text block.

    Iter43-fix24aq (2026-06-17) — Inclut le code produit `<vidal:id>` entre
    parenthèses pour chaque entrée (ex: « 1. DOLIPRANE 100 mg ... (5485) »).
    Extraction par regex sur le XML brut entry-par-entry (pas besoin d'un
    parser DOM côté backend).
    """
    label = action.get("label") or action.get("id")
    head = f"📋 *{label}*"
    raw = data.get("raw") if isinstance(data, dict) else None
    # Try to parse Atom entries from raw XML.
    if isinstance(raw, str) and "<entry" in raw:
        # Split on <entry ...> ... </entry> blocks and extract title + vidal:id per block
        entry_blocks = re.findall(r"<entry\b[^>]*>(.*?)</entry>", raw, flags=re.DOTALL | re.IGNORECASE)
        items: list = []
        for block in entry_blocks:
            title_m = re.search(r"<title[^>]*>([^<]+)</title>", block, flags=re.IGNORECASE)
            title = (title_m.group(1) if title_m else "").strip()
            if not title:
                continue
            # Look for <vidal:id>NNNN</vidal:id> OR <*:id>NNNN</*:id> (any prefix)
            vidal_id_m = re.search(r"<(?:[a-z][a-z0-9]*:)?id>\s*(\d+)\s*</(?:[a-z][a-z0-9]*:)?id>", block, flags=re.IGNORECASE)
            if not vidal_id_m:
                # Fallback: extract trailing digits from atom <id>vidal://product/5485</id>
                atom_id_m = re.search(r"<id[^>]*>([^<]+)</id>", block, flags=re.IGNORECASE)
                if atom_id_m:
                    trailing = re.search(r"(\d+)\s*$", atom_id_m.group(1))
                    if trailing:
                        vidal_id_m = trailing
            vidal_id = vidal_id_m.group(1) if vidal_id_m else ""
            items.append((title, vidal_id))
        if items:
            lines = [head, ""]
            for i, (t, code) in enumerate(items[:8], 1):
                if code:
                    lines.append(f"{i}. {t} (*{code}*)")
                else:
                    lines.append(f"{i}. {t}")
            if len(items) > 8:
                lines.append(f"… (+{len(items) - 8} résultats non affichés)")
            return "\n".join(lines)
        return f"{head}\n\n_Aucun résultat trouvé._"
    # JSON dict fallback
    if isinstance(data, dict) and data.get("entries"):
        entries = data["entries"][:8]
        lines = [head, ""]
        for i, e in enumerate(entries, 1):
            title = (e or {}).get("title") or (e or {}).get("name") or "?"
            code = (e or {}).get("vidal_id") or (e or {}).get("id") or ""
            if isinstance(code, str) and code.isdigit():
                lines.append(f"{i}. {title} (*{code}*)")
            else:
                lines.append(f"{i}. {title}")
        return "\n".join(lines)
    # Anything else → just confirm the call worked
    return f"{head}\n\n_Réponse VIDAL reçue ({len(str(data))} caractères). Consultez le portail pour le détail._"
