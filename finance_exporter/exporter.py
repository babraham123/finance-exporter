import logging
import os
from importlib import resources

import jsonschema
import yaml
from prometheus_client import start_http_server, REGISTRY

from .plugins import PLUGINS
from .source import BUILTIN_METRICS, Builtins, Source

log = logging.getLogger(__name__)

# Top-level keys removed when sources became independent, with how to migrate
REMOVED_KEYS = {
    'tickers': "move the tickers each source should poll into that source's `tickers` list",
    'update_cache_on_startup': 'delete it; labels are no longer shared between sources',
}


def live_plugin(plugin_class, source):
    return plugin_class(source, plugin_class.live_client(source))


class Exporter:
    """Builds every configured source against one registry and serves it.

    make_plugin(plugin_class, source) builds each source's plugin; tests pass one that replays recorded responses.
    """

    def __init__(self, config_path, port=None, address=None, registry=REGISTRY, make_plugin=live_plugin):
        self.registry = registry
        self.config = self.load_config(config_path)
        # Command-line values take precedence over the config file
        if port is not None:
            self.config['port'] = port
        if address is not None:
            self.config['address'] = address
        self.config.setdefault('min_interval', 15)
        self.check_names()
        prefix = self.config.get('metric_prefix')
        builtins = Builtins(registry, prefix)
        self.sources = {
            source['name']: Source(source, make_plugin(PLUGINS[source['plugin']], source), registry, builtins, prefix)
            for source in self.config['sources']
        }

    def load_config(self, config_path):
        with open(config_path, 'r') as fd:
            # Expand ${VAR} references so secrets like API keys can live in the environment
            config = yaml.safe_load(os.path.expandvars(fd.read()))
        for key, hint in REMOVED_KEYS.items():
            if key in config:
                raise Exception(f"Config key `{key}` is no longer supported: {hint}")
        schema = yaml.safe_load(resources.files(__package__).joinpath('schema.yaml').read_text())
        schema['definitions']['source']['properties']['plugin']['enum'] = list(PLUGINS)
        try:
            jsonschema.validate(config, schema)
        except jsonschema.ValidationError as e:
            path = "/".join(str(item) for item in e.absolute_path)
            raise Exception(f"Invalid config at {path}: {e.message}")
        return config

    def check_names(self):
        sources = set()
        metrics = dict()
        for source in self.config['sources']:
            if source['name'] in sources:
                raise Exception(f"Source name {source['name']} is used more than once")
            sources.add(source['name'])
            for name in source['metrics']:
                if name in BUILTIN_METRICS:
                    raise Exception(f"Metric {name} in source {source['name']} clashes with a built-in metric")
                if name in metrics:
                    raise Exception(f"Metric {name} is defined by sources {metrics[name]} and {source['name']}; metric names must be unique across sources")
                metrics[name] = source['name']

    def redacted_config(self):
        return { **self.config, 'sources': [
            { k: ('<redacted>' if k == 'api_key' else v) for k, v in source.items() }
            for source in self.config['sources']
        ] }

    def start_server(self):
        log.info(f"Starting HTTP Server on {self.config['address']}:{self.config['port']}")
        server, _ = start_http_server(int(self.config['port']), addr=self.config['address'], registry=self.registry)
        return server
