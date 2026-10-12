# garde_collections_archivees.py — Lot 116 : une collection archivée n'est PAS recréée au démarrage.
#
# Contexte : le cluster Atlas est limité à 500 collections (toutes bases confondues). La rubrique
# « 🧹 Libérer l'Espace » (routes/collections_inutilisees.py) sauvegarde dans R2 puis SUPPRIME des collections
# peu utilisées de la base de SAWALI. Or, au démarrage, SAWALI crée ses index (≈ 140 appels `create_index`
# répartis dans server_parts/p17_demarrage_planificateur.py et une vingtaine de modules) : sur MongoDB, créer un
# index sur une collection absente RECRÉE la collection. Sans garde-fou, chaque redémarrage annulerait la libération.
#
# Choix (expliqué au propriétaire) : un garde-fou CENTRAL plutôt que de modifier les ~140 appels un par un.
#   • `installer()` enveloppe UNE fois, au chargement de db.py, les méthodes `create_index` et `create_indexes`
#     de la classe des collections Motor. Tous les appels existants et FUTURS passent donc par le garde-fou,
#     sans rien changer dans les autres fichiers.
#   • Au premier appel de création d'index sur la base de SAWALI, le garde-fou lit UNE fois le registre
#     db.settings {_id: "collections_archivees"} et la liste des collections présentes. Sont bloquées : les
#     collections du registre qui n'existent PAS dans la base (si une fonction réactivée a de nouveau écrit dedans,
#     la collection existe : ses index sont alors créés normalement — c'est voulu).
#   • Pour une collection bloquée, la création d'index ne fait rien (une ligne au journal) : la collection n'est pas
#     recréée. Une écriture RÉELLE (insert/update) la recréera naturellement : c'est voulu (fonction réactivée).
#   • Sûr : registre absent ou illisible → rien n'est bloqué, le démarrage continue normalement (et la lecture est
#     retentée au prochain appel). Les autres bases (ALBARKA, copies de migration…) ne sont jamais concernées.
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Dict, Iterable, Optional, Set

logger = logging.getLogger("sawali.collections_archivees")

DOC_REGISTRE = "collections_archivees"      # document du registre dans db.settings (aucune nouvelle collection)

# Base surveillée : celle de SAWALI (variable DB_NAME). Remplaçable en test.
_BASES: Dict[str, Optional[str]] = {"sawali": os.environ.get("DB_NAME")}
# Noms bloqués, par base : rempli au premier appel (None = pas encore chargé)
_BLOQUEES: Dict[str, Set[str]] = {}
_VERROU: Dict[str, asyncio.Lock] = {}
_INSTALLE: Dict[type, bool] = {}
_ECHEC: Dict[str, float] = {}              # base → heure du dernier échec de lecture (nouvel essai après 60 s)
DELAI_NOUVEL_ESSAI = 60.0


def base_surveillee() -> Optional[str]:
    """Nom de la base de SAWALI (DB_NAME)."""
    return _BASES.get("sawali")


def definir_base(nom: Optional[str]) -> None:
    """Change la base surveillée et oublie le cache (utilisé par les tests)."""
    _BASES["sawali"] = nom
    _BLOQUEES.clear()
    _ECHEC.clear()


def noms_du_registre(doc: Optional[dict]) -> Set[str]:
    """Noms des collections listées dans le registre (chaque entrée garde son vrai nom dans « nom »)."""
    noms: Set[str] = set()
    for cle, val in (doc or {}).items():
        if cle == "_id" or not isinstance(val, dict):
            continue
        noms.add(str(val.get("nom") or cle))
    return noms


async def charger(db) -> Set[str]:
    """Lit le registre UNE fois et garde les collections archivées ABSENTES de la base. Ne lève jamais."""
    nom_base = db.name
    if nom_base in _BLOQUEES:
        return _BLOQUEES[nom_base]
    # Base injoignable il y a moins de 60 s : on ne relit pas (évite d'ajouter un délai à chaque index)
    if time.monotonic() - _ECHEC.get(nom_base, -DELAI_NOUVEL_ESSAI) < DELAI_NOUVEL_ESSAI:
        return set()
    verrou = _VERROU.setdefault(nom_base, asyncio.Lock())
    async with verrou:
        if nom_base in _BLOQUEES:                       # chargé pendant l'attente du verrou
            return _BLOQUEES[nom_base]
        try:
            doc = await db.settings.find_one({"_id": DOC_REGISTRE})
            archivees = noms_du_registre(doc)
            presentes = set(await db.list_collection_names()) if archivees else set()
            _BLOQUEES[nom_base] = archivees - presentes
            if _BLOQUEES[nom_base]:
                logger.info("[collections-archivees] %d collection(s) archivée(s) non recréée(s) au démarrage : %s",
                            len(_BLOQUEES[nom_base]), ", ".join(sorted(_BLOQUEES[nom_base])[:20]))
        except Exception as exc:  # noqa: BLE001 — registre illisible : on ne bloque rien, on réessaiera
            logger.warning("[collections-archivees] registre illisible (%s) : aucune collection bloquée",
                           type(exc).__name__)
            _ECHEC[nom_base] = time.monotonic()
            return set()
    return _BLOQUEES[nom_base]


def collection_archivee(nom: str, base: Optional[str] = None) -> bool:
    """Vrai si la collection `nom` est archivée (et absente) dans la base de SAWALI — d'après le cache chargé."""
    return nom in _BLOQUEES.get(base or base_surveillee() or "", set())


def noter_archivee(nom: str, base: Optional[str] = None) -> None:
    """Après une suppression (lot 116) : la collection ne sera plus recréée par une création d'index."""
    b = base or base_surveillee()
    # Si le cache n'est pas encore chargé, rien à faire : il lira le registre (qui contient déjà la collection)
    if b and b in _BLOQUEES:
        _BLOQUEES[b].add(nom)


def noter_restauree(nom: str, base: Optional[str] = None) -> None:
    """Avant une restauration : la collection redevient normale (ses index peuvent être recréés)."""
    b = base or base_surveillee()
    if b and b in _BLOQUEES:
        _BLOQUEES[b].discard(nom)


async def _bloquee(collection) -> bool:
    """Vrai si la création d'index doit être ignorée pour cette collection (base de SAWALI seulement)."""
    try:
        base = collection.database
        if not base_surveillee() or base.name != base_surveillee():
            return False
        return collection.name in await charger(base)
    except Exception:  # noqa: BLE001 — le garde-fou ne doit jamais empêcher la création d'un index
        return False


def _envelopper(origine, nom_methode: str):
    """Fabrique la version « gardée » de create_index / create_indexes."""
    async def gardee(self, *args, **kwargs):
        if await _bloquee(self):
            logger.info("[collections-archivees] %s ignoré : collection « %s » archivée (lot 116)",
                        nom_methode, self.name)
            return [] if nom_methode == "create_indexes" else None
        return await origine(self, *args, **kwargs)
    gardee.__name__ = nom_methode
    gardee.__doc__ = f"{nom_methode} avec le garde-fou du lot 116 (collections archivées non recréées)."
    gardee._lot116_origine = origine           # pour pouvoir désinstaller (tests)
    return gardee


def installer(classes: Optional[Iterable[type]] = None) -> None:
    """Enveloppe create_index et create_indexes de la classe des collections Motor (une seule fois)."""
    if classes is None:
        from motor.motor_asyncio import AsyncIOMotorCollection
        classes = [AsyncIOMotorCollection]
    for classe in classes:
        if _INSTALLE.get(classe):
            continue
        for nom_methode in ("create_index", "create_indexes"):
            origine = getattr(classe, nom_methode, None)
            if origine is None or getattr(origine, "_lot116_origine", None):
                continue
            setattr(classe, nom_methode, _envelopper(origine, nom_methode))
        _INSTALLE[classe] = True


def desinstaller(classe: type) -> None:
    """Remet les méthodes d'origine (tests)."""
    for nom_methode in ("create_index", "create_indexes"):
        m = getattr(classe, nom_methode, None)
        if m is not None and getattr(m, "_lot116_origine", None):
            setattr(classe, nom_methode, m._lot116_origine)
    _INSTALLE.pop(classe, None)
