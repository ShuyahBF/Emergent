"""Lot 39 — Stock des produits par client et par dépôt (MongoDB, copie Supabase).

Chaque produit est rangé sous le CODE DU CLIENT SAWALI (champ `users.client_code`)
et le CODE DU DÉPÔT (la base HFSQL : « PPH » dans InventaireSélectionné_PPH_…) :
un client a le plus souvent un seul dépôt, qui porte son propre code ; la
clinique Philadelphie (client PHM) en a deux : PPH (pharmacie) et PLB (produits
de laboratoire). La liste des produits d'un pharmacien est TOUJOURS filtrée par
le code de SON client (jamais par un paramètre envoyé par le navigateur).

Clé d'un produit : (code_client, code_depot, code_produit).

Deux sources alimentent la collection `stock_produits` :
  - « pointage » : fin de traitement d'une liste de pointage (OCR sur Pièces),
    chaque ligne du JSON d'inventaire complété ;
  - « loois »    : envoi quotidien du service Loois (stock HFSQL de la pharmacie),
    route POST /api/stock-produits/sync.

    champ du JSON WinDev   →  champ du stock
    Code_Produit           →  code_produit   (repli « CHRONO-<n> » s'il est vide)
    Libellé / Mesure / cip →  libelle / mesure / cip
    ISalle, IMagasin       →  isalle, imagasin, stock = isalle + imagasin
    Peremption1            →  peremption (« AAAAMMJJ », None si vide)
    IPPublic               →  prix_public

Copie Supabase (facultative) : si SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY sont
définies, les mêmes lignes sont envoyées (upsert PostgREST, conflit sur
code_client + code_depot + code_produit) dans la table SUPABASE_STOCK_TABLE
(« stock_produits » par défaut). Sans ces variables : rien n'est envoyé.
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sawali.stock_produits")

CLE_TABLE = "REQ_DétailInventaire"
LOT_SUPABASE = 500          # lignes par requête d'upsert
MOIS_ALERTE = 3             # « périme bientôt » : dans les 3 mois

# Colonnes de la table Supabase (mêmes noms que les documents MongoDB).
COLONNES = ("code_client", "code_depot", "code_produit", "libelle", "mesure", "cip", "prix_public",
            "isalle", "imagasin", "stock", "peremption", "compte", "source", "inventaire", "maj_le")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _entier(v: Any) -> int:
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def _peremption(v: Any) -> Optional[str]:
    """« 20270501 » ou « 2027-05-01 » → « 20270501 » ; vide ou invalide → None."""
    t = re.sub(r"\D", "", str(v or ""))
    return t if re.fullmatch(r"20\d{6}", t) else None


def normaliser(texte: Any) -> str:
    """Libellé sans accents, en majuscules, espaces simples (recherche et rapprochement)."""
    t = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9%,./+ ]", " ", t.upper())).strip()


def cle(code_client: str, code_depot: str, code_produit: str) -> str:
    return f"{code_client}:{code_depot}:{code_produit}"


def document_produit(p: dict, *, code_client: str, code_depot: str, source: str,
                     inventaire: Optional[str] = None, maintenant: Optional[str] = None) -> dict:
    """Un produit (déjà au format du stock) → document MongoDB complet."""
    isalle, imagasin = _entier(p.get("isalle")), _entier(p.get("imagasin"))
    code = str(p.get("code_produit") or "").strip()
    libelle = str(p.get("libelle") or "").strip()
    return {
        "id": cle(code_client, code_depot, code), "code_client": code_client, "code_depot": code_depot,
        "code_produit": code, "libelle": libelle, "libelle_norm": normaliser(libelle),
        "mesure": str(p.get("mesure") or "").strip(), "cip": str(p.get("cip") or "").strip(),
        "prix_public": p.get("prix_public"), "isalle": isalle, "imagasin": imagasin, "stock": isalle + imagasin,
        "peremption": _peremption(p.get("peremption")), "compte": bool(p.get("compte", True)),
        "source": source, "inventaire": inventaire, "maj_le": maintenant or _now(),
    }


def lignes_depuis_inventaire(doc: dict, *, code_client: str, code_depot: str, inventaire: Optional[str],
                             maintenant: Optional[str] = None) -> List[dict]:
    """JSON d'inventaire WinDev (complété) → documents du stock, un par produit.
    `compte` = ligne pointée (Saisie_par renseigné) ; sinon le stock est inconnu."""
    maj = maintenant or _now()
    lignes, vus = [], set()
    for l in doc.get(CLE_TABLE) or []:
        code = str(l.get("Code_Produit") or "").strip() or f"CHRONO-{l.get('Chrono')}"
        if code in vus:
            continue
        vus.add(code)
        lignes.append(document_produit({
            "code_produit": code, "libelle": l.get("Libellé"), "mesure": l.get("Mesure"), "cip": l.get("cip"),
            "prix_public": l.get("IPPublic"), "isalle": l.get("ISalle"), "imagasin": l.get("IMagasin"),
            "peremption": l.get("Peremption1"), "compte": bool(str(l.get("Saisie_par") or "").strip()),
        }, code_client=code_client, code_depot=code_depot, source="pointage", inventaire=inventaire, maintenant=maj))
    return lignes


async def enregistrer_mongo(db, lignes: List[dict]) -> int:
    """Upsert des lignes dans `stock_produits` (clé code_client + code_depot + code_produit)."""
    for l in lignes:
        await db.stock_produits.replace_one(
            {"code_client": l["code_client"], "code_depot": l["code_depot"], "code_produit": l["code_produit"]},
            dict(l), upsert=True)
    return len(lignes)


def supabase_configure() -> bool:
    return bool((os.environ.get("SUPABASE_URL") or "").strip()
                and (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip())


async def miroir_supabase(lignes: List[dict], client=None) -> Dict[str, Any]:
    """Copie des lignes dans Supabase (PostgREST). Ne lève jamais.
    Renvoie {"etat": "ok"|"non_configure"|"erreur", "lignes": n, "erreur"?}."""
    if not supabase_configure():
        return {"etat": "non_configure", "lignes": 0}
    import httpx
    url = os.environ["SUPABASE_URL"].strip().rstrip("/")
    cle_api = os.environ["SUPABASE_SERVICE_ROLE_KEY"].strip()
    table = (os.environ.get("SUPABASE_STOCK_TABLE") or "stock_produits").strip()
    entetes = {"apikey": cle_api, "Authorization": f"Bearer {cle_api}", "Content-Type": "application/json",
               "Prefer": "resolution=merge-duplicates,return=minimal"}
    propre = client is None
    client = client or httpx.AsyncClient(timeout=30)
    envoyees = 0
    try:
        for i in range(0, len(lignes), LOT_SUPABASE):
            lot = [{k: l.get(k) for k in COLONNES} for l in lignes[i:i + LOT_SUPABASE]]
            r = await client.post(f"{url}/rest/v1/{table}",
                                  params={"on_conflict": "code_client,code_depot,code_produit"},
                                  json=lot, headers=entetes)
            if r.status_code >= 300:
                return {"etat": "erreur", "lignes": envoyees, "erreur": f"HTTP {r.status_code} : {r.text[:300]}"}
            envoyees += len(lot)
        return {"etat": "ok", "lignes": envoyees}
    except Exception as exc:  # noqa: BLE001 — réseau, DNS…
        logger.exception("[stock_produits] copie Supabase impossible")
        return {"etat": "erreur", "lignes": envoyees, "erreur": str(exc)}
    finally:
        if propre:
            await client.aclose()


async def enregistrer(db, lignes: List[dict], client=None) -> Dict[str, Any]:
    """MongoDB puis copie Supabase. Renvoie {"mongo": n, "supabase": {...}}."""
    n = await enregistrer_mongo(db, lignes)
    return {"mongo": n, "supabase": await miroir_supabase(lignes, client=client)}


# ---------------------------------------------------------------------------
# Disponibilité et péremption (vérification des ordonnances)
# ---------------------------------------------------------------------------
def alerte_peremption(peremption: Optional[str], aujourd_hui: Optional[date] = None) -> Optional[str]:
    """None, « perime » (mois de péremption passé) ou « proche » (dans les 3 mois)."""
    if not peremption:
        return None
    j = aujourd_hui or date.today()
    ecart = (int(peremption[:4]) - j.year) * 12 + (int(peremption[4:6]) - j.month)
    if ecart < 0:
        return "perime"
    if ecart <= MOIS_ALERTE:
        return "proche"
    return None


def statut_disponibilite(produit: Optional[dict], reserve: int, demande: int) -> str:
    """absent | non_compte | rupture | insuffisant | disponible."""
    if not produit:
        return "absent"
    if not produit.get("compte"):
        return "non_compte"
    dispo = (produit.get("stock") or 0) - reserve
    if dispo <= 0:
        return "rupture"
    if dispo < max(demande, 1):
        return "insuffisant"
    return "disponible"
