#!/usr/bin/env python3
"""Re-record tests/fixtures by running each plugin against its live provider.

FRED is recorded only when FRED_API_KEY is set; AlphaVantage uses ALPHAVANTAGE_API_KEY or the demo key (IBM only).
"""

import os

from clients import FIXTURES, Record
from finance_exporter.clock import Clock
from finance_exporter.config import source_config
from finance_exporter.plugins import build_plugin, live_client

YAHOO_SYMBOLS = ["AAPL", "SPY", "VTSAX", "^GSPC", "BTC-USD", "EURUSD=X", "GC=F"]
FRED_SERIES = ["DGS2", "DGS10", "T10Y2Y", "BAMLH0A0HYM2", "MORTGAGE30US"]
TREASURY_TENORS = ["3M", "10Y", "30Y"]


def record(plugin, symbols, **settings):
    source = source_config(
        {
            "name": plugin,
            "plugin": plugin,
            "interval": 1,
            "tickers": symbols,
            "metrics": {},
            **settings,
        }
    )
    instance = build_plugin(source, Record(live_client(source), plugin), Clock())
    for symbol, result in instance.fetch_all(symbols):
        if isinstance(result, Exception):
            print(f"{plugin} {symbol}: {result}")


if __name__ == "__main__":
    record("yfinance", YAHOO_SYMBOLS)
    for curve in ("nominal", "real"):
        record("treasury", TREASURY_TENORS, curve=curve)
    if os.environ.get("FRED_API_KEY"):
        record("fred", FRED_SERIES, api_key=os.environ["FRED_API_KEY"])
    else:
        print("FRED_API_KEY not set; skipping FRED")
    record("alphavantage", ["IBM"], api_key=os.environ.get("ALPHAVANTAGE_API_KEY", "demo"))
    with open(os.path.join(FIXTURES, "recorded_on.txt"), "w") as fd:
        fd.write(f"{Clock().today().isoformat()}\n")
