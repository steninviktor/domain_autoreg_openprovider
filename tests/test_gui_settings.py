import tempfile
import unittest
from pathlib import Path

from domain_autoreg.gui.settings import update_safe_settings


class GuiSettingsTest(unittest.TestCase):
    def test_update_safe_settings_only_changes_allowed_fields_and_writes_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "database_path: state/domains.sqlite3",
                        "check_interval_seconds: 60",
                        "batch_size: 15",
                        "registration:",
                        "  enabled: true",
                        "  period: 1",
                        "  autorenew: default",
                        "  max_create_price: 20",
                        "  allowed_extensions:",
                        "    - it",
                        "  owner_handle: OWNER",
                        "telegram:",
                        "  enabled: false",
                    ]
                ),
                encoding="utf-8",
            )

            backup_path = update_safe_settings(
                config_path,
                check_interval_seconds=120,
                batch_size=5,
                max_create_price=12.5,
                allowed_extensions=["fr", ".es", "it"],
            )

            updated = config_path.read_text(encoding="utf-8")
            backup = backup_path.read_text(encoding="utf-8")

        self.assertIn("check_interval_seconds: 120", updated)
        self.assertIn("batch_size: 5", updated)
        self.assertIn("  max_create_price: 12.5", updated)
        self.assertIn("    - fr", updated)
        self.assertIn("    - es", updated)
        self.assertIn("    - it", updated)
        self.assertIn("  enabled: true", updated)
        self.assertIn("  owner_handle: OWNER", updated)
        self.assertIn("check_interval_seconds: 60", backup)

    def test_update_safe_settings_rejects_invalid_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text("registration:\n  enabled: false\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                update_safe_settings(
                    config_path,
                    check_interval_seconds=0,
                    batch_size=1,
                    max_create_price=20,
                    allowed_extensions=["com"],
                )


if __name__ == "__main__":
    unittest.main()
