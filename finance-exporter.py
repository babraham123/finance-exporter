#!/usr/bin/python3
import argparse
import time
import os
import yaml
import jsonschema
from prometheus_client import start_http_server, Counter, Gauge, Summary, Histogram, REGISTRY
from includes.plugins import PLUGINS
from includes.plugins.base import log
# Debug
from pprint import pformat

DEFAULT_LABELS = ['plugin', 'source', 'ticker']
BUILTIN_METRICS = ('updates', 'quote_time', 'quote_histogram')
METRIC_TYPES = {'Counter': Counter, 'Gauge': Gauge, 'Histogram': Histogram, 'Summary': Summary}
# Top-level keys removed when sources became independent, with how to migrate
REMOVED_KEYS = {
    'tickers': "move the tickers each source should poll into that source's `tickers` list",
    'update_cache_on_startup': 'delete it; labels are no longer shared between sources',
}

class finance:

    def __init__(self, args, registry=REGISTRY):
        self.print_log("Starting up...")
    # Prepare the config
        self.schema_path = f"{os.path.dirname(__file__)}/schema.yaml"
        self.registry = registry
        self.config = dict()
        self.load_config(args.config)
    # Set up -- prefer command line arg to yaml arg
        self.verbose            = args.verbose
        self.debug              = args.debug
        self.config['port']     = next(v for v in [ args.port, self.config.get('port') ] if v is not None)
        self.config['address']  = next(v for v in [ args.address, self.config.get('address') ] if v is not None)
        self.config.setdefault('min_interval', 15)
    # Setup plugins
        self.sources            = self.load_sources()
        self.metrics            = self.load_metrics()
    # Last known label values per (source, ticker), so a quote missing a label field doesn't split the series
        self.label_cache        = dict()
    # Prepare Prometheus Metrics
        self.prom_metrics               = dict()
        self.prom_metrics['updates']    = Counter(self.metric_name('updates'), 'Number of ticker updates', DEFAULT_LABELS, registry=registry)
        self.prom_metrics['quote_time'] = Gauge(self.metric_name('quote_time'), 'Time spent retrieving quote', DEFAULT_LABELS, registry=registry)
    # Response time histogram should not include ticker
        histogram_labels = [ label for label in DEFAULT_LABELS if label != 'ticker' ]
        self.prom_metrics['quote_histogram'] = Histogram(self.metric_name('quote_histogram'),
                                                         'Histogram of quote retrieval times',
                                                         histogram_labels,
                                                         buckets = list(range(1,21)),
                                                         registry = registry)
    # Initialized Configured Metrics
        self.init_metrics()
        self.print_log("Ready to Run...")

    def load_config(self, config_file):
        with open(config_file, 'r') as fd:
        # Expand ${VAR} references so secrets like API keys can live in the environment
            self.config = yaml.safe_load(os.path.expandvars(fd.read()))
        for key, hint in REMOVED_KEYS.items():
            if key in self.config:
                raise Exception(f"Config key `{key}` is no longer supported: {hint}")
        with open(self.schema_path) as fd:
            schema = yaml.safe_load(fd)
        schema['definitions']['source']['properties']['plugin']['enum'] = list(PLUGINS)
        self.print_log("Validating Config...")
        try:
            jsonschema.validate(self.config, schema)
        except jsonschema.ValidationError as e:
            path = "/".join(str(item) for item in e.absolute_path)
            raise Exception(f"Invalid config at {path}: {e.message}")

    def print_config(self):
        redacted = { **self.config, 'sources': [
            { k: ('<redacted>' if k == 'api_key' else v) for k, v in source.items() if k != 'handler' }
            for source in self.config['sources']
        ] }
        self.print_log(pformat(redacted))

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
            if self.verbose:
                self.print_log(f"Preparing metric {name}({metric['type']}) from {metric['source']}")
            labels = self.sources[metric['source']]['label_names']
            self.prom_metrics[name] = METRIC_TYPES[metric['type']](self.metric_name(name), metric['help'], labels, registry=self.registry)

    def start_server(self):
        if self.verbose:
            self.print_log(f"Starting HTTP Server on {self.config['address']}:{self.config['port']}")
        server, _ = start_http_server(int(self.config['port']), addr=self.config['address'], registry=self.registry)
        return server

    def fetch_data(self, source, ticker):
        try:
            return source['handler'].fetch(ticker)
        except Exception as e:
            self.print_log(f"Unable to fetch {ticker} from {source['name']}")
            if self.verbose:
                self.print_log(e)
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
            if self.verbose:
                self.print_log(f"Skipping {name} for {ticker}: {value!r} is not numeric")
            return None

    def update(self, source):
        try:
            source['handler'].begin_poll()
        except Exception as e:
            self.print_log(f"Unable to poll {source['name']}: {e}")
            return
        for ticker in source['tickers']:
            if self.verbose:
                self.print_log(f"Updating ticker {ticker} from {source['name']}")
            start_time = time.time()
            quote = self.fetch_data(source, ticker)
            if quote is None:
                continue
            if self.debug:
                self.print_log(pformat(quote))
            duration = time.time() - start_time
        # Handle labels
            quote_info = self.quote_labels(source, ticker, quote)
            default_info = { label: quote_info[label] for label in DEFAULT_LABELS }
        # Update Metrics
            if self.debug:
                self.print_log(f'Preparing to load metrics with labels: {quote_info}')
            self.prom_metrics['updates'].labels(**default_info).inc()
            self.prom_metrics['quote_time'].labels(**default_info).set(duration)
            self.prom_metrics['quote_histogram'].labels(
                source = source['name'],
                plugin = source['plugin']
            ).observe(duration)
        # Update Configured Metrics
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
            if self.verbose:
                self.print_log(f" - Updated {ticker} from {source['name']} in {duration}s")

    def print_log(self, msg):
        log(msg)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Finance Prometheus Exporter')
    parser.add_argument('-f', '--config', help='Location of config yaml', required=True)
    parser.add_argument('-v', '--verbose', action='store_true', help='Print status to stdout')
    parser.add_argument('-p', '--port', help='Listening port (ip:port or just port)')
    parser.add_argument('-a', '--address', help='Listen address')
    parser.add_argument('-d', '--debug', action="store_true",help="Dump API Data")
    args = parser.parse_args()

# Start up
    f = finance(args)
    if args.debug:
        f.print_log(f'Running with config: ')
        f.print_config()
    f.start_server()

# Track Updates
    last_run = dict()
    for name, source in f.sources.items():
        last_run[name] = 0

# Update in loop
    while True:
        for name, source in f.sources.items():
            if time.time() - last_run[name] > source['interval']:
                if args.verbose:
                    f.print_log(f"Updating Source {name}")
                f.update(source)
                last_run[name] = time.time()
        time.sleep(f.config['min_interval'])
