import json

import pytest
import yaml

from cecli.helpers.workspaces.config import (
    find_active_workspace_name,
    load_workspace_config,
    validate_config,
    workspace_layout,
)


def test_validate_config_empty():
    validate_config({})


def test_validate_config_no_name():
    with pytest.raises(ValueError, match="must include a 'name'"):
        validate_config({"projects": []})


def test_validate_config_project_missing_source():
    with pytest.raises(ValueError, match="exactly one of 'path' or 'repo'"):
        validate_config({"name": "test", "projects": [{"name": "p1"}]})


def test_validate_config_project_both_sources():
    with pytest.raises(ValueError, match="exactly one of 'path' or 'repo'"):
        validate_config(
            {
                "name": "test",
                "projects": [{"name": "p1", "path": "/a", "repo": "https://github.com/o/r.git"}],
            }
        )


def test_validate_config_path_project():
    validate_config(
        {"name": "local", "projects": [{"name": "app", "path": "/abs/app", "primary": True}]}
    )


def test_validate_config_repo_project():
    validate_config(
        {"name": "clone", "projects": [{"name": "app", "repo": "https://github.com/o/r.git"}]}
    )


def test_validate_config_duplicate_project():
    with pytest.raises(ValueError, match="Duplicate project name: p1"):
        validate_config(
            {
                "name": "test",
                "projects": [{"name": "p1", "path": "/a"}, {"name": "p1", "path": "/b"}],
            }
        )


def test_validate_config_multiple_primary():
    with pytest.raises(ValueError, match="Only one project may be marked primary"):
        validate_config(
            {
                "name": "test",
                "projects": [
                    {"name": "a", "path": "/a", "primary": True},
                    {"name": "b", "path": "/b", "primary": True},
                ],
            }
        )


def test_workspace_layout_local():
    config = {"name": "local", "projects": [{"name": "app", "path": "/a"}]}
    assert workspace_layout(config) == "local"


def test_workspace_layout_clone():
    config = {"name": "clone", "projects": [{"name": "app", "repo": "https://github.com/o/r.git"}]}
    assert workspace_layout(config) == "clone"


def test_workspace_layout_explicit_field_overrides_inference():
    config = {"name": "ws", "layout": "clone", "projects": [{"name": "app", "path": "/a"}]}
    assert workspace_layout(config) == "clone"


def test_load_workspace_config_json_string():
    config = load_workspace_config(json.dumps({"name": "json-ws", "projects": []}))
    assert config["name"] == "json-ws"


def test_load_workspace_config_yaml_string():
    config = load_workspace_config("name: yaml-ws\nprojects: []")
    assert config["name"] == "yaml-ws"


def test_load_workspace_config_select_by_name():
    config_list = [{"name": "ws1", "active": True, "projects": []}, {"name": "ws2", "projects": []}]
    config = load_workspace_config(yaml.dump({"workspaces": config_list}), name="ws2")
    assert config["name"] == "ws2"


def test_load_workspace_config_multiple_active_error():
    config_list = [
        {"name": "ws1", "active": True, "projects": []},
        {"name": "ws2", "active": True, "projects": []},
    ]
    with pytest.raises(ValueError, match="Multiple workspaces marked as active"):
        load_workspace_config(yaml.dump({"workspaces": config_list}))


def test_find_active_workspace_name():
    config_list = [{"name": "ws1", "active": True, "projects": []}, {"name": "ws2", "projects": []}]
    assert find_active_workspace_name(yaml.dump({"workspaces": config_list})) == "ws1"
