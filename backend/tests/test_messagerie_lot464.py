"""Lot 464 — Centre de Messagerie : la pastille de la barre latérale ne compte plus les messages non lus d'un contact BLOQUÉ (il a disparu de la liste) ;
bloquer un numéro marque ses non-lus comme lus. Réutilise l'environnement du lot 23 (fonctions extraites de server.py, Mongo simulé)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_messaging_center_lot23 import USER, env  # noqa: E402,F401 — fixture réutilisée

import liste_noire_wa as lnw  # noqa: E402


def _bloquer_sans_toucher_aux_messages(env, cle):
    """Simule un blocage fait AVANT ce lot : l'entrée existe, les messages restent non lus."""
    env.run(env.db.settings.update_one({"_id": lnw.ID_FICHE}, {"$set": {"entrees": [{"cle": cle, "numero": "+226" + cle}]}}, upsert=True))
    lnw.vider_cache()


def test_les_non_lus_d_un_contact_bloque_ne_comptent_plus(env):
    avant = env.run(env.ns["_wa_unread_summary"](USER))
    assert avant["by_contact"] == {"c-awa": 2, "c-ben": 1} and avant["total"] == 3
    _bloquer_sans_toucher_aux_messages(env, "70111111")                                     # Awa est bloquée
    apres = env.run(env.ns["_wa_unread_summary"](USER))
    assert apres["by_contact"] == {"c-ben": 1} and apres["total"] == 1 and apres["blocked"] == 2
    lnw.vider_cache()


def test_bloquer_marque_les_non_lus_comme_lus(env):
    lnw.vider_cache()
    env.run(lnw.bloquer(env.db, "+226 70 11 11 11", nom="Awa"))
    lus = env.run(env.db.whatsapp_messages.count_documents({"direction": "inbound", "phone_digits": "22670111111", "read_by_us_at": None}))
    assert lus == 0                                                                       # plus aucun non-lu pour ce numéro
    autre = env.run(env.db.whatsapp_messages.count_documents({"direction": "inbound", "phone_digits": "22670222222", "read_by_us_at": None}))
    assert autre == 1                                                                     # les autres contacts ne sont pas touchés
    assert env.run(env.ns["_wa_unread_summary"](USER))["total"] == 1
    lnw.vider_cache()
