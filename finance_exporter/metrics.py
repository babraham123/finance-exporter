"""The exporter's metric namespace: the built-ins every source reports into, and each source's own metrics."""

import logging

from prometheus_client import Counter, Gauge, Histogram, Info, Summary

log = logging.getLogger(__name__)

DEFAULT_LABELS = ("plugin", "source", "ticker")
BUILTIN_METRICS = ("updates", "fetch_errors", "poll_seconds")
POLL_SECONDS_BUCKETS = (0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120)
# Quote fields are snapshots, so only metric types that take a value per update are offered
METRIC_TYPES = {
    "Gauge": (Gauge, Gauge.set),
    "Histogram": (Histogram, Histogram.observe),
    "Summary": (Summary, Summary.observe),
}


class Metrics:
    """Every metric the exporter exports, in one registry, under one prefix."""

    def __init__(self, registry, prefix=None):
        self.registry = registry
        self.prefix = prefix
        self.updates = Counter(
            self.name("updates"), "Number of ticker updates", DEFAULT_LABELS, registry=registry
        )
        self.fetch_errors = Counter(
            self.name("fetch_errors"),
            "Number of failed ticker fetches",
            DEFAULT_LABELS,
            registry=registry,
        )
        self.poll_seconds = Histogram(
            self.name("poll_seconds"),
            "Time to poll all of a source's tickers",
            ["plugin", "source"],
            buckets=POLL_SECONDS_BUCKETS,
            registry=registry,
        )
        # Metric name -> the source that defines it
        self.owners = dict()

    def name(self, name):
        return f"{self.prefix}_{name}" if self.prefix else name

    def for_source(self, config):
        """The metrics a source records into, from its SourceConfig. Metric names must be unique across sources."""
        names = [spec.name for spec in config.metrics]
        if config.labels:
            names.append(info_name(config))
        for name in names:
            if name in BUILTIN_METRICS:
                raise Exception(
                    f"Metric {name} in source {config.name} clashes with a built-in metric"
                )
            if name in self.owners or names.count(name) > 1:
                raise Exception(
                    f"Metric {name} is defined by sources {self.owners.get(name, config.name)} and {config.name}; metric names must be unique across sources"
                )
        self.owners.update({name: config.name for name in names})
        return SourceMetrics(self, config)


class SourceMetrics:
    """One source's own metrics, and its share of the built-ins."""

    def __init__(self, metrics, config):
        self.builtins = metrics
        self.source = config.name
        self.plugin = config.plugin
        self.labels = {
            label: field for label, field in config.labels.items() if label not in DEFAULT_LABELS
        }
        self.metrics = list()
        for spec in config.metrics:
            metric_class, record = METRIC_TYPES[spec.type]
            metric = metric_class(
                metrics.name(spec.name), spec.help, DEFAULT_LABELS, registry=metrics.registry
            )
            self.metrics.append((spec, metric, record))
        # Label fields such as a name or an analyst recommendation change over time. Keeping them off
        # the value metrics gives each ticker one series, and an Info child holds one label set at a time.
        self.info = None
        if self.labels:
            self.info = Info(
                metrics.name(config.name),
                f"Labels of each {config.name} ticker",
                DEFAULT_LABELS,
                registry=metrics.registry,
            )
        # Last known label values per ticker, so a quote missing a label field doesn't drop the label
        self.label_cache = dict()

    def record(self, ticker, quote):
        """Record a quote's fields as this source's metrics. Fields that are missing or not numeric are skipped."""
        default_labels = self._default_labels(ticker)
        if self.info:
            labels = self.label_cache.setdefault(ticker, {label: "" for label in self.labels})
            labels.update(
                {
                    label: str(quote[field])
                    for label, field in self.labels.items()
                    if quote.get(field) is not None
                }
            )
            self.info.labels(**default_labels).info(labels)
        self.builtins.updates.labels(**default_labels).inc()
        for spec, metric, record in self.metrics:
            value = _value(spec, ticker, quote)
            if value is not None:
                record(metric.labels(**default_labels), value)

    def fetch_failed(self, ticker):
        self.builtins.fetch_errors.labels(**self._default_labels(ticker)).inc()

    def observe_poll(self, seconds):
        self.builtins.poll_seconds.labels(plugin=self.plugin, source=self.source).observe(seconds)

    def _default_labels(self, ticker):
        return {"plugin": self.plugin, "source": self.source, "ticker": ticker}


def info_name(config):
    """The source's info metric, which carries its configured labels."""
    return f"{config.name}_info"


def _value(spec, ticker, quote):
    value = quote.get(spec.item)
    if value is None:
        return None
    try:
        return float(value) * spec.scale
    except (TypeError, ValueError):
        log.debug(f"Skipping {spec.name} for {ticker}: {value!r} is not numeric")
        return None
