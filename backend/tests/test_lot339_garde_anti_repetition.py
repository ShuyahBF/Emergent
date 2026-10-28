"""Lot 339 — la liste des pharmacies de garde n'est pas renvoyée (demande devinée) dans les 3 heures ; réglable ; base défaillante = on répond."""
import asyncio
from datetime import datetime, timedelta, timezone

from routes.liluvine_wa_autoreply import garde_deja_envoyee_recemment


class _Messages:
    """Faux accès à db.whatsapp_messages : renvoie un envoi « !garde » à l'heure donnée (ou rien)."""

    def __init__(self, envoye_a=None, panne=False):
        self.envoye_a, self.panne = envoye_a, panne

    async def find_one(self, filtre, projection=None):
        if self.panne:
            raise RuntimeError("base indisponible")
        assert filtre["command"] == "!garde" and filtre["direction"] == "outbound"
        if self.envoye_a is None:
            return None
        return {"_id": 1} if self.envoye_a >= filtre["created_at"]["$gte"] else None


class _Db:
    def __init__(self, **kw):
        self.whatsapp_messages = _Messages(**kw)


def _lancer(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


MAINTENANT = datetime(2026, 10, 28, 17, 3, tzinfo=timezone.utc)


def test_liste_envoyee_il_y_a_une_heure_est_bloquee_par_defaut():
    db = _Db(envoye_a=(MAINTENANT - timedelta(hours=1)).isoformat())
    assert _lancer(garde_deja_envoyee_recemment(db, "22661000000", {}, MAINTENANT)) is True


def test_liste_envoyee_il_y_a_quatre_heures_est_renvoyable():
    db = _Db(envoye_a=(MAINTENANT - timedelta(hours=4)).isoformat())
    assert _lancer(garde_deja_envoyee_recemment(db, "22661000000", {}, MAINTENANT)) is False


def test_delai_reglable_et_desactivable():
    db = _Db(envoye_a=(MAINTENANT - timedelta(hours=4)).isoformat())
    assert _lancer(garde_deja_envoyee_recemment(db, "22661000000", {"garde_reply_anti_repetition_heures": 6}, MAINTENANT)) is True
    db = _Db(envoye_a=(MAINTENANT - timedelta(minutes=5)).isoformat())
    assert _lancer(garde_deja_envoyee_recemment(db, "22661000000", {"garde_reply_anti_repetition_heures": 0}, MAINTENANT)) is False


def test_aucun_envoi_ou_base_en_panne_on_repond():
    assert _lancer(garde_deja_envoyee_recemment(_Db(), "22661000000", {}, MAINTENANT)) is False
    assert _lancer(garde_deja_envoyee_recemment(_Db(panne=True), "22661000000", {}, MAINTENANT)) is False
