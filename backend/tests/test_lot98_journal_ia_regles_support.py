"""Lot 98 — journal de consommation de l'IA (tableau de synthèse) et règles des réponses du support :
réponses courtes, 2 questions au plus, abandon sans réponse, pastille de l'assistant, relais vers Claude.
MongoDB simulé ; aucun appel réel à l'IA.
Lancer : cd backend && python -m pytest tests/test_lot98_journal_ia_regles_support.py -q
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import ia_client  # noqa: E402
import routes.journal_ia as ji  # noqa: E402  (pose ia_client.PREFIXES_CONNUS)
from routes import regles_support as rs  # noqa: E402


def _db():
    return mongomock_motor.AsyncMongoMockClient()["sawali_lot98"]


def test_fonction_et_cout():
    f = ia_client.fonction_du_session_id
    assert f("support-loois-1a2b3c4d") == "support-loois"
    assert f("wa:uid42:22670000000") == "wa"
    assert f("gestion-stocks:AMY:complet") == "gestion-stocks"
    assert f("avis-claude-analyse") == "avis-claude-analyse" and f("avis-claude-ab12cd34") == "avis-claude"
    assert f("liluvine-pro-0f8fdc2c-1c2e-4a7a-9d5e-123456789abc") == "liluvine-pro"
    assert f(None) == "autre"
    assert ji.cout_estime("claude-haiku-4-5-20251001", 1_000_000, 1_000_000) == 6.0
    assert ji.cout_estime("claude-sonnet-4-5-20250929", 1_000_000, 0) == 3.0
    assert ji.cout_estime("modele-inconnu", 10, 10) is None


def test_journal_et_synthese():
    db = _db()

    async def scenario():
        notes = []

        async def enregistrer(doc):
            notes.append(doc)
            await db.journal_ia.insert_one(doc)

        ia_client.ENREGISTREUR_USAGE = enregistrer
        try:
            ia_client.noter_usage("support-loois-aa11bb22", "anthropic", "claude-haiku-4-5-20251001", 1000, 200)
            ia_client.noter_usage("support-loois-cc33dd44", "anthropic", "claude-haiku-4-5-20251001", 3000, 800)
            ia_client.noter_usage("avis-claude-analyse", "anthropic", "claude-sonnet-4-5-20250929", 10000, 2000)
            await asyncio.sleep(0.05)
        finally:
            ia_client.ENREGISTREUR_USAGE = None
        # Ancien appel hors période
        await db.journal_ia.insert_one({"le": (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                        "fonction": "agenda", "modele": "claude-haiku-4-5", "entree": 5, "sortie": 5})
        return notes, await ji.synthese(db, 30)

    notes, s = asyncio.run(scenario())
    assert len(notes) == 3
    lignes = {l["fonction"]: l for l in s["lignes"]}
    assert lignes["support-loois"]["appels"] == 2 and lignes["support-loois"]["entree"] == 4000
    assert lignes["support-loois"]["nom"] == "Liluvine — Support Loois" and lignes["support-loois"]["ou"]
    assert lignes["avis-claude-analyse"]["cout"] == round((10000 * 3 + 2000 * 15) / 1e6, 4)
    assert s["lignes"][0]["fonction"] == "avis-claude-analyse"          # tri par coût décroissant
    assert "agenda" not in lignes and any(f["fonction"] == "agenda" for f in s["inutilisees"])
    assert s["total"]["appels"] == 3


def test_pastille_des_assistants():
    db = _db()

    async def scenario():
        await db.settings.insert_one({"_id": "global", "liluvine_agents": [
            {"prenom": "Awa", "specialite": "Secrétaire"}, {"prenom": "Robert", "specialite": "Comptable"},
            {"prenom": "Gaspard", "specialite": "Technicien"}]})
        return (await rs.pastille(db, "Je n'ai pas reçu ma facture", "Voici"),
                await rs.pastille(db, "Bonjour", "Merci", defaut_technique=True),
                await rs.pastille(db, "Bonjour", "Merci"))

    compta, tech, aucun = asyncio.run(scenario())
    assert compta == {"prenom": "Robert", "specialite": "Comptable"}
    assert tech["prenom"] == "Gaspard" and aucun is None
    assert rs.nom_affiche("🤖 Liluvine", compta) == "🤖 Liluvine · Robert (Comptable)"
    assert rs.nom_affiche("🤖 Liluvine", None) == "🤖 Liluvine"


def test_liluvine_passe_la_main_a_claude(monkeypatch):
    """Règle 4 — Liluvine ne sait pas ([CLAUDE]) : Claude répond à sa place, sans lire le code."""
    import routes.support_loois_sessions as ss
    msgs = [{"sender_id": "p1", "text": "Comment exporter mes données en CSV ?", "created_at": "2026-10-10T08:00:00"}]

    async def conv(db, pid, depuis=None, limite=60):
        return msgs

    async def rien(*a, **k):
        return {}

    async def systeme(db, client_doc, question=""):
        return ss.SYSTEME_REPONSE

    vus = {}

    async def liluvine(systeme, texte, modele):
        vus["systeme"] = systeme
        return "[CLAUDE]"

    async def claude(texte):
        vus["claude"] = texte
        return "Ouvrez Paramètres puis « Exporter ». Voulez-vous tous les élèves ou une seule classe ?"

    monkeypatch.setattr(ss, "conversation", conv)
    monkeypatch.setattr(ss, "session_en_cours", rien)
    monkeypatch.setattr(ss, "client_du_poste", rien)
    monkeypatch.setattr(ss, "systeme_liluvine", systeme)
    monkeypatch.setattr(ss, "appeler_ia", liluvine)
    monkeypatch.setattr(ss, "appeler_claude_assistance", claude)
    texte, origine = asyncio.run(ss.reponse_liluvine_detail(None, "p1", en_attente=False))
    assert origine == "claude" and texte.startswith("Ouvrez Paramètres")
    assert "exporter mes données" in vus["claude"]
    # Les règles du propriétaire sont dans les consignes de Liluvine et de Claude
    assert "2 questions d'éclaircissement" in vus["systeme"] and "[CLAUDE]" in vus["systeme"]
    assert "Tu ne lis pas le code" in ss.SYSTEME_ASSISTANCE and "2 ou 3 phrases" in ss.SYSTEME_ASSISTANCE


def test_avis_claude_deux_questions_et_abandon():
    from routes import avis_claude as ac
    avis = ac.normaliser_avis("<avis>" + json.dumps({"verdict": "a_preciser", "questions": ["A ?", "B ?", "C ?"],
                                                      "reponse_client": "Deux questions"}) + "</avis>")
    assert avis["questions"] == ["A ?", "B ?"]
    assert "2 questions" in ac.SYSTEME_ANALYSE and "2 ou 3 phrases" in ac.SYSTEME_ANALYSE
    db = _db()

    async def scenario():
        vieux = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        recent = datetime.now(timezone.utc).isoformat()
        await db.demandes_fonctionnalites.insert_many([
            {"id": "d1", "statut": "a_preciser", "analysee_le": vieux},
            {"id": "d2", "statut": "a_preciser", "analysee_le": recent}])
        n = await ac.abandonner_sans_reponse(db)
        return n, {d["id"]: d["statut"] async for d in db.demandes_fonctionnalites.find({})}

    n, statuts = asyncio.run(scenario())
    assert n == 1 and statuts == {"d1": "abandonnee", "d2": "a_preciser"}
