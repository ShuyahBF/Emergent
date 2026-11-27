"""Lot 474 — réactivité du serveur : retard de la boucle d'événements (un calcul qui la bloque ralentit TOUTES les routes en même temps)."""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import performance_serveur as ps  # noqa: E402


def test_le_resume_du_retard():
    r = ps.RetardBoucle()
    assert r.resume()["retard_moy_ms"] is None and r.resume()["mesures"] == 0
    for ms in (2.0, 4.0, 150.0, 600.0):
        r.noter(ms)
    s = r.resume()
    assert s["mesures"] == 4 and s["retard_moy_ms"] == 189.0 and s["retard_max_ms"] == 600 and s["blocages_100ms"] == 2
    r.reinitialiser()
    assert r.resume()["mesures"] == 0


def test_un_calcul_qui_bloque_la_boucle_est_detecte():
    async def scenario():
        retard = ps.RetardBoucle()
        tache = asyncio.get_running_loop().create_task(ps._surveiller_boucle(retard, pas_s=0.05))
        await asyncio.sleep(0.2)                                  # boucle libre : retard proche de zéro
        calme = retard.resume()["retard_max_ms"]
        time.sleep(0.4)                                           # un calcul SYNCHRONE bloque la boucle 0,4 s (comme une lecture de fichier ou un calcul lourd)
        await asyncio.sleep(0.15)
        tache.cancel()
        return calme, retard.resume()

    calme, apres = asyncio.run(scenario())
    assert calme < 100                                            # sans blocage : pas de retard notable
    assert apres["retard_max_ms"] >= 300 and apres["blocages_100ms"] >= 1      # le blocage de 0,4 s est vu


def test_la_surveillance_ne_demarre_qu_une_fois():
    async def scenario():
        ps._SURVEILLANCE_BOUCLE["tache"] = None
        premier = ps.demarrer_surveillance_boucle(0.05)
        second = ps.demarrer_surveillance_boucle(0.05)
        ps._SURVEILLANCE_BOUCLE["tache"].cancel()
        await asyncio.sleep(0)
        return premier, second

    assert asyncio.run(scenario()) == (True, False)
