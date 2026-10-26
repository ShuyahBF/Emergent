"""Lot 314 — « Niveaux de service » : la disponibilité vendue comme un engagement de prise en charge (et non comme un créneau horaire).

Principe (demande du propriétaire, 27/10/2026) : on ne peut pas garantir une heure précise (l'intervention dépend du problème, de
l'environnement du client, de la connexion…). On annonce donc trois NIVEAUX avec un délai de prise en charge :
  - « contrat »  : client sous contrat valide (puce verte du Centre de messagerie) — prise en charge prioritaire, ex. 72 heures maximum ;
  - « standard » : sans contrat — prise en charge selon la charge ;
  - « express »  : prestation payante — intervention immédiate, avec un tarif.
Les réglages (Paramètres → « 📅 Niveaux de service »). Le tarif EXPRESS n'est PAS saisi ici : c'est le « Forfait par intervention » de la fiche du client (0 = à préciser avant l'intervention). sont gardés dans `settings.global.niveaux_service` (aucune nouvelle collection).
La modale « Calendrier » de la discussion en tire une image à envoyer au contact (lib/niveauxImage.js).
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import Body, Depends

DELAIS = ("30 minutes", "1 heure", "2 heures", "4 heures", "Le jour même", "24 heures", "48 heures", "72 heures maximum",
          "Selon disponibilité (sans engagement)", "À convenir à la demande")        # liste déroulante (+ « Autre… »)
NIVEAUX = ("contrat", "standard", "express")
LIBELLES_DEFAUT = {"contrat": "Client sous contrat", "standard": "Client sans contrat", "express": "⚡ EXPRESS"}
DESCRIPTIONS_DEFAUT = {"contrat": "Prise en charge prioritaire (contrat valide)", "standard": "Prise en charge selon ma disponibilité",
                       "express": "Intervention sur demande (prestation payante)"}
MENTION_DEFAUT = "Délais maximum, sous réserve de disponibilité."


def _texte(valeur: Any, longueur: int) -> str:
    return str(valeur or "").strip()[:longueur]


def normaliser_config(brut: Any) -> Dict[str, Any]:
    """Réglages propres : textes bornés, trois niveaux toujours présents. `configure` = actif ET un délai renseigné pour chaque niveau
    (tant que ce n'est pas le cas, l'image n'est pas proposée : jamais d'engagement par défaut)."""
    brut = brut if isinstance(brut, dict) else {}
    niveaux_brut = brut.get("niveaux") if isinstance(brut.get("niveaux"), dict) else {}
    niveaux: Dict[str, Dict[str, Any]] = {}
    for cle in NIVEAUX:
        n = niveaux_brut.get(cle) if isinstance(niveaux_brut.get(cle), dict) else {}
        niveaux[cle] = {"libelle": _texte(n.get("libelle"), 40) or LIBELLES_DEFAUT[cle],
                        "description": _texte(n.get("description"), 80) or DESCRIPTIONS_DEFAUT[cle],
                        "delai": _texte(n.get("delai"), 40)}
    express = niveaux_brut.get("express") if isinstance(niveaux_brut.get("express"), dict) else {}
    niveaux["express"]["afficher_tarif"] = bool(express.get("afficher_tarif"))
    config = {"actif": bool(brut.get("actif")), "societe": _texte(brut.get("societe"), 60),
              "mention": _texte(brut.get("mention"), 120) or MENTION_DEFAUT, "niveaux": niveaux}
    config["configure"] = config["actif"] and all(niveaux[c]["delai"] for c in NIVEAUX)
    return config


def setup_niveaux_service_routes(*, db, api, get_current_user, get_current_admin):
    async def _lire() -> Dict[str, Any]:
        s = await db.settings.find_one({"_id": "global"}, {"niveaux_service": 1}) or {}
        return normaliser_config(s.get("niveaux_service"))

    @api.get("/me/niveaux-service", tags=["Portail Client"])
    async def niveaux_pour_le_portail(user: dict = Depends(get_current_user)):
        """Réglages à jour pour la modale « Calendrier » (textes commerciaux destinés à être envoyés aux contacts)."""
        return await _lire()

    @api.get("/admin/niveaux-service", tags=["Admin — Niveaux de service"])
    async def niveaux_lire(user: dict = Depends(get_current_admin)):
        return {"config": await _lire(), "delais": list(DELAIS)}

    @api.put("/admin/niveaux-service", tags=["Admin — Niveaux de service"])
    async def niveaux_enregistrer(corps: Dict[str, Any] = Body(...), user: dict = Depends(get_current_admin)):
        config = normaliser_config(corps)
        enregistre = {k: v for k, v in config.items() if k != "configure"}
        await db.settings.update_one({"_id": "global"}, {"$set": {"niveaux_service": enregistre}}, upsert=True)
        return {"ok": True, "config": config}
