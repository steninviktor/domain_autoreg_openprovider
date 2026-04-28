from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import load_config
from .db import DomainRepository, init_db
from .notifier import TelegramNotifier
from .openprovider import OpenproviderClient
from .service import DomainAutoregService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="domain-autoreg")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--log-file", default="domain-autoreg.log")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db")

    import_parser = subparsers.add_parser("import")
    import_parser.add_argument("path")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--once", action="store_true")

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--status", choices=["active", "registered", "registration_failed"])

    args = parser.parse_args(argv)
    _setup_logging(Path(args.log_file))
    config = load_config(Path(args.config), Path(args.env))

    if args.command == "init-db":
        init_db(config.database_path)
        print(f"Initialized {config.database_path}")
        return 0

    repo = DomainRepository(config.database_path)
    if args.command == "import":
        init_db(config.database_path)
        domains = Path(args.path).read_text(encoding="utf-8").splitlines()
        imported = repo.import_domains(domains)
        print(f"Imported {imported} new domains")
        return 0

    if args.command == "list":
        for domain in repo.list_domains(args.status):
            print(f"{domain.fqdn}\t{domain.status}\t{domain.last_error or ''}")
        return 0

    if args.command == "run":
        init_db(config.database_path)
        service = DomainAutoregService(
            repo,
            OpenproviderClient(config.openprovider),
            config,
            TelegramNotifier(config.telegram),
        )
        if args.once:
            service.run_once()
        else:
            service.run_forever()
        return 0

    parser.error("unknown command")
    return 2


def _setup_logging(log_file: Path) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_file, encoding="utf-8")],
    )


if __name__ == "__main__":
    raise SystemExit(main())
