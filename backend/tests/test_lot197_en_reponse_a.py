# Lot 197 — la réponse d'un client garde un aperçu du message d'origine ; le relais admin le précise.
import ast
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "server_parts/p12_sms.py").read_text(encoding="utf-8")
FRONT = (Path(__file__).resolve().parents[2] / "frontend/src/pages/portal/Contacts.jsx").read_text(encoding="utf-8")


def test_python_valide():
    ast.parse(SOURCE)


def test_apercu_du_message_d_origine_garde_et_relaye():
    assert 'doc["reply_to_apercu"]' in SOURCE
    assert '{"wa_message_id": quoted_mid}, {"message_id": quoted_mid}' in SOURCE   # envois de modèles : champ message_id
    assert "en réponse à «" in SOURCE                                              # relais à l'admin


def test_conversation_affiche_en_reponse_a():
    assert "En réponse à" in FRONT and "reply_to_apercu" in FRONT
