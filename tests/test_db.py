import tempfile
import unittest
from pathlib import Path

from domain_autoreg.db import DomainRepository, init_db


class DomainRepositoryTest(unittest.TestCase):
    def test_import_skips_duplicates_and_lists_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "domains.sqlite3"
            init_db(db_path)
            repo = DomainRepository(db_path)

            imported = repo.import_domains(["example.com", "Example.COM", "second.net"])
            due = repo.get_due_domains(limit=10)

        self.assertEqual(imported, 2)
        self.assertEqual([domain.fqdn for domain in due], ["example.com", "second.net"])
        self.assertTrue(all(domain.created_at for domain in due))

    def test_registered_domain_is_not_due_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "domains.sqlite3"
            init_db(db_path)
            repo = DomainRepository(db_path)
            repo.import_domains(["example.com"])
            domain = repo.get_due_domains(limit=1)[0]

            repo.mark_registered(domain.id, openprovider_domain_id=123, response={"code": 0})
            due = repo.get_due_domains(limit=10)
            registered = repo.list_domains("registered")

        self.assertEqual(due, [])
        self.assertEqual(len(registered), 1)
        self.assertEqual(registered[0].openprovider_domain_id, 123)

    def test_registration_error_sets_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "domains.sqlite3"
            init_db(db_path)
            repo = DomainRepository(db_path)
            repo.import_domains(["example.com"])
            domain = repo.get_due_domains(limit=1)[0]

            repo.mark_registration_failed(domain.id, "API error", cooldown_seconds=300)
            immediately_due = repo.get_due_domains(limit=10)
            failed = repo.list_domains("registration_failed")[0]

        self.assertEqual(immediately_due, [])
        self.assertEqual(failed.last_error, "API error")
        self.assertIsNotNone(failed.next_attempt_at)

    def test_gui_filters_domains_by_operational_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "domains.sqlite3"
            init_db(db_path)
            repo = DomainRepository(db_path)
            repo.import_domains(["new.com", "busy.com", "manual.cz", "done.it", "failed.es"])
            records = {domain.fqdn: domain for domain in repo.list_domains()}

            repo.mark_checked(records["busy.com"].id, {"domain": "busy.com", "status": "active"})
            repo.log_event(
                records["manual.cz"].id,
                "manual.cz",
                "manual_registration_required",
                "Manual registration required",
            )
            repo.mark_registered(records["done.it"].id, openprovider_domain_id=123, response={"code": 0})
            repo.mark_registration_failed(records["failed.es"].id, "API error", cooldown_seconds=300)

            unchecked = repo.list_domains_for_gui("unchecked")
            busy = repo.list_domains_for_gui("busy")
            free = repo.list_domains_for_gui("free")
            registered = repo.list_domains_for_gui("registered")
            errors = repo.list_domains_for_gui("errors")

        self.assertEqual([domain.fqdn for domain in unchecked], ["new.com"])
        self.assertEqual([domain.fqdn for domain in busy], ["busy.com"])
        self.assertEqual([domain.fqdn for domain in free], ["manual.cz"])
        self.assertEqual([domain.fqdn for domain in registered], ["done.it"])
        self.assertEqual([domain.fqdn for domain in errors], ["failed.es"])

    def test_gui_free_filter_uses_latest_domain_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "domains.sqlite3"
            init_db(db_path)
            repo = DomainRepository(db_path)
            repo.import_domains(["flipped.com"])
            domain = repo.list_domains()[0]

            repo.log_event(domain.id, "flipped.com", "manual_registration_required", "Manual registration required")
            repo.mark_checked(domain.id, {"domain": "flipped.com", "status": "active"})

            free = repo.list_domains_for_gui("free")
            busy = repo.list_domains_for_gui("busy")

        self.assertEqual(free, [])
        self.assertEqual([domain.fqdn for domain in busy], ["flipped.com"])

    def test_domain_events_are_listed_newest_first_and_can_be_filtered(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "domains.sqlite3"
            init_db(db_path)
            repo = DomainRepository(db_path)
            repo.import_domains(["example.com", "second.net"])
            records = {domain.fqdn: domain for domain in repo.list_domains()}
            repo.log_event(records["example.com"].id, "example.com", "free", "Domain is free")
            repo.log_event(records["second.net"].id, "second.net", "checked", "Status: active")

            all_events = repo.list_domain_events(limit=10)
            filtered = repo.list_domain_events(limit=10, fqdn="example.com", event_type="free")

        self.assertEqual(all_events[0].fqdn, "second.net")
        self.assertEqual(filtered[0].fqdn, "example.com")
        self.assertEqual(filtered[0].event_type, "free")

    def test_delete_domains_removes_selected_records_and_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "domains.sqlite3"
            init_db(db_path)
            repo = DomainRepository(db_path)
            repo.import_domains(["one.com", "two.com"])
            records = {domain.fqdn: domain for domain in repo.list_domains()}

            deleted = repo.delete_domains([records["one.com"].id])
            remaining = repo.list_domains()
            events = repo.list_domain_events(limit=10, fqdn="one.com")

        self.assertEqual(deleted, 1)
        self.assertEqual([domain.fqdn for domain in remaining], ["two.com"])
        self.assertEqual(events, [])

    def test_delete_all_domains_removes_records_and_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "domains.sqlite3"
            init_db(db_path)
            repo = DomainRepository(db_path)
            repo.import_domains(["one.com", "two.com"])

            deleted = repo.delete_all_domains()
            remaining = repo.list_domains()
            events = repo.list_domain_events(limit=10)

        self.assertEqual(deleted, 2)
        self.assertEqual(remaining, [])
        self.assertEqual(events, [])

    def test_delete_domains_imported_at_least_days_ago_removes_only_busy_records_and_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "domains.sqlite3"
            init_db(db_path)
            repo = DomainRepository(db_path)
            repo.import_domains(["busy.com", "new.com", "free.com", "registered.com", "failed.com"])
            records = {domain.fqdn: domain for domain in repo.list_domains()}
            repo.log_event(records["busy.com"].id, "busy.com", "checked", "Status: active")
            repo.log_event(records["free.com"].id, "free.com", "manual_registration_required", "Manual registration required")
            repo.mark_registered(records["registered.com"].id, openprovider_domain_id=123, response={"code": 0})
            repo.mark_registration_failed(records["failed.com"].id, "API error", cooldown_seconds=300)
            with repo._connect() as conn:
                for fqdn in ["busy.com", "free.com", "registered.com", "failed.com"]:
                    conn.execute("UPDATE domains SET created_at = ? WHERE fqdn = ?", ("2026-04-24T00:00:00+00:00", fqdn))
                conn.execute("UPDATE domains SET created_at = ? WHERE fqdn = ?", ("2026-04-27T00:00:00+00:00", "new.com"))

            deleted = repo.delete_domains_imported_before_days(3, now="2026-04-28T20:00:00+00:00")
            remaining = repo.list_domains()
            busy_events = repo.list_domain_events(limit=10, fqdn="busy.com")

        self.assertEqual(deleted, 1)
        self.assertEqual([domain.fqdn for domain in remaining], ["new.com", "free.com", "registered.com", "failed.com"])
        self.assertEqual(busy_events, [])


if __name__ == "__main__":
    unittest.main()
