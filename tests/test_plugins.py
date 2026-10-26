"""Each plugin's edge cases, through fetch_all with small fake clients."""

from datetime import date

from clients import Replay
from conftest import RECORDED_ON, FakeClock, fixture
from finance_exporter.plugins.alphavantage import AlphaVantage
from finance_exporter.plugins.base import RateLimited
from finance_exporter.plugins.fred import Fred
from finance_exporter.plugins.treasury import Treasury
from finance_exporter.plugins.yahoo import Yahoo


def settings(**values):
    return values


class RateLimitedYahoo:
    """Replays recorded quotes after refusing the first `refusals` requests."""

    def __init__(self, refusals):
        self.refusals = refusals
        self.replay = Replay("yfinance")

    def info(self, symbol):
        if self.refusals:
            self.refusals -= 1
            raise RateLimited("Too Many Requests")
        return self.replay.info(symbol)

    def funds(self, symbol):
        return self.replay.funds(symbol)


def test_yahoo_retries_rate_limits_with_exponential_backoff():
    clock = FakeClock()
    yahoo = Yahoo(settings(), RateLimitedYahoo(refusals=2), clock)

    assert (
        dict(yahoo.fetch_all(["AAPL"]))["AAPL"]["regularMarketPrice"]
        == fixture("yfinance", "info", "AAPL")["regularMarketPrice"]
    )
    assert clock.sleeps == [5, 10]


def test_yahoo_gives_up_after_three_retries():
    clock = FakeClock()
    yahoo = Yahoo(settings(), RateLimitedYahoo(refusals=4), clock)

    assert isinstance(dict(yahoo.fetch_all(["AAPL"]))["AAPL"], RateLimited)
    assert clock.sleeps == [5, 10, 20]


def test_yahoo_keeps_the_quote_when_fund_data_fails():
    class NoFundData(RateLimitedYahoo):
        def funds(self, symbol):
            raise ConnectionError("funds unavailable")

    quote = dict(Yahoo(settings(), NoFundData(refusals=0)).fetch_all(["VTSAX"]))["VTSAX"]

    assert quote["asset_class"] == "mutual_fund"
    # category comes only from fund data for this fund
    assert quote.get("category") is None


class FakeFred:
    def __init__(self, observations, title="Series"):
        self.observations_ = observations
        self.title = title
        self.series_calls = 0

    def series(self, series_id):
        self.series_calls += 1
        return {"seriess": [{"title": self.title, "frequency": "Daily", "units": "Percent"}]}

    def observations(self, series_id):
        return {"observations": self.observations_}


def test_fred_has_no_data_when_every_recent_observation_is_missing():
    fred = Fred(settings(api_key="key"), FakeFred([{"date": "2026-10-12", "value": "."}]))

    assert dict(fred.fetch_all(["DGS10"])) == {"DGS10": None}


def test_fred_reads_series_metadata_every_poll():
    client = FakeFred([{"date": "2026-10-09", "value": "5.24"}], title="Old title")
    fred = Fred(settings(api_key="key"), client)
    dict(fred.fetch_all(["DGS10"]))
    client.title = "New title"

    assert dict(fred.fetch_all(["DGS10"]))["DGS10"]["title"] == "New title"
    assert client.series_calls == 2


class TreasuryYears:
    """Recorded CSV for `recorded_year`, and an empty file (as published before a year's first business day) otherwise."""

    def __init__(self, recorded_year):
        self.recorded_year = recorded_year
        self.years = list()

    def year_csv(self, curve, year):
        self.years.append(year)
        return (
            fixture("treasury", "year_csv", curve, RECORDED_ON.year)
            if year == self.recorded_year
            else ""
        )


def test_treasury_uses_previous_year_before_its_first_business_day():
    client = TreasuryYears(recorded_year=RECORDED_ON.year)
    treasury = Treasury(
        settings(curve="nominal"), client, FakeClock(today=date(RECORDED_ON.year + 1, 1, 1))
    )

    assert dict(treasury.fetch_all(["10Y"]))["10Y"]["value"] is not None
    assert client.years == [RECORDED_ON.year + 1, RECORDED_ON.year]


def test_treasury_has_no_data_when_both_years_are_empty():
    treasury = Treasury(settings(curve="nominal"), TreasuryYears(recorded_year=None), FakeClock())

    assert dict(treasury.fetch_all(["3M", "10Y"])) == {"3M": None, "10Y": None}


def test_treasury_rejects_tenors_missing_from_the_curve():
    treasury = Treasury(settings(curve="real"), Replay("treasury"), FakeClock())
    results = dict(treasury.fetch_all(["3M", "10Y"]))

    assert isinstance(results["3M"], LookupError)
    assert results["10Y"]["curve"] == "real"


def test_alphavantage_spaces_requests_and_reports_throttling():
    class Throttled:
        def query(self, function, symbol):
            return {
                "Note": "Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day."
            }

    clock = FakeClock()
    ibm = dict(
        AlphaVantage(settings(api_key="demo"), Replay("alphavantage"), clock).fetch_all(["IBM"])
    )["IBM"]
    throttled = dict(
        AlphaVantage(settings(api_key="demo"), Throttled(), FakeClock()).fetch_all(["IBM"])
    )["IBM"]

    assert ibm["asset_class"] == "stock"
    assert clock.sleeps == [1, 1, 1]
    assert isinstance(throttled, RateLimited)
