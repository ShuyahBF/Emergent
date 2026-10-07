# stats_plateformes.py — Lot 62 : statistiques INTERNES de chaque plateforme (adLyn, beAuthentik,
# Ster, ALBARKA, DentalCare…) — connexions, ventes, inscriptions… — dans la synthèse quotidienne
# de Liluvine et le tableau « Activité des plateformes ».
#
# Protocole (le même canal signé que les « retours » du lot 57.5, avec la même clé d'émetteur) :
#   SAWALI → POST <url_stats ou, à défaut, url_retour de la plateforme>
#     en-têtes : X-Emetteur: sawali · X-Timestamp: <heure Unix> ·
#                X-Signature: HMAC-SHA256(clé de l'émetteur, "<heure>.<corps>")
#     corps    : {"type": "stats_du_jour", "debut": "<ISO>", "fin": "<ISO>"}
#   Plateforme → réponse JSON :
#     {"indicateurs": [{"cle": "connexions", "libelle": "Connexions", "valeur": 42}, …],
#      "faits_marquants": ["3 nouvelles boutiques", …],          (faits_marquants facultatif)
#      "version": "1.84", "deploye_le": "2026-10-04T01:35:00Z"}  (lot 65, facultatifs)
#   Chaque plateforme choisit ses indicateurs ; SAWALI les affiche tels quels.
#
# Résultat gardé 10 minutes (collection plateformes_stats) : l'écran d'administration ne
# relance pas un appel à chaque affichage ; la synthèse quotidienne le relit au besoin.
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

DUREE_CACHE = timedelta(minutes=10)
DELAI_APPEL_S = 10
MAX_INDICATEURS = 20


def _maintenant() -> datetime:
    """Date et heure actuelles (UTC)."""
    return datetime.now(timezone.utc)


def adresse_stats(emetteur: Dict[str, Any]) -> str:
    """Adresse à interroger : URL dédiée aux statistiques, sinon l'URL de retour (lot 57.5)."""
    return ((emetteur.get("url_stats") or "").strip() or (emetteur.get("url_retour") or "").strip())


def _nettoyer(reponse: Any) -> Dict[str, Any]:
    """Garde uniquement des indicateurs bien formés (libellé + valeur affichable)."""
    if not isinstance(reponse, dict):
        raise ValueError("réponse non JSON")
    indicateurs = []
    for brut in (reponse.get("indicateurs") or [])[:MAX_INDICATEURS]:
        if not isinstance(brut, dict):
            continue
        libelle = str(brut.get("libelle") or brut.get("cle") or "").strip()[:60]
        valeur = brut.get("valeur")
        if not libelle or valeur is None or isinstance(valeur, (dict, list)):
            continue
        indicateurs.append({"cle": str(brut.get("cle") or libelle)[:40], "libelle": libelle,
                            "valeur": valeur if isinstance(valeur, (int, float)) else str(valeur)[:40]})
    faits = [str(f).strip()[:200] for f in (reponse.get("faits_marquants") or [])[:5] if str(f).strip()]
    if not indicateurs and not faits:
        raise ValueError("aucun indicateur dans la réponse")
    # Lot 63 — nombre d'utilisateurs actifs sur la plateforme ces 5 dernières minutes (facultatif)
    connectes = reponse.get("utilisateurs_connectes")
    connectes = int(connectes) if isinstance(connectes, (int, float)) and not isinstance(connectes, bool) else None
    # Lot 65 — version déployée de la plateforme et date de déploiement (facultatives, texte court)
    version = str(reponse.get("version") or "").strip()[:40] or None
    deploye_le = str(reponse.get("deploye_le") or "").strip()[:40] or None
    return {"indicateurs": indicateurs, "faits_marquants": faits, "utilisateurs_connectes": connectes,
            "version": version, "deploye_le": deploye_le}


async def interroger(emetteur: Dict[str, Any], debut_iso: str, fin_iso: str) -> Dict[str, Any]:
    """Appel signé à la plateforme ; renvoie {ok, indicateurs, faits_marquants} ou {ok: False, erreur}."""
    url = adresse_stats(emetteur)
    cle = (emetteur.get("secret") or "").encode()
    if not url:
        return {"ok": False, "erreur": "aucune adresse de statistiques (URL de retour ou URL des statistiques)"}
    if not cle:
        return {"ok": False, "erreur": "clé de l'émetteur absente"}
    corps = json.dumps({"type": "stats_du_jour", "debut": debut_iso, "fin": fin_iso}, ensure_ascii=False)
    ts = str(int(time.time()))
    signature = hmac.new(cle, f"{ts}.{corps}".encode(), hashlib.sha256).hexdigest()
    try:
        async with httpx.AsyncClient(timeout=DELAI_APPEL_S) as http:
            r = await http.post(url, content=corps.encode(), headers={
                "Content-Type": "application/json", "X-Emetteur": "sawali",
                "X-Timestamp": ts, "X-Signature": signature})
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "erreur": f"plateforme injoignable ({type(exc).__name__})"}
    if r.status_code >= 300:
        return {"ok": False, "erreur": f"HTTP {r.status_code}"}
    try:
        return {"ok": True, **_nettoyer(r.json())}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "erreur": f"réponse inexploitable : {exc}"}


# Lot 72 — rafraîchissements en arrière-plan en cours (un seul à la fois par plateforme)
_RAFRAICHISSEMENTS: Dict[str, "asyncio.Task"] = {}


async def stats_plateforme(db, emetteur: Dict[str, Any], debut_iso: str, fin_iso: str,
                           forcer: bool = False, duree_cache: timedelta = DUREE_CACHE,
                           sans_attendre: bool = False) -> Dict[str, Any]:
    """Statistiques internes d'une plateforme pour la période (cache de 10 minutes ;
    lot 63 : 1 minute pour la page « temps réel »).

    Lot 72 — sans_attendre (pages de l'administration) : si le cache est périmé, on renvoie TOUT DE SUITE les
    derniers chiffres connus (« perime » = True) et on les rafraîchit en arrière-plan ; la page ne patiente plus
    jusqu'à 10 s qu'une plateforme lente réponde. Sans aucun chiffre connu, on attend comme avant."""
    code = emetteur.get("code")
    cle_cache = f"{code}|{debut_iso[:13]}|{fin_iso[:13]}"     # période arrondie à l'heure
    if not forcer:
        en_cache = await db.plateformes_stats.find_one({"_id": cle_cache})
        if en_cache:
            try:
                if _maintenant() - datetime.fromisoformat(en_cache["recu_le"]) < duree_cache:
                    return en_cache["resultat"]
            except (KeyError, ValueError):
                pass
        if sans_attendre:
            # Derniers chiffres connus de cette plateforme (même période, sinon la plus récente)
            ancien = en_cache or await db.plateformes_stats.find_one({"code": code}, sort=[("recu_le", -1)])
            if ancien and ancien.get("resultat"):
                if code not in _RAFRAICHISSEMENTS or _RAFRAICHISSEMENTS[code].done():
                    _RAFRAICHISSEMENTS[code] = asyncio.create_task(
                        stats_plateforme(db, emetteur, debut_iso, fin_iso, forcer=True))
                return {**ancien["resultat"], "perime": True}
    resultat = await interroger(emetteur, debut_iso, fin_iso)
    resultat["recu_le"] = _maintenant().isoformat()
    await db.plateformes_stats.update_one(
        {"_id": cle_cache},
        {"$set": {"code": code, "debut": debut_iso, "fin": fin_iso, "recu_le": resultat["recu_le"],
                  "resultat": resultat}}, upsert=True)
    await db.liluvine_emetteurs.update_one({"code": code}, {"$set": {
        ("derniere_stats_ok" if resultat.get("ok") else "derniere_stats_echec"): resultat["recu_le"]}})
    return resultat


async def stats_toutes(db, emetteurs: List[Dict[str, Any]], debut_iso: str, fin_iso: str,
                       duree_cache: timedelta = DUREE_CACHE, sans_attendre: bool = False) -> Dict[str, Dict[str, Any]]:
    """Statistiques internes de toutes les plateformes actives qui ont une adresse (en parallèle).
    sans_attendre (lot 72) : chiffres connus tout de suite, rafraîchis en arrière-plan (voir stats_plateforme)."""
    cibles = [e for e in emetteurs if e.get("actif", True) and adresse_stats(e) and e.get("secret")]
    resultats = await asyncio.gather(*(stats_plateforme(db, e, debut_iso, fin_iso, duree_cache=duree_cache,
                                                        sans_attendre=sans_attendre)
                                       for e in cibles), return_exceptions=True)
    sortie: Dict[str, Dict[str, Any]] = {}
    for e, res in zip(cibles, resultats):
        sortie[e["code"]] = res if isinstance(res, dict) else {"ok": False, "erreur": str(res)[:120]}
    return sortie


def texte_indicateurs(interne: Optional[Dict[str, Any]]) -> str:
    """« Connexions 42 · Ventes 12 » (ou la raison de l'absence de statistiques)."""
    if not interne:
        return ""
    if not interne.get("ok"):
        return f"statistiques internes indisponibles ({interne.get('erreur') or 'erreur'})"
    morceaux = [f"{i['libelle']} {i['valeur']}" for i in interne.get("indicateurs") or []]
    return " · ".join(morceaux)
