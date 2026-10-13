from datetime import datetime, timezone
import requests

HTTP_TIMEOUT = 30


def log(msg):
    print(f'{datetime.now()} {msg}', flush=True)


def date_to_epoch(date_string, fmt='%Y-%m-%d'):
    """Midnight UTC of a date, as a Unix timestamp."""
    return datetime.strptime(date_string, fmt).replace(tzinfo=timezone.utc).timestamp()


def http_get(url, **params):
    response = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
    if not response.ok:
        raise Exception(f'HTTP {response.status_code} from {url}: {response.text[:200]}')
    return response


class Plugin:
    """A data source. fetch() returns a flat dict of fields for one symbol, or None if there is no data."""

    def __init__(self, source):
        self.source = source

    def require_api_key(self):
        key = self.source.get('api_key')
        # An unexpanded ${VAR} means the environment variable isn't set
        if not key or key.startswith('$'):
            raise Exception(f"Source {self.source['name']} requires api_key for the {self.source['plugin']} plugin")
        return key

    def begin_poll(self):
        """Called once before each poll of the source's tickers."""

    def fetch(self, symbol):
        raise NotImplementedError
