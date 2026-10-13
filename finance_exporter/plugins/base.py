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

    def __init__(self, source, client, sleep=time.sleep, today=utc_today):
        self.source = source
        self.client = client
        self.sleep = sleep
        self.today = today

    @classmethod
    def live_client(cls, source):
        """The client that talks to the real provider."""
        raise NotImplementedError

    def require_api_key(self):
        key = self.source.get('api_key')
        # An unexpanded ${VAR} means the environment variable isn't set
        if not key or key.startswith('$'):
            raise Exception(f"Source {self.source['name']} requires api_key for the {self.source['plugin']} plugin")
        return key

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
