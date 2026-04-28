import tempfile
import unittest
from pathlib import Path

from domain_autoreg.config import AppConfig, OpenproviderConfig, RegistrationConfig, TelegramConfig
from domain_autoreg.db import DomainRepository, init_db
from domain_autoreg.service import DomainAutoregService


class FakeClient:
    def __init__(self, check_results, create_response=None):
        self.check_results = check_results
        self.create_response = create_response or {"code": 0, "data": {"id": 456}}
        self.created = []

    def check_domains(self, domains):
        return [self.check_results[domain.fqdn] for domain in domains]

    def create_domain(self, domain, registration, check_result):
        self.created.append(domain.fqdn)
        return self.create_response


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def notify(self, text):
        self.messages.append(text)


class DomainAutoregServiceTest(unittest.TestCase):
    def make_config(self, enabled, allowed_extensions=None):
        return AppConfig(
            database_path=Path("unused.sqlite3"),
            check_interval_seconds=60,
            openprovider=OpenproviderConfig(username="u", password="p", ip="0.0.0.0"),
            registration=RegistrationConfig(
                enabled=enabled,
                period=1,
                autorenew="default",
                owner_handle="OWNER",
                admin_handle="ADMIN",
                tech_handle="TECH",
                billing_handle="BILL",
                allowed_extensions=allowed_extensions or [],
            ),
            telegram=TelegramConfig(enabled=False),
        )

    def test_run_once_registers_free_domain_and_notifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "domains.sqlite3"
            init_db(db_path)
            repo = DomainRepository(db_path)
            repo.import_domains(["free.com", "busy.com"])
            client = FakeClient(
                {
                    "free.com": {"domain": "free.com", "status": "free", "is_premium": False},
                    "busy.com": {"domain": "busy.com", "status": "active", "reason": "Domain exists"},
                }
            )
            notifier = FakeNotifier()
            service = DomainAutoregService(repo, client, self.make_config(enabled=True, allowed_extensions=["com"]), notifier)

            service.run_once()

            registered = repo.list_domains("registered")
            active = repo.list_domains("active")

        self.assertEqual(client.created, ["free.com"])
        self.assertEqual([d.fqdn for d in registered], ["free.com"])
        self.assertEqual([d.fqdn for d in active], ["busy.com"])
        self.assertTrue(any("registered" in message for message in notifier.messages))

    def test_run_once_dry_run_does_not_register(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "domains.sqlite3"
            init_db(db_path)
            repo = DomainRepository(db_path)
            repo.import_domains(["free.com"])
            client = FakeClient({"free.com": {"domain": "free.com", "status": "free", "is_premium": False}})
            notifier = FakeNotifier()
            service = DomainAutoregService(repo, client, self.make_config(enabled=False), notifier)

            service.run_once()

            active = repo.list_domains("active")

        self.assertEqual(client.created, [])
        self.assertEqual([d.fqdn for d in active], ["free.com"])
        self.assertTrue(any("dry-run" in message for message in notifier.messages))
        self.assertNotIn("free.com is free", notifier.messages)

    def test_run_once_notifies_manual_registration_for_disallowed_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "domains.sqlite3"
            init_db(db_path)
            repo = DomainRepository(db_path)
            repo.import_domains(["manual.cz"])
            client = FakeClient({"manual.cz": {"domain": "manual.cz", "status": "free", "is_premium": False}})
            notifier = FakeNotifier()
            service = DomainAutoregService(repo, client, self.make_config(enabled=True, allowed_extensions=["it"]), notifier)

            service.run_once()

            active = repo.list_domains("active")

        self.assertEqual(client.created, [])
        self.assertEqual([d.fqdn for d in active], ["manual.cz"])
        self.assertIn("manual.cz освободился, успевай зарегистрировать", notifier.messages)

    def test_run_once_empty_allowed_extensions_disables_automatic_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "domains.sqlite3"
            init_db(db_path)
            repo = DomainRepository(db_path)
            repo.import_domains(["free.com"])
            client = FakeClient({"free.com": {"domain": "free.com", "status": "free", "is_premium": False}})
            notifier = FakeNotifier()
            service = DomainAutoregService(repo, client, self.make_config(enabled=True), notifier)

            service.run_once()

            active = repo.list_domains("active")

        self.assertEqual(client.created, [])
        self.assertEqual([d.fqdn for d in active], ["free.com"])
        self.assertIn("free.com освободился, успевай зарегистрировать", notifier.messages)


if __name__ == "__main__":
    unittest.main()
