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
# Lot 210.3 — MONTANT ET AVIS DU PROPRIÉTAIRE : chaque ligne porte le montant de la souscription POUR CE CLIENT (+ devise).
#   Mode « avis » (par défaut) : chaque matin Liluvine envoie AU PROPRIÉTAIRE, comme pour les retards de paiement, une liste
#   numérotée « client · contacts · produit · montant · échéance » ; rien n'est envoyé aux clients sans son accord. Il répond
#   « rappel 1,2,5 » (ou « rappel tous ») : Liluvine envoie alors ces rappels aux décisionnaires et confirme. (Mot « rappel » et
#   non « ok », déjà pris par les relances de retard de paiement.) Mode « auto » : envoi direct aux décisionnaires (lot 210).
#   Réglage offre_rappel_mode (db.settings global) : « avis » | « auto ». Récapitulatif gardé dans db.settings {_id:"offre_client_recap"}.
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


def montant_texte(montant: Any, devise: str = "FCFA") -> str:
    """« 25 000 FCFA » ; chaîne vide si le montant est nul ou absent."""
    try:
        m = float(montant or 0)
    except (TypeError, ValueError):
        return ""
    if m <= 0:
        return ""
    corps = f"{m:,.0f}" if m == int(m) else f"{m:,.2f}"
    return f"{corps.replace(',', ' ')} {devise or 'FCFA'}"


def phrase_echeance(nom: str, jours: int, fin: date, montant: Any = 0, devise: str = "FCFA") -> str:
    """« SAWALI CRM : dans 3 jours (le 31/10/2026) — 25 000 FCFA » (montant seulement s'il est renseigné)."""
    quand = "aujourd'hui" if jours == 0 else ("demain" if jours == 1 else f"dans {jours} jours") if jours >= 0 else f"depuis {-jours} jour(s)"
    argent = montant_texte(montant, devise)
    return f"{nom} : {quand} (le {fin.strftime('%d/%m/%Y')})" + (f" — {argent}" if argent else "")


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
    mode = str(s.get("offre_rappel_mode") or "avis").strip().lower()
    return {"actif": bool(s.get("offre_rappel_actif")), "mode": mode if mode in ("avis", "auto") else "avis",
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
# Collecte : qui doit être rappelé aujourd'hui, et pour quoi
# ---------------------------------------------------------------------------------------------------------------------
DOC_RECAP = "offre_client_recap"            # récapitulatif du jour envoyé au propriétaire (db.settings, aucune collection)
JOURNAL_MAX = 200
# Réponse du propriétaire : « rappel 1,2,5 », « rappels 1 et 3 », « rappel tous » (« ok » est déjà pris par les retards de paiement)
MOTIF_REPONSE = re.compile(r"^\s*rappels?\b[\s:,-]*(?P<choix>(?:tous|tout|\d+)(?:\s*(?:,|;|et|&|-|\s)\s*\d+)*)\s*[.!]?\s*$",
                           re.IGNORECASE)


async def collecter(db, aujourdhui: date) -> List[Dict[str, Any]]:
    """Un élément par (client, ligne) à rappeler aujourd'hui, avec les décisionnaires du client.
    Lecture groupée : UNE requête pour les clients, UNE pour les décisionnaires (pas de boucle N+1).
    Élément : {client_id, client, ligne_id, produit, montant, devise, jours, echeance, cles, texte, contacts[{nom, tel}]}."""
    clients = await db.users.find({"offre_client": {"$elemMatch": {"alerte_active": True}}},
                                  {"_id": 0, "id": 1, "company": 1, "full_name": 1, "offre_client": 1}).to_list(2000)
    decideurs: Dict[str, List[Dict[str, str]]] = {}
    async for c in db.directory_contacts.find({"client_id": {"$in": [u["id"] for u in clients]}, "is_decision_maker": True},
                                              {"_id": 0, "client_id": 1, "name": 1, "phone": 1, "whatsapp": 1}):
        tel = re.sub(r"\D", "", str(c.get("whatsapp") or c.get("phone") or ""))
        if tel:
            decideurs.setdefault(c["client_id"], []).append({"nom": c.get("name") or "", "tel": tel})
    elements: List[Dict[str, Any]] = []
    for u in clients:
        nom_client = u.get("company") or u.get("full_name") or "votre société"
        for d in (a_rappeler(l, aujourdhui) for l in normaliser_offre(u.get("offre_client"))):
            if not d:
                continue
            l = d["ligne"]
            elements.append({
                "client_id": u["id"], "client": nom_client, "ligne_id": l["id"], "produit": l["nom"],
                "montant": l.get("montant") or 0, "devise": l.get("devise") or "FCFA", "jours": d["jours"],
                "echeance": d["echeance"].isoformat(), "cles": d["cles"],
                "texte": phrase_echeance(l["nom"], d["jours"], d["echeance"], l.get("montant"), l.get("devise")),
                "contacts": decideurs.get(u["id"], [])})
    elements.sort(key=lambda e: (e["jours"], e["client"].lower(), e["produit"].lower()))
    for n, e in enumerate(elements, start=1):
        e["n"] = n
    return elements


def texte_recap(elements: List[Dict[str, Any]], une_ligne: bool = False) -> str:
    """Récapitulatif envoyé au propriétaire : client · contacts · produit · montant · échéance. `une_ligne` pour un modèle Meta."""
    lignes = []
    for e in elements:
        qui = ", ".join(c["nom"] or "contact" for c in e["contacts"]) or "⚠ aucun décisionnaire"
        lignes.append(f"{e['n']}) {e['client']} — {qui} — {e['texte']}")
    consigne = "Répondez « rappel 1,2,5 » (ou « rappel tous ») pour les envoyer aux décisionnaires ; sans réponse, rien n'est envoyé."
    if une_ligne:
        return f"{len(elements)} échéance(s) de produits/services : " + " · ".join(lignes) + f" — {consigne}"
    return f"🔔 {len(elements)} échéance(s) de produits/services à rappeler :\n" + "\n".join(lignes) + f"\n\n{consigne}"


def lire_choix(texte: Optional[str], nombre: int) -> Optional[tuple]:
    """« rappel 1,2,5 » → ([1, 2, 5], [numéros invalides]) ; « rappel tous » → tous ; None si ce n'est pas une réponse."""
    m = MOTIF_REPONSE.match(texte or "")
    if not m:
        return None
    choix = m.group("choix").strip().lower()
    if choix in ("tous", "tout"):
        return list(range(1, nombre + 1)), []
    valides, invalides = [], []
    for brut in re.findall(r"\d+", choix):
        n = int(brut)
        if 1 <= n <= nombre:
            if n not in valides:
                valides.append(n)
        else:
            invalides.append(brut)
    return valides, invalides


# ---------------------------------------------------------------------------------------------------------------------
# Envoi aux décisionnaires d'une sélection d'éléments (mode auto, ou accord du propriétaire)
# ---------------------------------------------------------------------------------------------------------------------
async def envoyer_selection(db, elements: List[Dict[str, Any]], regl: Dict[str, Any],
                            envoyer: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None) -> List[Dict[str, Any]]:
    """Envoie les éléments : UN message par décisionnaire et par client (toutes ses échéances regroupées).
    Au moins un décisionnaire prévenu → les paliers de ces lignes sont marqués envoyés (jamais deux fois le même rappel).
    Renvoie un détail par client : {client, produits, alerte?, destinataires[{nom, telephone, ok, erreur, canal}]}."""
    envoyer = envoyer or envoyer_whatsapp
    par_client: Dict[str, List[Dict[str, Any]]] = {}
    for e in elements:
        par_client.setdefault(e["client_id"], []).append(e)
    details: List[Dict[str, Any]] = []
    for cid, items in par_client.items():
        detail: Dict[str, Any] = {"client": items[0]["client"], "produits": [e["texte"] for e in items], "destinataires": []}
        contacts = {c["tel"]: c["nom"] for e in items for c in e["contacts"]}
        if not contacts:
            detail["alerte"] = "Aucun décisionnaire avec un numéro WhatsApp : personne n'a été prévenu."
        ok_un = False
        for tel, nom in contacts.items():
            r = await envoyer(regl, tel, nom, items[0]["client"], detail["produits"])
            ok_un = ok_un or bool(r.get("ok"))
            detail["destinataires"].append({"nom": nom, "telephone": f"+{tel}", "ok": bool(r.get("ok")),
                                            "erreur": r.get("erreur"), "canal": r.get("canal")})
        if ok_un:
            # Une seule lecture de la fiche du client (pas de lecture par ligne), puis une mise à jour ciblée par ligne
            fiche = await db.users.find_one({"id": cid}, {"_id": 0, "offre_client": 1}) or {}
            suivi = {l.get("id"): l.get("rappels_envoyes") or [] for l in (fiche.get("offre_client") or []) if isinstance(l, dict)}
            for e in items:
                await db.users.update_one({"id": cid, "offre_client.id": e["ligne_id"]},
                                          {"$set": {"offre_client.$.rappels_envoyes": sorted({*suivi.get(e["ligne_id"], []), *e["cles"]})[-12:]}})
        details.append(detail)
    return details


# ---------------------------------------------------------------------------------------------------------------------
# Récapitulatif pour avis du propriétaire
# ---------------------------------------------------------------------------------------------------------------------
async def envoyer_recap(db, s: Dict[str, Any], elements: List[Dict[str, Any]], maintenant: datetime, forcer: bool = False) -> Dict[str, Any]:
    """Envoie UN récapitulatif numéroté au propriétaire (comme les retards de paiement) et le mémorise.
    Une fois par jour (sauf `forcer`, bouton manuel). Texte libre si le propriétaire a écrit depuis moins de 24 h, sinon modèle
    « relais » de Liluvine."""
    from routes import appel_proprietaire as ap
    jour = maintenant.date().isoformat()
    if not elements:
        return {"envoye": False, "raison": "aucune échéance à rappeler"}
    precedent = await db.settings.find_one({"_id": DOC_RECAP}) or {}
    if precedent.get("jour") == jour and precedent.get("whatsapp_ok") and not forcer:
        return {"envoye": False, "raison": "récapitulatif déjà envoyé aujourd'hui"}
    proprio = re.sub(r"\D", "", str(s.get("super_admin_phone") or ""))
    res: Dict[str, Any] = {"envoye": False, "whatsapp_ok": False, "erreur": None}
    if proprio:
        cfg = ap.reglages(s)
        numero_id, _ligne = ap.ligne_appelante(s, cfg)
        r = await ap.envoyer_relais(db, s, cfg, numero_id, proprio, texte_recap(elements),
                                    ["Liluvine — échéances produits", texte_recap(elements, une_ligne=True), ap.formater_date(maintenant)],
                                    maintenant)
        res["whatsapp_ok"], res["erreur"] = bool(r.get("ok")), r.get("erreur")
    else:
        res["erreur"] = "numéro WhatsApp du propriétaire absent (Paramètres → Contrats)"
    res["envoye"] = res["whatsapp_ok"]
    await db.settings.update_one({"_id": DOC_RECAP}, {"$set": {
        "jour": jour, "envoye_le": maintenant.isoformat(), "elements": elements,
        "whatsapp_ok": res["whatsapp_ok"], "erreur": res["erreur"]}}, upsert=True)
    return res


async def traiter_reponse(db, s: Dict[str, Any], chiffres: str, texte: Optional[str],
                          envoyer: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
                          maintenant: Optional[datetime] = None) -> Optional[str]:
    """Appelé par le webhook WhatsApp pour chaque message texte reçu. Si c'est « rappel 1,2,5 » (ou « rappel tous ») du
    propriétaire en réponse au récapitulatif : envoie ces rappels aux décisionnaires et renvoie le texte de confirmation ;
    sinon None (message ordinaire, traité normalement)."""
    if not texte or not MOTIF_REPONSE.match(texte):
        return None
    from routes.retards_paiement import _est_proprietaire
    if not _est_proprietaire(s, chiffres):
        return None
    recap = await db.settings.find_one({"_id": DOC_RECAP}) or {}
    elements = recap.get("elements") or []
    if not elements:
        return "Aucun récapitulatif d'échéances en attente."
    choix = lire_choix(texte, len(elements))
    if choix is None:
        return None
    valides, invalides = choix
    maintenant = maintenant or datetime.now(timezone.utc)
    deja = [n for n in valides if elements[n - 1].get("envoye_le")]
    a_envoyer = [elements[n - 1] for n in valides if n not in deja]
    regl = reglages(s)
    details = await envoyer_selection(db, a_envoyer, regl, envoyer) if a_envoyer else []
    ok_par_client = {d["client"]: any(x["ok"] for x in d["destinataires"]) for d in details}
    reussis, echecs, journal = [], [], []
    for e in a_envoyer:
        ok = ok_par_client.get(e["client"], False)
        detail = next((d for d in details if d["client"] == e["client"]), {})
        qui = ", ".join(f"{x['nom'] or x['telephone']}{' ✓' if x['ok'] else ''}" for x in detail.get("destinataires", []))
        (reussis if ok else echecs).append(f"{e['n']} {e['client']} — {e['produit']}" + (f" ({qui})" if ok and qui else "")
                                           + ("" if ok else f" ({detail.get('alerte') or 'échec WhatsApp'})"))
        if ok:
            e["envoye_le"] = maintenant.isoformat()
        journal.append({"le": maintenant.isoformat(), "n": e["n"], "client": e["client"], "produit": e["produit"], "ok": ok})
    if a_envoyer:
        await db.settings.update_one({"_id": DOC_RECAP}, {"$set": {"elements": elements}, "$push": {"journal": {"$each": journal, "$slice": -JOURNAL_MAX}}})
    morceaux = []
    if reussis:
        morceaux.append("✅ Rappel envoyé : " + " ; ".join(reussis))
    if echecs:
        morceaux.append("⚠️ Non envoyé(s) : " + " ; ".join(echecs))
    if deja:
        morceaux.append("ℹ️ Déjà envoyé(s) : " + ", ".join(str(n) for n in deja))
    if invalides:
        morceaux.append(f"❓ Numéro(s) inconnu(s) : {', '.join(invalides)} (liste de 1 à {len(elements)})")
    return "\n".join(morceaux) or "Aucune échéance choisie."


# ---------------------------------------------------------------------------------------------------------------------
# Tâche quotidienne
# ---------------------------------------------------------------------------------------------------------------------
async def rappeler(db, maintenant: Optional[datetime] = None, envoyer: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
                   simuler: bool = False, forcer: bool = False) -> Dict[str, Any]:
    """Passage quotidien de Liluvine. Mode « avis » (défaut) : récapitulatif au propriétaire, qui répond « rappel 1,2 » ; mode
    « auto » : envoi direct aux décisionnaires. `simuler` : calcule et montre ce qui partirait, sans rien envoyer ni marquer.
    Interrupteur général éteint : rien ne part (sauf simulation). `forcer` : renvoie le récapitulatif même déjà envoyé aujourd'hui.
    Renvoie {actif, mode, simule, clients, messages, envoyes, echecs, sans_decisionnaire, recap, details[]}. Ne lève jamais."""
    maintenant = maintenant or datetime.now(timezone.utc)
    rapport: Dict[str, Any] = {"le": maintenant.isoformat(), "simule": simuler, "actif": False, "mode": "avis", "clients": 0,
                               "elements": 0, "messages": 0, "envoyes": 0, "echecs": 0, "sans_decisionnaire": 0, "recap": None, "details": []}
    try:
        s = await db.settings.find_one({"_id": "global"}) or {}
        regl = reglages(s)
        rapport["actif"], rapport["mode"] = regl["actif"], regl["mode"]
        if not regl["actif"] and not simuler:
            return rapport
        elements = await collecter(db, maintenant.date())
        rapport["elements"] = len(elements)
        rapport["clients"] = len({e["client_id"] for e in elements})
        rapport["sans_decisionnaire"] = len({e["client_id"] for e in elements if not e["contacts"]})
        if simuler or regl["mode"] == "avis":
            # Aperçu (simulation) ou récapitulatif pour avis : aucun message n'est envoyé aux clients
            par_client: Dict[str, Dict[str, Any]] = {}
            for e in elements:
                d = par_client.setdefault(e["client_id"], {"client": e["client"], "produits": [], "destinataires": []})
                d["produits"].append(e["texte"])
                if not e["contacts"]:
                    d["alerte"] = "Aucun décisionnaire avec un numéro WhatsApp : personne n'a été prévenu."
                for c in e["contacts"]:
                    if not any(x["telephone"] == f"+{c['tel']}" for x in d["destinataires"]):
                        d["destinataires"].append({"nom": c["nom"], "telephone": f"+{c['tel']}", "ok": None})
            rapport["details"] = list(par_client.values())[:MAX_DETAILS]
            rapport["messages"] = sum(len(d["destinataires"]) for d in rapport["details"])
            if not simuler:
                rapport["recap"] = await envoyer_recap(db, s, elements, maintenant, forcer=forcer)
        else:
            details = await envoyer_selection(db, elements, regl, envoyer)
            rapport["details"] = details[:MAX_DETAILS]
            for d in details:
                for x in d["destinataires"]:
                    rapport["messages"] += 1
                    rapport["envoyes" if x["ok"] else "echecs"] += 1
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
    mode: str = Field(default="avis", pattern="^(avis|auto)$")
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
            "offre_rappel_actif": bool(data.actif), "offre_rappel_mode": data.mode, "offre_rappel_modele": data.modele.strip(),
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
        return await rappeler(db, simuler=data.simuler, forcer=True)
