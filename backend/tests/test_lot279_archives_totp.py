"""Lot 279 — application d'authentification (TOTP, Authenticator…) pour ouvrir les archives d'auRor.
Fonctions pures vérifiées avec les vecteurs officiels de la RFC 6238 ; parcours complet avec le harnais du lot 227.
Lancer : cd backend && python -m pytest tests/test_lot279_archives_totp.py -q
"""
from __future__ import annotations

import base64
import time

import archives_totp as T
from tests.test_lot227_formules_plateformes import SEL, VERIF, arch, env, U  # noqa: F401  (fixture « env »)

PREUVE = "P" * 43 + "="
AUTRE = "Q" * 43 + "="


def test_rfc6238_vecteurs_officiels():
    # Secret ASCII « 12345678901234567890 » (SHA-1), codes à 8 chiffres de l'annexe B de la RFC 6238
    s = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    for ts, attendu in ((59, "94287082"), (1111111109, "07081804"), (1234567890, "89005924"), (2000000000, "69279037")):
        assert T.code_au_pas(s, ts // 30, 8) == attendu
    # Codes à 6 chiffres (ceux des applications) : les 6 derniers chiffres
    assert T.code_au_pas(s, 59 // 30) == "287082"


def test_verification_fenetre_et_rejeu():
    s = T.nouveau_secret()
    assert len(s) == 32 and T.verifier(s, "abcdef", 1000.0) is None and T.verifier(s, "12345", 1000.0) is None
    t0 = 1_700_000_010.0
    pas = T.pas_de(t0)
    bon = T.code_au_pas(s, pas)
    assert T.verifier(s, bon, t0) == pas
    assert T.verifier(s, bon[:3] + " " + bon[3:], t0) == pas                       # espace saisi par l'utilisateur toléré
    assert T.verifier(s, T.code_au_pas(s, pas - 1), t0) == pas - 1                  # ±30 s de décalage d'horloge tolérés
    assert T.verifier(s, T.code_au_pas(s, pas + 2), t0) is None                     # trop loin
    assert T.verifier(s, bon, t0, dernier_pas=pas) is None                         # un code déjà utilisé est refusé (rejeu)


def test_uri_otpauth():
    u = T.uri_otpauth("ABCDEFGHIJKLMNOP", "+226 70 00 00 00")
    assert u.startswith("otpauth://totp/auRor%3A%2B226%2070%2000%2000%2000?secret=ABCDEFGHIJKLMNOP&issuer=auRor")
    assert "digits=6" in u and "period=30" in u


def _code(secret, decalage=0):
    return T.code_au_pas(secret, T.pas_de(time.time()) + decalage)


def _installer(env, u):
    arch(env, "cle", u, sel=SEL, verif=VERIF)
    arch(env, "pin/enregistrer", u, preuve=PREUVE, verif_actuelle=VERIF)


def test_activation_puis_ouverture_avec_le_code_de_l_application(env):
    u = U()
    _installer(env, u)
    assert arch(env, "etat", u).json()["a2f"] is False
    assert arch(env, "pin/ouvrir", u, preuve=PREUVE).status_code == 200            # avant activation : comme avant
    # préparation : exige le jeton de contrôle
    assert arch(env, "totp/preparer", u, verif_actuelle="X" * 40).status_code == 409
    r = arch(env, "totp/preparer", u, verif_actuelle=VERIF).json()
    assert r["uri"].startswith("otpauth://totp/") and r["secret"] in r["uri"]
    assert arch(env, "etat", u).json()["a2f"] is False and arch(env, "pin/ouvrir", u, preuve=PREUVE).status_code == 200   # rien d'actif tant que non confirmé
    # un mauvais code n'active rien (une erreur de scan ne verrouille jamais dehors)
    mauvais = arch(env, "totp/activer", u, code="000000")
    assert mauvais.status_code == 409 and "heure de votre téléphone" in mauvais.json()["detail"]
    assert arch(env, "etat", u).json()["a2f"] is False
    ok = arch(env, "totp/activer", u, code=_code(r["secret"]))
    assert ok.status_code == 200 and arch(env, "etat", u).json()["a2f"] is True
    # ouverture : le code PIN seul ne suffit plus
    sans = arch(env, "pin/ouvrir", u, preuve=PREUVE)
    assert sans.status_code == 409 and "application" in sans.json()["detail"]
    # PIN + code de l'application : accepté ; le MÊME code ne peut pas resservir ; le suivant (+30 s) est accepté
    assert arch(env, "pin/ouvrir", u, preuve=PREUVE, code_totp=_code(r["secret"], 1)).status_code == 200
    assert arch(env, "pin/ouvrir", u, preuve=PREUVE, code_totp=_code(r["secret"], 1)).status_code == 409        # rejeu refusé
    # mauvais PIN avec le bon code : refusé, même message
    assert arch(env, "pin/ouvrir", u, preuve=AUTRE, code_totp=_code(r["secret"], 1)).status_code == 409


def test_secret_garde_chiffre_et_essais_limites_aussi_avec_le_code(env):
    u = U()
    _installer(env, u)
    r = arch(env, "totp/preparer", u, verif_actuelle=VERIF).json()
    arch(env, "totp/activer", u, code=_code(r["secret"]))
    doc = env.portal.call(env.db.membres_plateformes.find_one, {"utilisateur_id": u["id"]}, {"_id": 0})
    assert r["secret"] not in str(doc)                                               # jamais en clair en base
    for _ in range(4):
        assert arch(env, "pin/ouvrir", u, preuve=PREUVE, code_totp="000000").status_code == 409
    assert arch(env, "pin/ouvrir", u, preuve=PREUVE, code_totp="000000").status_code == 429        # 5e échec : pause
    assert arch(env, "pin/ouvrir", u, preuve=PREUVE, code_totp=_code(r["secret"], 1)).status_code == 429   # même avec le bon code


def test_desactivation_exige_le_code_et_la_recuperation_la_retire(env):
    u = U()
    _installer(env, u)
    r = arch(env, "totp/preparer", u, verif_actuelle=VERIF).json()
    arch(env, "totp/activer", u, code=_code(r["secret"]))
    assert arch(env, "totp/desactiver", u, preuve=AUTRE, code=_code(r["secret"], 1)).status_code == 409   # mauvais PIN
    assert arch(env, "etat", u).json()["a2f"] is True
    assert arch(env, "totp/desactiver", u, preuve=PREUVE, code=_code(r["secret"], 1)).status_code == 200
    assert arch(env, "etat", u).json()["a2f"] is False
    assert arch(env, "pin/ouvrir", u, preuve=PREUVE).status_code == 200
    # Téléphone perdu : récupération par le code de secours = nouveau code enregistré (jeton) → l'application est retirée
    r = arch(env, "totp/preparer", u, verif_actuelle=VERIF).json()
    arch(env, "totp/activer", u, code=_code(r["secret"], 1))
    assert arch(env, "etat", u).json()["a2f"] is True
    assert arch(env, "pin/enregistrer", u, preuve=AUTRE, verif_actuelle=VERIF).status_code == 200
    assert arch(env, "etat", u).json()["a2f"] is False and arch(env, "pin/ouvrir", u, preuve=AUTRE).status_code == 200
