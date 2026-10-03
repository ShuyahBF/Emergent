"""
backend/vidal_v2
--------------------
Lot 56 — cœur « Sécurisation VIDAL v2 » porté depuis Ster : référentiels,
contrôles de saisie, fonction rénale, construction du XML envoyé à VIDAL,
lecture des réponses, traitements en cours, historique clinique, journal de
validation et patients fictifs.

Ces modules n'importent ni FastAPI (sauf `modeles.py`, pour l'erreur 422)
ni MongoDB : la base et l'authentification sont gérées par les routes
(routes/vidal_securisation.py, routes/vidal_patients.py,
routes/vidal_validation.py, routes/vidal_appels.py).
"""
