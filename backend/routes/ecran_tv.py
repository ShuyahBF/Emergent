"""Lot 289 — Écrans TV (Smart TV, webOS…) : page plein écran qui affiche en direct le fil du Centre de Messagerie
et les demandes de support d'un client, sans aucun bouton.

Comment ça marche (pour un développeur WinDev) :
  1. La page publique /tv s'ouvre dans le navigateur de la télé : elle fabrique un secret, le garde dans la télé et
     affiche un CODE à 6 caractères (le serveur ne garde que l'empreinte du secret, jamais le secret).
  2. L'administrateur saisit ce code dans Paramètres → « 📺 Écrans TV », choisit le client et les contenus : la télé
     est « appairée » et reçoit son flux toutes les quelques secondes avec son secret.
  3. L'administrateur peut renommer, modifier les contenus ou RÉVOQUER un écran à tout moment.

Données dans `settings.global` (aucune nouvelle collection) : `tv_ecrans` (écrans appairés) et `tv_appairages`
(codes en attente, 15 minutes, 20 au plus).
Confidentialité : les numéros de téléphone sont masqués (nom du contact, sinon « •••• 1234 »).
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("sawali.ecran_tv")

VALIDITE_CODE_MIN = 15           # un code d'appairage n'est valable que 15 minutes
MAX_APPAIRAGES = 20              # codes en attente conservés au plus
MAX_MESSAGES = 30                # messages renvoyés à la télé (fil en direct)
MAX_FILS = 12                    # conversations renvoyées à la télé
FENETRE_FILS = 200               # messages récents examinés pour former les conversations
JOURS_NON_LUS = 30               # les non-lus comptés remontent à 30 jours au plus
MAX_TICKETS = 12                 # demandes de support renvoyées
ALPHABET_CODE = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # sans I, L, O, 0, 1 : lisible de loin sur une télé
MODULES = ("messagerie", "support", "hall")         # contenus possibles ; « hall » = consultations du jour (lot 300)
STATUTS_OUVERTS = ("open", "in_progress", "suspended")
PAGE_TV_VERSION = "323"        # lot 307 : version de la page /tv-ecran.html ; à changer (ici ET dans la page) à chaque modification de la page
TAILLES_HEURE = ("normale", "grande", "tres_grande", "geante")   # lot 309 : taille de l'heure sur l'écran du hall (liste déroulante)
PIN_MIN, PIN_MAX = 4, 8                      # lot 317 : longueur du code PIN du « Suivi Support »
PIN_ESSAIS_MAX = 5                           # échecs consécutifs avant blocage de l'écran…
PIN_BLOCAGE_S = 60                           # … pendant 60 secondes
APPROBATION_MIN = 5                          # lot 323 : le code d'approbation « connexion administrateur » affiché par la télé n'est valable que 5 minutes
DEVERROU_MIN = 10                            # un déverrouillage valable 10 minutes (la page revient d'elle-même au planning avant)
NOUVEAU_RDV_MIN = 10                         # un RDV créé il y a moins de 10 minutes clignote sur l'écran du hall
JOURS_RDV_MASQUES = 3            # lot 303 : les patients rappelés pour un RDV depuis 3 jours n'apparaissent pas dans les conversations


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def empreinte(secret: str) -> str:
    """Empreinte SHA-256 d'un secret : c'est la seule chose gardée côté serveur."""
    return hashlib.sha256((secret or "").encode("utf-8")).hexdigest()


def hacher_pin(pin: str, sel: str) -> str:
    """Empreinte salée du code PIN : le code lui-même n'est jamais conservé ni renvoyé à la télé."""
    return hashlib.sha256(f"{sel}:{pin}".encode("utf-8")).hexdigest()


def pin_valide(pin: Any) -> bool:
    """Code PIN accepté : 4 à 8 chiffres."""
    return isinstance(pin, str) and pin.isdigit() and PIN_MIN <= len(pin) <= PIN_MAX and pin.isascii()


def nouveau_code() -> str:
    """Code d'appairage à 6 caractères lisibles (ex. K7MQ4X)."""
    return "".join(secrets.choice(ALPHABET_CODE) for _ in range(6))


def masquer_numero(chiffres: str) -> str:
    """« 22670001122 » → « •••• 1122 » : seuls les 4 derniers chiffres restent visibles."""
    c = "".join(ch for ch in str(chiffres or "") if ch.isdigit())
    return f"•••• {c[-4:]}" if len(c) >= 4 else "Contact"


def derniers8(valeur: Any) -> str:
    """Clé de rapprochement d'un numéro de téléphone : ses 8 derniers chiffres (vide si trop court)."""
    c = "".join(ch for ch in str(valeur or "") if ch.isdigit())
    return c[-8:] if len(c) >= 8 else ""


def est_conversation_rdv(doc: Dict[str, Any], numeros_rdv: set) -> bool:
    """Lot 303 : vrai si le message appartient à la conversation d'un patient rappelé pour un RDV (rappel, réponse du patient,
    réponse automatique) — ces échanges se suivent dans le Centre de Messagerie → « Suivi des RDV », pas sur la télé."""
    return bool(numeros_rdv) and derniers8(doc.get("phone_digits") or doc.get("from") or doc.get("to")) in numeros_rdv


_SIGNATURE_AGENT = re.compile(r"^\s*[—-]\s*([^\n(,]+?)\s*(?:\([^)\n]*\))?,\s*assistant Liluvine", re.IGNORECASE | re.MULTILINE)


def agent_ia(doc: Dict[str, Any]) -> str:
    """Lot 303 : prénom de l'agent IA qui a écrit ce message sortant (vide si message humain).
    1) champ `agent_ia` enregistré avec le message ; 2) sinon la signature « — Awa (Secrétaire), assistant Liluvine 🤖 » du texte ;
    3) sinon « Liluvine » pour toute réponse automatique ou générée par l'IA."""
    if doc.get("direction") == "inbound":
        return ""
    if doc.get("agent_ia"):
        return str(doc["agent_ia"])[:30]
    if not (doc.get("ai_generated") or doc.get("auto_reply")):
        return ""
    m = _SIGNATURE_AGENT.search(str(doc.get("body") or ""))
    return (m.group(1).strip()[:30] if m else "Liluvine")


def cle_fil(doc: Dict[str, Any]) -> str:
    """Clé d'une conversation : la fiche contact si elle existe, sinon une empreinte des 8 derniers chiffres du numéro."""
    if doc.get("contact_id"):
        return str(doc["contact_id"])
    chiffres = "".join(c for c in str(doc.get("phone_digits") or doc.get("from") or doc.get("to") or "") if c.isdigit())
    # Jamais de chiffres du numéro dans le flux envoyé à la télé : on n'expose qu'une empreinte
    return "t" + hashlib.sha1(chiffres[-8:].encode("utf-8")).hexdigest()[:10] if chiffres else "inconnu"


def forme_fils(docs: List[Dict[str, Any]], non_lus: Dict[str, int], noms: Dict[str, str]) -> List[Dict[str, Any]]:
    """Conversations à afficher : nom du contact (sinon numéro masqué), dernier message, heure et nombre de messages NON LUS.
    `docs` : messages récents, du plus récent au plus ancien. `non_lus` : clé de conversation → nombre de non-lus."""
    fils: Dict[str, Dict[str, Any]] = {}
    for d in docs:
        cle = cle_fil(d)
        if cle in fils:
            continue                                             # le premier rencontré est le plus récent
        m = forme_message(d)
        nom = d.get("contact_name") or noms.get(cle) or d.get("from_profile_name") or masquer_numero(d.get("phone_digits") or d.get("from") or d.get("to"))
        fils[cle] = {"cle": cle, "nom": str(nom)[:60], "dernier": m["texte"][:100], "sens": m["sens"], "date": m["date"], "non_lus": 0, "agent": m["agent"]}
    for cle, n in non_lus.items():
        if cle in fils:
            fils[cle]["non_lus"] = n
    return list(fils.values())[:MAX_FILS]


def forme_message(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Message prêt à afficher : jamais de numéro complet, texte raccourci, libellé pour image/vocal/document."""
    corps = str(doc.get("body") or "").strip()
    type_msg = doc.get("message_type") or "text"
    if not corps:
        corps = {"image": "📷 Image", "audio": "🎤 Message vocal", "voice": "🎤 Message vocal", "document": "📄 Document",
                 "video": "🎬 Vidéo", "sticker": "🙂 Autocollant", "location": "📍 Position"}.get(type_msg, "…")
    nom = doc.get("contact_name") or doc.get("from_profile_name") or masquer_numero(doc.get("phone_digits") or doc.get("from") or doc.get("to"))
    return {"id": doc.get("id"), "sens": "entrant" if doc.get("direction") == "inbound" else "sortant", "fil": cle_fil(doc),
            "nom": str(nom)[:60], "texte": corps[:240], "date": doc.get("received_at") or doc.get("sent_at") or doc.get("created_at"),
            "agent": agent_ia(doc)}


def forme_ticket(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Demande de support prête à afficher (numéro, motif, contact, état, date d'ouverture)."""
    return {"id": doc.get("id"), "numero": doc.get("number"), "motif": str(doc.get("motif") or "")[:140],
            "contact": str(doc.get("contact_name") or "")[:60], "statut": doc.get("status"), "date": doc.get("opened_at")}


# ----------------------------------------------------------------------------------------------------------------------
# Lot 300 — « Hall » : consultations du jour par médecin, prochain patient et numéro de porte (même source que le Planning des médecins)
# ----------------------------------------------------------------------------------------------------------------------
TYPES_ATTENTE = ("", "RDV", "PAT")          # patient encore en attente (pas de type = RDV ou arrivée reçue sans autre information)


def _dt(iso: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def borne_jour(maintenant: datetime) -> tuple:
    """Début et fin (UTC) de la journée de `maintenant` : même jour que dans le Planning des médecins (Burkina Faso = UTC)."""
    j0 = maintenant.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return j0, j0 + timedelta(days=1)


def anonymiser_nom(nom: Any) -> str:
    """Lot 305 : affichage PUBLIC (hall). Chaque mot garde ses 2 premiers caractères, les suivants deviennent « * » (la ponctuation
    reste) ; un mot de 1 ou 2 lettres (initiale) reste entier. « GUYO. R. Paulin : 70001122 » → « GU**. R. Pa**** ».
    Le téléphone collé au nom par le Planning (« NOM : 70001122 ») est retiré ici : il s'affiche à part, lui aussi masqué."""
    texte = str(nom or "").split(" : ")[0]
    mots = [m for m in texte.split() if m and not m.strip(".:;,-").isdigit()]
    sortie = []
    for mot in mots[:5]:
        lettres = 0
        res = ""
        for ch in mot:
            if ch.isalnum():
                lettres += 1
                res += ch if (lettres <= 2 or len([c for c in mot if c.isalnum()]) <= 2) else "*"
            else:
                res += ch                                 # ponctuation conservée (« . », « - », « ' »)
        sortie.append(res)
    return " ".join(sortie) if sortie else "—"


def recu_du_patient(patient: Any) -> str:
    """Numéro de reçu saisi après le téléphone dans le champ patient (« NOM : 25614545 : R-202660230 »), si le RDV n'a pas de champ
    `numero_recu` (anciennes lignes). Même analyse que le webhook (lot 308)."""
    from routes.planning import separer_patient_tel_recu
    return separer_patient_tel_recu(str(patient or ""))[2]


def masquer_tel_hall(tel: Any) -> str:
    """Lot 305 : téléphone pour le hall — 1er chiffre, étoiles, 2 derniers chiffres : « 70001122 » → « 7*****22 » (numéro national à 8 chiffres)."""
    c = "".join(ch for ch in str(tel or "") if ch.isdigit())
    if len(c) >= 8:
        c = c[-8:]
    return f"{c[0]}{'*' * (len(c) - 3)}{c[-2:]}" if len(c) >= 4 else ""


def nom_clair(patient: Any) -> str:
    """Lot 323 : nom et prénoms du patient EN CLAIR (partie avant le premier « : » du champ « NOM Prénoms : téléphone : reçu »)."""
    return str(patient or "").split(":")[0].strip() or "—"


def tel_clair(tel: Any) -> str:
    """Lot 323 : téléphone en clair, 8 derniers chiffres groupés par deux (« 70 00 11 22 »)."""
    c = "".join(ch for ch in str(tel or "") if ch.isdigit())[-8:]
    return " ".join(c[i:i + 2] for i in range(0, len(c), 2))


def forme_hall(docs: List[Dict[str, Any]], portes: Dict[str, str], maintenant: datetime,
               fiches: Optional[Dict[str, Dict[str, Any]]] = None, avec_photos: bool = False, limite: int = 14,
               en_clair: bool = False) -> Dict[str, Any]:
    """Planning du jour par médecin (RDV pris tels quels ; le champ `type_evenement` n'est pas utilisé).
    Deux listes par médecin (lot 309) : `rdv` (avec rendez-vous, classés par heure) et `sans_rdv` (consultations sans RDV, classées par
    numéro d'ordre, mises à jour par le secrétariat médical). Chaque ligne : patient ANONYMISÉ (« GU**. R. Pa**** »), téléphone masqué
    (« 7*****42 »), reçu s'il est transmis, et `etat` = « en_cours » / « fait » / « attente » (curseur Avancer / Reculer du médecin).
    `prochain_min` = minutes avant le prochain RDV en attente. Renvoie {"medecins": [...], "prochain": {medecin, porte, libelle} | None}."""
    par_med: Dict[str, Dict[str, Any]] = {}
    for d in docs:
        if str(d.get("status") or "").lower() in ("cancelled", "annule", "annulé"):
            continue
        nom = str(d.get("medecin") or "").strip() or "—"
        fiche = par_med.setdefault(nom, {"medecin": nom, "porte": portes.get(nom.lower(), ""), "rdv": [], "sans_rdv": []})
        sans = d.get("is_rdv", 1) == 0
        debut = None if sans else _dt(d.get("start_at"))
        arrivee = _dt(d.get("received_at")) or _dt(d.get("created_at")) or maintenant
        quand = debut or arrivee
        ligne = {"heure": quand.strftime("%H:%M"), "qui": nom_clair(d.get("patient")) if en_clair else anonymiser_nom(d.get("patient")),
                 "tel": tel_clair(d.get("patient_phone")) if en_clair else masquer_tel_hall(d.get("patient_phone")),
                 "recu": (str(d.get("numero_recu") or "").strip() or recu_du_patient(d.get("patient")))[:30],
                 "ordre": d.get("numero_ordre"), "curseur": d.get("etat_consult") or "", "passe": quand < maintenant, "_q": quand,
                 # lot 317 : début exact (UTC) pour que la télé masque le RDV à son heure ; « nouveau » = créé depuis moins de 10 minutes (clignote)
                 "debut": debut.isoformat() if debut else None,
                 "jour": quand.strftime("%Y-%m-%d"),               # lot 319 : jour du RDV (la télé regroupe par jour quand l'horizon est de 3 jours ou d'une semaine)
                 "nouveau": bool(_dt(d.get("created_at")) and maintenant - _dt(d.get("created_at")) < timedelta(minutes=NOUVEAU_RDV_MIN))}
        fiche["sans_rdv" if sans else "rdv"].append(ligne)

    def finir(lignes: List[Dict[str, Any]], par_numero: bool) -> List[Dict[str, Any]]:
        """Classe la liste, fixe l'état de chaque ligne ; si le médecin n'utilise pas encore Avancer/Reculer, l'heure passée estompe la ligne."""
        lignes.sort(key=(lambda x: int(x["ordre"] or 0)) if par_numero else (lambda x: x["_q"]))
        utilise = any(x["curseur"] for x in lignes)
        for x in lignes:
            x["etat"] = x["curseur"] or "attente"
            x["passe"] = (x["curseur"] == "fait") if utilise else (False if par_numero else x["passe"])
        return lignes

    medecins = []
    for fiche in par_med.values():
        rdv, sans_rdv = finir(fiche["rdv"], False), finir(fiche["sans_rdv"], True)
        a_venir = [x["_q"] for x in rdv if not x["passe"] and x["etat"] != "en_cours"]
        extra = (fiches or {}).get(fiche["medecin"].lower()) or {}          # profession et photo du médecin
        propre = lambda lst: [{k: v for k, v in x.items() if k not in ("_q", "curseur")} for x in lst][:limite]
        medecins.append({"medecin": fiche["medecin"], "porte": fiche["porte"], "profession": extra.get("profession", ""),
                         "a_photo": bool(extra.get("photo")), "photo": extra.get("photo", "") if avec_photos else "",
                         "rdv": [{**x, "etat_ancien": "termine" if x["passe"] else "attente"} for x in propre(rdv)],
                         "sans_rdv": propre(sans_rdv),
                         "prochain_min": int((a_venir[0] - maintenant).total_seconds() // 60) if a_venir else None,
                         # Compatibilité : une télé qui a gardé en cache une ancienne page lit encore ces champs
                         "prochains": [{"libelle": x["heure"], "heure": x["heure"]} for x in rdv if not x["passe"]][:3],
                         "en_consultation": None, "restants": len([x for x in rdv if not x["passe"]]), "vus": 0,
                         "_premier": a_venir[0] if a_venir else None})
    for m in medecins:
        for x in m["rdv"]:
            ancien = x.pop("etat_ancien")
            if x["etat"] == "attente":
                x["etat"] = ancien                                   # anciennes pages : « termine » / « attente »
    medecins.sort(key=lambda m: m["medecin"].lower())
    en_attente = [m for m in medecins if m["_premier"] is not None]
    prochain = None
    if en_attente:
        m = min(en_attente, key=lambda x: x["_premier"])
        prochain = {"medecin": m["medecin"], "porte": m["porte"], "libelle": next(x["heure"] for x in m["rdv"] if not x["passe"])}
    for m in medecins:
        m.pop("_premier", None)
    return {"medecins": medecins, "prochain": prochain, "jour": maintenant.strftime("%Y-%m-%d")}


MAX_PHOTO = 60000        # taille maximale (caractères) de la photo d'un médecin, enregistrée en « data:image » réduite par l'écran d'administration


def normaliser_portes(brut: Any) -> List[Dict[str, str]]:
    """Table « médecin → porte / bureau, profession, photo » (ex. Dr OUEDRAOGO → « Bureau 3 ») : une ligne par médecin (sans casse),
    lignes vides retirées. Lot 303 : `profession` (texte court) et `photo` (petite image « data:image/jpeg|png|webp;base64,… »)."""
    par_nom: Dict[str, Dict[str, str]] = {}
    for ligne in brut if isinstance(brut, list) else []:
        if not isinstance(ligne, dict):
            continue
        medecin = str(ligne.get("medecin") or "").strip()
        porte = str(ligne.get("porte") or "").strip()
        profession = str(ligne.get("profession") or "").strip()[:60]
        photo = str(ligne.get("photo") or "").strip()
        if not (photo.startswith(("data:image/jpeg;base64,", "data:image/png;base64,", "data:image/webp;base64,")) and len(photo) <= MAX_PHOTO):
            photo = ""                                  # photo absente, d'un autre type ou trop lourde : ignorée
        if medecin and (porte or profession or photo):
            entree = {"medecin": medecin[:80], "porte": porte[:30]}
            if profession:
                entree["profession"] = profession
            if photo:
                entree["photo"] = photo
            par_nom[medecin.lower()] = entree
    return list(par_nom.values())


def taille_heure_valide(valeur: Any) -> str:
    """Taille de l'heure sur l'écran du hall ; absente ou inconnue : « grande » (le hall est lu de loin)."""
    return valeur if valeur in TAILLES_HEURE else "grande"


def modules_valides(brut: Any) -> Dict[str, bool]:
    """Ne garde que les contenus connus ; absent = non."""
    brut = brut if isinstance(brut, dict) else {}
    return {m: bool(brut.get(m)) for m in MODULES}


class AppairageDemande(BaseModel):
    secret: str = Field(..., min_length=16, max_length=128, description="Secret fabriqué par la télé (jamais stocké en clair)")


class EcranAppairage(BaseModel):
    code: str = Field(..., min_length=4, max_length=12)
    nom: str = Field(..., min_length=1, max_length=60)
    client_id: str = Field(..., min_length=1, max_length=64)
    modules: Optional[Dict[str, bool]] = None


class EcranModif(BaseModel):
    nom: Optional[str] = Field(None, max_length=60)
    client_id: Optional[str] = Field(None, max_length=64)
    modules: Optional[Dict[str, bool]] = None
    taille_heure: Optional[str] = Field(None, max_length=20)


def setup_ecran_tv_routes(*, db, api, get_current_admin, resolve_visible_client_ids=None):
    """Monte les routes : publiques (/tv/…, protégées par le secret de la télé) et administrateur (/admin/tv/…)."""

    async def _perimetre(client_id: str) -> List[str]:
        """Identifiants dont les messages et tickets appartiennent à ce client : MÊME périmètre que le Centre de Messagerie
        (le compte, son client rattaché, et les comptes de la même société). Lot 298 : avant, seul l'identifiant exact du compte
        choisi était lu, donc l'écran restait vide quand les messages étaient rangés sous un autre compte de la même société."""
        if resolve_visible_client_ids is None:
            return [client_id]
        compte = await db.users.find_one({"id": client_id}, {"_id": 0})
        if not compte:
            return [client_id]
        ids = await resolve_visible_client_ids(compte)
        return list(dict.fromkeys([client_id, *ids]))

    async def _reglages_portes() -> List[Dict[str, str]]:
        s = await db.settings.find_one({"_id": "global"}, {"tv_portes": 1}) or {}
        return normaliser_portes(s.get("tv_portes"))

    async def _reglages() -> Dict[str, Any]:
        return await db.settings.find_one({"_id": "global"}, {"tv_ecrans": 1, "tv_appairages": 1, "tv_pin": 1}) or {}

    # ---------------- Côté télé (public) ----------------
    @api.post("/tv/appairage", tags=["Écran TV"])
    async def tv_demander_appairage(payload: AppairageDemande):
        """La télé demande un code. Elle envoie son secret ; le serveur n'en garde que l'empreinte."""
        limite = (_maintenant() - timedelta(minutes=VALIDITE_CODE_MIN)).isoformat()
        entree = {"id": uuid.uuid4().hex, "code": nouveau_code(), "empreinte": empreinte(payload.secret), "cree_le": _maintenant().isoformat()}
        # On retire les codes périmés puis on ajoute celui-ci en gardant les 20 plus récents
        await db.settings.update_one({"_id": "global"}, {"$pull": {"tv_appairages": {"cree_le": {"$lt": limite}}}}, upsert=True)
        await db.settings.update_one({"_id": "global"}, {"$push": {"tv_appairages": {"$each": [entree], "$slice": -MAX_APPAIRAGES}}})
        return {"appairage_id": entree["id"], "code": entree["code"], "valide_minutes": VALIDITE_CODE_MIN}

    @api.get("/tv/appairage/{appairage_id}", tags=["Écran TV"])
    async def tv_etat_appairage(appairage_id: str, x_tv_secret: str = Header(default="")):
        """La télé attend l'accord de l'administrateur : « attente », « ok » (appairée) ou « expire » (redemander un code)."""
        s = await _reglages()
        h = empreinte(x_tv_secret)
        if any(e.get("empreinte") == h for e in s.get("tv_ecrans") or []):
            return {"etat": "ok"}
        limite = (_maintenant() - timedelta(minutes=VALIDITE_CODE_MIN)).isoformat()
        for a in s.get("tv_appairages") or []:
            if a.get("id") == appairage_id and a.get("empreinte") == h and a.get("cree_le", "") >= limite:
                return {"etat": "attente"}
        return {"etat": "expire"}

    async def _ecran_de_la_tele(secret: str) -> Dict[str, Any]:
        """Retrouve l'écran appairé par l'empreinte de son secret ; sinon 401 (la télé redemande un code)."""
        if not secret:
            raise HTTPException(status_code=401, detail="Écran non appairé")
        h = empreinte(secret)
        s = await _reglages()   # la liste des écrans est minuscule : on la filtre ici
        ecran = next((e for e in s.get("tv_ecrans") or [] if e.get("empreinte") == h), None)
        if not ecran:
            raise HTTPException(status_code=401, detail="Écran non appairé ou révoqué")
        return ecran

    # ---------------- Lot 317 : code PIN du « Suivi Support » (messages + demandes de support) ----------------
    @api.post("/tv/pin", tags=["Écran TV"])
    async def tv_deverrouiller(corps: Dict[str, Any] = Body(...), x_tv_secret: str = Header(default="")):
        """La télé envoie le code saisi à la télécommande ; le serveur le compare à l'empreinte enregistrée dans les Paramètres.
        Réussite : un jeton valable 10 minutes (la télé le renvoie à chaque lecture). Échecs répétés : écran bloqué 60 secondes."""
        ecran = await _ecran_de_la_tele(x_tv_secret)
        s = await _reglages()
        pin = s.get("tv_pin") or {}
        if not pin.get("hash"):
            raise HTTPException(status_code=409, detail="Aucun code PIN défini dans les Paramètres")
        maintenant = _maintenant()
        if (ecran.get("pin_bloque_jusqua") or "") > maintenant.isoformat():
            raise HTTPException(status_code=429, detail="Trop d'essais : patientez une minute")
        saisi = str(corps.get("pin") or "")
        if not (pin_valide(saisi) and secrets.compare_digest(hacher_pin(saisi, pin.get("sel", "")), pin["hash"])):
            echecs = int(ecran.get("pin_echecs") or 0) + 1
            maj = {"tv_ecrans.$.pin_echecs": 0 if echecs >= PIN_ESSAIS_MAX else echecs}
            if echecs >= PIN_ESSAIS_MAX:
                maj["tv_ecrans.$.pin_bloque_jusqua"] = (maintenant + timedelta(seconds=PIN_BLOCAGE_S)).isoformat()
            await db.settings.update_one({"_id": "global", "tv_ecrans.id": ecran["id"]}, {"$set": maj})
            raise HTTPException(status_code=403, detail="Code incorrect")
        jeton = secrets.token_urlsafe(18)
        await db.settings.update_one({"_id": "global", "tv_ecrans.id": ecran["id"]}, {"$set": {
            "tv_ecrans.$.pin_echecs": 0, "tv_ecrans.$.deverrou_hash": empreinte(jeton), "tv_ecrans.$.deverrou_admin": False,
            "tv_ecrans.$.deverrou_expire": (maintenant + timedelta(minutes=DEVERROU_MIN)).isoformat()}})
        return {"jeton": jeton, "valide_minutes": DEVERROU_MIN}

    # ---------------- Lot 323 : « connexion administrateur » approuvée depuis SAWALI (aucun mot de passe tapé sur la télé) ----------------
    @api.post("/tv/admin-demande", tags=["Écran TV"])
    async def tv_demander_approbation(corps: Dict[str, Any] = Body(...), x_tv_secret: str = Header(default="")):
        """La télé fabrique un jeton secret (gardé en mémoire de la page), n'en envoie que l'empreinte et reçoit un CODE à 6 caractères.
        L'administrateur, déjà connecté à SAWALI avec son compte, saisit ce code (Paramètres → Écrans TV → « Approuver une télé »)."""
        ecran = await _ecran_de_la_tele(x_tv_secret)
        jeton = str(corps.get("jeton") or "")
        if not (16 <= len(jeton) <= 80):
            raise HTTPException(status_code=400, detail="Jeton invalide")
        code = nouveau_code()
        expire = (_maintenant() + timedelta(minutes=APPROBATION_MIN)).isoformat()
        await db.settings.update_one({"_id": "global", "tv_ecrans.id": ecran["id"]}, {"$set": {
            "tv_ecrans.$.admin_demande": {"code": code, "hash": empreinte(jeton), "expire": expire}}})
        return {"code": code, "valide_minutes": APPROBATION_MIN}

    @api.get("/tv/flux", tags=["Écran TV"])
    async def tv_flux(x_tv_secret: str = Header(default=""), x_tv_deverrou: str = Header(default=""), fil: str = Query("", max_length=40), photos: int = Query(0), jours: int = Query(1)):
        """Contenu à afficher : derniers messages du client et demandes de support ouvertes (selon les contenus choisis).
        `fil` (lot 301) : clé d'une conversation choisie sur la télé ; le fil en direct ne montre alors que ses messages."""
        ecran = await _ecran_de_la_tele(x_tv_secret)
        modules = modules_valides(ecran.get("modules"))
        ids = await _perimetre(ecran.get("client_id"))
        # Lot 317 : messages et demandes de support ne sortent du serveur qu'avec le jeton obtenu par le code PIN (jamais sur le seul secret de la télé)
        pin_defini = bool(((await _reglages()).get("tv_pin") or {}).get("hash"))
        suivi_possible = bool(modules["messagerie"] or modules["support"])      # lot 323 : possible aussi sans PIN (connexion administrateur)
        suivi_ouvert = bool(suivi_possible and x_tv_deverrou and ecran.get("deverrou_hash") == empreinte(x_tv_deverrou)
                            and (ecran.get("deverrou_expire") or "") > _maintenant().isoformat())
        # Lot 323 : session ouverte par un ADMINISTRATEUR (approbation depuis SAWALI) : les patients du hall s'affichent en clair
        admin_ouvert = bool(suivi_ouvert and ecran.get("deverrou_admin"))
        modules_servis = {**modules, "messagerie": modules["messagerie"] and suivi_ouvert, "support": modules["support"] and suivi_ouvert}
        flux: Dict[str, Any] = {"ecran": {"nom": ecran.get("nom"), "modules": modules, "taille_heure": taille_heure_valide(ecran.get("taille_heure")),
                                          "suivi_possible": suivi_possible, "suivi_ouvert": suivi_ouvert, "pin_defini": pin_defini, "admin": admin_ouvert},
                                "maintenant": _maintenant().isoformat(),
                                "page": PAGE_TV_VERSION}      # lot 307 : la page de la télé se recharge seule si elle n'est pas à cette version
        if modules_servis["messagerie"]:
            docs = await db.whatsapp_messages.find(
                {"client_id": {"$in": ids}},
                {"_id": 0, "id": 1, "direction": 1, "body": 1, "message_type": 1, "contact_id": 1, "contact_name": 1, "from_profile_name": 1,
                 "phone_digits": 1, "from": 1, "to": 1, "received_at": 1, "sent_at": 1, "created_at": 1,
                 "ai_generated": 1, "auto_reply": 1, "agent_ia": 1},
            ).sort("created_at", -1).to_list(900 if fil else FENETRE_FILS + 300)
            # Lot 303 : on retire les conversations des patients rappelés pour un RDV (UNE lecture des RDV récents)
            limite_rdv = (_maintenant() - timedelta(days=JOURS_RDV_MASQUES)).isoformat()
            numeros_rdv = set()
            async for r in db.planning_appointments.find({"reminder_sent_at": {"$gte": limite_rdv}}, {"_id": 0, "patient_phone": 1}).limit(3000):
                if derniers8(r.get("patient_phone")):
                    numeros_rdv.add(derniers8(r.get("patient_phone")))
            docs = [d for d in docs if not est_conversation_rdv(d, numeros_rdv)]
            # Noms des contacts : celui du message, sinon la fiche du carnet (UNE lecture pour tous les contacts concernés)
            ids_contacts = list({d["contact_id"] for d in docs if d.get("contact_id") and not d.get("contact_name")})
            noms = {}
            if ids_contacts:
                async for c in db.directory_contacts.find({"id": {"$in": ids_contacts}}, {"_id": 0, "id": 1, "name": 1}):
                    noms[c["id"]] = c.get("name") or ""
            for d in docs:
                if not d.get("contact_name") and noms.get(d.get("contact_id")):
                    d["contact_name"] = noms[d["contact_id"]]
            # Non-lus par conversation (même critère que le Centre de Messagerie : entrant, « read_by_us_at » vide), UNE agrégation
            depuis = (_maintenant() - timedelta(days=JOURS_NON_LUS)).isoformat()
            non_lus: Dict[str, int] = {}
            async for d in db.whatsapp_messages.find(
                    {"client_id": {"$in": ids}, "direction": "inbound", "read_by_us_at": None, "created_at": {"$gte": depuis}},
                    {"_id": 0, "contact_id": 1, "phone_digits": 1, "from": 1}).limit(5000):
                if est_conversation_rdv(d, numeros_rdv):
                    continue                                       # lot 303 : jamais de non-lu pour une conversation de RDV
                cle = cle_fil(d)
                non_lus[cle] = non_lus.get(cle, 0) + 1
            flux["fils"] = forme_fils(docs[:FENETRE_FILS], non_lus, {})
            flux["non_lus_total"] = sum(non_lus.values())
            # Fil en direct : tous les messages récents, ou ceux de la conversation choisie sur la télé (lot 301)
            retenus = [d for d in docs if cle_fil(d) == fil] if fil else docs
            flux["fil_choisi"] = fil or None
            flux["messages"] = [forme_message(d) for d in reversed(retenus[:MAX_MESSAGES])]   # du plus ancien au plus récent : le nouveau arrive en bas
        if modules_servis["support"]:
            docs = await db.support_tickets.find(
                {"client_id": {"$in": ids}, "status": {"$in": list(STATUTS_OUVERTS)}},
                {"_id": 0, "id": 1, "number": 1, "motif": 1, "contact_name": 1, "status": 1, "opened_at": 1},
            ).sort("opened_at", -1).to_list(MAX_TICKETS)
            flux["support"] = [forme_ticket(d) for d in docs]
        if modules["hall"]:
            # Consultations du jour : UNE lecture des RDV et arrivées du jour pour tous les médecins, regroupées en mémoire
            maintenant = _maintenant()
            j0, j1 = borne_jour(maintenant)
            # Lot 319 : horizon du planning = 1 jour (défaut, libre), 3 jours ou 7 jours — réservé à une télé déverrouillée par le code PIN
            horizon = jours if (jours in (3, 7) and suivi_ouvert) else 1
            j_fin = j1 + timedelta(days=horizon - 1)      # fin de la période des RDV ; les consultations sans RDV restent celles d'aujourd'hui
            # Lot 309 : les RDV d'une même clinique peuvent être rangés sous plusieurs comptes (médecins rattachés différemment) :
            # on prend aussi tous ceux qui portent le MÊME code clinique (ex. CMCO) que les RDV du périmètre de l'écran.
            codes = [c for c in await db.planning_appointments.distinct("code_clinique", {"tenant_id": {"$in": ids}}) if c and c != "manual"]
            perimetre = {"$or": [{"tenant_id": {"$in": ids}}, {"code_clinique": {"$in": codes}}]} if codes else {"tenant_id": {"$in": ids}}
            jour_q = {"$or": [{"start_at": {"$gte": j0.isoformat(), "$lt": j_fin.isoformat()}},
                              {"is_rdv": 0, "walk_in_list": {"$regex": f"^{j0.strftime('%y%m%d')}:"}},
                              {"is_rdv": 0, "received_at": {"$gte": j0.isoformat(), "$lt": j1.isoformat()}}]}
            docs = await db.planning_appointments.find(
                {"$and": [perimetre, jour_q]},
                {"_id": 0, "medecin": 1, "is_rdv": 1, "start_at": 1, "received_at": 1, "created_at": 1, "updated_at": 1,
                 "numero_ordre": 1, "status": 1, "patient": 1, "patient_phone": 1, "numero_recu": 1, "etat_consult": 1},
            ).to_list(2000)
            r = await _reglages_portes()
            # Lot 303 : les photos (lourdes) ne sont envoyées que si la télé les demande (au démarrage puis de temps en temps)
            flux["hall"] = forme_hall(docs, {p["medecin"].lower(): p["porte"] for p in r}, maintenant,
                                      fiches={p["medecin"].lower(): p for p in r}, avec_photos=bool(photos), limite=14 * horizon, en_clair=admin_ouvert)
            flux["hall"]["horizon"] = horizon
            # Lot 321 : QR « suivre mon RDV » sur l'écran du hall (si le service est activé dans les Paramètres)
            flux["suivi_rdv"] = bool(((await db.settings.find_one({"_id": "global"}, {"suivi_rdv": 1})) or {}).get("suivi_rdv", {}).get("actif"))
        # « Vu le » : écrit au plus une fois par minute (pas une écriture à chaque rafraîchissement)
        vu = ecran.get("vu_le") or ""
        if not vu or vu < (_maintenant() - timedelta(minutes=1)).isoformat():
            await db.settings.update_one({"_id": "global", "tv_ecrans.id": ecran["id"]}, {"$set": {"tv_ecrans.$.vu_le": _maintenant().isoformat()}})
        return flux

    # ---------------- Côté administrateur ----------------
    @api.get("/admin/tv/ecrans", tags=["Admin — Écrans TV"])
    async def admin_tv_liste(user: dict = Depends(get_current_admin)):
        s = await _reglages()
        secrets_ecran = {"empreinte", "deverrou_hash", "deverrou_expire", "pin_echecs", "pin_bloque_jusqua", "admin_demande", "deverrou_admin", "deverrou_par"}
        return {"ecrans": [{k: v for k, v in e.items() if k not in secrets_ecran} for e in s.get("tv_ecrans") or []]}

    @api.post("/admin/tv/approuver", tags=["Admin — Écrans TV"])
    async def admin_tv_approuver(corps: Dict[str, Any] = Body(...), user: dict = Depends(get_current_admin)):
        """Lot 323 : l'administrateur (connecté à SAWALI avec son propre compte) saisit le code affiché par la télé : cette télé est déverrouillée
        10 minutes en mode administrateur (Suivi Support, messagerie, planning sur 3 jours / semaine, patients en clair)."""
        code = "".join(ch for ch in str(corps.get("code") or "").upper() if ch.isalnum())
        maintenant = _maintenant()
        s = await _reglages()
        ecran = next((e for e in s.get("tv_ecrans") or [] if code and (e.get("admin_demande") or {}).get("code") == code
                      and (e["admin_demande"].get("expire") or "") > maintenant.isoformat()), None)
        if not ecran:
            raise HTTPException(status_code=404, detail="Code inconnu ou expiré : relancez « Connexion administrateur » sur la télé")
        await db.settings.update_one({"_id": "global", "tv_ecrans.id": ecran["id"]}, {
            "$set": {"tv_ecrans.$.deverrou_hash": ecran["admin_demande"]["hash"], "tv_ecrans.$.deverrou_admin": True,
                     "tv_ecrans.$.deverrou_par": str(user.get("email") or ""),
                     "tv_ecrans.$.deverrou_expire": (maintenant + timedelta(minutes=DEVERROU_MIN)).isoformat()},
            "$unset": {"tv_ecrans.$.admin_demande": ""}})
        return {"ok": True, "ecran": ecran.get("nom"), "valide_minutes": DEVERROU_MIN}

    @api.get("/admin/tv/pin", tags=["Admin — Écrans TV"])
    async def admin_tv_pin_etat(user: dict = Depends(get_current_admin)):
        """Un code PIN est-il défini ? (jamais le code lui-même)"""
        return {"defini": bool(((await _reglages()).get("tv_pin") or {}).get("hash"))}

    @api.put("/admin/tv/pin", tags=["Admin — Écrans TV"])
    async def admin_tv_pin_definir(corps: Dict[str, Any] = Body(...), user: dict = Depends(get_current_admin)):
        """Définit le code PIN (4 à 8 chiffres) du Suivi Support ; code vide = suppression (le Suivi Support n'est alors plus accessible)."""
        pin = str(corps.get("pin") or "").strip()
        if not pin:
            await db.settings.update_one({"_id": "global"}, {"$unset": {"tv_pin": ""}}, upsert=True)
            return {"defini": False}
        if not pin_valide(pin):
            raise HTTPException(status_code=400, detail=f"Le code PIN doit comporter de {PIN_MIN} à {PIN_MAX} chiffres")
        sel = secrets.token_hex(8)
        await db.settings.update_one({"_id": "global"}, {"$set": {"tv_pin": {"sel": sel, "hash": hacher_pin(pin, sel)}}}, upsert=True)
        return {"defini": True}

    @api.get("/admin/tv/portes", tags=["Admin — Écrans TV"])
    async def admin_tv_portes(user: dict = Depends(get_current_admin)):
        """Portes réglées + médecins vus dans le Planning (30 derniers jours) pour la liste déroulante de l'écran."""
        depuis = (_maintenant() - timedelta(days=30)).isoformat()
        try:
            medecins = await db.planning_appointments.distinct("medecin", {"received_at": {"$gte": depuis}})
        except Exception:  # la liste des médecins est un confort : jamais d'erreur 500 pour elle
            medecins = []
        return {"portes": await _reglages_portes(), "medecins_connus": sorted(m for m in medecins if m)}

    @api.put("/admin/tv/portes", tags=["Admin — Écrans TV"])
    async def admin_tv_portes_enregistrer(corps: Dict[str, Any] = Body(...), user: dict = Depends(get_current_admin)):
        portes = normaliser_portes(corps.get("portes"))
        await db.settings.update_one({"_id": "global"}, {"$set": {"tv_portes": portes}}, upsert=True)
        return {"ok": True, "portes": portes}

    @api.post("/admin/tv/appairer", tags=["Admin — Écrans TV"])
    async def admin_tv_appairer(payload: EcranAppairage, user: dict = Depends(get_current_admin)):
        """Associe le code affiché par la télé à un client et à des contenus."""
        s = await _reglages()
        limite = (_maintenant() - timedelta(minutes=VALIDITE_CODE_MIN)).isoformat()
        code = payload.code.strip().upper().replace(" ", "").replace("-", "")
        appairage = next((a for a in s.get("tv_appairages") or [] if a.get("code") == code and a.get("cree_le", "") >= limite), None)
        if not appairage:
            raise HTTPException(status_code=404, detail="Code inconnu ou expiré : relancez la page /tv sur la télé pour obtenir un nouveau code.")
        client = await db.users.find_one({"id": payload.client_id}, {"_id": 0, "id": 1, "company": 1, "full_name": 1})
        if not client:
            raise HTTPException(status_code=404, detail="Client introuvable")
        ecran = {"id": uuid.uuid4().hex, "nom": payload.nom.strip(), "code": code, "client_id": payload.client_id,
                 "client_nom": client.get("company") or client.get("full_name") or "",
                 "modules": modules_valides(payload.modules or {"messagerie": True, "support": True}),
                 "empreinte": appairage["empreinte"], "cree_le": _maintenant().isoformat(), "cree_par": user.get("email"), "vu_le": None}
        await db.settings.update_one({"_id": "global"}, {"$push": {"tv_ecrans": ecran}, "$pull": {"tv_appairages": {"id": appairage["id"]}}})
        return {"ok": True, "ecran": {k: v for k, v in ecran.items() if k != "empreinte"}}

    @api.put("/admin/tv/ecrans/{ecran_id}", tags=["Admin — Écrans TV"])
    async def admin_tv_modifier(ecran_id: str, payload: EcranModif, user: dict = Depends(get_current_admin)):
        champs: Dict[str, Any] = {}
        if payload.nom is not None and payload.nom.strip():
            champs["tv_ecrans.$.nom"] = payload.nom.strip()
        if payload.client_id:
            client = await db.users.find_one({"id": payload.client_id}, {"_id": 0, "company": 1, "full_name": 1})
            if not client:
                raise HTTPException(status_code=404, detail="Client introuvable")
            champs["tv_ecrans.$.client_id"] = payload.client_id
            champs["tv_ecrans.$.client_nom"] = client.get("company") or client.get("full_name") or ""
        if payload.modules is not None:
            champs["tv_ecrans.$.modules"] = modules_valides(payload.modules)
        if payload.taille_heure is not None:
            if payload.taille_heure not in TAILLES_HEURE:
                raise HTTPException(status_code=400, detail="Taille inconnue : " + ", ".join(TAILLES_HEURE))
            champs["tv_ecrans.$.taille_heure"] = payload.taille_heure
        if not champs:
            return {"ok": True}
        res = await db.settings.update_one({"_id": "global", "tv_ecrans.id": ecran_id}, {"$set": champs})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Écran introuvable")
        # Lot 303 : on renvoie ce qui est réellement enregistré (l'écran d'administration s'aligne dessus)
        s2 = await _reglages()
        ecran = next((e for e in s2.get("tv_ecrans") or [] if e.get("id") == ecran_id), {})
        return {"ok": True, "modules": modules_valides(ecran.get("modules")), "taille_heure": taille_heure_valide(ecran.get("taille_heure"))}

    @api.delete("/admin/tv/ecrans/{ecran_id}", tags=["Admin — Écrans TV"])
    async def admin_tv_revoquer(ecran_id: str, user: dict = Depends(get_current_admin)):
        """Révoque l'écran : sa télé est refusée à son prochain rafraîchissement et redemande un code."""
        res = await db.settings.update_one({"_id": "global"}, {"$pull": {"tv_ecrans": {"id": ecran_id}}})
        if res.modified_count == 0:
            raise HTTPException(status_code=404, detail="Écran introuvable")
        return {"ok": True}
