"""Lot 343 — l'IA laisse la main aux humains : délai de 15 s, pas de conversation humaine en cours (sauf équipe absente)."""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routes import wa_main_humaine as M  # noqa: E402


def test_reglages_par_defaut_et_bornes():
    r = M.reglages_main_humaine({})
    assert r == {"actif": True, "delai": 15, "fenetre_min": 30}
    assert M.reglages_main_humaine({"wa_main_humaine_delai_s": 0})["delai"] == 0          # 0 = immédiat
    assert M.reglages_main_humaine({"wa_main_humaine_delai_s": 9999})["delai"] == M.DELAI_MAX_S
    assert M.reglages_main_humaine({"wa_main_humaine_delai_s": "abc"})["delai"] == 15
    assert M.reglages_main_humaine({"wa_main_humaine_active": False})["actif"] is False


def test_decision_regles_du_proprietaire():
    # 1. un humain a déjà répondu à ce message → l'IA se tait
    assert M.decider(humain_a_repondu=True, conversation_humaine=True, humain_present=True)["ok"] is False
    assert M.decider(humain_a_repondu=True, conversation_humaine=False, humain_present=False)["reason"] == "humain_a_repondu"
    # 2. conversation humaine en cours ET un humain présent → l'IA ne se mêle pas de la conversation
    d = M.decider(humain_a_repondu=False, conversation_humaine=True, humain_present=True)
    assert d == {"ok": False, "reason": "conversation_humaine_en_cours"}
    # 3. conversation humaine mais plus aucun humain présent → l'IA peut répondre
    assert M.decider(humain_a_repondu=False, conversation_humaine=True, humain_present=False)["ok"] is True
    # 4. personne n'a répondu au bout du délai → l'IA répond
    assert M.decider(humain_a_repondu=False, conversation_humaine=False, humain_present=True)["ok"] is True


def test_commandes_jamais_retardees():
    assert M.est_commande("!Garde") and M.est_commande("  /aide") and not M.est_commande("bonjour")


class _Journal:
    def __init__(self):
        self.lignes = []

    async def insert_one(self, d):
        self.lignes.append(d)


class _Db:
    def __init__(self):
        self.liluvine_wa_autoreply_log = _Journal()


def test_reponse_differee_en_arriere_plan_puis_controlee(monkeypatch):
    """La requête n'attend pas (retour immédiat) ; après le délai, le contrôle décide ; le résultat est journalisé."""
    async def scenario():
        db, appels = _Db(), []

        async def executer():
            appels.append("repondu")
            return {"ok": True, "command": "ia"}

        async def controle_oui(*a, **k):
            return {"ok": True, "reason": "personne_n_a_repondu"}

        async def controle_non(*a, **k):
            return {"ok": False, "reason": "humain_a_repondu"}

        doc = {"phone_digits": "22670000000", "body": "Bonjour", "created_at": "2026-10-29T10:00:00+00:00"}
        reglages = {"wa_main_humaine_delai_s": 1}
        # Réponse programmée : retour immédiat, rien d'envoyé tout de suite
        monkeypatch.setattr(M, "controler", controle_oui)
        t0 = time.monotonic()
        r = await M.appliquer(db, inbound_doc=doc, settings_doc=reglages, scope_uid="c1", executer=executer)
        assert time.monotonic() - t0 < 0.5 and r == {"ok": False, "reason": "differe_1s"} and appels == []
        await asyncio.gather(*list(M._TACHES))
        assert appels == ["repondu"] and db.liluvine_wa_autoreply_log.lignes[-1]["ok"] is True
        # Un humain a répondu pendant le délai : l'IA ne répond pas
        monkeypatch.setattr(M, "controler", controle_non)
        await M.appliquer(db, inbound_doc=doc, settings_doc=reglages, scope_uid="c1", executer=executer)
        await asyncio.gather(*list(M._TACHES))
        assert appels == ["repondu"] and db.liluvine_wa_autoreply_log.lignes[-1]["reason"] == "differe_humain_a_repondu"
        # Commande « ! » : réponse immédiate, sans délai
        r = await M.appliquer(db, inbound_doc={**doc, "body": "!Garde"}, settings_doc=reglages, scope_uid="c1", executer=executer)
        assert r["ok"] is True and appels == ["repondu", "repondu"]
        # Réglage coupé : réponse immédiate
        r = await M.appliquer(db, inbound_doc=doc, settings_doc={"wa_main_humaine_active": False}, scope_uid="c1", executer=executer)
        assert r["ok"] is True and len(appels) == 3

    asyncio.run(scenario())
