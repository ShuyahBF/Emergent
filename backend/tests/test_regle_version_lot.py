"""Règle permanente « version et lot » : /api/version et /api/version-detail
renvoient le numéro de lot déclaré dans backend/lot.py (source unique)."""
import os

import pytest

os.environ.setdefault("DISABLE_SCHEDULER", "1")
os.environ.setdefault("JWT_SECRET", "test")


@pytest.mark.asyncio
async def test_version_contient_le_lot():
    # Le lot affiché à côté de la version vient de backend/lot.py
    import lot
    from server import version
    corps = await version()
    assert corps["lot"] == lot.LOT
    assert corps["lot_libelle"] == lot.LOT_LIBELLE
    assert "." in corps["version"]


@pytest.mark.asyncio
async def test_version_detail_contient_le_lot():
    # Même numéro de lot sur la route détaillée
    import lot
    from server import get_version_detail
    corps = await get_version_detail()
    assert corps["lot"] == lot.LOT
