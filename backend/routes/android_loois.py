# routes/android_loois.py — Lot 475 : API « Loois mobile » (Android). Logique et requêtes préparées : backend/android_loois.py.
#
# Toutes les routes (sauf l'enregistrement de l'appareil, lot 468) exigent le JETON de l'appareil (« Authorization: Bearer … ») ET un appareil à l'état « Autorisé » avec une zone, une base et
# un client renseignés : l'administrateur peut interdire un appareil à tout moment, l'effet est immédiat.
#   POST /api/android/connexion              identifiant + mot de passe Loois de l'utilisateur → session signée (8 h) + droits
#   GET  /api/android/moi                    session en cours (droits, appareil, zone, base)
#   POST /api/android/caisse/historique      Historique de Caisse : reçus d'un jour (un caissier ne voit que les siens)
#   POST /api/android/caisse/recu            détail d'un reçu : lignes, médecin, validité, date d'expiration, VID, réglé, visé (lot 490)
#   POST /api/android/caisse/recu/recherche  retrouver un reçu par son numéro (complet ou fin du numéro) (lot 490)
#   POST /api/android/corrections/liste      Corrections de reçus : reçus du jour avec le nombre de lignes à corriger
#   GET  /api/admin/android-journal          (administrateur) journal d'audit des actions des appareils
# Les requêtes HFSQL sont exécutées par UNE machine du client (file « SQL à distance ») : la clé « SQL à distance » reste sur SAWALI. Aucune écriture dans la base du client : lecture seule.
# Journal d'audit : qui (utilisateur, appareil), quoi (action, date ou référence), résultat, IP vue par le serveur — jamais de mot de passe ni de montant.
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import jwt
from fastapi import Body, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

import android_loois as al
import appareils_android as aa
import serveurs_locaux as sl
from ip_client import ip_reelle
from routes.liluvine_partage import est_admin

logger = logging.getLogger("sawali.android_loois")

ATTENTE_RESULTAT_S = 40.0            # une requête vers le client doit répondre dans ce délai (lecture : on peut la redemander)
PAS_SONDAGE_S = 0.5
CACHE_REFERENTIEL_S = 600            # validité de la clinique et durées des prestations : gardées 10 minutes par client
ID_JOURNAL = "android_journal"
MAX_JOURNAL = 1000
_cache: Dict[str, Tuple[float, Any]] = {}


def _secret() -> str:
    """Clé de signature des sessions : ANDROID_JWT_SECRET si elle existe, sinon dérivée du secret JWT du serveur (empreinte de 64 caractères)."""
    return hashlib.sha256((os.environ.get("ANDROID_JWT_SECRET") or (os.environ.get("JWT_SECRET", "fallback-insecure") + "-android")).encode()).hexdigest()


class DemandeConnexion(BaseModel):
    login: str = Field(min_length=1, max_length=40)
    mot_de_passe: str = Field(min_length=1, max_length=80)


class DemandeJour(BaseModel):
    date: str = ""                                   # AAAA-MM-JJ ; vide = aujourd'hui
    caissier: str = Field(default="", max_length=40)  # administrateur / laboratoire seulement


class DemandeRecu(BaseModel):
    reference: str = Field(min_length=3, max_length=60)


class DemandeRecherche(BaseModel):
    numero: str = Field(min_length=1, max_length=30)        # lot 490 : « R-202630889 », « 202630889 » ou la fin du numéro


def setup_android_loois_routes(*, db, api, get_current_user) -> None:
    def _interne() -> Dict[str, Any]:
        from routes.loois_sql_distant import INTERNE        # fonctions internes de la file « SQL à distance » (lot 458)
        if not INTERNE:
            raise HTTPException(status_code=503, detail="Service SQL à distance indisponible.")
        return INTERNE

    # ------------------------------------------------------------------------------------------------------------------ accès : appareil puis session
    async def _appareil(request: Request, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
        fiche = await aa.trouver_par_jeton(db, (authorization or "").removeprefix("Bearer ").strip())
        if fiche is None:
            raise HTTPException(status_code=401, detail="Appareil non reconnu : enregistrez-le de nouveau.")
        if fiche.get("etat") != "autorise":
            raise HTTPException(status_code=403, detail="Accès interdit : cet appareil n'est pas autorisé par l'administrateur SAWALI.")
        if not (fiche.get("zone") and fiche.get("client_code")):
            raise HTTPException(status_code=403, detail="Appareil incomplet : l'administrateur doit renseigner sa zone et son code client.")
        fiche["_ip"] = ip_reelle(request)
        return fiche

    async def _session(appareil: Dict[str, Any] = Depends(_appareil), x_session: Optional[str] = Header(default=None)) -> Dict[str, Any]:
        # Session signée avec une clé dérivée du SECRET DU CLIENT (lot 480) : la même session est valable sur la passerelle locale de Loois, sans Internet
        secret = await sl.secret_client(db, appareil["client_code"])
        s = sl.lire_session(secret, x_session or "") if secret else None
        if s is None:
            raise HTTPException(status_code=401, detail="Session expirée : reconnectez-vous.")
        if s.get("aid") != appareil["id"]:
            raise HTTPException(status_code=401, detail="Session d'un autre appareil : reconnectez-vous.")
        return {**s, "appareil": appareil}

    # ------------------------------------------------------------------------------------------------------------------ journal d'audit
    async def _journal(appareil: Dict[str, Any], login: str, action: str, detail: str, resultat: str) -> None:
        """Une ligne d'audit (jamais de mot de passe). Ne casse jamais l'appel."""
        try:
            await db.settings.update_one({"_id": ID_JOURNAL}, {"$push": {"lignes": {"$each": [{
                "quand": datetime.now(timezone.utc).isoformat(), "appareil": appareil["id"], "utilisateur_appareil": appareil.get("nom_utilisateur") or "", "login": login,
                "action": action, "detail": (detail or "")[:120], "resultat": resultat, "ip": appareil.get("_ip", ""), "zone": appareil.get("zone", ""), "client": appareil.get("client_code", "")}],
                "$slice": -MAX_JOURNAL}}}, upsert=True)
        except Exception:  # noqa: BLE001
            logger.warning("[android] journal d'audit non écrit", exc_info=True)

    # ------------------------------------------------------------------------------------------------------------------ exécution chez le client
    async def _executer(appareil: Dict[str, Any], sql: str, tolerant: bool = False) -> Dict[str, Any]:
        """Dépose la requête (lecture éphémère), attend sa fin, rend la vue. Erreurs : 503 client hors ligne, 504 délai, 502 erreur HFSQL (sauf `tolerant` : vue vide)."""
        interne = _interne()
        code = appareil["client_code"]
        try:
            vue = await interne["creer"]({"client": code, "sql": sql, "ephemere": True}, appareil.get("_ip", ""), f"Android {appareil['id']}")
        except HTTPException:
            raise
        debut = time.monotonic()
        while time.monotonic() - debut < ATTENTE_RESULTAT_S:
            etat = await interne["detail"](vue["id"])
            if etat.get("etat") in ("terminee", "echec", "expiree", "sans_reponse"):
                if etat.get("etat") == "terminee" and etat.get("ok"):
                    return etat
                if tolerant:
                    return {"lignes": [], "colonnes": [], "ok": False}
                raise HTTPException(status_code=502, detail=(etat.get("message") or "Le client n'a pas pu exécuter la lecture.")[:300])
            await asyncio.sleep(PAS_SONDAGE_S)
        if tolerant:
            return {"lignes": [], "colonnes": [], "ok": False}
        raise HTTPException(status_code=504, detail="Le serveur du client ne répond pas (aucune machine du client n'a traité la demande). Réessayez.")

    async def _client_en_ligne(appareil: Dict[str, Any]) -> None:
        """Refuse tout de suite (503) quand aucune machine du client n'est en ligne : inutile d'attendre 40 secondes."""
        liste = (await _interne()["clients"]()).get("clients") or []
        fiche = next((c for c in liste if c.get("code") == appareil["client_code"]), None)
        if not (fiche and fiche.get("en_ligne")):
            raise HTTPException(status_code=503, detail=f"Aucune machine du client {appareil['client_code']} n'est en ligne : son service Windows Loois doit être allumé.")

    async def _referentiel(appareil: Dict[str, Any]) -> Tuple[Optional[int], Dict[str, int]]:
        """(validité de la clinique, durées propres des prestations), gardés 10 minutes par client (règle 7 : on ne relit pas à chaque ouverture)."""
        cle = appareil["client_code"]
        t = time.monotonic()
        if cle in _cache and _cache[cle][0] > t:
            return _cache[cle][1]
        clinique, prestations = await asyncio.gather(_executer(appareil, al.sql_validite_clinique(), tolerant=True), _executer(appareil, al.sql_prestations(), tolerant=True))
        valeur = (al.lire_validite_clinique(clinique.get("lignes") or []), al.lire_prestations(prestations.get("lignes") or []))
        if clinique.get("ok") is not False and prestations.get("ok") is not False:
            _cache[cle] = (t + CACHE_REFERENTIEL_S, valeur)
        return valeur

    async def _masquer_plus_tard(requete_id: str, masque: str) -> None:
        """Remplace le texte d'une requête de connexion par une version sans mot de passe, dès qu'elle est terminée (tâche de fond : ne bloque jamais la réponse)."""
        interne = _interne()
        fin = time.monotonic() + 35 * 60
        while time.monotonic() < fin:
            try:
                etat = await interne["detail"](requete_id)
            except Exception:  # noqa: BLE001
                return
            if etat.get("etat") in ("terminee", "echec", "expiree", "sans_reponse"):
                await db.loois_reglages.update_one({"id": "sql_distant", "requetes.id": requete_id}, {"$set": {"requetes.$.sql": masque}})
                return
            await asyncio.sleep(5)

    # ------------------------------------------------------------------------------------------------------------------ connexion de l'utilisateur
    @api.post("/android/connexion", tags=["Loois mobile (Android)"])
    async def connexion(corps: DemandeConnexion, appareil: Dict[str, Any] = Depends(_appareil)):
        espace = al.espace_de_la_zone(appareil["zone"])
        if espace is None:
            await _journal(appareil, corps.login, "connexion", "zone non prise en charge", "refuse")
            raise HTTPException(status_code=422, detail="Cette zone n'est pas encore prise en charge par Loois mobile (Biolog et Aizenta le sont).")
        if not al.login_valide(corps.login):
            raise HTTPException(status_code=422, detail="Identifiant invalide.")
        cle = al.cle_essais(appareil["id"], corps.login)
        if al.essais_restants(cle) <= 0:
            await _journal(appareil, corps.login, "connexion", "trop d'essais", "refuse")
            raise HTTPException(status_code=429, detail="Trop de mots de passe faux : réessayez dans 15 minutes.")
        await _client_en_ligne(appareil)
        interne = _interne()
        masque = al.masquer_sql_connexion(espace, corps.login)
        sql = al.sql_authentifier(espace, corps.login, corps.mot_de_passe)
        try:
            vue = await _executer_connexion(appareil, sql, masque)
        except HTTPException as e:
            await _journal(appareil, corps.login, "connexion", f"erreur {e.status_code}", "erreur")
            raise
        lignes = vue.get("lignes") or []
        if not lignes:
            al.noter_echec(cle)
            await _journal(appareil, corps.login, "connexion", "identifiants refusés", "refuse")
            raise HTTPException(status_code=401, detail=f"Identifiant ou mot de passe incorrect ({al.essais_restants(cle)} essai(s) restant(s)).")
        al.effacer_echecs(cle)
        login = str(lignes[0][0]).strip() or corps.login
        autoriser = al.vrai(lignes[0][1]) if espace["autoriser"] and len(lignes[0]) > 1 else False
        return await _emettre(appareil, espace, login, autoriser, "réussie")

    async def _emettre(appareil: Dict[str, Any], espace: Dict[str, Any], login: str, autoriser: bool, detail: str) -> Dict[str, Any]:
        """Ouvre la session d'un utilisateur DÉJÀ authentifié (mot de passe vérifié, ou connexion rapide du lot 484) : groupe, droits, jeton signé."""
        q_groupe, q_suppr = al.sql_colonne_utilisateur(espace, "groupe", login), al.sql_colonne_utilisateur(espace, "supprimer", login)
        groupe_v, suppr_v = await asyncio.gather(_executer(appareil, q_groupe, tolerant=True) if q_groupe else _vide(), _executer(appareil, q_suppr, tolerant=True) if q_suppr else _vide())
        groupe = str((groupe_v.get("lignes") or [[""]])[0][0] or "").strip()
        peut_supprimer = al.vrai((suppr_v.get("lignes") or [[""]])[0][0])
        d = al.droits(espace, login, groupe, autoriser, peut_supprimer, profil=appareil.get("profil") or "agent")
        secret = await sl.secret_client(db, appareil["client_code"], creer=True)
        session = sl.creer_session(secret, appareil["id"], login, groupe, d)
        await _journal(appareil, login, "connexion", detail, "ok")
        return {"session": session, "expire_dans_s": sl.SESSION_TTL_H * 3600, "utilisateur": {"login": login, "groupe": groupe, "espace": espace["nom"]}, "droits": d,
                "appareil": {"zone": appareil["zone"], "base": appareil.get("base", ""), "client": appareil["client_code"]}}

    async def _vide() -> Dict[str, Any]:
        return {"lignes": []}

    async def _executer_connexion(appareil: Dict[str, Any], sql: str, masque: str) -> Dict[str, Any]:
        """Comme `_executer`, mais le texte (mot de passe compris) est remplacé dans l'historique de la file DÈS que la requête est terminée."""
        interne = _interne()
        vue = await interne["creer"]({"client": appareil["client_code"], "sql": sql, "ephemere": True}, appareil.get("_ip", ""), f"Android {appareil['id']} (connexion)")
        asyncio.get_event_loop().create_task(_masquer_plus_tard(vue["id"], masque))
        debut = time.monotonic()
        while time.monotonic() - debut < ATTENTE_RESULTAT_S:
            etat = await interne["detail"](vue["id"])
            if etat.get("etat") in ("terminee", "echec", "expiree", "sans_reponse"):
                if etat.get("etat") == "terminee" and etat.get("ok"):
                    return etat
                raise HTTPException(status_code=502, detail="La vérification de l'identifiant a échoué chez le client. Réessayez.")
            await asyncio.sleep(PAS_SONDAGE_S)
        raise HTTPException(status_code=504, detail="Le serveur du client ne répond pas. Réessayez.")

    @api.get("/android/moi", tags=["Loois mobile (Android)"])
    async def moi(s: Dict[str, Any] = Depends(_session)):
        a = s["appareil"]
        return {"login": s["login"], "groupe": s.get("groupe", ""), "droits": s["d"], "appareil": {"zone": a["zone"], "base": a.get("base", ""), "client": a["client_code"], "nom": a.get("nom_utilisateur", "")}}

    # ------------------------------------------------------------------------------------------------------------------ Historique de Caisse
    def _jour(corps: DemandeJour) -> Any:
        if not corps.date:
            return datetime.now(timezone.utc).date()
        j = al.jour_valide(corps.date)
        if j is None:
            raise HTTPException(status_code=422, detail="Date invalide : AAAA-MM-JJ.")
        return j

    def _caissier(s: Dict[str, Any], corps: DemandeJour) -> Optional[str]:
        """Login dont on lit les reçus : le caissier connecté (toujours le sien), sauf administrateur / laboratoire (tous, ou le caissier demandé)."""
        if not s["d"].get("caisse"):
            raise HTTPException(status_code=403, detail="La caisse n'est pas disponible pour cette zone.")
        if s["d"].get("voir_tous_les_recus"):
            if corps.caissier.strip():
                if not al.login_valide(corps.caissier.strip()):
                    raise HTTPException(status_code=422, detail="Caissier invalide.")
                return corps.caissier.strip().upper()
            return None
        return s["login"].upper()

    async def _recus_du_jour(s: Dict[str, Any], corps: DemandeJour) -> Tuple[List[Dict[str, Any]], bool, Any]:
        jour, caissier = _jour(corps), _caissier(s, corps)
        await _client_en_ligne(s["appareil"])
        vue = await _executer(s["appareil"], al.sql_recus_du_jour(jour, caissier))
        recus = al.lire_recus(vue.get("lignes") or [])
        tronque = len(recus) > al.MAX_RECUS or bool(vue.get("tronque"))
        return recus[:al.MAX_RECUS], tronque, jour

    @api.post("/android/caisse/historique", tags=["Loois mobile (Android)"])
    async def historique(corps: DemandeJour = Body(default_factory=DemandeJour), s: Dict[str, Any] = Depends(_session)):
        recus, tronque, jour = await _recus_du_jour(s, corps)
        await _journal(s["appareil"], s["login"], "historique_caisse", f"{jour} {corps.caissier}".strip(), "ok")
        return {"date": jour.isoformat(), "nombre": len(recus), "total_montant": round(sum(r["montant"] for r in recus), 2), "tronque": tronque, "recus": recus,
                "portee": "tous les caissiers" if s["d"].get("voir_tous_les_recus") and not corps.caissier.strip() else (corps.caissier.strip().upper() or s["login"].upper())}

    @api.post("/android/caisse/recu", tags=["Loois mobile (Android)"])
    async def detail_recu(corps: DemandeRecu, s: Dict[str, Any] = Depends(_session)):
        if not s["d"].get("caisse"):
            raise HTTPException(status_code=403, detail="La caisse n'est pas disponible pour cette zone.")
        reference = corps.reference.strip()
        if not al.reference_valide(reference):
            raise HTTPException(status_code=422, detail="Référence de reçu invalide (« R-… »).")
        a = s["appareil"]
        await _client_en_ligne(a)
        entete, lignes, (clinique, prestations), infos_v = await asyncio.gather(_executer(a, al.sql_entete_recu(reference)), _executer(a, al.sql_lignes_recu(reference)), _referentiel(a),
                                                                                  _executer(a, al.sql_infos_recu(reference), tolerant=True))      # lot 490 : VID, réglé, visé (lecture tolérante)
        recus = al.lire_recus(entete.get("lignes") or [])
        if not recus:
            raise HTTPException(status_code=404, detail="Reçu introuvable.")
        recu = recus[0]
        if not s["d"].get("voir_tous_les_recus") and recu["caissier"].strip().upper() != s["login"].upper():
            await _journal(a, s["login"], "detail_recu", reference, "refuse")
            raise HTTPException(status_code=403, detail="Ce reçu appartient à un autre caissier.")
        brutes = lignes.get("lignes") or []
        codes = sorted({str(l[0]).strip() for l in brutes if l and str(l[0]).strip()})
        ids = sorted({str(l[1]).strip() for l in brutes if len(l) > 1 and str(l[1]).strip()})
        q_des, q_med = al.sql_designations(codes), al.sql_medecins(ids)
        des_v, med_v = await asyncio.gather(_executer(a, q_des, tolerant=True) if q_des else _vide(), _executer(a, q_med, tolerant=True) if q_med else _vide())
        designations = {str(l[0]).strip(): str(l[1]).strip() for l in (des_v.get("lignes") or []) if len(l) > 1}
        medecins = {str(l[0]).strip(): " ".join(x for x in (str(l[1]).strip(), str(l[2]).strip() if len(l) > 2 else "") if x) for l in (med_v.get("lignes") or [])}
        details = al.lire_lignes_recu(brutes, designations, medecins, prestations, clinique, al.date_vente(recu["date_heure_iso"].replace("T", " ")))
        await _journal(a, s["login"], "detail_recu", reference, "ok")
        return {"recu": recu, "lignes": details, "total": round(sum(l["montant"] for l in details), 2), "validite_clinique": clinique, "a_corriger": any(l["necessite_correction"] for l in details),
                "infos": al.lire_infos_recu(infos_v.get("lignes") or [])}

    @api.post("/android/caisse/recu/recherche", tags=["Loois mobile (Android)"])
    async def recherche_recu(corps: DemandeRecherche, s: Dict[str, Any] = Depends(_session)):
        """Lot 490 — retrouver un reçu par son numéro (complet ou fin du numéro). Un caissier ne retrouve que SES reçus ; l'ouverture se fait ensuite par /android/caisse/recu."""
        if not s["d"].get("caisse"):
            raise HTTPException(status_code=403, detail="La caisse n'est pas disponible pour cette zone.")
        n = al.numero_recherche(corps.numero)
        if n is None:
            raise HTTPException(status_code=422, detail="Tapez le numéro du reçu : « R-202630889 », « 202630889 » ou la fin du numéro (3 chiffres au moins).")
        a = s["appareil"]
        await _client_en_ligne(a)
        vue = await _executer(a, al.sql_recherche_recu(n["chiffres"]))
        recus = al.lire_recus(vue.get("lignes") or [])
        if not s["d"].get("voir_tous_les_recus"):
            recus = [r for r in recus if r["caissier"].strip().upper() == s["login"].upper()]
        # Un numéro EXACT passe en premier : « 30889 » peut aussi finir d'autres numéros plus anciens
        recus.sort(key=lambda r: r["reference"].upper() != n["reference"].upper())
        await _journal(a, s["login"], "recherche_recu", n["reference"], "ok" if recus else "introuvable")
        return {"numero": n["reference"], "nombre": len(recus), "recus": recus}

    # ------------------------------------------------------------------------------------------------------------------ Corrections de reçus (lecture seule)
    @api.post("/android/corrections/liste", tags=["Loois mobile (Android)"])
    async def corrections(corps: DemandeJour = Body(default_factory=DemandeJour), s: Dict[str, Any] = Depends(_session)):
        if not s["d"].get("corrections"):
            await _journal(s["appareil"], s["login"], "corrections", "droit absent", "refuse")
            raise HTTPException(status_code=403, detail="Votre compte n'a pas le droit de corriger les reçus (AutoriserCorrectionReçu).")
        recus, tronque, jour = await _recus_du_jour(s, corps)
        a = s["appareil"]
        refs = [r["reference"] for r in recus if al.reference_valide(r["reference"])]
        morceaux = [refs[i:i + al.MAX_REFERENCES_PAR_REQUETE] for i in range(0, len(refs), al.MAX_REFERENCES_PAR_REQUETE)]
        (clinique, prestations), *domaines_v = await asyncio.gather(_referentiel(a), *[_executer(a, al.sql_domaines(m)) for m in morceaux])
        domaines = [l for v in domaines_v for l in (v.get("lignes") or [])]
        enrichis = al.recus_a_corriger(recus, domaines, prestations, clinique)
        await _journal(a, s["login"], "corrections", f"{jour}", "ok")
        a_corriger = [r for r in enrichis if r["a_corriger"]]
        return {"date": jour.isoformat(), "nombre": len(enrichis), "nombre_a_corriger": len(a_corriger), "validite_clinique": clinique, "consultation_seule": bool(s["d"].get("consultation_seule")),
                "tronque": tronque, "recus": sorted(enrichis, key=lambda r: (not r["a_corriger"], r["date_heure_iso"]), reverse=False)}

    # ------------------------------------------------------------------------------------------------------------------ Tableau de bord de suivi (lot 483)
    cache_tdb: Dict[str, Tuple[float, Any]] = {}

    def _droit_tdb(s: Dict[str, Any]) -> None:
        if not s["d"].get("tableau_de_bord"):
            raise HTTPException(status_code=403, detail="Le tableau de bord est réservé à l'administrateur et aux téléphones « client ».")

    async def _gardee(cle: str, duree_s: float, calcul):
        """Résultat gardé quelques instants (règle 7) : plusieurs ouvertures du tableau de bord ne relancent pas les mêmes totaux."""
        t = time.monotonic()
        if cle in cache_tdb and cache_tdb[cle][0] > t:
            return cache_tdb[cle][1]
        valeur = await calcul()
        cache_tdb[cle] = (t + duree_s, valeur)
        return valeur

    @api.post("/android/tableau-de-bord", tags=["Loois mobile (Android)"])
    async def tableau_de_bord(corps: DemandeJour = Body(default_factory=DemandeJour), s: Dict[str, Any] = Depends(_session)):
        """Un jour : nombre de reçus, montant, panier moyen et détail par caissier (totaux calculés par la base)."""
        _droit_tdb(s)
        jour = _jour(corps)
        a = s["appareil"]
        await _client_en_ligne(a)
        vue = await _gardee(f"{a['client_code']}|jour|{jour}", 60, lambda: _executer(a, al.sql_agregat_par_caissier(jour)))
        par_caissier = al.lire_par_caissier(vue.get("lignes") or [])
        nombre_recus, total = sum(c["nombre"] for c in par_caissier), round(sum(c["montant"] for c in par_caissier), 2)
        await _journal(a, s["login"], "tableau_de_bord", str(jour), "ok")
        return {"date": jour.isoformat(), "nombre": nombre_recus, "total_montant": total, "panier_moyen": round(total / nombre_recus, 2) if nombre_recus else 0.0, "par_caissier": par_caissier}

    @api.post("/android/tableau-de-bord/semaine", tags=["Loois mobile (Android)"])
    async def tableau_de_bord_semaine(corps: DemandeJour = Body(default_factory=DemandeJour), s: Dict[str, Any] = Depends(_session)):
        """Les 7 derniers jours jusqu'à la date donnée : une ligne par jour (nombre, montant) — chargée à part pour ne pas retarder le tableau du jour."""
        _droit_tdb(s)
        fin = _jour(corps)
        a = s["appareil"]
        await _client_en_ligne(a)
        jours = [fin - timedelta(days=i) for i in range(6, -1, -1)]

        async def calcul():
            vues = await asyncio.gather(*[_executer(a, al.sql_agregat_jour(j)) for j in jours])
            return [{"date": j.isoformat(), "nombre": n, "montant": m} for j, (n, m) in zip(jours, [al.lire_agregat_jour(v.get("lignes") or []) for v in vues])]
        semaine = await _gardee(f"{a['client_code']}|semaine|{fin}", 120, calcul)
        await _journal(a, s["login"], "tableau_de_bord_semaine", str(fin), "ok")
        return {"fin": fin.isoformat(), "jours": semaine, "total_montant": round(sum(j["montant"] for j in semaine), 2), "nombre": sum(j["nombre"] for j in semaine)}

    # ------------------------------------------------------------------------------------------------------------------ journal (administrateur)
    @api.get("/admin/android-journal", tags=["Loois mobile (Android)"])
    async def journal_admin(limite: int = 200, user: dict = Depends(get_current_user)):
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        fiche = await db.settings.find_one({"_id": ID_JOURNAL}) or {}
        lignes = list(reversed(fiche.get("lignes") or []))[:max(1, min(limite, MAX_JOURNAL))]
        return {"lignes": lignes, "total": len(fiche.get("lignes") or [])}

    # ------------------------------------------------------------------------------------------------------------------ connexion rapide (lot 484)
    from routes.connexion_rapide import attacher_connexion_rapide
    attacher_connexion_rapide(db=db, api=api, get_current_user=get_current_user, appareil_dep=_appareil, session_dep=_session, journal=_journal,
                              emettre=_emettre, executer=_executer, interne=_interne)
