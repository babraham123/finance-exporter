"""Stand-ins for a plugin's live client that replay or record its responses.

A call client.method(*args) maps to fixtures/<plugin>/<method>/<args joined by __>.json (dict responses) or .csv (text).
API keys are client constructor arguments, never method arguments, so they never reach fixture paths.
"""

import json
import os

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture_path(plugin, method, args, extension, root=FIXTURES):
    return os.path.join(root, plugin, method, "__".join(str(arg) for arg in args) + extension)


class Replay:
    def __init__(self, plugin, root=FIXTURES):
        self.plugin = plugin
        self.root = root

    def __getattr__(self, method):
        def call(*args):
            path = fixture_path(self.plugin, method, args, ".json", self.root)
            if os.path.exists(path):
                with open(path) as fd:
                    return json.load(fd)
            path = fixture_path(self.plugin, method, args, ".csv", self.root)
            if os.path.exists(path):
                with open(path) as fd:
                    return fd.read()
            raise FileNotFoundError(f"No recorded {self.plugin} response for {method}{args}")

        return call


class Record:
    def __init__(self, live, plugin, root=FIXTURES):
        self.live = live
        self.plugin = plugin
        self.root = root

    def __getattr__(self, method):
        def call(*args):
            response = getattr(self.live, method)(*args)
            is_text = isinstance(response, str)
            path = fixture_path(
                self.plugin, method, args, ".csv" if is_text else ".json", self.root
            )
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fd:
                fd.write(
                    response
                    if is_text
                    else json.dumps(response, indent=1, sort_keys=True, default=str) + "\n"
                )
            print(f"wrote {os.path.relpath(path, self.root)}")
            return response

        return call
