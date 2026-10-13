import re
from .base import Plugin, RateLimited, http_get

BASE_URL = 'https://www.alphavantage.co/query'
ASSET_TYPES = {'Common Stock': 'stock', 'ETF': 'etf', 'Mutual Fund': 'mutual_fund'}
# Back-to-back requests trip the per-second limit
REQUEST_SPACING_SECONDS = 1


class AlphaVantageClient:

    def __init__(self, api_key):
        self.api_key = api_key

    def query(self, function, symbol):
        return http_get(BASE_URL, function=function, symbol=symbol, apikey=self.api_key).json()


class AlphaVantage(Plugin):
    """Free tier allows 25 requests/day, and each fetch makes 3."""

    def __init__(self, source, client, **kwargs):
        super().__init__(source, client, **kwargs)
        self.require_api_key()

    @classmethod
    def live_client(cls, source):
        return AlphaVantageClient(source.get('api_key'))

    def fetch(self, symbol):
        quote = self._query('GLOBAL_QUOTE', symbol).get('Global Quote') or dict()
        # Keys look like "05. price"
        info = { re.sub(r'^\d+\.\s+', '', k): v for k, v in quote.items() }
        overview = self._query('OVERVIEW', symbol)
        info.update(overview)
        earnings = self._query('EARNINGS', symbol).get('quarterlyEarnings') or list()
        if earnings:
            info.update(earnings[0])
        info['asset_class'] = ASSET_TYPES.get(overview.get('AssetType'), 'unknown')
        return info

    def _query(self, function, symbol):
        self.sleep(REQUEST_SPACING_SECONDS)
        response = self.client.query(function, symbol)
        # Throttling and bad requests come back as HTTP 200 with a message instead of data
        if 'Note' in response or 'Information' in response:
            raise RateLimited(f"AlphaVantage {function} {symbol}: {response.get('Note') or response['Information']}")
        if 'Error Message' in response:
            raise Exception(f"AlphaVantage {function} {symbol}: {response['Error Message']}")
        return response
