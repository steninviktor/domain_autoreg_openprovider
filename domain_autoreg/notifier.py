from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from .config import TelegramConfig

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, config: TelegramConfig):
        self.config = config

    def notify(self, text: str) -> None:
        if not self.config.enabled:
            return
        if not self.config.bot_token or not self.config.chat_id:
            logger.warning("Telegram enabled but bot_token/chat_id is missing")
            return
        url = f"https://api.telegram.org/bot{urllib.parse.quote(self.config.bot_token)}/sendMessage"
        payload = json.dumps({"chat_id": self.config.chat_id, "text": text}).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                response.read()
        except urllib.error.URLError as exc:
            logger.warning("Telegram notification failed: %s", exc)
