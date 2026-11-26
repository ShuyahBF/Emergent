"""Garde-fou (lot 470.1) : TOUT fichier Python du serveur doit se compiler.

Le 26/11/2026, une parenthèse fermante perdue dans routes/performance_serveur.py (un commentaire collé dans l'appel) a empêché le démarrage du serveur
sur Render ; aucun test n'importait ce fichier, donc rien ne l'avait vu avant la fusion. Ce test compile chaque fichier du serveur, tests exclus."""
import py_compile
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent


def test_tous_les_fichiers_du_serveur_se_compilent():
    erreurs = []
    with tempfile.TemporaryDirectory() as tmp:
        for f in sorted(RACINE.rglob("*.py")):
            if "tests" in f.relative_to(RACINE).parts or ".venv" in f.parts or "node_modules" in f.parts:
                continue
            try:
                py_compile.compile(str(f), cfile=str(Path(tmp) / (f.name + "c")), doraise=True)
            except py_compile.PyCompileError as exc:
                erreurs.append(f"{f.relative_to(RACINE)} : {exc.msg.strip().splitlines()[-1]}")
    assert not erreurs, "Fichiers qui ne se compilent pas :\n" + "\n".join(erreurs)
