"""Lot 475 — préchauffage : l'import lourd part dans un fil, la boucle reste libre, une erreur n'arrête pas le serveur."""
import asyncio
import time

import prechauffage as pc


def test_un_module_inexistant_est_note_sans_exception():
    bilan = pc.importer_modules(["json", "module_qui_n_existe_pas_475"])
    assert bilan[0]["ok"] is True
    assert bilan[1]["ok"] is False and "erreur" in bilan[1]


def test_la_boucle_n_est_pas_bloquee_pendant_le_prechauffage(monkeypatch):
    # Faux import lent (0,5 s) : pendant ce temps la boucle doit continuer de tourner (ticks réguliers).
    monkeypatch.setattr(pc.importlib, "import_module", lambda nom: time.sleep(0.5))

    async def essai():
        tache = asyncio.create_task(pc.prechauffer(["lent"]))
        ticks = 0
        while not tache.done():
            await asyncio.sleep(0.02)
            ticks += 1
        return ticks, await tache
    ticks, bilan = asyncio.run(essai())
    assert bilan[0]["ok"] and ticks >= 10     # un import fait DANS la boucle donnerait 0 à 1 tick


def test_le_module_de_l_agenda_se_prechauffe_vraiment():
    assert "routes.liluvine_agenda" in pc.MODULES_A_PRECHAUFFER


def test_branchement_dans_le_demarrage():
    src = open("server_parts/p17_demarrage_planificateur.py", encoding="utf-8").read()
    assert "from prechauffage import prechauffer" in src and "asyncio.create_task(_prechauffer())" in src
