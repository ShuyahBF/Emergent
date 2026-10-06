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


def fenetre_plateformes(debut, fin) -> tuple:
    """Période d'analyse des plateformes pour une synthèse du `debut` au `fin` (dates).

    Synthèse « du jour » (envoyée le matin, par exemple à 08:00) : les 24 dernières heures,
    sinon elle ne montrerait que l'activité de la nuit. Autre période : du début à la fin inclus.
    """
    from datetime import date, datetime, timedelta, timezone
    if debut == fin == date.today():
        maintenant = datetime.now(timezone.utc)
        return (maintenant - timedelta(hours=24)).isoformat(), maintenant.isoformat()
    return debut.isoformat(), (fin + timedelta(days=1)).isoformat()


async def _compter(db, collection: str, filtre: Dict[str, Any]) -> int:
    """Nombre de documents (0 si la collection est absente ou en erreur)."""
    try:
        return await db[collection].count_documents(filtre)
    except Exception:  # noqa: BLE001
        return 0


async def activite_plateformes(db, debut_iso: str, fin_iso: str, avec_interne: bool = True) -> List[Dict[str, Any]]:
    """Activité de chaque plateforme entre debut_iso (inclus) et fin_iso (exclu).

    Lot 62 : avec_interne → ajoute aussi les statistiques INTERNES fournies par la plateforme
    elle-même (connexions, ventes, inscriptions…), champ « interne »."""
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
            "stats_configurees": bool((e.get("url_stats") or e.get("url_retour") or "").strip()),
        })
    # Lot 62 — statistiques internes de chaque plateforme (appels signés, en parallèle)
    if avec_interne and resultat:
        try:
            from routes.stats_plateformes import stats_toutes
            complets = [x async for x in db.liluvine_emetteurs.find({}, {"_id": 0})]
            internes = await stats_toutes(db, complets, debut_iso, fin_iso)
            for p in resultat:
                p["interne"] = internes.get(p["code"])
        except Exception:  # noqa: BLE001 — les statistiques internes ne bloquent jamais le rapport
            pass
    return resultat


def bloc_plateformes(plateformes: List[Dict[str, Any]]) -> str:
    """Texte « 🌐 Activité des plateformes », ajouté tel quel à la synthèse (chiffres exacts)."""
    if not plateformes:
        return ""
    lignes = ["🌐 Activité des plateformes (messages WhatsApp transmis par SAWALI + activité interne)"]
    for p in plateformes:
        etat = "" if p["actif"] else " (désactivée)"
        # Lot 62 — activité interne fournie par la plateforme (connexions, ventes…)
        interne = ""
        try:
            from routes.stats_plateformes import texte_indicateurs
            interne = texte_indicateurs(p.get("interne"))
        except Exception:  # noqa: BLE001
            pass
        faits = [f for f in ((p.get("interne") or {}).get("faits_marquants") or [])]
        if not p["envois"] and not p["reponses"] and not p["desinscriptions"]:
            lignes.append(f"• {p['nom']}{etat} : aucun message WhatsApp transmis"
                          + (f" — dernier envoi le {p['dernier_envoi'][:10]}" if p.get("dernier_envoi") else ""))
            if interne:
                lignes.append(f"   Activité interne : {interne}")
            lignes += [f"   ◦ {f}" for f in faits]
            continue
        ligne = (f"• {p['nom']}{etat} : {p['envois']} envoi(s), {p['reussis']} réussi(s), {p['echecs']} échec(s), "
                 f"{p['remis']} remis, {p['lus']} lu(s), {p['reponses']} réponse(s) client, "
                 f"{p['desinscriptions']} désinscription(s)")
        if p["incidents"]:
            ligne += f", ⚠️ {p['incidents']} incident(s)"
        if p.get("usage_quota_pct") is not None:
            ligne += f" — quota utilisé : {p['usage_quota_pct']} %"
        lignes.append(ligne)
        if interne:
            lignes.append(f"   Activité interne : {interne}")
        lignes += [f"   ◦ {f}" for f in faits]
    return "\n".join(lignes)


def setup_rapport_plateformes_routes(*, db, api, get_current_user) -> None:
    """Lot 61.1 — écran « Activité des plateformes » (administration → Synthèse Liluvine)."""
    from datetime import datetime, timedelta, timezone

    from fastapi import Depends, HTTPException, Query

    @api.get("/admin/plateformes-activite", tags=["Admin — Synthèse"])
    async def plateformes_activite(jours: int = Query(1, ge=1, le=90), user: dict = Depends(get_current_user)):
        """Activité de chaque plateforme sur les `jours` derniers jours (+ texte de la synthèse)."""
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs et superviseurs")
        fin = datetime.now(timezone.utc)
        debut = fin - timedelta(days=jours)
        items = await activite_plateformes(db, debut.isoformat(), fin.isoformat())
        return {"debut": debut.isoformat(), "fin": fin.isoformat(), "jours": jours,
                "items": items, "texte": bloc_plateformes(items)}

    @api.post("/admin/plateformes-activite/{code}/tester", tags=["Admin — Synthèse"])
    async def tester_stats(code: str, user: dict = Depends(get_current_user)):
        """Lot 62 — interroge tout de suite la plateforme (sans cache) et renvoie sa réponse."""
        if user.get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs et superviseurs")
        emetteur = await db.liluvine_emetteurs.find_one({"code": code}, {"_id": 0})
        if not emetteur:
            raise HTTPException(status_code=404, detail="Plateforme introuvable")
        from routes.stats_plateformes import stats_plateforme
        fin = datetime.now(timezone.utc)
        return await stats_plateforme(db, emetteur, (fin - timedelta(days=1)).isoformat(), fin.isoformat(), forcer=True)
