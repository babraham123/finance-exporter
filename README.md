# finance-exporter

finance-exporter polls market and rates data from multiple sources and serves it on a Prometheus metrics endpoint.

| Plugin | Covers | API key |
|---|---|---|
| `yfinance` (Yahoo Finance) | Stocks, ETFs, mutual funds, indices, FX, crypto, futures | No |
| `fred` (St. Louis Fed) | Treasury yields, credit spreads, policy rates, inflation, mortgage rates, and other economic series | Yes, free: [request one](https://fred.stlouisfed.org/docs/api/api_key.html) |
| `treasury` (Treasury.gov) | Official daily Treasury par yield curves, nominal and real | No |
| `alphavantage` | Stocks (quote, company overview, latest earnings) | Yes. Free tier: 25 requests/day, 3 per ticker |

## Grafana Dashboard Sample
Sample in [Grafana JSON](contrib/finance-exporter.json) with an `asset_class` filter, per-ticker market panels, and a Rates row.
![Grafana Dashboard](contrib/grafana.png)

## Running the exporter
```bash
pip install .
finance-exporter -f finance-exporter.yaml -v
```
To run in Docker, mount config at `/usr/src/app/finance-exporter.yaml` and pass API keys as environment variables (see [docker-compose.yaml](docker-compose.yaml)):
```bash
FRED_API_KEY=... docker-compose up -d
```
```
usage: finance-exporter [-h] -f CONFIG [-v] [-d] [-p PORT] [-a ADDRESS]

  -f, --config CONFIG     Location of config yaml
  -v, --verbose           Log each update
  -d, --debug             Log the config and every API response
  -p, --port PORT         Listen port (overrides the config file)
  -a, --address ADDRESS   Listen address (overrides the config file)
```
Gracefully shuts down on SIGTERM/Ctrl-C (waits up to 10 seconds for in-progress polls).

## Configuration
Validated at startup against [schema.yaml](finance_exporter/schema.yaml). Full example: [finance-exporter.yaml](finance-exporter.yaml).

### Global Settings
```yaml
port: 8000
address: 0.0.0.0
metric_prefix: finance
```

### Sources
Sources poll independently every `interval` seconds.
```yaml
sources:
  - name: yahoo
    interval: 300
    plugin: yfinance
    tickers: [AAPL, SPY, VTSAX, ^GSPC, EURUSD=X, BTC-USD, GC=F]
    metrics:
      ...
    labels:
      ...
```

| Plugin | Tickers | Example |
|---|---|---|
| `yfinance` | Yahoo symbols | `AAPL`, `SPY`, `^GSPC`, `EURUSD=X`, `BTC-USD`, `GC=F` |
| `fred` | FRED series IDs | `DGS10`, `T10Y2Y`, `BAMLH0A0HYM2`, `MORTGAGE30US` |
| `treasury` | Tenors on the curve | `3M`, `2Y`, `10Y`, `30Y` (the real curve has 5Y–30Y only) |
| `alphavantage` | Stock symbols | `IBM` |

| Plugin | Setting | |
|---|---|---|
| `fred`, `alphavantage` | `api_key` | Required. Use an environment variable, e.g. `${FRED_API_KEY}`; startup fails naming the variable if it isn't set. |
| `treasury` | `curve` | `nominal` (default) or `real`. Add two sources to export both. |

### Metrics
`type` is `Gauge`, `Histogram` or `Summary`. Optional `scale` acts as a multiplier. Metric names must be unique across all sources.
```yaml
    metrics:
      current_price:
        item: regularMarketPrice
        type: Gauge
        help: Current Market Price of Asset
      expense_ratio:
        item: netExpenseRatio
        type: Gauge
        help: Net Expense Ratio (ratio)
        scale: 0.01
```

| Plugin | Fields |
|---|---|
| `yfinance` | Everything in Yahoo's quote. ETFs and mutual funds also get `category`, `fundFamily`, `legalType`, `annualReportExpenseRatio`, `annualHoldingsTurnover` and asset mix (`stockPosition`, `bondPosition`, ...). Yahoo mixes percents and ratios, so check each field. |
| `fred` | `value`, `observation_time`, `title`, `frequency`, `units` |
| `treasury` | `value`, `observation_time`, `curve` |
| `alphavantage` | Quote fields (`price`, `volume`, ...), company overview fields, latest quarterly earnings |

| Plugin | `asset_class` values |
|---|---|
| `yfinance` | `stock`, `etf`, `mutual_fund`, `index`, `fx`, `crypto`, `future` |
| `fred` | `rate` (series measured in percent), otherwise `economic_indicator` |
| `treasury` | `treasury_yield` |
| `alphavantage` | `stock`, `etf`, `mutual_fund` |

### Observation time
`observation_time` (FRED and Treasury) is the data date as a Unix timestamp at midnight UTC. Use to alert on staleness:
```
time() - finance_fred_observation_time{ticker="DGS10"} > 4 * 86400
```

### Labels
Maps label names to source fields. `plugin`, `source` and `ticker` are added automatically.
```yaml
    labels:
      asset_class: asset_class
      name: shortName
      sector: sector
      category: category
```

### Built-in metrics
| Metric | Labels | |
|---|---|---|
| `<prefix>_updates_total` | `plugin`, `source`, `ticker` | Successful ticker updates |
| `<prefix>_fetch_errors_total` | `plugin`, `source`, `ticker` | Failed fetches. A source-wide failure counts one per ticker. |
| `<prefix>_poll_seconds` | `plugin`, `source` | Histogram of how long each poll of the source takes |

### Migrating from older configs
* Move top-level `tickers` into each source's `tickers`.
* Delete `update_cache_on_startup` and `min_interval`.
* Change `Counter` metrics to `Gauge`.
* Replace `iexcloud` sources. Yahoo's `regularMarketPrice` and `regularMarketVolume` replace `current_price` and `volume`.
* Write AlphaVantage plugin name as `alphavantage`.
* Replace `quote_time` and `quote_histogram` with `poll_seconds` and `fetch_errors_total`.
* Run `finance-exporter` (after `pip install .`) instead of `python3 finance-exporter.py`.

## Development
```bash
pip install -e '.[dev]'
pytest
```
Tests replay recorded API responses (`tests/fixtures`). To re-record, run `python tests/record_fixtures.py` (requires `FRED_API_KEY` to include FRED).

### Adding a plugin
Subclass `Plugin` in `finance_exporter/plugins/`:
- Put I/O in a client class and return it from `live_client(settings)`.
- Implement `fetch(symbol)` or `fetch_all(symbols)`.
- Declare source settings in `SETTINGS`.
- Register the class in `PLUGINS`.

See [CONTEXT.md](CONTEXT.md) for terminology.
