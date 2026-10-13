import json
import os
import urllib.request
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest
import requests
import yaml
import yfinance
from prometheus_client import CollectorRegistry
from prometheus_client.parser import text_string_to_metric_families

from finance_exporter.exporter import Exporter

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')

TREASURY_CURVES = {'daily_treasury_yield_curve': 'nominal', 'daily_treasury_real_yield_curve': 'real'}


def fixture_text(path):
    with open(os.path.join(FIXTURES, path)) as fd:
        return fd.read()


def fixture_json(path):
    return json.loads(fixture_text(path))


def midnight_utc(date_string):
    return datetime.strptime(date_string, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp()


class FakeResponse:

    def __init__(self, status_code, text):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = text

    def json(self):
        return json.loads(self.text)


class FakeHTTP:
    """Serves recorded fixtures in place of the FRED, Treasury and AlphaVantage APIs."""

    def __init__(self):
        self.calls = list()
        # Years before the current one (0 = this year) whose Treasury file has no rows yet
        self.empty_treasury_years = set()
        self.alphavantage_throttled = False

    def get(self, url, params=None, timeout=None):
        params = params or dict()
        self.calls.append((url, params))
        if 'stlouisfed.org' in url:
            kind = 'observations' if url.endswith('/observations') else 'series'
            return self._fixture(f"fred/{params['series_id']}_{kind}.json")
        if 'treasury.gov' in url:
            years_ago = datetime.now(timezone.utc).year - int(params['field_tdr_date_value'])
            if years_ago in self.empty_treasury_years:
                return FakeResponse(200, '')
            return self._fixture(f"treasury/{TREASURY_CURVES[params['type']]}.csv")
        if 'alphavantage.co' in url:
            if self.alphavantage_throttled:
                return FakeResponse(200, json.dumps({'Information': 'Rate limit reached'}))
            return self._fixture(f"alphavantage/{params['symbol']}_{params['function']}.json")
        raise AssertionError(f'Unexpected request to {url}')

    def _fixture(self, path):
        try:
            return FakeResponse(200, fixture_text(path))
        except FileNotFoundError:
            return FakeResponse(404, f'no fixture {path}')


class FakeTicker:
    """Stands in for yfinance.Ticker using recorded fixtures."""
    rate_limited = dict()

    def __init__(self, symbol):
        self.symbol = symbol
        self.fixture = fixture_json(f'yahoo/{symbol}.json')

    @property
    def info(self):
        if FakeTicker.rate_limited.get(self.symbol, 0) > 0:
            FakeTicker.rate_limited[self.symbol] -= 1
            raise yfinance.exceptions.YFRateLimitError()
        return self.fixture['info']

    @property
    def funds_data(self):
        funds = self.fixture['funds_data']
        return SimpleNamespace(
            fund_overview=funds['fund_overview'],
            asset_classes=funds['asset_classes'],
            fund_operations=pd.DataFrame(funds['fund_operations']),
        )


class RunningExporter:
    """A running exporter on an ephemeral port with its own metric registry."""

    def __init__(self, config_path, http):
        self.http = http
        self.exporter = Exporter(config_path, port=0, address='127.0.0.1', registry=CollectorRegistry())
        self.server = self.exporter.start_server()

    def poll(self):
        for source in self.exporter.sources.values():
            self.exporter.update(source)

    def scrape(self):
        """Samples from /metrics as {(name, frozenset(labels)): value}."""
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.server_port}/metrics') as response:
            text = response.read().decode()
        return {
            (sample.name, frozenset(sample.labels.items())): sample.value
            for family in text_string_to_metric_families(text)
            for sample in family.samples
        }

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def find(samples, name, **labels):
    """Value of the one sample named `name` whose labels include `labels`, or None if absent."""
    matches = [ value for (sample_name, sample_labels), value in samples.items()
                if sample_name == name and set(labels.items()) <= sample_labels ]
    assert len(matches) <= 1, f'{name} {labels} matched {len(matches)} samples'
    return matches[0] if matches else None


def label_names(samples, name):
    return { frozenset(k for k, _ in labels) for (sample_name, labels) in samples if sample_name == name }


@pytest.fixture
def http(monkeypatch):
    fake = FakeHTTP()
    monkeypatch.setattr(requests, 'get', fake.get)
    monkeypatch.setattr(yfinance, 'Ticker', FakeTicker)
    monkeypatch.setattr(FakeTicker, 'rate_limited', dict())
    monkeypatch.setattr('finance_exporter.plugins.yahoo.time.sleep', lambda seconds: None)
    monkeypatch.setattr('finance_exporter.plugins.alphavantage.time.sleep', lambda seconds: None)
    return fake


@pytest.fixture
def start_exporter(http, tmp_path):
    exporters = list()

    def start(config):
        path = tmp_path / 'config.yaml'
        path.write_text(config if isinstance(config, str) else yaml.safe_dump(config))
        exporter = RunningExporter(str(path), http)
        exporters.append(exporter)
        return exporter

    yield start
    for exporter in exporters:
        exporter.close()
