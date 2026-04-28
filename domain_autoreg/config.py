from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OpenproviderConfig:
    username: str
    password: str
    ip: str = "0.0.0.0"
    base_url: str = "https://api.openprovider.eu/v1beta"


@dataclass(frozen=True)
class RegistrationConfig:
    enabled: bool = False
    period: int = 1
    autorenew: str = "default"
    max_create_price: float | None = 20.0
    allowed_extensions: list[str] = field(default_factory=list)
    owner_handle: str = ""
    admin_handle: str = ""
    tech_handle: str = ""
    billing_handle: str = ""
    ns_group: str | None = None
    name_servers: list[dict[str, Any]] = field(default_factory=list)
    provider: str | None = None


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool = False
    bot_token: str | None = None
    chat_id: str | None = None
    timeout_seconds: int = 10


@dataclass(frozen=True)
class AppConfig:
    database_path: Path
    check_interval_seconds: int
    openprovider: OpenproviderConfig
    registration: RegistrationConfig
    telegram: TelegramConfig
    batch_size: int = 15


def load_config(config_path: Path, env_path: Path | None = None) -> AppConfig:
    env = dict(os.environ)
    if env_path and env_path.exists():
        env.update(_read_env_file(env_path))

    data = _read_yaml(config_path) if config_path.exists() else {}
    username = env.get("OPENPROVIDER_USERNAME", "").strip()
    password = env.get("OPENPROVIDER_PASSWORD", "").strip()
    if not username or not password:
        raise ValueError("OPENPROVIDER_USERNAME and OPENPROVIDER_PASSWORD are required")

    registration_data = data.get("registration", {}) or {}
    telegram_data = data.get("telegram", {}) or {}
    openprovider_data = data.get("openprovider", {}) or {}

    return AppConfig(
        database_path=Path(data.get("database_path", "state/domains.sqlite3")),
        check_interval_seconds=int(data.get("check_interval_seconds", 60)),
        batch_size=int(data.get("batch_size", 15)),
        openprovider=OpenproviderConfig(
            username=username,
            password=password,
            ip=env.get("OPENPROVIDER_IP", "0.0.0.0"),
            base_url=str(openprovider_data.get("base_url", "https://api.openprovider.eu/v1beta")).rstrip("/"),
        ),
        registration=RegistrationConfig(
            enabled=bool(registration_data.get("enabled", False)),
            period=int(registration_data.get("period", 1)),
            autorenew=str(registration_data.get("autorenew", "default")),
            max_create_price=_parse_optional_float(registration_data.get("max_create_price", 20.0)),
            allowed_extensions=_parse_extensions(registration_data.get("allowed_extensions", [])),
            owner_handle=str(registration_data.get("owner_handle", "")),
            admin_handle=str(registration_data.get("admin_handle", "")),
            tech_handle=str(registration_data.get("tech_handle", "")),
            billing_handle=str(registration_data.get("billing_handle", "")),
            ns_group=registration_data.get("ns_group"),
            name_servers=list(registration_data.get("name_servers", []) or []),
            provider=registration_data.get("provider"),
        ),
        telegram=TelegramConfig(
            enabled=bool(telegram_data.get("enabled", False)),
            bot_token=telegram_data.get("bot_token") or env.get("TELEGRAM_BOT_TOKEN"),
            chat_id=str(telegram_data.get("chat_id") or env.get("TELEGRAM_CHAT_ID") or "") or None,
            timeout_seconds=int(telegram_data.get("timeout_seconds", 10)),
        ),
    )


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _read_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(text)
        return loaded or {}
    except ModuleNotFoundError:
        return _read_simple_yaml(text)


def _read_simple_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    lines = text.splitlines()
    stack: list[tuple[int, Any]] = [(-1, root)]
    for index, raw_line in enumerate(lines):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            if isinstance(parent, list):
                parent.append(_parse_scalar(line[2:].strip()))
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            child: dict[str, Any] | list[Any]
            if _next_content_line_is_list(lines, index + 1, indent):
                child = []
            else:
                child = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_scalar(value)
    return root


def _parse_scalar(value: str) -> Any:
    value = value.strip().strip('"').strip("'")
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none", "~"}:
        return None
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _parse_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _parse_extensions(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [part.strip() for part in value.split(",")]
    else:
        values = list(value)
    return [str(item).strip().lower().lstrip(".") for item in values if str(item).strip()]


def _next_content_line_is_list(lines: list[str], start_index: int, current_indent: int) -> bool:
    for raw_line in lines[start_index:]:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        return indent > current_indent and raw_line.strip().startswith("- ")
    return False
