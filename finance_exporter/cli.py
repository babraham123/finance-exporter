import argparse
import logging
import signal
import threading
from pprint import pformat

from .config import load_config
from .exporter import Exporter

log = logging.getLogger(__name__)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="finance-exporter", description="Finance Prometheus Exporter"
    )
    parser.add_argument("-f", "--config", help="Location of config yaml", required=True)
    parser.add_argument("-v", "--verbose", action="store_true", help="Log each update")
    parser.add_argument(
        "-d", "--debug", action="store_true", help="Log the config and every API response"
    )
    parser.add_argument("-p", "--port", type=int, help="Listen port")
    parser.add_argument("-a", "--address", help="Listen address")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    level = logging.DEBUG if args.debug else logging.INFO if args.verbose else logging.WARNING
    logging.basicConfig(
        level=level, format="%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s"
    )

    config = load_config(args.config, port=args.port, address=args.address)
    log.debug(f"Running with config:\n{pformat(config.redacted())}")
    exporter = Exporter(config)

    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    exporter.start()
    while not stop.wait(1):
        pass

    log.info("Shutting down")
    exporter.stop()
