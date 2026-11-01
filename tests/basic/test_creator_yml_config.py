"""Tests for the creator.yml config layer (highest config-file precedence)."""

import os
from pathlib import Path

import yaml

from cecli.helpers import config_utils
from cecli.helpers.creator import utils as creator_utils


def _write(path: Path, data: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data))

    return str(path)


def test_creator_yml_overrides_cecli_conf_yml(tmp_path):
    cecli_conf = _write(
        tmp_path / ".cecli.conf.yml",
        {"model": "file-model", "agent-config": {"a": 1, "b": 2}},
    )
    creator = _write(
        tmp_path / "creator.yml",
        {"model": "creator-model", "agent-config": {"b": 3}},
    )

    merged = config_utils.read_and_merge_all_configs(
        [cecli_conf, creator], [], [cecli_conf], [creator]
    )

    assert merged["model"] == "creator-model"

    assert merged["model"] == "creator-model"
    assert merged["agent-config"] == {"a": 1, "b": 3}


def test_local_creator_yml_overrides_global_creator_yml(tmp_path):
    global_creator = _write(
        tmp_path / "global" / "creator.yml",
        {"model": "global-model", "shared": {"keep": True, "val": "global"}},
    )
    local_creator = _write(
        tmp_path / "local" / "creator.yml",
        {"model": "local-model", "shared": {"val": "local"}},
    )

    merged = config_utils.read_and_merge_all_configs(
        [global_creator, local_creator], [], [], [global_creator, local_creator]
    )

    assert merged["model"] == "local-model"
    assert merged["shared"] == {"keep": True, "val": "local"}


def test_missing_creator_yml_files_are_graceful(tmp_path):
    cecli_conf = _write(tmp_path / ".cecli.conf.yml", {"model": "file-model"})
    missing_global = str(tmp_path / "nowhere" / "creator.yml")
    missing_local = str(tmp_path / "also-nowhere" / "creator.yml")

    merged = config_utils.read_and_merge_all_configs(
        [cecli_conf, missing_global, missing_local],
        [],
        [cecli_conf],
        [missing_global, missing_local],
    )

    assert merged == {"model": "file-model"}


def test_none_creator_paths_preserve_three_arg_behavior(tmp_path):
    cecli_conf = _write(tmp_path / ".cecli.conf.yml", {"model": "file-model"})

    four = config_utils.read_and_merge_all_configs([cecli_conf], [], [cecli_conf], None)
    three = config_utils.read_and_merge_all_configs([cecli_conf], [], [cecli_conf])

    assert three == four == {"model": "file-model"}


def test_creator_arrays_concatenate_over_cecli_conf(tmp_path):
    cecli_conf = _write(tmp_path / ".cecli.conf.yml", {"skills_paths": ["/from/conf"]})
    creator = _write(tmp_path / "creator.yml", {"skills_paths": ["/from/creator"]})

    merged = config_utils.read_and_merge_all_configs(
        [cecli_conf, creator], [], [cecli_conf], [creator]
    )

    assert merged["skills_paths"] == ["/from/conf", "/from/creator"]


def test_creator_yml_paths_returns_global_and_local(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"

    monkeypatch.setattr(creator_utils.Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.chdir(tmp_path)

    global_path, local_path = creator_utils.creator_yml_paths()

    assert global_path == str(fake_home / ".cecli" / "creator.yml")
    assert Path(local_path) == tmp_path / ".cecli" / "creator.yml"

    root = tmp_path / "repo"
    global_path, local_path = creator_utils.creator_yml_paths(root)

    assert global_path == str(fake_home / ".cecli" / "creator.yml")
    assert local_path == str(root / ".cecli" / "creator.yml")

    global_path, local_path = creator_utils.creator_yml_paths(str(root))

    assert local_path == str(root / ".cecli" / "creator.yml")


def test_resolve_config_paths_includes_creator_paths(tmp_path):
    class FakeCoder:
        root = tmp_path

    paths, conf_yml_paths, cecli_conf_paths, creator_paths = creator_utils.resolve_config_paths(
        FakeCoder()
    )

    assert creator_paths[0].endswith(os.path.join(".cecli", "creator.yml"))
    assert creator_paths[1] == str(tmp_path / ".cecli" / "creator.yml")
    assert all(p in paths for p in creator_paths)
    assert not any(p.endswith("creator.yml") for p in conf_yml_paths)
    assert not any(p.endswith("creator.yml") for p in cecli_conf_paths)


def test_read_merged_config_layers_creator_yml(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"

    monkeypatch.setattr(creator_utils.Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.delenv("CECLI_CONFIG_FILE", raising=False)

    class FakeCoder:
        root = tmp_path

    global_creator = _write(fake_home / ".cecli" / "creator.yml", {"model": "global"})
    _write(Path(global_creator).parent / ".cecli.conf.yml", {"model": "ignored"})

    merged = creator_utils.read_merged_config(FakeCoder())

    assert merged.get("model") == "global"
