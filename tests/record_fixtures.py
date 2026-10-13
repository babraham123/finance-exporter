#!/usr/bin/python3
"""Re-record the API responses in tests/fixtures from the live services.

FRED is recorded only when FRED_API_KEY is set; AlphaVantage uses ALPHAVANTAGE_API_KEY or the demo key (IBM only).
"""
import json
import os
import time
from datetime import datetime, timezone
import requests
import yfinance as yf

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')
YAHOO_SYMBOLS = ['AAPL', 'SPY', 'VTSAX', '^GSPC', 'BTC-USD', 'EURUSD=X', 'GC=F']
FRED_SERIES = ['DGS2', 'DGS10', 'T10Y2Y', 'BAMLH0A0HYM2', 'MORTGAGE30US']
TREASURY_URL = 'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{year}/all'
TREASURY_CURVES = {'nominal': 'daily_treasury_yield_curve', 'real': 'daily_treasury_real_yield_curve'}
TREASURY_ROWS = 5


def write(path, content):
    path = os.path.join(FIXTURES, path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as fd:
        fd.write(content)
    print(f'wrote {path}')


def write_json(path, data):
    write(path, json.dumps(data, indent=1, sort_keys=True, default=str) + '\n')


def record_yahoo():
    for symbol in YAHOO_SYMBOLS:
        ticker = yf.Ticker(symbol)
        fixture = {'info': ticker.info}
        if fixture['info'].get('quoteType') in ('ETF', 'MUTUALFUND'):
            funds = ticker.funds_data
            fixture['funds_data'] = {
                'fund_overview': funds.fund_overview,
                'asset_classes': funds.asset_classes,
                'fund_operations': funds.fund_operations.to_dict(),
            }
        write_json(f'yahoo/{symbol}.json', fixture)


def record_treasury():
    year = datetime.now(timezone.utc).year
    for curve, curve_type in TREASURY_CURVES.items():
        text = requests.get(TREASURY_URL.format(year=year), params={'type': curve_type, 'field_tdr_date_value': year, '_format': 'csv'}, timeout=30).text
        lines = text.strip().splitlines()
        write(f'treasury/{curve}.csv', '\n'.join(lines[:TREASURY_ROWS + 1]) + '\n')


def record_fred():
    api_key = os.environ.get('FRED_API_KEY')
    if not api_key:
        print('FRED_API_KEY not set; skipping FRED')
        return
    base = 'https://api.stlouisfed.org/fred'
    for series_id in FRED_SERIES:
        params = {'series_id': series_id, 'api_key': api_key, 'file_type': 'json'}
        write_json(f'fred/{series_id}_series.json', requests.get(f'{base}/series', params=params, timeout=30).json())
        observations = requests.get(f'{base}/series/observations', params={**params, 'sort_order': 'desc', 'limit': 10}, timeout=30).json()
        write_json(f'fred/{series_id}_observations.json', observations)


def record_alphavantage():
    api_key = os.environ.get('ALPHAVANTAGE_API_KEY', 'demo')
    for function in ('GLOBAL_QUOTE', 'OVERVIEW', 'EARNINGS'):
        time.sleep(1)  # demo key allows 2 requests/second
        response = requests.get('https://www.alphavantage.co/query', params={'function': function, 'symbol': 'IBM', 'apikey': api_key}, timeout=30).json()
        if function == 'EARNINGS':
            response = {k: v[:2] if isinstance(v, list) else v for k, v in response.items()}
        write_json(f'alphavantage/IBM_{function}.json', response)


if __name__ == '__main__':
    record_yahoo()
    record_treasury()
    record_fred()
    record_alphavantage()
