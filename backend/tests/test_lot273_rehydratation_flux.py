"""Lot 273 — réhydratation des fichiers depuis R2 EN FLUX (le serveur Render était tué pour manque de mémoire : 512 Mo).

  - le fichier est copié sur le disque par morceaux : le corps de la réponse n'est JAMAIS lu en une seule fois ;
  - fichier temporaire renommé à la fin : un échec en cours de route ne laisse aucun fichier à moitié écrit ;
  - au plus 2 réhydratations en même temps, même pour une rafale de 10 fichiers ;
  - un fichier déjà revenu n'est pas retéléchargé ; objet absent ou vide → False, comme avant ;
  - la copie de migration (uploads/…) est aussi restaurée en flux.
Aucun réseau : R2 est un bucket en mémoire qui répond comme boto3.
Lancer : cd backend && python -m pytest tests/test_lot273_rehydratation_flux.py -q
"""
import asyncio
import os
import threading
import time

import pytest

import storage

MORCEAU = storage._TAILLE_MORCEAU


class CorpsEnFlux:
    """Corps de réponse S3 : lecture par morceaux obligatoire (une lecture sans taille est refusée)."""

    def __init__(self, octets: bytes, suivi: dict, panne_apres: int = None, delai: float = 0.0):
        self.octets, self.pos, self.suivi, self.panne_apres, self.delai = octets, 0, suivi, panne_apres, delai
        self.ferme = False

    def read(self, taille=None):
        assert taille is not None and taille <= MORCEAU, "lecture du fichier ENTIER en mémoire interdite"
        if self.delai:
            time.sleep(self.delai)
        if self.panne_apres is not None and self.pos >= self.panne_apres:
            raise ConnectionError("coupure réseau")
        bloc = self.octets[self.pos:self.pos + taille]
        self.pos += len(bloc)
        self.suivi["plus_gros_bloc"] = max(self.suivi["plus_gros_bloc"], len(bloc))
        return bloc

    def close(self):
        self.ferme = True


class FauxR2:
    def __init__(self):
        self.objets, self.suivi = {}, {"plus_gros_bloc": 0, "actifs": 0, "max_actifs": 0, "ouvertures": 0}
        self.panne_apres, self.delai = None, 0.0
        self.verrou = threading.Lock()

    def get_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.objets:
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "absent"}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "GetObject")
        with self.verrou:
            self.suivi["ouvertures"] += 1
        corps = CorpsEnFlux(self.objets[Key], self.suivi, self.panne_apres, self.delai)
        outils = self

        class Suivi(CorpsEnFlux):
            pass
        # on compte les téléchargements simultanés entre l'ouverture et la fermeture du corps
        with self.verrou:
            self.suivi["actifs"] += 1
            self.suivi["max_actifs"] = max(self.suivi["max_actifs"], self.suivi["actifs"])
        fermer = corps.close

        def close():
            fermer()
            with outils.verrou:
                outils.suivi["actifs"] -= 1
        corps.close = close
        return {"Body": corps, "ContentType": "video/mp4"}


@pytest.fixture()
def r2(monkeypatch, tmp_path):
    seau = FauxR2()
    for nom in list(os.environ):
        if nom.startswith(("R2_FICHIERS_", "R2_SAUVEGARDES_", "R2_STOCKS_")):
            monkeypatch.delenv(nom)
    monkeypatch.setenv("R2_FICHIERS_BUCKET", "sawali-fichiers")
    monkeypatch.setenv("R2_FICHIERS_PREFIXE", "migration-20261003-190000")
    monkeypatch.setenv("R2_SAUVEGARDES_ACCOUNT_ID", "compte")
    monkeypatch.setenv("R2_SAUVEGARDES_ACCESS_KEY_ID", "cle")
    monkeypatch.setenv("R2_SAUVEGARDES_SECRET_ACCESS_KEY", "secret")
    monkeypatch.delenv("EMERGENT_LLM_KEY", raising=False)
    monkeypatch.setattr(storage, "EMERGENT_KEY", None)
    monkeypatch.setattr(storage, "_storage_key", None)
    monkeypatch.setattr(storage, "_r2_client", None)
    monkeypatch.setattr(storage, "_nouveau_client_r2", lambda cfg: seau)
    storage._missing.clear()
    seau.dossier = tmp_path
    return seau


def cle(chemin):
    return storage.cle_r2_ecriture(chemin)


def test_fichier_copie_par_morceaux_sans_jamais_etre_lu_en_entier(r2):
    contenu = os.urandom(5 * MORCEAU + 1234)                                 # 5,x Mo
    r2.objets[cle("files/video.mp4")] = contenu
    local = r2.dossier / "video.mp4"
    assert storage.rehydrate_from_storage(local_path=local, remote_path="files/video.mp4") is True
    assert local.read_bytes() == contenu and r2.suivi["plus_gros_bloc"] <= MORCEAU
    assert not list(r2.dossier.glob("*.part"))                               # aucun fichier temporaire oublié


def test_echec_en_cours_de_route_ne_laisse_aucun_fichier(r2):
    r2.objets[cle("files/gros.mp4")] = os.urandom(4 * MORCEAU)
    r2.panne_apres = MORCEAU                                                 # coupure après le 1er Mo
    local = r2.dossier / "gros.mp4"
    assert storage.rehydrate_from_storage(local_path=local, remote_path="files/gros.mp4") is False
    assert not local.exists() and not list(r2.dossier.glob("*.part"))
    # le réseau revient (après l'oubli du cache négatif) : le fichier est rapatrié en entier
    storage._missing.clear()
    r2.panne_apres = None
    assert storage.rehydrate_from_storage(local_path=local, remote_path="files/gros.mp4") is True
    assert local.stat().st_size == 4 * MORCEAU


def test_objet_absent_ou_vide_renvoie_faux(r2):
    local = r2.dossier / "x.ogg"
    assert storage.rehydrate_from_storage(local_path=local, remote_path="files/x.ogg") is False and not local.exists()
    r2.objets[cle("files/vide.ogg")] = b""
    vide = r2.dossier / "vide.ogg"
    assert storage.rehydrate_from_storage(local_path=vide, remote_path="files/vide.ogg") is False and not vide.exists()


def test_fichier_deja_revenu_n_est_pas_retelecharge(r2):
    r2.objets[cle("files/a.jpg")] = b"JPEG" * 10
    local = r2.dossier / "a.jpg"
    assert storage.rehydrate_from_storage(local_path=local, remote_path="files/a.jpg") is True
    avant = r2.suivi["ouvertures"]
    assert storage.rehydrate_from_storage(local_path=local, remote_path="files/a.jpg") is True
    assert r2.suivi["ouvertures"] == avant


def test_rafale_de_10_fichiers_deux_telechargements_au_plus_en_meme_temps(r2):
    r2.delai = 0.02                                                          # chaque morceau prend un peu de temps
    for i in range(10):
        r2.objets[cle(f"files/m{i}.mp4")] = os.urandom(3 * MORCEAU)

    async def rafale():
        return await asyncio.gather(*[
            storage.arehydrate_from_storage(local_path=r2.dossier / f"m{i}.mp4", remote_path=f"files/m{i}.mp4") for i in range(10)])
    resultats = asyncio.run(rafale())
    assert all(resultats) and all((r2.dossier / f"m{i}.mp4").stat().st_size == 3 * MORCEAU for i in range(10))
    assert r2.suivi["max_actifs"] <= storage.MAX_REHYDRATATIONS == 2
    assert r2.suivi["max_actifs"] == 2                                       # et on profite bien des 2 voies


def test_meme_fichier_demande_dix_fois_n_est_telecharge_qu_une_fois(r2):
    r2.delai = 0.01
    r2.objets[cle("files/unique.mp4")] = os.urandom(2 * MORCEAU)

    async def rafale():
        return await asyncio.gather(*[
            storage.arehydrate_from_storage(local_path=r2.dossier / "unique.mp4", remote_path="files/unique.mp4") for _ in range(10)])
    assert all(asyncio.run(rafale()))
    assert r2.suivi["ouvertures"] <= 2                                       # les requêtes simultanées partagent le résultat


def test_copie_de_migration_restauree_en_flux(r2, monkeypatch):
    local = r2.dossier / "uploads" / "doc.pdf"
    monkeypatch.setattr(storage, "cles_r2_local", lambda p: ["migration-20261003-190000/uploads/doc.pdf"])
    r2.objets["migration-20261003-190000/uploads/doc.pdf"] = os.urandom(2 * MORCEAU + 7)
    assert storage.restaurer_fichier_local(local) is True
    assert local.stat().st_size == 2 * MORCEAU + 7 and r2.suivi["plus_gros_bloc"] <= MORCEAU
