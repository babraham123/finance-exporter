from datetime import datetime, timezone
import requests

HTTP_TIMEOUT = 30


def date_to_epoch(date_string, fmt='%Y-%m-%d'):
    """Midnight UTC of a date, as a Unix timestamp."""
    return datetime.strptime(date_string, fmt).replace(tzinfo=timezone.utc).timestamp()


def http_get(url, **params):
    response = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
    if not response.ok:
        raise Exception(f'HTTP {response.status_code} from {url}: {response.text[:200]}')
    return response


class Plugin:
    """A data source for one configured source's tickers."""

    def __init__(self, source):
        self.source = source

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
