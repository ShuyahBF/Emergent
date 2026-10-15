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
from datetime import datetime, timedelta, timezone
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


# ---------------------------------------------------------------------------------------------------------------------
# Lot 206 — clics sur un bouton (« Confirmer »…) reçus MAIS jamais transformés en accord (ex. les réponses du matin du
# 15/10/2026 : le webhook ne reconnaissait que les boutons à identifiant « accord_wa:… »). Rattrapage en UN clic, au lieu
# de chercher chaque contact à la main : la personne a cliqué, l'administrateur contrôle la liste et la valide.
# ---------------------------------------------------------------------------------------------------------------------
JOURS_CLICS = 45          # clics relus (les plus récents d'abord) ; au-delà, l'accord se redemande


async def _fiches_par_numero(db, fins: set) -> Dict[str, List[Dict[str, Any]]]:
    """{fin de numéro → fiches qui le portent} : contacts, utilisateurs suivis, comptes (une lecture par collection)."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for coll, nom_champ, champs in (("directory_contacts", "name", ("whatsapp", "phone", "phone_digits")),
                                    ("tracked_users", "name", ("whatsapp_number", "phone")),
                                    ("users", "full_name", ("whatsapp_number", "phone"))):
        proj = {"_id": 0, "id": 1, "client_id": 1, "accepte_whatsapp": 1, nom_champ: 1, **{c: 1 for c in champs}}
        async for d in db[coll].find({}, proj):
            for f in {fin8(d.get(c)) for c in champs}:
                if f in fins:
                    out.setdefault(f, []).append({"coll": coll, "id": d.get("id"), "nom": d.get(nom_champ) or "",
                                                  "client_id": d.get("client_id"), "accepte": bool(d.get("accepte_whatsapp")),
                                                  "numero": next((d[c] for c in champs if d.get(c)), "")})
    return out


async def clics_a_valider(db) -> List[Dict[str, Any]]:
    """Personnes dont le DERNIER clic sur un bouton positif n'a donné aucun accord : [{telephone, nom, le, texte, fiches,
    sans_fiche}]. Exclues : clic suivi d'une décision enregistrée (accord ou retrait), fiches déjà toutes en accord."""
    from routes.accord_whatsapp import sens_bouton
    depuis = (datetime.now(timezone.utc) - timedelta(days=JOURS_CLICS)).isoformat()
    clics: Dict[str, Dict[str, Any]] = {}
    async for m in db.whatsapp_messages.find(
            {"direction": "inbound", "message_type": "button", "created_at": {"$gte": depuis}},
            {"_id": 0, "phone_digits": 1, "body": 1, "created_at": 1, "received_at": 1, "from_profile_name": 1}).sort("created_at", 1):
        f = fin8(m.get("phone_digits"))
        if len(f) == 8:
            clics[f] = {"telephone": chiffres(m.get("phone_digits")), "texte": m.get("body") or "", "sens": sens_bouton(m.get("body")),
                        "le": m.get("received_at") or m.get("created_at"), "profil": m.get("from_profile_name") or ""}
    clics = {f: c for f, c in clics.items() if c["sens"] is True}      # le dernier clic est positif
    if not clics:
        return []
    decisions: Dict[str, str] = {}
    async for e in db.accords_whatsapp_journal.find({"tenant_id": None}, {"_id": 0, "telephone": 1, "le": 1}):
        f = fin8(e.get("telephone"))
        if f in clics and (e.get("le") or "") > decisions.get(f, ""):
            decisions[f] = e["le"]
    restants = {f: c for f, c in clics.items() if (decisions.get(f) or "") < (c["le"] or "")}
    fiches = await _fiches_par_numero(db, set(restants))
    lignes = []
    for f, c in restants.items():
        fs = fiches.get(f, [])
        if fs and all(x["accepte"] for x in fs):
            continue
        lignes.append({"telephone": c["telephone"], "nom": (fs[0]["nom"] if fs else "") or c["profil"], "le": c["le"],
                       "texte": c["texte"], "fiches": [{"id": x["id"], "coll": x["coll"], "nom": x["nom"]} for x in fs],
                       "sans_fiche": not fs})
    lignes.sort(key=lambda x: x.get("le") or "", reverse=True)
    return lignes[:MAX_LIGNES]


async def valider_clics(db, telephones: List[str], par: str) -> Dict[str, Any]:
    """Note l'accord (date du clic, moyen « bouton ») sur TOUTES les fiches portant le numéro des personnes choisies et trace
    la validation dans le journal. Les personnes sans fiche rejoignent la liste « accords sans fiche ». Renvoie
    {valides: [{telephone, nom, fiche: {id, nom, telephone}|None}], ignores}."""
    voulus = {fin8(t) for t in telephones if len(fin8(t)) == 8}
    candidats = {fin8(c["telephone"]): c for c in await clics_a_valider(db)}
    valides, ignores = [], 0
    for f in voulus:
        c = candidats.get(f)
        if not c:
            ignores += 1
            continue
        moyen = f"bouton « {c['texte']} »"
        maj = {"accepte_whatsapp": True, "accepte_whatsapp_le": c["le"], "accepte_whatsapp_moyen": moyen,
               "accepte_whatsapp_par": f"la personne elle-même ({moyen}) — validé par {par}"}
        fiches = await _fiches_par_numero(db, {f})
        n = 0
        for x in fiches.get(f, []):
            r = await db[x["coll"]].update_one({"id": x["id"]}, {"$set": maj})
            n += r.modified_count
        await db.accords_whatsapp_journal.insert_one({
            "telephone": c["telephone"], "accepte": True, "moyen": "bouton", "numero_recu": None, "tenant_id": None,
            "fiches": n, "le": c["le"], "type": "validation_clic", "par": par,
            "note_le": datetime.now(timezone.utc).isoformat()})
        # Une fiche suffit pour l'envoi : contact de l'annuaire d'abord, puis utilisateur suivi, puis compte
        ordre = {"directory_contacts": 0, "tracked_users": 1, "users": 2}
        choisie = sorted(fiches.get(f, []), key=lambda x: ordre[x["coll"]])[:1]
        valides.append({"telephone": c["telephone"], "nom": c["nom"],
                        "fiche": ({"id": choisie[0]["id"], "nom": choisie[0]["nom"], "telephone": choisie[0]["numero"] or c["telephone"]}
                                  if choisie else None)})
    return {"valides": valides, "ignores": ignores}
