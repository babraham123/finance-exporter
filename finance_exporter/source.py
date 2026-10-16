import logging
import time
from pprint import pformat

log = logging.getLogger(__name__)


class Source:
    """One configured source: polls its plugin for its tickers and records the results in its metrics."""

    def __init__(self, config, plugin, metrics):
        """config is a SourceConfig; plugin anything with fetch_all(symbols); metrics the exporter's Metrics."""
        self.name = config.name
        self.interval = config.interval
        self.tickers = list(config.tickers)
        self.plugin = plugin
        self.metrics = metrics.for_source(config)

    def poll(self):
        start_time = time.monotonic()
        pending = set(self.tickers)
        try:
            for ticker, result in self.plugin.fetch_all(self.tickers):
                pending.discard(ticker)
                if isinstance(result, Exception):
                    log.warning(f'Unable to fetch {ticker} from {self.name}: {result}')
                    self.metrics.fetch_failed(ticker)
                elif result is None:
                    log.info(f'No data for {ticker} from {self.name}')
                else:
                    log.debug(pformat(result))
                    self.metrics.record(ticker, result)
                    log.info(f'Updated {ticker} from {self.name}')
        except Exception as e:
            log.warning(f'Unable to poll {self.name}: {e}')
            for ticker in pending:
                self.metrics.fetch_failed(ticker)
        finally:
            self.metrics.observe_poll(time.monotonic() - start_time)
