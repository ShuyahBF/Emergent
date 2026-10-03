"""Lot 56 — Mode « Validation VIDAL » : réglage, patients fictifs, journal.

Porté depuis Ster (app/routers/vidal_validation.py). Décision de
l'utilisateur reprise telle quelle : « Vrais appels (pas de sandbox), avec
des patients fictifs ; les patients doivent couvrir tous les profils
cliniques, 3 patients par profil. Aucune donnée de vrai patient n'est
transmise à VIDAL. Tableau récapitulatif : date/heure de l'appel, URL de la
requête (identifiants anonymisés), body, valeur du retour, délai avant
réponse, observations. »

Adaptations SAWALI :
  - le réglage est fait PAR ÉTABLISSEMENT (client « tenant ») par un
    gestionnaire (rôle client, admin ou superviseur) au lieu de
    l'Administrateur d'un cabinet ;
  - les patients fictifs sont des patients enregistrés (`vidal_patients`)
    du praticien qui les génère, marqués `est_fictif` ; leur ordonnance
    antérieure fictive (traitements en cours) est rangée sur le patient ;
  - le journal est consultable par le gestionnaire (tout l'établissement)
    et par chaque praticien (ses propres appels) ;
  - l'export XLSX est écrit sans openpyxl (vidal_v2/journal_validation.py).

Le garde-fou « patients fictifs uniquement » est appliqué dans
routes/vidal_appels.py (appeler_vidal), jamais ici, pour qu'aucun chemin
ne l'évite.

Endpoints (préfixe /api/vidal/validation) :
  GET    /etat                         bandeau : mode actif ? identifiants de production ?
  PUT    /mode                         activer / désactiver (confirmation « DESACTIVER »)
  GET    /patients-fictifs             liste des patients fictifs du praticien
  POST   /patients-fictifs             créer / remettre à neuf (idempotent)
  DELETE /patients-fictifs             supprimer (le journal est conservé)
  GET    /journal                      liste filtrable (sans corps ni réponse)
  GET    /journal/export.xlsx | .html  exports
  GET    /journal/{numero}             détail
  PATCH  /journal/{numero}             observation manuelle
"""
import html
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import Body, Depends, HTTPException, Query, Response

from routes.vidal_appels import (
    appeler_vidal, assurer_index, config_prete, est_gestionnaire, mode_validation_actif, portee_etablissement,
)
from vidal_v2 import journal_validation as jv
from vidal_v2.parseurs import parser_entrees_categorisees
from vidal_v2.patients_fictifs import PROFILS, construire_patients_fictifs

CONFIRMATION_DESACTIVATION = "DESACTIVER"
MAX_CANDIDATS = 30

# Recherche VIDAL (sans donnée patient) utilisée pour chaque catégorie de terme.
_RECHERCHES = {
    "ALLERGY": ("/allergies", {}), "MOLECULE": ("/allergies", {}),
    "PATHOLOGY": ("/pathologies", {"type": "CIM10"}), "PRODUCT": ("/products", {}),
}
_SCHEMAS = {"ALLERGY": "allergy", "MOLECULE": "molecule", "PATHOLOGY": "cim10", "PRODUCT": "product"}
# Catégorie du terme -> clé de la liste dans `profil_clinique` et nom affiché du champ.
_CHAMP_PAR_CATEGORIE = {"ALLERGY": ("allergies", "allergies"), "MOLECULE": ("molecules_a_eviter", "molecules"),
                        "PATHOLOGY": ("pathologies", "pathologies")}

_COLONNES_EXPORT = [
    ("numero", "N°"), ("date_utc", "Date/heure (UTC)"), ("date_locale", "Date/heure (Ouagadougou)"), ("type_appel", "Type d'appel"),
    ("methode", "Méthode"), ("url", "URL de la requête (identifiants masqués)"), ("entetes", "En-têtes"), ("corps", "Body envoyé"),
    ("statut_http", "Statut HTTP"), ("reponse", "Valeur du retour"), ("duree_ms", "Délai avant réponse (ms)"),
    ("patient_libelle", "Patient fictif"), ("profil", "Profil clinique"), ("resume_gravites", "Alertes par gravité"),
    ("observations_auto", "Observations automatiques"), ("observation_manuelle", "Observations manuelles"), ("login", "Utilisateur"),
]


def _cellule(cle: str, valeur):
    """Valeur d'une colonne du journal, prête pour une cellule (XLSX) ou une case (HTML)."""
    if valeur is None:
        return ""
    if cle == "date_utc" and isinstance(valeur, datetime):
        return valeur.strftime("%d/%m/%Y %H:%M:%S")
    if isinstance(valeur, dict):
        return ", ".join(f"{k} : {v}" for k, v in valeur.items())
    if isinstance(valeur, list):
        return " ; ".join(str(v) for v in valeur)
    if isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
        return valeur
    return str(valeur)


async def _rechercher_reference(db, cfg: Optional[dict], raison_indisponible: Optional[str], user: dict, cache: dict,
                                categorie: str, terme: str) -> dict:
    """
    Une recherche RÉELLE dans VIDAL (journalisée comme tout appel) :
      - 1 résultat  -> statut "trouve", référence et libellé EXACTEMENT ceux renvoyés par VIDAL ;
      - plusieurs   -> statut "a_choisir" et la liste réelle des résultats (le testeur choisit) ;
      - 0 / erreur / VIDAL non configuré -> statut "a_rechercher" (aucune valeur inventée).
    """
    cle = (categorie, terme.lower())
    if cle in cache:
        return cache[cle]
    if cfg is None:
        resultat = {"statut": "a_rechercher", "raison": f"VIDAL non interrogé : {raison_indisponible}"}
        cache[cle] = resultat
        return resultat
    chemin, extra = _RECHERCHES[categorie]
    try:
        data = await appeler_vidal(db, cfg, user, "GET", chemin, params={"q": terme, **extra})
    except HTTPException as exc:
        data = {"_erreur": {"statut": exc.status_code, "message": str(exc.detail)}}
    if data.get("_erreur"):
        resultat = {"statut": "a_rechercher", "raison": f"Recherche VIDAL en échec ({data['_erreur'].get('statut')}) : {data['_erreur'].get('message')}"}
    else:
        candidats = []
        for e in parser_entrees_categorisees(data.get("raw")):
            if not e.get("vidal_id"):
                continue
            if categorie in ("ALLERGY", "MOLECULE") and e.get("categorie") != categorie:
                continue
            candidats.append({"label": e["title"], "ref": e.get("uri") or f"vidal://{_SCHEMAS[categorie]}/{e['vidal_id']}", "vidal_id": e["vidal_id"]})
        if len(candidats) == 1:
            resultat = {"statut": "trouve", "reference": candidats[0]}
        elif candidats:
            resultat = {"statut": "a_choisir", "candidats": candidats[:MAX_CANDIDATS], "nombre_resultats": len(candidats)}
        else:
            resultat = {"statut": "a_rechercher", "raison": "Aucun résultat VIDAL pour ce terme."}
    cache[cle] = resultat
    return resultat


def _filtre_journal(scope_uid: str, user: dict, depuis, jusqua, profil, type_appel, statut) -> dict:
    """Le gestionnaire voit tout l'établissement ; un praticien, ses propres appels."""
    filtre: Dict[str, Any] = {"scope_uid": scope_uid}
    if not est_gestionnaire(user):
        filtre["user_id"] = user["id"]
    if depuis or jusqua:
        filtre["date_utc"] = {}
        if depuis:
            filtre["date_utc"]["$gte"] = datetime.fromisoformat(depuis)
        if jusqua:
            filtre["date_utc"]["$lte"] = datetime.combine(datetime.fromisoformat(jusqua).date(), time.max)
    if profil:
        filtre["profil"] = profil
    if type_appel:
        filtre["type_appel"] = type_appel
    if statut == "succes":
        filtre["statut_http"] = {"$gte": 200, "$lt": 400}
    elif statut == "erreur":
        filtre["$or"] = [{"statut_http": {"$gte": 400}}, {"statut_http": 0}]
    return filtre


def attach_vidal_validation_routes(*, api, db, get_current_user):
    """Monte les endpoints /api/vidal/validation/* (appelé par routes/vidal.py)."""

    async def _acces_vidal(user: dict) -> str:
        """Même contrôle que les autres pages VIDAL (403 si le module n'est pas activé pour l'établissement)."""
        from routes.vidal import _ensure_tenant_can_access
        await _ensure_tenant_can_access(db, user)
        return await portee_etablissement(db, user)

    async def _entrees(user: dict, depuis, jusqua, profil, type_appel, statut, projection=None) -> list:
        scope_uid = await _acces_vidal(user)
        curseur = db.vidal_journal_validation.find(
            _filtre_journal(scope_uid, user, depuis, jusqua, profil, type_appel, statut), projection or {"_id": 0},
        ).sort("date_utc", -1)
        return await curseur.to_list(length=5000)

    # ---- Mode validation ----
    @api.get("/vidal/validation/etat", tags=["VIDAL — validation"])
    async def etat_validation(user: dict = Depends(get_current_user)):
        """Bandeau de l'interface : mode actif ? URL de production et identifiants configurés ?"""
        from routes.vidal import DEFAULT_PROD_BASE_URL, _clean_vidal_base_url
        scope_uid = await _acces_vidal(user)
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
        return {
            "mode_validation": await mode_validation_actif(db, scope_uid),
            "url_production": _clean_vidal_base_url(s.get("vidal_prod_base_url") or DEFAULT_PROD_BASE_URL),
            "identifiants_production_configures": bool((s.get("vidal_prod_app_id") or "").strip() and (s.get("vidal_prod_app_key") or "").strip()),
            "gestionnaire": est_gestionnaire(user),
        }

    @api.put("/vidal/validation/mode", tags=["VIDAL — validation"])
    async def regler_mode_validation(corps: dict = Body(...), user: dict = Depends(get_current_user)):
        """Active/désactive le mode validation de l'établissement — la désactivation exige « DESACTIVER »."""
        if not est_gestionnaire(user):
            raise HTTPException(status_code=403, detail="Réglage réservé au gestionnaire de l'établissement.")
        scope_uid = await _acces_vidal(user)
        actif = bool(corps.get("mode_validation"))
        if not actif and corps.get("confirmation") != CONFIRMATION_DESACTIVATION:
            raise HTTPException(status_code=422, detail=f"Pour désactiver le mode validation VIDAL, saisissez « {CONFIRMATION_DESACTIVATION} » en confirmation.")
        await assurer_index(db)
        await db.vidal_validation_config.update_one(
            {"scope_uid": scope_uid},
            {"$set": {"scope_uid": scope_uid, "mode_validation": actif, "updated_at": datetime.now(timezone.utc), "updated_by": user.get("email")}},
            upsert=True,
        )
        return {"mode_validation": actif}

    # ---- Patients fictifs ----
    @api.get("/vidal/validation/patients-fictifs", tags=["VIDAL — validation"])
    async def lister_patients_fictifs(user: dict = Depends(get_current_user)):
        await _acces_vidal(user)
        patients = await db.vidal_patients.find(
            {"user_id": user["id"], "est_fictif": True},
            {"_id": 0, "id": 1, "name": 1, "profil_fictif": 1, "code_fictif": 1, "prescriptions_test_validation": 1, "references_a_resoudre": 1},
        ).sort("code_fictif", 1).to_list(length=500)
        return {"patients": patients, "profils": [{"code": p["code"], "libelle": p["libelle"]} for p in PROFILS]}

    @api.post("/vidal/validation/patients-fictifs", tags=["VIDAL — validation"])
    async def generer_patients_fictifs(user: dict = Depends(get_current_user)):
        """Crée (ou REMET À NEUF, de façon idempotente : même code fictif ->
        même patient) les 3 patients de chaque profil clinique, dans les
        patients enregistrés de l'utilisateur. Chaque création / remise à neuf
        passe par le versionnage de l'historique clinique.

        § « Rien ne doit être simulé ni venir des exemples de la
        documentation » : allergies, molécules, pathologies, traitements en
        cours et produits des prescriptions de test sont résolus par de
        VRAIES recherches VIDAL (sans donnée patient, journalisées) ; une
        recherche sans résultat univoque laisse le champ vide, « à choisir »
        (liste réelle) ou « à rechercher dans VIDAL pendant la recette »."""
        from routes.vidal_patients import enregistrer_version_profil_clinique
        await _acces_vidal(user)
        await assurer_index(db)
        try:
            cfg, raison = await config_prete(db, user, quota=False), None
        except HTTPException as exc:
            cfg, raison = None, str(exc.detail)
        cache: dict = {}
        bilan = {"crees": 0, "remis_a_neuf": 0, "versions_creees": 0, "ordonnances_fictives": 0,
                 "vidal_interroge": cfg is not None, "message_vidal": raison,
                 "references_trouvees": 0, "references_a_choisir": 0, "references_a_rechercher": 0}

        def compter(resolution):
            bilan[{"trouve": "references_trouvees", "a_choisir": "references_a_choisir"}.get(resolution["statut"], "references_a_rechercher")] += 1

        maintenant = datetime.now(timezone.utc)
        for item in construire_patients_fictifs():
            doc = dict(item["document"])
            clinique = dict(doc["profil_clinique"])
            a_resoudre = []
            for recherche in item["recherches"]:
                resolution = await _rechercher_reference(db, cfg, raison, user, cache, recherche["categorie"], recherche["recherche"])
                compter(resolution)
                cle, champ = _CHAMP_PAR_CATEGORIE[recherche["categorie"]]
                if resolution["statut"] == "trouve":
                    clinique[cle] = clinique[cle] + [{"label": resolution["reference"]["label"], "ref": resolution["reference"]["ref"]}]
                else:
                    a_resoudre.append({"champ": champ, "recherche": recherche["recherche"], **resolution})
            prescriptions = []
            for t in doc["prescriptions_test_validation"]:
                resolution = await _rechercher_reference(db, cfg, raison, user, cache, "PRODUCT", t["recherche"])
                compter(resolution)
                prescriptions.append({**t, "resolution": resolution})
            doc.update({"profil_clinique": clinique, "prescriptions_test_validation": prescriptions, "references_a_resoudre": a_resoudre})

            # Ordonnance antérieure fictive (traitements en cours du profil « polymédiqué »).
            ordonnances = []
            if item["traitements"]:
                lignes = []
                for nom in item["traitements"]:
                    resolution = await _rechercher_reference(db, cfg, raison, user, cache, "PRODUCT", nom)
                    compter(resolution)
                    trouve = resolution["statut"] == "trouve"
                    lignes.append({
                        "designation": (resolution["reference"]["label"] if trouve else nom).upper(), "duree": "3 mois",
                        "vidal_id": resolution["reference"]["vidal_id"] if trouve else None,
                        "recherche_vidal": None if trouve else nom, "candidats_vidal": resolution.get("candidats", []),
                        "statut_reference": resolution["statut"], "raison_reference": resolution.get("raison"),
                    })
                ordonnances.append({"reference": f"FICTIF-{item['code_fictif']}",
                                    "date_creation": (maintenant - timedelta(days=10)).isoformat(), "lignes": lignes})
                bilan["ordonnances_fictives"] += 1
            doc["ordonnances_fictives"] = ordonnances

            existant = await db.vidal_patients.find_one({"user_id": user["id"], "est_fictif": True, "code_fictif": item["code_fictif"]}, {"_id": 0, "id": 1})
            if existant:
                await db.vidal_patients.update_one({"id": existant["id"]}, {"$set": {**doc, "updated_at": maintenant, "profil_clinique_maj_le": maintenant}})
                pid = existant["id"]
                bilan["remis_a_neuf"] += 1
            else:
                pid = str(uuid.uuid4())
                await db.vidal_patients.insert_one({
                    **doc, "id": pid, "user_id": user["id"], "current_treatments": [], "created_at": maintenant,
                    "updated_at": maintenant, "last_consultation_at": None, "profil_clinique_maj_le": maintenant,
                })
                bilan["crees"] += 1
            patient = await db.vidal_patients.find_one({"id": pid}, {"_id": 0})
            if await enregistrer_version_profil_clinique(db, patient, user, "validation_vidal"):
                bilan["versions_creees"] += 1
        return bilan

    @api.delete("/vidal/validation/patients-fictifs", tags=["VIDAL — validation"])
    async def supprimer_patients_fictifs(user: dict = Depends(get_current_user)):
        """Supprime les patients fictifs de l'utilisateur, leurs sécurisations et
        leur historique clinique. Le journal de validation est CONSERVÉ."""
        await _acces_vidal(user)
        ids = [p["id"] for p in await db.vidal_patients.find({"user_id": user["id"], "est_fictif": True}, {"_id": 0, "id": 1}).to_list(length=1000)]
        await db.vidal_historique_profil_clinique.delete_many({"patient_id": {"$in": ids}})
        await db.vidal_prescription_audit.delete_many({"patient_id": {"$in": ids}, "user_id": user["id"]})
        await db.vidal_patients.delete_many({"user_id": user["id"], "est_fictif": True})
        return {"patients_supprimes": len(ids)}

    # ---- Journal de validation ----
    def _params(depuis=Query(None), jusqua=Query(None), profil=Query(None), type_appel=Query(None),
                statut=Query(None, pattern="^(succes|erreur)$")):
        return dict(depuis=depuis, jusqua=jusqua, profil=profil, type_appel=type_appel, statut=statut)

    @api.get("/vidal/validation/journal", tags=["VIDAL — validation"])
    async def journal_validation(filtres: dict = Depends(_params), user: dict = Depends(get_current_user)):
        """Liste (sans corps ni réponse, voir le détail) + valeurs disponibles pour les filtres."""
        entrees = await _entrees(user, **filtres, projection={"_id": 0, "corps": 0, "reponse": 0})
        tous = await _entrees(user, None, None, None, None, None, {"_id": 0, "profil": 1, "type_appel": 1})
        return {
            "entrees": entrees,
            "profils": sorted({e["profil"] for e in tous if e.get("profil")}),
            "types": sorted({e["type_appel"] for e in tous if e.get("type_appel")}),
        }

    @api.get("/vidal/validation/journal/export.xlsx", tags=["VIDAL — validation"])
    async def export_journal_xlsx(filtres: dict = Depends(_params), user: dict = Depends(get_current_user)):
        """Tableau récapitulatif : une ligne par appel (du plus ancien au plus récent)."""
        entrees = await _entrees(user, **filtres)
        contenu = jv.classeur_xlsx(
            "Journal validation VIDAL", [libelle for _, libelle in _COLONNES_EXPORT],
            [[_cellule(cle, e.get(cle)) for cle, _ in _COLONNES_EXPORT] for e in reversed(entrees)],
        )
        return Response(content=contenu, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="journal_validation_vidal_{date.today().isoformat()}.xlsx"'})

    @api.get("/vidal/validation/journal/export.html", tags=["VIDAL — validation"])
    async def export_journal_html(filtres: dict = Depends(_params), user: dict = Depends(get_current_user)):
        """Synthèse imprimable (HTML autonome) : compteurs par type et statut, puis tableau des appels."""
        entrees = list(reversed(await _entrees(user, **filtres)))
        par_type: Dict[str, int] = {}
        erreurs = 0
        for e in entrees:
            par_type[e.get("type_appel") or "?"] = par_type.get(e.get("type_appel") or "?", 0) + 1
            erreurs += 1 if (e.get("statut_http") or 0) >= 400 or e.get("statut_http") == 0 else 0
        duree_moy = int(sum(e.get("duree_ms") or 0 for e in entrees) / len(entrees)) if entrees else 0

        def h(v, n=None):
            t = "" if v is None else str(_cellule("", v))
            return html.escape(t if n is None or len(t) <= n else t[:n] + " […]")

        lignes = "".join(
            f"<tr><td>{e.get('numero')}</td><td>{h(e.get('date_locale'))}</td><td>{h(e.get('type_appel'))}</td>"
            f"<td class='code'>{h(e.get('methode'))} {h(e.get('url'))}</td><td class='code'>{h(e.get('corps'), 1500)}</td>"
            f"<td>{h(e.get('statut_http'))}</td><td class='code'>{h(e.get('reponse'), 800)}</td><td>{h(e.get('duree_ms'))}</td>"
            f"<td>{h(e.get('patient_libelle'))}<br><small>{h(e.get('profil'))}</small></td>"
            f"<td>{h(e.get('observations_auto'))}<br><b>{h(e.get('observation_manuelle'))}</b></td></tr>"
            for e in entrees
        )
        page = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Journal de validation VIDAL</title>
<style>body{{font-family:Arial,sans-serif;font-size:11px;margin:16px}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:4px;vertical-align:top}}th{{background:#eef2fa}}.code{{font-family:monospace;white-space:pre-wrap;word-break:break-all;max-width:320px}}
@media print{{@page{{size:landscape;margin:10mm}}}}</style></head><body>
<h1>Journal de validation VIDAL — SAWALI</h1>
<p>Édité le {datetime.now().strftime('%d/%m/%Y %H:%M')} — {len(entrees)} appel(s), {erreurs} en erreur, délai moyen {duree_moy} ms.
Identifiants VIDAL masqués (app_id=***, app_key=***). Patients fictifs uniquement.</p>
<p>{' — '.join(f'{html.escape(t)} : {n}' for t, n in sorted(par_type.items()))}</p>
<table><thead><tr><th>N°</th><th>Date/heure (Ouagadougou)</th><th>Type</th><th>Requête</th><th>Body (extrait)</th><th>Statut</th>
<th>Retour (extrait)</th><th>Délai (ms)</th><th>Patient / profil</th><th>Observations</th></tr></thead><tbody>{lignes}</tbody></table>
<p><small>Corps et réponses complets : export XLSX ou détail de chaque appel dans l'application.</small></p></body></html>"""
        return Response(content=page, media_type="text/html; charset=utf-8")

    @api.get("/vidal/validation/journal/{numero}", tags=["VIDAL — validation"])
    async def detail_journal(numero: int, user: dict = Depends(get_current_user)):
        scope_uid = await _acces_vidal(user)
        filtre: Dict[str, Any] = {"numero": numero, "scope_uid": scope_uid}
        if not est_gestionnaire(user):
            filtre["user_id"] = user["id"]
        entree = await db.vidal_journal_validation.find_one(filtre, {"_id": 0})
        if not entree:
            raise HTTPException(status_code=404, detail="Appel introuvable dans le journal.")
        return entree

    @api.patch("/vidal/validation/journal/{numero}", tags=["VIDAL — validation"])
    async def observer_journal(numero: int, corps: dict = Body(...), user: dict = Depends(get_current_user)):
        """Observation manuelle (texte libre, 2000 caractères au plus)."""
        scope_uid = await _acces_vidal(user)
        filtre: Dict[str, Any] = {"numero": numero, "scope_uid": scope_uid}
        if not est_gestionnaire(user):
            filtre["user_id"] = user["id"]
        texte = str(corps.get("observation_manuelle") or "").strip()[:2000]
        r = await db.vidal_journal_validation.update_one(filtre, {"$set": {"observation_manuelle": texte}})
        if r.matched_count == 0:
            raise HTTPException(status_code=404, detail="Appel introuvable dans le journal.")
        return {"numero": numero, "observation_manuelle": texte}
