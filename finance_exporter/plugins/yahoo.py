import logging
import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError
from .base import Plugin, RateLimited

log = logging.getLogger(__name__)

ASSET_CLASSES = {
    'EQUITY': 'stock',
    'ETF': 'etf',
    'MUTUALFUND': 'mutual_fund',
    'INDEX': 'index',
    'CURRENCY': 'fx',
    'CRYPTOCURRENCY': 'crypto',
    'FUTURE': 'future',
}
FUND_TYPES = ('ETF', 'MUTUALFUND')
# funds_data field -> quote field; fills gaps where .info lacks fund details (common for mutual funds)
FUND_OVERVIEW = {'categoryName': 'category', 'family': 'fundFamily', 'legalType': 'legalType'}
FUND_OPERATIONS = {
    'Annual Report Expense Ratio': 'annualReportExpenseRatio',
    'Annual Holdings Turnover': 'annualHoldingsTurnover',
}
RETRIES = 3
BACKOFF_SECONDS = 5


class YahooClient:
    """yfinance, reduced to plain dicts."""

    def info(self, symbol):
        try:
            return dict(yf.Ticker(symbol).info)
        except YFRateLimitError as e:
            raise RateLimited(str(e)) from e

    def funds(self, symbol):
        """Fund overview, asset mix, and this fund's operations column (rows Yahoo has no value for are left out)."""
        funds = yf.Ticker(symbol).funds_data
        operations = funds.fund_operations
        column = operations[symbol] if symbol in operations else dict()
        return {
            'fund_overview': funds.fund_overview or dict(),
            'asset_classes': funds.asset_classes or dict(),
            'fund_operations': { row: value for row, value in column.items() if pd.notna(value) },
        }


class Yahoo(Plugin):

    @classmethod
    def live_client(cls, source):
        return YahooClient()

    def fetch(self, symbol):
        for attempt in range(RETRIES + 1):
            try:
                return self._fetch(symbol)
            except RateLimited:
                if attempt == RETRIES:
                    raise
                delay = BACKOFF_SECONDS * 2 ** attempt
                log.warning(f"Yahoo rate limited fetching {symbol}; retrying in {delay}s")
                self.sleep(delay)

    def _fetch(self, symbol):
        quote = self.client.info(symbol)
        quote_type = quote.get('quoteType')
        quote['asset_class'] = ASSET_CLASSES.get(quote_type, str(quote_type).lower())
        if quote_type in FUND_TYPES:
            for field, value in self._fund_fields(symbol).items():
                if quote.get(field) is None:
                    quote[field] = value
        return quote

    def _fund_fields(self, symbol):
        fields = dict()
        try:
            funds = self.client.funds(symbol)
        except Exception as e:
            # Fund details are supplementary; keep the quote
            log.warning(f"Unable to fetch fund data for {symbol}: {e}")
            return fields
        overview = funds['fund_overview']
        fields.update({ name: overview[key] for key, name in FUND_OVERVIEW.items() if overview.get(key) is not None })
        fields.update(funds['asset_classes'])
        operations = funds['fund_operations']
        fields.update({ name: operations[row] for row, name in FUND_OPERATIONS.items() if operations.get(row) is not None })
        return fields
