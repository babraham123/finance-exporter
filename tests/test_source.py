from prometheus_client import CollectorRegistry
from conftest import find, label_names, read_samples
from finance_exporter.config import MetricSpec, SourceConfig
from finance_exporter.metrics import Metrics
from finance_exporter.source import Source


class ScriptedPlugin:
    """Yields the given {ticker: result} for each poll in turn, then raises `then` if set."""

    def __init__(self, *polls, then=None):
        self.polls = list(polls)
        self.then = then

    def fetch_all(self, symbols):
        yield from self.polls.pop(0).items()
        if self.then:
            raise self.then


def scripted_source(plugin, tickers=("X",), metrics=None, labels=None):
    registry = CollectorRegistry()
    metrics = metrics or {"price": {"item": "price", "type": "Gauge", "help": "Price"}}
    config = SourceConfig(
        name="scripted",
        plugin="fake",
        interval=60,
        tickers=tuple(tickers),
        metrics=tuple(MetricSpec(name=name, **spec) for name, spec in metrics.items()),
        labels=labels or dict(),
    )
    return Source(config, plugin, Metrics(registry, "finance")), registry


def test_source_records_each_metric_type_and_keeps_last_known_labels():
    plugin = ScriptedPlugin({"X": {"price": "10", "sector": "Tech"}}, {"X": {"price": 12}})
    source, registry = scripted_source(
        plugin,
        metrics={
            "price": {"item": "price", "type": "Gauge", "help": "Price"},
            "price_histogram": {"item": "price", "type": "Histogram", "help": "Price"},
            "price_summary": {"item": "price", "type": "Summary", "help": "Price", "scale": 0.5},
        },
        labels={"sector": "sector"},
    )
    source.poll()
    source.poll()
    samples = read_samples(registry)

    # The second quote lacks sector, so the series keeps the last known value rather than splitting
    assert (
        find(samples, "finance_price", ticker="X", sector="Tech", source="scripted", plugin="fake")
        == 12
    )
    assert label_names(samples, "finance_price") == {
        frozenset({"plugin", "source", "ticker", "sector"})
    }
    assert find(samples, "finance_price_histogram_count", ticker="X") == 2
    assert find(samples, "finance_price_histogram_sum", ticker="X") == 22
    assert find(samples, "finance_price_summary_sum", ticker="X") == 11
    assert find(samples, "finance_updates_total", ticker="X") == 2


def test_source_failure_mid_poll_counts_errors_only_for_unfetched_tickers():
    plugin = ScriptedPlugin({"A": {"price": 1}, "B": None}, then=RuntimeError("connection reset"))
    source, registry = scripted_source(plugin, tickers=["A", "B", "C", "D"])
    source.poll()
    samples = read_samples(registry)

    assert find(samples, "finance_price", ticker="A") == 1
    # No data is not an error
    assert find(samples, "finance_fetch_errors_total", ticker="B") is None
    assert find(samples, "finance_updates_total", ticker="B") is None
    assert find(samples, "finance_fetch_errors_total", ticker="C") == 1
    assert find(samples, "finance_fetch_errors_total", ticker="D") == 1
    assert find(samples, "finance_poll_seconds_count", source="scripted") == 1
