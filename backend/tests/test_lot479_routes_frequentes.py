"""Lot 479 — routes très fréquentes : clés des postes gardées 10 s, comptage du chat en parallèle, briefing d'accueil gardé 30 s."""
import asyncio

import routes.loois_cles_clients as lc


class _Col:
    """Fausse collection de clés : compte les lectures et les écritures."""
    def __init__(self, fiche): self.fiche = fiche; self.lectures = 0; self.ecritures = 0
    async def find_one(self, *a, **k): self.lectures += 1; return dict(self.fiche) if self.fiche else None
    async def update_one(self, *a, **k): self.ecritures += 1


class _DB:
    def __init__(self, fiche): self.loois_cles_clients = _Col(fiche)


def _cle_valide(monkeypatch):
    monkeypatch.setattr(lc, "empreintes_candidates", lambda cle: ["h"])


def test_une_cle_reconnue_n_interroge_la_base_qu_une_fois_par_fenetre(monkeypatch):
    _cle_valide(monkeypatch)
    lc._CACHE_CLES._valeurs.clear()
    db = _DB({"id": "1", "code": "CMC", "libelle": "CMC", "applications": []})
    cle = lc.PREFIXE_CLE + "abc"

    async def essai():
        return [await lc.identifier_cle(db, cle) for _ in range(5)]
    res = asyncio.run(essai())
    assert all(r["code"] == "CMC" for r in res)
    assert db.loois_cles_clients.lectures == 1            # avant : 5 lectures + 5 écritures conditionnelles


def test_une_cle_inconnue_n_est_jamais_gardee(monkeypatch):
    _cle_valide(monkeypatch)
    lc._CACHE_CLES._valeurs.clear()
    db = _DB(None)
    cle = lc.PREFIXE_CLE + "zzz"

    async def essai():
        return [await lc.identifier_cle(db, cle) for _ in range(3)]
    assert asyncio.run(essai()) == [None, None, None]
    assert db.loois_cles_clients.lectures == 3            # un échec est toujours revérifié (clé nouvelle = valable tout de suite)


def test_la_cle_expire_apres_dix_secondes(monkeypatch):
    _cle_valide(monkeypatch)
    horloge = {"t": 0.0}
    lc._CACHE_CLES._horloge = lambda: horloge["t"]
    lc._CACHE_CLES._valeurs.clear()
    db = _DB({"id": "1", "code": "CMC", "libelle": "CMC", "applications": []})
    cle = lc.PREFIXE_CLE + "exp"

    async def essai():
        await lc.identifier_cle(db, cle)
        horloge["t"] = 11.0                                # clé révoquée entre-temps : relue au bout de 10 s
        await lc.identifier_cle(db, cle)
    asyncio.run(essai())
    lc._CACHE_CLES._horloge = __import__("time").monotonic
    assert db.loois_cles_clients.lectures == 2


def test_le_decompte_du_chat_part_en_parallele():
    src = open("routes/internal_chat.py", encoding="utf-8").read()
    assert "await asyncio.gather(*[_non_lus(c) for c in clients])" in src


def test_le_briefing_est_garde_30_s():
    src = open("server_parts/p19_briefing_accueil.py", encoding="utf-8").read()
    assert "_CACHE_BRIEFING = _CacheCourtBriefing(duree_s=30.0" in src and "_calculer_briefing_accueil" in src
