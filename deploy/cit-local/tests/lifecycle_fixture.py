"""A small Docker state machine for existing-container lifecycle regressions."""

import copy
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_lifecycle():
    path = ROOT / "lifecycle.py"
    assert path.exists(), "Existing-container operations need a shared lifecycle guard"
    spec = importlib.util.spec_from_file_location("lifecycle", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules["lifecycle"] = module
    return module


class DockerFixture:
    def __init__(self, *, apps=2):
        names = ["postgres", "clamav", *(["app"] * apps), "email", "reconcile", "web", "migrate", "initialize"]
        self.records = {}
        self.commands = []
        self.fail_stop = False
        for index, name in enumerate(names, 1):
            identifier = f"{index:064x}"
            active = name not in {"migrate", "initialize"}
            self.records[identifier] = {
                "Id": identifier, "Image": "sha256:" + f"{index:064x}",
                "Project": "litblogs-cit", "Service": name, "Oneoff": "False",
                "State": "running" if active else "exited",
                "Health": "healthy" if active else None,
                "StartedAt": f"original-{index}",
            }

    def ids(self, *services):
        return [key for key, row in self.records.items() if row["Service"] in services]

    def snapshot(self):
        return copy.deepcopy(self.records)

    def run(self, arguments, *, timeout=120):
        self.commands.append(arguments)
        if arguments[:2] == ["container", "ls"]:
            return ("\n".join(self.records) + "\n").encode()
        if arguments[:2] == ["container", "inspect"]:
            return ("\n".join(json.dumps(self.records[key]) for key in arguments[4:]) + "\n").encode()
        if arguments[:2] == ["container", "stop"]:
            for key in arguments[4:]:
                self.records[key]["State"] = "exited"
                self.records[key]["Health"] = None
                if self.fail_stop:
                    raise RuntimeError("partial Docker stop fixture")
            return b""
        if arguments[:2] == ["container", "start"]:
            for key in arguments[2:]:
                row = self.records[key]
                if row["State"] != "running":
                    row.update(State="running", Health="healthy", StartedAt="resumed")
            return b""
        raise AssertionError("Unexpected Docker operation")

    def mutations(self):
        return [item for item in self.commands if item[:2] in (["container", "start"], ["container", "stop"])]
