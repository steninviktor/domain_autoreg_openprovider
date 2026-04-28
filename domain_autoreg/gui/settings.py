from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


def update_safe_settings(
    config_path: Path,
    *,
    check_interval_seconds: int,
    batch_size: int,
    max_create_price: float | None,
    allowed_extensions: list[str],
) -> Path:
    if check_interval_seconds <= 0:
        raise ValueError("check_interval_seconds must be positive")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if max_create_price is not None and max_create_price < 0:
        raise ValueError("max_create_price must be non-negative or empty")

    normalized_extensions = _normalize_extensions(allowed_extensions)
    original = config_path.read_text(encoding="utf-8")
    backup_path = _backup_path(config_path)
    shutil.copy2(config_path, backup_path)

    lines = original.splitlines()
    lines = _set_top_level_scalar(lines, "check_interval_seconds", str(check_interval_seconds))
    lines = _set_top_level_scalar(lines, "batch_size", str(batch_size))
    lines = _ensure_section(lines, "registration")
    lines = _set_section_scalar(lines, "registration", "max_create_price", _format_optional_float(max_create_price))
    lines = _set_section_list(lines, "registration", "allowed_extensions", normalized_extensions)
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return backup_path


def _normalize_extensions(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        extension = str(value).strip().lower().lstrip(".")
        if extension and extension not in seen:
            result.append(extension)
            seen.add(extension)
    return result


def _format_optional_float(value: float | None) -> str:
    if value is None:
        return "null"
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def _backup_path(config_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return config_path.with_name(f"{config_path.name}.bak-{timestamp}")


def _set_top_level_scalar(lines: list[str], key: str, value: str) -> list[str]:
    prefix = f"{key}:"
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{key}: {value}"
            return lines
    insert_at = _first_section_index(lines)
    lines.insert(insert_at, f"{key}: {value}")
    return lines


def _ensure_section(lines: list[str], section: str) -> list[str]:
    if any(line == f"{section}:" for line in lines):
        return lines
    if lines and lines[-1].strip():
        lines.append("")
    lines.append(f"{section}:")
    return lines


def _set_section_scalar(lines: list[str], section: str, key: str, value: str) -> list[str]:
    start, end = _section_bounds(lines, section)
    prefix = f"  {key}:"
    for index in range(start + 1, end):
        if lines[index].startswith(prefix):
            lines[index] = f"  {key}: {value}"
            return lines
    lines.insert(start + 1, f"  {key}: {value}")
    return lines


def _set_section_list(lines: list[str], section: str, key: str, values: list[str]) -> list[str]:
    start, end = _section_bounds(lines, section)
    prefix = f"  {key}:"
    for index in range(start + 1, end):
        if lines[index].startswith(prefix):
            remove_to = index + 1
            while remove_to < len(lines) and lines[remove_to].startswith("    - "):
                remove_to += 1
            replacement = [f"  {key}:"] + [f"    - {value}" for value in values]
            return lines[:index] + replacement + lines[remove_to:]
    insertion = [f"  {key}:"] + [f"    - {value}" for value in values]
    return lines[: start + 1] + insertion + lines[start + 1 :]


def _section_bounds(lines: list[str], section: str) -> tuple[int, int]:
    start = next(index for index, line in enumerate(lines) if line == f"{section}:")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index] and not lines[index].startswith(" "):
            end = index
            break
    return start, end


def _first_section_index(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if line.endswith(":") and not line.startswith(" "):
            return index
    return len(lines)
