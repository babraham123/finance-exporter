import re
import time
from .base import Plugin, http_get

BASE_URL = 'https://www.alphavantage.co/query'
ASSET_TYPES = {'Common Stock': 'stock', 'ETF': 'etf', 'Mutual Fund': 'mutual_fund'}
# Back-to-back requests trip the per-second limit
REQUEST_SPACING_SECONDS = 1


class AlphaVantage(Plugin):
    """Free tier allows 25 requests/day, and each fetch makes 3."""

    def __init__(self, source):
        super().__init__(source)
        self.api_key = self.require_api_key()

    def fetch(self, symbol):
        quote = self._get('GLOBAL_QUOTE', symbol).get('Global Quote') or dict()
        # Keys look like "05. price"
        info = { re.sub(r'^\d+\.\s+', '', k): v for k, v in quote.items() }
        overview = self._get('OVERVIEW', symbol)
        info.update(overview)
        earnings = self._get('EARNINGS', symbol).get('quarterlyEarnings') or list()
        if earnings:
            info.update(earnings[0])
        info['asset_class'] = ASSET_TYPES.get(overview.get('AssetType'), 'unknown')
        return info

    def _get(self, function, symbol):
        time.sleep(REQUEST_SPACING_SECONDS)
        response = http_get(BASE_URL, function=function, symbol=symbol, apikey=self.api_key).json()
        # Throttling and bad requests come back as HTTP 200 with a message instead of data
        for key in ('Note', 'Information', 'Error Message'):
            if key in response:
                raise Exception(f'AlphaVantage {function} {symbol}: {response[key]}')
        return response
