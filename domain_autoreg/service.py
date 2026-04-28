from __future__ import annotations

import logging
import time

from .config import AppConfig
from .db import DomainRepository, DomainRecord
from .domain import DomainName

logger = logging.getLogger(__name__)


class DomainAutoregService:
    def __init__(self, repo: DomainRepository, client, config: AppConfig, notifier):
        self.repo = repo
        self.client = client
        self.config = config
        self.notifier = notifier

    def run_forever(self) -> None:
        while True:
            self.run_once()
            time.sleep(self.config.check_interval_seconds)

    def run_once(self) -> None:
        due = self.repo.get_due_domains(limit=self.config.batch_size)
        if not due:
            logger.info("No domains due for check")
            return
        for batch in _chunks(due, self.config.batch_size):
            domains = [record.as_domain_name() for record in batch]
            logger.info("Checking %d domains", len(domains))
            results = self.client.check_domains(domains)
            results_by_fqdn = {str(result.get("domain", "")).lower(): result for result in results}
            for record in batch:
                result = results_by_fqdn.get(record.fqdn)
                if result is None:
                    self.repo.mark_registration_failed(record.id, "No check result returned", _cooldown(record.attempts))
                    continue
                self._handle_check_result(record, record.as_domain_name(), result)

    def _handle_check_result(self, record: DomainRecord, domain: DomainName, result: dict) -> None:
        status = str(result.get("status", "")).lower()
        if status != "free":
            self.repo.mark_checked(record.id, result)
            logger.info("%s is not free: %s", record.fqdn, status or "unknown")
            return

        self.repo.log_event(record.id, record.fqdn, "free", "Domain is free", result)
        if not self.config.registration.enabled:
            logger.info("%s is free, dry-run mode prevents registration", record.fqdn)
            self.repo.log_event(record.id, record.fqdn, "dry_run", "Registration disabled", result)
            self.notifier.notify(f"{record.fqdn} is free, dry-run registration skipped")
            return

        if domain.extension not in self.config.registration.allowed_extensions:
            logger.info("%s is free, manual registration required for .%s", record.fqdn, domain.extension)
            self.repo.log_event(record.id, record.fqdn, "manual_registration_required", "Manual registration required", result)
            self.notifier.notify(f"{record.fqdn} освободился, успевай зарегистрировать")
            return

        try:
            response = self.client.create_domain(domain, self.config.registration, result)
            openprovider_domain_id = ((response.get("data") or {}).get("id"))
            self.repo.mark_registered(record.id, openprovider_domain_id, response)
            logger.info("%s registered", record.fqdn)
            self.notifier.notify(f"{record.fqdn} registered")
        except Exception as exc:
            message = str(exc)
            cooldown = _cooldown(record.attempts + 1)
            self.repo.mark_registration_failed(record.id, message, cooldown)
            logger.warning("%s registration failed: %s", record.fqdn, message)
            self.notifier.notify(f"{record.fqdn} registration failed: {message}")


def _chunks(records: list[DomainRecord], size: int):
    for index in range(0, len(records), size):
        yield records[index : index + size]


def _cooldown(attempts: int) -> int:
    return min(3600, 300 * max(1, attempts))
