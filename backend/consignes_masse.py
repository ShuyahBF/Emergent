"""consignes_masse.py — ENVOIS EN MASSE demandés par une consigne à Liluvine (lot 456).

Règle du propriétaire : un message à tout un groupe (ex. « décalage d'1 h pour tous les RDV de demain ») est TOUJOURS confirmé avant l'envoi :
  1) APERÇU  : SAWALI choisit les destinataires (rendez-vous du jour ou de la période) et MONTRE qui, combien, quel texte ; rien ne part.
  2) CONFIRMATION : la personne confirme l'aperçu (valable 15 minutes, lié à CET aperçu : liste et texte ne peuvent plus changer).
  3) ENVOI en arrière-plan (règle 7), message après message ; le résultat se consulte (envoyés / hors fenêtre / bloqués / échecs).
Sécurité : les contacts de la liste noire WhatsApp sont exclus ; un numéro n'est contacté qu'une fois ; WhatsApp n'accepte le texte libre que dans la
fenêtre de 24 h : les autres contacts sont LISTÉS « non envoyé » (jamais un envoi forcé ni un modèle choisi à notre place). 200 destinataires au plus.
Stockage : une seule fiche de `settings` (`liluvine_masse`), aucune nouvelle collection (cluster plein).
"""
from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

MAX_DESTINATAIRES = 200
VALIDITE_APERCU_MIN = 15
MAX_LOTS_GARDES = 20
MAX_TEXTE = 1000
ID_FICHE = "liluvine_masse"
STATUTS_EXCLUS = ("cancelled", "canceled", "annule", "annulé", "refused", "refuse", "refusé")


def _chiffres(v: Any) -> str:
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def _jour(v: Any) -> str:
    """« 2026-11-25T09:30:00+00:00 » → « 2026-11-25 » ('' si illisible)."""
    s = str(v or "")[:10]
    return s if len(s) == 10 and s[4] == "-" and s[7] == "-" else ""


def choisir_destinataires(rdvs: List[Dict[str, Any]], du: str, au: str, bloques: frozenset = frozenset()) -> Dict[str, Any]:
    """Fonction PURE : parmi les rendez-vous, garde ceux de la période [du, au] (AAAA-MM-JJ), non annulés, avec un numéro valable, hors liste noire, un seul par numéro (8 derniers chiffres).
    Rend {destinataires: [{nom, telephone, quand}], exclus: {sans_numero, bloques, annules, doublons}}."""
    exclus = {"sans_numero": 0, "bloques": 0, "annules": 0, "doublons": 0}
    vus: set = set()
    sortie: List[Dict[str, str]] = []
    for r in sorted(rdvs, key=lambda x: str(x.get("scheduled_at") or "")):
        j = _jour(r.get("scheduled_at"))
        if not j or j < du or j > au:
            continue
        if str(r.get("status") or "").lower() in STATUTS_EXCLUS:
            exclus["annules"] += 1
            continue
        tel = _chiffres(r.get("whatsapp") or r.get("phone"))
        if len(tel) < 8:
            exclus["sans_numero"] += 1
            continue
        cle = tel[-8:]
        if cle in bloques:
            exclus["bloques"] += 1
            continue
        if cle in vus:
            exclus["doublons"] += 1
            continue
        vus.add(cle)
        sortie.append({"nom": str(r.get("name") or "")[:80], "telephone": tel, "quand": str(r.get("scheduled_at") or "")[:16].replace("T", " ")})
    return {"destinataires": sortie, "exclus": exclus}


def empreinte(message: str, destinataires: List[Dict[str, str]]) -> str:
    """Empreinte du message ET de la liste : la confirmation n'est valable que pour CET aperçu exact."""
    base = message + "|" + ",".join(d["telephone"] for d in destinataires)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]


def valider_periode(du: Any, au: Any) -> tuple:
    """Dates AAAA-MM-JJ cohérentes (au ≥ du, 31 jours au plus) ou ValueError."""
    d, a = _jour(du), _jour(au or du)
    if not d or not a:
        raise ValueError("Précisez la période des rendez-vous (de AAAA-MM-JJ à AAAA-MM-JJ)")
    if a < d:
        raise ValueError("La fin de la période est avant son début")
    if (datetime.fromisoformat(a) - datetime.fromisoformat(d)).days > 31:
        raise ValueError("La période est limitée à 31 jours")
    return d, a


async def _fiche(db) -> Dict[str, Any]:
    f = await db["settings"].find_one({"_id": ID_FICHE}) or {}
    f.setdefault("apercus", [])
    f.setdefault("lots", [])
    f.setdefault("modele", {"nom": "", "langue": "fr"})
    f.setdefault("soumission", {})            # lot 460 : dernière soumission du modèle à Meta (nom, statut, raison, dates)
    return f


async def _ecrire(db, fiche: Dict[str, Any]) -> None:
    fiche["apercus"] = fiche["apercus"][-10:]
    fiche["lots"] = fiche["lots"][-MAX_LOTS_GARDES:]
    await db["settings"].update_one({"_id": ID_FICHE}, {"$set": {"apercus": fiche["apercus"], "lots": fiche["lots"], "modele": fiche["modele"], "soumission": fiche.get("soumission") or {}}}, upsert=True)


async def apercu(db, message: str, du: Any, au: Any, par: str, instant: Optional[datetime] = None) -> Dict[str, Any]:
    """ÉTAPE 1 : choisit les destinataires et MONTRE ; rien ne part. Garde l'aperçu (15 min) pour la confirmation."""
    message = " ".join(str(message or "").split())[:MAX_TEXTE]
    if len(message) < 5:
        raise ValueError("Écrivez le message à envoyer")
    d, a = valider_periode(du, au)
    from liste_noire_wa import cles_bloquees
    rdvs = await db.appointments.find({"scheduled_at": {"$gte": d, "$lte": a + "T99"}}, {"_id": 0}).to_list(5000)
    choix = choisir_destinataires(rdvs, d, a, await cles_bloquees(db))
    dest = choix["destinataires"]
    if not dest:
        raise ValueError("Aucun destinataire : aucun rendez-vous avec un numéro valable sur cette période")
    if len(dest) > MAX_DESTINATAIRES:
        raise ValueError(f"{len(dest)} destinataires : au plus {MAX_DESTINATAIRES} par envoi (réduisez la période)")
    instant = instant or datetime.now(timezone.utc)
    ap = {"id": uuid.uuid4().hex[:12], "message": message, "du": d, "au": a, "destinataires": dest, "exclus": choix["exclus"], "empreinte": empreinte(message, dest),
          "par": par, "cree_le": instant.isoformat(), "expire_le": (instant + timedelta(minutes=VALIDITE_APERCU_MIN)).isoformat(), "utilise": False}
    f = await _fiche(db)
    f["apercus"].append(ap)
    await _ecrire(db, f)
    return ap


def masquer(tel: str) -> str:
    """Numéro partiellement masqué pour l'affichage de l'aperçu."""
    return tel[:3] + "*" * max(0, len(tel) - 5) + tel[-2:] if len(tel) > 5 else tel


async def confirmer(db, identifiant: str, empreinte_vue: str, par: str, envoyeur, fenetre, instant: Optional[datetime] = None, modeleur=None) -> Dict[str, Any]:
    """ÉTAPE 2 : la personne a vu l'aperçu et confirme. Vérifie (aperçu connu, non expiré, non déjà utilisé, empreinte identique), crée le lot puis lance l'envoi EN ARRIÈRE-PLAN.
    `envoyeur(tel, texte) -> dict{ok,error}` et `fenetre(tel) -> bool` sont injectés (tests sans réseau)."""
    instant = instant or datetime.now(timezone.utc)
    f = await _fiche(db)
    ap = next((x for x in f["apercus"] if x.get("id") == identifiant), None)
    if not ap:
        raise ValueError("Aperçu introuvable : refaites l'aperçu avant d'envoyer")
    if ap.get("utilise"):
        raise ValueError("Cet aperçu a déjà été envoyé")
    if datetime.fromisoformat(ap["expire_le"]) < instant:
        raise ValueError("L'aperçu a expiré (15 minutes) : refaites l'aperçu")
    if ap["empreinte"] != empreinte_vue:
        raise ValueError("L'aperçu a changé : relisez-le avant de confirmer")
    ap["utilise"] = True
    lot = {"id": ap["id"], "message": ap["message"], "du": ap["du"], "au": ap["au"], "par": par, "confirme_le": instant.isoformat(), "total": len(ap["destinataires"]),
           "envoyes": 0, "par_modele": 0, "hors_fenetre": 0, "echecs": 0, "termine": False, "details": []}
    f["lots"].append(lot)
    await _ecrire(db, f)
    modele = f.get("modele") or {}
    asyncio.get_event_loop().create_task(_envoyer_tout(db, ap, envoyeur, fenetre, modeleur if modele.get("nom") else None, modele))      # règle 7 : jamais dans la requête
    return {k: v for k, v in lot.items() if k != "details"}


async def _envoyer_tout(db, ap: Dict[str, Any], envoyeur, fenetre, modeleur=None, modele: Optional[Dict[str, str]] = None) -> None:
    """Envoi message après message ; une panne sur un numéro n'arrête pas les autres. Résultat gardé dans le lot."""
    compte = {"envoyes": 0, "par_modele": 0, "hors_fenetre": 0, "echecs": 0}
    details: List[Dict[str, str]] = []
    for d in ap["destinataires"]:
        try:
            if not await fenetre(d["telephone"]):
                if modeleur is None:                                  # pas de modèle réglé : jamais d'envoi forcé
                    compte["hors_fenetre"] += 1
                    details.append({"tel": masquer(d["telephone"]), "etat": "non envoyé : hors fenêtre de 24 h (aucun modèle Meta réglé)"})
                    continue
                r = await modeleur(d["telephone"], modele["nom"], modele.get("langue") or "fr", variables_modele(d["nom"], ap["message"]))
                if r.get("ok"):
                    compte["par_modele"] += 1
                else:
                    compte["echecs"] += 1
                    details.append({"tel": masquer(d["telephone"]), "etat": "modèle : " + str(r.get("error") or "échec")[:110]})
                continue
            r = await envoyeur(d["telephone"], ap["message"])
            if r.get("ok"):
                compte["envoyes"] += 1
            else:
                compte["echecs"] += 1
                details.append({"tel": masquer(d["telephone"]), "etat": str(r.get("error") or "échec")[:120]})
        except Exception as exc:  # noqa: BLE001
            compte["echecs"] += 1
            details.append({"tel": masquer(d["telephone"]), "etat": str(exc)[:120]})
        await asyncio.sleep(0.3)             # cadence douce : jamais de rafale
    f = await _fiche(db)
    for lot in f["lots"]:
        if lot["id"] == ap["id"]:
            lot.update(compte)
            lot["details"] = details[:50]
            lot["termine"] = True
    await _ecrire(db, f)


# ---------------------------------------------------------------- modèle Meta pour les envois HORS fenêtre de 24 h
MODELE_NOM = "information_rdv"
MODELE_CORPS = "Bonjour {{1}}, une information concernant votre rendez-vous : {{2}} Merci de confirmer la bonne réception en appuyant sur le bouton ci-dessous."
MODELE_BOUTON = "Bien reçu"


def variables_modele(nom: str, message: str) -> List[str]:
    """Valeurs {{1}} (nom) et {{2}} (message) du modèle : Meta refuse les retours à la ligne et les espaces répétés dans une variable."""
    n = " ".join(str(nom or "").split())[:60] or "cher client"
    m = " ".join(str(message or "").split())[:900]
    return [n, m]


async def lire_modele(db) -> Dict[str, str]:
    return dict((await _fiche(db))["modele"])


async def regler_modele(db, nom: Any, langue: Any) -> Dict[str, str]:
    """Nom du modèle approuvé par Meta (minuscules, chiffres, _) et sa langue ; vide = pas de modèle (les contacts hors fenêtre restent « non envoyé »)."""
    import re
    n = str(nom or "").strip().lower()
    l = str(langue or "fr").strip() or "fr"
    if n and not re.fullmatch(r"[a-z0-9_]{1,512}", n):
        raise ValueError("Nom du modèle : lettres minuscules, chiffres et _ seulement")
    if not re.fullmatch(r"[a-z]{2}(_[A-Za-z]{2})?", l):
        raise ValueError("Langue du modèle : « fr » par exemple")
    f = await _fiche(db)
    f["modele"] = {"nom": n, "langue": l}
    await _ecrire(db, f)
    return f["modele"]


# ---------------------------------------------------------------- lot 460 : SOUMISSION du modèle à Meta depuis SAWALI et SUIVI de son statut
# Le propriétaire ne passe plus par le Gestionnaire WhatsApp : un bouton envoie le modèle (corps, exemples, bouton « Bien reçu ») à Meta, un autre relit son statut.
# Aucun appel à Meta à l'ouverture de l'écran (règle 7) : le dernier statut connu est lu dans la fiche ; seuls les boutons interrogent Meta. Administrateur seul.
WA_GRAPH_VERSION = "v21.0"
MODELE_EXEMPLES = ["Awa", "Votre rendez-vous de demain est décalé d'une heure."]
LIBELLES_STATUT = {
    "ABSENT": "Non soumis à Meta", "PENDING": "En attente d'examen par Meta", "IN_APPEAL": "En appel chez Meta", "APPROVED": "Approuvé par Meta",
    "REJECTED": "Refusé par Meta", "PAUSED": "Mis en pause par Meta", "DISABLED": "Désactivé par Meta", "PENDING_DELETION": "Suppression en cours",
}


def contenu_modele_meta(nom: str = MODELE_NOM, langue: str = "fr") -> Dict[str, Any]:
    """Fonction PURE : le JSON exact à envoyer à Meta (POST /{WABA}/message_templates) : catégorie UTILITY, corps avec exemples {{1}} / {{2}}, bouton de réponse rapide."""
    return {"name": nom, "language": langue, "category": "UTILITY", "components": [
        {"type": "BODY", "text": MODELE_CORPS, "example": {"body_text": [list(MODELE_EXEMPLES)]}},
        {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": MODELE_BOUTON}]},
    ]}


async def _appel_meta(methode: str, url: str, jeton: str, json: Any = None, params: Any = None) -> tuple:
    """Appel réel à l'API Graph de Meta (injecté par les tests) : rend (code HTTP, corps JSON)."""
    import httpx
    async with httpx.AsyncClient(timeout=20) as http:
        r = await http.request(methode, url, headers={"Authorization": f"Bearer {jeton}"}, json=json, params=params)
    try:
        corps = r.json()
    except Exception:  # noqa: BLE001
        corps = {}
    return r.status_code, corps if isinstance(corps, dict) else {}


async def _acces_meta(db) -> tuple:
    """(jeton, identifiant du compte WhatsApp Business) lus dans les réglages WhatsApp de SAWALI ; ValueError si l'un manque. Jamais affichés ni journalisés."""
    g = await db["settings"].find_one({"_id": "global"}) or {}
    jeton, waba = str(g.get("wa_access_token") or "").strip(), str(g.get("wa_business_account_id") or "").strip()
    if not jeton or not waba:
        raise ValueError("WhatsApp n'est pas configuré : renseignez l'identifiant du compte WhatsApp Business et le jeton d'accès dans les Paramètres.")
    return jeton, waba


def _erreur_meta(code: int, corps: Dict[str, Any]) -> str:
    """Message d'erreur de Meta, lisible (jamais renvoyé en 401 / 403 : l'écran déconnecterait l'administrateur)."""
    e = corps.get("error") or {}
    return f"Meta a répondu {code} : " + str(e.get("error_user_msg") or e.get("message") or "échec sans détail")[:300]


def vue_soumission(sou: Dict[str, Any], modele: Dict[str, str]) -> Dict[str, Any]:
    """Ce que l'écran affiche : statut en clair, catégorie, raison d'un refus, alerte si Meta a changé la catégorie, et si le modèle est déjà ACTIVÉ pour les envois."""
    statut = str(sou.get("statut") or "ABSENT")
    cat = str(sou.get("categorie") or "")
    alerte = ("Meta a classé ce modèle « " + cat + " » au lieu de UTILITY : l'envoi est facturé autrement. Vérifiez le texte dans le Gestionnaire WhatsApp.") if cat and cat != "UTILITY" else ""
    return {"nom": sou.get("nom") or MODELE_NOM, "langue": sou.get("langue") or "fr", "statut": statut, "libelle": LIBELLES_STATUT.get(statut, statut), "categorie": cat,
            "raison": sou.get("raison") or "", "id": sou.get("id") or "", "envoye_le": sou.get("envoye_le") or "", "verifie_le": sou.get("verifie_le") or "", "alerte": alerte,
            "active": bool(modele.get("nom")) and modele.get("nom") == (sou.get("nom") or MODELE_NOM)}


async def lire_soumission(db) -> Dict[str, Any]:
    """Dernier statut CONNU (lu dans la fiche, aucun appel à Meta)."""
    f = await _fiche(db)
    return vue_soumission(f["soumission"], f["modele"])


async def statut_modele(db, nom: Optional[str] = None, appeler=None, instant: Optional[datetime] = None) -> Dict[str, Any]:
    """Interroge Meta (GET /{WABA}/message_templates?name=…) et garde le statut : ABSENT (jamais soumis), PENDING, APPROVED, REJECTED (avec la raison)…"""
    appeler = appeler or _appel_meta
    f = await _fiche(db)
    n = _nom_valide(nom or f["soumission"].get("nom") or MODELE_NOM)
    langue = f["soumission"].get("langue") or "fr"
    jeton, waba = await _acces_meta(db)
    code, corps = await appeler("GET", f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{waba}/message_templates", jeton,
                                params={"name": n, "fields": "id,name,status,category,language,rejected_reason", "limit": 25})
    if code >= 300:
        raise ValueError(_erreur_meta(code, corps))
    trouve = next((t for t in (corps.get("data") or []) if t.get("name") == n and str(t.get("language") or "")[:2] == langue[:2]), None)
    maintenant = (instant or datetime.now(timezone.utc)).isoformat()
    ancien = f["soumission"] if f["soumission"].get("nom") == n else {}
    if not trouve:
        f["soumission"] = {"nom": n, "langue": langue, "statut": "ABSENT", "categorie": "", "raison": "", "id": "", "envoye_le": "", "verifie_le": maintenant}
    else:
        raison = str(trouve.get("rejected_reason") or "")
        f["soumission"] = {"nom": n, "langue": langue, "statut": str(trouve.get("status") or "PENDING").upper(), "categorie": str(trouve.get("category") or "").upper(),
                           "raison": "" if raison.upper() == "NONE" else raison, "id": str(trouve.get("id") or ""), "envoye_le": ancien.get("envoye_le", ""), "verifie_le": maintenant}
    await _ecrire(db, f)
    return vue_soumission(f["soumission"], f["modele"])


def _nom_valide(nom: Any) -> str:
    """Nom d'un modèle Meta : minuscules, chiffres et _ (512 au plus)."""
    import re
    n = str(nom or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{1,512}", n):
        raise ValueError("Nom du modèle : lettres minuscules, chiffres et _ seulement")
    return n


async def soumettre_modele(db, nom: Optional[str] = None, appeler=None, instant: Optional[datetime] = None) -> Dict[str, Any]:
    """Envoie le modèle à Meta pour approbation. Si un modèle de ce nom existe déjà chez Meta, on NE le renvoie PAS : on relit son statut (rien n'est écrasé ni doublé)."""
    appeler = appeler or _appel_meta
    n = _nom_valide(nom or MODELE_NOM)
    deja = await statut_modele(db, n, appeler, instant)
    if deja["statut"] != "ABSENT":
        return {**deja, "deja": True}
    jeton, waba = await _acces_meta(db)
    contenu = contenu_modele_meta(n, "fr")
    code, corps = await appeler("POST", f"https://graph.facebook.com/{WA_GRAPH_VERSION}/{waba}/message_templates", jeton, json=contenu)
    if code >= 300:
        raise ValueError(_erreur_meta(code, corps))
    f = await _fiche(db)
    maintenant = (instant or datetime.now(timezone.utc)).isoformat()
    f["soumission"] = {"nom": n, "langue": "fr", "statut": str(corps.get("status") or "PENDING").upper(), "categorie": str(corps.get("category") or "UTILITY").upper(),
                       "raison": "", "id": str(corps.get("id") or ""), "envoye_le": maintenant, "verifie_le": maintenant}
    await _ecrire(db, f)
    return {**vue_soumission(f["soumission"], f["modele"]), "deja": False}


def envoyeurs_serveur():
    """Les 3 fonctions réelles d'envoi (texte libre, test de fenêtre de 24 h, modèle Meta) : utilisées par l'écran ET par les consignes données par WhatsApp."""
    async def envoyeur(tel: str, texte: str) -> dict:
        import server as srv
        return await srv._wa_send_text(f"+{tel}", texte)

    async def fenetre(tel: str) -> bool:
        from routes.offre_client_rappels import fenetre_ouverte      # même règle de la fenêtre de 24 h que les rappels
        return await fenetre_ouverte(tel)

    async def modeleur(tel: str, nom: str, langue: str, valeurs: list) -> dict:
        import server as srv
        comp = [{"type": "body", "parameters": [{"type": "text", "text": v} for v in valeurs]}]
        return await srv._wa_send_template(f"+{tel}", nom, langue, comp)

    return envoyeur, fenetre, modeleur


async def lots(db) -> List[Dict[str, Any]]:
    """Derniers envois (le plus récent d'abord)."""
    return list(reversed((await _fiche(db))["lots"]))
