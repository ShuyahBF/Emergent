"""Lot 41 — la synthèse quotidienne de Liluvine inclut formulaires, sondages et « !formulaire ».

MongoDB simulé, Liluvine simulée. Lancer : cd backend && python -m pytest tests/test_synthese_formulaires_lot41.py -q
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.synthese as sy  # noqa: E402

JOUR = date(2026, 9, 29)


def test_bloc_formulaires_sondages_dans_la_synthese(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_sy"]
    invites = []

    async def liluvine(db_, prompt):
        invites.append(prompt)
        return "• Activité calme."

    monkeypatch.setattr(sy, "_call_liluvine", liluvine)

    async def go():
        await db.forms.insert_many([{"id": "f1", "title": "Fiche visite"}, {"id": "f2", "title": "Inscription"}])
        await db.wa_surveys.insert_one({"id": "s1", "title": "Satisfaction"})
        await db.form_submissions.insert_many([
            {"form_id": "f1", "created_at": "2026-09-29T08:00:00+00:00"},
            {"form_id": "f1", "created_at": "2026-09-29T09:00:00+00:00"},
            {"form_id": "f2", "created_at": "2026-09-20T09:00:00+00:00", "updated_at": "2026-09-29T10:00:00+00:00"},
            {"form_id": "f2", "created_at": "2026-09-28T09:00:00+00:00"}])                 # veille : exclue
        await db.wa_survey_responses.insert_one({"survey_id": "s1", "created_at": "2026-09-29T11:00:00+00:00"})
        await db.liluvine_formulaires.insert_many([
            {"id": "a", "statut": "publie", "cree_le": "2026-09-29T07:00:00+00:00",
             "publie_le": "2026-09-29T07:30:00+00:00"},
            {"id": "b", "statut": "publie", "mode_realisation": "force", "cree_le": "2026-09-28T07:00:00+00:00",
             "publie_le": "2026-09-29T12:00:00+00:00"},
            {"id": "c", "statut": "en_attente_paiement", "cree_le": "2026-09-29T13:00:00+00:00"},
            {"id": "d", "statut": "erreur", "cree_le": "2026-09-29T14:00:00+00:00"},
            {"id": "e", "statut": "mode_emploi", "cree_le": "2026-09-29T15:00:00+00:00"}])
        return await sy.build_synthese(db, start=JOUR, end=JOUR)

    texte = asyncio.new_event_loop().run_until_complete(go())
    assert texte.startswith("• Activité calme.")
    assert "🟢 Formulaires : 3 soumission(s) reçue(s)" in texte
    assert "   • Fiche visite : 2" in texte and "   • Inscription : 1" in texte
    assert "🔵 Sondages : 1 réponse(s) reçue(s)" in texte and "   • Satisfaction : 1" in texte
    assert ("🤖 !formulaire : 3 reçue(s), mises en ligne 1 AUTO / 1 FORCÉ, 1 en attente de paiement, "
            "1 en erreur") in texte
    # Liluvine reçoit les mêmes chiffres dans son contexte
    assert "🟢 Formulaires : 3 soumission(s)" in invites[0] and "AUTO / FORCÉ" in invites[0]
