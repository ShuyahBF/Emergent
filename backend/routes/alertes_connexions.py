"""Lot 109 — Alerte WhatsApp à chaque CONNEXION sur une plateforme (adLyn, bfmobility, sTer, beAuthentik, ZandGo…).

Demande du propriétaire (11/10/2026) : « N'étant pas toujours connecté, je souhaiterais une automation WA pour chaque
connexion adLyn, bfmobility, sTer, beAuthentik et ZandGo avec la plateforme, la date/heure, l'adresse IP,
l'utilisateur/numéro de téléphone (si le client est connecté) et un bouton "Visiter le site" avec l'adresse du site
concerné. »

Pour un développeur WinDev — le principe :
  1. Chaque plateforme SIGNALE à SAWALI, en arrière-plan, chaque connexion d'un compte (type « connexion ») et chaque
     nouvelle visite d'un visiteur non connecté (type « visite », au plus une par visiteur et par demi-heure) :
       POST /api/webhook/plateforme-connexion   (signé : X-Emetteur, X-Timestamp, X-Signature = HMAC-SHA256(clé,
       "<horodatage>.<corps brut>"), la clé d'émetteur de la Transmission universelle)
       {"type": "connexion" | "visite", "le": ISO, "ip": "…", "utilisateur": "Awa O." | null,
        "telephone": "22670…" | null, "role": "client" | "admin" | …, "url_site": "https://zandgo.shop",
        "page": "/produits/12", "agent": "<navigateur>"}
  2. SAWALI garde la trace (db.alertes_connexions, 90 jours) et, si les réglages le permettent, envoie au propriétaire
     (numéros de la rubrique « Liluvine appelle le propriétaire ») un WhatsApp :
       🔔 Connexion sur ZandGo — 11/10/2026 01:35 — IP 154.66.x.x — Awa (+226 70…) + bouton « Visiter le site ».
     - fenêtre de 24 h ouverte (le propriétaire a écrit au numéro SAWALI depuis moins de 24 h) : message interactif
       gratuit avec un vrai bouton lien (cta_url) vers l'adresse du site ;
     - sinon : modèle Meta « sawali_connexion_plateforme » (à créer une fois depuis la rubrique), dont le bouton ouvre
       https://api.sawalismartsystems.com/api/visiter/<code> → redirection vers le site de la plateforme.
  3. Garde-fous (réglables) : robots ignorés, une seule alerte par personne / visiteur / IP et par plateforme pendant
     N minutes (30 par défaut), plafond d'alertes par plateforme et par jour (100), IP exclues (les vôtres),
     plateformes désactivées, visites anonymes activables séparément.
Aucun secret n'est stocké ni affiché ici.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

import routes.appel_proprietaire as ap
from routes.contrats_plateformes import signature_valide

logger = logging.getLogger(__name__)

COLLECTION = "alertes_connexions"
MODELE = "sawali_connexion_plateforme"          # nom du modèle Meta (hors fenêtre de 24 h)
LANGUE = "fr"
DUREE_CONSERVATION_J = 90                        # index TTL du journal
TYPES = {"connexion": "Connexion", "visite": "Visite"}
# Adresse publique de SAWALI (bouton du modèle → /api/visiter/<code>)
API_PUBLIQUE = (os.environ.get("SAWALI_API_PUBLIQUE") or "https://api.sawalismartsystems.com").rstrip("/")
# Navigateurs automatiques (moteurs de recherche, aperçus de liens, sondes) : jamais d'alerte
ROBOTS = re.compile(r"bot|crawl|spider|slurp|preview|facebookexternalhit|whatsapp|curl|wget|python|httpx|"
                    r"headless|lighthouse|uptime|monitor|render", re.I)


# ---------------------------------------------------------------------------
# Réglages (db.settings {_id: "global"}, clés alerte_cnx_*)
# ---------------------------------------------------------------------------

def _entier(v: Any, defaut: int, mini: int, maxi: int) -> int:
    try:
        return max(mini, min(maxi, int(v)))
    except (TypeError, ValueError):
        return defaut


def _liste(v: Any) -> List[str]:
    """Texte « a, b ; c » ou liste → liste nettoyée."""
    if isinstance(v, list):
        v = ",".join(str(x) for x in v)
    return [x.strip() for x in re.split(r"[,;\n]+", str(v or "")) if x.strip()]


def reglages(s: Dict[str, Any]) -> Dict[str, Any]:
    """Réglages de l'alerte, complétés par les valeurs par défaut."""
    s = s or {}
    return {
        "actif": s.get("alerte_cnx_actif") is not False,              # activée par défaut
        "connexions": s.get("alerte_cnx_connexions") is not False,     # connexions de comptes : oui
        "visites": s.get("alerte_cnx_visites") is not False,           # visites anonymes : oui
        "delai_min": _entier(s.get("alerte_cnx_delai_min"), 30, 1, 24 * 60),
        "plafond_jour": _entier(s.get("alerte_cnx_plafond_jour"), 100, 1, 5000),
        "ip_exclues": _liste(s.get("alerte_cnx_ip_exclues")),
        "plateformes_exclues": [x.lower() for x in _liste(s.get("alerte_cnx_plateformes_exclues"))],
    }


CHAMPS_REGLAGES = {"alerte_cnx_actif": bool, "alerte_cnx_connexions": bool, "alerte_cnx_visites": bool,
                   "alerte_cnx_delai_min": int, "alerte_cnx_plafond_jour": int,
                   "alerte_cnx_ip_exclues": str, "alerte_cnx_plateformes_exclues": str}


# ---------------------------------------------------------------------------
# Fonctions pures (testées)
# ---------------------------------------------------------------------------

def chiffres(v: Any) -> str:
    return "".join(c for c in str(v or "") if c.isdigit())


def est_robot(agent: Any) -> bool:
    """Vrai pour un navigateur automatique (aucune alerte)."""
    return bool(ROBOTS.search(str(agent or "")))


def url_valide(url: Any) -> Optional[str]:
    """Adresse http(s) d'un site, sinon None (aucune autre forme n'est suivie ni redirigée)."""
    u = str(url or "").strip()
    return u.rstrip("/") if re.match(r"^https?://[^\s/$.?#][^\s]*$", u, re.I) and len(u) <= 300 else None


def telephone_lisible(tel: Any) -> str:
    """« 22670123456 » → « +226 70 12 34 56 » (autres formats : +chiffres)."""
    c = chiffres(tel)
    if len(c) == 11 and c.startswith("226"):
        return f"+226 {c[3:5]} {c[5:7]} {c[7:9]} {c[9:11]}"
    return f"+{c}" if c else ""


def qui(evt: Dict[str, Any]) -> str:
    """Utilisateur affiché : « Nom (+226 …) », le numéro seul, ou « Visiteur non connecté »."""
    nom = str(evt.get("utilisateur") or "").strip()[:60]
    tel = telephone_lisible(evt.get("telephone"))
    role = str(evt.get("role") or "").strip()[:20]
    if nom and tel:
        base = f"{nom} ({tel})"
    else:
        base = nom or tel
    if not base:
        return "Visiteur non connecté"
    return f"{base} — {role}" if role and role not in ("client",) else base


def cle_personne(evt: Dict[str, Any]) -> str:
    """Clé anti-répétition : téléphone, sinon nom, sinon identifiant de visiteur, sinon IP."""
    return (chiffres(evt.get("telephone")) or str(evt.get("utilisateur") or "").strip().lower()
            or str(evt.get("visiteur") or "").strip() or str(evt.get("ip") or "").strip() or "?")[:80]


def texte_alerte(nom_plateforme: str, evt: Dict[str, Any], quand: datetime) -> str:
    """Texte du message (message libre et aperçu dans le Centre de messagerie)."""
    titre = "🔐 Connexion" if evt.get("type") == "connexion" else "👀 Visite"
    lignes = [f"{titre} sur *{nom_plateforme}*",
              f"📅 {ap.formater_date(quand)}",
              f"🌐 IP : {evt.get('ip') or 'inconnue'}",
              f"👤 {qui(evt)}"]
    if evt.get("page"):
        lignes.append(f"📄 Page : {str(evt['page'])[:120]}")
    return "\n".join(lignes)


def variables_modele(nom_plateforme: str, evt: Dict[str, Any], quand: datetime) -> List[str]:
    """{{1}} plateforme, {{2}} date, {{3}} IP, {{4}} utilisateur (une ligne chacune, jamais vide)."""
    genre = "connexion" if evt.get("type") == "connexion" else "visite"
    return [f"{nom_plateforme} ({genre})", ap.formater_date(quand), str(evt.get("ip") or "inconnue")[:60], qui(evt)]


def definition_modele() -> Dict[str, Any]:
    """Corps envoyé à Meta pour créer le modèle (catégorie Utilitaire, bouton lien à suffixe variable)."""
    return {"name": MODELE, "language": LANGUE, "category": "UTILITY", "components": [
        {"type": "BODY",
         "text": ("Nouvelle activité sur la plateforme {{1}} le {{2}}.\nAdresse IP : {{3}}\nUtilisateur : {{4}}"),
         "example": {"body_text": [["ZandGo (connexion)", "11/10/2026 01:35", "154.66.162.235",
                                    "Awa Ouédraogo (+226 70 12 34 56)"]]}},
        {"type": "FOOTER", "text": "SAWALI Smart Systems"},
        {"type": "BUTTONS", "buttons": [{"type": "URL", "text": "Visiter le site",
                                         "url": f"{API_PUBLIQUE}/api/visiter/{{{{1}}}}",
                                         "example": [f"{API_PUBLIQUE}/api/visiter/zandgo"]}]},
    ]}


def corps_interactif(proprio: str, texte: str, url_site: str) -> Dict[str, Any]:
    """Message interactif avec bouton lien (fenêtre de 24 h ouverte : gratuit, adresse directe du site)."""
    return {"messaging_product": "whatsapp", "to": proprio, "type": "interactive",
            "interactive": {"type": "cta_url", "body": {"text": texte[:1024]},
                            "footer": {"text": "SAWALI Smart Systems"},
                            "action": {"name": "cta_url",
                                       "parameters": {"display_text": "Visiter le site", "url": url_site}}}}


def corps_modele(proprio: str, variables: List[str], code: str) -> Dict[str, Any]:
    """Modèle Meta (hors fenêtre de 24 h) : 4 variables + suffixe du bouton (code de la plateforme)."""
    return {"messaging_product": "whatsapp", "to": proprio, "type": "template",
            "template": {"name": MODELE, "language": {"code": LANGUE}, "components": [
                {"type": "body", "parameters": [{"type": "text", "text": re.sub(r"\s+", " ", v).strip()[:300] or "-"}
                                                for v in variables]},
                {"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": code}]}]}}


def decision(cfg: Dict[str, Any], code: str, evt: Dict[str, Any]) -> Optional[str]:
    """Raison de NE PAS alerter (None = alerter), avant les contrôles en base (répétition, plafond)."""
    if not cfg["actif"]:
        return "alerte désactivée"
    if code in cfg["plateformes_exclues"]:
        return "plateforme désactivée"
    if evt.get("type") == "connexion" and not cfg["connexions"]:
        return "alertes de connexion désactivées"
    if evt.get("type") == "visite" and not cfg["visites"]:
        return "alertes de visite désactivées"
    if est_robot(evt.get("agent")):
        return "robot"
    if evt.get("ip") and evt["ip"] in cfg["ip_exclues"]:
        return "IP exclue"
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def setup_alertes_connexions_routes(*, api, db, get_current_user):

    async def _admin(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        return user

    async def _emetteur_signe(request: Request) -> tuple:
        """Vérifie la signature de la plateforme ; renvoie (émetteur, corps JSON)."""
        code = (request.headers.get("X-Emetteur") or "").strip().lower()
        emetteur = await db.liluvine_emetteurs.find_one({"code": code}, {"_id": 0}) if code else None
        if not emetteur or not emetteur.get("actif", True):
            raise HTTPException(status_code=401, detail="Émetteur inconnu ou désactivé")
        brut = await request.body()
        if not signature_valide(emetteur.get("secret") or "", request.headers.get("X-Timestamp") or "", brut,
                                request.headers.get("X-Signature") or "", datetime.now(timezone.utc)):
            raise HTTPException(status_code=401, detail="Signature refusée")
        try:
            corps = json.loads(brut.decode("utf-8") or "{}")
        except ValueError:
            raise HTTPException(status_code=400, detail="Corps JSON illisible")
        if not isinstance(corps, dict):
            raise HTTPException(status_code=400, detail="Corps JSON attendu")
        return emetteur, corps

    async def _index() -> None:
        """Index TTL du journal (90 jours) et index de recherche — sans effet s'ils existent déjà."""
        try:
            await db[COLLECTION].create_index("le_date", expireAfterSeconds=DUREE_CONSERVATION_J * 86400)
            await db[COLLECTION].create_index([("code", 1), ("cle", 1), ("le", -1)])
        except Exception:  # noqa: BLE001
            pass

    async def envoyer(s: Dict[str, Any], code: str, nom: str, evt: Dict[str, Any], url_site: Optional[str],
                      quand: datetime) -> List[Dict[str, Any]]:
        """Envoie l'alerte à chaque numéro du propriétaire ; renvoie le détail par numéro (mode, ok, erreur)."""
        cfgp = ap.reglages(s)
        numero_id, _ = ap.ligne_appelante(s, cfgp)
        if not numero_id:
            return [{"telephone": None, "ok": False, "erreur": "aucun numéro WhatsApp SAWALI configuré"}]
        if not cfgp["numeros"]:
            return [{"telephone": None, "ok": False,
                     "erreur": "aucun numéro du propriétaire (rubrique « Liluvine appelle le propriétaire »)"}]
        texte = texte_alerte(nom, evt, quand)
        if url_site:
            texte_libre = texte
        else:
            texte_libre = texte + "\n(adresse du site inconnue)"
        resultats = []
        for proprio in cfgp["numeros"]:
            ouverte = await ap.fenetre_24h_ouverte(db, proprio, numero_id, quand)
            if ouverte and url_site:
                mode, corps = "interactif", corps_interactif(proprio, texte, url_site)
            elif ouverte:
                mode, corps = "texte", {"messaging_product": "whatsapp", "to": proprio, "type": "text",
                                        "text": {"body": texte_libre[:4000], "preview_url": False}}
            else:
                mode, corps = "modele", corps_modele(proprio, variables_modele(nom, evt, quand), code)
            res = await ap._graph_post(s, numero_id, "messages", corps)
            erreur = res.get("erreur")
            if not res["ok"] and mode == "modele":
                erreur = f"{erreur} — créez le modèle « {MODELE} » dans la rubrique (puis attendez son approbation)"
            mid = ((res.get("donnees") or {}).get("messages") or [{}])[0].get("id") if res["ok"] else None
            resultats.append({"telephone": proprio, "mode": mode, "ok": res["ok"], "erreur": erreur})
            # Trace dans la conversation du propriétaire (Centre de messagerie)
            try:
                await db.whatsapp_messages.insert_one({
                    "id": str(uuid.uuid4()), "direction": "outbound", "to": f"+{proprio}", "phone_digits": proprio,
                    "body": texte, "message_type": "template" if mode == "modele" else mode,
                    "template_name": MODELE if mode == "modele" else None, "ai_generated": True,
                    "alerte_connexion": True, "sender_label": "Liluvine — alerte connexion",
                    "wa_numero_id": numero_id, "wa_message_id": mid, "ok": res["ok"], "error": erreur,
                    "created_at": quand.isoformat(), "sent_at": quand.isoformat() if res["ok"] else None})
            except Exception:  # noqa: BLE001
                pass
        return resultats

    async def traiter(alerte_id: str, s: Dict[str, Any], code: str, nom: str, evt: Dict[str, Any],
                      url_site: Optional[str], quand: datetime) -> None:
        """Envoi en arrière-plan puis mise à jour du journal (jamais bloquant pour la plateforme)."""
        try:
            envois = await envoyer(s, code, nom, evt, url_site, quand)
            statut = "envoyee" if any(e["ok"] for e in envois) else "echec"
        except Exception as exc:  # noqa: BLE001
            logger.warning("[alertes_connexions] envoi impossible", exc_info=True)
            envois, statut = [{"ok": False, "erreur": str(exc)[:200]}], "echec"
        await db[COLLECTION].update_one({"id": alerte_id}, {"$set": {"statut": statut, "envois": envois}})

    # ---- Signal d'une plateforme ----
    @api.post("/webhook/plateforme-connexion", tags=["Plateformes — alertes de connexion"])
    async def signal_connexion(request: Request):
        """Une plateforme signale une connexion (compte) ou une visite (anonyme) ; SAWALI alerte le propriétaire."""
        emetteur, corps = await _emetteur_signe(request)
        code = emetteur["code"]
        nom = emetteur.get("nom") or code
        quand = datetime.now(timezone.utc)
        genre = str(corps.get("type") or "connexion").strip().lower()
        if genre not in TYPES:
            raise HTTPException(status_code=422, detail="type attendu : connexion ou visite")
        evt = {"type": genre, "ip": str(corps.get("ip") or "").strip()[:60] or None,
               "utilisateur": str(corps.get("utilisateur") or "").strip()[:80] or None,
               "telephone": chiffres(corps.get("telephone"))[:20] or None,
               "role": str(corps.get("role") or "").strip()[:30] or None,
               "visiteur": str(corps.get("visiteur") or "").strip()[:80] or None,
               "page": str(corps.get("page") or "").strip()[:200] or None,
               "agent": str(corps.get("agent") or "").strip()[:300] or None}
        url_site = url_valide(corps.get("url_site")) or url_valide(emetteur.get("url_site"))
        if url_site and url_site != emetteur.get("url_site"):
            await db.liluvine_emetteurs.update_one({"code": code}, {"$set": {"url_site": url_site}})
        await _index()

        s = await db.settings.find_one({"_id": "global"}) or {}
        cfg = reglages(s)
        cle = cle_personne(evt)
        raison = decision(cfg, code, evt)
        if raison is None:
            # Anti-répétition : une alerte par personne / visiteur / IP et par plateforme pendant N minutes
            depuis = (quand - timedelta(minutes=cfg["delai_min"])).isoformat()
            if await db[COLLECTION].find_one({"code": code, "cle": cle, "statut": {"$in": ["en_cours", "envoyee"]},
                                              "le": {"$gte": depuis}}, {"_id": 1}):
                raison = f"déjà signalé il y a moins de {cfg['delai_min']} min"
        if raison is None:
            minuit = quand.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            n = await db[COLLECTION].count_documents({"code": code, "statut": {"$in": ["en_cours", "envoyee"]},
                                                      "le": {"$gte": minuit}})
            if n >= cfg["plafond_jour"]:
                raison = f"plafond du jour atteint ({cfg['plafond_jour']})"

        alerte_id = str(uuid.uuid4())
        await db[COLLECTION].insert_one({
            "id": alerte_id, "code": code, "plateforme": nom, **evt, "cle": cle, "url_site": url_site,
            "le": quand.isoformat(), "le_date": quand, "statut": "ignoree" if raison else "en_cours",
            "raison": raison, "envois": []})
        if raison is None:
            asyncio.create_task(traiter(alerte_id, s, code, nom, evt, url_site, quand))
        return {"ok": True, "alerte": raison is None, "raison": raison}

    # ---- Bouton « Visiter le site » du modèle Meta : redirection vers le site de la plateforme ----
    @api.get("/visiter/{code}", tags=["Plateformes — alertes de connexion"], include_in_schema=False)
    async def visiter(code: str):
        emetteur = await db.liluvine_emetteurs.find_one({"code": code.strip().lower()[:40]}, {"_id": 0, "url_site": 1})
        url = url_valide((emetteur or {}).get("url_site"))
        if not url:
            raise HTTPException(status_code=404, detail="Site inconnu")
        return RedirectResponse(url, status_code=302)

    # ---- Rubrique des Paramètres ----
    @api.get("/admin/alertes-connexions", tags=["Plateformes — alertes de connexion"])
    async def lire(user: dict = Depends(_admin)):
        """Réglages, numéros destinataires, plateformes (adresse du site) et 50 dernières alertes."""
        s = await db.settings.find_one({"_id": "global"}) or {}
        cfgp = ap.reglages(s)
        plateformes = [{"code": e["code"], "nom": e.get("nom") or e["code"], "url_site": e.get("url_site"),
                        "actif": e.get("actif", True)}
                       async for e in db.liluvine_emetteurs.find({}, {"_id": 0, "code": 1, "nom": 1, "url_site": 1, "actif": 1})]
        dernieres = await db[COLLECTION].find({}, {"_id": 0, "le_date": 0, "agent": 0}).sort("le", -1).to_list(50)
        depuis = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        compteurs = {}
        async for a in db[COLLECTION].find({"le": {"$gte": depuis}}, {"_id": 0, "code": 1, "statut": 1}):
            c = compteurs.setdefault(a["code"], {"recues": 0, "envoyees": 0})
            c["recues"] += 1
            c["envoyees"] += 1 if a.get("statut") == "envoyee" else 0
        return {"reglages": reglages(s), "destinataires": [telephone_lisible(n) for n in cfgp["numeros"]],
                "modele": MODELE, "plateformes": plateformes, "compteurs_24h": compteurs, "dernieres": dernieres}

    @api.put("/admin/alertes-connexions/reglages", tags=["Plateformes — alertes de connexion"])
    async def enregistrer(corps: Dict[str, Any], user: dict = Depends(_admin)):
        maj = {}
        for k, typ in CHAMPS_REGLAGES.items():
            if k in corps:
                v = corps[k]
                maj[k] = bool(v) if typ is bool else (_entier(v, 0, 0, 5000) if typ is int else str(v or "")[:2000])
        if maj:
            await db.settings.update_one({"_id": "global"}, {"$set": maj}, upsert=True)
        s = await db.settings.find_one({"_id": "global"}) or {}
        return {"ok": True, "reglages": reglages(s)}

    async def _meta() -> tuple:
        g = await db.settings.find_one({"_id": "global"}) or {}
        jeton, waba = (g.get("wa_access_token") or "").strip(), (g.get("wa_business_account_id") or "").strip()
        if not jeton or not waba:
            raise HTTPException(status_code=400, detail="WhatsApp non configuré (WABA ID et Access Token dans les Paramètres)")
        return jeton, waba

    @api.get("/admin/alertes-connexions/modele", tags=["Plateformes — alertes de connexion"])
    async def etat_modele(user: dict = Depends(_admin)):
        """État du modèle chez Meta : ABSENT, PENDING (en revue), APPROVED, REJECTED…"""
        import httpx
        jeton, waba = await _meta()
        async with httpx.AsyncClient(timeout=15) as http:
            rep = await http.get(f"https://graph.facebook.com/{ap.GRAPH_VERSION}/{waba}/message_templates",
                                 params={"name": MODELE, "fields": "name,status,language,rejected_reason"},
                                 headers={"Authorization": f"Bearer {jeton}"})
        donnees = (rep.json() or {}).get("data") if rep.status_code < 300 else None
        trouve = next((m for m in donnees or [] if m.get("language") == LANGUE), None)
        return {"nom": MODELE, "etat": (trouve or {}).get("status") or ("ABSENT" if donnees is not None else "INCONNU"),
                "motif_refus": (trouve or {}).get("rejected_reason")}

    @api.post("/admin/alertes-connexions/modele", tags=["Plateformes — alertes de connexion"])
    async def creer_modele(user: dict = Depends(_admin)):
        """Soumet le modèle à Meta (approbation en général en quelques minutes). Déjà existant = sans effet."""
        import httpx
        jeton, waba = await _meta()
        async with httpx.AsyncClient(timeout=15) as http:
            rep = await http.post(f"https://graph.facebook.com/{ap.GRAPH_VERSION}/{waba}/message_templates",
                                  json=definition_modele(),
                                  headers={"Authorization": f"Bearer {jeton}", "Content-Type": "application/json"})
        try:
            brut = rep.json()
        except Exception:  # noqa: BLE001
            brut = {}
        if rep.status_code < 300:
            return {"ok": True, "etat": brut.get("status") or "PENDING"}
        msg = ((brut.get("error") or {}).get("error_user_msg") or (brut.get("error") or {}).get("message")
               or f"HTTP {rep.status_code}")
        if "already" in msg.lower() or "existe" in msg.lower():
            return {"ok": True, "etat": "EXISTANT"}
        raise HTTPException(status_code=400, detail=f"Meta : {msg}")

    @api.post("/admin/alertes-connexions/tester", tags=["Plateformes — alertes de connexion"])
    async def tester(corps: Dict[str, Any] = None, user: dict = Depends(_admin)):
        """Envoie une alerte d'essai (première plateforme, ou celle choisie) sans contrôle de répétition."""
        corps = corps or {}
        filtre = {"code": str(corps.get("code")).lower()} if corps.get("code") else {}
        emetteur = await db.liluvine_emetteurs.find_one(filtre, {"_id": 0}) or {"code": "test", "nom": "Plateforme d'essai"}
        s = await db.settings.find_one({"_id": "global"}) or {}
        quand = datetime.now(timezone.utc)
        evt = {"type": "connexion", "ip": "0.0.0.0 (essai)", "utilisateur": user.get("name") or "Essai",
               "telephone": None, "role": "essai", "page": "/"}
        envois = await envoyer(s, emetteur["code"], emetteur.get("nom") or emetteur["code"], evt,
                               url_valide(emetteur.get("url_site")) or "https://www.sawalismartsystems.com", quand)
        return {"ok": any(e["ok"] for e in envois), "envois": envois}
