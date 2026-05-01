import tempfile
import unittest
from pathlib import Path

from domain_autoreg.config import AppConfig, OpenproviderConfig, RegistrationConfig, TelegramConfig
from domain_autoreg.db import DomainRepository, init_db
from domain_autoreg.openprovider import OpenproviderError
from domain_autoreg.service import DomainAutoregService


class FakeClient:
    def __init__(self, check_results, create_response=None):
        self.check_results = check_results
        self.create_response = create_response or {"code": 0, "data": {"id": 456}}
        self.created = []
        self.checked_batches = []

    def check_domains(self, domains):
        self.checked_batches.append([domain.fqdn for domain in domains])
        return [self.check_results[domain.fqdn] for domain in domains]

    def create_domain(self, domain, registration, check_result):
        self.created.append(domain.fqdn)
        return self.create_response


class BatchFailingClient(FakeClient):
    def __init__(self, check_results, failing_domain):
        super().__init__(check_results)
        self.failing_domain = failing_domain

    def check_domains(self, domains):
        self.checked_batches.append([domain.fqdn for domain in domains])
        if any(domain.fqdn == self.failing_domain for domain in domains):
            raise RuntimeError("check failed")
        return [self.check_results[domain.fqdn] for domain in domains]


class CreateFailingClient(FakeClient):
    def __init__(self, check_results, error):
        super().__init__(check_results)
        self.error = error

    def create_domain(self, domain, registration, check_result):
        self.created.append(domain.fqdn)
        raise self.error


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def notify(self, text):
        self.messages.append(text)


class DomainAutoregServiceTest(unittest.TestCase):
    def make_config(self, enabled, allowed_extensions=None, batch_size=15):
        return AppConfig(
            database_path=Path("unused.sqlite3"),
            check_interval_seconds=60,
            batch_size=batch_size,
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

    def test_run_once_treats_create_not_free_error_as_busy_without_notification(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "domains.sqlite3"
            init_db(db_path)
            repo = DomainRepository(db_path)
            repo.import_domains(["race.com"])
            client = CreateFailingClient(
                {"race.com": {"domain": "race.com", "status": "free", "is_premium": False}},
                OpenproviderError('HTTP 500: {"desc":"The domain you want to register is not free!","code":311}'),
            )
            notifier = FakeNotifier()
            service = DomainAutoregService(repo, client, self.make_config(enabled=True, allowed_extensions=["com"]), notifier)

            service.run_once()

            active = repo.list_domains_for_gui("all")
            failed = repo.list_domains("registration_failed")
            events = repo.list_domain_events(limit=1, fqdn="race.com")

        self.assertEqual(client.created, ["race.com"])
        self.assertEqual([domain.fqdn for domain in active], ["race.com"])
        self.assertEqual(active[0].display_status, "занят")
        self.assertIsNone(active[0].last_error)
        self.assertEqual(failed, [])
        self.assertEqual(notifier.messages, [])
        self.assertEqual(events[0].event_type, "checked")

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
        self.assertIsNotNone(active[0].last_check_at)
        self.assertIn("manual.cz освободился, успевай зарегистрировать", notifier.messages)

    def test_run_once_notifies_manual_registration_only_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "domains.sqlite3"
            init_db(db_path)
            repo = DomainRepository(db_path)
            repo.import_domains(["manual.pl"])
            client = FakeClient({"manual.pl": {"domain": "manual.pl", "status": "free", "is_premium": False}})
            notifier = FakeNotifier()
            service = DomainAutoregService(repo, client, self.make_config(enabled=True, allowed_extensions=["it"]), notifier)

            service.run_once()
            service.run_once()

            manual_events = repo.list_domain_events(
                limit=10,
                fqdn="manual.pl",
                event_type="manual_registration_required",
            )

        self.assertEqual(len(notifier.messages), 1)
        self.assertIn("manual.pl", notifier.messages[0])
        self.assertEqual(len(manual_events), 1)

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

    def test_run_once_checks_all_due_domains_in_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "domains.sqlite3"
            init_db(db_path)
            repo = DomainRepository(db_path)
            domains = [f"busy-{index}.com" for index in range(16)]
            repo.import_domains(domains)
            client = FakeClient(
                {
                    domain: {"domain": domain, "status": "active", "reason": "Domain exists"}
                    for domain in domains
                }
            )
            notifier = FakeNotifier()
            service = DomainAutoregService(
                repo,
                client,
                self.make_config(enabled=False, batch_size=5),
                notifier,
            )

            service.run_once()

            checked = repo.list_domains("active")

        self.assertEqual([len(batch) for batch in client.checked_batches], [5, 5, 5, 1])
        self.assertEqual(len([domain for domain in checked if domain.last_check_at]), 16)

    def test_run_once_retries_failed_batch_individually_and_continues(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "domains.sqlite3"
            init_db(db_path)
            repo = DomainRepository(db_path)
            domains = ["ok-one.com", "bad.com", "ok-two.com", "ok-three.com"]
            repo.import_domains(domains)
            client = BatchFailingClient(
                {
                    "ok-one.com": {"domain": "ok-one.com", "status": "active"},
                    "ok-two.com": {"domain": "ok-two.com", "status": "active"},
                    "ok-three.com": {"domain": "ok-three.com", "status": "active"},
                },
                failing_domain="bad.com",
            )
            notifier = FakeNotifier()
            service = DomainAutoregService(
                repo,
                client,
                self.make_config(enabled=False, batch_size=2),
                notifier,
            )

            service.run_once()

            active = {domain.fqdn: domain for domain in repo.list_domains("active")}
            failed = repo.list_domains("registration_failed")

        self.assertEqual(
            client.checked_batches,
            [["ok-one.com", "bad.com"], ["ok-one.com"], ["bad.com"], ["ok-two.com", "ok-three.com"]],
        )
        self.assertIsNotNone(active["ok-one.com"].last_check_at)
        self.assertIsNotNone(active["ok-two.com"].last_check_at)
        self.assertIsNotNone(active["ok-three.com"].last_check_at)
        self.assertEqual([domain.fqdn for domain in failed], ["bad.com"])


if __name__ == "__main__":
    unittest.main()
