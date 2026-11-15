"""Lot 420 — « Dossier du demandeur » de la télé des familles : captcha, vérification, localisation de l'adresse IP, indicateurs de risque.

Pour un développeur WinDev : ce fichier ne contient que des FONCTIONS PURES (sans base de données ni réseau, sauf `localiser_ip`), pour qu'elles se testent
sur ordinateur. Les routes (routes/famille_tv.py) les appellent. Objectif du propriétaire (15/11/2026) : aider l'administrateur à décider d'une demande
d'accès à la télé, s'assurer de son authenticité et éviter les abus (bots, faux comptes, demandes en rafale).

  - CAPTCHA maison (aucun service tiers, aucune clé) : une image de 5 caractères déformés ; le jeton signé (HMAC) contient la preuve de la réponse, le serveur
    ne garde rien d'autre qu'une liste des jetons déjà utilisés (usage unique) ;
  - téléphone : normalisé en format international, pays déduit de l'indicatif ;
  - adresse IP : celle vue par le serveur (jamais celle déclarée), localisée (pays, ville, fournisseur, VPN / proxy / hébergeur) ;
  - appareil : informations DÉCLARÉES par l'application (marque, modèle, Android, langue, fuseau, écran, version, émulateur) — filtrées, jamais d'identifiant publicitaire ;
  - e-mail : vérifié par un code envoyé à l'adresse ; domaines jetables signalés ;
  - INDICATEURS : chaque signal inquiétant ou rassurant est listé avec son poids ; le score donne un niveau faible / moyen / élevé. L'administrateur décide ; rien n'est refusé
    automatiquement.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import os
import random
import re
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

ALPHABET_CAPTCHA = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"        # sans I, L, O, 0, 1 : lisible, sans confusion
CAPTCHA_LONGUEUR = 5
CAPTCHA_VALIDITE_S = 600                                      # 10 minutes pour répondre
CODE_EMAIL_VALIDITE_S = 900                                   # le code reçu par e-mail dure 15 minutes
CODE_EMAIL_ESSAIS = 5
LIMITE_DEMANDES_IP_24H = 5
LIMITE_DEMANDES_COMPTE_24H = 3
LIMITE_ENVOIS_CODE_COMPTE_H = 5
LIMITE_ENVOIS_CODE_IP_H = 10

# Indicatifs téléphoniques → pays (ISO) : pays de l'Afrique de l'Ouest et du Centre, France, Belgique, Suisse, Canada / États-Unis, Maghreb
INDICATIFS = {"226": "BF", "225": "CI", "223": "ML", "227": "NE", "228": "TG", "229": "BJ", "221": "SN", "224": "GN", "233": "GH", "234": "NG", "237": "CM", "241": "GA",
              "242": "CG", "243": "CD", "235": "TD", "222": "MR", "212": "MA", "213": "DZ", "216": "TN", "33": "FR", "32": "BE", "41": "CH", "1": "US", "44": "GB", "49": "DE"}
INDICATIF_DEFAUT = os.environ.get("FAMILLE_TV_INDICATIF", "226")     # numéro saisi sans indicatif : Burkina Faso

DOMAINES_JETABLES = {"mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com", "temp-mail.org", "yopmail.com", "trashmail.com", "sharklasers.com",
                     "getnada.com", "maildrop.cc", "throwawaymail.com", "dispostable.com", "fakeinbox.com", "mohmal.com", "emailondeck.com", "mintemail.com", "mytemp.email"}
_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")


# ------------------------------------------------------------------ téléphone, e-mail
def normaliser_telephone(saisie: str) -> Optional[Dict[str, str]]:
    """« 70 12 34 56 », « +226 70123456 », « 0022670123456 » → {e164: « +22670123456 », pays: « BF », indicatif: « 226 »} ; None si invalide (8 à 15 chiffres)."""
    brut = (saisie or "").strip()
    chiffres = re.sub(r"\D", "", brut)
    if brut.startswith("+"):
        pass
    elif chiffres.startswith("00"):
        chiffres = chiffres[2:]
    else:
        chiffres = INDICATIF_DEFAUT + chiffres.lstrip("0") if len(chiffres.lstrip("0")) <= 9 else chiffres
    if not 8 <= len(chiffres) <= 15:
        return None
    indicatif = next((i for i in sorted(INDICATIFS, key=len, reverse=True) if chiffres.startswith(i)), "")
    return {"e164": "+" + chiffres, "pays": INDICATIFS.get(indicatif, ""), "indicatif": indicatif}


def email_valide(email: str) -> bool:
    return bool(_EMAIL.match((email or "").strip())) and len(email) <= 120


def email_jetable(email: str) -> bool:
    return (email or "").strip().lower().rsplit("@", 1)[-1] in DOMAINES_JETABLES


def masquer_email(email: str) -> str:
    """« awa.badini@gmail.com » → « aw•••@gmail.com »."""
    nom, _, domaine = (email or "").partition("@")
    return (nom[:2] + "•••" if len(nom) > 2 else nom[:1] + "•••") + "@" + domaine


# ------------------------------------------------------------------ codes envoyés par e-mail
def nouveau_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(6))


def empreinte_code(compte_id: str, code: str) -> str:
    """Le code n'est jamais gardé en clair : empreinte liée au compte (un code ne vaut que pour SON compte)."""
    return hashlib.sha256(f"{compte_id}|{(code or '').strip()}".encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ captcha maison
def _secret() -> bytes:
    return (os.environ.get("JWT_SECRET") or "fallback-insecure").encode("utf-8")


def _signature(nonce: str, expire: int, reponse: str) -> str:
    return hmac.new(_secret(), f"{nonce}|{expire}|{reponse.upper()}".encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def fabriquer_captcha(maintenant: Optional[float] = None) -> Tuple[str, str, bytes]:
    """→ (jeton, texte attendu, image PNG). Le jeton est « nonce.expiration.signature » : la réponse n'est PAS dedans (seulement sa preuve)."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont      # Pillow est déjà une dépendance de SAWALI
    texte = "".join(random.SystemRandom().choice(ALPHABET_CAPTCHA) for _ in range(CAPTCHA_LONGUEUR))
    nonce = secrets.token_hex(8)
    expire = int((maintenant or time.time()) + CAPTCHA_VALIDITE_S)
    largeur, hauteur = 230, 84
    alea = random.SystemRandom()
    img = Image.new("RGB", (largeur, hauteur), (244, 247, 252))
    d = ImageDraw.Draw(img)
    for _ in range(7):                                              # traits de bruit
        d.line([(alea.randint(0, largeur), alea.randint(0, hauteur)), (alea.randint(0, largeur), alea.randint(0, hauteur))], fill=(alea.randint(120, 200),) * 3 + (), width=alea.randint(1, 2))
    police = ImageFont.load_default(size=44)
    for i, ch in enumerate(texte):                                  # chaque caractère : taille, rotation et hauteur propres
        calque = Image.new("RGBA", (56, 64), (0, 0, 0, 0))
        ImageDraw.Draw(calque).text((8, 6), ch, font=police, fill=(alea.randint(10, 70), alea.randint(30, 90), alea.randint(80, 150), 255))
        calque = calque.rotate(alea.randint(-22, 22), resample=Image.BICUBIC, expand=False)
        img.paste(calque, (10 + i * 42, alea.randint(2, 14)), calque)
    for _ in range(140):                                            # points de bruit
        d.point((alea.randint(0, largeur - 1), alea.randint(0, hauteur - 1)), fill=(alea.randint(60, 200),) * 3)
    img = img.filter(ImageFilter.SMOOTH_MORE)
    flux = io.BytesIO()
    img.save(flux, format="PNG")
    return f"{nonce}.{expire}.{_signature(nonce, expire, texte)}", texte, flux.getvalue()


def lire_jeton_captcha(jeton: str) -> Optional[Tuple[str, int]]:
    p = (jeton or "").split(".")
    if len(p) != 3 or not p[1].isdigit():
        return None
    return p[0], int(p[1])


def captcha_valide(jeton: str, reponse: str, maintenant: Optional[float] = None) -> bool:
    """Réponse exacte (sans tenir compte de la casse ni des espaces) ET jeton non expiré. L'usage unique est contrôlé par l'appelant (liste des nonces utilisés)."""
    lu = lire_jeton_captcha(jeton)
    if not lu:
        return False
    nonce, expire = lu
    if expire < int(maintenant or time.time()):
        return False
    attendue = _signature(nonce, expire, re.sub(r"\s", "", reponse or ""))
    return hmac.compare_digest(attendue, jeton.split(".")[2])


def png_en_data_url(octets: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(octets).decode("ascii")


# ------------------------------------------------------------------ adresse IP
def ip_client(entetes: Dict[str, str], hote: str) -> str:
    """Adresse vue par le serveur : premier élément de X-Forwarded-For (Render est derrière un relais), sinon l'adresse de la connexion."""
    xff = (entetes.get("x-forwarded-for") or "").split(",")[0].strip()
    return (xff or hote or "")[:64]


def ip_publique(ip: str) -> bool:
    import ipaddress
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast)


_cache_geo: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_localiser_remplace = None        # tests : async (ip) → dict ; None en production


async def localiser_ip(ip: str) -> Dict[str, Any]:
    """{pays, code_pays, region, ville, fai, mobile, proxy, hebergeur} ; vide si l'adresse n'est pas publique ou si le service ne répond pas (jamais bloquant)."""
    if _localiser_remplace is not None:
        return await _localiser_remplace(ip)
    if not ip_publique(ip):
        return {}
    en_cache = _cache_geo.get(ip)
    if en_cache and en_cache[0] > time.time():
        return en_cache[1]
    try:
        import httpx
        async with httpx.AsyncClient(timeout=2.5) as http:
            r = await http.get(f"http://ip-api.com/json/{ip}?fields=status,country,countryCode,regionName,city,isp,mobile,proxy,hosting")
            j = r.json() if r.status_code == 200 else {}
    except Exception:  # noqa: BLE001 — best effort
        return {}
    if j.get("status") != "success":
        return {}
    res = {"pays": j.get("country") or "", "code_pays": j.get("countryCode") or "", "region": j.get("regionName") or "", "ville": j.get("city") or "", "fai": j.get("isp") or "",
           "mobile": bool(j.get("mobile")), "proxy": bool(j.get("proxy")), "hebergeur": bool(j.get("hosting"))}
    _cache_geo[ip] = (time.time() + 3600, res)
    return res


# ------------------------------------------------------------------ appareil (informations déclarées par l'application)
CHAMPS_APPAREIL = {"marque": 40, "modele": 60, "android": 12, "sdk": 4, "langue": 12, "fuseau": 50, "ecran": 30, "app_version": 16, "reseau": 12}


def nettoyer_appareil(brut: Any) -> Dict[str, Any]:
    """Ne garde que les champs connus, en texte court (jamais d'identifiant publicitaire ni de numéro de série)."""
    brut = brut if isinstance(brut, dict) else {}
    sortie: Dict[str, Any] = {k: re.sub(r"[\x00-\x1f]", "", str(brut.get(k) or ""))[:n] for k, n in CHAMPS_APPAREIL.items() if brut.get(k) is not None}
    sortie["emulateur"] = bool(brut.get("emulateur"))
    return sortie


# ------------------------------------------------------------------ indicateurs de risque
def evaluer(dossier: Dict[str, Any], autres: List[Dict[str, Any]], maintenant_iso: str) -> Dict[str, Any]:
    """Indicateurs (positifs et inquiétants), score et niveau d'un dossier. `autres` : les demandes d'AUTRES comptes (pour repérer les doublons)."""
    ind: List[Dict[str, Any]] = []

    def ajouter(poids: int, code: str, texte: str):
        ind.append({"poids": poids, "niveau": "alerte" if poids >= 3 else "attention" if poids > 0 else "ok", "code": code, "texte": texte})

    geo = dossier.get("ip_infos") or {}
    tel = dossier.get("telephone") or {}
    app = dossier.get("appareil") or {}
    ip = dossier.get("ip") or ""
    if dossier.get("email_verifie"):
        ajouter(0, "email_verifie", "Adresse e-mail vérifiée par code")
    if email_jetable(dossier.get("email") or ""):
        ajouter(2, "email_jetable", "E-mail jetable (domaine temporaire)")
    if geo.get("proxy") or geo.get("hebergeur"):
        ajouter(3, "ip_proxy", "Adresse IP d'un VPN, d'un proxy ou d'un hébergeur (pas d'un abonné)")
    if tel.get("pays") and geo.get("code_pays"):
        if tel["pays"] == geo["code_pays"]:
            ajouter(0, "pays_coherent", f"Pays du téléphone et de l'adresse IP identiques ({geo['code_pays']})")
        else:
            ajouter(2, "pays_different", f"Pays du téléphone ({tel['pays']}) différent de celui de l'adresse IP ({geo['code_pays']})")
    if app.get("emulateur"):
        ajouter(2, "emulateur", "Appareil détecté comme émulateur")
    # doublons avec d'autres comptes
    memes_ip = [a for a in autres if ip and a.get("ip") == ip]
    if len(memes_ip) >= 2:
        ajouter(2, "ip_partagee", f"Adresse IP déjà utilisée par {len(memes_ip)} autres comptes")
    elif memes_ip:
        ajouter(1, "ip_partagee", "Adresse IP déjà utilisée par un autre compte")
    if tel.get("e164") and any((a.get("telephone") or {}).get("e164") == tel["e164"] for a in autres):
        ajouter(3, "tel_double", "Même numéro de téléphone que celui d'un autre compte")
    if dossier.get("email") and any((a.get("email") or "").lower() == dossier["email"].lower() for a in autres):
        ajouter(3, "email_double", "Même adresse e-mail que celle d'un autre compte")
    modele = (app.get("marque"), app.get("modele"))
    if all(modele) and sum(1 for a in autres if (a.get("appareil") or {}).get("marque") == modele[0] and (a.get("appareil") or {}).get("modele") == modele[1]
                           and a.get("ip") == ip and ip) >= 2:
        ajouter(2, "appareil_repete", "Même modèle de téléphone et même adresse IP que d'autres comptes")
    refus = [a for a in autres if a.get("etat") == "refuse" and (a.get("ip") == ip or (a.get("telephone") or {}).get("e164") == tel.get("e164") or (a.get("email") or "").lower() == (dossier.get("email") or "").lower())]
    if refus:
        ajouter(3, "deja_refuse", f"Une demande liée (même IP, téléphone ou e-mail) a déjà été refusée ({len(refus)})")
    # ancienneté du compte et liens de famille
    cree = dossier.get("compte_cree_le") or ""
    if cree and maintenant_iso:
        from datetime import datetime
        try:
            from datetime import timezone
            # une date sans fuseau (base de test ou ancienne donnée) est lue comme UTC
            def _lire(t):
                d = datetime.fromisoformat(t)
                return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
            age_h = (_lire(maintenant_iso) - _lire(cree)).total_seconds() / 3600
            if age_h < 24:
                ajouter(2, "compte_recent", "Compte « Ma famille » créé il y a moins de 24 heures")
        except ValueError:
            pass
    if dossier.get("teles_deplacees"):
        ajouter(3, "tele_deplacee", "Une télé de ce compte est vue dans un autre pays que celui de son appairage (télé déplacée ?)")
    if dossier.get("liens_verifies", 0) == 0:
        ajouter(1, "sans_lien", "Aucun proche vérifié dans « Ma famille »")
    else:
        ajouter(0, "avec_liens", f"{dossier['liens_verifies']} proche(s) vérifié(s) dans « Ma famille »")
    score = sum(i["poids"] for i in ind)
    return {"indicateurs": sorted(ind, key=lambda i: -i["poids"]), "score": score, "niveau": "eleve" if score >= 6 else "moyen" if score >= 3 else "faible"}


# ------------------------------------------------------------------ fiabilité des informations d'un dossier
# Règle du propriétaire (15/11/2026) : on ne s'appuie JAMAIS sur la seule bonne foi de l'utilisateur ; chaque information porte son degré de fiabilité :
#  - « verifie »  : prouvée (le code reçu par e-mail prouve que la personne lit cette boîte) ;
#  - « constate » : relevée par le serveur lui-même (adresse IP, localisation, ancienneté du compte, liens de famille vérifiés) ;
#  - « declare »  : fournie par l'application ou par la personne, NON vérifiable (lieu, téléphone, détails du téléphone) : simple indice, jamais une preuve.
FIABILITE = {"email": "verifie", "ip": "constate", "ip_infos": "constate", "compte_cree_le": "constate", "liens_verifies": "constate",
             "telephone": "declare", "lieu": "declare", "appareil": "declare"}


# ------------------------------------------------------------------ télé ancrée au lieu de son appairage
# La demande part du téléphone : SAWALI ne sait RIEN de fiable sur la télé à ce moment. La seule preuve est ce que le serveur voit de la télé elle-même :
#  - à l'appairage : l'adresse IP de la télé (relevée quand sa page /tv a demandé son code) est « l'ancre » (pays, ville, opérateur) ;
#  - ensuite, à chaque interrogation de la télé : son adresse IP du moment est comparée à l'ancre ; un AUTRE PAYS marque la télé « déplacée »
#    (les commandes sont refusées jusqu'à ce que SAWALI confirme le nouvel emplacement). Un changement de box ou d'opérateur dans le même pays ne déclenche rien.
OBSERVATION_SYNCHRONE = False          # vrai dans les tests : le calcul est attendu au lieu de partir en arrière-plan
_observations_en_cours: set = set()


def _lieu(infos: Dict[str, Any], ip: str, quand: str) -> Dict[str, Any]:
    return {"ip": ip, "code_pays": infos.get("code_pays", ""), "pays": infos.get("pays", ""), "ville": infos.get("ville", ""), "fai": infos.get("fai", ""), "le": quand}


async def _comparer(db, ecran_id: str) -> None:
    """Marque (ou démarque) la télé « déplacée » selon l'ancre et la dernière observation."""
    g = await db.settings.find_one({"_id": "global"}, {"tv_ecrans": 1}) or {}
    e = next((x for x in g.get("tv_ecrans") or [] if x.get("id") == ecran_id), None)
    if not e:
        return
    a, o = e.get("ancre") or {}, e.get("observe") or {}
    if not a.get("code_pays") or not o.get("code_pays"):
        return
    deplace = a["code_pays"] != o["code_pays"]
    if bool(e.get("deplacee")) != deplace:
        await db.settings.update_one({"_id": "global", "tv_ecrans.id": ecran_id}, {"$set": {"tv_ecrans.$.deplacee": deplace, "tv_ecrans.$.deplacee_le": o.get("le") if deplace else None}})


async def _enregistrer_lieu(db, ecran_id: str, ip: str, champ: str) -> None:
    from datetime import datetime, timezone
    try:
        infos = await localiser_ip(ip)
        if infos:
            await db.settings.update_one({"_id": "global", "tv_ecrans.id": ecran_id}, {"$set": {f"tv_ecrans.$.{champ}": _lieu(infos, ip, datetime.now(timezone.utc).isoformat())}})
            await _comparer(db, ecran_id)
    finally:
        _observations_en_cours.discard((ecran_id, champ, ip))


async def _lancer(db, ecran_id: str, ip: str, champ: str) -> None:
    """Calcul lourd (service externe) : jamais dans la requête de la télé (règle 7), sauf dans les tests."""
    import asyncio
    cle = (ecran_id, champ, ip)
    if cle in _observations_en_cours:
        return
    _observations_en_cours.add(cle)
    if OBSERVATION_SYNCHRONE:
        await _enregistrer_lieu(db, ecran_id, ip, champ)
    else:
        asyncio.create_task(_enregistrer_lieu(db, ecran_id, ip, champ))


async def observer_tele(db, ecran: Dict[str, Any], ip: str) -> None:
    """Appelée à chaque interrogation de la télé : ne fait rien tant que son adresse IP est la même (comparaison immédiate, sans base ni réseau)."""
    if ip and ip != (ecran.get("observe") or {}).get("ip"):
        await _lancer(db, ecran["id"], ip, "observe")


async def ancrer_tele(db, ecran_id: str, ip: str) -> None:
    """À l'appairage : la première adresse vue de la télé devient son ancre."""
    if ip:
        await _lancer(db, ecran_id, ip, "ancre")
