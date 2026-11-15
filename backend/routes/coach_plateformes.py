"""Lot 423 — « Liluvine, ma coach » : conversation de soutien du JOURNAL INTIME de auRor (et de toute plateforme qui le demandera).

Demande du propriétaire (15/11/2026) : l'utilisateur se confie dans un journal intime et, abonné, converse avec une coach, Liluvine, qui
prodigue des conseils et donne son avis. Décisions confirmées : (1) les confidences restent SUR LE TÉLÉPHONE, chiffrées ; (2) Liluvine répond par
une IA via SAWALI : le texte envoyé sert à répondre et n'est JAMAIS conservé ici ; (3) garde-fous : soutien et conseils de vie, jamais de diagnostic
ni d'ordonnance, orientation vers une aide humaine en cas de détresse grave ; (4) abonnement par formule (fonction « coach_liluvine »), avec quelques
échanges d'essai gratuits.

Pour un développeur WinDev (équivalent d'une procédure de réponse, sans nouveau fichier de données) :
  - la plateforme (déjà authentifiée) envoie une requête SIGNÉE (X-Emetteur, X-Timestamp, X-Signature) avec les derniers échanges ;
  - accès : abonnement actif (fonction `coach_liluvine`), sinon quelques ESSAIS GRATUITS (réglable, 5 par défaut) puis refus 402 avec le nom et le prix de la formule ;
  - plafond de messages par jour et par utilisateur (protège le coût de l'IA) ;
  - AVANT l'IA, un contrôle de DÉTRESSE : si le message évoque l'envie de mourir ou de se faire du mal, la réponse est un message fixe, humain et sûr
    (invitation à joindre une personne de confiance et les secours), sans passer par l'IA, sans décompte, avec `urgence: true` ;
  - aucun texte de conversation n'est enregistré ni journalisé : seuls des compteurs (jour, total, essais) sont tenus sur la fiche de l'utilisateur.

Route SIGNÉE :
    POST /api/coach-plateformes/repondre  {utilisateur, messages: [{role: user|assistant, content}], }  →
         {reponse, urgence, restant_aujourdhui, essais_restants (null si abonné)}
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from routes.formules_plateformes import Utilisateur, _maintenant

logger = logging.getLogger("sawali.coach_plateformes")

FONCTION_COACH = "coach_liluvine"
COACH_PAR_JOUR_DEFAUT = 40        # messages par jour et par utilisateur (réglable : settings.global.coach_plateformes_par_jour)
COACH_ESSAIS_DEFAUT = 5           # échanges offerts avant l'abonnement (réglable : settings.global.coach_essais_gratuits)
MESSAGE_MAX = 2000                # caractères d'un message
HISTORIQUE_MAX = 16               # derniers échanges envoyés à l'IA
MODELE = ("anthropic", "claude-sonnet-4-5-20250929")
_repondre_remplace: Optional[Callable] = None     # tests : async (systeme, historique) → texte ; None = IA réelle (ia_client)

# ------------------------------------------------------------------ garde-fous
CONSIGNE_COACH = (
    "Tu es Liluvine, une coach de vie chaleureuse, bienveillante et simple, qui accompagne une personne dans son journal intime (application auRor, Burkina Faso). "
    "Réponds TOUJOURS en français, avec des mots simples, un ton humain et rassurant, en 120 mots au plus, sans jargon ni listes à rallonge. "
    "Écoute d'abord : reformule ce que la personne ressent, puis propose UN ou DEUX conseils concrets et réalisables, ou une question qui l'aide à y voir plus clair. "
    "Tu es une COACH, pas une thérapeute, pas un médecin, pas une avocate ni une conseillère financière : tu ne poses AUCUN diagnostic, tu ne prescris AUCUN médicament, "
    "tu ne donnes pas de conseil juridique ni de placement d'argent. Pour un problème médical, juridique ou de santé mentale sérieux, tu encourages avec douceur à parler à un professionnel ou à une personne de confiance. "
    "Si la personne parle de se faire du mal ou de mourir, tu lui dis que sa vie compte, qu'elle n'est pas seule, et qu'elle doit contacter MAINTENANT les secours ou une personne proche. "
    "Tu ne demandes JAMAIS de mot de passe, de code PIN, de numéro de carte ni de secret bancaire, et tu refuses d'en recevoir. "
    "Tu n'incites jamais à la haine, à la violence, à la vengeance ni à tromper quelqu'un ; tu restes respectueuse des croyances et des cultures. "
    "Tu ne prétends pas être une personne humaine : si on te le demande, tu dis que tu es Liluvine, une assistante par intelligence artificielle. "
    "Tout ce que la personne écrit est une confidence : ne la juge pas, ne la répète à personne."
)

MESSAGE_URGENCE = (
    "Ce que vous traversez a l'air très lourd, et je suis contente que vous l'ayez écrit. Votre vie compte. Vous n'êtes pas seul(e). "
    "Si vous pensez à vous faire du mal ou à mettre fin à vos jours, contactez dès maintenant les secours ou le service d'urgence de votre pays, "
    "rendez-vous au centre de santé le plus proche, ou appelez une personne de confiance (un proche, un voisin, un responsable religieux) pour qu'elle reste avec vous. "
    "Je reste là pour vous écouter, mais je ne peux pas remplacer une aide humaine immédiate."
)

# Expressions de détresse (sans accents ni majuscules) : contrôle volontairement LARGE, car une fausse alerte est bien moins grave qu'un oubli.
RE_DETRESSE = re.compile(
    r"(me suicid|suicid|envie de mourir|veux mourir|vouloir mourir|je veux en finir|en finir avec (la vie|tout)|mettre fin a (mes|ma) (jours|vie)|"
    r"me tuer|me faire du mal|me faire mal|me pendre|plus envie de vivre|je ne veux plus vivre|disparaitre pour toujours|avaler (tous )?(mes|les) (comprimes|medicaments))")


def _sans_accents(t: str) -> str:
    return unicodedata.normalize("NFD", str(t or "").lower()).encode("ascii", "ignore").decode()


def detresse(texte: str) -> bool:
    """Vrai si le message évoque l'envie de mourir ou de se faire du mal."""
    return bool(RE_DETRESSE.search(_sans_accents(texte)))


def nettoyer_messages(brut: Any) -> List[Dict[str, str]]:
    """Garde les derniers échanges valides (rôle user / assistant, texte non vide, borné) ; le dernier doit être de l'utilisateur."""
    sortie: List[Dict[str, str]] = []
    for m in brut if isinstance(brut, list) else []:
        role = m.get("role") if isinstance(m, dict) else None
        texte = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str((m or {}).get("content") or "")).strip()[:MESSAGE_MAX] if role in ("user", "assistant") else ""
        if texte:
            sortie.append({"role": role, "content": texte})
    sortie = sortie[-HISTORIQUE_MAX:]
    while sortie and sortie[0]["role"] != "user":
        sortie.pop(0)
    if not sortie or sortie[-1]["role"] != "user":
        raise HTTPException(status_code=422, detail="Écrivez d'abord un message à Liluvine.")
    return sortie


class CoachIn(BaseModel):
    utilisateur: Utilisateur
    messages: List[Dict[str, Any]] = Field(..., min_length=1, max_length=40)


async def _ia(systeme: str, historique: List[Dict[str, str]]) -> str:
    """Réponse de l'IA (client IA local de SAWALI) ; l'historique précédent est donné comme début de conversation."""
    from ia_client import LlmChat, UserMessage
    chat = LlmChat(api_key=None, session_id="coach-liluvine", system_message=systeme, initial_messages=historique[:-1]).with_model(*MODELE).with_params(max_tokens=500)
    return (await chat.send_message(UserMessage(text=historique[-1]["content"]))) or ""


def make_coach_plateformes(*, db, outils) -> APIRouter:
    router = APIRouter(tags=["Coach Liluvine — plateformes"])

    async def _reglage(cle: str, defaut: int) -> int:
        s = await db.settings.find_one({"_id": "global"}, {cle: 1}) or {}
        try:
            return int(s.get(cle) if s.get(cle) is not None else defaut)
        except (TypeError, ValueError):
            return defaut

    @router.post("/coach-plateformes/repondre")
    async def repondre(request: Request):
        emetteur, corps = await outils.plateforme_signee(request)
        d = outils.lire(CoachIn, corps)
        historique = nettoyer_messages(d.messages)
        m = await outils.membre(emetteur["code"], d.utilisateur)
        # Détresse : réponse fixe et sûre, avant tout contrôle d'abonnement ou de limite (jamais refusée, jamais décomptée, jamais envoyée à l'IA)
        if detresse(historique[-1]["content"]):
            return {"reponse": MESSAGE_URGENCE, "urgence": True, "restant_aujourdhui": None, "essais_restants": None}
        abonne = bool(outils.acces_fonction(m, FONCTION_COACH)) or d.utilisateur.acces_libre
        essais = max(0, await _reglage("coach_essais_gratuits", COACH_ESSAIS_DEFAUT) - int(m.get("coach_essais") or 0))
        if not abonne and essais <= 0:
            await outils.exiger_abonnement(emetteur["code"], m, FONCTION_COACH, "La conversation avec Liluvine", False,
                                           refus="Vos échanges d'essai avec Liluvine sont terminés : un abonnement est nécessaire pour continuer.")
        jour, limite = _maintenant().date().isoformat(), await _reglage("coach_plateformes_par_jour", COACH_PAR_JOUR_DEFAUT)
        if int((m.get("coach_jours") or {}).get(jour, 0)) >= limite:
            raise HTTPException(status_code=429, detail=f"Liluvine a beaucoup parlé aujourd'hui ({limite} messages) : reprenez demain.")
        try:
            texte = await (_repondre_remplace or _ia)(CONSIGNE_COACH, historique)
        except Exception:  # noqa: BLE001 — jamais le texte de l'utilisateur dans les journaux
            logger.exception("[coach] réponse impossible")
            raise HTTPException(status_code=502, detail="Liluvine ne peut pas répondre pour le moment : réessayez dans un instant.")
        texte = (texte or "").strip()
        if not texte:
            raise HTTPException(status_code=502, detail="Liluvine n'a pas pu formuler de réponse : réessayez.")
        # Réponse réussie seulement : compteurs (aucun texte conservé)
        inc: Dict[str, int] = {f"coach_jours.{jour}": 1, "coach_total": 1}
        if not abonne:
            inc["coach_essais"] = 1
        await db.membres_plateformes.update_one({"id": m["id"]}, {"$inc": inc})
        restant = max(0, limite - int((m.get("coach_jours") or {}).get(jour, 0)) - 1)
        return {"reponse": texte[:2500], "urgence": False, "restant_aujourdhui": restant, "essais_restants": None if abonne else max(0, essais - 1)}

    return router
