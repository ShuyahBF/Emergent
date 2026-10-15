# carrousel_accords_orphelins.py — Lot 204 : accords WhatsApp de personnes SANS fiche, rattachés à un client puis servis.
#
# Constat (15/10/2026) : des personnes ont confirmé (bouton « Confirmer » / mot-clé) alors que leur numéro ne figure sur
# aucune fiche (contact, utilisateur suivi, compte) — elles ont sans doute changé de numéro. Leur accord est bien tracé dans
# le journal `accords_whatsapp_journal` (fiches = 0) mais elles ne reçoivent jamais le carrousel.
#
# Ce module (aucune nouvelle collection) :
#   1. `lister` : accords toujours « orphelins » = dernier accord de la personne, sans retrait ensuite, aucune fiche ne porte
#      aujourd'hui ce numéro (lecture en bloc : une requête par collection) ;
#   2. `fiche_depuis_accord` : fiche contact rattachée à un client choisi dans la liste, qui reprend l'accord TEL QU'IL A ÉTÉ
#      DONNÉ (date et moyen du journal — jamais la date du jour) ;
#   3. `rattacher` : crée les fiches, retire les entrées « contact à enregistrer » et trace le rattachement dans le journal.
# L'envoi du carrousel choisi est fait par la route (carrousel_whatsapp.py), qui ajoute ces personnes à la campagne.
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sawali.carrousel_accords_orphelins")

MAX_LIGNES = 300          # accords orphelins affichés
MAX_RATTACHEMENT = 200    # personnes rattachées par appel


def chiffres(brut: Any) -> str:
    return re.sub(r"\D", "", str(brut or ""))


def fin8(brut: Any) -> str:
    """8 derniers chiffres d'un numéro (clé de rapprochement, quelle que soit la mise en forme)."""
    return chiffres(brut)[-8:]


def fiche_depuis_accord(*, telephone: str, nom: str, client_id: str, accord: Dict[str, Any], par: str) -> Dict[str, Any]:
    """Fiche contact rattachée à `client_id`. L'accord reprend la date et le moyen du journal : c'est la preuve d'origine."""
    d = chiffres(telephone)
    maintenant = datetime.now(timezone.utc).isoformat()
    moyen = accord.get("moyen") or "bouton"
    return {
        "id": str(uuid.uuid4()), "client_id": client_id, "name": (nom or "").strip() or f"+{d}",
        "phone": f"+{d}", "whatsapp": f"+{d}", "phone_digits": d, "wa_profile_name": (nom or "").strip() or None,
        "tags": ["accord-rattache"], "group_ids": [], "shared": False, "source": "accord_rattache",
        "accepte_whatsapp": True, "accepte_whatsapp_le": accord.get("le") or maintenant,
        "accepte_whatsapp_par": f"la personne elle-même ({moyen}) — fiche créée par {par}",
        "accepte_whatsapp_moyen": moyen, "created_at": maintenant, "updated_at": maintenant,
    }


async def _numeros_connus(db) -> set:
    """Fins de numéros (8 chiffres) portés aujourd'hui par une fiche : contacts, utilisateurs suivis, comptes."""
    connus: set = set()
    for coll, champs in ((db.directory_contacts, ("whatsapp", "phone", "phone_digits")),
                         (db.tracked_users, ("whatsapp_number", "phone")),
                         (db.users, ("whatsapp_number", "phone"))):
        async for d in coll.find({}, {"_id": 0, **{c: 1 for c in champs}}):
            for c in champs:
                f = fin8(d.get(c))
                if len(f) == 8:
                    connus.add(f)
    return connus


async def lister(db) -> List[Dict[str, Any]]:
    """Accords orphelins, les plus récents d'abord : [{telephone, nom, le, moyen}]."""
    derniers: Dict[str, Dict[str, Any]] = {}       # fin de numéro → dernière entrée du journal (accord ou retrait)
    async for e in db.accords_whatsapp_journal.find({"tenant_id": None}, {"_id": 0}).sort("le", 1):
        f = fin8(e.get("telephone"))
        if len(f) == 8:
            derniers[f] = e                        # les plus récentes écrasent les plus anciennes
    candidats = {f: e for f, e in derniers.items() if e.get("accepte") and not e.get("fiches")}
    if not candidats:
        return []
    connus = await _numeros_connus(db)
    restants = {f: e for f, e in candidats.items() if f not in connus}
    tels = [e["telephone"] for e in restants.values()]
    noms: Dict[str, str] = {}
    if tels:
        async for p in db.wa_pending_imports.find({"phone_digits": {"$in": tels}}, {"_id": 0, "phone_digits": 1, "wa_profile_name": 1}):
            if p.get("wa_profile_name"):
                noms[fin8(p["phone_digits"])] = p["wa_profile_name"]
        async for m in db.whatsapp_messages.find({"direction": "inbound", "phone_digits": {"$in": tels},
                                                  "from_profile_name": {"$nin": [None, ""]}},
                                                 {"_id": 0, "phone_digits": 1, "from_profile_name": 1}).sort("created_at", 1):
            noms[fin8(m["phone_digits"])] = m["from_profile_name"]      # la plus récente l'emporte
    lignes = [{"telephone": e["telephone"], "nom": noms.get(f, ""), "le": e.get("le"), "moyen": e.get("moyen") or "bouton"}
              for f, e in restants.items()]
    lignes.sort(key=lambda x: x.get("le") or "", reverse=True)
    return lignes[:MAX_LIGNES]


async def rattacher(db, items: List[Dict[str, Any]], clients_valides: Dict[str, str], par: str) -> Dict[str, Any]:
    """Crée une fiche par personne, rattachée au client choisi. `items` = [{telephone, client_id, nom?}] ;
    `clients_valides` = {id → nom} des clients de la liste. Renvoie {crees: [{id, nom, telephone, client_id}], refuses: [...]}."""
    crees: List[Dict[str, Any]] = []
    refuses: List[Dict[str, Any]] = []
    connus = await _numeros_connus(db)
    orphelins = {fin8(o["telephone"]): o for o in await lister(db)}
    for it in items[:MAX_RATTACHEMENT]:
        tel, cid = chiffres(it.get("telephone")), str(it.get("client_id") or "")
        f = fin8(tel)
        if cid not in clients_valides:
            refuses.append({"telephone": tel, "motif": "Choisissez un client de la liste"})
        elif f not in orphelins:
            refuses.append({"telephone": tel, "motif": "Pas d'accord à rattacher pour ce numéro (déjà rattaché, retiré ou inconnu)"})
        elif f in connus:
            refuses.append({"telephone": tel, "motif": "Ce numéro a déjà une fiche"})
        else:
            o = orphelins[f]
            fiche = fiche_depuis_accord(telephone=o["telephone"], nom=(it.get("nom") or o.get("nom") or ""), client_id=cid,
                                        accord={"le": o.get("le"), "moyen": o.get("moyen")}, par=par)
            await db.directory_contacts.insert_one(dict(fiche))
            connus.add(f)
            # Le numéro n'est plus « inconnu » : son entrée « contact à enregistrer » disparaît
            await db.wa_pending_imports.delete_many({"phone_digits": o["telephone"]})
            # Trace du rattachement (le journal des accords n'est jamais modifié : on ajoute une ligne)
            await db.accords_whatsapp_journal.insert_one({
                "telephone": o["telephone"], "accepte": True, "moyen": o.get("moyen"), "numero_recu": None, "tenant_id": None,
                "fiches": 1, "le": datetime.now(timezone.utc).isoformat(), "type": "rattachement",
                "client_id": cid, "contact_id": fiche["id"], "par": par})
            crees.append({"id": fiche["id"], "nom": fiche["name"], "telephone": o["telephone"], "client_id": cid,
                          "client": clients_valides[cid]})
    return {"crees": crees, "refuses": refuses}
