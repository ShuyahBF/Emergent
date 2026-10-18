"""Lot 244 — Modération des cartes virtuelles des plateformes (auRor…) : refus AVANT toute génération, même si l'abonnement est payé.

Demande du propriétaire (18/10/2026) : « modérer les décors et les messages : bannir les expressions, mots ou allusions à caractère
sexuel, offensant, discriminant, pédophile, sexiste, rabaissant, insultant, homophobe. Refuser la génération même si l'abonnement est
payé et signaler à l'administrateur. Un message est quand même délivré à l'utilisateur. »

Pour un développeur WinDev (deux filtres successifs, le premier est local et gratuit, le second est un service de modération) :
  1. LISTE DE TERMES (ce fichier) : français et anglais, par catégorie. Le texte est d'abord NORMALISÉ pour déjouer les contournements
     usuels : accents, majuscules, lettres répétées (« puuute »), lettres espacées (« p u t e », « p.u.t.e »), chiffres à la place des
     lettres (« p0te »). On compare des MOTS ENTIERS (jamais un morceau de mot : « concert » ne contient pas « con »).
  2. MODÉRATION IA (OpenAI « omni-moderation ») : attrape les allusions que la liste ne connaît pas. Si ce service est indisponible,
     la carte est refusée avec un message de réessai (on ne laisse jamais passer un texte non vérifié).
  - Sont vérifiés ensemble : le thème et le décor souhaité, le message et le nom du destinataire.
  - Un refus n'est jamais décompté du plafond du jour, ne coûte aucune image et laisse une trace (incident + e-mail à l'administrateur).
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("sawali.moderation_cartes")

MESSAGE_REFUS = ("Cette carte ne peut pas être créée : le texte ou le décor contient des termes ou des allusions contraires aux règles "
                 "(sexuel, offensant, discriminant, sexiste, rabaissant, insultant, homophobe ou visant des mineurs). "
                 "L'administrateur a été informé.")
MESSAGE_INDISPONIBLE = "La vérification du contenu est momentanément indisponible : réessayez dans un instant. Aucune carte n'a été créée."

# Vérificateur IA de remplacement (tests) : async (textes) → {"signale": bool, "categories": [..]} ; None = vrai service
_moderer_ia: Optional[Callable] = None

# Catégories de la modération IA refusées (les autres, comme la violence ou l'automutilation, ne sont pas visées par la règle)
CATEGORIES_IA_REFUSEES = ("sexual", "sexual/minors", "hate", "hate/threatening", "harassment", "harassment/threatening")

# Termes refusés, par catégorie. Un mot se termine par « * » quand seul son DÉBUT compte (« pedophil* » couvre pédophile, pédophilie…).
# Une expression de plusieurs mots est comparée telle quelle. Les listes sont volontairement limitées aux termes sans usage innocent courant.
TERMES: Dict[str, List[str]] = {
    "sexuel": [
        "sexe", "sexuel*", "sexy", "sexo*", "porno*", "porn", "nude", "nudes", "tout nu", "toute nue", "femme nue", "femmes nues", "fille nue", "filles nues", "homme nu", "hommes nus", "a poil", "seins nus", "naked",
        "chatte", "couille*", "nichon*", "teton*", "foutre", "baise", "baiser fort", "suce moi", "coucher avec toi", "coucher avec moi", "branler", "branlette", "masturb*",
        "bander", "erection", "orgasme", "sperme", "vagin", "penis", "bite", "fellation", "sodomie", "levrette", "coucher avec",
        "faire l amour", "faire l'amour", "au lit avec toi", "nique", "niquer", "tirer un coup", "sex", "sexual", "fuck*", "dick", "pussy",
        "boobs", "tits", "blowjob", "horny", "anal", "erotique", "libidineux", "salace", 
    ],
    "pedophile": [
        "pedophil*", "pedo", "pedopornograph*", "lolicon", "shota", "pedobear", "enfant nu", "enfants nus", "petite fille nue",
        "petit garcon nu", "jeune fille nue", "mineure nue", "child porn", "kiddie", "underage",
    ],
    "insultant": [
        "connard*", "connasse*", "salaud*", "salopard*", "salope*", "pute*", "putain", "fils de pute", "fille de pute", "ta gueule", "ferme ta gueule",
        "va te faire", "va te faire foutre", "va mourir", "ordure*", "merde", "enfoire*", "abruti*", "cretin*", "imbecile*", "debile*",
        "batard*", "ducon", "tocard*", "pourriture", "sale con", "sale pute", "sale chien", "bitch", "asshole", "bastard", "idiot",
        "stupide", "motherfucker", "shit",
    ],
    "rabaissant": [
        "tu es nul", "tu es nulle", "t es nul", "t es nulle", "tu es moche", "t es moche", "tu es gros", "tu es grosse", "t es gros", "t es grosse",
        "gros porc", "grosse vache", "grosse truie", "sale gros", "minable", "tu ne vaux rien", "tu vaux rien", "bon a rien", "tu es un raté",
        "tu es une ratee", "tu es laid", "tu es laide", "t es laid", "t es laide", "tu pues", "t es une honte", "tu es une honte", "loser", "ugly", "fat pig",
    ],
    "discriminant": [
        "negre*", "negro", "nigger*", "nigga*", "bamboula*", "bougnoule*", "youpin*", "chinetoque*", "sale race", "nazi", "nazis", "sales noirs", "sale noir", "sale noire",
        "sale arabe", "sales arabes", "sale juif", "sales juifs", "sale blanc", "sales blancs", "sale etranger", "sales etrangers", "sale musulman",
        "sale chretien", "retourne dans ton pays", "retourne chez toi", "negre de maison", "heil hitler", "handicape de merde",
        "sale mongol", "mongolien", "attarde", "chink", 
    ],
    "sexiste": [
        "retourne a la cuisine", "retourne dans ta cuisine", "sale bonne femme", "sois belle et tais toi",
        "tais toi et sois belle", "ce n est qu une femme", "c est qu une femme", "les femmes ne savent pas", "sale nana",
        "salope", "pute", "traînée", "trainee", "tu n es qu une femme", "tu es qu une fille", "get back in the kitchen",
    ],
    "homophobe": [
        "pede", "pd", "tapette*", "tarlouze*", "tarlouse*", "gouine*", "enculé", "encule*", "sale homo", "sales homos", "faggot*", "fag", "dyke", "homophobe", "sale lesbienne", "sale gay", "sales gays", "travelo*", "sale trans", "tafiole*", "fiotte*",
        "lopette*",
    ],
}

_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i", "€": "e", "£": "l"})


def _sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texte) if not unicodedata.combining(c))


def _espaces(texte: str) -> str:
    """Tout ce qui n'est pas lettre ou chiffre devient une espace ; espaces multiples réduits."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]", " ", texte)).strip()


def _lettres_espacees(texte: str) -> str:
    """« p u t e » ou « p.u.t.e » → « pute » : une suite d'au moins trois lettres isolées est recollée."""
    mots = texte.split(" ")
    sortie, serie = [], []
    for mot in mots + [""]:
        if len(mot) == 1 and mot.isalpha():
            serie.append(mot)
            continue
        if len(serie) >= 3:
            sortie.append("".join(serie))
        else:
            sortie.extend(serie)
        serie = []
        if mot:
            sortie.append(mot)
    return " ".join(sortie)


def _sans_repetitions(texte: str) -> str:
    """Lettres répétées réduites à une seule : « puuuute » → « pute » (la liste subit la même réduction)."""
    return re.sub(r"(.)\1+", r"\1", texte)


def variantes(texte: str) -> List[str]:
    """Le texte sous ses formes normalisées : simple, chiffres→lettres, lettres recollées, lettres répétées réduites."""
    base = _espaces(_sans_accents((texte or "").lower().replace("’", "'")))
    leet = _espaces(_sans_accents((texte or "").lower().replace("’", "'")).translate(_LEET))
    liste = []
    for t in (base, leet):
        for v in (t, _lettres_espacees(t)):
            liste.append(v)
            liste.append(_sans_repetitions(v))
    return list(dict.fromkeys(v for v in liste if v))


def _motif(terme: str, reduit: bool) -> re.Pattern:
    """Motif « mot entier » (ou « début de mot » si le terme finit par *)."""
    debut = terme.endswith("*")
    brut = _espaces(_sans_accents(terme.rstrip("*").lower()))
    if reduit:
        brut = _sans_repetitions(brut)
    corps = re.escape(brut)
    return re.compile(rf"(?<![a-z0-9]){corps}" + ("" if debut else r"s?(?![a-z0-9])"))


_MOTIFS: List[Tuple[str, str, re.Pattern, re.Pattern]] = [
    (cat, terme, _motif(terme, False), _motif(terme, True)) for cat, termes in TERMES.items() for terme in termes]


def verifier_liste(texte: str) -> Optional[Tuple[str, str]]:
    """(catégorie, terme) du premier terme interdit trouvé dans le texte, sinon None."""
    for v in variantes(texte):
        for categorie, terme, motif, motif_reduit in _MOTIFS:
            if motif.search(v) or motif_reduit.search(v):
                return categorie, terme.rstrip("*")
    return None


async def _moderation_openai(textes: List[str]) -> Dict[str, Any]:
    """Service de modération OpenAI (gratuit) : {"signale": bool, "categories": [catégories refusées signalées]}."""
    import httpx
    from ia_client import cle_ia
    cle = cle_ia("openai")
    if not cle:
        raise RuntimeError("clé OpenAI absente")
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post("https://api.openai.com/v1/moderations", headers={"Authorization": f"Bearer {cle}"},
                              json={"model": "omni-moderation-latest", "input": textes})
    r.raise_for_status()
    categories: List[str] = []
    for res in r.json().get("results") or []:
        for nom, actif in (res.get("categories") or {}).items():
            if actif and nom in CATEGORIES_IA_REFUSEES and nom not in categories:
                categories.append(nom)
    return {"signale": bool(categories), "categories": categories}


class ContenuIndisponible(Exception):
    """Le service de modération n'a pas répondu : la carte n'est pas créée (jamais de texte non vérifié)."""


async def moderer(theme: str, message: str, destinataire: str = "") -> Optional[Dict[str, Any]]:
    """None si le contenu est accepté ; sinon {"source": "liste"|"ia", "categorie": …, "terme": …}. Lève ContenuIndisponible si le contrôle IA échoue."""
    textes = [t for t in (theme, message, destinataire) if (t or "").strip()]
    for t in textes:
        trouve = verifier_liste(t)
        if trouve:
            return {"source": "liste", "categorie": trouve[0], "terme": trouve[1]}
    try:
        res = await (_moderer_ia or _moderation_openai)(textes)
    except Exception:  # noqa: BLE001
        logger.warning("[cartes] modération IA indisponible", exc_info=True)
        raise ContenuIndisponible()
    if res.get("signale"):
        return {"source": "ia", "categorie": ", ".join(res.get("categories") or []) or "contenu inapproprié", "terme": ""}
    return None
