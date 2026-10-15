# Lot 200 — Liluvine remercie un clic de bouton (message_type button / interactive) ; image et vocal restent ignorés.
import asyncio

from mongomock_motor import AsyncMongoMockClient

from routes.liluvine_wa_autoreply import autoreply_to_inbound


def _run(c):
    return asyncio.new_event_loop().run_until_complete(c)


async def _ne_pas_envoyer(*a, **k):
    raise AssertionError("aucun envoi attendu")


def test_image_et_vocal_toujours_ignores():
    db = AsyncMongoMockClient()["t"]
    for t in ("image", "audio"):
        r = _run(autoreply_to_inbound(db, inbound_doc={"message_type": t, "body": "", "phone_digits": "22677001214"},
                                      contact=None, settings_doc={}, wa_send_text=_ne_pas_envoyer))
        assert r == {"ok": False, "reason": "non_text_message"}


def test_bouton_sans_texte_ignore_et_bouton_avec_texte_traite():
    db = AsyncMongoMockClient()["t"]
    # bouton sans libellé : rien à traiter
    r = _run(autoreply_to_inbound(db, inbound_doc={"message_type": "button", "body": "", "phone_digits": "22677001214"},
                                  contact=None, settings_doc={}, wa_send_text=_ne_pas_envoyer))
    assert r["reason"] == "non_text_message"
    # bouton avec libellé : n'est PLUS écarté pour « message non texte » (la suite dépend des réglages)
    r = _run(autoreply_to_inbound(db, inbound_doc={"message_type": "button", "body": "Confirmer", "phone_digits": "22677001214",
                                                   "from": "+22677001214", "client_id": "c1"},
                                  contact=None, settings_doc={}, wa_send_text=lambda *a, **k: asyncio.sleep(0)))
    assert r.get("reason") != "non_text_message"
