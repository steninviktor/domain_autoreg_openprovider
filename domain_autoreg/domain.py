from __future__ import annotations

from dataclasses import dataclass


MULTI_LABEL_EXTENSIONS = {
    "co.za",
    "net.za",
    "org.za",
    "web.za",
    "co.uk",
    "me.uk",
    "org.uk",
    "com.au",
    "net.au",
    "org.au",
}


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
    if len(labels) >= 3:
        two_label_extension = ".".join(labels[-2:])
        if two_label_extension in MULTI_LABEL_EXTENSIONS:
            return DomainName(
                fqdn=fqdn,
                name=".".join(labels[:-2]),
                extension=two_label_extension,
            )
    return DomainName(fqdn=fqdn, name=".".join(labels[:-1]), extension=labels[-1])
