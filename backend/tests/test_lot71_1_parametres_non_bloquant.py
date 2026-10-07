"""Lot 71.1 — la première ouverture des Paramètres ne fige plus le serveur.

1. Le client Qdrant (import lourd de qdrant_client la première fois) est créé HORS de la boucle principale.
2. Aucun appel direct à `_make_client` ne reste dans une fonction async.
3. La sentinelle écrit dans les journaux la ligne de code qui bloque la boucle.
"""
import asyncio
import logging
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RACINE = Path(__file__).resolve().parents[1]


async def _pire_retard(coro):
    """Exécute `coro` en mesurant le plus grand retard de la boucle pendant ce temps."""
    pire, arret = 0.0, asyncio.Event()

    async def sonde():
        nonlocal pire
        t = time.perf_counter()
        while not arret.is_set():
            await asyncio.sleep(0.01)
            n = time.perf_counter()
            pire = max(pire, n - t - 0.01)
            t = n

    tache = asyncio.create_task(sonde())
    resultat = await coro
    arret.set()
    await tache
    return resultat, pire


def test_client_qdrant_cree_hors_de_la_boucle(monkeypatch):
    # Création lente simulée (1 s, comme l'import de qdrant_client) : la boucle doit rester libre
    import routes.qdrant_rag as q
    q._CLIENTS.clear()
    faux = object()

    def lent(url, key):
        time.sleep(1.0)
        return faux

    monkeypatch.setattr(q, "_make_client", lent)
    client, retard = asyncio.run(_pire_retard(q._client_pret("https://x", "k")))
    assert client is faux
    assert retard < 0.3, f"boucle figée {retard:.2f} s"


def test_client_deja_pret_rendu_tout_de_suite():
    # Client déjà créé : rendu sans passer par un fil
    import routes.qdrant_rag as q
    faux = object()
    q._CLIENTS[("https://y", "k")] = faux
    assert asyncio.run(q._client_pret("https://y", "k")) is faux
    q._CLIENTS.clear()


def test_plus_aucun_make_client_direct_dans_une_fonction_async():
    # Toute fonction async doit passer par `await _client_pret(...)`
    for fichier in ("routes/qdrant_rag.py", "routes/vidal_rag.py"):
        texte = (RACINE / fichier).read_text(encoding="utf-8")
        assert not re.search(r"=\s*_make_client\(", texte), f"appel bloquant restant dans {fichier}"


def test_sentinelle_signale_le_code_qui_bloque(caplog):
    # Un time.sleep de 2 s dans la boucle : la sentinelle écrit la pile (avec le nom de la fonction fautive)
    import sentinelle_boucle as s
    s._etat["demarree"] = False

    def fonction_qui_bloque():
        time.sleep(2.0)

    async def scenario():
        s.demarrer()
        await asyncio.sleep(0.3)
        fonction_qui_bloque()
        await asyncio.sleep(0.6)   # la sentinelle constate la reprise

    with caplog.at_level(logging.WARNING, logger="sawali.sentinelle"):
        asyncio.run(scenario())
    textes = "\n".join(r.getMessage() for r in caplog.records)
    assert "[boucle-bloquee] serveur figé" in textes
    assert "fonction_qui_bloque" in textes
    assert "a repris après" in textes


def test_lot71_2_sdk_ia_importe_hors_de_la_boucle(monkeypatch):
    # Lot 71.2 — import lent simulé (1 s) d'un SDK d'IA : la boucle doit rester libre
    import ia_client

    def import_lent(nom):
        time.sleep(1.0)

    monkeypatch.setattr(ia_client.importlib, "import_module", import_lent)
    ia_client._SDK_PRETS.discard("anthropic")
    _, retard = asyncio.run(_pire_retard(ia_client._sdk_pret("anthropic")))
    assert retard < 0.3, f"boucle figée {retard:.2f} s"
    assert "anthropic" in ia_client._SDK_PRETS
    # Deuxième appel : immédiat (déjà prêt)
    t = time.perf_counter()
    asyncio.run(ia_client._sdk_pret("anthropic"))
    assert time.perf_counter() - t < 0.05


def test_lot71_3_sentinelle_garde_les_derniers_blocages():
    # Lot 71.3 — rubrique « ⚡ Santé du serveur » : heure, durée et ligne de code SAWALI en cause
    import sentinelle_boucle as s
    s._etat["demarree"] = False
    s._BLOCAGES.clear()

    def code_sawali_lent():
        time.sleep(2.0)

    async def scenario():
        s.demarrer()
        await asyncio.sleep(0.3)
        code_sawali_lent()
        await asyncio.sleep(0.6)

    asyncio.run(scenario())
    e = s.etat()
    assert e["active"] is True and e["seuil_s"] == s.SEUIL_S
    assert len(e["blocages"]) == 1
    b = e["blocages"][0]
    assert b["duree_s"] and b["duree_s"] >= 1.5
    assert "test_lot71_1_parametres_non_bloquant.py" in b["lieu"]
