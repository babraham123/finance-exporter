import logging
import os
import time
from importlib import resources
from pprint import pformat

import jsonschema
import yaml
from prometheus_client import start_http_server, Counter, Gauge, Summary, Histogram, REGISTRY

from .plugins import PLUGINS

log = logging.getLogger(__name__)

DEFAULT_LABELS = ['plugin', 'source', 'ticker']
BUILTIN_METRICS = ('updates', 'quote_time', 'quote_histogram')
METRIC_TYPES = {'Counter': Counter, 'Gauge': Gauge, 'Histogram': Histogram, 'Summary': Summary}
# Top-level keys removed when sources became independent, with how to migrate
REMOVED_KEYS = {
    'tickers': "move the tickers each source should poll into that source's `tickers` list",
    'update_cache_on_startup': 'delete it; labels are no longer shared between sources',
}


class Exporter:

    def __init__(self, config_path, port=None, address=None, registry=REGISTRY):
        log.info("Starting up...")
        self.registry = registry
        self.config = self.load_config(config_path)
        # Command-line values take precedence over the config file
        if port is not None:
            self.config['port'] = port
        if address is not None:
            self.config['address'] = address
        self.config.setdefault('min_interval', 15)
        self.sources = self.load_sources()
        self.metrics = self.load_metrics()
        # Last known label values per (source, ticker), so a quote missing a label field doesn't split the series
        self.label_cache = dict()
        self.prom_metrics = dict()
        self.prom_metrics['updates'] = Counter(self.metric_name('updates'), 'Number of ticker updates', DEFAULT_LABELS, registry=registry)
        self.prom_metrics['quote_time'] = Gauge(self.metric_name('quote_time'), 'Time spent retrieving quote', DEFAULT_LABELS, registry=registry)
        # Response time histogram should not include ticker
        histogram_labels = [ label for label in DEFAULT_LABELS if label != 'ticker' ]
        self.prom_metrics['quote_histogram'] = Histogram(self.metric_name('quote_histogram'),
                                                         'Histogram of quote retrieval times',
                                                         histogram_labels,
                                                         buckets = list(range(1,21)),
                                                         registry = registry)
        self.init_metrics()
        log.info("Ready to Run...")

    def load_config(self, config_path):
        with open(config_path, 'r') as fd:
            # Expand ${VAR} references so secrets like API keys can live in the environment
            config = yaml.safe_load(os.path.expandvars(fd.read()))
        for key, hint in REMOVED_KEYS.items():
            if key in config:
                raise Exception(f"Config key `{key}` is no longer supported: {hint}")
        schema = yaml.safe_load(resources.files(__package__).joinpath('schema.yaml').read_text())
        schema['definitions']['source']['properties']['plugin']['enum'] = list(PLUGINS)
        log.info("Validating Config...")
        try:
            jsonschema.validate(config, schema)
        except jsonschema.ValidationError as e:
            path = "/".join(str(item) for item in e.absolute_path)
            raise Exception(f"Invalid config at {path}: {e.message}")
        return config

    def redacted_config(self):
        return { **self.config, 'sources': [
            { k: ('<redacted>' if k == 'api_key' else v) for k, v in source.items() if k != 'handler' }
            for source in self.config['sources']
        ] }

    def load_sources(self):
        sources = dict()
        for source in self.config['sources']:
            if source['name'] in sources:
                raise Exception(f"Source name {source['name']} is used more than once")
            source['labels']      = source.get('labels') or dict()
            source['label_names'] = DEFAULT_LABELS + [ label for label in source['labels'] if label not in DEFAULT_LABELS ]
            source['handler']     = PLUGINS[source['plugin']](source)
            sources[source['name']] = source
        return sources

    def load_metrics(self):
        metrics = dict()
        for source in self.sources.values():
            for name, metric in source['metrics'].items():
                if name in BUILTIN_METRICS:
                    raise Exception(f"Metric {name} in source {source['name']} clashes with a built-in metric")
                if name in metrics:
                    raise Exception(f"Metric {name} is defined by sources {metrics[name]['source']} and {source['name']}; metric names must be unique across sources")
                metrics[name] = { **metric, 'source': source['name'] }
        return metrics

    def metric_name(self, name):
        prefix = self.config.get('metric_prefix')
        return f"{prefix}_{name}" if prefix else name

    def init_metrics(self):
        for name, metric in self.metrics.items():
            log.info(f"Preparing metric {name}({metric['type']}) from {metric['source']}")
            labels = self.sources[metric['source']]['label_names']
            self.prom_metrics[name] = METRIC_TYPES[metric['type']](self.metric_name(name), metric['help'], labels, registry=self.registry)

    def start_server(self):
        log.info(f"Starting HTTP Server on {self.config['address']}:{self.config['port']}")
        server, _ = start_http_server(int(self.config['port']), addr=self.config['address'], registry=self.registry)
        return server

    def fetch_data(self, source, ticker):
        try:
            return source['handler'].fetch(ticker)
        except Exception as e:
            log.warning(f"Unable to fetch {ticker} from {source['name']}: {e}")
        return None

    # Prepare labels using standard labels, label cache, and quote labels
    def quote_labels(self, source, ticker, quote):
        cache = self.label_cache.setdefault((source['name'], ticker), { label: '' for label in source['label_names'] })
        cache.update({
            'source': source['name'],
            'plugin': source['plugin'],
            'ticker': ticker,
        })
        cache.update({ label: str(quote[field]) for label, field in source['labels'].items() if quote.get(field) is not None })
        return dict(cache)

    def metric_value(self, name, metric, ticker, quote):
        value = quote.get(metric['item'])
        if value is None:
            return None
        try:
            return float(value) * metric.get('scale', 1)
        except (TypeError, ValueError):
            log.debug(f"Skipping {name} for {ticker}: {value!r} is not numeric")
            return None

    def update(self, source):
        try:
            source['handler'].begin_poll()
        except Exception as e:
            log.warning(f"Unable to poll {source['name']}: {e}")
            return
        for ticker in source['tickers']:
            log.info(f"Updating ticker {ticker} from {source['name']}")
            start_time = time.time()
            quote = self.fetch_data(source, ticker)
            if quote is None:
                continue
            duration = time.time() - start_time
            log.debug(pformat(quote))
            quote_info = self.quote_labels(source, ticker, quote)
            default_info = { label: quote_info[label] for label in DEFAULT_LABELS }
            self.prom_metrics['updates'].labels(**default_info).inc()
            self.prom_metrics['quote_time'].labels(**default_info).set(duration)
            self.prom_metrics['quote_histogram'].labels(
                source = source['name'],
                plugin = source['plugin']
            ).observe(duration)
            for name, metric in self.metrics.items():
                if metric['source'] != source['name']:
                    continue
                value = self.metric_value(name, metric, ticker, quote)
                if value is None:
                    continue
                if metric['type'] == 'Counter':
                    self.prom_metrics[name].labels(**quote_info).inc()
                elif metric['type'] == 'Gauge':
                    self.prom_metrics[name].labels(**quote_info).set(value)
                elif metric['type'] in ('Histogram', 'Summary'):
                    self.prom_metrics[name].labels(**quote_info).observe(value)
            log.info(f" - Updated {ticker} from {source['name']} in {duration}s")
