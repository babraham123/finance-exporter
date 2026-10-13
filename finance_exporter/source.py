import logging
import time
from pprint import pformat

from prometheus_client import Counter, Gauge, Histogram, Summary

log = logging.getLogger(__name__)

DEFAULT_LABELS = ('plugin', 'source', 'ticker')
BUILTIN_METRICS = ('updates', 'fetch_errors', 'poll_seconds')
POLL_SECONDS_BUCKETS = (0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120)
# Quote fields are snapshots, so only metric types that take a value per update are offered
METRIC_TYPES = {
    'Gauge': (Gauge, Gauge.set),
    'Histogram': (Histogram, Histogram.observe),
    'Summary': (Summary, Summary.observe),
}


def metric_name(prefix, name):
    return f'{prefix}_{name}' if prefix else name


class Builtins:
    """Metrics every source reports into, labelled by source."""

    def __init__(self, registry, prefix):
        self.updates = Counter(metric_name(prefix, 'updates'), 'Number of ticker updates', DEFAULT_LABELS, registry=registry)
        self.fetch_errors = Counter(metric_name(prefix, 'fetch_errors'), 'Number of failed ticker fetches', DEFAULT_LABELS, registry=registry)
        self.poll_seconds = Histogram(metric_name(prefix, 'poll_seconds'), "Time to poll all of a source's tickers",
                                      ['plugin', 'source'], buckets=POLL_SECONDS_BUCKETS, registry=registry)


class Source:
    """One configured source: polls its plugin for its tickers and records the quotes as its own metrics."""

    def __init__(self, config, plugin, registry, builtins, prefix=None):
        """config is a SourceConfig; plugin anything with fetch_all(symbols)."""
        self.name = config.name
        self.plugin_name = config.plugin
        self.interval = config.interval
        self.tickers = list(config.tickers)
        self.plugin = plugin
        self.builtins = builtins
        self.labels = config.labels
        self.label_names = list(DEFAULT_LABELS) + [ label for label in self.labels if label not in DEFAULT_LABELS ]
        self.metrics = list()
        for spec in config.metrics:
            metric_class, record = METRIC_TYPES[spec.type]
            metric = metric_class(metric_name(prefix, spec.name), spec.help, self.label_names, registry=registry)
            self.metrics.append((spec, metric, record))
        # Last known label values per ticker, so a quote missing a label field doesn't split the series
        self.label_cache = dict()

    def poll(self):
        start_time = time.monotonic()
        pending = set(self.tickers)
        try:
            for ticker, result in self.plugin.fetch_all(self.tickers):
                pending.discard(ticker)
                if isinstance(result, Exception):
                    log.warning(f'Unable to fetch {ticker} from {self.name}: {result}')
                    self._fetch_failed(ticker)
                elif result is None:
                    log.info(f'No data for {ticker} from {self.name}')
                else:
                    self._record(ticker, result)
        except Exception as e:
            log.warning(f'Unable to poll {self.name}: {e}')
            for ticker in pending:
                self._fetch_failed(ticker)
        finally:
            self.builtins.poll_seconds.labels(plugin=self.plugin_name, source=self.name).observe(time.monotonic() - start_time)

    def _default_labels(self, ticker):
        return {'plugin': self.plugin_name, 'source': self.name, 'ticker': ticker}

    def _fetch_failed(self, ticker):
        self.builtins.fetch_errors.labels(**self._default_labels(ticker)).inc()

    def _record(self, ticker, quote):
        log.debug(pformat(quote))
        labels = self.label_cache.setdefault(ticker, { label: '' for label in self.label_names })
        labels.update(self._default_labels(ticker))
        labels.update({ label: str(quote[field]) for label, field in self.labels.items() if quote.get(field) is not None })
        self.builtins.updates.labels(**self._default_labels(ticker)).inc()
        for spec, metric, record in self.metrics:
            value = self._value(spec, ticker, quote)
            if value is not None:
                record(metric.labels(**labels), value)
        log.info(f'Updated {ticker} from {self.name}')

    def _value(self, spec, ticker, quote):
        value = quote.get(spec.item)
        if value is None:
            return None
        try:
            return float(value) * spec.scale
        except (TypeError, ValueError):
            log.debug(f'Skipping {spec.name} for {ticker}: {value!r} is not numeric')
            return None
