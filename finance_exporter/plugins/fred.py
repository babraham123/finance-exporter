from .base import Plugin, date_to_epoch, http_get

BASE_URL = 'https://api.stlouisfed.org/fred'
# The newest observations of a daily series are "." on holidays, so look back far enough to find a value
LOOKBACK = 10


class Fred(Plugin):

    def __init__(self, source):
        super().__init__(source)
        self.api_key = self.require_api_key()
        self.series = dict()

    def fetch(self, symbol):
        if symbol not in self.series:
            self.series[symbol] = self._get('series', series_id=symbol)['seriess'][0]
        series = self.series[symbol]
        observations = self._get('series/observations', series_id=symbol, sort_order='desc', limit=LOOKBACK)['observations']
        latest = next((o for o in observations if o['value'] != '.'), None)
        if latest is None:
            return None
        return {
            'value': latest['value'],
            'observation_time': date_to_epoch(latest['date']),
            'title': series['title'],
            'frequency': series['frequency'],
            'units': series['units'],
            'asset_class': 'rate' if series['units'] == 'Percent' else 'economic_indicator',
        }

    def _get(self, path, **params):
        return http_get(f'{BASE_URL}/{path}', api_key=self.api_key, file_type='json', **params).json()
