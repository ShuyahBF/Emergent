"""commande_hfsql_wa.py — COMMANDE HFSQL DISTANTE VIA LILUVINE (lot 458, propriétaire 25/11/2026).

Le propriétaire écrit à Liluvine, sur WhatsApp :
    « hfsql docx=CMC UPDATE VenteClinique SET Mag='SUP' WHERE Référence='R-2026367681' »
SAWALI dépose la commande dans la file des « requêtes SQL distantes » (`routes/loois_sql_distant`) : UNE machine disponible du client la prend, l'exécute sur sa base HFSQL
et SAWALI répond sur WhatsApp : zone d'exécution, base concernée (et machine), rappel de la commande, puis le résultat tel que le moteur HFSQL le renvoie.

SÉCURITÉ (règle 21 : une commande SQL par WhatsApp touche des données réelles, y compris de l'argent) :
  - SEUL un numéro de la liste « Commande HFSQL distante via Liluvine » (administrateur seul, Paramètres), ACTIF, est écouté ; le mot « hfsql » est obligatoire ; tout autre message
    suit le traitement habituel de Liluvine ;
  - les contrôles « Prudent » sont les MÊMES que ceux de Loois (`loois_sql_distant.verifier`) : SELECT / INSERT / UPDATE / DELETE, une seule instruction, UPDATE et DELETE avec WHERE,
    aucune modification de structure, 4000 caractères au plus ;
  - SELECT : exécuté tout de suite. INSERT / UPDATE / DELETE : Liluvine REDIT la commande, la zone et attend « OUI » (5 minutes ; « NON » annule ; un « OUI » sans commande récente est ignoré) ;
  - une modification n'est déposée que si le client est EN LIGNE (jamais une modification qui s'exécuterait plus tard par surprise) ;
  - un numéro peut être limité à certaines zones ; 20 commandes par heure et par numéro ; JOURNAL de chaque commande (qui, zone, nature, commande, issue) dans les Paramètres ;
  - le résultat n'est renvoyé qu'au numéro qui a envoyé la commande ; 3 000 caractères au plus, le reste est tronqué.
Stockage : trois fiches de `settings` (`liluvine_hfsql_acces`, `liluvine_hfsql_attente`, `liluvine_hfsql_journal`), aucune nouvelle collection (cluster plein).
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("uvicorn.error")

ID_ACCES = "liluvine_hfsql_acces"
ID_ATTENTE = "liluvine_hfsql_attente"
ID_JOURNAL = "liluvine_hfsql_journal"
MAX_ACCES = 30
MAX_JOURNAL = 200
VALIDITE_CONFIRMATION_MIN = 5
PAR_HEURE = 20
ATTENTE_RESULTAT_S = 25 * 60           # on attend le résultat au plus 25 minutes (la requête expire à 30 minutes côté file)
PAS_SONDAGE_S = 3
TEXTE_MAX = 3000
LIGNES_AFFICHEES = 15
DECLENCHEUR = re.compile(r"^\s*!?\s*hfsql\b[\s:,-]*(.*)$", re.I | re.S)
ZONE_FIN = re.compile(r"^(.*?)\s+((?:docx|doc|ekol)\s*=\s*[A-Za-z0-9_-]{1,20})\s*$", re.I | re.S)
MOTS_SQL = ("SELECT", "INSERT", "UPDATE", "DELETE")
MOTS_DANGER = ("DROP", "ALTER", "CREATE", "TRUNCATE", "EXEC", "EXECUTE", "GRANT", "REVOKE", "RENAME", "MERGE")
VALIDITE_PARAMETRES_MIN = 10
ZONE = re.compile(r"^\s*((?:docx|doc|ekol)\s*=\s*[A-Za-z0-9_-]{1,20}|/?(?:docx|doc)=[A-Za-z0-9_-]{1,20}|[A-Za-z0-9_-]{1,20})\s+(.+)$", re.I | re.S)
OUI = {"oui", "o", "ok", "d'accord", "daccord", "valider", "confirme", "confirmer", "executer", "execute", "yes"}
NON = {"non", "n", "annuler", "annule", "stop", "no"}


def chiffres(valeur: Any) -> str:
    return "".join(c for c in str(valeur or "") if c.isdigit())


def cle_numero(valeur: Any) -> str:
    """Numéro reconnu par ses 8 derniers chiffres (comme la liste noire et les consignes)."""
    d = chiffres(valeur)
    return d[-8:] if len(d) >= 8 else ""


def _mot(texte: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFD", str(texte or "")).encode("ascii", "ignore").decode().lower().strip()
    return re.sub(r"[\s.!]+$", "", t)


def analyser(texte: str) -> Optional[Dict[str, Any]]:
    """Comprend un message « hfsql … » : {type: "menu"} (« hfsql » seul : liste des raccourcis), {type: "commande", zone, client, sql} (« hfsql docx=CMC UPDATE … »)
    ou {type: "raccourci", ref, zone?} (« hfsql 2 » ou « hfsql statut reçu docx=PHL »). None si ce n'est pas pour nous.
    La zone est « docx=CMC », « doc=CMC », « ekol=IPM » ou le code seul « CMC » : le CODE DU CLIENT (celui de la base) est la partie après « = »."""
    m = DECLENCHEUR.match(str(texte or ""))
    if not m:
        return None
    reste = m.group(1).strip()
    if not reste:
        return {"type": "menu"}
    z = ZONE.match(reste)
    # Une zone EN TÊTE (« docx=CMC … ») ou un mot SQL / interdit juste après un code (« cmc DROP … ») = une commande tapée à la main (les contrôles « Prudent » la refusent si besoin) ;
    # sinon c'est la référence d'un raccourci (numéro ou nom, zone éventuelle à la FIN).
    if z and ("=" in z.group(1) or z.group(2).split(None, 1)[0].upper() in MOTS_SQL + MOTS_DANGER):
        zone = re.sub(r"\s+", "", z.group(1)).lstrip("/")
        return {"type": "commande", "zone": zone, "client": zone.split("=")[-1].upper(), "sql": z.group(2).strip()}
    zf = ZONE_FIN.match(reste)
    ref, zone = (zf.group(1).strip(), re.sub(r"\s+", "", zf.group(2))) if zf else (reste, "")
    return {"type": "raccourci", "ref": ref, "zone": zone}


def extraire(texte: str) -> Optional[Dict[str, str]]:
    """{zone, client, sql} si le message est une commande « hfsql <zone> <SELECT|INSERT|UPDATE|DELETE …> », sinon None (compatibilité)."""
    a = analyser(texte)
    return {k: a[k] for k in ("zone", "client", "sql")} if a and a["type"] == "commande" else None


def nettoyer_acces(liste: Any) -> List[Dict[str, Any]]:
    """Numéros autorisés, sans doublon, bornés. `zones` = codes de clients permis (vide = tous)."""
    vus, propre = set(), []
    for e in (liste if isinstance(liste, list) else []):
        if not isinstance(e, dict):
            continue
        cle = cle_numero(e.get("numero"))
        if not cle or cle in vus:
            continue
        vus.add(cle)
        zones = sorted({z.strip().upper() for z in re.split(r"[,; ]+", str(e.get("zones") or "")) if re.fullmatch(r"[A-Za-z0-9_-]{1,20}", z.strip() or "")})
        propre.append({"cle": cle, "numero": re.sub(r"[^\d+ ]", "", str(e.get("numero") or ""))[:30], "nom": str(e.get("nom") or "")[:120],
                       "zones": ", ".join(zones), "actif": bool(e.get("actif", True))})
    return propre[:MAX_ACCES]


async def lister_acces(db) -> List[Dict[str, Any]]:
    return nettoyer_acces((await db["settings"].find_one({"_id": ID_ACCES}) or {}).get("acces"))


async def enregistrer_acces(db, liste: Any) -> List[Dict[str, Any]]:
    propre = nettoyer_acces(liste)
    await db["settings"].update_one({"_id": ID_ACCES}, {"$set": {"acces": propre}}, upsert=True)
    return propre


async def numero_autorise(db, numero: Any) -> Optional[Dict[str, Any]]:
    cle = cle_numero(numero)
    if not cle:
        return None
    return next((e for e in await lister_acces(db) if e["cle"] == cle and e["actif"]), None)


def zone_permise(acces: Dict[str, Any], client: str) -> bool:
    zones = [z for z in re.split(r"[,; ]+", acces.get("zones") or "") if z]
    return not zones or client.upper() in zones


async def _journaliser(db, entree: Dict[str, Any]) -> None:
    """Une ligne de journal (la commande est gardée, JAMAIS le résultat)."""
    f = await db["settings"].find_one({"_id": ID_JOURNAL}) or {}
    liste = (f.get("entrees") or [])[-(MAX_JOURNAL - 1):] + [{**entree, "quand": datetime.now(timezone.utc).isoformat()}]
    await db["settings"].update_one({"_id": ID_JOURNAL}, {"$set": {"entrees": liste}}, upsert=True)


async def journal(db) -> List[Dict[str, Any]]:
    return list(reversed((await db["settings"].find_one({"_id": ID_JOURNAL}) or {}).get("entrees") or []))


async def _attente(db) -> Dict[str, Any]:
    return (await db["settings"].find_one({"_id": ID_ATTENTE}) or {}).get("attente") or {}


async def _poser(db, cle: str, valeur: Optional[Dict[str, Any]]) -> None:
    a = await _attente(db)
    if valeur is None:
        a.pop(cle, None)
    else:
        a[cle] = valeur
    await db["settings"].update_one({"_id": ID_ATTENTE}, {"$set": {"attente": a}}, upsert=True)


def formater_resultat(zone: str, sql: str, req: Dict[str, Any]) -> str:
    """Réponse WhatsApp : zone d'exécution, base concernée, rappel de la commande, résultat du moteur HFSQL."""
    base = req.get("base") or "base non précisée"
    machine = f" (machine {req['machine']})" if req.get("machine") else ""
    tete = f"📡 Commande HFSQL distante\nZone : {zone}\nBase : {base}{machine}\nCommande : {sql}\n"
    etat = req.get("etat")
    if etat == "terminee" and req.get("ok"):
        colonnes, lignes = req.get("colonnes") or [], req.get("lignes") or []
        if colonnes:
            corps = [" | ".join(colonnes)] + [" | ".join(l) for l in lignes[:LIGNES_AFFICHEES]]
            plus = f"\n… {len(lignes) - LIGNES_AFFICHEES} ligne(s) de plus non affichées." if len(lignes) > LIGNES_AFFICHEES else ""
            plus += "\n(résultat tronqué par la limite de lignes)" if req.get("tronque") else ""
            res = f"✅ {len(lignes)} ligne(s) lue(s) en {req.get('duree_ms') or 0} ms :\n" + "\n".join(corps) + plus
        else:
            res = f"✅ Exécutée : {req.get('lignes_affectees') or 0} ligne(s) modifiée(s) en {req.get('duree_ms') or 0} ms."
        if req.get("message"):
            res += f"\n{req['message']}"
    elif etat == "terminee" or etat == "echec":
        res = "❌ Erreur du moteur HFSQL : " + (req.get("message") or "échec sans détail")
    elif etat == "expiree":
        res = "⏳ Aucune machine du client ne s'est présentée à temps : commande NON exécutée."
    elif etat == "sans_reponse":
        res = "⚠️ Une machine a pris la commande mais n'a pas répondu : l'exécution est INCERTAINE (elle n'est jamais rejouée). Vérifiez dans la base."
    else:
        res = "⏳ Toujours en attente d'une machine du client."
    return (tete + res)[:TEXTE_MAX + 400]


async def _surveiller(db, requete_id: str, zone: str, sql: str, envoyer: Callable[[str], Awaitable[Any]], pas_s: float = PAS_SONDAGE_S, duree_s: float = ATTENTE_RESULTAT_S) -> None:
    """Tâche de FOND (règle 7) : attend le résultat de la file puis l'envoie au demandeur. Une panne ici ne casse rien."""
    from routes.loois_sql_distant import INTERNE
    ecoule = 0.0
    try:
        while ecoule <= duree_s:
            vue = await INTERNE["detail"](requete_id)
            if vue.get("etat") in ("terminee", "echec", "expiree", "sans_reponse"):
                await envoyer(formater_resultat(zone, sql, vue))
                return
            await asyncio.sleep(pas_s)
            ecoule += pas_s
        await envoyer(f"⏳ Pas de réponse après {int(duree_s // 60)} minutes (zone {zone}). La commande reste dans la file ; consultez Loois → Requête SQL distante.")
    except Exception:  # noqa: BLE001
        logger.warning("[hfsql-wa] surveillance de %s interrompue", requete_id, exc_info=True)


async def _deposer(db, acces: Dict[str, Any], zone: str, client: str, sql: str, nature: str, envoyer, surveiller: bool = True) -> str:
    """Dépose la commande dans la file et lance la surveillance du résultat ; rend l'accusé immédiat."""
    from routes.loois_sql_distant import INTERNE
    clients = {c["code"]: c for c in (await INTERNE["clients"]())["clients"]}
    fiche = clients.get(client)
    en_ligne = bool(fiche and fiche.get("en_ligne"))
    if nature == "MODIF" and not en_ligne:
        await _journaliser(db, {"numero": acces["numero"], "nom": acces.get("nom"), "zone": zone, "nature": nature, "sql": sql[:300], "issue": "refusée : client hors ligne"})
        return f"⚠️ Aucune machine du client {client} n'est en ligne : la modification n'est PAS déposée (elle ne doit jamais s'exécuter plus tard par surprise). Réessayez quand le client est connecté."
    try:
        vue = await INTERNE["creer"]({"client": client, "sql": sql, "ephemere": False}, "whatsapp", f"WhatsApp {acces.get('nom') or acces['numero']}"[:120])
    except Exception as exc:  # noqa: BLE001
        detail = getattr(exc, "detail", None) or str(exc)
        await _journaliser(db, {"numero": acces["numero"], "nom": acces.get("nom"), "zone": zone, "nature": nature, "sql": sql[:300], "issue": f"refusée : {detail}"[:200]})
        return f"⚠️ Commande refusée : {detail}"
    await _journaliser(db, {"numero": acces["numero"], "nom": acces.get("nom"), "zone": zone, "nature": nature, "sql": sql[:300], "issue": "déposée", "requete": vue["id"]})
    if surveiller:
        asyncio.get_event_loop().create_task(_surveiller(db, vue["id"], zone, sql, envoyer))
    return f"📡 Commande déposée pour la zone {zone}{'' if en_ligne else ' (client sans machine en ligne : en attente)'}. Je vous réponds dès que la machine a exécuté."


def _liste_pour_whatsapp(raccourcis: List[Dict[str, Any]]) -> str:
    """Menu des raccourcis : numéro, nom, zone, paramètres demandés."""
    if not raccourcis:
        return ("📡 Commande HFSQL distante.\nAucun raccourci n'est encore enregistré.\n"
                "Envoyez une commande complète : « hfsql docx=CMC SELECT … ». Les raccourcis se créent depuis Loois (Requête SQL distante → Dernières requêtes → ⭐ Créer un raccourci).")
    lignes = ["📡 Raccourcis HFSQL — envoyez « hfsql <numéro> » (ou « hfsql <nom> ») :"]
    for n, r in enumerate(raccourcis, 1):
        params = ", ".join(r.get("parametres") or []) or "aucun paramètre"
        lignes.append(f"{n}. {r['nom']} — {r.get('zone') or 'zone à préciser'} — {params}")
    lignes.append("Pour une autre zone : « hfsql 2 docx=PHL ». « annuler » arrête un raccourci en cours.")
    return "\n".join(lignes)


async def _executer_commande(db, acces: Dict[str, Any], zone: str, client: str, sql: str, envoyer, instant, surveiller: bool, confirmer: bool = False) -> str:
    """Contrôles communs (zone permise, « Prudent », limite horaire) puis : SELECT immédiat ; modification = OUI d'abord si `confirmer` (ou commande tapée à la main), sinon dépôt direct."""
    from routes.loois_sql_distant import verifier
    cle = acces["cle"]
    if not zone_permise(acces, client):
        await _journaliser(db, {"numero": acces["numero"], "nom": acces.get("nom"), "zone": zone, "nature": "?", "sql": sql[:300], "issue": "refusée : zone non permise"})
        return f"⛔ Ce numéro n'est pas autorisé pour la zone {client}."
    ok, nature, raison = verifier(sql)
    if not ok:
        await _journaliser(db, {"numero": acces["numero"], "nom": acces.get("nom"), "zone": zone, "nature": "?", "sql": sql[:300], "issue": f"refusée : {raison}"[:200]})
        return f"⚠️ Commande refusée : {raison}"
    recent = [e for e in await journal(db) if e.get("numero") == acces["numero"] and e.get("issue") == "déposée" and datetime.fromisoformat(e["quand"]) > instant - timedelta(hours=1)]
    if len(recent) >= PAR_HEURE:
        return f"⛔ Limite atteinte : {PAR_HEURE} commandes par heure pour ce numéro."
    if nature == "SELECT" or not confirmer:
        return await _deposer(db, acces, zone, client, sql, nature, envoyer, surveiller)
    await _poser(db, cle, {"zone": zone, "client": client, "sql": sql, "expire_le": (instant + timedelta(minutes=VALIDITE_CONFIRMATION_MIN)).isoformat()})
    return (f"✋ MODIFICATION de données — rien n'est encore exécuté.\nZone : {zone}\nCommande : {sql}\n"
            f"Répondez OUI pour EXÉCUTER, NON pour annuler (valable {VALIDITE_CONFIRMATION_MIN} minutes).")


async def _demander_suivant(db, acces, etat: Dict[str, Any], envoyer, instant, surveiller: bool) -> str:
    """Demande le paramètre suivant, ou — toutes les valeurs reçues — résout la commande et l'exécute."""
    import raccourcis_hfsql as rh
    cle = acces["cle"]
    attendus = etat["attendus"]
    if len(etat["valeurs"]) < len(attendus):
        nom = attendus[len(etat["valeurs"])]
        await _poser_parametres(db, cle, etat)
        return f"▶️ {etat['nom']} — valeur de « {nom} » ? ({len(etat['valeurs']) + 1}/{len(attendus)})"
    await _poser_parametres(db, cle, None)
    try:
        sql = rh.resoudre(etat["sql"], dict(zip(attendus, etat["valeurs"])))
    except ValueError as exc:                                   # valeur refusée : on la redemande (jamais d'exécution partielle)
        etat["valeurs"] = etat["valeurs"][:-1]
        await _poser_parametres(db, cle, etat)
        return f"⚠️ {exc} Renvoyez la valeur de « {attendus[len(etat['valeurs'])]} » (ou « annuler »)."
    return await _executer_commande(db, acces, etat["zone"], etat["client"], sql, envoyer, instant, surveiller, confirmer=bool(etat.get("confirmer")))


async def _poser_parametres(db, cle: str, valeur: Optional[Dict[str, Any]]) -> None:
    f = (await db["settings"].find_one({"_id": ID_ATTENTE}) or {}).get("parametres") or {}
    if valeur is None:
        f.pop(cle, None)
    else:
        f[cle] = valeur
    await db["settings"].update_one({"_id": ID_ATTENTE}, {"$set": {"parametres": f}}, upsert=True)


async def _etat_parametres(db, cle: str, instant) -> Optional[Dict[str, Any]]:
    e = ((await db["settings"].find_one({"_id": ID_ATTENTE}) or {}).get("parametres") or {}).get(cle)
    if e and datetime.fromisoformat(e["expire_le"]) < instant:
        await _poser_parametres(db, cle, None)
        return None
    return e


async def traiter(db, numero: Any, texte: str, envoyer: Callable[[str], Awaitable[Any]], instant: Optional[datetime] = None, surveiller: bool = True) -> Optional[str]:
    """Point d'entrée : rend le texte À RÉPONDRE tout de suite si le message est pour nous, sinon None (traitement habituel de Liluvine).
    Pour nous : numéro autorisé ET (« hfsql… », ou OUI / NON à une modification proposée, ou valeur d'un raccourci en cours).
    `envoyer(texte)` sert à envoyer le RÉSULTAT plus tard ; injectable pour les tests."""
    import raccourcis_hfsql as rh
    acces = await numero_autorise(db, numero)
    if not acces:
        return None
    instant = instant or datetime.now(timezone.utc)
    cle = acces["cle"]
    msg = analyser(texte)

    # --- un raccourci attend la valeur d'un paramètre : tout message (sauf une nouvelle commande « hfsql ») est cette valeur
    etat = await _etat_parametres(db, cle, instant)
    if etat and msg is None:
        if _mot(texte) in ("annuler", "annule", "stop", "non"):
            await _poser_parametres(db, cle, None)
            return "D'accord, le raccourci est annulé : rien n'a été exécuté."
        attendu = etat["attendus"][len(etat["valeurs"])]
        try:
            valeur = rh.valider_valeur(attendu, texte)
        except ValueError as exc:                               # refusée tout de suite : on la redemande
            return f"⚠️ {exc} Renvoyez la valeur de « {attendu} » (ou « annuler »)."
        etat["valeurs"] = list(etat["valeurs"]) + [valeur]
        etat["expire_le"] = (instant + timedelta(minutes=VALIDITE_PARAMETRES_MIN)).isoformat()
        return await _demander_suivant(db, acces, etat, envoyer, instant, surveiller)
    if etat and msg is not None:
        await _poser_parametres(db, cle, None)                 # une nouvelle commande « hfsql » remplace le raccourci en cours

    # --- réponse OUI / NON à une modification proposée
    attente = (await _attente(db)).get(cle)
    if attente and datetime.fromisoformat(attente["expire_le"]) < instant:
        await _poser(db, cle, None)
        attente = None
    if attente and msg is None:
        m = _mot(texte)
        rep = True if m in OUI else (False if m in NON else None)
        if rep is None:
            return None
        await _poser(db, cle, None)
        if not rep:
            return "D'accord, la commande est annulée : rien n'a été exécuté."
        return await _deposer(db, acces, attente["zone"], attente["client"], attente["sql"], "MODIF", envoyer, surveiller)
    if msg is None:
        return None

    # --- « hfsql » seul : la liste des raccourcis
    if msg["type"] == "menu":
        return _liste_pour_whatsapp(await rh.lister(db))

    # --- « hfsql 2 » / « hfsql statut reçu » : démarre un raccourci
    if msg["type"] == "raccourci":
        liste = await rh.lister(db)
        r = rh.trouver(liste, msg["ref"])
        if not r:
            return f"⚠️ Je ne trouve pas le raccourci « {msg['ref']} ».\n" + _liste_pour_whatsapp(liste)
        zone = msg["zone"] or r.get("zone") or ""
        if not zone:
            return f"⚠️ Le raccourci « {r['nom']} » n'a pas de zone : ajoutez-la (« hfsql {liste.index(r) + 1} docx=CMC »)."
        client = zone.split("=")[-1].upper()
        etat = {"id": r["id"], "nom": r["nom"], "sql": r["sql"], "zone": zone, "client": client, "attendus": rh.parametres(r["sql"]), "valeurs": [],
                "confirmer": bool(r.get("confirmer")), "expire_le": (instant + timedelta(minutes=VALIDITE_PARAMETRES_MIN)).isoformat()}
        return await _demander_suivant(db, acces, etat, envoyer, instant, surveiller)

    # --- commande tapée en entier : « hfsql docx=CMC UPDATE … » (une modification demande toujours OUI)
    return await _executer_commande(db, acces, msg["zone"], msg["client"], msg["sql"], envoyer, instant, surveiller, confirmer=True)
