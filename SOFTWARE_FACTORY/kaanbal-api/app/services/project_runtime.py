"""Detección ligera del runtime de un repositorio generado."""

from pathlib import Path


def detect_project_runtime(app_path: str) -> str:
    """Devuelve php, node, python o generic; Composer tiene prioridad.

    Laravel full-stack incluye composer.json y package.json. Tratarlo primero
    como Node omitiría Composer y los comandos Artisan del pipeline.
    """
    root = Path(app_path)
    if (root / "composer.json").exists():
        return "php"
    if (root / "package.json").exists():
        return "node"
    if (root / "requirements.txt").exists():
        return "python"
    return "generic"
