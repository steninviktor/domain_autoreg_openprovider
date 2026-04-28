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


if __name__ == "__main__":
    unittest.main()
