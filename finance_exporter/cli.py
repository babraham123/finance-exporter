import argparse
import logging
import time
from pprint import pformat

from .exporter import Exporter

log = logging.getLogger(__name__)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog='finance-exporter', description='Finance Prometheus Exporter')
    parser.add_argument('-f', '--config', help='Location of config yaml', required=True)
    parser.add_argument('-v', '--verbose', action='store_true', help='Log each update')
    parser.add_argument('-d', '--debug', action='store_true', help='Log the config and every API response')
    parser.add_argument('-p', '--port', type=int, help='Listen port')
    parser.add_argument('-a', '--address', help='Listen address')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    level = logging.DEBUG if args.debug else logging.INFO if args.verbose else logging.WARNING
    logging.basicConfig(level=level, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

    exporter = Exporter(args.config, port=args.port, address=args.address)
    log.debug(f'Running with config:\n{pformat(exporter.redacted_config())}')
    exporter.start_server()

    last_run = { name: 0 for name in exporter.sources }
    while True:
        for name, source in exporter.sources.items():
            if time.time() - last_run[name] > source['interval']:
                log.info(f"Updating Source {name}")
                exporter.update(source)
                last_run[name] = time.time()
        time.sleep(exporter.config['min_interval'])
