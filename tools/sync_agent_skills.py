#!/usr/bin/env python3
"""Valida instrucciones y crea enlaces compartidos sin pisar archivos locales."""

import argparse
import os
from pathlib import Path
import re
import sys

try:
    import tomllib
except ImportError:
    import tomli as tomllib

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLES = ("api", "web", "vision", "database", "activity", "jetson", "review")
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def frontmatter(path):
    """Lee YAML real, compartido por SKILL.md y agentes Markdown."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError(f"{path}: falta frontmatter YAML")
    header, body = text[4:].split("\n---\n", 1)
    data = yaml.safe_load(header)
    if not isinstance(data, dict) or not body.strip():
        raise ValueError(f"{path}: metadata o cuerpo vacio")
    return data, body


def validate_sources(root):
    """Comprueba fuentes, rutas de skills y adaptadores sin escribir."""
    skills = sorted((root / "skills").glob("*/SKILL.md"))
    if not skills:
        raise ValueError("No se encontraron skills canonicas")
    names = set()
    for path in skills:
        if path.parent.is_symlink() or path.is_symlink():
            raise ValueError(f"La fuente canonica debe ser un archivo local: {path}")
        data, _ = frontmatter(path)
        name = data.get("name", "")
        description = data.get("description", "")
        if (not isinstance(name, str) or not NAME.fullmatch(name)
                or len(name) > 64 or name != path.parent.name or name in names):
            raise ValueError(f"{path}: nombre invalido o duplicado")
        if (not isinstance(description, str) or not description.strip()
                or len(description) > 1024):
            raise ValueError(f"{path}: descripcion invalida")
        names.add(name)

    documents = [root / "AGENTS.md", root / "README.md", *skills]
    documents.extend(root.glob("*/AGENTS.md"))
    documents.extend(root.glob("api/*/AGENTS.md"))
    for document in documents:
        content = document.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]]+\]\(([^)\n]+)\)", content):
            if "://" in target or target.startswith("#"):
                continue
            local = document.parent / target.split("#", 1)[0]
            if not local.exists():
                raise ValueError(f"{document}: enlace inexistente {target}")

    for role in ROLES:
        name = f"aeye-{role}"
        if name not in names:
            raise ValueError(f"Agente sin skill: {name}")
        path = root / ".codex" / "agents" / f"{name}.toml"
        with path.open("rb") as handle:
            codex = tomllib.load(handle)
        markdown = root / ".opencode" / "agents" / f"{name}.md"
        opencode, instructions = frontmatter(markdown)
        reference = f"skills/{name}/SKILL.md"
        if (codex.get("name") != name or not codex.get("description")
                or reference not in codex.get("developer_instructions", "")
                or opencode.get("mode") != "subagent"
                or not opencode.get("description") or reference not in instructions):
            raise ValueError(f"Adaptador inconsistente: {name}")
        if "model" in codex or "model" in opencode:
            raise ValueError(f"El modelo debe heredarse en {name}")
        if role == "review":
            allowed = {"*": "deny", "read": "allow", "glob": "allow",
                       "grep": "allow", "skill": "allow"}
            if (codex.get("sandbox_mode") != "read-only"
                    or opencode.get("permission") != allowed):
                raise ValueError("El revisor debe conservar permisos restrictivos")

    primary, instructions = frontmatter(root / ".opencode" / "agents" / "aeye.md")
    if (primary.get("mode") != "primary"
            or "skills/aeye-agents/SKILL.md" not in instructions):
        raise ValueError("Orquestador OpenCode invalido")
    expected = {f"aeye-{role}" for role in ROLES}
    for directory, suffix, extra in ((".codex", ".toml", set()),
                                     (".opencode", ".md", {"aeye"})):
        actual = {path.stem for path in (root / directory / "agents").glob(f"aeye*{suffix}")}
        if actual != expected | extra:
            raise ValueError(f"Actualizar ROLES/adaptadores de {directory}")
    return sorted(names)


def synchronize(root, check=False):
    """Prevalida todos los destinos; solo crea enlaces faltantes y relativos."""
    root = Path(root).resolve()
    names = validate_sources(root)
    destination = root / ".agents" / "skills"
    for parent in (destination.parent, destination):
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise ValueError(f"Destino padre no administrable: {parent}")
    if destination.exists():
        unknown = {path.name for path in destination.iterdir()} - set(names)
        if unknown:
            raise ValueError(f"Destinos no administrados; revisar sin borrar: {sorted(unknown)}")

    missing = []
    for name in names:
        path = destination / name
        target = f"../../skills/{name}"
        if path.is_symlink():
            if os.readlink(path) != target or not path.is_dir():
                raise ValueError(f"Enlace conflictivo: {path}")
        elif path.exists():
            raise ValueError(f"No se sobrescribe destino existente: {path}")
        else:
            missing.append((path, target))

    if missing and check:
        raise ValueError("Faltan enlaces; ejecutar sin --check: "
                         + ", ".join(path.name for path, _ in missing))
    if missing:
        destination.mkdir(parents=True, exist_ok=True)
        for path, target in missing:
            path.symlink_to(target, target_is_directory=True)
    return len(names), len(missing)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validar sin escribir")
    args = parser.parse_args()
    try:
        count, created = synchronize(ROOT, check=args.check)
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: {count} skills, {len(ROLES)} pares de agentes; {created} enlaces creados")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
