"""Loads the config file into validated, immutable values."""
import copy
import os
import re
from dataclasses import dataclass, field
from importlib import resources

import jsonschema
import yaml

from .plugins import PLUGINS
from .source import BUILTIN_METRICS

# Top-level keys that are no longer supported, with how to migrate
REMOVED_KEYS = {
    'tickers': "move the tickers each source should poll into that source's `tickers` list",
    'update_cache_on_startup': 'delete it; labels are no longer shared between sources',
}
# Source keys every plugin shares; anything else is a plugin setting
SOURCE_KEYS = ('name', 'plugin', 'interval', 'tickers', 'metrics', 'labels')
UNEXPANDED_VARIABLE = re.compile(r'\$(\w+|\{[^}]*\})')


@dataclass(frozen=True)
class MetricSpec:
    name: str
    item: str
    type: str
    help: str
    scale: float = 1


@dataclass(frozen=True)
class SourceConfig:
    name: str
    plugin: str
    interval: int
    tickers: tuple
    metrics: tuple
    labels: dict = field(default_factory=dict)
    # Plugin-specific settings, with the plugin's defaults filled in
    settings: dict = field(default_factory=dict)
    secrets: frozenset = frozenset()


@dataclass(frozen=True)
class Config:
    port: int
    address: str
    sources: tuple
    metric_prefix: str = None
    min_interval: int = 15

    def redacted(self):
        """The config as plain data, with secret settings hidden, for logging."""
        return {
            'port': self.port, 'address': self.address, 'metric_prefix': self.metric_prefix, 'min_interval': self.min_interval,
            'sources': [
                { 'name': s.name, 'plugin': s.plugin, 'interval': s.interval, 'tickers': list(s.tickers),
                  'metrics': { m.name: { 'item': m.item, 'type': m.type, 'help': m.help, 'scale': m.scale } for m in s.metrics },
                  'labels': s.labels,
                  **{ k: ('<redacted>' if k in s.secrets else v) for k, v in s.settings.items() } }
                for s in self.sources
            ],
        }


def schema():
    """schema.yaml, with one source schema per plugin built from the generic source fields plus the plugin's SETTINGS."""
    full = yaml.safe_load(resources.files(__package__).joinpath('schema.yaml').read_text())
    generic = full['definitions']['source']
    full['definitions']['source'] = {
        'type': 'object',
        'required': ['plugin'],
        'properties': {'plugin': {'enum': list(PLUGINS)}},
        'allOf': [
            {'if': {'properties': {'plugin': {'const': name}}}, 'then': {'$ref': f'#/definitions/source_{name}'}}
            for name in PLUGINS
        ],
    }
    for name, plugin_class in PLUGINS.items():
        settings = plugin_class.SETTINGS
        source = copy.deepcopy(generic)
        source['properties'].update({ key: _schema_only(spec) for key, spec in settings.get('properties', dict()).items() })
        source['required'] = generic['required'] + settings.get('required', list())
        full['definitions'][f'source_{name}'] = source
    return full


def _schema_only(spec):
    return { k: v for k, v in spec.items() if k != 'secret' }


def load_config(path, port=None, address=None):
    """Read, validate and type the config file. port and address, when given, override the file."""
    with open(path) as fd:
        # Expand ${VAR} references so secrets like API keys can live in the environment
        raw = yaml.safe_load(os.path.expandvars(fd.read()))
    for key, hint in REMOVED_KEYS.items():
        if key in raw:
            raise Exception(f"Config key `{key}` is no longer supported: {hint}")
    _check_variables_expanded(raw)
    try:
        jsonschema.validate(raw, schema())
    except jsonschema.ValidationError as e:
        location = '/'.join(str(item) for item in e.absolute_path)
        raise Exception(f'Invalid config at {location}: {e.message}')
    sources = tuple(_source(source) for source in raw['sources'])
    _check_names(sources)
    return Config(
        port=raw['port'] if port is None else port,
        address=raw['address'] if address is None else address,
        sources=sources,
        metric_prefix=raw.get('metric_prefix'),
        min_interval=raw.get('min_interval', 15),
    )


def _check_variables_expanded(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items():
            _check_variables_expanded(item, path + (key,))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _check_variables_expanded(item, path + (index,))
    elif isinstance(value, str):
        match = UNEXPANDED_VARIABLE.search(value)
        if match:
            location = '/'.join(str(item) for item in path)
            raise Exception(f"Environment variable {match.group(1).strip('{}')} is not set (used at {location})")


def _source(raw):
    plugin_settings = PLUGINS[raw['plugin']].SETTINGS.get('properties', dict())
    settings = { key: spec['default'] for key, spec in plugin_settings.items() if 'default' in spec }
    settings.update({ key: value for key, value in raw.items() if key not in SOURCE_KEYS })
    return SourceConfig(
        name=raw['name'],
        plugin=raw['plugin'],
        interval=raw['interval'],
        tickers=tuple(raw['tickers']),
        metrics=tuple(MetricSpec(name=name, **metric) for name, metric in raw['metrics'].items()),
        labels=dict(raw.get('labels') or dict()),
        settings=settings,
        secrets=frozenset(key for key, spec in plugin_settings.items() if spec.get('secret')),
    )


def _check_names(sources):
    names = set()
    metrics = dict()
    for source in sources:
        if source.name in names:
            raise Exception(f'Source name {source.name} is used more than once')
        names.add(source.name)
        for metric in source.metrics:
            if metric.name in BUILTIN_METRICS:
                raise Exception(f'Metric {metric.name} in source {source.name} clashes with a built-in metric')
            if metric.name in metrics:
                raise Exception(f'Metric {metric.name} is defined by sources {metrics[metric.name]} and {source.name}; metric names must be unique across sources')
            metrics[metric.name] = source.name
