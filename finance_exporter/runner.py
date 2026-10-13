import logging
import threading
import time

log = logging.getLogger(__name__)


class Clock:
    """Real time. wait() returns True as soon as `stop` is set."""

    def now(self):
        return time.monotonic()

    def wait(self, seconds, stop):
        return stop.wait(seconds)


class Runner:
    """Polls one source every `interval` seconds, start to start, until stopped.

    A poll that overruns its interval is followed immediately by the next; missed polls are not made up.
    """

    def __init__(self, source, clock=None):
        self.source = source
        self.clock = clock or Clock()

    def run(self, stop):
        next_poll = self.clock.now()
        while not stop.is_set():
            try:
                self.source.poll()
            except Exception:
                # A bug in one poll shouldn't end this source's polling for good
                log.exception(f'Poll of {self.source.name} failed')
            next_poll += self.source.interval
            now = self.clock.now()
            next_poll = max(next_poll, now)
            if self.clock.wait(next_poll - now, stop):
                return

    def start(self, stop):
        thread = threading.Thread(target=self.run, args=(stop,), name=f'source-{self.source.name}', daemon=True)
        thread.start()
        return thread
