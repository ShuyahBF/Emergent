"""Lot 106 — Une PLATEFORME (ZandGo…) demande à Liluvine d'APPELER un de ses clients.

Demande du propriétaire (10/10/2026) : sur ZandGo, des visiteurs passent commande puis s'arrêtent (aucun moyen de
paiement, incident de paiement). « Liluvine ou un humain peut communiquer (appel ou message) pour avoir plus
d'informations et relancer ce client. »

Pour un développeur WinDev : la plateforme « dépose une fiche » dans l'agenda d'appels de Liluvine (lot 70), puis
vient relire cette fiche pour connaître le résultat. Aucun nouveau moteur : l'appel, l'autorisation WhatsApp, les
nouvelles tentatives, le résumé et les informations recueillies sont ceux de l'agenda.

Sécurité : requêtes SIGNÉES avec la clé d'émetteur de la plateforme (même règle que la Transmission universelle et
les contrats : en-têtes X-Emetteur, X-Timestamp, X-Signature = HMAC-SHA256(clé, "<horodatage>.<corps brut>")).
Une plateforme ne voit QUE les appels qu'elle a demandés.

  POST /api/webhook/plateforme-appel
       {"ref": "ZG-261010-ABCD", "telephone": "22670…", "nom": "Awa", "objectif": "…", "contexte": "…",
        "texte_a_lire": "…", "questions": ["…", {"libelle": "…", "type": "oui_non"}], "date_heure"?: ISO}
       → {"id", "statut", "statut_libelle", "deja": bool}   (une seule fiche active par référence)
  POST /api/webhook/plateforme-appel/etat   {"ref": "ZG-…"}
       → {"id", "statut", "statut_libelle", "tentatives", "resume", "informations", "action_suivante", "termine_le",
          "derniere_etape"}
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import HTTPException, Request

import routes.liluvine_agenda as ag
from routes.contrats_plateformes import signature_valide

# Statuts d'une fiche encore « vivante » (une nouvelle demande pour la même référence la renvoie telle quelle)
STATUTS_ACTIFS = ("planifie", "attente_autorisation", "en_cours")


def id_fiche(code: str, ref: str) -> str:
    """Identifiant stable de la fiche : plat-<plateforme>-<référence nettoyée>."""
    return f"plat-{code}-{re.sub(r'[^A-Za-z0-9_-]', '', ref)[:60]}"


def etat_public(ev: Dict[str, Any]) -> Dict[str, Any]:
    """Ce que la plateforme peut lire : statut et résultat (jamais la transcription complète ni les coûts)."""
    r = ev.get("resultat") or {}
    histo = ev.get("historique") or []
    return {
        "id": ev["id"], "statut": ev.get("statut"), "statut_libelle": ag.STATUTS.get(ev.get("statut"), ev.get("statut")),
        "tentatives": ev.get("tentatives", 0), "prochaine_tentative": ev.get("prochaine_tentative"),
        "resume": r.get("resume"), "informations": r.get("informations"), "action_suivante": r.get("action_suivante"),
        "duree_s": r.get("duree_s"), "termine_le": r.get("termine_le"),
        "derniere_etape": (histo[-1] if histo else None),
    }


def setup_appels_plateformes_routes(*, api, db):

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

    @api.post("/webhook/plateforme-appel", tags=["Plateformes — appels Liluvine"])
    async def demander_appel(request: Request):
        """Crée (ou renvoie) la fiche d'appel de Liluvine pour une référence de la plateforme."""
        emetteur, corps = await _emetteur_signe(request)
        code = emetteur["code"]
        ref = str(corps.get("ref") or "").strip()
        if not ref:
            raise HTTPException(status_code=422, detail="Référence (ref) obligatoire")
        fid = id_fiche(code, ref)
        existante = await db[ag.COLLECTION].find_one({"id": fid}, {"_id": 0})
        if existante and existante.get("statut") in STATUTS_ACTIFS:
            return {**etat_public(existante), "deja": True}

        s = await db.settings.find_one({"_id": "global"}) or {}
        cfga = ag.reglages_agenda(s)
        nom_plateforme = emetteur.get("nom") or code
        maintenant = ag._maintenant()
        try:
            champs = ag.valider_evenement({
                "date_heure": corps.get("date_heure") or ag._iso(maintenant), "type": "relance",
                "titre": f"Relance {nom_plateforme} — {str(corps.get('nom') or '').strip() or ref}",
                "contact": {"source": "libre", "nom": corps.get("nom"), "telephone": corps.get("telephone")},
                "objectif": corps.get("objectif"), "contexte": corps.get("contexte"),
                "texte_a_lire": corps.get("texte_a_lire"), "questions": corps.get("questions") or [],
                "priorite": corps.get("priorite") or "normale",
            }, cfga)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        champs["priorite_ordre"] = ag.PRIORITES[champs["priorite"]]
        # Espace propriétaire : celui de la plateforme, sinon l'espace de réception des nouveaux numéros (lot 104.4)
        champs["client_id"] = emetteur.get("client_id") or s.get("wa_espace_reception")
        champs["plateforme"] = {"code": code, "nom": nom_plateforme, "ref": ref}
        doc = ag._nouvel_evenement(champs, par=f"plateforme {nom_plateforme}", maintenant=maintenant, ev_id=fid)
        if existante:   # une fiche terminée existe : elle est remplacée par la nouvelle demande (même identifiant)
            await db[ag.COLLECTION].replace_one({"id": fid}, doc)
        else:
            await db[ag.COLLECTION].insert_one(dict(doc))
        doc.pop("_id", None)
        return {**etat_public(doc), "deja": False}

    @api.post("/webhook/plateforme-appel/etat", tags=["Plateformes — appels Liluvine"])
    async def etat_appel(request: Request):
        """Statut et résultat de l'appel demandé pour une référence (seulement les appels de CETTE plateforme)."""
        emetteur, corps = await _emetteur_signe(request)
        ref = str(corps.get("ref") or "").strip()
        ev = await db[ag.COLLECTION].find_one({"id": id_fiche(emetteur["code"], ref)}, {"_id": 0}) if ref else None
        if not ev:
            raise HTTPException(status_code=404, detail="Aucun appel demandé pour cette référence")
        return etat_public(ev)
