"""System clock implementation."""

from datetime import datetime


class SystemClock:
    def now(self) -> datetime:
        return datetime.now()
