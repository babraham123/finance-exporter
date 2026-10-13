import time
from datetime import datetime, timezone

import requests

HTTP_TIMEOUT = 30


class RateLimited(Exception):
    """The provider asked us to slow down."""


def date_to_epoch(date_string, fmt='%Y-%m-%d'):
    """Midnight UTC of a date, as a Unix timestamp."""
    return datetime.strptime(date_string, fmt).replace(tzinfo=timezone.utc).timestamp()


def utc_today():
    return datetime.now(timezone.utc).date()


def http_get(url, **params):
    response = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
    if not response.ok:
        raise Exception(f'HTTP {response.status_code} from {url}: {response.text[:200]}')
    return response


class Plugin:
    """A data source for one configured source's tickers.

    All I/O goes through `client`, whose live implementation comes from live_client(); tests replay recorded
    responses through the same methods. `sleep` and `today` stand in for the clock.
    """
    # JSON Schema for the plugin's own source settings: {'properties': {...}, 'required': [...]}.
    # A property may set 'default', and 'secret': True to keep it out of logs.
    SETTINGS = dict()

    def __init__(self, settings, client, sleep=time.sleep, today=utc_today):
        self.settings = settings
        self.client = client
        self.sleep = sleep
        self.today = today

    @classmethod
    def live_client(cls, settings):
        """The client that talks to the real provider."""
        raise NotImplementedError

    def fetch_all(self, symbols):
        """Yield (symbol, result) once per symbol, as each is fetched.

        result is the quote (a flat dict of fields), None when the source has no data for the symbol,
        or the exception that stopped this symbol. Raising instead fails every symbol not yet yielded.
        """
        for symbol in symbols:
            try:
                yield symbol, self.fetch(symbol)
            except Exception as e:
                yield symbol, e

    def fetch(self, symbol):
        """One symbol's quote, or None if there is no data. Plugins that fetch every symbol at once override fetch_all instead."""
        raise NotImplementedError
