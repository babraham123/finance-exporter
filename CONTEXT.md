# finance-exporter

Polls market and rates data from several independent providers and exposes the latest values as Prometheus metrics.

## Language

### Polling

**Source**:
One configured feed in the config file: a plugin, the tickers to poll with it, and the metrics and labels to export from its quotes. Two sources may use the same plugin (e.g. the nominal and real Treasury curves).
_Avoid_: feed, provider (for the configured thing), job

**Plugin**:
The adapter for one provider (Yahoo, FRED, Treasury, AlphaVantage) that turns tickers into quotes. Plugins are independent; one is never a fallback for another.
_Avoid_: handler, driver, backend

**Client**:
The part of a plugin that only talks to the provider and returns its responses as plain data, with no interpretation.
_Avoid_: API, connector

**Settings**:
A source's plugin-specific options, such as `api_key` or `curve`, declared by the plugin itself.
_Avoid_: options, params

**Ticker**:
A symbol a source polls, in its plugin's own vocabulary: a Yahoo symbol, a FRED series ID, a Treasury tenor (`10Y`).
_Avoid_: symbol (except inside a plugin), series, instrument

**Quote**:
The flat set of fields a plugin returns for one ticker in one poll.
_Avoid_: response, data, payload

**Field**:
One named value in a quote (`regularMarketPrice`, `value`, `observation_time`), referenced by a metric's `item` or a label.
_Avoid_: item (except in config), attribute

**Poll**:
One pass over all of a source's tickers.
_Avoid_: update (for the whole pass), refresh, scrape

**Interval**:
Seconds between the starts of consecutive polls of a source.
_Avoid_: period, frequency (FRED uses "frequency" for a series' cadence)

**Runner**:
What keeps one source polling on its own schedule, independently of every other source.
_Avoid_: scheduler, loop, worker

### Results

**No data**:
A ticker the provider has nothing for right now (e.g. every recent FRED observation is missing). Not an error.

**Fetch error**:
A ticker whose fetch failed, including every not-yet-fetched ticker of a poll that failed as a whole.
_Avoid_: failure, miss

**Observation time**:
The date the data describes, as midnight UTC. For weekly and monthly series it is the start of the period, not the release date.
_Avoid_: timestamp, as-of, release date

**Asset class**:
The kind of instrument a ticker is (`stock`, `etf`, `mutual_fund`, `rate`, `treasury_yield`, ...), assigned by its plugin.
_Avoid_: type, quote type (Yahoo's own term)
