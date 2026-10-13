import logging

from prometheus_client import start_http_server, REGISTRY

from .plugins import PLUGINS
from .source import Builtins, Source

log = logging.getLogger(__name__)


def live_plugin(plugin_class, source):
    return plugin_class(source.settings, plugin_class.live_client(source.settings))


class Exporter:
    """Builds every configured source against one registry and serves it.

    make_plugin(plugin_class, source_config) builds each source's plugin; tests pass one that replays recorded responses.
    """

    def __init__(self, config, registry=REGISTRY, make_plugin=live_plugin):
        self.config = config
        self.registry = registry
        builtins = Builtins(registry, config.metric_prefix)
        self.sources = {
            source.name: Source(source, make_plugin(PLUGINS[source.plugin], source), registry, builtins, config.metric_prefix)
            for source in config.sources
        }

    def start_server(self):
        log.info(f"Starting HTTP Server on {self.config.address}:{self.config.port}")
        server, _ = start_http_server(int(self.config.port), addr=self.config.address, registry=self.registry)
        return server
