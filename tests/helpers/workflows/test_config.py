"""Tests for workflow discovery, loading and validation (tests.md cases 1-8)."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest

from cecli.helpers.workflows import models
from cecli.helpers.workflows.config import (
    WORKFLOW_FILENAMES,
    load_workflows,
    resolve_workflow_configs,
    validate_workflow_config,
)

logger_name = "cecli.helpers.workflows.config"


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Point HOME and the cwd at empty temp dirs so no real config leaks in."""
    home = tmp_path / "home"
    (home / ".cecli" / "workflows").mkdir(parents=True)
    repo = tmp_path / "repo"
    repo.mkdir()

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.chdir(repo)

    return {"home": home, "repo": repo, "wdir": home / ".cecli" / "workflows"}


def _home_workflow(wdir: Path, filename: str, text: str) -> Path:
    path = wdir / filename
    path.write_text(text, encoding="utf-8")
    return path


def _home_agents_workflow(home: Path, filename: str, text: str) -> Path:
    wdir = home / ".agents" / "workflows"
    wdir.mkdir(parents=True, exist_ok=True)
    path = wdir / filename
    path.write_text(text, encoding="utf-8")
    return path


def _mapping_text(name: str, prompt: str) -> str:
    return f"name: {name}\ntasks:\n  - prompt: {prompt}\n"


def _local_dir_workflow(repo: Path, filename: str, text: str) -> Path:
    wdir = repo / ".cecli" / "workflows"
    wdir.mkdir(parents=True, exist_ok=True)
    path = wdir / filename
    path.write_text(text, encoding="utf-8")
    return path


def _agents_dir_workflow(repo: Path, filename: str, text: str) -> Path:
    wdir = repo / ".agents" / "workflows"
    wdir.mkdir(parents=True, exist_ok=True)
    path = wdir / filename
    path.write_text(text, encoding="utf-8")
    return path


# ── Case 1: single-mapping file, defaults ───────────────────────────────────


def test_workflow_filenames_cover_both_extensions():
    assert WORKFLOW_FILENAMES == (".cecli.workflows.yml", ".cecli.workflows.yaml")


def test_single_mapping_file_yields_defaults(isolated):
    _home_workflow(isolated["wdir"], "demo.yml", _mapping_text("demo", "say hi"))

    configs = load_workflows()

    assert [wf.name for wf in configs] == ["demo"]
    wf = configs[0]
    assert wf.enabled is True
    assert wf.lease_timeout == 30.0
    assert wf.on_failure == "stop"
    assert wf.timezone == "local"
    assert wf.catch_up is None
    assert wf.tasks[0].prompt == "say hi"
    assert wf.agent_name == "wf:demo"
    assert wf.source_path == str(isolated["wdir"] / "demo.yml")


def test_no_sources_loads_empty(isolated):
    assert load_workflows() == []


# ── Case 2: {workflows: [...]} list form, order preserved ───────────────────


def test_list_form_preserves_order(isolated):
    _home_workflow(
        isolated["wdir"],
        "many.yml",
        "workflows:\n"
        "  - name: alpha\n    tasks:\n      - prompt: a\n"
        "  - name: beta\n    tasks:\n      - prompt: b\n"
        "  - name: gamma\n    tasks:\n      - prompt: c\n",
    )

    assert [wf.name for wf in load_workflows()] == ["alpha", "beta", "gamma"]


def test_glob_of_home_files_is_stably_sorted(isolated):
    _home_workflow(isolated["wdir"], "b_second.yml", _mapping_text("b", "second"))
    _home_workflow(isolated["wdir"], "a_first.yml", _mapping_text("a", "first"))

    assert [wf.name for wf in load_workflows()] == ["a", "b"]


def test_home_agents_dir_files_are_loaded(isolated):
    _home_agents_workflow(
        isolated["home"], "pipelines.yml", _mapping_text("home-agents-dir", "check")
    )

    configs = load_workflows()

    assert [wf.name for wf in configs] == ["home-agents-dir"]
    assert configs[0].source_path == str(
        isolated["home"] / ".agents" / "workflows" / "pipelines.yml"
    )


def test_home_cecli_dir_wins_over_home_agents_dir(isolated):
    _home_agents_workflow(isolated["home"], "dup.yml", _mapping_text("dup", "agents"))
    _home_workflow(isolated["wdir"], "dup.yml", _mapping_text("dup", "cecli"))

    configs = load_workflows()

    assert [wf.tasks[0].prompt for wf in configs] == ["cecli"]


# ── Case 3: hyphen-case keys normalize ──────────────────────────────────────


def test_hyphen_case_keys_are_normalized(isolated):
    _home_workflow(
        isolated["wdir"],
        "hyphen.yml",
        "name: hy-demo\n"
        "lease-timeout: 12\n"
        "on-failure: continue\n"
        "tasks:\n"
        "  - prompt: work\n"
        "    continue-on-error: true\n",
    )

    wf = load_workflows()[0]
    assert wf.name == "hy-demo"
    assert wf.lease_timeout == 12.0
    assert wf.on_failure == "continue"
    assert wf.tasks[0].continue_on_error is True


# ── Case 4: environment interpolation ───────────────────────────────────────


def test_env_vars_interpolated(isolated, monkeypatch):
    monkeypatch.setenv("REPO_ROOT", "/srv/repo")

    _home_workflow(
        isolated["wdir"],
        "env.yml",
        "name: envy\nroot: ${REPO_ROOT}/x\ntasks:\n  - prompt: look at $REPO_ROOT\n",
    )

    wf = load_workflows()[0]
    assert wf.root == "/srv/repo/x"
    assert wf.tasks[0].prompt == "look at /srv/repo"


# ── Case 5: validation errors ────────────────────────────────────────────────


def test_missing_name_is_skipped_with_warning(isolated, caplog):
    _home_workflow(isolated["wdir"], "bad.yml", "tasks:\n  - prompt: x\n")

    with caplog.at_level(logging.WARNING, logger=logger_name):
        assert load_workflows() == []

    assert "missing required 'name'" in caplog.text


def test_empty_tasks_raises():
    wf = models.WorkflowConfig.from_dict({"name": "t"})

    with pytest.raises(ValueError, match="'tasks' must contain at least one task"):
        validate_workflow_config(wf)


def test_string_tasks_raises_not_junk():
    wf = models.WorkflowConfig.from_dict({"name": "t", "tasks": "oops"})

    with pytest.raises(ValueError, match="'tasks' must be a list"):
        validate_workflow_config(wf, {"name": "t", "tasks": "oops"})


def test_whitespace_task_prompt_raises():
    wf = models.WorkflowConfig.from_dict({"name": "t", "tasks": [{"prompt": "   "}]})

    with pytest.raises(ValueError, match="'prompt' must be a non-empty string"):
        validate_workflow_config(wf)


def test_task_missing_prompt_raises():
    with pytest.raises(ValueError, match="requires a 'prompt'"):
        models.WorkflowConfig.from_dict({"name": "t", "tasks": [{"name": "label"}]})


@pytest.mark.parametrize("bad_name", ["has:colon", "with space", ""])
def test_bad_name_raises(bad_name):
    wf = models.WorkflowConfig(name=bad_name, tasks=[models.TaskConfig(prompt="p")])

    with pytest.raises(ValueError, match="'name'"):
        validate_workflow_config(wf)


def test_duplicate_name_lower_priority_dropped_with_warning(isolated, caplog):
    _home_workflow(isolated["wdir"], "a_dup.yml", _mapping_text("dup", "from home"))
    _home_workflow(isolated["wdir"], "b_dup.yml", _mapping_text("dup", "loser"))

    with caplog.at_level(logging.WARNING, logger=logger_name):
        configs = load_workflows()

    assert [wf.name for wf in configs] == ["dup"]
    assert configs[0].tasks[0].prompt == "from home"
    loser = isolated["wdir"] / "b_dup.yml"
    assert "skipping duplicate workflow 'dup'" in caplog.text
    assert str(loser) in caplog.text


def test_duplicate_within_one_file_first_wins(isolated, caplog):
    _home_workflow(
        isolated["wdir"],
        "two.yml",
        "workflows:\n"
        "  - name: dup\n    tasks:\n      - prompt: first\n"
        "  - name: dup\n    tasks:\n      - prompt: second\n",
    )

    with caplog.at_level(logging.WARNING, logger=logger_name):
        configs = load_workflows()

    assert len(configs) == 1
    assert configs[0].tasks[0].prompt == "first"


# ── Other design §1 validation rules ────────────────────────────────────────


def test_schedule_shape_checked():
    wf = models.WorkflowConfig(name="s", tasks=[models.TaskConfig(prompt="p")])

    validate_workflow_config(replace(wf, schedule="*/30 * * * *"))
    validate_workflow_config(replace(wf, schedule="@hourly"))
    validate_workflow_config(replace(wf, schedule="@every 15m"))

    with pytest.raises(ValueError, match="not a valid cron expression"):
        validate_workflow_config(replace(wf, schedule="every tuesday"))


def test_malformed_lease_timeout_raises(isolated, caplog):
    _home_workflow(
        isolated["wdir"],
        "bad_lease.yml",
        "name: lz\nlease-timeout: abc\ntasks:\n  - prompt: x\n",
    )

    with caplog.at_level(logging.WARNING, logger=logger_name):
        assert load_workflows() == []

    assert "could not convert" in caplog.text


@pytest.mark.parametrize("bad", [0, -5])
def test_non_positive_lease_timeout_raises(bad):
    wf = models.WorkflowConfig(name="lz", tasks=[models.TaskConfig(prompt="p")], lease_timeout=bad)

    with pytest.raises(ValueError, match="'lease_timeout' must be a positive number"):
        validate_workflow_config(wf)


def test_bad_task_timeout_raises():
    wf = models.WorkflowConfig(name="tt", tasks=[models.TaskConfig(prompt="p", timeout="soon")])

    with pytest.raises(ValueError, match="'timeout' must be a positive number"):
        validate_workflow_config(wf)


def test_bad_on_failure_raises():
    wf = models.WorkflowConfig(name="of", tasks=[models.TaskConfig(prompt="p")], on_failure="retry")

    with pytest.raises(ValueError, match="'on_failure' must be one of"):
        validate_workflow_config(wf)


def test_string_skills_raises_not_letters():
    wf = models.WorkflowConfig.from_dict({"name": "sk", "skills": "gitlab", "tasks": ["p"]})

    with pytest.raises(ValueError, match="'skills' must be a list of strings"):
        validate_workflow_config(wf, {"name": "sk", "skills": "gitlab", "tasks": ["p"]})


def test_servers_lowercased_in_place():
    wf = models.WorkflowConfig(name="sv", tasks=[models.TaskConfig(prompt="p")], servers=["GitLab"])

    validate_workflow_config(wf)
    assert wf.servers == ["gitlab"]


def test_unknown_keys_warn(capsys):
    wf = models.WorkflowConfig(name="uk", tasks=[models.TaskConfig(prompt="p")])

    warnings = validate_workflow_config(
        wf, {"name": "uk", "tasks": [{"prompt": "p"}], "scheduel": "* * * * *"}
    )

    assert any("unknown key(s) ignored" in w and "scheduel" in w for w in warnings)


def test_unknown_task_key_warns():
    raw = {"name": "tk", "tasks": [{"prompt": "p", "contine-on-error": True}]}
    wf = models.WorkflowConfig.from_dict(raw)

    warnings = validate_workflow_config(wf, raw)

    assert any("unknown key(s) ignored" in w and "contine_on_error" in w for w in warnings)


def test_hooks_not_a_mapping_warns():
    raw = {"name": "hk", "hooks": ["nope"], "tasks": ["p"]}
    wf = models.WorkflowConfig.from_dict(raw)

    warnings = validate_workflow_config(wf, raw)

    assert any("'hooks' is not a mapping" in w for w in warnings)


def test_bad_timezone_warns_but_loads(isolated, caplog):
    _home_workflow(
        isolated["wdir"],
        "tz.yml",
        "name: tzy\ntimezone: Mars/Olympus\nschedule: '0 9 * * *'\ntasks:\n  - prompt: x\n",
    )

    with caplog.at_level(logging.WARNING, logger=logger_name):
        configs = load_workflows()

    assert [wf.name for wf in configs] == ["tzy"]
    assert "falls back to UTC" in caplog.text


def test_utc_timezone_never_warns(isolated, caplog, monkeypatch):
    """A host without a tz database (bare Windows) must still accept 'UTC'."""
    import zoneinfo

    def explode(key):
        raise zoneinfo.ZoneInfoNotFoundError(key)

    monkeypatch.setattr(zoneinfo, "ZoneInfo", explode)

    _home_workflow(
        isolated["wdir"],
        "tzutc.yml",
        "name: tzutc\ntimezone: UTC\nschedule: '0 9 * * *'\ntasks:\n  - prompt: x\n",
    )

    with caplog.at_level(logging.WARNING, logger=logger_name):
        configs = load_workflows()

    assert [wf.name for wf in configs] == ["tzutc"]
    assert "falls back to UTC" not in caplog.text


# ── Case 6: discovery precedence ────────────────────────────────────────────


def test_cli_string_wins_over_everything(isolated, caplog):
    _home_workflow(isolated["wdir"], "a_home.yml", _mapping_text("dup", "home"))
    (isolated["repo"] / WORKFLOW_FILENAMES[0]).write_text(
        _mapping_text("dup", "local"), encoding="utf-8"
    )
    merged = {"workflows": [{"name": "dup", "tasks": [{"prompt": "merged"}]}]}
    cli = json.dumps([{"name": "dup", "tasks": [{"prompt": "cli"}]}])

    with caplog.at_level(logging.WARNING, logger=logger_name):
        configs = load_workflows(config_arg=cli, merged_config=merged, git_root=isolated["repo"])

    assert [wf.tasks[0].prompt for wf in configs] == ["cli"]


def test_local_file_wins_over_merged_config(isolated):
    (isolated["repo"] / WORKFLOW_FILENAMES[1]).write_text(
        _mapping_text("dup", "local"), encoding="utf-8"
    )
    merged = {"workflows": [{"name": "dup", "tasks": [{"prompt": "merged"}]}]}

    configs = load_workflows(merged_config=merged, git_root=isolated["repo"])

    assert [wf.tasks[0].prompt for wf in configs] == ["local"]


def test_merged_config_wins_over_home_files(isolated):
    _home_workflow(isolated["wdir"], "a_home.yml", _mapping_text("dup", "home"))
    merged = {"workflows": [{"name": "dup", "tasks": [{"prompt": "merged"}]}]}

    configs = load_workflows(merged_config=merged)

    assert [wf.tasks[0].prompt for wf in configs] == ["merged"]


def test_config_arg_may_be_a_file_path(isolated, tmp_path):
    arg_file = tmp_path / "arg.yml"
    arg_file.write_text(_mapping_text("from-path", "cli file"), encoding="utf-8")

    configs = load_workflows(config_arg=str(arg_file))

    assert configs[0].source_path == str(arg_file)


@pytest.mark.parametrize("absent", [None, "", "   ", "{}", "[]", "null"])
def test_absent_config_arg_falls_through(isolated, absent):
    _home_workflow(isolated["wdir"], "a_home.yml", _mapping_text("homey", "home"))

    configs = load_workflows(config_arg=absent)

    assert [wf.name for wf in configs] == ["homey"]


def test_config_arg_yaml_string(isolated):
    configs = load_workflows(config_arg="name: inline-yaml\ntasks:\n  - prompt: hi\n")

    assert [wf.name for wf in configs] == ["inline-yaml"]


def test_bare_list_config_arg_supported(isolated):
    configs = load_workflows(config_arg=json.dumps([{"name": "one", "tasks": [{"prompt": "a"}]}]))

    assert [wf.name for wf in configs] == ["one"]


def test_conflicting_sources_merge_by_name(isolated):
    _home_workflow(isolated["wdir"], "a_home.yml", _mapping_text("home-only", "home"))
    cli = json.dumps([{"name": "cli-only", "tasks": [{"prompt": "cli"}]}])

    configs = load_workflows(config_arg=cli)

    assert sorted(wf.name for wf in configs) == ["cli-only", "home-only"]


def test_non_mapping_entry_skipped_with_warning(isolated, caplog):
    _home_workflow(
        isolated["wdir"],
        "junk.yml",
        "workflows:\n  - just a string\n  - name: ok\n    tasks:\n      - prompt: x\n",
    )

    with caplog.at_level(logging.WARNING, logger=logger_name):
        configs = load_workflows()

    assert [wf.name for wf in configs] == ["ok"]
    assert "non-mapping workflow entry" in caplog.text


# ── Case 7: a bad YAML file must not sink the others ────────────────────────


def test_bad_yaml_file_skipped_others_load(isolated, caplog):
    _home_workflow(isolated["wdir"], "a_broken.yml", "name: broken\ntasks: [ {oops\n")
    _home_workflow(isolated["wdir"], "b_good.yml", _mapping_text("good", "x"))

    with caplog.at_level(logging.WARNING, logger=logger_name):
        configs = load_workflows()

    assert [wf.name for wf in configs] == ["good"]
    assert "skipping unreadable workflows file" in caplog.text
    assert "a_broken.yml" in caplog.text


def test_bad_local_file_does_not_block_home_files(isolated, caplog):
    (isolated["repo"] / WORKFLOW_FILENAMES[0]).write_text("}}[bad yaml", encoding="utf-8")
    _home_workflow(isolated["wdir"], "a_home.yml", _mapping_text("homey", "home"))

    with caplog.at_level(logging.WARNING, logger=logger_name):
        configs = load_workflows(git_root=isolated["repo"])

    assert [wf.name for wf in configs] == ["homey"]


# ── Case 8: definition_hash stability ───────────────────────────────────────


def test_local_dir_files_are_loaded(isolated):
    _local_dir_workflow(isolated["repo"], "pipelines.yml", _mapping_text("local-dir", "check"))

    configs = load_workflows(git_root=isolated["repo"])

    assert [wf.name for wf in configs] == ["local-dir"]
    assert configs[0].source_path == str(
        isolated["repo"] / ".cecli" / "workflows" / "pipelines.yml"
    )


def test_local_dir_globs_stably_sorted(isolated):
    _local_dir_workflow(isolated["repo"], "b_second.yml", _mapping_text("b", "second"))
    _local_dir_workflow(isolated["repo"], "a_first.yml", _mapping_text("a", "first"))

    configs = load_workflows(git_root=isolated["repo"])

    assert [wf.name for wf in configs] == ["a", "b"]


def test_local_dir_defaults_to_cwd(isolated):
    _local_dir_workflow(isolated["repo"], "here.yml", _mapping_text("here", "cwd"))

    configs = load_workflows()

    assert [wf.name for wf in configs] == ["here"]


def test_local_file_wins_over_local_dir(isolated):
    _local_dir_workflow(isolated["repo"], "dir.yml", _mapping_text("dup", "dir"))
    (isolated["repo"] / WORKFLOW_FILENAMES[0]).write_text(
        _mapping_text("dup", "local-file"), encoding="utf-8"
    )

    configs = load_workflows(git_root=isolated["repo"])

    assert [wf.tasks[0].prompt for wf in configs] == ["local-file"]


def test_local_dir_wins_over_merged_config_and_home(isolated):
    _local_dir_workflow(isolated["repo"], "dir.yml", _mapping_text("dup", "dir"))
    _home_workflow(isolated["wdir"], "a_home.yml", _mapping_text("dup", "home"))
    merged = {"workflows": [{"name": "dup", "tasks": [{"prompt": "merged"}]}]}

    configs = load_workflows(merged_config=merged, git_root=isolated["repo"])

    assert [wf.tasks[0].prompt for wf in configs] == ["dir"]


def test_agents_dir_files_are_loaded(isolated):
    _agents_dir_workflow(isolated["repo"], "pipelines.yml", _mapping_text("agents-dir", "check"))

    configs = load_workflows(git_root=isolated["repo"])

    assert [wf.name for wf in configs] == ["agents-dir"]
    assert configs[0].source_path == str(
        isolated["repo"] / ".agents" / "workflows" / "pipelines.yml"
    )


def test_cecli_dir_wins_over_agents_dir(isolated):
    _agents_dir_workflow(isolated["repo"], "dup.yml", _mapping_text("dup", "agents"))
    _local_dir_workflow(isolated["repo"], "dup.yml", _mapping_text("dup", "cecli"))

    configs = load_workflows(git_root=isolated["repo"])

    assert [wf.tasks[0].prompt for wf in configs] == ["cecli"]


def test_agents_dir_wins_over_merged_config_and_home(isolated):
    _agents_dir_workflow(isolated["repo"], "dir.yml", _mapping_text("dup", "agents"))
    _home_workflow(isolated["wdir"], "a_home.yml", _mapping_text("dup", "home"))
    merged = {"workflows": [{"name": "dup", "tasks": [{"prompt": "merged"}]}]}

    configs = load_workflows(merged_config=merged, git_root=isolated["repo"])

    assert [wf.tasks[0].prompt for wf in configs] == ["agents"]


def test_definition_hash_stable_across_key_order():
    one = models.WorkflowConfig.from_dict(
        {"name": "h", "tasks": [{"prompt": "a", "name": "t1"}], "enabled": True}
    )
    two = models.WorkflowConfig.from_dict(
        {"tasks": [{"name": "t1", "prompt": "a"}], "enabled": True, "name": "h"}
    )

    assert one.definition_hash() == two.definition_hash()


def test_definition_hash_changes_when_prompt_changes():
    one = models.WorkflowConfig.from_dict({"name": "h", "tasks": [{"prompt": "a"}]})
    two = models.WorkflowConfig.from_dict({"name": "h", "tasks": [{"prompt": "b"}]})

    assert one.definition_hash() != two.definition_hash()


def test_definition_hash_ignores_source_path(isolated):
    _home_workflow(isolated["wdir"], "a_one.yml", _mapping_text("same", "p"))
    first = load_workflows()[0]

    other = models.WorkflowConfig.from_dict(
        {"name": "same", "tasks": [{"prompt": "p"}]}, "/elsewhere/two.yml"
    )

    assert first.definition_hash() == other.definition_hash()


# ── resolve_workflow_configs (raw discovery) ────────────────────────────────


def test_resolve_returns_raw_precedence_order(isolated):
    _home_workflow(isolated["wdir"], "a_home.yml", _mapping_text("homey", "home"))

    entries = resolve_workflow_configs(
        config_arg=json.dumps([{"name": "cli", "tasks": ["a"]}]),
        merged_config={"workflows": [{"name": "conf", "tasks": ["b"]}]},
    )

    assert [entry[0]["name"] for entry in entries] == ["cli", "conf", "homey"]
    assert entries[0][1] is None
    assert entries[0][2] == "inline --workflows value"
    assert entries[2][1] == str(isolated["wdir"] / "a_home.yml")
