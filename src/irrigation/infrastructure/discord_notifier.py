"""Best-effort Discord webhook delivery using only the Python standard library."""

from __future__ import annotations

import json
import logging
import os
import syslog
import threading
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)


class DiscordNotifier:
    """Starts a detached delivery so callers never wait on Discord."""

    def __init__(self, timeout_seconds: float = 5.0) -> None:
        self._timeout_seconds = timeout_seconds

    def send(self, webhook_url: str, message: str) -> None:
        payload = json.dumps(
            {"content": message}, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        if hasattr(os, "fork"):
            self._send_detached(webhook_url, payload)
            return
        thread = threading.Thread(
            target=self._deliver_and_log,
            args=(webhook_url, payload),
            name="discord-webhook",
            daemon=True,
        )
        thread.start()

    def _send_detached(self, webhook_url: str, payload: bytes) -> None:
        first_pid = os.fork()
        if first_pid:
            os.waitpid(first_pid, 0)
            return

        try:
            os.setsid()
            second_pid = os.fork()
            if second_pid:
                os._exit(0)
            self._redirect_standard_streams()
            try:
                self._deliver(webhook_url, payload)
            except Exception as exc:  # best effort must never escape the child
                syslog.syslog(
                    syslog.LOG_WARNING,
                    f"irrigation Discord notification failed: {type(exc).__name__}",
                )
        finally:
            os._exit(0)

    def _deliver_and_log(self, webhook_url: str, payload: bytes) -> None:
        try:
            self._deliver(webhook_url, payload)
        except Exception:
            LOGGER.warning("Discord notification delivery failed", exc_info=True)

    def _deliver(self, webhook_url: str, payload: bytes) -> None:
        request = Request(
            webhook_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "irrigation-core/1.0",
            },
            method="POST",
        )
        with urlopen(request, timeout=self._timeout_seconds) as response:
            status = response.getcode()
            if status < 200 or status >= 300:
                raise OSError(f"Discord returned HTTP {status}")

    @staticmethod
    def _redirect_standard_streams() -> None:
        descriptor = os.open(os.devnull, os.O_RDWR)
        try:
            for target in (0, 1, 2):
                os.dup2(descriptor, target)
        finally:
            if descriptor > 2:
                os.close(descriptor)
