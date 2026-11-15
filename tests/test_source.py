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

    assert find(samples, "finance_price", ticker="X", source="scripted", plugin="fake") == 12
    assert label_names(samples, "finance_price") == {frozenset({"plugin", "source", "ticker"})}
    # The second quote lacks sector, so the info series keeps the last known value
    assert find(samples, "finance_scripted_info", ticker="X", sector="Tech") == 1
    assert label_names(samples, "finance_scripted_info") == {
        frozenset({"plugin", "source", "ticker", "sector"})
    }
    assert find(samples, "finance_price_histogram_count", ticker="X") == 2
    assert find(samples, "finance_price_histogram_sum", ticker="X") == 22
    assert find(samples, "finance_price_summary_sum", ticker="X") == 11
    assert find(samples, "finance_updates_total", ticker="X") == 2


def test_changed_label_field_leaves_one_series_per_ticker():
    plugin = ScriptedPlugin(
        {"X": {"price": 10, "rating": "buy"}, "Y": {"price": 20, "rating": "hold"}},
        {"X": {"price": 11, "rating": "sell"}},
    )
    source, registry = scripted_source(plugin, tickers=["X", "Y"], labels={"rating": "rating"})
    source.poll()
    source.poll()
    samples = read_samples(registry)

    # find() fails on more than one match, so a ticker-only match proves a single series
    assert find(samples, "finance_price", ticker="X") == 11
    assert find(samples, "finance_scripted_info", ticker="X") == 1
    assert find(samples, "finance_scripted_info", ticker="X", rating="sell") == 1
    # Tickers missing from the poll keep their series
    assert find(samples, "finance_price", ticker="Y") == 20
    assert find(samples, "finance_scripted_info", ticker="Y", rating="hold") == 1


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
