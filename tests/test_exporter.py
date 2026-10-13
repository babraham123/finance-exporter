import pytest
from conftest import FakeTicker, find, fixture_json, label_names, midnight_utc

YAHOO_ASSET_CLASSES = {
    'AAPL': 'stock',
    'SPY': 'etf',
    'VTSAX': 'mutual_fund',
    '^GSPC': 'index',
    'BTC-USD': 'crypto',
    'EURUSD=X': 'fx',
    'GC=F': 'future',
}


def config(*sources):
    return {'port': 0, 'address': '127.0.0.1', 'metric_prefix': 'finance', 'min_interval': 1, 'sources': list(sources)}


def yahoo_source(tickers=tuple(YAHOO_ASSET_CLASSES)):
    return {
        'name': 'yahoo', 'plugin': 'yfinance', 'interval': 300, 'tickers': list(tickers),
        'metrics': {
            'current_price': {'item': 'regularMarketPrice', 'type': 'Gauge', 'help': 'Price'},
            'net_expense_ratio': {'item': 'netExpenseRatio', 'type': 'Gauge', 'help': 'Net expense ratio', 'scale': 0.01},
            'report_expense_ratio': {'item': 'annualReportExpenseRatio', 'type': 'Gauge', 'help': 'Annual report expense ratio'},
            'stock_position': {'item': 'stockPosition', 'type': 'Gauge', 'help': 'Share of fund in stocks'},
            'name_as_number': {'item': 'shortName', 'type': 'Gauge', 'help': 'Not numeric'},
        },
        'labels': {'asset_class': 'asset_class', 'category': 'category', 'fund_family': 'fundFamily'},
    }


def fred_source():
    return {
        'name': 'fred', 'plugin': 'fred', 'interval': 3600, 'api_key': '${FRED_API_KEY}',
        'tickers': ['DGS2', 'DGS10', 'T10Y2Y', 'BAMLH0A0HYM2', 'MORTGAGE30US'],
        'metrics': {
            'fred_value': {'item': 'value', 'type': 'Gauge', 'help': 'Value', 'scale': 0.01},
            'fred_observation_time': {'item': 'observation_time', 'type': 'Gauge', 'help': 'Observation date'},
        },
        'labels': {'asset_class': 'asset_class', 'frequency': 'frequency'},
    }


def treasury_source(name='treasury', curve='nominal', tickers=('3M', '10Y', '30Y')):
    return {
        'name': name, 'plugin': 'treasury', 'curve': curve, 'interval': 3600, 'tickers': list(tickers),
        'metrics': {
            f'{name}_yield': {'item': 'value', 'type': 'Gauge', 'help': 'Par yield', 'scale': 0.01},
            f'{name}_observation_time': {'item': 'observation_time', 'type': 'Gauge', 'help': 'Curve date'},
        },
        'labels': {'asset_class': 'asset_class', 'curve': 'curve'},
    }


def alphavantage_source():
    return {
        'name': 'alphavantage', 'plugin': 'alphavantage', 'interval': 86400, 'api_key': 'demo', 'tickers': ['IBM'],
        'metrics': {
            'av_price': {'item': 'price', 'type': 'Gauge', 'help': 'Price'},
            'av_reported_eps': {'item': 'reportedEPS', 'type': 'Gauge', 'help': 'Reported EPS'},
        },
        'labels': {'asset_class': 'asset_class', 'sector': 'Sector'},
    }


def all_sources():
    return config(yahoo_source(), fred_source(), treasury_source(), treasury_source('treasury_real', 'real', ['10Y']), alphavantage_source())


@pytest.fixture
def fred_key(monkeypatch):
    monkeypatch.setenv('FRED_API_KEY', 'test-fred-key')


def test_all_sources_export_their_own_metrics(start_exporter, http, fred_key):
    exporter = start_exporter(all_sources())
    exporter.poll()
    samples = exporter.scrape()

    # Yahoo: price for every asset class, classified from quoteType
    for symbol, asset_class in YAHOO_ASSET_CLASSES.items():
        price = fixture_json(f'yahoo/{symbol}.json')['info']['regularMarketPrice']
        assert find(samples, 'finance_current_price', ticker=symbol, asset_class=asset_class, source='yahoo', plugin='yfinance') == price
    spy = fixture_json('yahoo/SPY.json')['info']
    assert find(samples, 'finance_net_expense_ratio', ticker='SPY') == pytest.approx(spy['netExpenseRatio'] * 0.01)
    assert find(samples, 'finance_net_expense_ratio', ticker='AAPL') is None
    # Mutual fund details missing from .info are filled from funds_data
    vtsax_funds = fixture_json('yahoo/VTSAX.json')['funds_data']
    assert find(samples, 'finance_report_expense_ratio', ticker='VTSAX',
                category=vtsax_funds['fund_overview']['categoryName'],
                fund_family=vtsax_funds['fund_overview']['family']) == vtsax_funds['fund_operations']['VTSAX']['Annual Report Expense Ratio']
    assert find(samples, 'finance_stock_position', ticker='VTSAX') == vtsax_funds['asset_classes']['stockPosition']
    # Non-numeric values are skipped, not exported or fatal
    assert find(samples, 'finance_name_as_number') is None

    # FRED: latest real observation (holiday "." skipped), percent scaled to ratio, dated at midnight UTC
    assert find(samples, 'finance_fred_value', ticker='DGS10', asset_class='rate', frequency='Daily') == pytest.approx(0.0524)
    assert find(samples, 'finance_fred_observation_time', ticker='DGS10') == midnight_utc('2026-10-09')
    assert find(samples, 'finance_fred_value', ticker='T10Y2Y') == pytest.approx(0.0042)
    assert find(samples, 'finance_fred_value', ticker='MORTGAGE30US', frequency='Weekly, Ending Thursday') == pytest.approx(0.074)
    assert find(samples, 'finance_fred_observation_time', ticker='MORTGAGE30US') == midnight_utc('2026-10-08')
    assert all(params['api_key'] == 'test-fred-key' for url, params in http.calls if 'stlouisfed' in url)

    # Treasury: latest row of each curve, tenors as tickers
    assert find(samples, 'finance_treasury_yield', ticker='10Y', curve='nominal', asset_class='treasury_yield') == pytest.approx(0.0521)
    assert find(samples, 'finance_treasury_yield', ticker='3M') == pytest.approx(0.0426)
    assert find(samples, 'finance_treasury_observation_time', ticker='30Y') == midnight_utc('2026-10-13')
    assert find(samples, 'finance_treasury_real_yield', ticker='10Y', curve='real') == pytest.approx(0.0288)

    # AlphaVantage: quote, overview and latest earnings merged
    ibm_quote = fixture_json('alphavantage/IBM_GLOBAL_QUOTE.json')['Global Quote']
    ibm_earnings = fixture_json('alphavantage/IBM_EARNINGS.json')['quarterlyEarnings'][0]
    assert find(samples, 'finance_av_price', ticker='IBM', asset_class='stock') == float(ibm_quote['05. price'])
    assert find(samples, 'finance_av_reported_eps', ticker='IBM') == float(ibm_earnings['reportedEPS'])

    # Each source's metrics carry only that source's labels
    assert label_names(samples, 'finance_current_price') == {frozenset({'plugin', 'source', 'ticker', 'asset_class', 'category', 'fund_family'})}
    assert label_names(samples, 'finance_fred_value') == {frozenset({'plugin', 'source', 'ticker', 'asset_class', 'frequency'})}
    assert label_names(samples, 'finance_treasury_yield') == {frozenset({'plugin', 'source', 'ticker', 'asset_class', 'curve'})}
    # Built-in metrics use only the default labels, once per ticker update
    assert label_names(samples, 'finance_updates_total') == {frozenset({'plugin', 'source', 'ticker'})}
    assert find(samples, 'finance_updates_total', source='fred', ticker='DGS2') == 1
    assert find(samples, 'finance_updates_total', source='treasury_real', ticker='10Y') == 1


def test_failed_sources_and_tickers_do_not_stop_others(start_exporter, http, fred_key):
    http.alphavantage_throttled = True
    FakeTicker.rate_limited['SPY'] = 2
    exporter = start_exporter(config(
        yahoo_source(['SPY', 'NOPE']),
        treasury_source(tickers=['10Y', '15Y']),
        alphavantage_source(),
    ))
    exporter.poll()
    samples = exporter.scrape()

    # Yahoo retries through rate limiting
    assert find(samples, 'finance_current_price', ticker='SPY') is not None
    assert find(samples, 'finance_fetch_errors_total', ticker='SPY') is None
    # Unknown symbols, tenors missing from the curve and throttled responses export nothing and count an error
    for source, ticker in [('yahoo', 'NOPE'), ('treasury', '15Y'), ('alphavantage', 'IBM')]:
        assert find(samples, 'finance_updates_total', source=source, ticker=ticker) is None
        assert find(samples, 'finance_fetch_errors_total', source=source, ticker=ticker) == 1
    assert find(samples, 'finance_treasury_yield', ticker='10Y') is not None
    assert find(samples, 'finance_av_price') is None


def test_source_wide_failure_counts_an_error_per_ticker(start_exporter, http):
    http.failing_hosts = {'treasury.gov'}
    exporter = start_exporter(config(treasury_source(tickers=['3M', '10Y']), yahoo_source(['AAPL'])))
    exporter.poll()
    samples = exporter.scrape()

    assert find(samples, 'finance_fetch_errors_total', source='treasury', ticker='3M') == 1
    assert find(samples, 'finance_fetch_errors_total', source='treasury', ticker='10Y') == 1
    assert find(samples, 'finance_treasury_yield') is None
    assert find(samples, 'finance_current_price', ticker='AAPL') is not None
    # Every poll is timed per source, whether or not it succeeded
    assert find(samples, 'finance_poll_seconds_count', source='treasury', plugin='treasury') == 1
    assert find(samples, 'finance_poll_seconds_count', source='yahoo', plugin='yfinance') == 1


def test_treasury_uses_previous_year_before_first_business_day(start_exporter, http):
    http.empty_treasury_years = {0}
    exporter = start_exporter(config(treasury_source(tickers=['10Y'])))
    exporter.poll()
    samples = exporter.scrape()

    assert find(samples, 'finance_treasury_yield', ticker='10Y') == pytest.approx(0.0521)
    requested_years = [int(params['field_tdr_date_value']) for url, params in http.calls]
    assert requested_years[1] == requested_years[0] - 1


@pytest.mark.parametrize('bad_config, error', [
    (lambda: {**config(yahoo_source()), 'tickers': ['AAPL']}, 'tickers` is no longer supported'),
    (lambda: {**config(yahoo_source()), 'update_cache_on_startup': True}, 'update_cache_on_startup` is no longer supported'),
    (lambda: config({**yahoo_source(), 'tickers': []}), 'Invalid config at sources/0/tickers'),
    (lambda: config({k: v for k, v in yahoo_source().items() if k != 'tickers'}), "'tickers' is a required property"),
    (lambda: config({k: v for k, v in fred_source().items() if k != 'api_key'}), "'api_key' is a required property"),
    (lambda: config({**yahoo_source(), 'plugin': 'iexcloud'}), "'iexcloud' is not one of"),
    (lambda: config({**yahoo_source(), 'curve': 'real'}), 'Invalid config at sources/0'),
    (lambda: config(treasury_source(), {**treasury_source(), 'name': 'other'}), 'metric names must be unique across sources'),
    (lambda: config(yahoo_source(), {**yahoo_source(['SPY']), 'metrics': {}}), 'used more than once'),
])
def test_invalid_configs_are_rejected(start_exporter, bad_config, error):
    with pytest.raises(Exception, match=error):
        start_exporter(bad_config())


def test_fred_requires_api_key_in_environment(start_exporter, monkeypatch):
    monkeypatch.delenv('FRED_API_KEY', raising=False)
    with pytest.raises(Exception, match='requires api_key'):
        start_exporter(config(fred_source()))
