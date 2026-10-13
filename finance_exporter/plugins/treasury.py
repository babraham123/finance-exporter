import csv
import io
import re
from datetime import datetime
from .base import Plugin, date_to_epoch, http_get

URL = 'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{year}/all'
CURVES = {
    'nominal': 'daily_treasury_yield_curve',
    'real': 'daily_treasury_real_yield_curve',
}
DATE_FORMAT = '%m/%d/%Y'
# Column headers vary by curve: "1 Mo", "1.5 Month", "10 Yr", "10 YR"
TENOR = re.compile(r'^([\d.]+)\s*(mo|month|yr|year)s?$', re.IGNORECASE)


def tenor(column):
    match = TENOR.match(column.strip())
    if match is None:
        return None
    return match.group(1) + ('M' if match.group(2).lower().startswith('mo') else 'Y')


class TreasuryClient:

    def year_csv(self, curve, year):
        """Every business day's par yields on the curve for one year, as CSV text."""
        return http_get(URL.format(year=year), type=CURVES[curve], field_tdr_date_value=year, _format='csv').text


class Treasury(Plugin):
    SETTINGS = {
        'properties': {'curve': {'enum': list(CURVES), 'default': 'nominal', 'description': 'Which daily Treasury par yield curve to read'}},
    }

    def __init__(self, settings, client, **kwargs):
        super().__init__(settings, client, **kwargs)
        self.curve = settings['curve']

    @classmethod
    def live_client(cls, settings):
        return TreasuryClient()

    def fetch_all(self, symbols):
        year = self.today().year
        # The current year's file is empty until the first business day of January
        latest = self._latest_row(year) or self._latest_row(year - 1)
        if latest is None:
            for symbol in symbols:
                yield symbol, None
            return
        observation_time, yields = latest
        for symbol in symbols:
            value = yields.get(symbol.upper())
            if value is None:
                yield symbol, LookupError(f"Tenor {symbol} not on the {self.curve} curve; available: {', '.join(yields)}")
                continue
            yield symbol, {
                'value': value,
                'observation_time': observation_time,
                'curve': self.curve,
                'asset_class': 'treasury_yield',
            }

    def _latest_row(self, year):
        rows = list(csv.DictReader(io.StringIO(self.client.year_csv(self.curve, year))))
        if not rows:
            return None
        row = max(rows, key=lambda r: datetime.strptime(r['Date'], DATE_FORMAT))
        yields = { tenor(column): value for column, value in row.items() if tenor(column) and value }
        return date_to_epoch(row['Date'], DATE_FORMAT), yields
