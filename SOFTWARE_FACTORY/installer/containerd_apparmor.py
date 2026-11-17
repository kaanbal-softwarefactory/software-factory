#!/usr/bin/env python3
"""Desactiva el perfil AppArmor por defecto de containerd en nodos k3s.

Por qué existe
--------------
En Ubuntu 26.04 con kernels 7.0.0-42 o posteriores, el perfil
``cri-containerd.apparmor.d`` que containerd aplica a cada contenedor niega las
señales que un proceso se envía a sí mismo (``operation="signal"``,
``peer=cri-containerd.apparmor.d//&unconfined``). Los binarios de Go que hacen
``exec`` al arrancar —``gosu`` en las imágenes oficiales de ``mongo`` y
``postgres``— se quedan en un bucle de ``sched_yield`` y nunca lanzan la base.
Con el kernel 7.0.0-38 las denegaciones ya existían pero no colgaban el proceso.

El arreglo es pedirle a containerd que no aplique su perfil
(``disable_apparmor = true``). k3s regenera ``config.toml`` en cada arranque, así
que el cambio va en la plantilla que k3s respeta: ``config-v3.toml.tmpl`` (o
``config.toml.tmpl`` en configuraciones v2). La plantilla se genera a partir del
``config.toml`` que k3s ya escribió, con la única línea añadida.

Uso en un nodo existente (requiere root)::

    sudo python3 containerd_apparmor.py --check
    sudo python3 containerd_apparmor.py --apply && sudo systemctl restart k3s

Después hay que recrear los pods que quedaron colgados (las bases).

Solo biblioteca estándar.
"""

import argparse
import os
import re
import sys

CONTAINERD_DIR = "/var/lib/rancher/k3s/agent/etc/containerd"
APPARMOR_ENABLED_PATH = "/sys/module/apparmor/parameters/enabled"
POLICY_ENV = "KAANBAL_CONTAINERD_APPARMOR"
POLICIES = ("disable", "keep")
MARKER = "# Kaanbal: containerd_apparmor"
HEADER = (
    f"{MARKER} — plantilla generada por el instalador.\n"
    "# disable_apparmor evita que gosu/Go se cuelgue con kernels Ubuntu 7.0.0-42+.\n"
    "# Para volver al comportamiento de k3s: borra este archivo y reinicia k3s.\n"
)

# Sección CRI donde vive disable_apparmor según la versión del config.
_SECTIONS = {
    3: "[plugins.'io.containerd.cri.v1.runtime']",
    2: "[plugins.\"io.containerd.grpc.v1.cri\"]",
}


class TemplateError(ValueError):
    """El config.toml no tiene la forma esperada."""


def config_version(config_text):
    m = re.search(r"^\s*version\s*=\s*(\d+)\s*$", config_text, re.MULTILINE)
    return int(m.group(1)) if m else 2


def template_name(config_text):
    return "config-v3.toml.tmpl" if config_version(config_text) >= 3 else "config.toml.tmpl"


def render_template(config_text):
    """Devuelve la plantilla: el config de k3s con disable_apparmor = true.

    Es idempotente: si la línea ya está, no la duplica. Las líneas de
    comentario iniciales de k3s ("DO NOT EDIT") se sustituyen por la cabecera.
    """
    version = config_version(config_text)
    section = _SECTIONS[3 if version >= 3 else 2]
    lines = config_text.splitlines()
    while lines and lines[0].lstrip().startswith("#"):
        lines.pop(0)

    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == section)
    except StopIteration:
        raise TemplateError(f"no se encontró la sección {section} en config.toml")

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].lstrip().startswith("["):
            end = i
            break

    body = lines[start + 1:end]
    key = re.compile(r"^\s*disable_apparmor\s*=")
    if any(key.match(ln) for ln in body):
        body = ["  disable_apparmor = true" if key.match(ln) else ln for ln in body]
    else:
        body.insert(0, "  disable_apparmor = true")
    lines = lines[:start + 1] + body + lines[end:]
    return HEADER + "\n".join(lines) + "\n"


def apparmor_enabled(path=APPARMOR_ENABLED_PATH):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip().upper().startswith("Y")
    except OSError:
        return False


def policy(environ=None):
    value = (environ if environ is not None else os.environ).get(POLICY_ENV, "disable").strip().lower()
    return value if value in POLICIES else "disable"


def plan(containerd_dir=CONTAINERD_DIR, apparmor_path=APPARMOR_ENABLED_PATH, environ=None):
    """Decide qué hacer sin tocar nada. Devuelve (acción, detalle).

    Acciones: ``skip`` (nada que hacer), ``write`` (escribir la plantilla) o
    ``foreign`` (ya hay una plantilla que no es nuestra: no se toca).
    """
    if policy(environ) == "keep":
        return "skip", f"{POLICY_ENV}=keep: se conserva el perfil AppArmor de containerd"
    if not apparmor_enabled(apparmor_path):
        return "skip", "AppArmor no está activo en el host"
    config = os.path.join(containerd_dir, "config.toml")
    try:
        with open(config, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        return "skip", f"no se pudo leer {config}: {exc.strerror}"
    tmpl = os.path.join(containerd_dir, template_name(text))
    if os.path.exists(tmpl):
        with open(tmpl, encoding="utf-8") as fh:
            current = fh.read()
        if MARKER in current:
            return "skip", f"{tmpl} ya existe (generado por Kaanbal)"
        return "foreign", f"{tmpl} ya existe y no lo generó Kaanbal: no se modifica"
    if re.search(r"^\s*disable_apparmor\s*=\s*true", text, re.MULTILINE):
        return "skip", "containerd ya tiene disable_apparmor = true"
    return "write", tmpl


def apply(containerd_dir=CONTAINERD_DIR, apparmor_path=APPARMOR_ENABLED_PATH, environ=None):
    """Escribe la plantilla si hace falta. Devuelve (acción, detalle).

    Si la acción es ``write``, hay que reiniciar k3s para que surta efecto.
    """
    action, detail = plan(containerd_dir, apparmor_path, environ)
    if action != "write":
        return action, detail
    with open(os.path.join(containerd_dir, "config.toml"), encoding="utf-8") as fh:
        rendered = render_template(fh.read())
    tmp = detail + ".kaanbal-tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(rendered)
    os.chmod(tmp, 0o600)
    os.replace(tmp, detail)
    return "write", detail


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="solo informa qué haría")
    group.add_argument("--apply", action="store_true", help="escribe la plantilla si hace falta")
    parser.add_argument("--containerd-dir", default=CONTAINERD_DIR)
    args = parser.parse_args(argv)
    fn = plan if args.check else apply
    try:
        action, detail = fn(args.containerd_dir)
    except (OSError, TemplateError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{action}: {detail}")
    if action == "write" and args.apply:
        print("reinicia k3s (systemctl restart k3s) y recrea los pods que estaban colgados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
