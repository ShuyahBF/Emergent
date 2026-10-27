# ekol_portail_export.py — EXPORT SERVEUR-À-SERVEUR DES TABLES e-KOL SYNCHRONISÉES VERS LE PORTAIL e-KOL.
#
# Contexte : Loois remonte les tables HFSQL d'e-Kol de chaque école dans SAWALI (lot 68, routes/loois_synchro.py :
# une collection « hf_ekol_<site>_<table> » par école et par table, un document = une ligne HFSQL avec les noms de
# colonnes exacts, plus « _hf_cle » (clé unique) et « _hf_maj » (date de dernière mise à jour)).
# Le PORTAIL e-KOL ÉLÈVES ET PARENTS (plateforme séparée sur Render) a besoin de ces lignes : il les lit ici, par
# pages, toutes les 10 minutes et sur demande depuis son espace école.
#
# En résumé (pour un développeur WinDev) :
#   - UNE route : GET /api/ekol-portail/export?site=<code école>&table=<nom HFSQL>&depuis=<curseur>&limite=<n>
#   - SÉCURITÉ : pas d'utilisateur connecté ; la requête est SIGNÉE par le portail avec la clé partagée
#     EKOL_PORTAIL_HMAC (variable d'environnement, saisie par le propriétaire sur Render, jamais dans Git) :
#       X-Timestamp = horodatage Unix (secondes) ; validité 5 minutes ;
#       X-Signature = HMAC-SHA256(clé, "<horodatage>.<MÉTHODE> <chemin>?<requête>") en hexadécimal,
#       la requête étant la chaîne EXACTE envoyée (« site=…&table=… », encodage compris).
#     Clé absente sur le serveur → 503 (route désactivée) ; signature absente, périmée ou fausse → 401.
#   - PAGINATION PAR CURSEUR : lignes triées par (_hf_maj, _hf_cle) ; « curseur_suivant » = position de la dernière
#     ligne renvoyée (texte opaque) ; le portail le renvoie dans « depuis » pour la page suivante, puis garde le dernier
#     pour ne demander ensuite QUE les lignes modifiées depuis. « nb_documents » (total de la table) permet au
#     portail de détecter des suppressions et de tout relire au besoin.
#   - Table non synchronisée pour ce site : « disponible: false » + message à afficher dans l'espace école
#     (« activer la synchro de la table X dans SAWALI → Loois → Synchro »).
#   - LECTURE SEULE : aucune écriture dans SAWALI ; colonnes binaires (photos, images) jamais renvoyées.
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException, Request

from routes.loois_synchro import code_site, colonnes_binaires, json_sur, nom_collection, table_reference

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
VALIDITE_SECONDES = 300        # une signature vaut 5 minutes (horloges des deux serveurs à l'heure)
LIMITE_DEFAUT = 500            # lignes par page
LIMITE_MAX = 1000              # lignes par page, au plus
# Lot 134 : tables e-Kol lues par le portail (rubrique « 🎓 Portail e-Kol » : lesquelles sont déjà synchronisées)
TABLES_PORTAIL = ("ElèveEdu", "Tuteur", "Elève_Tuteur", "Inscription", "Paiements", "ClassesOffertes", "ClasseEdu",
                  "Ecole", "Session", "Matières", "MatièresClasse", "Examens", "NotesExamens", "BulletinElève",
                  "BulletinElèveClassement", "Bulletin")
APPLICATION = "eKol"           # seules les tables e-Kol sont exportées


# ---------------------------------------------------------------------------
# Signature (logique pure, testée)
# ---------------------------------------------------------------------------
def message_a_signer(horodatage: str, methode: str, chemin: str, requete: str) -> str:
    """Texte signé : « <horodatage>.<MÉTHODE> <chemin>?<requête> » (requête vide → pas de « ? »)."""
    cible = f"{chemin}?{requete}" if requete else chemin
    return f"{horodatage}.{methode.upper()} {cible}"


def calculer_signature(cle: str, horodatage: str, methode: str, chemin: str, requete: str) -> str:
    """HMAC-SHA256 hexadécimal du message (même calcul côté portail)."""
    return hmac.new(cle.encode("utf-8"), message_a_signer(horodatage, methode, chemin, requete).encode("utf-8"),
                    hashlib.sha256).hexdigest()


def requete_du_corps(corps: bytes) -> str:
    """Lot 333 : pour une requête POST, la « requête » signée est l'empreinte SHA-256 du corps (« sha256=<hex> ») : une signature
    interceptée ne peut pas servir à soumettre une AUTRE clé à vérifier."""
    return "sha256=" + hashlib.sha256(corps).hexdigest()


def verifier_signature(cle: str, horodatage: Optional[str], signature: Optional[str], methode: str, chemin: str,
                       requete: str, maintenant: Optional[float] = None) -> bool:
    """Vrai si la signature est correcte ET récente (±5 min). Comparaison à temps constant."""
    if not cle or not horodatage or not signature:
        return False
    try:
        ts = int(horodatage)
    except ValueError:
        return False
    if abs((maintenant if maintenant is not None else time.time()) - ts) > VALIDITE_SECONDES:
        return False
    attendue = calculer_signature(cle, horodatage, methode, chemin, requete)
    return hmac.compare_digest(attendue, signature.strip().lower())


# ---------------------------------------------------------------------------
# Curseur de pagination (texte opaque : base64 d'un petit JSON {m: date ISO, c: clé})
# ---------------------------------------------------------------------------
def coder_curseur(maj: Optional[datetime], cle: str) -> str:
    """Position (date de mise à jour, clé) → texte transmissible dans l'adresse."""
    brut = json.dumps({"m": maj.isoformat() if maj else None, "c": cle}, separators=(",", ":"))
    return base64.urlsafe_b64encode(brut.encode("utf-8")).decode("ascii").rstrip("=")


def decoder_curseur(texte: str) -> Optional[Tuple[Optional[datetime], str]]:
    """Texte du curseur → (date, clé) ; vide → None (début) ; illisible → ValueError (422)."""
    if not texte:
        return None
    try:
        brut = base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4)).decode("utf-8")
        d = json.loads(brut)
        maj = datetime.fromisoformat(d["m"]).replace(tzinfo=None) if d.get("m") else None
        return maj, str(d.get("c") or "")
    except Exception as exc:  # noqa: BLE001 — tout curseur illisible donne la même réponse
        raise ValueError("curseur illisible") from exc


def filtre_apres(curseur: Optional[Tuple[Optional[datetime], str]]) -> Dict[str, Any]:
    """Filtre MongoDB « lignes situées APRÈS le curseur » dans l'ordre (_hf_maj, _hf_cle)."""
    if curseur is None:
        return {}
    maj, cle = curseur
    if maj is None:
        return {"_hf_cle": {"$gt": cle}}
    return {"$or": [{"_hf_maj": {"$gt": maj}}, {"_hf_maj": maj, "_hf_cle": {"$gt": cle}}]}


def _sans_fuseau(valeur: Any) -> Optional[datetime]:
    """Date MongoDB → date sans fuseau (comparaisons homogènes)."""
    return valeur.replace(tzinfo=None) if isinstance(valeur, datetime) else None


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------
def setup_ekol_portail_export_routes(*, db, api, get_current_user=None) -> None:
    """Branche la route d'export sur le routeur /api de SAWALI."""

    # --- Lot 134 : état pour la rubrique des Paramètres (administrateur) ------------------------------------------
    from fastapi import Depends
    if get_current_user is None:   # appel sans dépendance fournie : celle du serveur SAWALI
        from auth import get_current_user

    @api.get("/admin/ekol-portail/etat", tags=["Portail e-Kol"])
    async def etat(user: dict = Depends(get_current_user)):
        """Clé configurée ? et, par école e-Kol, tables utiles au portail déjà synchronisées par Loois."""
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        ecoles: Dict[str, Dict[str, Any]] = {}
        async for t in db.loois_synchro_tables.find({"application": APPLICATION},
                                                    {"_id": 0, "site": 1, "table": 1, "collection": 1,
                                                     "derniere_synchro": 1, "nb_documents": 1}):
            site = t.get("site") or "?"
            nom = t.get("table") or str(t.get("collection") or "").split("_")[-1]
            ecoles.setdefault(site, {})[nom] = {"derniere_synchro": t.get("derniere_synchro"),
                                                "nb_documents": t.get("nb_documents")}
        return {"cle_configuree": bool(os.environ.get("EKOL_PORTAIL_HMAC", "").strip()),
                "tables_utiles": list(TABLES_PORTAIL),
                "ecoles": [{"site": s, "tables": ecoles[s]} for s in sorted(ecoles)]}

    @api.post("/ekol-portail/verifier-cle", tags=["Portail e-Kol"])
    async def verifier_cle(request: Request):
        """Lot 333 — le portail demande à SAWALI si une clé client Loois (« LK-… », celle du support) est valide et à quel client elle
        appartient : le suivi d'utilisation remonté par Loois n'a ainsi besoin d'AUCUNE autre clé que celle déjà saisie sur le poste.
        Signature identique à l'export (EKOL_PORTAIL_HMAC), calculée sur l'empreinte du corps. Réponse :
        {valide, code, libelle, applications} ; clé commune, révoquée ou inconnue → valide=false (jamais le détail).
        Lecture seule : aucune écriture hors la « dernière utilisation » de la clé."""
        cle = os.environ.get("EKOL_PORTAIL_HMAC", "").strip()
        if not cle:
            raise HTTPException(status_code=503, detail="Vérification désactivée : EKOL_PORTAIL_HMAC non configurée.")
        corps = await request.body()
        if len(corps) > 2048 or not verifier_signature(cle, request.headers.get("X-Timestamp"), request.headers.get("X-Signature"),
                                                       request.method, request.url.path, requete_du_corps(corps)):
            raise HTTPException(status_code=401, detail="Signature invalide ou expirée.")
        try:
            cle_loois = str(json.loads(corps or b"{}").get("cle") or "")
        except (ValueError, AttributeError):
            raise HTTPException(status_code=422, detail="Corps JSON attendu : {\"cle\": \"LK-…\"}")
        from routes.loois_cles_clients import identifier_cle
        identite = await identifier_cle(db, cle_loois, machine="portail e-Kol")
        if not identite or identite.get("type") != "client":
            return {"valide": False}
        return {"valide": True, "code": identite["code"], "libelle": identite.get("libelle") or identite["code"],
                "applications": list(identite.get("applications") or [])}

    @api.get("/ekol-portail/export", tags=["Portail e-Kol"])
    async def exporter(request: Request, site: str, table: str, depuis: str = "", limite: int = LIMITE_DEFAUT):
        # --- 1. Signature du portail (clé partagée en variable d'environnement) ---
        cle = os.environ.get("EKOL_PORTAIL_HMAC", "").strip()
        if not cle:
            raise HTTPException(status_code=503, detail="Export e-Kol désactivé : EKOL_PORTAIL_HMAC non configurée.")
        requete = request.scope.get("query_string", b"").decode("latin-1")
        if not verifier_signature(cle, request.headers.get("X-Timestamp"), request.headers.get("X-Signature"),
                                  request.method, request.url.path, requete):
            raise HTTPException(status_code=401, detail="Signature invalide ou expirée.")

        # --- 2. Paramètres : site, table connue du schéma e-Kol, curseur, taille de page ---
        code = code_site(site)
        if not code:
            raise HTTPException(status_code=422, detail="Code du site manquant.")
        ref = table_reference(APPLICATION, table)
        if not ref:
            raise HTTPException(status_code=422, detail=f"Table e-Kol inconnue : {table}.")
        try:
            curseur = decoder_curseur(depuis)
        except ValueError:
            raise HTTPException(status_code=422, detail="Curseur illisible.")
        limite = max(1, min(int(limite or LIMITE_DEFAUT), LIMITE_MAX))

        # --- 3. Table synchronisée pour ce site ? (catalogue de la synchro Loois) ---
        nom = nom_collection(APPLICATION, code, ref["nom"])
        cat = await db.loois_synchro_tables.find_one({"application": APPLICATION, "site": code, "collection": nom},
                                                     {"_id": 0, "derniere_synchro": 1, "nb_documents": 1})
        collection = db[nom]
        # Lot 258 : estimation instantanée (métadonnées) — count_documents({}) parcourait toute la table (420 000 lignes)
        # à CHAQUE page d'export (alerte MongoDB « Query Targeting »)
        total = await collection.estimated_document_count()
        if not cat and total == 0:
            return {"site": code, "table": ref["nom"], "disponible": False, "lignes": [], "curseur_suivant": depuis,
                    "termine": True, "nb_documents": 0,
                    "message": f"Table {ref['nom']} non synchronisée pour ce site : activer la synchro de la table "
                               f"{ref['nom']} dans SAWALI → Plateformes → Loois → Synchro."}

        # --- 4. Page de lignes après le curseur, dans l'ordre (_hf_maj, _hf_cle) ; binaires retirés ---
        exclus = {"_id": 0, **{c: 0 for c in colonnes_binaires(ref.get("colonnes", []))}}
        docs = [d async for d in collection.find(filtre_apres(curseur), exclus)
                .sort([("_hf_maj", 1), ("_hf_cle", 1)]).limit(limite)]
        suivant = depuis
        if docs:
            dernier = docs[-1]
            suivant = coder_curseur(_sans_fuseau(dernier.get("_hf_maj")), str(dernier.get("_hf_cle") or ""))
        return {"site": code, "table": ref["nom"], "disponible": True, "lignes": [json_sur(d) for d in docs],
                "curseur_suivant": suivant, "termine": len(docs) < limite, "nb_documents": total}
