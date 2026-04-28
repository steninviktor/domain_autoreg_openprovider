import unittest
from unittest.mock import patch

from domain_autoreg.cli import main


class CliTest(unittest.TestCase):
    def test_gui_starts_without_loading_openprovider_credentials_first(self):
        with patch("domain_autoreg.gui.web.serve_gui") as serve_gui:
            result = main(["--config", "missing.yaml", "--env", "missing.env", "gui", "--port", "0"])

        self.assertEqual(result, 0)
        serve_gui.assert_called_once()


if __name__ == "__main__":
    unittest.main()
