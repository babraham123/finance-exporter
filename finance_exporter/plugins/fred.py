from .base import Plugin, Settings, date_to_epoch, http_get

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
    SETTINGS = Settings(
        {'api_key': {'type': 'string', 'minLength': 1, 'secret': True, 'description': 'May reference an environment variable, e.g. ${FRED_API_KEY}'}},
        required=['api_key'],
    )

    @classmethod
    def live_client(cls, settings):
        return FredClient(settings['api_key'])

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
