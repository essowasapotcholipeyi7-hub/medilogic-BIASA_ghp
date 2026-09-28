"""Vérifie que tous les templates Jinja2 (templates/*.html) sont
syntaxiquement valides — blocs {% if %}/{% endif %}, {% for %}/{% endfor %}
correctement fermés et imbriqués, etc. N'a besoin que de jinja2 (déjà une
dépendance de Flask), pas d'app Flask ni de credentials : on parse le
texte du template directement, sans le rendre.

Utile en particulier après une grosse suppression de blocs HTML/Jinja
(ex: retrait d'un onglet entier) — le genre d'erreur (un {% endif %} en
trop ou en moins) ne se voit pas forcément à l'oeil et ne remonte souvent
qu'au moment où un utilisateur ouvre la page concernée."""

from pathlib import Path

import pytest
from jinja2 import Environment, TemplateSyntaxError

RACINE = Path(__file__).resolve().parent.parent
DOSSIER_TEMPLATES = RACINE / "templates"


def _fichiers_templates():
    if not DOSSIER_TEMPLATES.exists():
        return []
    return sorted(DOSSIER_TEMPLATES.rglob("*.html"), key=lambda p: str(p))


FICHIERS_TEMPLATES = _fichiers_templates()

# Env Jinja2 nue, juste pour la validation syntaxique — pas de loader ni de
# contexte Flask (pas besoin : on ne rend rien, on parse seulement).
_ENV = Environment()


@pytest.mark.parametrize(
    "chemin", FICHIERS_TEMPLATES, ids=lambda p: str(p.relative_to(RACINE))
)
def test_template_syntaxe_valide(chemin):
    source = chemin.read_text(encoding="utf-8")
    try:
        _ENV.parse(source, filename=str(chemin))
    except TemplateSyntaxError as e:
        pytest.fail(f"Erreur de syntaxe Jinja2 dans {chemin.relative_to(RACINE)} : {e}")


def test_au_moins_un_template_trouve():
    assert len(FICHIERS_TEMPLATES) > 20
