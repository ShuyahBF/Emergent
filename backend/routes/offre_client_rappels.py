# offre_client_rappels.py — Lot 210 : rappels d'échéance des logiciels, produits et services d'un client.
#
# Demande du propriétaire (16/10/2026) : « Chaque produit / prestation / service a une durée de souscription et un nombre de
# jours de rappel avant la fin (ex. outil de contrôle à distance : 30 j et 3 j : il doit être rappelé 3 jours avant la fin au
# contact décisionnaire du client). Chaque matin, Liluvine inspecte tous les produits et services de chaque client dont l'alerte
# a été autorisée, et envoie une notification WhatsApp à tous les décisionnaires du client / tenant : les produits expirent dans x jours. »
#
# En résumé (pour un développeur WinDev) :
#   - DONNÉES : sur chaque ligne de l'offre du client (db.users.offre_client, aucune nouvelle collection — cluster plein) :
#       date_debut  : début de la période en cours (AAAA-MM-JJ) ;  duree_jours : durée de la période (30 = un mois) ;
#       fin_de_mois : l'échéance est le DERNIER JOUR DU MOIS calendaire (lot 210.1 ; la durée en jours est alors ignorée) ;
#       rappel_jours: jours AVANT l'échéance où rappeler (ex. [7, 3]) ;  alerte_active : rappel AUTORISÉ pour cette ligne ;
#       reconduction: vrai = la période suivante commence à l'échéance (la date de début n'est pas à ressaisir) ;
#       rappels_envoyes : « échéance|palier » déjà envoyés (jamais deux fois le même rappel).
#   - ÉCHÉANCE = date_debut + duree_jours, ou le dernier jour du mois si « fin de mois » est coché. Avec reconduction, tant qu'elle est passée, on ajoute une durée.
#   - RAPPEL : à J − palier (un jour de rattrapage si l'envoi a échoué la veille). Une ligne inactive, sans alerte autorisée,
#     sans date de début ou sans durée n'est jamais rappelée.
#   - DESTINATAIRES : les contacts « décisionnaires » du client (directory_contacts.is_decision_maker). UN message par
#     décisionnaire regroupe toutes les lignes à rappeler ce jour-là.
#   - RÉGLAGES (db.settings {_id:"global"}, Paramètres → « 🧩 Offre du client — Liluvine ») :
#       offre_rappel_actif   : interrupteur général, DÉSACTIVÉ par défaut (rien n'est envoyé tant qu'il n'est pas activé) ;
#       offre_rappel_modele  : modèle WhatsApp approuvé par Meta (3 variables : contact, client, liste). Hors fenêtre de 24 h,
#                              WhatsApp n'accepte QUE un modèle : sans modèle, le texte libre n'arrive que si le contact a écrit récemment ;
#       offre_rappel_langue  : langue du modèle (fr par défaut) ;  offre_rappel_message : texte libre ({contact} {client} {liste}).
#   - SUIVI : dernier passage dans db.settings {_id:"offre_client_rappels"} (aucune nouvelle collection).
#   - TÂCHE : chaque matin à 07 h 30 (Abidjan), dans le planificateur ; JAMAIS dans la requête d'une page (règle 7).
# Lot 210.2 — MESSAGE PARAMÉTRABLE + MODÈLE META ASSOCIÉ : le texte libre ({contact} {client} {liste}) sert aussi de corps au modèle
#   WhatsApp ({contact} → {{1}}, {client} → {{2}}, {liste} → {{3}}). Dans la fenêtre de 24 h (le décisionnaire a écrit récemment) :
#   texte libre ; HORS fenêtre : modèle approuvé par Meta. « Créer le modèle chez Meta » le soumet (catégorie Utilitaire) à partir
#   du texte enregistré ; « Vérifier l'état » dit s'il est en revue, approuvé ou refusé. Meta n'autorise pas une variable au tout
#   début ni à la toute fin du texte : le serveur le contrôle à l'enregistrement.
# Routes (administrateur) : GET/PUT /api/admin/offre-client/rappels ; POST /api/admin/offre-client/rappels/executer {simuler} ;
#   GET / POST /api/admin/offre-client/rappels/modele (état chez Meta / création du modèle).
from __future__ import annotations

import calendar
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from routes.offre_client import normaliser_offre

logger = logging.getLogger("sawali.offre_client_rappels")

DOC_SUIVI = "offre_client_rappels"
MESSAGE_DEFAUT = ("Bonjour {contact}, ici l'assistant IA de SAWALI. Pour {client}, arrivent à échéance : {liste}. "
                  "Pensez à renouveler pour que le service reste actif ; contactez-nous si besoin.")
LANGUE_DEFAUT = "fr"
MODELE_DEFAUT = "rappel_echeance_produits"        # nom proposé du modèle Meta (minuscules, chiffres et _ seulement)
FENETRE_HEURES = 24                               # fenêtre de service WhatsApp : texte libre autorisé si le contact a écrit depuis moins de 24 h
RE_NOM_MODELE = re.compile(r"^[a-z0-9_]{1,100}$")
EXEMPLE_MODELE = ["Awa", "Pharmacie du Centre", "SAWALI CRM : dans 3 jours (le 31/10/2026) ; Contrôle à distance : dans 3 jours (le 31/10/2026)"]
MAX_DETAILS = 60          # lignes de détail gardées dans le dernier rapport


# ---------------------------------------------------------------------------------------------------------------------
# Calcul (fonctions pures, testées sans base)
# ---------------------------------------------------------------------------------------------------------------------
def _jour(texte: Any) -> Optional[date]:
    """Date AAAA-MM-JJ → date ; None si absente ou illisible."""
    try:
        return datetime.strptime(str(texte or "").strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def fin_du_mois(jour: date) -> date:
    """Dernier jour du mois calendaire de `jour` (28, 29, 30 ou 31)."""
    return jour.replace(day=calendar.monthrange(jour.year, jour.month)[1])


def echeance_ligne(ligne: Dict[str, Any], aujourdhui: date) -> Optional[date]:
    """Prochaine échéance d'une ligne.
    - « fin de mois calendaire » (lot 210.1) : dernier jour du mois de la date de début ; avec reconduction, dernier jour du
      mois en cours (donc chaque mois), la date de début n'étant alors même plus nécessaire ;
    - sinon début + durée ; avec reconduction, la première échéance qui n'est pas passée.
    None si les données manquent. Sans reconduction, une échéance passée reste passée."""
    debut, duree = _jour(ligne.get("date_debut")), int(ligne.get("duree_jours") or 0)
    if ligne.get("fin_de_mois") is True:
        reference = debut or (aujourdhui if ligne.get("reconduction") is not False else None)
        if not reference:
            return None
        fin = fin_du_mois(reference)
        return fin_du_mois(aujourdhui) if ligne.get("reconduction") is not False and fin < aujourdhui else fin
    if not debut or duree <= 0:
        return None
    fin = debut + timedelta(days=duree)
    if ligne.get("reconduction") is not False and fin < aujourdhui:
        periodes = -(-(aujourdhui - fin).days // duree)           # nombre entier de périodes à ajouter (arrondi supérieur)
        fin += timedelta(days=periodes * duree)
    return fin


def a_rappeler(ligne: Dict[str, Any], aujourdhui: date) -> Optional[Dict[str, Any]]:
    """Paliers à envoyer aujourd'hui pour une ligne, ou None.
    Conditions : ligne active, alerte autorisée, échéance connue, paliers réglés. Un palier p est dû si l'échéance est dans
    p jours (ou p − 1 : rattrapage d'un envoi raté la veille) et s'il n'a pas déjà été envoyé pour cette échéance."""
    if ligne.get("actif") is False or ligne.get("alerte_active") is not True:
        return None
    paliers = [int(p) for p in ligne.get("rappel_jours") or []]
    fin = echeance_ligne(ligne, aujourdhui)
    if not paliers or not fin:
        return None
    jours = (fin - aujourdhui).days
    envoyes = set(ligne.get("rappels_envoyes") or [])
    dus = [p for p in paliers if p - 1 <= jours <= p and f"{fin.isoformat()}|{p}" not in envoyes]
    if not dus:
        return None
    return {"ligne": ligne, "echeance": fin, "jours": jours, "paliers": dus,
            "cles": [f"{fin.isoformat()}|{p}" for p in dus]}


def phrase_echeance(nom: str, jours: int, fin: date) -> str:
    """« SAWALI CRM : dans 3 jour(s) (le 19/10/2026) »."""
    quand = "aujourd'hui" if jours == 0 else ("demain" if jours == 1 else f"dans {jours} jours") if jours >= 0 else f"depuis {-jours} jour(s)"
    return f"{nom} : {quand} (le {fin.strftime('%d/%m/%Y')})"


def texte_message(modele: str, contact: str, client: str, liste: List[str]) -> str:
    """Message libre : {contact}, {client} et {liste} remplacés (la liste est une ligne par produit, « • » en tête)."""
    corps = (modele or MESSAGE_DEFAUT).replace("{contact}", contact or "").replace("{client}", client or "")
    return corps.replace("{liste}", "\n" + "\n".join(f"• {x}" for x in liste) + "\n")


def variables_modele(contact: str, client: str, liste: List[str]) -> List[str]:
    """Variables du modèle Meta : sans retour à la ligne (interdits par WhatsApp dans une variable), séparateur « ; »."""
    nettoyer = lambda t: re.sub(r"\s+", " ", str(t or "")).strip()[:900] or "—"       # noqa: E731
    return [nettoyer(contact), nettoyer(client), nettoyer(" ; ".join(liste))]


def corps_modele(message: str) -> str:
    """Corps du modèle Meta déduit du texte libre : {contact} → {{1}}, {client} → {{2}}, {liste} → {{3}} (une seule ligne)."""
    texte = (message or MESSAGE_DEFAUT).replace("{contact}", "{{1}}").replace("{client}", "{{2}}").replace("{liste}", "{{3}}")
    return re.sub(r"\s+", " ", texte).strip()


def verifier_message(message: str) -> Optional[str]:
    """Texte d'erreur si le message ne peut pas servir de corps au modèle Meta, sinon None.
    Règles : {liste} obligatoire ; seules les variables {contact} {client} {liste} ; pas de variable au tout début ni à la toute
    fin du texte (règle Meta) ; pas de deux variables collées."""
    texte = (message or "").strip()
    if not texte:
        return None                                                   # vide = texte par défaut
    if "{liste}" not in texte:
        return "Le texte doit contenir {liste} (les produits à renouveler)."
    inconnues = sorted(set(re.findall(r"\{(\w+)\}", texte)) - {"contact", "client", "liste"})
    if inconnues:
        return "Variable inconnue : {" + inconnues[0] + "} (seulement {contact}, {client}, {liste})."
    corps = corps_modele(texte)
    if corps.startswith("{{") or corps.endswith("}}"):
        return "Meta refuse une variable au tout début ou à la toute fin : ajoutez un mot avant la première et après la dernière variable."
    if re.search(r"\}\}\s*\{\{", corps):
        return "Deux variables ne peuvent pas se suivre sans texte entre elles."
    return None


def definition_modele(nom: str, langue: str, message: str) -> Dict[str, Any]:
    """Corps JSON de POST /{waba}/message_templates : modèle UTILITAIRE à 3 variables, avec exemples (exigés par Meta)."""
    return {"name": nom, "language": langue, "category": "UTILITY",
            "components": [{"type": "BODY", "text": corps_modele(message), "example": {"body_text": [EXEMPLE_MODELE]}}]}


def reglages(settings_doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Réglages des rappels (désactivés par défaut)."""
    s = settings_doc or {}
    return {"actif": bool(s.get("offre_rappel_actif")),
            "modele": str(s.get("offre_rappel_modele") or "").strip()[:100],
            "langue": str(s.get("offre_rappel_langue") or "").strip()[:10] or LANGUE_DEFAUT,
            "message": str(s.get("offre_rappel_message") or "").strip()[:700] or MESSAGE_DEFAUT}


# ---------------------------------------------------------------------------------------------------------------------
# Envoi WhatsApp (modèle approuvé si réglé, sinon texte libre)
# ---------------------------------------------------------------------------------------------------------------------
async def fenetre_ouverte(telephone: str, maintenant: Optional[datetime] = None) -> bool:
    """Le décisionnaire a-t-il écrit à SAWALI depuis moins de 24 h ? (alors le texte libre est autorisé par WhatsApp)."""
    try:
        import server as srv
        dernier = await srv._wa_last_inbound_iso(None, phone_digits=telephone)
        if not dernier:
            return False
        recu = datetime.fromisoformat(str(dernier).replace("Z", "+00:00"))
        if recu.tzinfo is None:
            recu = recu.replace(tzinfo=timezone.utc)
        return ((maintenant or datetime.now(timezone.utc)) - recu) < timedelta(hours=FENETRE_HEURES)
    except Exception:  # noqa: BLE001 — en cas de doute, on passe par le modèle (toujours accepté)
        return False


async def envoyer_whatsapp(regl: Dict[str, Any], telephone: str, contact: str, client: str, liste: List[str]) -> Dict[str, Any]:
    """Envoie le rappel à un décisionnaire → {ok, erreur, canal}. Ne lève jamais.
    Fenêtre de 24 h ouverte : texte libre. Hors fenêtre : modèle Meta (s'il est réglé) ; sans modèle, le texte libre est tenté
    quand même (il n'arrive que si WhatsApp l'accepte) et l'erreur dit alors de créer le modèle."""
    try:
        import server as srv                       # les fonctions d'envoi WhatsApp vivent dans le module du serveur
        ouverte = await fenetre_ouverte(telephone)
        if regl["modele"] and not ouverte:
            composants = [{"type": "body", "parameters": [{"type": "text", "text": v} for v in variables_modele(contact, client, liste)]}]
            r = await srv._wa_send_template(f"+{telephone}", regl["modele"], regl["langue"], composants)
            canal = "modèle Meta"
        else:
            r = await srv._wa_send_text(f"+{telephone}", texte_message(regl["message"], contact, client, liste))
            canal = "texte libre"
        if r.get("ok"):
            return {"ok": True, "erreur": None, "canal": canal}
        erreur = str(r.get("error") or "échec WhatsApp")[:200]
        if canal == "texte libre" and not regl["modele"]:
            erreur += " — hors fenêtre de 24 h : créez et renseignez le modèle Meta (Paramètres → Offre du client)."
        return {"ok": False, "erreur": erreur, "canal": canal}
    except Exception as exc:  # noqa: BLE001 — un envoi en échec ne doit rien casser
        logger.warning("[offre_rappels] envoi WhatsApp impossible", exc_info=True)
        return {"ok": False, "erreur": str(exc)[:200], "canal": None}


# ---------------------------------------------------------------------------------------------------------------------
# Tâche quotidienne
# ---------------------------------------------------------------------------------------------------------------------
async def rappeler(db, maintenant: Optional[datetime] = None, envoyer: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
                   simuler: bool = False) -> Dict[str, Any]:
    """Inspecte les clients dont au moins une ligne a une alerte autorisée et prévient leurs décisionnaires.
    `simuler` : calcule et renvoie ce qui partirait, sans rien envoyer ni marquer. Interrupteur général éteint : rien ne part
    (sauf simulation). Lecture groupée : UNE requête pour les clients, UNE pour les décisionnaires (pas de boucle N+1).
    Renvoie {actif, simule, clients, messages, envoyes, echecs, sans_decisionnaire, details[]}. Ne lève jamais."""
    maintenant = maintenant or datetime.now(timezone.utc)
    aujourdhui = maintenant.date()
    envoyer = envoyer or envoyer_whatsapp
    rapport: Dict[str, Any] = {"le": maintenant.isoformat(), "simule": simuler, "actif": False, "clients": 0, "messages": 0,
                               "envoyes": 0, "echecs": 0, "sans_decisionnaire": 0, "details": []}
    try:
        regl = reglages(await db.settings.find_one({"_id": "global"}))
        rapport["actif"] = regl["actif"]
        if not regl["actif"] and not simuler:
            return rapport
        clients = await db.users.find({"offre_client": {"$elemMatch": {"alerte_active": True}}},
                                      {"_id": 0, "id": 1, "company": 1, "full_name": 1, "offre_client": 1}).to_list(2000)
        decideurs: Dict[str, List[Dict[str, Any]]] = {}
        async for c in db.directory_contacts.find({"client_id": {"$in": [u["id"] for u in clients]}, "is_decision_maker": True},
                                                  {"_id": 0, "client_id": 1, "name": 1, "phone": 1, "whatsapp": 1}):
            decideurs.setdefault(c["client_id"], []).append(c)
        for u in clients:
            lignes = normaliser_offre(u.get("offre_client"))
            dues = [d for d in (a_rappeler(l, aujourdhui) for l in lignes) if d]
            if not dues:
                continue
            rapport["clients"] += 1
            nom_client = u.get("company") or u.get("full_name") or "votre société"
            liste = [phrase_echeance(d["ligne"]["nom"], d["jours"], d["echeance"]) for d in dues]
            contacts = [(c.get("name") or "", re.sub(r"\D", "", str(c.get("whatsapp") or c.get("phone") or ""))) for c in decideurs.get(u["id"], [])]
            contacts = [(n, t) for n, t in contacts if t]
            detail: Dict[str, Any] = {"client": nom_client, "produits": liste, "destinataires": []}
            if not contacts:
                rapport["sans_decisionnaire"] += 1
                detail["alerte"] = "Aucun décisionnaire avec un numéro WhatsApp : personne n'a été prévenu."
            ok_un = False
            for nom, tel in contacts:
                rapport["messages"] += 1
                if simuler:
                    detail["destinataires"].append({"nom": nom, "telephone": f"+{tel}", "ok": None})
                    continue
                r = await envoyer(regl, tel, nom, nom_client, liste)
                ok_un = ok_un or bool(r.get("ok"))
                rapport["envoyes" if r.get("ok") else "echecs"] += 1
                detail["destinataires"].append({"nom": nom, "telephone": f"+{tel}", "ok": bool(r.get("ok")), "erreur": r.get("erreur"), "canal": r.get("canal")})
            if ok_un and not simuler:
                # Au moins un décisionnaire a été prévenu : les paliers sont marqués envoyés (jamais deux fois le même rappel)
                for d in dues:
                    marques = sorted({*d["ligne"].get("rappels_envoyes", []), *d["cles"]})[-12:]
                    await db.users.update_one({"id": u["id"], "offre_client.id": d["ligne"]["id"]},
                                              {"$set": {"offre_client.$.rappels_envoyes": marques}})
            rapport["details"].append(detail)
        rapport["details"] = rapport["details"][:MAX_DETAILS]
        if not simuler:
            await db.settings.update_one({"_id": DOC_SUIVI}, {"$set": {"dernier": rapport}}, upsert=True)
    except Exception as exc:  # noqa: BLE001 — la tâche quotidienne ne doit jamais s'arrêter sur une erreur
        logger.warning("[offre_rappels] passage en échec : %s", exc, exc_info=True)
        rapport["erreur"] = str(exc)[:200]
    return rapport


# ---------------------------------------------------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------------------------------------------------
class ReglagesRappelsIn(BaseModel):
    actif: bool = False
    modele: str = Field(default="", max_length=100)
    langue: str = Field(default=LANGUE_DEFAUT, max_length=10)
    message: str = Field(default="", max_length=700)


class ExecuterIn(BaseModel):
    simuler: bool = True


def setup_offre_client_rappels_routes(*, db, api, get_current_admin) -> None:
    """Branche les routes du lot 210 (appelée depuis server_parts/p20)."""
    from fastapi import Depends, HTTPException

    async def _etat() -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        suivi = await db.settings.find_one({"_id": DOC_SUIVI}) or {}
        avec_alerte = await db.users.count_documents({"offre_client": {"$elemMatch": {"alerte_active": True}}})
        regl = reglages(s)
        return {**regl, "message_defaut": MESSAGE_DEFAUT, "modele_defaut": MODELE_DEFAUT, "clients_avec_alerte": avec_alerte,
                "dernier": suivi.get("dernier"), "corps_modele": corps_modele(regl["message"]),
                "apercu": texte_message(regl["message"], *EXEMPLE_MODELE[:2], ["SAWALI CRM : dans 3 jours (le 31/10/2026)"])}

    async def _meta() -> tuple:
        """Jeton et compte WhatsApp Business de SAWALI ; HTTPException si WhatsApp n'est pas configuré."""
        g = await db.settings.find_one({"_id": "global"}) or {}
        jeton, waba = (g.get("wa_access_token") or "").strip(), (g.get("wa_business_account_id") or "").strip()
        if not jeton or not waba:
            raise HTTPException(status_code=400, detail="WhatsApp non configuré (WABA ID et Access Token dans les Paramètres)")
        return jeton, waba

    def _version() -> str:
        from routes import appel_proprietaire as ap
        return ap.GRAPH_VERSION

    @api.get("/admin/offre-client/rappels", tags=["Admin — Offre du client"])
    async def lire(_: dict = Depends(get_current_admin)):
        """Réglages des rappels d'échéance et dernier passage de Liluvine."""
        return await _etat()

    @api.put("/admin/offre-client/rappels", tags=["Admin — Offre du client"])
    async def ecrire(data: ReglagesRappelsIn, _: dict = Depends(get_current_admin)):
        """Interrupteur général, modèle WhatsApp et texte libre. Le texte libre doit contenir {liste}."""
        texte = data.message.strip()
        erreur = verifier_message(texte)
        if erreur:
            raise HTTPException(status_code=422, detail=erreur)
        if data.modele.strip() and not RE_NOM_MODELE.match(data.modele.strip()):
            raise HTTPException(status_code=422, detail="Nom du modèle : minuscules, chiffres et _ seulement (ex. rappel_echeance_produits).")
        await db.settings.update_one({"_id": "global"}, {"$set": {
            "offre_rappel_actif": bool(data.actif), "offre_rappel_modele": data.modele.strip(),
            "offre_rappel_langue": data.langue.strip() or LANGUE_DEFAUT, "offre_rappel_message": texte}}, upsert=True)
        return await _etat()

    @api.get("/admin/offre-client/rappels/modele", tags=["Admin — Offre du client"])
    async def etat_modele(_: dict = Depends(get_current_admin)):
        """État du modèle chez Meta : ABSENT, PENDING (en revue), APPROVED, REJECTED… (avec le motif d'un refus)."""
        import httpx
        regl = reglages(await db.settings.find_one({"_id": "global"}))
        if not regl["modele"]:
            return {"nom": "", "etat": "NON RENSEIGNÉ", "corps": corps_modele(regl["message"])}
        jeton, waba = await _meta()
        try:
            async with httpx.AsyncClient(timeout=15) as http:
                rep = await http.get(f"https://graph.facebook.com/{_version()}/{waba}/message_templates",
                                     params={"name": regl["modele"], "fields": "name,status,language,rejected_reason"},
                                     headers={"Authorization": f"Bearer {jeton}"})
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Meta injoignable ({type(exc).__name__})")
        donnees = (rep.json() or {}).get("data") if rep.status_code < 300 else None
        trouve = next((m for m in donnees or [] if m.get("language") == regl["langue"]), None)
        return {"nom": regl["modele"], "langue": regl["langue"], "corps": corps_modele(regl["message"]),
                "etat": (trouve or {}).get("status") or ("ABSENT" if donnees is not None else "INCONNU"),
                "motif_refus": (trouve or {}).get("rejected_reason")}

    @api.post("/admin/offre-client/rappels/modele", tags=["Admin — Offre du client"])
    async def creer_modele(_: dict = Depends(get_current_admin)):
        """Soumet à Meta le modèle construit depuis le TEXTE ENREGISTRÉ (approbation en général en quelques minutes).
        Un modèle de ce nom déjà présent n'est pas modifié : changer le nom (ex. …_v2) pour soumettre un nouveau texte."""
        import httpx
        regl = reglages(await db.settings.find_one({"_id": "global"}))
        if not regl["modele"]:
            raise HTTPException(status_code=422, detail="Renseignez et enregistrez d'abord le nom du modèle.")
        erreur = verifier_message(regl["message"])
        if erreur:
            raise HTTPException(status_code=422, detail=erreur)
        jeton, waba = await _meta()
        try:
            async with httpx.AsyncClient(timeout=20) as http:
                rep = await http.post(f"https://graph.facebook.com/{_version()}/{waba}/message_templates",
                                      json=definition_modele(regl["modele"], regl["langue"], regl["message"]),
                                      headers={"Authorization": f"Bearer {jeton}", "Content-Type": "application/json"})
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Meta injoignable ({type(exc).__name__})")
        try:
            brut = rep.json()
        except Exception:  # noqa: BLE001
            brut = {}
        if rep.status_code < 300:
            return {"ok": True, "etat": brut.get("status") or "PENDING", "nom": regl["modele"]}
        msg = ((brut.get("error") or {}).get("error_user_msg") or (brut.get("error") or {}).get("message") or f"HTTP {rep.status_code}")
        if "already" in msg.lower() or "existe" in msg.lower():
            return {"ok": False, "etat": "EXISTANT", "nom": regl["modele"],
                    "erreur": "Un modèle de ce nom existe déjà chez Meta (son texte n'est pas modifié). Pour soumettre un nouveau "
                              "texte, changez le nom du modèle (ex. " + regl["modele"] + "_v2), enregistrez puis recréez."}
        return {"ok": False, "etat": "ERREUR", "nom": regl["modele"], "erreur": msg}

    @api.post("/admin/offre-client/rappels/executer", tags=["Admin — Offre du client"])
    async def executer(data: ExecuterIn, _: dict = Depends(get_current_admin)):
        """Lance le passage de Liluvine maintenant. `simuler` (par défaut) : montre ce qui partirait, sans rien envoyer."""
        return await rappeler(db, simuler=data.simuler)
