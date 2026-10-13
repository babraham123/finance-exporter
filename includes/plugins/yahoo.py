import time
import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError
from .base import Plugin, log

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


class Yahoo(Plugin):

    def fetch(self, symbol):
        for attempt in range(RETRIES + 1):
            try:
                return self._fetch(symbol)
            except YFRateLimitError:
                if attempt == RETRIES:
                    raise
                delay = BACKOFF_SECONDS * 2 ** attempt
                log(f"Yahoo rate limited fetching {symbol}; retrying in {delay}s")
                time.sleep(delay)

    def _fetch(self, symbol):
        ticker = yf.Ticker(symbol)
        quote = dict(ticker.info)
        quote_type = quote.get('quoteType')
        quote['asset_class'] = ASSET_CLASSES.get(quote_type, str(quote_type).lower())
        if quote_type in FUND_TYPES:
            for field, value in self._funds_data(ticker, symbol).items():
                if quote.get(field) is None:
                    quote[field] = value
        return quote

    def _funds_data(self, ticker, symbol):
        fields = dict()
        try:
            funds = ticker.funds_data
            overview = funds.fund_overview or dict()
            fields.update({ name: overview[key] for key, name in FUND_OVERVIEW.items() if overview.get(key) is not None })
            fields.update(funds.asset_classes or dict())
            operations = funds.fund_operations
            if symbol in operations:
                column = operations[symbol]
                fields.update({ name: column[row] for row, name in FUND_OPERATIONS.items() if row in column.index and pd.notna(column[row]) })
        except Exception as e:
            # Fund details are supplementary; keep the quote
            log(f"Unable to fetch fund data for {symbol}: {e}")
        return fields
