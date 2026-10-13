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
