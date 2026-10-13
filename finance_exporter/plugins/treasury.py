import csv
import io
import logging
import re
from datetime import datetime, timezone
from .base import Plugin, date_to_epoch, http_get

log = logging.getLogger(__name__)

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


class Treasury(Plugin):

    def __init__(self, source):
        super().__init__(source)
        self.curve = source.get('curve', 'nominal')
        self.latest = None

    def begin_poll(self):
        year = datetime.now(timezone.utc).year
        # The current year's file is empty until the first business day of January
        self.latest = self._latest_row(year) or self._latest_row(year - 1)

    def fetch(self, symbol):
        if self.latest is None:
            return None
        observation_time, yields = self.latest
        value = yields.get(symbol.upper())
        if value is None:
            log.warning(f"Tenor {symbol} not on the {self.curve} curve; available: {', '.join(yields)}")
            return None
        return {
            'value': value,
            'observation_time': observation_time,
            'curve': self.curve,
            'asset_class': 'treasury_yield',
        }

    def _latest_row(self, year):
        text = http_get(URL.format(year=year), type=CURVES[self.curve], field_tdr_date_value=year, _format='csv').text
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows:
            return None
        row = max(rows, key=lambda r: datetime.strptime(r['Date'], DATE_FORMAT))
        yields = { tenor(column): value for column, value in row.items() if tenor(column) and value }
        return date_to_epoch(row['Date'], DATE_FORMAT), yields
