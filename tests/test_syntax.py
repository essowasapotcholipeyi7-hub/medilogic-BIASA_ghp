"""Vérifie que tous les fichiers Python du dépôt sont syntaxiquement
valides. Ne nécessite aucune dépendance (ast est dans la bibliothèque
standard) ni credentials — ast.parse() lit le code source sans jamais
l'exécuter ni l'importer. Filet de sécurité bon marché : une bonne partie
des incidents de cette session (déploiements Render cassés, régressions
lors des gros retraits de code) étaient des erreurs de syntaxe qu'un
simple `ast.parse` aurait attrapées avant le push."""

import ast
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent

# Dossiers qu'on ne veut pas parcourir (environnements virtuels, cache,
# dépendances éventuellement vendorisées).
DOSSIERS_EXCLUS = {".git", "__pycache__", "venv", ".venv", "env", "node_modules", ".claude"}


def _fichiers_python():
    for chemin in RACINE.rglob("*.py"):
        # ⭐ IMPORTANT : vérifier chemin.parts (chemin ABSOLU) plutôt que
        # les parts relatives à RACINE exclut TOUT dès que le dépôt
        # lui-même se trouve sous un dossier ancêtre nommé comme un des
        # DOSSIERS_EXCLUS — ex: un git worktree sous
        # .../.claude/worktrees/<nom>/ (le cas dans ce dépôt) : ".claude"
        # apparaît alors dans le chemin absolu de CHAQUE fichier, et
        # `chemin.parts` (repéré en test local) videait la liste à zéro.
        relatif = chemin.relative_to(RACINE)
        if any(partie in DOSSIERS_EXCLUS for partie in relatif.parts):
            continue
        yield chemin


FICHIERS_PYTHON = sorted(_fichiers_python(), key=lambda p: str(p))


@pytest.mark.parametrize("chemin", FICHIERS_PYTHON, ids=lambda p: str(p.relative_to(RACINE)))
def test_syntaxe_valide(chemin):
    source = chemin.read_text(encoding="utf-8")
    try:
        ast.parse(source, filename=str(chemin))
    except SyntaxError as e:
        pytest.fail(f"Erreur de syntaxe dans {chemin.relative_to(RACINE)} : {e}")


def test_au_moins_un_fichier_trouve():
    """Garde-fou : si ce test échoue, c'est que la découverte de fichiers
    elle-même est cassée (mauvais dossier, filtre trop large) — sans lui,
    les tests ci-dessus pourraient silencieusement ne rien vérifier du
    tout."""
    assert len(FICHIERS_PYTHON) > 50
