from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainName:
    fqdn: str
    name: str
    extension: str
    id: int | None = None


def parse_domain(value: str) -> DomainName:
    fqdn = value.strip().lower().rstrip(".")
    if not fqdn or "." not in fqdn:
        raise ValueError(f"Invalid domain: {value!r}")
    labels = fqdn.split(".")
    if any(not label for label in labels):
        raise ValueError(f"Invalid domain: {value!r}")
    if len(labels) < 2:
        raise ValueError(f"Invalid domain: {value!r}")
    return DomainName(fqdn=fqdn, name=".".join(labels[:-1]), extension=labels[-1])
