import csv
import io
import json
import os
import urllib.request
from datetime import date, datetime, timezone

import pytest
import yaml
from prometheus_client import CollectorRegistry
from prometheus_client.parser import text_string_to_metric_families

from clients import FIXTURES, Replay, fixture_path
from finance_exporter.config import load_config
from finance_exporter.exporter import Exporter

with open(os.path.join(FIXTURES, 'recorded_on.txt')) as _fd:
    RECORDED_ON = date.fromisoformat(_fd.read().strip())


def fixture(plugin, method, *args):
    """A recorded response, exactly as the live client returned it."""
    path = fixture_path(plugin, method, args, '.json')
    if os.path.exists(path):
        with open(path) as fd:
            return json.load(fd)
    with open(fixture_path(plugin, method, args, '.csv')) as fd:
        return fd.read()


def midnight_utc(date_string, fmt='%Y-%m-%d'):
    return datetime.strptime(date_string, fmt).replace(tzinfo=timezone.utc).timestamp()


def latest_fred_observation(series_id):
    """Newest observation with a value; FRED lists newest first and marks holidays '.'."""
    return next(o for o in fixture('fred', 'observations', series_id)['observations'] if o['value'] != '.')


def latest_treasury_row(curve):
    rows = csv.DictReader(io.StringIO(fixture('treasury', 'year_csv', curve, RECORDED_ON.year)))
    return max(rows, key=lambda row: datetime.strptime(row['Date'], '%m/%d/%Y'))


class Sleeps(list):
    """A sleep() that records requested delays instead of waiting."""

    def __call__(self, seconds):
        self.append(seconds)


def read_samples(registry):
    """Samples in a registry as {(name, frozenset(labels)): value}."""
    return {
        (sample.name, frozenset(sample.labels.items())): sample.value
        for family in registry.collect()
        for sample in family.samples
    }


class ExporterUnderTest:
    """An exporter whose plugins replay recorded responses, with its own metric registry.

    `clients` replaces the replayed client for the named plugins. The HTTP server starts only when scraped.
    """

    def __init__(self, config_path, clients=None):
        clients = clients or dict()
        self.sleeps = Sleeps()
        self.registry = CollectorRegistry()

        def make_plugin(plugin_class, source):
            client = clients.get(source.plugin) or Replay(source.plugin)
            return plugin_class(source.settings, client, sleep=self.sleeps, today=lambda: RECORDED_ON)

        self.config = load_config(config_path, port=0, address='127.0.0.1')
        self.exporter = Exporter(self.config, registry=self.registry, make_plugin=make_plugin)

    def poll(self):
        for source in self.exporter.sources.values():
            source.poll()

    def samples(self):
        return read_samples(self.registry)

    def scrape(self):
        """Samples as served over HTTP on /metrics."""
        server = self.exporter.start_server()
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/metrics') as response:
                text = response.read().decode()
        finally:
            server.shutdown()
            server.server_close()
        return {
            (sample.name, frozenset(sample.labels.items())): sample.value
            for family in text_string_to_metric_families(text)
            for sample in family.samples
        }


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
    def start(config, clients=None):
        path = tmp_path / 'config.yaml'
        path.write_text(config if isinstance(config, str) else yaml.safe_dump(config))
        return ExporterUnderTest(str(path), clients)

    return start
