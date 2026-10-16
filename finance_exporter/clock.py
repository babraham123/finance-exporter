import time
from datetime import datetime, timezone


class Clock:
    """Real time, for everything that waits or reads the time, so tests can substitute virtual time."""

    def now(self):
        return time.monotonic()

    def wait(self, seconds, stop):
        """Wait up to `seconds`; returns True as soon as `stop` is set."""
        return stop.wait(seconds)

    def sleep(self, seconds):
        time.sleep(seconds)

    def today(self):
        return datetime.now(timezone.utc).date()
