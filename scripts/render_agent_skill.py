#!/usr/bin/env python3
"""Render the canonical Envman agent skill from source-controlled facts."""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
CLI_FILE = ROOT / "src" / "envman" / "cli.py"
SKILL_FILE = ROOT / ".agents" / "skills" / "envman-environment-variable-manager" / "SKILL.md"
SOURCE_MARKER = "src/envman/cli.py"
LOCK_PATTERN = re.compile(
    r"(?m)^<!-- envman-skill-lock: version=[^ ]+ source=[^ ]+ -->$"
)
COMMAND_BLOCK_PATTERN = re.compile(
    r"(?ms)^<!-- BEGIN GENERATED COMMANDS -->\n.*?^<!-- END GENERATED COMMANDS -->$"
)
DOC_LINK_PATTERN = re.compile(
    r"(https://github\.com/CruxExperts/envman/blob/)v\d+\.\d+\.\d+(/docs/)"
)


def read_version() -> str:
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not version or "\n" in version or "\r" in version:
        raise ValueError(f"{VERSION_FILE} must contain one non-empty version line")
    return version


def _constant_strings(tree: ast.AST) -> dict[str, str]:
    constants: dict[str, str] = {}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = node.value.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str) and isinstance(node.target, ast.Name):
                constants[node.target.id] = node.value.value
    return constants


def _string_value(node: ast.AST, constants: dict[str, str]) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif (
                isinstance(value, ast.FormattedValue)
                and isinstance(value.value, ast.Name)
                and value.value.id in constants
            ):
                parts.append(constants[value.value.id])
            else:
                raise ValueError("CLI parser help contains an unsupported expression")
        return "".join(parts)
    raise ValueError("CLI parser command help must be a string literal")


def extract_commands() -> list[tuple[str, str]]:
    tree = ast.parse(CLI_FILE.read_text(encoding="utf-8"), filename=str(CLI_FILE))
    constants = _constant_strings(tree)
    parser_function = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "build_cli_parser"
        ),
        None,
    )
    if parser_function is None:
        raise ValueError("src/envman/cli.py does not define build_cli_parser()")

    commands: list[tuple[str, str]] = []
    for node in ast.walk(parser_function):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "command":
            call_kind = "command"
        elif (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_parser"
            and node.args
        ):
            call_kind = "add_parser"
        else:
            continue
        if (
            not node.args
            or not isinstance(node.args[0], ast.Constant)
            or not isinstance(node.args[0].value, str)
        ):
            if call_kind == "add_parser":
                continue
            raise ValueError(f"{call_kind}() command name must be a string literal")
        help_node = next((keyword.value for keyword in node.keywords if keyword.arg == "help"), None)
        if help_node is None:
            raise ValueError(f"{call_kind}({node.args[0].value!r}) is missing help text")
        commands.append((node.args[0].value, " ".join(_string_value(help_node, constants).split())))

    if not commands:
        raise ValueError("No CLI commands found in build_cli_parser()")
    names = [name for name, _ in commands]
    if len(names) != len(set(names)):
        raise ValueError("CLI parser contains duplicate command names")
    return commands


def _generated_command_block(commands: list[tuple[str, str]]) -> str:
    rows = [
        "<!-- BEGIN GENERATED COMMANDS -->",
        "| Command | Purpose |",
        "| --- | --- |",
    ]
    for name, help_text in commands:
        rows.append(f"| `{name}` | {help_text.replace('|', r'\|')} |")
    rows.append("<!-- END GENERATED COMMANDS -->")
    return "\n".join(rows)


def render_skill(source: str, version: str, commands: list[tuple[str, str]]) -> str:
    lock = f"<!-- envman-skill-lock: version={version} source={SOURCE_MARKER} -->"
    if len(LOCK_PATTERN.findall(source)) != 1:
        raise ValueError("SKILL.md must contain exactly one Envman skill lock marker")
    if len(COMMAND_BLOCK_PATTERN.findall(source)) != 1:
        raise ValueError("SKILL.md must contain exactly one generated command block")
    rendered = LOCK_PATTERN.sub(lock, source)
    rendered = COMMAND_BLOCK_PATTERN.sub(_generated_command_block(commands), rendered)
    return DOC_LINK_PATTERN.sub(rf"\g<1>v{version}\g<2>", rendered)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if SKILL.md is not renderer-parity.")
    arguments = parser.parse_args(argv)
    try:
        source = SKILL_FILE.read_text(encoding="utf-8")
        rendered = render_skill(source, read_version(), extract_commands())
    except (OSError, SyntaxError, ValueError) as exc:
        print(f"render_agent_skill.py: {exc}", file=sys.stderr)
        return 1
    if arguments.check:
        if source != rendered:
            print(f"{SKILL_FILE} is out of date; run scripts/render_agent_skill.py", file=sys.stderr)
            return 1
        return 0
    if source != rendered:
        SKILL_FILE.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
