from .alphavantage import AlphaVantage
from .fred import Fred
from .treasury import Treasury
from .yahoo import Yahoo

PLUGINS = {
    'yfinance': Yahoo,
    'fred': Fred,
    'treasury': Treasury,
    'alphavantage': AlphaVantage,
}


def live_client(source):
    """The client that talks to a SourceConfig's real provider."""
    return PLUGINS[source.plugin].live_client(source.settings)


def build_plugin(source, client, clock):
    """The plugin for a SourceConfig, doing its I/O through `client`."""
    return PLUGINS[source.plugin](source.settings, client, clock)
