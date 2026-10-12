# puce_contrat_support.py — Lot 121 : puce CARRÉE « contrat » dans la fenêtre de chat « Support Loois ».
#
# Demande du propriétaire (12/10/2026) : « Je voudrais la même chose sur la fenêtre de chat support quand j'ouvre le
# chat support Loois avec un client. Afficher les infos par rapport au client/tenant auquel appartient l'utilisateur
# en conversation ».
#
# En résumé (pour un développeur WinDev) :
#   - Dans le chat interne, l'espace virtuel « Support Loois » (lot 57.12) contient un FIL par POSTE Loois
#     (identifiant « loois-… », fiche db.support_loois_postes). Chaque demande d'assistance de ce poste est une SESSION
#     (lot 58, db.support_loois_sessions). La puce du lot 120 (vert / orange / rouge, infobulle SANS montant) est
#     affichée devant chaque poste de la liste des conversations et dans l'en-tête de la fenêtre de chat.
#   - LIEN « poste / session → client SAWALI » retenu (fonction pure `client_id_support`, testée), par ordre de
#     fiabilité :
#        1. session.client_id      : le client CHOISI PAR L'AGENT à l'acceptation de la session ; c'est le client du
#                                    ticket créé pour cette conversation (lot 58) → le plus fiable ;
#        2. poste.client_id        : le client retenu pour ce poste (dernière acceptation, association manuelle dans le
#                                    bandeau, lot 58.1, ou à défaut retrouvé par le nom exact de l'école) ;
#        3. session.client_id_suggere : copie du point 2 au moment de la demande (anciens postes) ;
#        4. clé client Loois (lot 68.1) : poste.cle_client_code → fiche active de db.loois_cles_clients → tenant_id
#                                    (compte SAWALI du client, facultatif sur la clé). Ce point arrive en dernier car le
#                                    compte n'est pas toujours renseigné sur la clé.
#     Le compte trouvé est ramené à son COMPTE PRINCIPAL (porteur du contrat) avec IndexComptes du lot 120 : un
#     utilisateur rattaché (parent_client_id / client_id) renvoie au contrat de son client.
#   - Couleurs, infobulle et règles de retard : EXACTEMENT celles du lot 120 (`fiche_contrat`, non dupliquée).
#   - AUCUN MONTANT : les comptes sont lus avec la liste FERMÉE CHAMPS_CLIENT du lot 120 ; les postes, sessions et
#     clés sont lus avec des listes fermées de champs (ci-dessous) qui ne contiennent aucun montant.
#   - DROITS : mêmes que le lot 120 (super-administrateur, comptes du locataire SAWALI, e-mails des domaines internes).
#     Tout autre utilisateur reçoit {actif: false} — rien n'est révélé.
#   - Efficacité : la liste des conversations est servie en UNE requête groupée (POST /support-loois/postes-contrats) ;
#     côté base : une lecture des postes, une des sessions en cours, une des clés (si besoin), et l'index des comptes
#     mémorisé 60 s du lot 120.
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel

from routes.puce_contrat import IndexComptes, est_interne, fiche_contrat

# ---------------------------------------------------------------------------------------------------------------------
# Lot 121 — champs lus (listes FERMÉES : aucun montant ne peut sortir de ces lectures)
# ---------------------------------------------------------------------------------------------------------------------
CHAMPS_POSTE = {"_id": 0, "id": 1, "nom": 1, "ecole": 1, "client_id": 1, "cle_client_code": 1, "cle_client_libelle": 1}
CHAMPS_SESSION = {"_id": 0, "id": 1, "poste_id": 1, "statut": 1, "client_id": 1, "client_id_suggere": 1,
                  "client_nom": 1, "demande_le": 1}
CHAMPS_CLE = {"_id": 0, "code": 1, "tenant_id": 1, "libelle": 1, "client_nom": 1}
MAX_POSTES = 500                                        # plafond d'une requête groupée (protection)


# =====================================================================================================================
# Lot 121 — logique pure (testée : tests/test_puce_contrat_support_lot121.py)
# =====================================================================================================================

def client_id_support(session: Optional[Dict[str, Any]], poste: Optional[Dict[str, Any]],
                      cles_par_code: Optional[Dict[str, Dict[str, Any]]] = None) -> Tuple[Optional[str], str]:
    """Lot 121 — identifiant du compte SAWALI auquel appartient le poste en conversation.

    Renvoie (client_id ou None, critère) — critère : session | poste | session_suggere | cle_client | aucun.
    Ordre de fiabilité expliqué en tête du fichier."""
    session = session or {}
    poste = poste or {}
    # 1. Client choisi par l'agent à l'acceptation (client du ticket de cette conversation)
    if session.get("client_id"):
        return str(session["client_id"]), "session"
    # 2. Client retenu pour le poste (association manuelle ou dernière acceptation)
    if poste.get("client_id"):
        return str(poste["client_id"]), "poste"
    # 3. Client proposé au moment de la demande
    if session.get("client_id_suggere"):
        return str(session["client_id_suggere"]), "session_suggere"
    # 4. Clé client Loois du poste → compte SAWALI renseigné sur la clé
    code = str(poste.get("cle_client_code") or "").strip()
    cle = (cles_par_code or {}).get(code) if code else None
    if cle and cle.get("tenant_id"):
        return str(cle["tenant_id"]), "cle_client"
    return None, "aucun"


def fiche_support(session: Optional[Dict[str, Any]], poste: Optional[Dict[str, Any]],
                  cles_par_code: Dict[str, Dict[str, Any]], index: IndexComptes, aujourdhui,
                  seuil_defaut: int, internes: set, domaines: List[str]) -> Optional[Dict[str, Any]]:
    """Lot 121 — fiche de la puce pour un poste Loois (None = client interne SAWALI : pas de puce).

    Même contenu que la fiche du lot 120, plus :
      relie_par  : critère du lien (voir client_id_support) ;
      client_nom : nom du client à afficher dans l'en-tête (société du compte, sinon libellé de la clé, sinon école)."""
    cid, critere = client_id_support(session, poste, cles_par_code)
    compte = index.par_id.get(cid) if cid else None
    client = index.principal(compte) if compte else None            # compte principal = porteur du contrat
    if client and est_interne(client, internes, domaines):
        return None                                                  # poste de l'équipe SAWALI elle-même
    if client is None:
        critere = "aucun"                                            # identifiant inconnu : aucun client relié
    fiche = fiche_contrat(client, aujourdhui, seuil_defaut)
    cle = cles_par_code.get(str((poste or {}).get("cle_client_code") or "").strip()) or {}
    fiche["relie_par"] = critere
    fiche["client_nom"] = (fiche.get("client") or (session or {}).get("client_nom")
                           or (poste or {}).get("cle_client_libelle") or cle.get("client_nom")
                           or cle.get("libelle") or (poste or {}).get("ecole") or None)
    return fiche


# =====================================================================================================================
# Lot 121 — routes (installées par setup_puce_contrat_routes du lot 120, qui fournit l'index et les droits)
# =====================================================================================================================

class DemandePostes(BaseModel):
    """Corps de POST /support-loois/postes-contrats : identifiants des postes affichés (vide = aucun)."""
    poste_ids: List[str] = []


def installer_routes_support(*, db, api, get_current_user,
                             contexte: Callable[[dict], Awaitable[Optional[Dict[str, Any]]]],
                             index: Callable[[], Awaitable[IndexComptes]]) -> None:
    """Lot 121 — branche les deux routes de la puce du Support Loois.

    `contexte(user)` (fourni par le lot 120) renvoie None si l'utilisateur n'est pas de l'équipe SAWALI, sinon
    {settings, domaines, internes, seuil_defaut} ; `index()` renvoie l'index des comptes mémorisé 60 s."""
    from fastapi import Depends

    async def _cles(postes: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Clés clients ACTIVES des postes (une seule lecture), rangées par code de site."""
        codes = sorted({str(p.get("cle_client_code") or "").strip() for p in postes} - {""})
        if not codes:
            return {}
        cles = await db.loois_cles_clients.find({"code": {"$in": codes}, "actif": True}, CHAMPS_CLE).to_list(len(codes) * 2)
        return {c["code"]: c for c in cles if c.get("code")}

    async def _calculer(postes: List[Dict[str, Any]], sessions_par_poste: Dict[str, Dict[str, Any]],
                        ctx: Dict[str, Any]) -> Dict[str, Optional[Dict[str, Any]]]:
        """Fiche de chaque poste (tout en mémoire après les lectures groupées)."""
        cles = await _cles(postes)
        idx = await index()
        aujourdhui = datetime.now(timezone.utc).date()
        return {p["id"]: fiche_support(sessions_par_poste.get(p["id"]), p, cles, idx, aujourdhui,
                                       ctx["seuil_defaut"], ctx["internes"], ctx["domaines"])
                for p in postes}

    @api.post("/support-loois/postes-contrats", tags=["Chat interne"])
    async def contrats_des_postes(payload: DemandePostes, user: dict = Depends(get_current_user)):
        """Lot 121 — puce « contrat » de chaque poste de la liste des conversations Support Loois, en UNE requête.

        Réponse : {actif, contrats: {poste_id: {etat, couleur, numero, statut_libelle, …, relie_par, client_nom}
        | null}} — null = poste de l'équipe SAWALI (pas de puce). Aucun montant."""
        ctx = await contexte(user)
        if ctx is None:
            return {"actif": False, "contrats": {}}
        ids = [str(i) for i in (payload.poste_ids or [])[:MAX_POSTES] if str(i).startswith("loois-")]
        if not ids:
            return {"actif": True, "contrats": {}}
        postes = await db.support_loois_postes.find({"id": {"$in": ids}}, CHAMPS_POSTE).to_list(len(ids))
        # Sessions EN COURS (attente / active) des postes : une seule lecture ; la plus récente par poste
        sessions: Dict[str, Dict[str, Any]] = {}
        async for s in db.support_loois_sessions.find({"poste_id": {"$in": ids}, "en_cours": True},
                                                      CHAMPS_SESSION).sort("demande_le", -1):
            sessions.setdefault(s.get("poste_id"), s)
        return {"actif": True, "contrats": await _calculer(postes, sessions, ctx)}

    @api.get("/support-loois/sessions/{sid}/contrat", tags=["Chat interne"])
    async def contrat_de_la_session(sid: str, user: dict = Depends(get_current_user)):
        """Lot 121 — puce « contrat » d'UNE session d'assistance (en cours ou terminée) : client de la session.

        Réponse : {actif, poste_id, contrat: {…} | null}. Session inconnue : contrat null."""
        ctx = await contexte(user)
        if ctx is None:
            return {"actif": False, "poste_id": None, "contrat": None}
        session = await db.support_loois_sessions.find_one({"id": sid}, CHAMPS_SESSION)
        if not session:
            return {"actif": True, "poste_id": None, "contrat": None}
        pid = session.get("poste_id")
        poste = await db.support_loois_postes.find_one({"id": pid}, CHAMPS_POSTE) or {"id": pid}
        fiches = await _calculer([poste], {pid: session}, ctx)
        return {"actif": True, "poste_id": pid, "contrat": fiches.get(pid)}
