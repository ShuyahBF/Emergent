"""Lot 477 — routes lourdes : traductions en une lecture, comptage rapide de l'état de sauvegarde, comptages plateformes bornés."""
import asyncio
import os

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_lot477")
os.environ.setdefault("JWT_SECRET", "x")


class _Curseur:
    def __init__(self, lignes): self.lignes = list(lignes)
    def __aiter__(self):
        self._it = iter(self.lignes); return self
    async def __anext__(self):
        try: return next(self._it)
        except StopIteration: raise StopAsyncIteration


class _CollectionEspion:
    """Compte les lectures : le jeu de départ doit coûter UNE lecture, pas une par clé."""
    def __init__(self): self.finds = 0; self.find_ones = 0; self.inserts = 0; self.lignes = []
    def find(self, *a, **k): self.finds += 1; return _Curseur(self.lignes)
    async def find_one(self, *a, **k): self.find_ones += 1; return None
    async def insert_one(self, doc): self.inserts += 1
    async def update_one(self, *a, **k): pass


def test_le_jeu_de_depart_des_traductions_se_lit_en_une_requete():
    from fastapi import APIRouter
    import routes.i18n as i18n
    i18n._SEED_VERIFIE["fait"] = False
    col = _CollectionEspion()
    db = type("DB", (), {"i18n_translations": col})()
    api = APIRouter()
    i18n.attach_i18n_routes(api, db=db, get_current_user=lambda: None)
    route = next(r for r in api.routes if r.path == "/i18n/translations")

    async def essai():
        i18n._CACHE_TRADUCTIONS.clear()
        await route.endpoint(lang="fr")
        premier = (col.finds, col.find_ones)
        i18n._CACHE_TRADUCTIONS.clear()
        await route.endpoint(lang="fr")          # cache vidé : seul le dictionnaire est relu, le jeu de départ n'est plus contrôlé
        return premier, (col.finds, col.find_ones)
    premier, second = asyncio.run(essai())
    assert premier[1] == 0                       # plus de find_one par clé (avant : ~190)
    assert premier[0] == 2                       # 1 lecture du jeu de départ + 1 du dictionnaire
    assert second[0] == premier[0] + 1           # 2e appel : le dictionnaire seulement


def test_etat_base_rapide_ne_parcourt_pas_les_documents(monkeypatch):
    import routes.sauvegarde_complete as sc
    appels = {"exact": 0, "estime": 0}

    class Col:
        async def count_documents(self, f): appels["exact"] += 1; return 1
        async def estimated_document_count(self): appels["estime"] += 1; return 1

    class DB:
        def __getitem__(self, nom): return Col()
    monkeypatch.setattr(sc, "db", DB())

    async def noms(): return ["a", "b", "c"]
    monkeypatch.setattr(sc, "_collections", noms)

    asyncio.run(sc.etat_base(rapide=True))
    assert appels == {"exact": 0, "estime": 3}
    asyncio.run(sc.etat_base())                  # l'import « base vide » garde le comptage EXACT
    assert appels["exact"] == 3


def test_comptages_plateformes_bornes_a_8_en_meme_temps():
    import routes.rapport_plateformes as rp
    actifs = {"n": 0, "max": 0}

    class Col:
        async def count_documents(self, f):
            actifs["n"] += 1; actifs["max"] = max(actifs["max"], actifs["n"])
            await asyncio.sleep(0.01); actifs["n"] -= 1; return 1

    class DB:
        def __getitem__(self, nom): return Col()

    async def essai():
        rp._FEU_COMPTAGES = asyncio.Semaphore(8)
        await asyncio.gather(*[rp._compter(DB(), "x", {}) for _ in range(40)])
    asyncio.run(essai())
    assert actifs["max"] <= 8
