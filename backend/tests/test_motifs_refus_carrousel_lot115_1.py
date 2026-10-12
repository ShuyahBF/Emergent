"""Lot 115.1 — motif du refus Meta des modèles de carrousel, par nombre de cartes."""
from routes.carrousel_whatsapp import motifs_depuis_liste


def test_motifs_seulement_pour_les_modeles_refuses():
    modeles = [
        {"name": "swl_2", "language": "fr", "status": "REJECTED", "rejected_reason": "INVALID_FORMAT"},
        {"name": "swl_3", "language": "fr", "status": "APPROVED", "rejected_reason": "NONE"},
        {"name": "swl_4", "language": "fr", "status": "REJECTED"},                       # motif absent
        {"name": "swl_5", "language": "en", "status": "REJECTED", "rejected_reason": "SCAM"},   # autre langue
        {"name": "autre_2", "language": "fr", "status": "REJECTED", "rejected_reason": "SCAM"},  # autre préfixe
    ]
    m = motifs_depuis_liste("swl", "fr", modeles)
    assert set(m) == {2, 4}
    assert m[2]["code"] == "INVALID_FORMAT" and "format" in m[2]["libelle"]
    assert m[4]["code"] == "NONE"
