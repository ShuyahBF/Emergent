"""Lot 240 — l'Admin peut lever l'exclusion du samedi et du dimanche pour les seuls carrousels WhatsApp."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import routes.plages_envoi as pe  # noqa: E402

SAMEDI_10H = datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)      # samedi 17/10/2026, 10 h (Ouagadougou = UTC)
CFG = pe.normaliser({"actif": True, "jours": [0, 1, 2, 3, 4], "plages": [{"de": "08:00", "a": "19:00"}]})


def test_exclusion_du_weekend_par_defaut():
    assert CFG["carrousels_weekend"] is False
    assert pe.config_carrousel(CFG) == CFG
    ouverture = pe.prochaine_ouverture(pe.config_carrousel(CFG), SAMEDI_10H)
    assert ouverture is not None and ouverture.weekday() == 0          # attend le lundi


def test_levee_pour_les_carrousels_seulement():
    cfg = pe.normaliser({**CFG, "carrousels_weekend": True})
    assert cfg["carrousels_weekend"] is True and cfg["jours"] == [0, 1, 2, 3, 4]      # réglage commun inchangé
    assert pe.config_carrousel(cfg)["jours"] == [0, 1, 2, 3, 4, 5, 6]
    assert pe.prochaine_ouverture(pe.config_carrousel(cfg), SAMEDI_10H) is None        # carrousel : envoi permis le samedi
    assert pe.prochaine_ouverture(cfg, SAMEDI_10H) is not None                         # sondages / formulaires : toujours attente
    # heures toujours respectées le week-end
    nuit = datetime(2026, 10, 17, 22, 0, tzinfo=timezone.utc)
    assert pe.prochaine_ouverture(pe.config_carrousel(cfg), nuit) is not None
