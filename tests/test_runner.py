import threading

from conftest import FakeClock
from finance_exporter.runner import Runner


class TimedSource:
    """Each poll takes the next of `durations` seconds of virtual time; the last poll stops the runner."""

    def __init__(self, clock, stop, interval, durations, fail_on=()):
        self.name = 'timed'
        self.clock = clock
        self.stop = stop
        self.interval = interval
        self.durations = list(durations)
        self.fail_on = fail_on
        self.started = list()

    def poll(self):
        self.started.append(self.clock.now())
        self.clock.time += self.durations.pop(0)
        if not self.durations:
            self.stop.set()
        if len(self.started) in self.fail_on:
            raise RuntimeError('unexpected bug')


def run(interval, durations, fail_on=()):
    clock = FakeClock()
    stop = threading.Event()
    source = TimedSource(clock, stop, interval, durations, fail_on)
    Runner(source, clock).run(stop)
    return source.started


def test_polls_start_every_interval_regardless_of_poll_duration():
    assert run(60, [5, 20, 1]) == [0, 60, 120]


def test_an_overrunning_poll_is_followed_immediately_without_catching_up():
    assert run(60, [150, 5, 5]) == [0, 150, 210]


def test_a_failing_poll_does_not_stop_the_source():
    assert run(60, [1, 1, 1], fail_on=(1,)) == [0, 60, 120]


def test_stopping_ends_the_runner_without_another_poll():
    clock = FakeClock()
    stop = threading.Event()
    stop.set()
    source = TimedSource(clock, stop, 60, [1])

    Runner(source, clock).run(stop)

    assert source.started == []
