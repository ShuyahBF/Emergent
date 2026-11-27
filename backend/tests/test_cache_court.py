"""Lot 473 — petit cache à durée de vie courte (compteurs de la barre latérale, diagnostics d'administration, modèles WhatsApp)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cache_court import CacheCourt  # noqa: E402


class Horloge:
    """Horloge factice : le temps n'avance que quand on le décide (aucune attente réelle)."""
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


def test_une_valeur_fraiche_est_rendue_puis_expire():
    h = Horloge(); c = CacheCourt(duree_s=45, horloge=h)
    assert c.lire("u|admin") is None                       # rien en cache : l'appelant calcule
    assert c.ecrire("u|admin", {"a": 1}) == {"a": 1}       # ecrire rend la valeur (pratique)
    h.t += 44.9
    assert c.lire("u|admin") == {"a": 1}                   # encore fraîche : aucune requête à la base
    h.t += 0.2
    assert c.lire("u|admin") is None and len(c) == 0       # expirée : retirée, on recalcule


def test_invalider_par_prefixe_ne_touche_que_cet_utilisateur():
    c = CacheCourt(duree_s=45, horloge=Horloge())
    c.ecrire("u1|admin", 1); c.ecrire("u1|client", 2); c.ecrire("u2|admin", 3)
    assert c.invalider("u1|") == 2                         # « marquer comme vu » de u1 : ses compteurs tombent tout de suite
    assert c.lire("u1|admin") is None and c.lire("u2|admin") == 3
    assert c.invalider() == 1 and len(c) == 0              # sans préfixe : tout


def test_taille_bornee_la_plus_ancienne_est_retiree():
    h = Horloge(); c = CacheCourt(duree_s=999, max_entrees=3, horloge=h)
    for i, cle in enumerate(["a", "b", "c"]):
        h.t += 1; c.ecrire(cle, i)
    h.t += 1; c.ecrire("d", 3)                              # 4e entrée : « a » (la plus ancienne) disparaît
    assert c.lire("a") is None and [c.lire(x) for x in "bcd"] == [1, 2, 3] and len(c) == 3
    h.t += 1; c.ecrire("b", 99)                             # réécrire une clé existante ne retire rien
    assert len(c) == 3 and c.lire("b") == 99


def test_une_valeur_vide_ou_nulle_est_bien_mise_en_cache():
    c = CacheCourt(duree_s=45, horloge=Horloge())
    c.ecrire("zero", 0); c.ecrire("vide", {})
    assert c.lire("zero") == 0 and c.lire("vide") == {}     # 0 et {} sont des valeurs, pas des « absents » (seul None signifie « pas en cache »)


# ---------------------------------------------------------------------------------------------------------------------------------------
# Lot 474 — cache d'objets (fichiers du stockage externe) à budget de mémoire borné
# ---------------------------------------------------------------------------------------------------------------------------------------
from cache_court import CacheOctets  # noqa: E402


def test_cache_d_objets_garde_les_petits_et_refuse_les_gros():
    h = Horloge(); c = CacheOctets(duree_s=600, max_total=100, max_objet=40, horloge=h)
    assert c.ecrire("petit", b"x" * 30, "image/png") is True
    assert c.lire("petit") == (b"x" * 30, "image/png")
    assert c.ecrire("gros", b"x" * 41, "image/png") is False            # plus gros que la limite par objet : jamais gardé
    assert c.lire("gros") is None and c.total == 30


def test_cache_d_objets_respecte_le_budget_total_en_retirant_les_plus_anciens():
    h = Horloge(); c = CacheOctets(duree_s=600, max_total=100, max_objet=60, horloge=h)
    for cle in ("a", "b", "c"):
        h.t += 1; assert c.ecrire(cle, b"x" * 40, "t")                   # a (40) + b (40) = 80 ; c (40) ne tient pas : a est retiré
    assert c.lire("a") is None and c.lire("b") is not None and c.lire("c") is not None
    assert c.total == 80 <= 100


def test_cache_d_objets_expire_et_se_vide():
    h = Horloge(); c = CacheOctets(duree_s=600, max_total=1000, max_objet=500, horloge=h)
    c.ecrire("x", b"abc", "t")
    h.t += 599; assert c.lire("x") is not None
    h.t += 2; assert c.lire("x") is None and c.total == 0                # expiré : retiré, la mémoire est rendue
    c.ecrire("y", b"abc", "t"); c.invalider()
    assert len(c) == 0 and c.total == 0


def test_reecrire_la_meme_cle_ne_double_pas_la_memoire():
    c = CacheOctets(duree_s=600, max_total=100, max_objet=60, horloge=Horloge())
    c.ecrire("k", b"x" * 50, "t"); c.ecrire("k", b"y" * 30, "t")
    assert c.total == 30 and c.lire("k") == (b"y" * 30, "t")
