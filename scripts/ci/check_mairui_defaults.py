# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml==6.0.3"]
# ///
"""检查会真实调用麦蕊的开关是否保持关闭默认值。"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("缺少 pyyaml：uv run --no-project --with pyyaml==6.0.3 python scripts/ci/check_mairui_defaults.py",
          file=sys.stderr)
    raise SystemExit(2)


COMPOSE_DIR = Path("deploy/compose")
DEV_COMPOSE = COMPOSE_DIR / "docker-compose.dev.yml"
ENV_EXAMPLE = Path("deploy/env/.env.example")
WORKFLOW_DIR = Path(".github/workflows")
CONFIG = Path("src/backend/app/config.py")
MODE = "MAIRUI_MODE"
SOURCE = "DAILY_BARS_SOURCE"
ALLOWED = {
    MODE: {"replay", "${MAIRUI_MODE:-replay}"},
    SOURCE: {"off", "${DAILY_BARS_SOURCE:-off}"},
}
GENERIC_KEY = re.compile(
    r"^(?:MAIRUI_[A-Z0-9_]*|[A-Z0-9_]*_SOURCE|[A-Z0-9_]*(?:REALTIME|QUOTES|INTRADAY)[A-Z0-9_]*_ENABLED)$"
)
# 只接受带关闭默认值（含空串）的插值；裸 $VAR、无默认值的 ${VAR} 不算关闭。
GENERIC_ENV_VAR = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*:?-(?:off|false|replay|0)?\}$")
GENERIC_LITERAL = {"", "off", "false", "replay", "0"}
EXEMPT_SUFFIX = re.compile(r"_(?:URL|TIMEOUT[A-Z0-9_]*|KEY[A-Z0-9_]*|TOKEN[A-Z0-9_]*|FILE|DIR|PATH)$")


def _allowed_key(key: object) -> str | None:
    return next((allowed for allowed in ALLOWED if allowed.casefold() == str(key).strip().casefold()), None)


class _ComposeLoader(yaml.SafeLoader):
    """按 Compose 使用的 YAML 1.2 布尔值规则解析，保留未加引号的 off 字符串。"""


_ComposeLoader.yaml_implicit_resolvers = {
    key: [resolver for resolver in resolvers if resolver[0] != "tag:yaml.org,2002:bool"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_ComposeLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


def _environment_items(environment: object):
    if isinstance(environment, dict):
        for key, value in environment.items():
            yield str(key), value
    elif isinstance(environment, list):
        for item in environment:
            if isinstance(item, str):
                key, separator, value = item.partition("=")
                yield key, value if separator else None
            elif isinstance(item, dict):
                for key, value in item.items():
                    yield str(key), value


def _is_closed_value(value: object) -> bool:
    # None 表示 YAML 空值或无等号的列表项，compose 会从主机环境继承，不算关闭。
    if value is None:
        return False
    if value is False or (value == 0 and not isinstance(value, bool)):
        return True
    if isinstance(value, str):
        return value in GENERIC_LITERAL or bool(GENERIC_ENV_VAR.fullmatch(value))
    return False


def _is_generic_switch(key: str) -> bool:
    if key in ALLOWED:
        return False
    if not GENERIC_KEY.fullmatch(key):
        return False
    return not (key.startswith("MAIRUI_") and EXEMPT_SUFFIX.search(key))


def _check_compose_file(path: Path, repo: Path, errs: list[str]) -> dict | None:
    rel = path.relative_to(repo).as_posix()
    try:
        document = yaml.load(path.read_text(encoding="utf-8"), Loader=_ComposeLoader)
    except (OSError, UnicodeDecodeError) as exc:
        errs.append(f"{rel}:services/{MODE}: 无法读取 compose 文件（{type(exc).__name__}）")
        return None
    except yaml.YAMLError as exc:
        errs.append(f"{rel}:services/{MODE}: YAML 无法解析（{getattr(exc, 'problem', None) or type(exc).__name__}）")
        return None
    if not isinstance(document, dict):
        errs.append(f"{rel}:services/{MODE}: compose 顶层必须是映射")
        return None
    services = document.get("services")
    if not isinstance(services, dict):
        errs.append(f"{rel}:services/{MODE}: 缺少 services 映射")
        return document
    for service, definition in services.items():
        if not isinstance(definition, dict):
            continue
        for raw_key, value in _environment_items(definition.get("environment")):
            key = _allowed_key(raw_key)
            if key is not None:
                if not isinstance(value, str) or value not in ALLOWED[key]:
                    errs.append(f"{rel}:{service}/{key}: 值必须是 {sorted(ALLOWED[key])}（发现 {value!r}）")
                continue
            key = str(raw_key).strip()
            if _is_generic_switch(key) and not _is_closed_value(value):
                errs.append(f"{rel}:services/{service}/{key}：默认必须关闭")
    return document


def _check_dev_ingest(repo: Path, document: dict | None, errs: list[str]) -> None:
    rel = DEV_COMPOSE.as_posix()
    where = f"{rel}:ingest/{MODE}"
    if document is None:
        return
    services = document.get("services")
    ingest = services.get("ingest") if isinstance(services, dict) else None
    if not isinstance(ingest, dict):
        errs.append(f"{where}: dev compose 必须存在 ingest 服务，且 MAIRUI_MODE 必须为字面量 replay")
        return
    values = [value for key, value in _environment_items(ingest.get("environment")) if _allowed_key(key) == MODE]
    if values != ["replay"]:
        found = values[0] if values else None
        errs.append(f"{where}: dev compose 必须为字面量 replay（发现 {found!r}）")


def _check_env_example(repo: Path, errs: list[str]) -> None:
    path = repo / ENV_EXAMPLE
    rel = ENV_EXAMPLE.as_posix()
    if not path.is_file():
        errs.append(f"{rel}:MAIRUI_MODE: 缺少文件，必须有 MAIRUI_MODE=replay")
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        errs.append(f"{rel}:MAIRUI_MODE: 无法读取文件（{type(exc).__name__}）")
        return
    mode_seen = False
    for line in lines:
        stripped = line.strip()
        key, _, value = stripped.partition("=")
        key = key.strip()
        allowed_key = _allowed_key(key)
        if allowed_key == MODE:
            mode_seen = True
            if value != "replay":
                errs.append(f"{rel}:{MODE}: 值必须为 replay（发现 {value!r}）")
        elif allowed_key == SOURCE:
            if value != "off":
                errs.append(f"{rel}:{SOURCE}: 值必须为 off（发现 {value!r}）")
        elif (
            "=" in stripped
            and not stripped.startswith("#")
            and _is_generic_switch(key)
            and not _is_closed_value(value)
        ):
            errs.append(f"{rel}:{key}：默认必须关闭")
    if not mode_seen:
        errs.append(f"{rel}:{MODE}: 必须有一行 MAIRUI_MODE=replay")


def _check_workflow_environment(
    environment: object, rel: str, location: str, errs: list[str]
) -> None:
    for key, value in _environment_items(environment):
        key = _allowed_key(key)
        if key is None:
            continue
        if not isinstance(value, str) or value not in ALLOWED[key]:
            errs.append(f"{rel}:{location}/{key}: 值必须是 {sorted(ALLOWED[key])}（发现 {value!r}）")


def _check_workflow_file(path: Path, repo: Path, errs: list[str]) -> None:
    rel = path.relative_to(repo).as_posix()
    try:
        document = yaml.load(path.read_text(encoding="utf-8"), Loader=_ComposeLoader)
    except (OSError, UnicodeDecodeError) as exc:
        errs.append(f"{rel}:workflow: 无法读取 workflow 文件（{type(exc).__name__}）")
        return
    except yaml.YAMLError as exc:
        detail = getattr(exc, "problem", None) or type(exc).__name__
        errs.append(f"{rel}:workflow: YAML 无法解析（{detail}）")
        return
    if not isinstance(document, dict):
        errs.append(f"{rel}:workflow: 顶层必须是映射")
        return

    _check_workflow_environment(document.get("env"), rel, "env", errs)
    jobs = document.get("jobs")
    if not isinstance(jobs, dict):
        return
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        job_location = f"jobs/{job_id}"
        _check_workflow_environment(job.get("env"), rel, f"{job_location}/env", errs)
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for index, step in enumerate(steps):
            if isinstance(step, dict):
                _check_workflow_environment(
                    step.get("env"), rel, f"{job_location}/steps[{index}]/env", errs
                )


def _check_workflows(repo: Path, errs: list[str]) -> None:
    path = repo / WORKFLOW_DIR
    rel = WORKFLOW_DIR.as_posix()
    if not path.is_dir():
        errs.append(f"{rel}:workflow: 缺少 workflows 目录")
        return
    files = sorted([*path.rglob("*.yml"), *path.rglob("*.yaml")])
    if not files:
        errs.append(f"{rel}:workflow: 没有 *.yml 或 *.yaml workflow 文件")
        return
    for workflow in files:
        _check_workflow_file(workflow, repo, errs)


def _is_literal_annotation(annotation: ast.expr) -> bool:
    if not isinstance(annotation, ast.Subscript):
        return False
    value = annotation.value
    return (isinstance(value, ast.Name) and value.id == "Literal") or (
        isinstance(value, ast.Attribute) and value.attr == "Literal"
    )


def _is_constant_off(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value == "off"


def _is_off_default(value: ast.expr) -> bool:
    if _is_constant_off(value):
        return True
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    is_field = (isinstance(func, ast.Name) and func.id == "Field") or (
        isinstance(func, ast.Attribute) and func.attr == "Field"
    )
    if not is_field:
        return False
    default_keywords = [keyword.value for keyword in value.keywords if keyword.arg == "default"]
    if default_keywords:
        return len(default_keywords) == 1 and _is_constant_off(default_keywords[0])
    return bool(value.args) and _is_constant_off(value.args[0])


def _check_config(repo: Path, errs: list[str]) -> None:
    path = repo / CONFIG
    rel = CONFIG.as_posix()
    if not path.is_file():
        errs.append(f"{rel}:daily_bars_source: 缺少文件，必须有默认值 off")
        return
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errs.append(f"{rel}:daily_bars_source: 无法读取文件（{type(exc).__name__}）")
        return
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        errs.append(f"{rel}:daily_bars_source: Python 无法解析（{type(exc).__name__}）")
        return
    declarations: list[ast.AnnAssign] = []
    settings_classes = [
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Settings"
    ]
    for settings in settings_classes:
        for member in settings.body:
            if (
                isinstance(member, ast.AnnAssign)
                and isinstance(member.target, ast.Name)
                and member.target.id == "daily_bars_source"
            ):
                declarations.append(member)
    if len(declarations) != 1:
        errs.append(f"{rel}:daily_bars_source: Settings 中必须恰有一个声明且默认值为 off")
        return
    declaration = declarations[0]
    if not _is_literal_annotation(declaration.annotation) or not _is_off_default(declaration.value):
        errs.append(f"{rel}:daily_bars_source: 必须使用 Literal 注解且默认值为 off")


def check(repo: Path) -> list[str]:
    repo = repo.resolve()
    errs: list[str] = []
    compose_dir = repo / COMPOSE_DIR
    documents: dict[Path, dict | None] = {}
    if not compose_dir.is_dir():
        errs.append(f"{COMPOSE_DIR.as_posix()}:services/{MODE}: 缺少 compose 目录")
    else:
        files = sorted({*compose_dir.glob("*.yml"), *compose_dir.glob("*.yaml")})
        if not files:
            errs.append(f"{COMPOSE_DIR.as_posix()}:services/{MODE}: 没有 *.yml 或 *.yaml compose 文件")
        for path in files:
            documents[path.relative_to(repo)] = _check_compose_file(path, repo, errs)
    dev_document = documents.get(DEV_COMPOSE)
    if not (repo / DEV_COMPOSE).is_file():
        errs.append(f"{DEV_COMPOSE.as_posix()}:ingest/{MODE}: 缺少 dev compose 文件")
    _check_dev_ingest(repo, dev_document, errs)
    _check_env_example(repo, errs)
    _check_workflows(repo, errs)
    _check_config(repo, errs)
    return errs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="检查麦蕊相关开关的默认值")
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    errs = check(ap.parse_args(argv).repo.resolve())
    if errs:
        for error in errs:
            print(f"::error title=mairui-defaults::{error}")
        print(f"check_mairui_defaults: {len(errs)} 处问题")
        return 1
    print("check_mairui_defaults: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
