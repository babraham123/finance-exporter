from datetime import datetime, timezone

import requests

from ..clock import Clock

HTTP_TIMEOUT = 30


class RateLimited(Exception):
    """The provider asked us to slow down."""


def date_to_epoch(date_string, fmt='%Y-%m-%d'):
    """Midnight UTC of a date, as a Unix timestamp."""
    return datetime.strptime(date_string, fmt).replace(tzinfo=timezone.utc).timestamp()


def http_get(url, **params):
    response = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
    if not response.ok:
        raise Exception(f'HTTP {response.status_code} from {url}: {response.text[:200]}')
    return response


class Settings:
    """A plugin's own source settings, declared as JSON Schema properties.

    Beyond JSON Schema, a property may set 'secret': True to keep its value out of logs.
    A 'default' is filled in when the config leaves the setting out.
    """

    def __init__(self, properties=None, required=()):
        self.properties = properties or dict()
        self.required = list(required)
        self.secrets = frozenset(key for key, spec in self.properties.items() if spec.get('secret'))

    def schema(self):
        """The properties and required keys this plugin adds to the source schema."""
        return {
            'properties': { key: { k: v for k, v in spec.items() if k != 'secret' } for key, spec in self.properties.items() },
            'required': self.required,
        }

    def resolve(self, values):
        """values, with the defaults of settings left out filled in."""
        return { **{ key: spec['default'] for key, spec in self.properties.items() if 'default' in spec }, **values }


class Plugin:
    """A data source for one configured source's tickers.

    All I/O goes through `client`, whose live implementation comes from live_client(); tests replay recorded
    responses through the same methods. Waiting and reading the date go through `clock`.
    """
    SETTINGS = Settings()

    def __init__(self, settings, client, clock=None):
        self.settings = settings
        self.client = client
        self.clock = clock or Clock()

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
