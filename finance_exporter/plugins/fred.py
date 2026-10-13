from .base import Plugin, date_to_epoch, http_get

BASE_URL = 'https://api.stlouisfed.org/fred'
# The newest observations of a daily series are "." on holidays, so look back far enough to find a value
LOOKBACK = 10


class FredClient:

    def __init__(self, api_key):
        self.api_key = api_key

    def series(self, series_id):
        return self._get('series', series_id=series_id)

    def observations(self, series_id):
        return self._get('series/observations', series_id=series_id, sort_order='desc', limit=LOOKBACK)

    def _get(self, path, **params):
        return http_get(f'{BASE_URL}/{path}', api_key=self.api_key, file_type='json', **params).json()


class Fred(Plugin):

    def __init__(self, source, client, **kwargs):
        super().__init__(source, client, **kwargs)
        self.require_api_key()

    @classmethod
    def live_client(cls, source):
        return FredClient(source.get('api_key'))

    def fetch(self, symbol):
        # Fetched every poll so renamed or re-based series show up without a restart
        series = self.client.series(symbol)['seriess'][0]
        observations = self.client.observations(symbol)['observations']
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
