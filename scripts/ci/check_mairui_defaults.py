# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml==6.0.3"]
# ///
"""检查会真实调用麦蕊的开关是否保持关闭默认值。"""

from __future__ import annotations

import argparse
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
CONFIG = Path("src/backend/app/config.py")
MODE = "MAIRUI_MODE"
SOURCE = "DAILY_BARS_SOURCE"
ALLOWED = {
    MODE: {"replay", "${MAIRUI_MODE:-replay}"},
    SOURCE: {"off", "${DAILY_BARS_SOURCE:-off}"},
}
CONFIG_DEFAULT = re.compile(r'daily_bars_source:\s*Literal\[[^\]]*\]\s*=\s*"off"')
GENERIC_KEY = re.compile(
    r"^(?:MAIRUI_[A-Z0-9_]*|[A-Z0-9_]*_SOURCE|[A-Z0-9_]*(?:REALTIME|QUOTES|INTRADAY)[A-Z0-9_]*_ENABLED)$"
)
GENERIC_ENV_VAR = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*(?::-(?:off|false|replay|0)?)?\}$|^\$[A-Za-z_][A-Za-z0-9_]*$")
GENERIC_LITERAL = {"", "off", "false", "replay", "0"}
EXEMPT_SUFFIX = re.compile(r"_(?:URL|TIMEOUT[A-Z0-9_]*|KEY[A-Z0-9_]*|TOKEN[A-Z0-9_]*|FILE|DIR|PATH)$")


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
    if value is None or value is False or value == 0:
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
        for key, value in _environment_items(definition.get("environment")):
            if key in ALLOWED and (not isinstance(value, str) or value not in ALLOWED[key]):
                errs.append(f"{rel}:{service}/{key}: 值必须是 {sorted(ALLOWED[key])}（发现 {value!r}）")
            elif _is_generic_switch(key) and not _is_closed_value(value):
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
    values = [value for key, value in _environment_items(ingest.get("environment")) if key == MODE]
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
        if stripped.startswith(f"{MODE}="):
            mode_seen = True
            value = stripped.split("=", 1)[1]
            if value != "replay":
                errs.append(f"{rel}:{MODE}: 值必须为 replay（发现 {value!r}）")
        elif stripped.startswith(f"{SOURCE}="):
            value = stripped.split("=", 1)[1]
            if value != "off":
                errs.append(f"{rel}:{SOURCE}: 值必须为 off（发现 {value!r}）")
        elif "=" in stripped and not stripped.startswith("#"):
            key, value = stripped.split("=", 1)
            if _is_generic_switch(key) and not _is_closed_value(value):
                errs.append(f"{rel}:{key}：默认必须关闭")
    if not mode_seen:
        errs.append(f"{rel}:{MODE}: 必须有一行 MAIRUI_MODE=replay")


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
    if not CONFIG_DEFAULT.search(text):
        errs.append(f"{rel}:daily_bars_source: 必须匹配 Literal 类型且默认值为 off")


def check(repo: Path) -> list[str]:
    repo = repo.resolve()
    errs: list[str] = []
    compose_dir = repo / COMPOSE_DIR
    documents: dict[Path, dict | None] = {}
    if not compose_dir.is_dir():
        errs.append(f"{COMPOSE_DIR.as_posix()}:services/{MODE}: 缺少 compose 目录")
    else:
        files = sorted(compose_dir.glob("*.yml"))
        if not files:
            errs.append(f"{COMPOSE_DIR.as_posix()}:services/{MODE}: 没有 *.yml compose 文件")
        for path in files:
            documents[path.relative_to(repo)] = _check_compose_file(path, repo, errs)
    dev_document = documents.get(DEV_COMPOSE)
    if not (repo / DEV_COMPOSE).is_file():
        errs.append(f"{DEV_COMPOSE.as_posix()}:ingest/{MODE}: 缺少 dev compose 文件")
    _check_dev_ingest(repo, dev_document, errs)
    _check_env_example(repo, errs)
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
