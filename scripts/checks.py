#!/usr/bin/env python3
"""Общие проверки репозитория. Только стандартная библиотека, Python 3.11+.

    python3 scripts/checks.py lint                    decision log + запрещённые файлы
    python3 scripts/checks.py pre-commit              то же + границы областей по индексу
    python3 scripts/checks.py decision-log [--base REF]
    python3 scripts/checks.py forbidden [--staged]
    python3 scripts/checks.py workspaces (--staged | --base REF)
                                         [--owner ID] [--github-login LOGIN] [--branch NAME]
    python3 scripts/checks.py setup OWNER             хуки + запись .workspace-owner
"""

from __future__ import annotations

import argparse
import datetime
import fnmatch
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECISION_LOG = "docs/decision-log.md"
WORKSPACES_FILE = "workspaces.toml"
OWNER_FILE = ".workspace-owner"

# --------------------------------------------------------------------------- decision log

DECISION_RE = re.compile(
    r"^D-(?P<n>[1-9]\d*) \| (?P<date>\d{4}-\d{2}-\d{2}) \| (?P<author>[^|]+?) \| (?P<scope>[^|]+?) \| (?P<text>\S.*)$"
)
SCOPES = ("team", "core", "server", "web")


def decision_lines(text: str) -> list[str]:
    """Строки решений: всё, что начинается с «D-» (без учёта регистра)."""
    return [line for line in text.splitlines() if line[:2].upper() == "D-"]


def check_decision_log(text: str, authors: set[str], base_text: str | None = None) -> list[str]:
    errors = []
    lines = decision_lines(text)
    for position, line in enumerate(lines, start=1):
        match = DECISION_RE.match(line)
        if not match:
            errors.append(
                f"строка не по формату «D-n | ГГГГ-ММ-ДД | автор | область | решение»: {line[:80]}"
            )
            continue
        number = int(match["n"])
        if number != position:
            errors.append(f"D-{number}: ожидался номер D-{position} (нумерация подряд, без пропусков и повторов)")
        try:
            datetime.date.fromisoformat(match["date"])
        except ValueError:
            errors.append(f"D-{number}: несуществующая дата {match['date']}")
        if match["author"] not in authors:
            errors.append(f"D-{number}: автор «{match['author']}» не из списка {sorted(authors)}")
        if match["scope"] not in SCOPES:
            errors.append(f"D-{number}: область «{match['scope']}» не из списка {list(SCOPES)}")
    if base_text is not None:
        for position, old in enumerate(decision_lines(base_text)):
            if position >= len(lines) or lines[position] != old:
                errors.append(
                    f"принятое решение изменено или удалено: «{old[:60]}…». "
                    "Старые строки не правим — отмену или замену записываем новой строкой"
                )
    return errors


# --------------------------------------------------------------------------- рабочие области


def load_workspaces(root: Path = ROOT) -> dict[str, dict]:
    with open(root / WORKSPACES_FILE, "rb") as handle:
        return tomllib.load(handle)["workspaces"]


def path_owner(path: str, workspaces: dict[str, dict]) -> str | None:
    """ID участника, которому принадлежит путь, либо None для общей зоны."""
    for owner, spec in workspaces.items():
        for pattern in spec["paths"]:
            if path == pattern or (pattern.endswith("/") and path.startswith(pattern)):
                return owner
    return None


def resolve_owner(
    workspaces: dict[str, dict],
    explicit: str | None = None,
    github_login: str | None = None,
    branch: str | None = None,
) -> str | None:
    """Кто вносит изменение: явное указание → логин GitHub → префикс ветки «<участник>/…»."""
    if explicit:
        explicit = explicit.strip().lower()
        return explicit if explicit in workspaces else None
    if github_login:
        for owner, spec in workspaces.items():
            if github_login.lower() in (login.lower() for login in spec.get("github", [])):
                return owner
    if branch and "/" in branch:
        prefix = branch.split("/", 1)[0].lower()
        if prefix in workspaces:
            return prefix
    return None


def foreign_changes(paths: list[str], owner: str | None, workspaces: dict[str, dict]) -> dict[str, list[str]]:
    """Изменённые пути в чужих областях: {владелец области: [пути]}."""
    result: dict[str, list[str]] = {}
    for path in paths:
        holder = path_owner(path, workspaces)
        if holder is not None and holder != owner:
            result.setdefault(holder, []).append(path)
    return result


# --------------------------------------------------------------------------- запрещённые файлы

FORBIDDEN_NAMES = (
    "knowledge-base*", "knowledge_base*", "kb.zip",
    "questions.csv", "train.csv", "demo_questions.csv", "demo_output.csv", "submission.csv",
    ".env", ".env.*", "*.sqlite", "*.sqlite3", "*.db",
)
ALLOWED_NAMES = (".env.example",)
ALLOWED_PATHS = ("data/README.md",)
SECRET_RES = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)\b[A-Z0-9_]*(?:api[_-]?key|token|secret|password)\b\s*[=:]\s*[\"']?[A-Za-z0-9_\-./+]{24,}"),
)
SECRET_PRAGMA = "checks:allow"


def forbidden_reason(path: str) -> str | None:
    if path in ALLOWED_PATHS:
        return None
    if path.startswith("data/"):
        return "каталог data/ — только для локальных данных кейса, в репозиторий не попадает"
    name = path.rsplit("/", 1)[-1]
    if name in ALLOWED_NAMES:
        return None
    for pattern in FORBIDDEN_NAMES:
        if fnmatch.fnmatch(name, pattern):
            return f"имя файла совпадает с запрещённым шаблоном «{pattern}» (данные кейса, секреты или база данных)"
    return None


def find_secrets(text: str) -> list[int]:
    """Номера строк, похожих на ключ или пароль."""
    hits = []
    for number, line in enumerate(text.splitlines(), start=1):
        if SECRET_PRAGMA in line:
            continue
        if any(regex.search(line) for regex in SECRET_RES):
            hits.append(number)
    return hits


# --------------------------------------------------------------------------- git и команды


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout if result.returncode == 0 else ""


def changed_paths(staged: bool, base: str | None) -> list[str]:
    if staged:
        out = git("-c", "core.quotePath=false", "diff", "--cached", "--name-only", "--no-renames")
    else:
        out = git("-c", "core.quotePath=false", "diff", "--name-only", "--no-renames", f"{base}...HEAD")
    return [line for line in out.splitlines() if line]


def current_branch() -> str:
    return git("symbolic-ref", "--quiet", "--short", "HEAD", check=False).strip()


def report(title: str, errors: list[str]) -> int:
    if errors:
        print(f"✗ {title}", file=sys.stderr)
        for error in errors:
            print(f"    {error}", file=sys.stderr)
        return 1
    print(f"✓ {title}")
    return 0


def cmd_decision_log(base: str | None) -> int:
    path = ROOT / DECISION_LOG
    if not path.is_file():
        return report("decision log", [f"нет файла {DECISION_LOG}"])
    workspaces = load_workspaces()
    authors = {spec["name"] for spec in workspaces.values()}
    base_text = None
    if base:
        base_text = git("show", f"{base}:{DECISION_LOG}", check=False) or None
    return report("decision log", check_decision_log(path.read_text(encoding="utf-8"), authors, base_text))


def cmd_forbidden(staged: bool) -> int:
    if staged:
        paths = [p for p in changed_paths(True, None) if (ROOT / p).is_file()]
    else:
        paths = [p for p in git("-c", "core.quotePath=false", "ls-files").splitlines() if p]
    errors = []
    for path in paths:
        reason = forbidden_reason(path)
        if reason:
            errors.append(f"{path}: {reason}")
            continue
        file = ROOT / path
        if not file.is_file() or file.stat().st_size > 1_000_000:
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line in find_secrets(text):
            errors.append(f"{path}:{line}: похоже на ключ или пароль (ложное срабатывание — пометьте строку «{SECRET_PRAGMA}»)")
    return report("запрещённые файлы и секреты", errors)


def cmd_workspaces(args: argparse.Namespace) -> int:
    workspaces = load_workspaces()
    explicit = args.owner or os.environ.get("WORKSPACE_OWNER")
    if not explicit and not args.github_login:
        owner_file = ROOT / OWNER_FILE
        if owner_file.is_file():
            explicit = owner_file.read_text(encoding="utf-8").strip()
    branch = args.branch or current_branch()
    owner = resolve_owner(workspaces, explicit, args.github_login, branch)
    foreign = foreign_changes(changed_paths(args.staged, args.base), owner, workspaces)
    title = f"границы рабочих областей (участник: {owner or 'не определён'})"
    if not foreign:
        return report(title, [])
    errors = []
    if owner is None:
        errors.append(
            "не удалось определить участника. Локально: make setup OWNER=<ivan|arthur|andrew>. "
            f"В CI: добавьте свой GitHub-логин в {WORKSPACES_FILE} или назовите ветку <участник>/<тема>"
        )
    for holder, paths in foreign.items():
        errors.append(f"область {workspaces[holder]['name']} ({holder}) — менять может только владелец:")
        errors.extend(f"  {path}" for path in paths)
    errors.append("Нужна правка в чужой области — попросите владельца или опишите её в pull request (см. AGENTS.md).")
    if os.environ.get("ALLOW_CROSS_WORKSPACE") == "1":
        print(f"! {title}: нарушения пропущены по ALLOW_CROSS_WORKSPACE=1", file=sys.stderr)
        for error in errors:
            print(f"    {error}", file=sys.stderr)
        return 0
    return report(title, errors)


def cmd_setup(owner: str) -> int:
    workspaces = load_workspaces()
    owner = owner.strip().lower()
    if owner not in workspaces:
        return report("setup", [f"участник «{owner}» не найден, доступны: {', '.join(workspaces)}"])
    (ROOT / OWNER_FILE).write_text(owner + "\n", encoding="utf-8")
    git("config", "core.hooksPath", ".githooks")
    spec = workspaces[owner]
    print(f"✓ вы — {spec['name']}; ваша область: {', '.join(spec['paths'])}")
    print("✓ git-хуки подключены (.githooks): pre-commit проверяет decision log, запрещённые файлы и границы областей")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("lint")
    sub.add_parser("pre-commit")
    p_log = sub.add_parser("decision-log")
    p_log.add_argument("--base")
    p_forbidden = sub.add_parser("forbidden")
    p_forbidden.add_argument("--staged", action="store_true")
    p_ws = sub.add_parser("workspaces")
    scope = p_ws.add_mutually_exclusive_group(required=True)
    scope.add_argument("--staged", action="store_true")
    scope.add_argument("--base")
    p_ws.add_argument("--owner")
    p_ws.add_argument("--github-login")
    p_ws.add_argument("--branch")
    p_setup = sub.add_parser("setup")
    p_setup.add_argument("owner")
    args = parser.parse_args(argv)

    if args.command == "lint":
        return cmd_decision_log(None) | cmd_forbidden(False)
    if args.command == "pre-commit":
        staged = argparse.Namespace(staged=True, base=None, owner=None, github_login=None, branch=None)
        return cmd_decision_log("HEAD") | cmd_forbidden(True) | cmd_workspaces(staged)
    if args.command == "decision-log":
        return cmd_decision_log(args.base)
    if args.command == "forbidden":
        return cmd_forbidden(args.staged)
    if args.command == "workspaces":
        return cmd_workspaces(args)
    return cmd_setup(args.owner)


if __name__ == "__main__":
    sys.exit(main())
