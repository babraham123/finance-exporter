"""Loads the config file into validated, immutable values."""

import copy
import os
import re
from dataclasses import asdict, dataclass, field
from importlib import resources

import jsonschema
import yaml

from .plugins import PLUGINS

# Top-level keys that are no longer supported, with how to migrate
REMOVED_KEYS = {
    "tickers": "move the tickers each source should poll into that source's `tickers` list",
    "update_cache_on_startup": "delete it; labels are no longer shared between sources",
    "min_interval": "delete it; each source now polls on its own schedule, every `interval` seconds",
}
SCHEMA = yaml.safe_load(resources.files(__package__).joinpath("schema.yaml").read_text())
# Source keys every plugin shares; anything else is a plugin setting
SOURCE_KEYS = tuple(SCHEMA["definitions"]["source"]["properties"])
UNEXPANDED_VARIABLE = re.compile(r"\$(\w+|\{[^}]*\})")


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

    def redacted(self):
        """Shaped like the source's entry in the config file, with secret settings hidden."""
        shared = {key: value for key, value in asdict(self).items() if key in SOURCE_KEYS}
        return {
            **shared,
            **{
                key: ("<redacted>" if key in self.secrets else value)
                for key, value in self.settings.items()
            },
        }


@dataclass(frozen=True)
class Config:
    port: int
    address: str
    sources: tuple
    metric_prefix: str = None

    def redacted(self):
        """The config as plain data, with secret settings hidden, for logging."""
        return {**asdict(self), "sources": [source.redacted() for source in self.sources]}


def schema():
    """schema.yaml, with one source schema per plugin built from the generic source fields plus the plugin's SETTINGS."""
    full = copy.deepcopy(SCHEMA)
    generic = full["definitions"]["source"]
    full["definitions"]["source"] = {
        "type": "object",
        "required": ["plugin"],
        "properties": {"plugin": {"enum": list(PLUGINS)}},
        "allOf": [
            {
                "if": {"properties": {"plugin": {"const": name}}},
                "then": {"$ref": f"#/definitions/source_{name}"},
            }
            for name in PLUGINS
        ],
    }
    for name, plugin_class in PLUGINS.items():
        settings = plugin_class.SETTINGS.schema()
        source = copy.deepcopy(generic)
        source["properties"].update(settings["properties"])
        source["required"] = generic["required"] + settings["required"]
        full["definitions"][f"source_{name}"] = source
    return full


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
        location = "/".join(str(item) for item in e.absolute_path)
        raise Exception(f"Invalid config at {location}: {e.message}")
    sources = tuple(source_config(source) for source in raw["sources"])
    _check_names_unique(sources)
    return Config(
        port=raw["port"] if port is None else port,
        address=raw["address"] if address is None else address,
        sources=sources,
        metric_prefix=raw.get("metric_prefix"),
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
            location = "/".join(str(item) for item in path)
            raise Exception(
                f"Environment variable {match.group(1).strip('{}')} is not set (used at {location})"
            )


def source_config(raw):
    """One validated source entry from the config file, typed, with its plugin's setting defaults filled in."""
    plugin_settings = PLUGINS[raw["plugin"]].SETTINGS
    return SourceConfig(
        name=raw["name"],
        plugin=raw["plugin"],
        interval=raw["interval"],
        tickers=tuple(raw["tickers"]),
        metrics=tuple(MetricSpec(name=name, **metric) for name, metric in raw["metrics"].items()),
        labels=dict(raw.get("labels") or dict()),
        settings=plugin_settings.resolve(
            {key: value for key, value in raw.items() if key not in SOURCE_KEYS}
        ),
        secrets=plugin_settings.secrets,
    )


def _check_names_unique(sources):
    names = set()
    for source in sources:
        if source.name in names:
            raise Exception(f"Source name {source.name} is used more than once")
        names.add(source.name)
