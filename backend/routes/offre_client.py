# offre_client.py — Lot 163 : logiciels, produits et services d'un client, connus de Liluvine.
#
# Demande du propriétaire (14/10/2026) : « Pour les clients/tenants je veux mettre à jour la liste des logiciels,
# produits et services d'un client (Espace "SMART COMMUNICATION"). Cela permettra à Liluvine de :
#   - ne plus poser de questions à un contact lié concernant nos produits, CRM et autres ;
#   - mieux l'orienter sur le type de réponses à donner en connaissant les bases de nos relations SAWALI-Client ;
#   - analyser le message et, si non compris, questionner le contact pour plus de détails, sinon escalader vers un humain ;
#   - si le message concerne une assistance, une maintenance, une question spécifique à un produit, prestation ou service
#     lié au client et que ce dernier n'est pas à jour de son contrat : répondre « Notre assistance pour (ce que Liluvine
#     aura détecté) n'est pas disponible pour le moment. Contactez votre responsable. », signer par son assistant IA,
#     ouvrir un ticket et escalader. »
#
# En résumé (pour un développeur WinDev) :
#   - DONNÉES : la liste est un champ `offre_client` de la fiche du client (db.users) — AUCUNE nouvelle collection
#     (le cluster Atlas est plein : 500 / 500 collections). Chaque ligne : {id, type: logiciel|produit|service, nom,
#     description, version, actif}. Édition : fiche client → « SMART Communications » → « Logiciels, produits et services ».
#   - RÉGLAGES (db.settings {_id:"global"}, Paramètres → « 🧩 Offre du client — Liluvine ») :
#       offre_client_refus_actif    : bool, DÉSACTIVÉ par défaut (rien ne change tant qu'il n'est pas activé)
#       offre_client_message_refus  : texte du refus, `{objet}` = ce que Liluvine a détecté
#       (l'enrichissement du prompt par l'offre du client, lui, est toujours actif : il est sans effet si la liste est vide)
#   - LIAISON contact → client : même logique que la puce de contrat (société, puis e-mail, puis téléphone).
#   - CONTRAT À JOUR = puce VERTE (lot 120), pseudo-contrat de 5 jours compris. Orange (retard) / rouge (aucun) = pas à jour.
#     Contact non analysable (sans société, interne SAWALI) = jamais refusé.
#   - REFUS (si activé, client relié, contrat pas à jour, message d'assistance détecté) : texte exact ci-dessus, signé par
#     l'assistant IA, ticket ouvert (ou message rattaché au ticket déjà ouvert du client) et escalade à l'administrateur.
#     Détection par mots-clés (assistance, maintenance, panne, bug, erreur, dépannage, support, intervention…) : volontairement
#     déterministe, pour qu'un client en retard ne reçoive JAMAIS d'aide par erreur.
#
# Lot 210 — ÉCHÉANCES ET RAPPELS : chaque ligne porte aussi date_debut (AAAA-MM-JJ), duree_jours (0 = pas d'échéance),
#   fin_de_mois (échéance = dernier jour du mois calendaire), rappel_jours (ex. [3] ou [7, 3]), reconduction (la période suivante commence à l'échéance, vrai par défaut),
#   montant + devise (montant de la souscription POUR CE CLIENT, lot 210.3 : remis à 0 lors d'une copie vers un autre client),
#   alerte_active (rappel AUTORISÉ pour cette ligne, faux par défaut), montant + devise (montant POUR CE CLIENT, lot 210.3 ; remis à 0 lors d'une copie vers un autre client) et rappels_envoyes (suivi interne, jamais modifié à la main).
#   Chaque matin, Liluvine envoie un WhatsApp aux décisionnaires du client — voir routes/offre_client_rappels.py.
# Routes : GET/PUT /api/admin/clients/{id}/offre ; GET/PUT /api/admin/offre-client/reglages.
# Lot 169 : copie de la liste d'un client vers un ou plusieurs autres — GET /api/admin/offre-client/clients (liste des
#   clients avec le nombre de lignes de leur offre) et POST /api/admin/offre-client/copier {source_id, cible_ids, mode} ;
#   mode « remplacer » (la liste de la cible devient celle de la source) ou « ajouter » (lignes absentes seulement : même
#   type et même nom = déjà présente). Les lignes copiées reçoivent de NOUVEAUX identifiants (listes indépendantes).
from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.offre_client")

TYPES_OFFRE = ("logiciel", "produit", "service")
MAX_LIGNES = 60
MESSAGE_REFUS_DEFAUT = "Notre assistance pour {objet} n'est pas disponible pour le moment. Contactez votre responsable."
SIGNATURE_DEFAUT = "— 🤖 Assistant IA de SAWALI (réponse automatique)"

# Intentions d'assistance : (motif sur le texte sans accents ni majuscules, libellé « ce que Liluvine a détecté »).
# Ordre = priorité : la première qui correspond donne le libellé.
INTENTIONS: List[Tuple[str, str]] = [
    (r"\bmaintenance\b", "la maintenance"),
    (r"\bdepann\w*|\breparation\b|\breparer\b", "le dépannage"),
    (r"\bpanne\b|\ben panne\b|\bne (?:marche|fonctionne|demarre|s'ouvre|repond)\w* (?:plus|pas)\b|\bplante\w*|\bbloque\w*",
     "la résolution de la panne signalée"),
    (r"\bbug\b|\berreur\b|\banomalie\b|\bdysfonction\w*|\bprobleme\b|\bincident\b", "la résolution du problème signalé"),
    (r"\bintervention\b|\bdeplacement\b|\bvenir (?:sur|chez)\b", "l'intervention demandée"),
    (r"\bmise a jour\b|\bmettre a jour\b|\bupdate\b|\binstallation\b|\binstaller\b|\bconfigur\w*|\bparametr\w*", "l'installation ou la mise à jour demandée"),
    (r"\bformation\b|\bformer\b", "la formation demandée"),
    (r"\bassistance\b|\bsupport\b|\baide\b|\bbesoin d'aide\b|\bcomment (?:faire|utiliser|activer|modifier|imprimer)\b|\bcomment ca\b",
     "l'assistance demandée"),
]


def _sans_accents(s: Any) -> str:
    """Minuscules sans accents (comparaisons de texte)."""
    t = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------------------------------------------------------------
# Offre du client
# ---------------------------------------------------------------------------------------------------------------------
def _date_iso(valeur: Any) -> str:
    """Date AAAA-MM-JJ valide, sinon chaîne vide (les 10 premiers caractères d'un horodatage ISO sont acceptés)."""
    texte = str(valeur or "").strip()[:10]
    try:
        return datetime.strptime(texte, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return ""


def _montant(valeur: Any) -> float:
    """Montant positif arrondi au centime (0 si absent ou illisible), plafonné à 1 000 milliards."""
    try:
        n = float(str(valeur).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0
    return round(min(max(n, 0.0), 1e12), 2)


def _entier(valeur: Any, mini: int, maxi: int) -> int:
    """Entier borné entre mini et maxi (0 si illisible)."""
    try:
        return max(mini, min(maxi, int(float(valeur))))
    except (TypeError, ValueError):
        return 0


def _rappels(valeur: Any) -> List[int]:
    """Jours de rappel avant l'échéance : liste d'entiers 0..365 sans doublon, du plus lointain au plus proche, 5 au plus.
    Accepte une liste ou un texte (« 7, 3 » ou « 3 »)."""
    if isinstance(valeur, str):
        valeur = re.split(r"[,;\s]+", valeur.strip())
    jours = set()
    for x in (valeur if isinstance(valeur, (list, tuple)) else []):
        try:
            n = int(float(x))
        except (TypeError, ValueError):
            continue
        if 0 <= n <= 365:
            jours.add(n)
    return sorted(jours, reverse=True)[:5]


def normaliser_offre(brut: Any) -> List[Dict[str, Any]]:
    """Liste propre : type connu, nom obligatoire, textes bornés, au plus MAX_LIGNES lignes, identifiants uniques."""
    sortie: List[Dict[str, Any]] = []
    vus = set()
    for ligne in (brut if isinstance(brut, list) else []):
        if not isinstance(ligne, dict):
            continue
        nom = str(ligne.get("nom") or "").strip()[:120]
        if not nom:
            continue
        type_ = str(ligne.get("type") or "").strip().lower()
        ident = str(ligne.get("id") or "").strip()[:40]
        if not ident or ident in vus:
            ident = uuid.uuid4().hex[:12]
        vus.add(ident)
        sortie.append({
            "id": ident,
            "type": type_ if type_ in TYPES_OFFRE else "logiciel",
            "nom": nom,
            "description": str(ligne.get("description") or "").strip()[:300],
            "version": str(ligne.get("version") or "").strip()[:40],
            "actif": ligne.get("actif") is not False,
            # Lot 210 — échéance et rappels
            "date_debut": _date_iso(ligne.get("date_debut")),
            "duree_jours": _entier(ligne.get("duree_jours"), 0, 3650),
            "rappel_jours": _rappels(ligne.get("rappel_jours")),
            "reconduction": ligne.get("reconduction") is not False,
            # Lot 210.3 — montant de la souscription POUR CE CLIENT (il diffère d'un client à l'autre) et sa devise
            "montant": _montant(ligne.get("montant")),
            "devise": (str(ligne.get("devise") or "").strip().upper()[:6] or "FCFA"),
            "fin_de_mois": ligne.get("fin_de_mois") is True,       # échéance = dernier jour du mois (la durée en jours est alors ignorée)
            "alerte_active": ligne.get("alerte_active") is True,
            "rappels_envoyes": [str(x)[:40] for x in (ligne.get("rappels_envoyes") or []) if x][-12:]
            if isinstance(ligne.get("rappels_envoyes"), list) else [],
        })
        if len(sortie) >= MAX_LIGNES:
            break
    return sortie


def bloc_prompt(societe: str, offre: List[Dict[str, Any]]) -> str:
    """Texte ajouté au prompt système de Liluvine : ce que SAWALI fournit déjà à ce client."""
    actives = [o for o in offre if o.get("actif") is not False]
    if not actives:
        return ""
    lignes = []
    for o in actives:
        detail = " ".join(x for x in (o.get("version") and f"v{o['version']}", o.get("description")) if x)
        lignes.append(f"- {o['type'].capitalize()} : {o['nom']}" + (f" — {detail}" if detail else ""))
    return (
        f"\n\n[Offre de SAWALI chez ce client — {societe or 'client lié'}]\n"
        "Le contact qui écrit est lié à ce client. Voici ce que SAWALI lui fournit (logiciels, produits, services) :\n"
        + "\n".join(lignes) + "\n"
        "Règles : ne lui demande JAMAIS quels produits, CRM ou logiciels il utilise avec SAWALI (tu le sais déjà) ; "
        "adapte tes réponses à cette offre. PÉRIMÈTRE (lot 336) : tu n'assistes QUE sur les logiciels, produits et services de cette liste. "
        "Si le message parle d'un logiciel ou d'un produit qui n'y figure PAS, ne donne AUCUNE aide technique dessus et ne pose aucune question "
        "de diagnostic : réponds simplement que ce logiciel ne figure pas dans son offre chez SAWALI, qu'il peut le vérifier avec son "
        "responsable, puis escalade vers un humain avec le marqueur d'escalade. Analyse son message : si tu ne le comprends pas, pose UNE question précise "
        "pour obtenir plus de détails ; si, même avec ces détails, la demande dépasse tes moyens, escalade vers un humain "
        "avec le marqueur d'escalade."
    )


def detecter_objet(texte: str, offre: List[Dict[str, Any]]) -> Optional[str]:
    """Ce que Liluvine détecte dans un message d'assistance : « la maintenance de <produit> », « l'assistance demandée »…
    None si le message ne demande aucune assistance (salutation, remerciement, simple question commerciale…)."""
    t = _sans_accents(texte)
    libelle = None
    for motif, lib in INTENTIONS:
        if re.search(motif, t):
            libelle = lib
            break
    if not libelle:
        return None
    # Produit / logiciel / service de l'offre cité dans le message (le nom le plus long d'abord)
    for o in sorted(offre, key=lambda x: -len(x.get("nom") or "")):
        nom = _sans_accents(o.get("nom"))
        if o.get("actif") is not False and len(nom) >= 3 and nom in t:
            return f"{libelle} de {o['nom']}"
    return libelle


def reglages(settings_doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Réglages du refus d'assistance (désactivé par défaut)."""
    s = settings_doc or {}
    message = str(s.get("offre_client_message_refus") or "").strip() or MESSAGE_REFUS_DEFAUT
    if "{objet}" not in message:
        message = MESSAGE_REFUS_DEFAUT          # texte sans {objet} : on garde la formule voulue par le propriétaire
    return {"actif": bool(s.get("offre_client_refus_actif")), "message": message[:500]}


def texte_refus(settings_doc: Optional[Dict[str, Any]], objet: str) -> str:
    return reglages(settings_doc)["message"].replace("{objet}", objet)


# ---------------------------------------------------------------------------------------------------------------------
# Lecture du client d'un contact
# ---------------------------------------------------------------------------------------------------------------------
async def client_du_contact(db, contact: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Fiche du client relié à un contact ({id, company, full_name, offre_client}), ou None.
    Même liaison que la puce de contrat ; un contact sans société, ou interne à SAWALI, n'a pas de client."""
    if not contact:
        return None
    try:
        from routes.puce_contrat import a_une_societe, est_interne
        from routes.vip_contrat import _index_comptes
        if not a_une_societe(contact):
            return None
        index, internes = await _index_comptes(db)
        client, critere = index.client_du_contact(contact)
        if not client or est_interne(client, internes, []):
            return None
        complet = await db.users.find_one({"id": client["id"]}, {"_id": 0, "id": 1, "company": 1, "full_name": 1, "offre_client": 1}) or {}
        return {"id": client["id"], "company": complet.get("company") or client.get("company") or complet.get("full_name") or "",
                "offre_client": normaliser_offre(complet.get("offre_client"))}
    except Exception:  # noqa: BLE001 — la liaison ne doit jamais empêcher Liluvine de répondre
        logger.warning("[offre_client] liaison contact → client impossible", exc_info=True)
        return None


# ---------------------------------------------------------------------------------------------------------------------
# Ticket
# ---------------------------------------------------------------------------------------------------------------------
async def _numero_ticket(db, client_id: str) -> str:
    """Même compteur et même format que server._next_ticket_number : SOCIÉTÉ-AAAA-NNNN."""
    annee = datetime.now(timezone.utc).year
    res = await db.counters.find_one_and_update({"_id": f"tickets_{client_id}_{annee}"}, {"$inc": {"seq": 1}},
                                                upsert=True, return_document=True)
    seq = (res or {}).get("seq", 1)
    prefixe = "TKT"
    try:
        c = await db.users.find_one({"id": client_id}, {"_id": 0, "company": 1, "full_name": 1}) or {}
        slug = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9]+", " ", str(c.get("company") or c.get("full_name") or ""))).strip().upper()[:20].strip()
        prefixe = slug or prefixe
    except Exception:  # noqa: BLE001
        pass
    return f"{prefixe}-{annee}-{seq:04d}"


CLIENT_DEFAUT = "SAWALI-2S"     # client primaire : reçoit les tickets des expéditeurs non reliés à un client


async def client_par_defaut(db, settings_doc: Optional[Dict[str, Any]], scope_uid: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Lots 186/186.1 — client choisi PAR DÉFAUT quand le contact n'est relié à aucun client :
    1. si une société est réglée (`liluvine_wa_client_defaut`), le compte de cette société (insensible à la casse) ;
    2. sinon le CLIENT PRIMAIRE de la base (`is_primary_client`, désigné dans Admin → Clients : SAWALI-2S) ;
    3. à défaut, le compte de la société « SAWALI-2S ».
    Plusieurs comptes possibles : celui qui reçoit la conversation d'abord, puis un administrateur / superviseur, puis le
    plus ancien. → {id, company, offre_client} ou None (jamais d'exception)."""
    try:
        champs = {"_id": 0, "id": 1, "company": 1, "role": 1, "created_at": 1, "offre_client": 1}

        def rang(u: Dict[str, Any]):
            return (0 if u.get("id") == scope_uid else 1, 0 if u.get("role") in ("admin", "superviseur") else 1,
                    str(u.get("created_at") or ""))

        async def par_societe(nom: str):
            return await db.users.find({"company": {"$regex": f"^{re.escape(nom)}$", "$options": "i"}}, champs).to_list(200)

        regle = str((settings_doc or {}).get("liluvine_wa_client_defaut") or "").strip()
        comptes = await par_societe(regle) if regle else []
        if not comptes and not regle:
            comptes = await db.users.find({"is_primary_client": True}, champs).to_list(50)   # client primaire désigné en base
        if not comptes and not regle:
            comptes = await par_societe(CLIENT_DEFAUT)
        if not comptes:
            return None
        c = sorted(comptes, key=rang)[0]
        return {"id": c["id"], "company": c.get("company") or regle or CLIENT_DEFAUT,
                "offre_client": normaliser_offre(c.get("offre_client"))}
    except Exception:  # noqa: BLE001
        logger.warning("[offre_client] client par défaut introuvable", exc_info=True)
        return None


async def ouvrir_ticket(db, client: Dict[str, Any], contact: Optional[Dict[str, Any]], objet: str, texte: str, *,
                        motif: Optional[str] = None, categorie: Optional[str] = None,
                        source: str = "liluvine_offre_client", nouveau: bool = False) -> Optional[Dict[str, Any]]:
    """Ouvre un ticket pour ce client — ou rattache la demande au ticket déjà ouvert (règle du lot 54 : un seul ticket
    ouvert par client). Renvoie {id, number, rattache} ou None en cas d'échec (jamais d'exception)."""
    try:
        import tickets_clients as tc
        contact_id = (contact or {}).get("id")
        # nouveau=True (client par défaut) : un ticket PAR conversation, jamais rattaché au ticket ouvert d'un autre expéditeur
        ouvert = None if nouveau else await tc.ticket_ouvert_du_client(client["id"])
        if ouvert:
            ouvert = await tc.rattacher_contact(ouvert, contact_id)
            return {"id": ouvert["id"], "number": ouvert.get("number"), "rattache": True}
        maintenant = datetime.now(timezone.utc).isoformat()
        numero = await _numero_ticket(db, client["id"])
        ticket = {
            "id": uuid.uuid4().hex, "number": numero, "client_id": client["id"],
            "contact_id": contact_id, "contact_name": (contact or {}).get("name"),
            "contact_phone": (contact or {}).get("whatsapp") or (contact or {}).get("phone"),
            # Lot 181 : le classement par Liluvine fournit son propre motif et sa catégorie ; sinon, motif du refus d'assistance.
            "motif": (motif or f"Demande d'assistance refusée (contrat pas à jour) : {objet}")[:200],
            "category": categorie or None,
            "status": "open", "notes": (f"Catégorie : {categorie}\n" if categorie else "") + f"Message reçu : {texte[:500]}",
            "software": None, "incident_at": None,
            "attach_wa_sms_history": False, "source": source,
            "opened_at": maintenant, "opened_by_id": "liluvine", "opened_by_label": "Liluvine (assistant IA)",
            "owner_id": client["id"], "owner_company": client.get("company") or None, "owner_parent_client_id": None,
            "shared_with_tenant": False, "editable_by_tenant": False,
            "closed_at": None, "closed_by_id": None, "closed_by_label": None, "outcome": None, "resolution_note": None,
            "created_at": maintenant, "updated_at": maintenant,
            "contact_ids": [c for c in [contact_id] if c],
            **tc.champs_creation(await tc.lire_client(client["id"]), maintenant),
        }
        await db.support_tickets.insert_one(ticket.copy())
        return {"id": ticket["id"], "number": numero, "rattache": False}
    except Exception:  # noqa: BLE001
        logger.warning("[offre_client] ouverture du ticket impossible", exc_info=True)
        return None


# ---------------------------------------------------------------------------------------------------------------------
# Refus d'assistance (appelé par l'auto-réponse WhatsApp avant toute réponse IA)
# ---------------------------------------------------------------------------------------------------------------------
async def refuser_assistance(db, settings_doc: Dict[str, Any], *, contact: Optional[Dict[str, Any]], texte: str,
                             etat_contrat: Optional[str], client: Optional[Dict[str, Any]], phone_digits: str,
                             envoyer: Callable[..., Awaitable[Any]], signature: str,
                             reply_to: Optional[str] = None) -> Dict[str, Any]:
    """Si le client n'est pas à jour et que le message demande une assistance : envoie le refus signé, ouvre le ticket et
    escalade. → {refuse: bool, objet, ticket, envoye}. Jamais d'exception (une erreur laisse Liluvine répondre comme avant)."""
    resultat: Dict[str, Any] = {"refuse": False, "objet": None, "ticket": None, "envoye": False}
    try:
        if not reglages(settings_doc)["actif"] or not client:
            return resultat
        if etat_contrat is None or etat_contrat == "valide":
            return resultat                       # à jour (pseudo-contrat compris) ou non analysable : jamais refusé
        objet = detecter_objet(texte, client.get("offre_client") or [])
        if not objet:
            return resultat
        resultat.update(refuse=True, objet=objet)
        message = f"{texte_refus(settings_doc, objet)}\n\n{signature or SIGNATURE_DEFAUT}"
        envoi = await envoyer(f"+{phone_digits}", message, reply_to_message_id=reply_to) if reply_to else await envoyer(f"+{phone_digits}", message)
        resultat["envoye"] = bool((envoi or {}).get("ok")) if isinstance(envoi, dict) else bool(envoi)
        resultat["ticket"] = await ouvrir_ticket(db, client, contact, objet, texte)
        # Escalade vers l'administrateur (même canal que le marqueur [ESCALATE])
        try:
            from routes.liluvine_escalation import notify_admin
            ticket = resultat["ticket"] or {}
            await notify_admin(
                db, contact_name=(contact or {}).get("name"), contact_phone_digits=phone_digits, last_user_message=texte,
                reason=f"Assistance refusée (contrat {etat_contrat}) : {objet} — {client.get('company') or 'client'}"
                       + (f" — ticket {ticket['number']}" if ticket.get("number") else ""),
                send_wa=envoyer, session_id=f"wa:offre:{phone_digits}",
                history=[{"role": "user", "text": texte}, {"role": "assistant", "text": message}])
        except Exception:  # noqa: BLE001
            logger.warning("[offre_client] escalade impossible", exc_info=True)
    except Exception:  # noqa: BLE001
        logger.warning("[offre_client] refus d'assistance impossible", exc_info=True)
    return resultat


# ---------------------------------------------------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------------------------------------------------
class LigneOffreIn(BaseModel):
    id: Optional[str] = None
    type: str = "logiciel"
    nom: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=300)
    version: str = Field(default="", max_length=40)
    actif: bool = True
    # Lot 210 — échéance et rappels (voir routes/offre_client_rappels.py)
    date_debut: str = Field(default="", max_length=10)
    duree_jours: int = Field(default=0, ge=0, le=3650)
    rappel_jours: List[int] = Field(default_factory=list, max_length=10)
    reconduction: bool = True
    fin_de_mois: bool = False
    alerte_active: bool = False
    montant: float = Field(default=0, ge=0, le=1e12)       # lot 210.3 : montant pour ce client
    devise: str = Field(default="FCFA", max_length=6)


class OffreIn(BaseModel):
    lignes: List[LigneOffreIn] = Field(default_factory=list)


class CopieOffreIn(BaseModel):
    """Lot 169 — copie de l'offre d'un client vers d'autres : `remplacer` ou `ajouter` (sans doublon type + nom)."""
    source_id: str = Field(..., min_length=1, max_length=80)
    cible_ids: List[str] = Field(..., min_length=1, max_length=200)
    mode: str = Field(default="ajouter", pattern="^(remplacer|ajouter)$")


def fusionner_offre(existante: List[Dict[str, Any]], copiee: List[Dict[str, Any]], mode: str) -> Tuple[List[Dict[str, Any]], int]:
    """Lot 169 — liste obtenue en copiant `copiee` sur `existante`, et nombre de lignes reprises.
    `remplacer` : la liste devient la copie ; `ajouter` : on garde l'existante et on ajoute les lignes absentes (même type
    et même nom, sans tenir compte des accents ni de la casse), dans la limite de MAX_LIGNES. Identifiants toujours neufs."""
    neuves = normaliser_offre([{**l, "id": "", "date_debut": "", "rappels_envoyes": [], "montant": 0} for l in copiee])      # id vide = nouvel identifiant : listes indépendantes
    if mode == "remplacer":
        return neuves, len(neuves)
    cles = {(l["type"], _sans_accents(l["nom"])) for l in existante}
    ajoutees = [l for l in neuves if (l["type"], _sans_accents(l["nom"])) not in cles]
    ajoutees = ajoutees[: max(0, MAX_LIGNES - len(existante))]
    return [*existante, *ajoutees], len(ajoutees)


class ReglagesOffreIn(BaseModel):
    actif: bool = False
    message: str = Field(default="", max_length=500)


def setup_offre_client_routes(*, db, api, get_current_admin) -> None:
    """Branche les routes du lot 163 (appelée depuis server_parts/p20)."""
    from fastapi import Depends, HTTPException

    @api.get("/admin/clients/{client_id}/offre", tags=["Admin — Offre du client"])
    async def lire_offre(client_id: str, _: dict = Depends(get_current_admin)):
        """Logiciels, produits et services de ce client."""
        u = await db.users.find_one({"id": client_id}, {"_id": 0, "id": 1, "company": 1, "full_name": 1, "offre_client": 1, "offre_client_maj": 1})
        if not u:
            raise HTTPException(status_code=404, detail="Client introuvable")
        return {"client": u.get("company") or u.get("full_name"), "lignes": normaliser_offre(u.get("offre_client")),
                "maj": u.get("offre_client_maj"), "types": list(TYPES_OFFRE)}

    @api.put("/admin/clients/{client_id}/offre", tags=["Admin — Offre du client"])
    async def ecrire_offre(client_id: str, data: OffreIn, admin: dict = Depends(get_current_admin)):
        """Remplace la liste (lignes sans nom ignorées, identifiants attribués au besoin)."""
        if not await db.users.find_one({"id": client_id}, {"_id": 0, "id": 1}):
            raise HTTPException(status_code=404, detail="Client introuvable")
        deja = {l["id"]: l.get("rappels_envoyes") or [] for l in normaliser_offre(
            (await db.users.find_one({"id": client_id}, {"_id": 0, "offre_client": 1}) or {}).get("offre_client"))}
        lignes = normaliser_offre([{**l.model_dump(), "rappels_envoyes": deja.get(l.id or "", [])} for l in data.lignes])
        maj = {"le": datetime.now(timezone.utc).isoformat(), "par": admin.get("full_name") or admin.get("email")}
        await db.users.update_one({"id": client_id}, {"$set": {"offre_client": lignes, "offre_client_maj": maj}})
        return {"ok": True, "lignes": lignes, "maj": maj}

    @api.get("/admin/offre-client/clients", tags=["Admin — Offre du client"])
    async def lister_clients(_: dict = Depends(get_current_admin)):
        """Lot 169 — clients (comptes principaux) avec le nombre de lignes de leur offre : choix de la source ou des cibles
        d'une copie. Triés par nom ; les administrateurs et le compte de la plateforme ne sont pas proposés."""
        lignes = []
        async for u in db.users.find({"role": {"$nin": ["admin", "superviseur"]}, "email": {"$ne": "admin@sawalismartsystems.com"},
                                      "$or": [{"parent_client_id": {"$exists": False}}, {"parent_client_id": {"$in": [None, ""]}}]},
                                     {"_id": 0, "id": 1, "company": 1, "full_name": 1, "offre_client": 1}):
            nom = u.get("company") or u.get("full_name") or ""
            if nom:
                lignes.append({"id": u["id"], "nom": nom, "nb_lignes": len(normaliser_offre(u.get("offre_client")))})
        return {"clients": sorted(lignes, key=lambda c: _sans_accents(c["nom"]))}

    @api.post("/admin/offre-client/copier", tags=["Admin — Offre du client"])
    async def copier_offre(data: CopieOffreIn, admin: dict = Depends(get_current_admin)):
        """Lot 169 — copie la liste de `source_id` vers chaque client de `cible_ids` (mode « remplacer » ou « ajouter »).
        La source n'est jamais modifiée ; une cible inconnue est signalée sans bloquer les autres."""
        src = await db.users.find_one({"id": data.source_id}, {"_id": 0, "id": 1, "company": 1, "full_name": 1, "offre_client": 1})
        if not src:
            raise HTTPException(status_code=404, detail="Client source introuvable")
        copiee = normaliser_offre(src.get("offre_client"))
        if not copiee:
            raise HTTPException(status_code=409, detail="La liste de ce client est vide : rien à copier")
        nom_src = src.get("company") or src.get("full_name") or ""
        maj = {"le": datetime.now(timezone.utc).isoformat(), "par": admin.get("full_name") or admin.get("email"),
               "copie_de": nom_src}
        resultat: List[Dict[str, Any]] = []
        for cid in dict.fromkeys(data.cible_ids):                         # sans doublon, ordre conservé
            if cid == data.source_id:
                continue
            cible = await db.users.find_one({"id": cid}, {"_id": 0, "id": 1, "company": 1, "full_name": 1, "offre_client": 1})
            if not cible:
                resultat.append({"id": cid, "nom": "", "ok": False, "erreur": "Client introuvable"})
                continue
            liste, nb = fusionner_offre(normaliser_offre(cible.get("offre_client")), copiee, data.mode)
            await db.users.update_one({"id": cid}, {"$set": {"offre_client": liste, "offre_client_maj": maj}})
            resultat.append({"id": cid, "nom": cible.get("company") or cible.get("full_name") or "", "ok": True,
                             "copiees": nb, "total": len(liste)})
        return {"source": nom_src, "mode": data.mode, "resultat": resultat,
                "copiees": sum(r.get("copiees", 0) for r in resultat), "clients": sum(1 for r in resultat if r["ok"])}

    async def _etat() -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        avec_offre = await db.users.count_documents({"offre_client.0": {"$exists": True}})
        return {**reglages(s), "message_defaut": MESSAGE_REFUS_DEFAUT, "clients_avec_offre": avec_offre}

    @api.get("/admin/offre-client/reglages", tags=["Admin — Offre du client"])
    async def lire_reglages(_: dict = Depends(get_current_admin)):
        """Activation du refus d'assistance et texte du refus."""
        return await _etat()

    @api.put("/admin/offre-client/reglages", tags=["Admin — Offre du client"])
    async def ecrire_reglages(data: ReglagesOffreIn, _: dict = Depends(get_current_admin)):
        """Active / désactive le refus ; le texte doit contenir {objet} (sinon la formule par défaut s'applique)."""
        texte = data.message.strip()
        if texte and "{objet}" not in texte:
            raise HTTPException(status_code=422, detail="Le texte doit contenir {objet} (ce que Liluvine a détecté)")
        await db.settings.update_one({"_id": "global"}, {"$set": {
            "offre_client_refus_actif": bool(data.actif), "offre_client_message_refus": texte}}, upsert=True)
        return await _etat()
