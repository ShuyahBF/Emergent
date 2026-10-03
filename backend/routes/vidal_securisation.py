"""Sécurisation de prescription VIDAL — version 2 (lot 56, portée depuis Ster).

Remplace l'ancienne version de ce fichier (portage site-meetafrican) par la
« Sécurisation VIDAL v2 » de Ster, elle-même issue de cette même page puis
alignée sur le manuel d'intégration VIDAL (les § cités renvoient à ce
manuel, qui n'est pas reproduit ici). Ce qui change pour le praticien :
  - données cliniques complètes (poids/taille datés, créatininémie ->
    clairance + DFG, grossesse/allaitement pour une femme seulement,
    allergies/molécules/pathologies CIM-10 lues dans VIDAL) ;
  - lignes de prescription STRUCTURÉES (unités, voies, indications lues
    dans VIDAL pour le médicament choisi ; dose par 24 h + fréquence ;
    intervalles ; période ; ALD) ;
  - traitements en cours repris des sécurisations précédentes du patient ;
  - contrôles de saisie identiques à l'écran et au serveur (HTTP 422
    détaillé, en français, champ par champ) ;
  - rapport HTML exhaustif de VIDAL (`/alerts/full/html`) ;
  - instantané de chaque sécurisation pour l'historique clinique.

Ce qui ne change pas : mêmes chemins `/api/vidal/securisation/analyze` et
`/api/vidal/securisation/history`, même collection `vidal_prescription_audit`
(enrichie), même authentification, même contrôle d'accès au module VIDAL,
même quota. L'ancienne page « Analyse prescription » (`/vidal/prescription/
analyze`, routes/vidal.py) n'est pas touchée.

Tous les appels à VIDAL passent par routes/vidal_appels.py (`appeler_vidal`),
qui applique le mode « Validation VIDAL » (patients fictifs uniquement).

Endpoints (préfixe /api) :
  GET  /vidal/referentiels                               listes, libellés, bornes
  GET  /vidal/referential/search?kind=&q=                allergies, molécules, CIM-10, ALD
  GET  /vidal/medicament/{type}/{id}/{liste}             unités, voies, indications, indicateurs
  GET  /vidal/formes-galeniques                          référentiel des formes
  GET  /vidal/groupes-dfg  |  PUT (gestionnaire)         groupes de référence du DFG
  POST /vidal/calculateurs/fonction-renale               clairance + DFG
  GET  /vidal/securisation/traitements-en-cours/{patient_id}
  POST /vidal/securisation/analyze                       alertes structurées
  POST /vidal/securisation/rapport-html                  rapport HTML VIDAL
  GET  /vidal/securisation/history[/{id}]                historique (inchangé)
  GET  /vidal/product/{id}/indications                   (inchangé, page Posologie)
"""
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ValidationError, field_validator

from routes.vidal_appels import appeler_vidal, assurer_index, config_prete, est_gestionnaire, mode_validation_actif, portee_etablissement
from vidal_v2.fonction_renale import (
    CLAIRANCE_MAX_TRANSMISE, arrondi2, calculer_fonction_renale_locale, categorie_insuffisance_renale, clairance_transmise,
    construire_xml_cockroft_gault, construire_xml_fonction_renale, lire_reponse_cockroft_gault, lire_reponse_fonction_renale,
    mg_dl_vers_umol_l,
)
from vidal_v2.groupes_dfg import configuration_dfg_par_defaut, controler_configuration
from vidal_v2.historique_clinique import resume_gravites
from vidal_v2.modeles import traduire_erreurs, valider_payload_securisation
from vidal_v2.parseurs import parser_entrees_atom, parser_entrees_categorisees, parser_indicateurs
from vidal_v2.referentiels import BORNES, RESSOURCES_API_MEDICAMENT, SEXES, referentiels_en_dict
from vidal_v2.traitements_en_cours import lignes_traitements_en_cours
from vidal_v2.xml_securisation import ORDRE_SEVERITE, construire_xml_prescription, extraire_patient_envoye, parser_reponse_alertes


# ---------------------------------------------------------------------------
# Modèles Pydantic (au niveau du MODULE, jamais dans la fonction d'attache :
# voir le correctif du 2026-09-15 sur les classes locales non résolues).
# ---------------------------------------------------------------------------

class EntreeFonctionRenale(BaseModel):
    """Corps de POST /vidal/calculateurs/fonction-renale — mêmes bornes que la sécurisation.

    § le groupe de référence du DFG n'est pas un champ de ce modèle : même
    envoyé par erreur, il est ignoré et n'atteint jamais les calculateurs VIDAL."""
    dateOfBirth: date
    gender: str
    weight: float
    height: Optional[float] = None
    serumCreatinine: Optional[float] = None
    # § saisie possible en mg/dL (convertie en µmol/L : × 88,4).
    serumCreatinineUnit: str = "umol_l"
    creatin: Optional[float] = None
    # § mode validation : patient fictif concerné (jamais transmis à VIDAL).
    patient_id: Optional[str] = None

    @field_validator("gender")
    @classmethod
    def _sexe(cls, v):
        if v not in ("MALE", "FEMALE"):
            raise ValueError(f"Le calcul de la fonction rénale nécessite le sexe Homme ou Femme (reçu : {SEXES.get(v, v)}).")
        return v

    @field_validator("dateOfBirth")
    @classmethod
    def _naissance(cls, v):
        if v > date.today():
            raise ValueError("La date de naissance ne peut pas être dans le futur.")
        return v

    @field_validator("weight")
    @classmethod
    def _poids(cls, v):
        b = BORNES["poids_kg"]
        if not (b["min"] <= v <= b["max"]):
            raise ValueError(f"Le poids (kg) doit être compris entre {b['min']:g} et {b['max']:g}.")
        return v

    @field_validator("serumCreatinineUnit")
    @classmethod
    def _unite(cls, v):
        if v not in ("umol_l", "mg_dl"):
            raise ValueError("Unité de créatininémie inconnue (attendu : umol_l ou mg_dl).")
        return v


class GroupeDfg(BaseModel):
    id: str
    libelle: str
    valeur_normale: float
    actif: bool = True
    ordre: int = 0
    par_defaut: bool = False


class SeuilsDfg(BaseModel):
    normal_pct: float = 90
    leger_pct: float = 60


class ConfigurationDfg(BaseModel):
    groupes: List[GroupeDfg]
    seuils: SeuilsDfg = SeuilsDfg()


# ---------------------------------------------------------------------------
# Fonctions utilitaires (sans route)
# ---------------------------------------------------------------------------

# § MI VIDAL §5.1.2.2 : /allergies?q= cherche À LA FOIS les classes
# d'allergie (catégorie ALLERGY) et les substances (catégorie MOLECULE) —
# la référence de chaque résultat est celle de SA catégorie. §5.2.1.2 :
# pathologies CIM-10 (/pathologies?q=&type=CIM10). §5.2.4.1 : ALD (/alds?q=).
_REFERENTIEL = {
    "allergy": {"chemin": "/allergies", "categories": ("ALLERGY", "MOLECULE")},
    "molecule": {"chemin": "/allergies", "categories": ("MOLECULE",)},
    "pathology": {"chemin": "/pathologies", "categories": None, "schema": "cim10", "params_extra": {"type": "CIM10"}},
    "ald": {"chemin": "/alds", "categories": None, "schema": "ald"},
}
_LISTES_MEDICAMENT = ("units", "routes", "indications", "indicators")


def preparer_lignes_securisation(payload) -> List[Dict[str, Any]]:
    """Traitements en cours (groupe 2, PREVIOUS_ORDER) + nouvelle prescription
    (groupe 1, SAME_ORDER, ou INFUSION si la ligne est une perfusion)."""
    lignes = []
    for ligne in payload.current_treatments:
        d = ligne.model_dump(mode="json")
        lignes.append({**d, "groupType": "PREVIOUS_ORDER", "groupId": 2})
    for ligne in payload.new_prescription_lines:
        d = ligne.model_dump(mode="json")
        type_groupe = d.get("groupType") if d.get("groupType") == "INFUSION" else "SAME_ORDER"
        lignes.append({**d, "groupType": type_groupe, "groupId": d.get("groupId") if d.get("groupId") is not None else 1})
    return lignes


def _erreur_422(message: str, champ: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"message": message, "erreurs": [{"champ": champ, "message": message}]})


def ordonnances_depuis_audits(audits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sécurisations précédentes d'un patient -> « ordonnances » lues par
    `lignes_traitements_en_cours` (vidal_v2/traitements_en_cours.py).

    (SAWALI) Ster lit ses ordonnances ; SAWALI n'a pas d'ordonnance
    structurée par patient, mais chaque sécurisation garde ses lignes
    (`lignes_envoyees`) : seules celles de la NOUVELLE prescription comptent
    (un traitement en cours repris tel quel n'est pas une nouvelle ordonnance)."""
    ordonnances = []
    for audit in audits:
        lignes = []
        for l in audit.get("lignes_envoyees") or []:
            if l.get("groupType") == "PREVIOUS_ORDER" or not l.get("drugRef"):
                continue
            donnees = {k: v for k, v in l.items() if k not in ("drugRef", "label", "groupId", "groupType", "status") and v not in (None, "", [])}
            lignes.append({"vidal_id": str(l["drugRef"]), "designation": l.get("label"), "donnees_vidal": donnees})
        if lignes:
            ordonnances.append({
                "reference": f"SEC-{(audit.get('id') or '')[:6].upper()}",
                "date_creation": audit.get("created_at"), "lignes": lignes,
            })
    return ordonnances


def ordonnance_depuis_ancien_format(patient: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Patients enregistrés AVANT le lot 56 : leurs « traitements en cours » (dernière prescription, durée en texte)."""
    lignes = []
    for t in patient.get("current_treatments") or []:
        if not t.get("drugRef"):
            continue
        duree = " ".join(str(x) for x in (t.get("duration"), t.get("durationType")) if x)
        lignes.append({"vidal_id": str(t["drugRef"]), "designation": t.get("label"), "duree": duree or None})
    if not lignes:
        return []
    return [{"reference": "Dernière consultation", "date_creation": patient.get("last_consultation_at"), "lignes": lignes}]


def dedoublonner_traitements(traitements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Un même médicament n'est proposé qu'une fois (la sécurisation la plus récente l'emporte)."""
    vus, resultat = set(), []
    for t in traitements:
        cle = t.get("drugRef") or f"?{(t.get('recherche_vidal') or t.get('label') or '').lower()}"
        if cle in vus:
            continue
        vus.add(cle)
        resultat.append(t)
    return resultat


def attach_vidal_securisation_routes(*, api, db, get_current_user):
    """Monte les endpoints de la sécurisation v2 (appelé par routes/vidal.py)."""

    async def _patient_du_praticien(patient_id: str, user: dict) -> dict:
        """Patient enregistré de CE praticien (404 sinon) — cloisonnement par utilisateur, comme vidal_patients."""
        doc = await db.vidal_patients.find_one({"id": patient_id, "user_id": user["id"]}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Patient introuvable")
        return doc

    async def _liste_cachee(user: dict, chemin: str, params: Optional[dict], lire) -> Any:
        """Appel VIDAL d'un référentiel stable, résultat LU mis en cache (le cache
        SAWALI ne garde pas les réponses XML brutes, on y range donc le JSON lu)."""
        from routes.vidal import _cache_get, _cache_key, _cache_set
        cfg = await config_prete(db, user)
        cle = _cache_key(cfg["mode"], "GET", f"v2:{chemin}", params or {})
        en_cache = await _cache_get(db, cle, cfg["cache_ttl_hours"])
        if en_cache is not None:
            return en_cache
        data = await appeler_vidal(db, cfg, user, "GET", chemin, params=params)
        if data.get("_erreur"):
            return None
        resultat = lire(data.get("raw"))
        await _cache_set(db, cle, resultat)
        return resultat

    # ---- Référentiels (aucun appel à VIDAL) ----
    @api.get("/vidal/referentiels", tags=["VIDAL"])
    async def referentiels_vidal(user: dict = Depends(get_current_user)):
        """Listes de valeurs VIDAL + libellés français + bornes (miroir de frontend/src/lib/vidalReferentiels.js)."""
        return referentiels_en_dict()

    # ---- Recherche référentielle : allergies, molécules, pathologies CIM-10, ALD ----
    @api.get("/vidal/referential/search", tags=["VIDAL"])
    async def recherche_referentielle(
        kind: str = Query(..., pattern="^(allergy|pathology|molecule|ald)$"),
        q: str = Query(..., min_length=2),
        user: dict = Depends(get_current_user),
    ):
        cfg = await config_prete(db, user)
        spec = _REFERENTIEL[kind]
        data = await appeler_vidal(db, cfg, user, "GET", spec["chemin"], params={"q": q, **spec.get("params_extra", {})})
        if data.get("_erreur"):
            raise HTTPException(status_code=502, detail="Recherche référentielle indisponible.")
        resultats = []
        for e in parser_entrees_categorisees(data.get("raw")):
            if not e.get("vidal_id"):
                continue
            if spec["categories"]:
                if e.get("categorie") not in spec["categories"]:
                    continue
                ref = e.get("uri") or f"vidal://{e['categorie'].lower()}/{e['vidal_id']}"
                resultats.append({"label": e["title"], "ref": ref, "type": e["categorie"]})
            else:
                resultats.append({"label": e["title"], "ref": e.get("uri") or f"vidal://{spec['schema']}/{e['vidal_id']}",
                                  "type": kind.upper(), "code": e.get("code")})
        return {"kind": kind, "query": q, "results": resultats}

    # ---- Listes propres à un médicament (sur la ressource de SON type) ----
    @api.get("/vidal/medicament/{type_medicament}/{ident}/{liste}", tags=["VIDAL"])
    async def liste_medicament(type_medicament: str, ident: str, liste: str, user: dict = Depends(get_current_user)):
        """§ MI VIDAL §6.3 / §4.7.1 : unités, voies, indications et indicateurs se
        lisent sur la ressource du MÊME type que le médicament prescrit
        (/product, /package, /ucd, /vmp). Voies triées par rang VIDAL, voies hors
        AMM signalées (elles ne sont pas sécurisées)."""
        ressource = RESSOURCES_API_MEDICAMENT.get(type_medicament.upper())
        if not ressource or liste not in _LISTES_MEDICAMENT or not ident.isdigit():
            raise HTTPException(status_code=400, detail="Type de médicament, identifiant ou liste non pris en charge.")

        def lire(raw):
            if liste == "indicators":
                return {"indicators": parser_indicateurs(raw)}
            entrees = parser_entrees_categorisees(raw)
            if liste == "routes":
                voies = [{"id": e["vidal_id"], "label": e["title"], "rang": e["ranking"], "hors_amm": e["hors_amm"]} for e in entrees if e.get("vidal_id")]
                voies.sort(key=lambda v: (v["rang"] is None, v["rang"] if v["rang"] is not None else 0))
                return {"routes": voies}
            if liste == "indications":
                return {"indications": [{"label": e["title"], "ref": f"vidal://indication/{e['vidal_id']}"} for e in entrees if e.get("vidal_id")]}
            return {"units": [{"id": e["vidal_id"], "label": e["title"]} for e in entrees if e.get("vidal_id")]}

        resultat = await _liste_cachee(user, f"/{ressource}/{ident}/{liste}", None, lire)
        if resultat is None:
            raise HTTPException(status_code=502, detail=f"Liste VIDAL « {liste} » indisponible pour ce médicament.")
        return resultat

    # ---- Référentiel des formes galéniques (filtre « Forme recherchée ») ----
    @api.get("/vidal/formes-galeniques", tags=["VIDAL"])
    async def formes_galeniques(user: dict = Depends(get_current_user)):
        def lire(raw):
            formes = [{"id": e["vidal_id"], "label": e["title"]} for e in parser_entrees_atom(raw) if e.get("vidal_id")]
            return {"formes": sorted(formes, key=lambda f: f["label"].lower())}

        resultat = await _liste_cachee(user, "/galenic-forms", {"page-size": 500}, lire)
        if resultat is None:
            raise HTTPException(status_code=502, detail="Référentiel des formes galéniques indisponible.")
        return resultat

    # ---- Indications d'une spécialité : endpoint HISTORIQUE conservé tel quel
    # (utilisé par la page Posologie ; la sécurisation v2 utilise
    # /vidal/medicament/PRODUCT/{id}/indications ci-dessus). ----
    @api.get("/vidal/product/{product_id}/indications", tags=["VIDAL"])
    async def product_indications(product_id: str, user: dict = Depends(get_current_user)):
        from routes.vidal import _ensure_tenant_can_access, _ensure_active, _quota_check_and_increment, _vidal_call
        from routes.vidal_riche import _parse_atom_entries

        cfg = await _ensure_tenant_can_access(db, user)
        _ensure_active(cfg)
        await _quota_check_and_increment(db, user["id"], cfg)
        data = await _vidal_call(cfg, "GET", f"/product/{product_id}/indications")
        entries = _parse_atom_entries((data or {}).get("raw"))
        results = [
            {"label": e["title"], "ref": f"vidal://indication/{e['vidal_id']}"}
            for e in entries if e.get("title") and e.get("vidal_id")
        ]
        return {"product_id": product_id, "indications": results}

    # ---- Groupes de référence du DFG (aide d'interprétation LOCALE) ----
    async def _charger_configuration_dfg(scope_uid: str) -> dict:
        doc = await db.vidal_config_groupes_dfg.find_one({"scope_uid": scope_uid}, {"_id": 0})
        if not doc:
            return configuration_dfg_par_defaut()
        return {"groupes": doc.get("groupes") or [], "seuils": doc.get("seuils") or configuration_dfg_par_defaut()["seuils"]}

    @api.get("/vidal/groupes-dfg", tags=["VIDAL"])
    async def obtenir_groupes_dfg(user: dict = Depends(get_current_user)):
        """Groupes de l'établissement — préremplis (Groupe A 84, Groupe B 74 ; seuils 90 % / 60 %)
        tant qu'un gestionnaire ne les a pas modifiés. Jamais transmis à VIDAL."""
        config = await _charger_configuration_dfg(await portee_etablissement(db, user))
        config["groupes"] = sorted(config["groupes"], key=lambda g: g.get("ordre", 0))
        config["modifiable"] = est_gestionnaire(user)
        return config

    @api.put("/vidal/groupes-dfg", tags=["VIDAL"])
    async def enregistrer_groupes_dfg(config: ConfigurationDfg, user: dict = Depends(get_current_user)):
        """Remplace la configuration de l'établissement (gestionnaire uniquement) — 422 détaillé si incohérente."""
        if not est_gestionnaire(user):
            raise HTTPException(status_code=403, detail="Paramétrage réservé au gestionnaire de l'établissement.")
        donnees = config.model_dump()
        erreurs = controler_configuration(donnees["groupes"], donnees["seuils"])
        if erreurs:
            raise HTTPException(status_code=422, detail={
                "message": "Configuration des groupes du DFG invalide : " + " ; ".join(e["message"] for e in erreurs), "erreurs": erreurs,
            })
        await assurer_index(db)
        scope_uid = await portee_etablissement(db, user)
        await db.vidal_config_groupes_dfg.update_one(
            {"scope_uid": scope_uid},
            {"$set": {**donnees, "scope_uid": scope_uid, "updated_at": datetime.now(timezone.utc), "updated_by": user.get("email")}},
            upsert=True,
        )
        return donnees

    # ---- Calculateurs de la fonction rénale ----
    async def _appeler_calculateur(cfg, user, chemin, xml_corps, patient_id, refus) -> Optional[str]:
        try:
            data = await appeler_vidal(db, cfg, user, "POST", chemin, corps_xml=xml_corps, patient_id=patient_id)
        except HTTPException as exc:
            refus.append(exc.detail)
            return None
        return None if data.get("_erreur") else data.get("raw")

    async def _calculateur_vidal_strict(cfg, user, chemin, xml_corps, patient_id) -> str:
        """Mode validation : la moindre erreur VIDAL remonte telle quelle (jamais de repli local)."""
        data = await appeler_vidal(db, cfg, user, "POST", chemin, corps_xml=xml_corps, patient_id=patient_id)
        if data.get("_erreur"):
            erreur = data["_erreur"]
            extrait = (data.get("raw") or "").strip()[:300]
            message = f"VIDAL {chemin} : statut {erreur.get('statut')} — {erreur.get('message')}{f' — {extrait}' if extrait else ''}"
            raise HTTPException(status_code=502, detail={"message": message, "statut_vidal": erreur.get("statut"), "erreurs": []})
        return data.get("raw") or ""

    async def _fonction_renale_mode_validation(entree: EntreeFonctionRenale, creat: Optional[float], user: dict, cfg: dict) -> dict:
        """Mode validation : clairance, créatininémie et DFG lus dans les réponses VIDAL UNIQUEMENT."""
        resultat = {"creatin": None, "creatin_calculee": None, "plafonnee": False, "serumCreatinine": arrondi2(creat) if creat is not None else None,
                    "glomerularFiltrationRate": None, "insuffisanceRenale": None, "stadeKdigo": None}
        sources = {"creatin": None, "serumCreatinine": "saisie" if creat is not None else None, "glomerularFiltrationRate": None}
        if creat is not None:
            raw = await _calculateur_vidal_strict(cfg, user, "/calculators/ccreat/cockroft-gault", construire_xml_cockroft_gault(
                date_naissance=entree.dateOfBirth, sexe=entree.gender, poids_kg=entree.weight, taille_cm=entree.height, creatininemie_umol_l=creat,
            ), entree.patient_id)
            cg = lire_reponse_cockroft_gault(raw)
            if not cg:
                raise HTTPException(status_code=502, detail={
                    "message": "VIDAL /calculators/ccreat/cockroft-gault : réponse sans clairance estimée (vidal:estimatedCreatinineClearance) — aucune valeur calculée localement.",
                    "erreurs": []})
            resultat.update({"creatin_calculee": arrondi2(cg["clairance"]), "creatin": clairance_transmise(cg["clairance"]),
                             "plafonnee": cg["clairance"] > CLAIRANCE_MAX_TRANSMISE, "insuffisanceRenale": cg.get("insuffisanceRenale")})
            sources["creatin"] = "vidal"
            rf = lire_reponse_fonction_renale(await _calculateur_vidal_strict(cfg, user, "/calculators/renal-function", construire_xml_fonction_renale(
                date_naissance=entree.dateOfBirth, sexe=entree.gender, poids_kg=entree.weight, creatininemie_umol_l=creat,
            ), entree.patient_id))
        else:
            rf = lire_reponse_fonction_renale(await _calculateur_vidal_strict(cfg, user, "/calculators/renal-function", construire_xml_fonction_renale(
                date_naissance=entree.dateOfBirth, sexe=entree.gender, poids_kg=entree.weight, clairance_ml_min=entree.creatin,
            ), entree.patient_id))
            if rf.get("creatininemie") is not None:
                resultat["serumCreatinine"] = arrondi2(rf["creatininemie"])
                sources["serumCreatinine"] = "vidal"
        if rf.get("dfg") is not None:  # absent si VIDAL ne le calcule pas (ex. moins de 18 ans) : laissé vide
            resultat.update({"glomerularFiltrationRate": arrondi2(rf["dfg"]), "stadeKdigo": rf.get("stadeKdigo")})
            sources["glomerularFiltrationRate"] = "vidal"
        return {**resultat, "sources": sources, "avertissement": None, "mode_validation": True}

    @api.post("/vidal/calculateurs/fonction-renale", tags=["VIDAL"])
    async def calculer_fonction_renale(donnees: dict = Body(...), user: dict = Depends(get_current_user)):
        """Les 3 valeurs de la fonction rénale (clairance, créatininémie, DFG).

        Hors mode validation : calcul LOCAL immédiat (Cockcroft & Gault,
        CKD-EPI 2009 sans coefficient ethnique), remplacé par les valeurs des
        calculateurs VIDAL quand ils répondent (§5.2.2.3 à 5.2.2.5).
        En mode validation : valeurs VIDAL UNIQUEMENT, aucune valeur locale ;
        l'erreur VIDAL réelle est renvoyée telle quelle."""
        try:
            entree = EntreeFonctionRenale.model_validate(donnees or {})
        except ValidationError as exc:
            erreurs = traduire_erreurs(exc)
            raise HTTPException(status_code=422, detail={
                "message": "Calcul de la fonction rénale impossible : " + " ; ".join(f"{e['champ']} — {e['message']}" for e in erreurs),
                "erreurs": erreurs,
            }) from exc

        creat = entree.serumCreatinine
        if creat is not None and entree.serumCreatinineUnit == "mg_dl":
            creat = mg_dl_vers_umol_l(creat)
        if creat is None and entree.creatin is None:
            raise _erreur_422("Saisissez la créatininémie (ou, à défaut, la clairance de la créatinine).", "serumCreatinine")
        b = BORNES["creatininemie_umol_l"]
        if creat is not None and not (b["min"] <= creat <= b["max"]):
            raise _erreur_422(f"La créatininémie doit être comprise entre {b['min']} et {b['max']} µmol/L.", "serumCreatinine")

        if await mode_validation_actif(db, await portee_etablissement(db, user)):
            cfg = await config_prete(db, user)  # 503 explicite si module/identifiants de production absents
            return await _fonction_renale_mode_validation(entree, creat, user, cfg)

        resultat = calculer_fonction_renale_locale(
            date_naissance=entree.dateOfBirth, sexe=entree.gender, poids_kg=entree.weight,
            creatininemie_umol_l=creat, clairance_ml_min=entree.creatin,
        )
        sources = {"creatin": "local", "serumCreatinine": "saisie" if creat is not None else "local", "glomerularFiltrationRate": "local"}
        refus: list = []
        try:
            cfg = await config_prete(db, user)
        except HTTPException:
            cfg = None  # module désactivé, identifiants absents ou quota atteint : calcul local
        if cfg:
            if creat is not None:
                cg = lire_reponse_cockroft_gault(await _appeler_calculateur(cfg, user, "/calculators/ccreat/cockroft-gault", construire_xml_cockroft_gault(
                    date_naissance=entree.dateOfBirth, sexe=entree.gender, poids_kg=entree.weight, taille_cm=entree.height, creatininemie_umol_l=creat,
                ), entree.patient_id, refus))
                if cg:
                    resultat.update({
                        "creatin_calculee": arrondi2(cg["clairance"]), "creatin": clairance_transmise(cg["clairance"]),
                        "plafonnee": cg["clairance"] > CLAIRANCE_MAX_TRANSMISE,
                        "insuffisanceRenale": cg.get("insuffisanceRenale") or categorie_insuffisance_renale(cg["clairance"]),
                    })
                    sources["creatin"] = "vidal"
                rf = lire_reponse_fonction_renale(await _appeler_calculateur(cfg, user, "/calculators/renal-function", construire_xml_fonction_renale(
                    date_naissance=entree.dateOfBirth, sexe=entree.gender, poids_kg=entree.weight, creatininemie_umol_l=creat,
                ), entree.patient_id, refus))
            else:
                rf = lire_reponse_fonction_renale(await _appeler_calculateur(cfg, user, "/calculators/renal-function", construire_xml_fonction_renale(
                    date_naissance=entree.dateOfBirth, sexe=entree.gender, poids_kg=entree.weight, clairance_ml_min=entree.creatin,
                ), entree.patient_id, refus))
                if rf.get("creatininemie") is not None:
                    resultat["serumCreatinine"] = arrondi2(rf["creatininemie"])
                    sources["serumCreatinine"] = "vidal"
            if rf.get("dfg") is not None:
                resultat["glomerularFiltrationRate"] = arrondi2(rf["dfg"])
                resultat["stadeKdigo"] = rf.get("stadeKdigo")
                sources["glomerularFiltrationRate"] = "vidal"
        return {**resultat, "sources": sources, "avertissement": refus[0] if refus else None, "formules": {
            "creatin": "Cockcroft & Gault", "glomerularFiltrationRate": "CKD-EPI (sans coefficient ethnique)",
        }}

    # ---- Traitements en cours d'un patient enregistré ----
    @api.get("/vidal/securisation/traitements-en-cours/{patient_id}", tags=["VIDAL"])
    async def traitements_en_cours(patient_id: str, user: dict = Depends(get_current_user)):
        """§ doc VIDAL : traitements courants = lignes des prescriptions
        ANTÉRIEURES non terminées à la date du jour. Sources, de la plus
        récente à la plus ancienne : sécurisations v2 du patient, ordonnance
        antérieure fictive (patients de validation), puis l'ancien format
        (patients enregistrés avant le lot 56)."""
        patient = await _patient_du_praticien(patient_id, user)
        audits = await db.vidal_prescription_audit.find(
            {"patient_id": patient_id, "user_id": user["id"], "source": "securisation_v2"},
            {"_id": 0, "id": 1, "created_at": 1, "lignes_envoyees": 1},
        ).sort("created_at", -1).to_list(length=50)
        ordonnances = ordonnances_depuis_audits(audits) + list(patient.get("ordonnances_fictives") or [])
        if not audits:
            ordonnances += ordonnance_depuis_ancien_format(patient)
        return {"traitements": dedoublonner_traitements(lignes_traitements_en_cours(ordonnances))}

    # ---- Analyse (alertes structurées) ----
    @api.post("/vidal/securisation/analyze", tags=["VIDAL"])
    async def securisation_analyze(donnees: dict = Body(...), user: dict = Depends(get_current_user)):
        # § validation serveur (types, bornes, cohérence) identique à l'écran — 422 détaillé en français.
        payload = valider_payload_securisation(donnees)
        if not payload.new_prescription_lines and not payload.current_treatments:
            raise HTTPException(status_code=400, detail="Au moins un médicament est requis")
        patient_doc = await _patient_du_praticien(payload.patient_id, user) if payload.patient_id else None
        cfg = await config_prete(db, user)
        await assurer_index(db)

        toutes_lignes = preparer_lignes_securisation(payload)
        xml_corps = construire_xml_prescription(payload.patient.model_dump(mode="json"), toutes_lignes, payload.alert_types)
        data = await appeler_vidal(db, cfg, user, "POST", "/alerts/full", corps_xml=xml_corps, patient_id=payload.patient_id)
        analyse = parser_reponse_alertes(data.get("raw"))
        severites = [s.get("severity") for s in analyse.get("summary", []) if s.get("severity")]
        severite_max = max(severites, key=lambda s: ORDRE_SEVERITE.get(s, -1)) if severites else None

        # § INSTANTANÉ (historique clinique) : données patient réellement
        # envoyées (relues dans le XML), lignes analysées, alertes par
        # gravité. Le groupe de référence du DFG est gardé dans un champ
        # LOCAL séparé : il ne figure jamais dans le XML envoyé.
        audit_id = str(uuid.uuid4())
        nom = payload.patient_name or payload.patient_nom or (patient_doc or {}).get("name")
        entree = {
            "id": audit_id, "user_id": user["id"], "user_email": user.get("email"),
            "scope_uid": cfg.get("scope_uid"),
            "patient_id": payload.patient_id, "patient_name": nom,
            "patient_whatsapp": payload.patient_whatsapp or (patient_doc or {}).get("whatsapp_number"),
            "lines_count": len(toutes_lignes), "top_severity": severite_max, "parsed": analyse,
            "request_xml": xml_corps[:4000], "response_summary": str(data.get("_erreur") or "")[:1500],
            "mode": cfg["mode"], "mode_validation": bool(cfg.get("validation")),
            "source": "securisation_v2", "created_at": datetime.now(timezone.utc),
            "patient_envoye": extraire_patient_envoye(xml_corps),
            "lignes_envoyees": toutes_lignes,
            "resume_gravites": resume_gravites(analyse.get("alerts")),
            "groupe_reference_dfg_local": payload.groupe_reference_dfg,
        }
        await db.vidal_prescription_audit.insert_one(entree)
        if payload.patient_id:
            from routes.vidal_patients import record_consultation
            await record_consultation(db, patient_id=payload.patient_id, user_id=user["id"],
                                      new_prescription_lines=[l for l in toutes_lignes if l.get("groupType") != "PREVIOUS_ORDER"])
        reponse = {"id": audit_id, "analyse": analyse, "parsed": analyse, "request_xml": xml_corps}
        if data.get("_erreur"):
            reponse["erreur_vidal"] = data["_erreur"]
        return reponse

    # ---- Rapport HTML exhaustif ----
    @api.post("/vidal/securisation/rapport-html", tags=["VIDAL"])
    async def rapport_html_securisation(donnees: dict = Body(...), user: dict = Depends(get_current_user)):
        """POST /alerts/full/html avec le MÊME corps (patient + toutes les lignes) :
        document exhaustif (toutes alertes, toutes sévérités) renvoyé tel quel,
        complet ou filtré sur des rubriques (§6.5.5, <alert-display-types>)."""
        payload = valider_payload_securisation(donnees)
        if not payload.new_prescription_lines and not payload.current_treatments:
            raise HTTPException(status_code=400, detail="Au moins un médicament est requis")
        if payload.patient_id:
            await _patient_du_praticien(payload.patient_id, user)
        cfg = await config_prete(db, user)
        xml_corps = construire_xml_prescription(
            payload.patient.model_dump(mode="json"), preparer_lignes_securisation(payload), inclure_types_alerte=False,
            rubriques_html=payload.alert_display_types,
        )
        data = await appeler_vidal(db, cfg, user, "POST", "/alerts/full/html", corps_xml=xml_corps, patient_id=payload.patient_id)
        if data.get("_erreur") or not data.get("raw"):
            raise HTTPException(status_code=502, detail="VIDAL n'a pas renvoyé le rapport HTML de sécurisation.")
        return Response(content=data["raw"], media_type="text/html; charset=utf-8")

    # ---- Historique de TOUTES les sécurisations du praticien (inchangé) ----
    @api.get("/vidal/securisation/history", tags=["VIDAL"])
    async def securisation_history(user: dict = Depends(get_current_user)):
        cursor = db.vidal_prescription_audit.find(
            {"user_id": user["id"], "source": "securisation_v2"},
            {"_id": 0, "id": 1, "created_at": 1, "patient_name": 1, "patient_whatsapp": 1,
             "lines_count": 1, "top_severity": 1, "patient_id": 1},
        ).sort("created_at", -1).limit(50)
        return {"results": await cursor.to_list(length=50)}

    @api.get("/vidal/securisation/history/{analysis_id}", tags=["VIDAL"])
    async def securisation_history_detail(analysis_id: str, user: dict = Depends(get_current_user)):
        doc = await db.vidal_prescription_audit.find_one({"id": analysis_id, "user_id": user["id"]}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Analyse introuvable")
        # § compatibilité : l'écran v2 lit `analyse`, l'ancien `parsed`.
        doc.setdefault("analyse", doc.get("parsed"))
        return doc
