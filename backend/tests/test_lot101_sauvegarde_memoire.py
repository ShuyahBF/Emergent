"""Lot 101 — la sauvegarde complète (migration_render) ne doit plus dépasser la mémoire du serveur (512 Mo) :
un lot de documents part dès 500 documents OU 4 Mo."""
import os

# db.py lit ces variables à l'import (aucune connexion n'est ouverte)
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot101")

from routes import migration_render as m  # noqa: E402


def test_lot_limite_en_nombre_et_en_octets():
    assert not m.lot_plein(10, 1000)
    assert m.lot_plein(m.LOT, 0)                       # 500 petits documents
    assert m.lot_plein(3, m.LOT_OCTETS)                # quelques gros documents (4 Mo)
    assert m.LOT_OCTETS <= 8 * 1024 * 1024 and m.LOT_LECTURE <= m.LOT


def test_taille_bson():
    petit = {"_id": 1, "a": "x"}
    gros = {"_id": 2, "media": "A" * 2_000_000}
    assert m.taille_bson(petit) < 100
    assert m.taille_bson(gros) > 2_000_000
    # Document non encodable : estimation prudente, jamais d'exception
    assert m.taille_bson({"x": object()}) == 64 * 1024


def test_gros_documents_decoupes():
    """10 documents de 1 Mo : le lot part au 4e document (4 Mo), jamais 10 Mo d'un coup."""
    lots, lot, octets = [], [], 0
    for i in range(10):
        doc = {"_id": i, "media": "B" * 1_048_576}
        lot.append(doc)
        octets += m.taille_bson(doc)
        if m.lot_plein(len(lot), octets):
            lots.append(len(lot))
            lot, octets = [], 0
    if lot:
        lots.append(len(lot))
    assert max(lots) <= 4 and sum(lots) == 10
