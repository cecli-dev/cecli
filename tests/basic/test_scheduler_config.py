import os
import tempfile

import yaml

from cecli.args import get_parser
from cecli.main import (
    _scheduler_config,
    _scheduler_enabled,
    convert_yaml_to_json_string,
)


class _Args:
    def __init__(self, scheduler=None):
        self.scheduler = scheduler


class _Workflow:
    def __init__(self, schedule=None, enabled=True):
        self.schedule = schedule
        self.enabled = enabled


def _parse_config(config, argv=()):
    fd, path = tempfile.mkstemp(suffix=".yml")
    os.close(fd)

    try:
        with open(path, "w") as f:
            yaml.dump(config, f)

        parser = get_parser([path], None)

        return parser.parse_known_args(list(argv))[0]
    finally:
        os.unlink(path)


def _resolve_scheduler(config, argv=()):
    """Mirror main_async: parse the config, then deep-merge the scheduler arg."""

    args = _parse_config(config, argv)

    if args.scheduler is not None:
        args.scheduler = convert_yaml_to_json_string(args.scheduler, config.get("scheduler"))

    return _scheduler_config(args)


def test_scheduler_object_parses_without_aborting_startup():
    """Regression: the documented object form used to abort argparse startup."""

    resolved = _resolve_scheduler({"scheduler": {"enabled": False, "tick_seconds": 5}})

    assert resolved == {
        "enabled": False,
        "tick_seconds": 5,
        "catch_up": True,
        "max_catchup": 1,
    }


def test_scheduler_absent_uses_documented_defaults_and_auto():
    resolved = _resolve_scheduler({})

    assert resolved == {
        "enabled": None,
        "tick_seconds": 60,
        "catch_up": True,
        "max_catchup": 1,
    }


def test_cli_scheduler_json_overrides_config_per_key():
    config = {"scheduler": {"enabled": True, "tick_seconds": 5}}
    resolved = _resolve_scheduler(config, argv=["--scheduler", '{"enabled": false}'])

    assert resolved["enabled"] is False  # CLI wins
    assert resolved["tick_seconds"] == 5  # file-only key preserved


def test_scheduler_config_defaults_on_bad_input():
    assert _scheduler_config(_Args(None))["tick_seconds"] == 60
    assert _scheduler_config(_Args("not json"))["tick_seconds"] == 60
    assert _scheduler_config(_Args("[1, 2]"))["tick_seconds"] == 60


def test_scheduler_enabled_explicit_and_auto():
    scheduled = _Workflow(schedule="@daily")
    manual = _Workflow(schedule=None)

    assert _scheduler_enabled({"enabled": True}, [manual]) is True
    assert _scheduler_enabled({"enabled": False}, [scheduled]) is False
    assert _scheduler_enabled({"enabled": None}, [scheduled]) is True  # auto
    assert _scheduler_enabled({"enabled": None}, [manual]) is False  # auto
