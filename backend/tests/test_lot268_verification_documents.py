"""Lot 268 — authenticité des documents : chiffrement du jeton, lecture en clair, refus des jetons falsifiés."""
import os
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot268")
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from routes import verification_documents as vd


def _paire():
    p = vd._nouvelle_paire()
    privee = X25519PrivateKey.from_private_bytes(vd._debase64(vd.dechiffrer(p["cle_privee"])))
    return p["cle_publique"], privee


def test_aller_retour_et_contenu_en_clair():
    pub, privee = _paire()
    jeton = vd.sceller(pub, "ALB-GUIDE|20261020|EX0001|p12")
    assert len(jeton) < 130                                   # assez court pour un petit QR code
    assert "ALB-GUIDE" not in jeton                            # rien de lisible dans le lien
    texte = vd.ouvrir(privee, jeton)
    assert texte == "ALB-GUIDE|20261020|EX0001|p12"
    c = vd.lire_contenu(texte)
    assert c["titre"] == "Guide de prise en main ALBARKA" and c["version"] == "20 octobre 2026"
    assert c["droits"].startswith("© 2026, 2027, 2028") and c["exemplaire"] == "EX0001" and c["page"] == "12"


def test_jeton_modifie_ou_autre_cle_refuse():
    pub, privee = _paire()
    jeton = vd.sceller(pub, "ALB-GUIDE|20261020|EX0001|p1")
    modifie = jeton[:-2] + ("AA" if not jeton.endswith("AA") else "BB")
    assert vd.ouvrir(privee, modifie) is None                  # contenu altéré
    assert vd.ouvrir(privee, "n'importe quoi") is None
    _, autre = _paire()
    assert vd.ouvrir(autre, jeton) is None                     # chiffré pour une autre clé
    assert vd.ouvrir(privee, "") is None


def test_code_inconnu():
    assert vd.lire_contenu("XXX|20261020|EX1|p1")["titre"] == "Document non répertorié"
