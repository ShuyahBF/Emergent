# rapport_plateformes.py — Lot 61 : activité et usage de chaque plateforme (adLyn, beAuthentik,
# Ster, ALBARKA…) dans la synthèse quotidienne de Liluvine.
#
# Source : la « Transmission WA Universelle » (lots 57.3 à 57.5). Chaque plateforme est un
# « émetteur » (collection liluvine_emetteurs) qui demande à SAWALI d'envoyer ses messages
# WhatsApp ; chaque envoi est journalisé (liluvine_transmissions), ainsi que les réponses des
# clients relayées à la plateforme (liluvine_reponses), les désinscriptions STOP
# (liluvine_desinscriptions) et les incidents (liluvine_incidents).
#
# Pour chaque plateforme, sur la période : envois, réussis, échecs, remis, lus, réponses
# reçues, désinscriptions, incidents, dernier envoi, et usage du quota journalier.
from __future__ import annotations

from typing import Any, Dict, List


async def _compter(db, collection: str, filtre: Dict[str, Any]) -> int:
    """Nombre de documents (0 si la collection est absente ou en erreur)."""
    try:
        return await db[collection].count_documents(filtre)
    except Exception:  # noqa: BLE001
        return 0


async def activite_plateformes(db, debut_iso: str, fin_iso: str) -> List[Dict[str, Any]]:
    """Activité de chaque plateforme entre debut_iso (inclus) et fin_iso (exclu)."""
    periode = {"$gte": debut_iso, "$lt": fin_iso}
    nb_jours = 1
    try:
        from datetime import date
        nb_jours = max(1, (date.fromisoformat(fin_iso[:10]) - date.fromisoformat(debut_iso[:10])).days)
    except ValueError:
        pass
    resultat: List[Dict[str, Any]] = []
    try:
        emetteurs = [e async for e in db.liluvine_emetteurs.find({}, {"_id": 0, "secret": 0}).sort("nom", 1)]
    except Exception:  # noqa: BLE001
        emetteurs = []
    for e in emetteurs:
        code = e.get("code")
        if not code:
            continue
        base = {"emetteur": code, "date": periode}
        envois = await _compter(db, "liluvine_transmissions", base)
        reussis = await _compter(db, "liluvine_transmissions", {**base, "ok": True})
        remis = await _compter(db, "liluvine_transmissions", {**base, "statut": {"$in": ["delivered", "read"]}})
        lus = await _compter(db, "liluvine_transmissions", {**base, "statut": "read"})
        quota = int(e.get("quota_jour") or 0)
        resultat.append({
            "code": code,
            "nom": e.get("nom") or code,
            "actif": bool(e.get("actif", True)),
            "envois": envois,
            "reussis": reussis,
            "echecs": envois - reussis,
            "remis": remis,
            "lus": lus,
            "reponses": await _compter(db, "liluvine_reponses", {"emetteur": code, "relaye_le": periode}),
            "desinscriptions": await _compter(db, "liluvine_desinscriptions",
                                              {"emetteur": code, "actif": True, "date": periode}),
            "incidents": await _compter(db, "liluvine_incidents", {"emetteur": code, "date": periode}),
            "dernier_envoi": e.get("dernier_envoi"),
            "quota_jour": quota,
            # Usage moyen du quota journalier sur la période (en %)
            "usage_quota_pct": round(100 * envois / (quota * nb_jours)) if quota else None,
        })
    return resultat


def bloc_plateformes(plateformes: List[Dict[str, Any]]) -> str:
    """Texte « 🌐 Activité des plateformes », ajouté tel quel à la synthèse (chiffres exacts)."""
    if not plateformes:
        return ""
    lignes = ["🌐 Activité des plateformes (messages WhatsApp transmis par SAWALI)"]
    for p in plateformes:
        etat = "" if p["actif"] else " (désactivée)"
        if not p["envois"] and not p["reponses"] and not p["desinscriptions"]:
            lignes.append(f"• {p['nom']}{etat} : aucune activité"
                          + (f" — dernier envoi le {p['dernier_envoi'][:10]}" if p.get("dernier_envoi") else ""))
            continue
        ligne = (f"• {p['nom']}{etat} : {p['envois']} envoi(s), {p['reussis']} réussi(s), {p['echecs']} échec(s), "
                 f"{p['remis']} remis, {p['lus']} lu(s), {p['reponses']} réponse(s) client, "
                 f"{p['desinscriptions']} désinscription(s)")
        if p["incidents"]:
            ligne += f", ⚠️ {p['incidents']} incident(s)"
        if p.get("usage_quota_pct") is not None:
            ligne += f" — quota utilisé : {p['usage_quota_pct']} %"
        lignes.append(ligne)
    return "\n".join(lignes)
