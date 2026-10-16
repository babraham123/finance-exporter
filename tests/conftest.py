import csv
import io
import os
import urllib.request
from datetime import date, datetime, timezone

import pytest
import yaml
from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.parser import text_string_to_metric_families

from clients import FIXTURES, Replay
from finance_exporter.config import load_config
from finance_exporter.exporter import Exporter

with open(os.path.join(FIXTURES, 'recorded_on.txt')) as _fd:
    RECORDED_ON = date.fromisoformat(_fd.read().strip())


def fixture(plugin, method, *args):
    """A recorded response, exactly as the live client returned it."""
    return getattr(Replay(plugin), method)(*args)


def midnight_utc(date_string, fmt='%Y-%m-%d'):
    return datetime.strptime(date_string, fmt).replace(tzinfo=timezone.utc).timestamp()


def latest_fred_observation(series_id):
    """Newest observation with a value; FRED lists newest first and marks holidays '.'."""
    return next(o for o in fixture('fred', 'observations', series_id)['observations'] if o['value'] != '.')


def latest_treasury_row(curve):
    rows = csv.DictReader(io.StringIO(fixture('treasury', 'year_csv', curve, RECORDED_ON.year)))
    return max(rows, key=lambda row: datetime.strptime(row['Date'], '%m/%d/%Y'))


class FakeClock:
    """Virtual time: sleep() and wait() advance it instantly. today() is the day the fixtures were recorded."""

    def __init__(self, today=RECORDED_ON):
        self.time = 0
        self.sleeps = list()
        self.waits = list()
        self.date = today

    def now(self):
        return self.time

    def wait(self, seconds, stop):
        self.waits.append(seconds)
        self.time += seconds
        return stop.is_set()

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.time += seconds

    def today(self):
        return self.date


def parse_samples(text):
    """Samples in Prometheus text exposition as {(name, frozenset(labels)): value}."""
    return {
        (sample.name, frozenset(sample.labels.items())): sample.value
        for family in text_string_to_metric_families(text)
        for sample in family.samples
    }


def read_samples(registry):
    """Samples in a registry, as it would serve them."""
    return parse_samples(generate_latest(registry).decode())


def scrape(port):
    """Samples served over HTTP on /metrics."""
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/metrics') as response:
        return parse_samples(response.read().decode())


class ExporterUnderTest:
    """An exporter whose plugins replay recorded responses, on `clock`, with its own metric registry and a free port.

    `clients` replaces the replayed client for the named plugins.
    """

    def __init__(self, config_path, clients=None, clock=None):
        overrides = clients or dict()
        self.clock = clock or FakeClock()
        self.registry = CollectorRegistry()
        self.config = load_config(config_path, port=0, address='127.0.0.1')
        self.exporter = Exporter(self.config, clients=lambda source: overrides.get(source.plugin) or Replay(source.plugin),
                                 clock=self.clock, registry=self.registry)

    def poll(self):
        self.exporter.poll()

    def samples(self):
        return read_samples(self.registry)

    def start(self):
        return self.exporter.start()

    def stop(self):
        self.exporter.stop()


def find(samples, name, **labels):
    """Value of the one sample named `name` whose labels include `labels`, or None if absent."""
    matches = [ value for (sample_name, sample_labels), value in samples.items()
                if sample_name == name and set(labels.items()) <= sample_labels ]
    assert len(matches) <= 1, f'{name} {labels} matched {len(matches)} samples'
    return matches[0] if matches else None


def label_names(samples, name):
    return { frozenset(k for k, _ in labels) for (sample_name, labels) in samples if sample_name == name }


@pytest.fixture
def start_exporter(tmp_path):
    def start(config, clients=None, clock=None):
        path = tmp_path / 'config.yaml'
        path.write_text(config if isinstance(config, str) else yaml.safe_dump(config))
        return ExporterUnderTest(str(path), clients, clock)

    return start
