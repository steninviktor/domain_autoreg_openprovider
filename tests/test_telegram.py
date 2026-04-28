import json
import unittest
from unittest.mock import patch

from domain_autoreg.config import TelegramConfig
from domain_autoreg.notifier import TelegramNotifier


class TelegramNotifierTest(unittest.TestCase):
    def test_notify_posts_message_when_enabled(self):
        calls = []

        def fake_urlopen(request, timeout):
            calls.append((request.full_url, json.loads(request.data.decode("utf-8")), timeout))

            class Response:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def read(self):
                    return b'{"ok": true}'

            return Response()

        notifier = TelegramNotifier(TelegramConfig(enabled=True, bot_token="token", chat_id="123"))

        with patch("urllib.request.urlopen", fake_urlopen):
            notifier.notify("domain registered")

        self.assertEqual(len(calls), 1)
        self.assertIn("/bottoken/sendMessage", calls[0][0])
        self.assertEqual(calls[0][1]["chat_id"], "123")
        self.assertEqual(calls[0][1]["text"], "domain registered")

    def test_notify_noops_when_disabled(self):
        notifier = TelegramNotifier(TelegramConfig(enabled=False))
        notifier.notify("nothing happens")


if __name__ == "__main__":
    unittest.main()
