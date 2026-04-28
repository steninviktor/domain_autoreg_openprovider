import os
import tempfile
import unittest
from pathlib import Path

from domain_autoreg.config import load_config


class ConfigTest(unittest.TestCase):
    def test_load_config_reads_env_and_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = root / ".env"
            config_path = root / "config.yaml"
            env_path.write_text(
                "\n".join(
                    [
                        "OPENPROVIDER_USERNAME=user",
                        "OPENPROVIDER_PASSWORD=secret",
                        "OPENPROVIDER_IP=0.0.0.0",
                    ]
                ),
                encoding="utf-8",
            )
            config_path.write_text(
                "\n".join(
                    [
                        "database_path: state/domains.sqlite3",
                        "check_interval_seconds: 60",
                        "registration:",
                        "  enabled: false",
                        "  period: 1",
                        "  autorenew: default",
                        "  owner_handle: OWNER",
                        "  admin_handle: ADMIN",
                        "  tech_handle: TECH",
                        "  billing_handle: BILL",
                        "  ns_group: default",
                        "  max_create_price: 20",
                        "  allowed_extensions:",
                        "    - it",
                        "    - .es",
                        "telegram:",
                        "  enabled: true",
                        "  bot_token: token",
                        "  chat_id: '123'",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_config(config_path, env_path)

        self.assertEqual(config.openprovider.username, "user")
        self.assertEqual(config.database_path, Path("state/domains.sqlite3"))
        self.assertFalse(config.registration.enabled)
        self.assertEqual(config.registration.owner_handle, "OWNER")
        self.assertEqual(config.registration.max_create_price, 20)
        self.assertEqual(config.registration.allowed_extensions, ["it", "es"])
        self.assertTrue(config.telegram.enabled)
        self.assertEqual(config.telegram.chat_id, "123")

    def test_load_config_fails_when_credentials_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.yaml"
            config_path.write_text("registration:\n  enabled: false\n", encoding="utf-8")

            old_username = os.environ.pop("OPENPROVIDER_USERNAME", None)
            old_password = os.environ.pop("OPENPROVIDER_PASSWORD", None)
            try:
                with self.assertRaises(ValueError):
                    load_config(config_path, root / ".missing-env")
            finally:
                if old_username is not None:
                    os.environ["OPENPROVIDER_USERNAME"] = old_username
                if old_password is not None:
                    os.environ["OPENPROVIDER_PASSWORD"] = old_password


if __name__ == "__main__":
    unittest.main()
