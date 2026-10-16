import logging
import threading

from prometheus_client import start_http_server, REGISTRY

from .clock import Clock
from .metrics import Metrics
from .plugins import build_plugin, live_client
from .runner import Runner
from .source import Source

log = logging.getLogger(__name__)
# How long stop() waits for a poll in progress before returning anyway
SHUTDOWN_GRACE_SECONDS = 10


class Exporter:
    """Every configured source, polling on its own schedule into one registry, served over HTTP.

    clients(source_config) gives each source's plugin its client; tests pass one that replays recorded responses.
    """

    def __init__(self, config, clients=live_client, clock=None, registry=REGISTRY):
        self.config = config
        self.clock = clock or Clock()
        self.registry = registry
        metrics = Metrics(registry, config.metric_prefix)
        self.sources = [
            Source(source, build_plugin(source, clients(source), self.clock), metrics)
            for source in config.sources
        ]
        self.stopping = threading.Event()
        self.server = None
        self.threads = list()

    def poll(self):
        """Poll every source once, in turn, on the calling thread."""
        for source in self.sources:
            source.poll()

    def start(self):
        """Serve metrics and start polling every source. Returns the port served on."""
        log.info(f"Starting HTTP Server on {self.config.address}:{self.config.port}")
        self.server, _ = start_http_server(self.config.port, addr=self.config.address, registry=self.registry)
        # Each source polls on its own thread, so one source's slow or throttled provider never delays another
        self.threads = [ Runner(source, self.clock).start(self.stopping) for source in self.sources ]
        return self.server.server_port

    def stop(self):
        """Stop polling and serving, waiting up to SHUTDOWN_GRACE_SECONDS per source for a poll in progress."""
        self.stopping.set()
        self.server.shutdown()
        self.server.server_close()
        for thread in self.threads:
            thread.join(SHUTDOWN_GRACE_SECONDS)
