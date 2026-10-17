# wa_usage_lignes.py — Lot 224 : suivi des consommations WhatsApp PAR LIGNE et PAR PÉRIODE (facturation éventuelle).
#
# Principe : chaque message WhatsApp envoyé ou reçu par une ligne de SAWALI (numéro principal ou ligne supplémentaire, voir
# numeros_wa.py) est compté dans un document par ligne et par mois, rangé dans la collection EXISTANTE `settings`
# (_id « wa_usage:<Phone Number ID>:<AAAA-MM> ») : le cluster MongoDB est plein (500 / 500 collections), aucune nouvelle
# collection n'est créée.
#
#   jours.<AAAA-MM-JJ> = { out, in, echecs,                      messages sortants / entrants / envois refusés
#                          t_texte, t_modele, t_media, t_interactif,   par type d'envoi
#                          m_<nom du modèle Meta>, c_<CATÉGORIE>,     modèles Meta utilisés et leur catégorie facturable
#                          h_<HH>,                                    messages par heure (00-23, UTC = heure de Ouagadougou)
#                          ia_appels, ia_tokens, ia_cout_xof }        consommation d'IA (réponses de Liluvine)
#   derniers = 500 derniers événements détaillés du mois : date/heure, sens, type, modèle, catégorie, 4 derniers chiffres
#              du correspondant (jamais le texte du message).
#
# Les compteurs partent du déploiement de ce lot : l'historique antérieur n'est pas reconstitué (sauf les messages reçus,
# déjà marqués par numéro depuis le lot 59).
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

logger = logging.getLogger(__name__)

PREFIXE_ID = "wa_usage:"
EVENEMENTS_MAX = 500          # événements détaillés gardés par ligne et par mois
TYPES_ENVOI = ("texte", "modele", "media", "interactif")


def _sain(nom: Any) -> str:
    """Nom utilisable comme clé MongoDB (ni point, ni $, ni espace)."""
    return re.sub(r"[.$\s]", "_", str(nom or ""))[:80]


def _id_doc(phone_number_id: str, mois: str) -> str:
    return f"{PREFIXE_ID}{phone_number_id}:{mois}"


async def noter(db, *, phone_number_id: Optional[str], sens: str = "out", type_msg: str = "texte",
                modele: Optional[str] = None, categorie: Optional[str] = None, destinataire: Optional[str] = None,
                ok: bool = True, ia: Optional[Dict[str, Any]] = None, maintenant: Optional[datetime] = None) -> None:
    """Compte UN événement sur la ligne `phone_number_id`. Ne lève jamais d'exception (le suivi ne bloque aucun envoi).

    sens : « out » (envoi) ou « in » (réception) ; type_msg : texte | modele | media | interactif ;
    ia : {"tokens": n, "cout_xof": x} pour une consommation d'IA (réponse de Liluvine) — compte à part, sans message."""
    try:
        pid = str(phone_number_id or "").strip()
        if not pid:
            return
        t = maintenant or datetime.now(timezone.utc)
        mois, jour, heure = t.strftime("%Y-%m"), t.strftime("%Y-%m-%d"), t.strftime("%H")
        base = f"jours.{jour}"
        inc: Dict[str, float] = {}
        evenement: Dict[str, Any] = {"t": t.isoformat(timespec="seconds"), "sens": sens, "type": type_msg}
        if ia is not None:
            inc[f"{base}.ia_appels"] = 1
            inc[f"{base}.ia_tokens"] = float(ia.get("tokens") or 0)
            inc[f"{base}.ia_cout_xof"] = float(ia.get("cout_xof") or 0)
            evenement.update({"type": "ia", "tokens": int(ia.get("tokens") or 0), "cout_xof": float(ia.get("cout_xof") or 0)})
        elif not ok:
            inc[f"{base}.echecs"] = 1
            evenement["ok"] = False
        else:
            inc[f"{base}.{'out' if sens == 'out' else 'in'}"] = 1
            if type_msg in TYPES_ENVOI:
                inc[f"{base}.t_{type_msg}"] = 1
            inc[f"{base}.h_{heure}"] = 1
            if modele:
                inc[f"{base}.m_{_sain(modele)}"] = 1
                evenement["modele"] = str(modele)[:80]
            if categorie:
                inc[f"{base}.c_{_sain(str(categorie).upper())}"] = 1
                evenement["categorie"] = str(categorie).upper()
        chiffres = re.sub(r"\D", "", destinataire or "")
        if chiffres:
            evenement["fin"] = chiffres[-4:]                 # 4 derniers chiffres seulement
        await db.settings.update_one(
            {"_id": _id_doc(pid, mois)},
            {"$inc": inc,
             "$set": {"type": "wa_usage", "phone_number_id": pid, "mois": mois},
             "$push": {"derniers": {"$each": [evenement], "$slice": -EVENEMENTS_MAX}}},
            upsert=True)
    except Exception:  # noqa: BLE001 — le suivi ne doit jamais empêcher un envoi
        logger.debug("[wa_usage] comptage impossible", exc_info=True)


# ----------------------------------------------------------------------------- lecture / agrégation
def _jours_entre(du: str, au: str) -> List[str]:
    d0, d1 = datetime.strptime(du, "%Y-%m-%d"), datetime.strptime(au, "%Y-%m-%d")
    return [(d0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((d1 - d0).days + 1)]


def _periode(du: Optional[str], au: Optional[str]) -> tuple:
    """(du, au) en AAAA-MM-JJ ; défaut : le mois en cours. Lève 400 si invalide ou plus de 366 jours."""
    aujourdhui = datetime.now(timezone.utc)
    try:
        d1 = datetime.strptime(au[:10], "%Y-%m-%d") if au else aujourdhui.replace(tzinfo=None)
        d0 = datetime.strptime(du[:10], "%Y-%m-%d") if du else d1.replace(day=1)
    except ValueError:
        raise HTTPException(status_code=400, detail="Date invalide (format attendu : AAAA-MM-JJ)")
    if d0 > d1:
        raise HTTPException(status_code=400, detail="La date de début doit précéder la date de fin")
    if (d1 - d0).days > 366:
        raise HTTPException(status_code=400, detail="Période limitée à 366 jours")
    return d0.strftime("%Y-%m-%d"), d1.strftime("%Y-%m-%d")


def _mois_de(du: str, au: str) -> List[str]:
    vus: List[str] = []
    for j in _jours_entre(du, au):
        m = j[:7]
        if m not in vus:
            vus.append(m)
    return vus


def _vide() -> Dict[str, Any]:
    return {"sortants": 0, "entrants": 0, "echecs": 0, "par_type": {t: 0 for t in TYPES_ENVOI},
            "modeles": {}, "categories": {}, "heures": {f"{h:02d}": 0 for h in range(24)},
            "ia": {"appels": 0, "tokens": 0, "cout_xof": 0.0}, "jours": {}}


def _ajouter_jour(cumul: Dict[str, Any], jour: str, d: Dict[str, Any]) -> None:
    out, ent = int(d.get("out") or 0), int(d.get("in") or 0)
    cumul["sortants"] += out
    cumul["entrants"] += ent
    cumul["echecs"] += int(d.get("echecs") or 0)
    for t in TYPES_ENVOI:
        cumul["par_type"][t] += int(d.get(f"t_{t}") or 0)
    for cle, val in d.items():
        if cle.startswith("m_"):
            cumul["modeles"][cle[2:]] = cumul["modeles"].get(cle[2:], 0) + int(val or 0)
        elif cle.startswith("c_"):
            cumul["categories"][cle[2:]] = cumul["categories"].get(cle[2:], 0) + int(val or 0)
        elif cle.startswith("h_") and cle[2:] in cumul["heures"]:
            cumul["heures"][cle[2:]] += int(val or 0)
    cumul["ia"]["appels"] += int(d.get("ia_appels") or 0)
    cumul["ia"]["tokens"] += int(d.get("ia_tokens") or 0)
    cumul["ia"]["cout_xof"] = round(cumul["ia"]["cout_xof"] + float(d.get("ia_cout_xof") or 0), 2)
    cumul["jours"][jour] = {"sortants": out, "entrants": ent, "ia_cout_xof": round(float(d.get("ia_cout_xof") or 0), 2),
                            "modeles": int(d.get("t_modele") or 0)}


async def rapport(db, *, du: Optional[str], au: Optional[str], ligne: Optional[str] = None,
                  detail_max: int = 300, reglages: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Consommations par ligne sur la période (du … au, jours inclus). `ligne` = clé de ligne (« principal » ou Phone Number ID)
    ou vide pour toutes. Renvoie un résumé par ligne, les totaux, la série par jour et les événements détaillés."""
    from routes.numeros_wa import lignes_configurees
    du, au = _periode(du, au)
    reglages = reglages if reglages is not None else (await db.settings.find_one({"_id": "global"}) or {})
    lignes = lignes_configurees(reglages)
    if ligne:
        lignes = [l for l in lignes if l["cle"] == ligne or l["phone_number_id"] == ligne]
        if not lignes:
            raise HTTPException(status_code=404, detail="Ligne inconnue")
    jours_utiles = set(_jours_entre(du, au))
    mois = _mois_de(du, au)
    sortie_lignes: List[Dict[str, Any]] = []
    evenements: List[Dict[str, Any]] = []
    total = _vide()
    for l in lignes:
        pid = l["phone_number_id"]
        cumul = _vide()
        if pid:
            for m in mois:
                doc = await db.settings.find_one({"_id": _id_doc(pid, m)}) or {}
                for jour, d in sorted((doc.get("jours") or {}).items()):
                    if jour in jours_utiles:
                        _ajouter_jour(cumul, jour, d)
                for ev in doc.get("derniers") or []:
                    if du <= str(ev.get("t") or "")[:10] <= au:
                        evenements.append({**ev, "ligne": l["libelle"], "ligne_cle": l["cle"]})
        sortie_lignes.append({"cle": l["cle"], "libelle": l["libelle"], "telephone": l["telephone"],
                              "privee": bool(l.get("privee")), "principale": bool(l.get("principale")), **cumul})
        # Totaux toutes lignes
        total["sortants"] += cumul["sortants"]; total["entrants"] += cumul["entrants"]; total["echecs"] += cumul["echecs"]
        for t in TYPES_ENVOI:
            total["par_type"][t] += cumul["par_type"][t]
        for n, v in cumul["modeles"].items():
            total["modeles"][n] = total["modeles"].get(n, 0) + v
        for n, v in cumul["categories"].items():
            total["categories"][n] = total["categories"].get(n, 0) + v
        for h, v in cumul["heures"].items():
            total["heures"][h] += v
        total["ia"]["appels"] += cumul["ia"]["appels"]; total["ia"]["tokens"] += cumul["ia"]["tokens"]
        total["ia"]["cout_xof"] = round(total["ia"]["cout_xof"] + cumul["ia"]["cout_xof"], 2)
        for jour, d in cumul["jours"].items():
            c = total["jours"].setdefault(jour, {"sortants": 0, "entrants": 0, "ia_cout_xof": 0.0, "modeles": 0})
            c["sortants"] += d["sortants"]; c["entrants"] += d["entrants"]; c["modeles"] += d["modeles"]
            c["ia_cout_xof"] = round(c["ia_cout_xof"] + d["ia_cout_xof"], 2)
    evenements.sort(key=lambda e: e.get("t") or "", reverse=True)
    serie = [{"jour": j, **total["jours"].get(j, {"sortants": 0, "entrants": 0, "ia_cout_xof": 0.0, "modeles": 0})} for j in sorted(jours_utiles)]
    total.pop("jours", None)
    for l in sortie_lignes:
        l["jours"] = [{"jour": j, "sortants": d["sortants"], "entrants": d["entrants"], "modeles": d["modeles"], "ia_cout_xof": d["ia_cout_xof"]}
                      for j, d in sorted(l["jours"].items())]
    return {"du": du, "au": au, "lignes": sortie_lignes, "total": total, "serie": serie,
            "evenements": evenements[:detail_max], "nb_evenements": len(evenements),
            "note": "Les compteurs partent du déploiement du suivi ; l'historique antérieur n'est pas reconstitué."}



def csv_rapport(donnees: Dict[str, Any]) -> str:
    """Export CSV (séparateur « ; », ouvert directement par Excel) : une ligne par ligne WhatsApp et par jour."""
    tampon = io.StringIO()
    tampon.write("﻿")
    ecrivain = csv.writer(tampon, delimiter=";")
    ecrivain.writerow(["Ligne", "Téléphone", "Jour", "Messages envoyés", "Messages reçus", "Coût IA (XOF)"])
    for l in donnees["lignes"]:
        for j in l["jours"]:
            ecrivain.writerow([l["libelle"], l["telephone"], j["jour"], j["sortants"], j["entrants"], j["ia_cout_xof"]])
    ecrivain.writerow([])
    ecrivain.writerow(["Ligne", "Date et heure (UTC)", "Sens", "Type", "Modèle Meta", "Catégorie", "Fin du numéro", "Tokens IA", "Coût IA (XOF)", "Échec"])
    for e in donnees["evenements"]:
        ecrivain.writerow([e.get("ligne"), e.get("t"), "envoi" if e.get("sens") == "out" else "réception", e.get("type"),
                           e.get("modele") or "", e.get("categorie") or "", e.get("fin") or "", e.get("tokens") or "",
                           e.get("cout_xof") or "", "oui" if e.get("ok") is False else ""])
    return tampon.getvalue()


def make_wa_usage_router(*, db, get_current_admin) -> APIRouter:
    router = APIRouter()

    @router.get("/admin/wa-lignes/usage", tags=["Admin — Lignes WhatsApp"])
    async def usage(du: Optional[str] = Query(None), au: Optional[str] = Query(None), ligne: Optional[str] = Query(None),
                    _: dict = Depends(get_current_admin)):
        """Consommations par ligne WhatsApp sur une période (défaut : mois en cours)."""
        return await rapport(db, du=du, au=au, ligne=ligne)

    @router.get("/admin/wa-lignes/usage.csv", tags=["Admin — Lignes WhatsApp"])
    async def usage_csv(du: Optional[str] = Query(None), au: Optional[str] = Query(None), ligne: Optional[str] = Query(None),
                        _: dict = Depends(get_current_admin)):
        """Même rapport en CSV (Excel), détails date/heure compris (500 derniers événements par ligne et par mois)."""
        donnees = await rapport(db, du=du, au=au, ligne=ligne, detail_max=100000)
        return Response(content=csv_rapport(donnees).encode("utf-8"), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="lignes_whatsapp_{donnees["du"]}_{donnees["au"]}.csv"'})

    return router
