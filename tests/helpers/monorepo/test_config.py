import pytest

from cecli.helpers.monorepo.config import validate_config


def test_validate_config_empty():
    # Should not raise
    validate_config({})


def test_validate_config_no_name():
    with pytest.raises(ValueError, match="Workspace configuration must include a 'name'"):
        validate_config({"projects": []})


def test_validate_config_invalid_project():
    with pytest.raises(ValueError, match="Each project must have a 'name' and 'repo' URL"):
        validate_config({"name": "test", "projects": [{"name": "p1"}]})


def test_validate_config_duplicate_project():
    with pytest.raises(ValueError, match="Duplicate project name: p1"):
        validate_config(
            {
                "name": "test",
                "projects": [{"name": "p1", "repo": "url1"}, {"name": "p1", "repo": "url2"}],
            }
        )


def test_validate_config_valid():
    config = {"name": "test", "projects": [{"name": "p1", "repo": "url1"}]}
    validate_config(config)
    assert config["projects"][0]["name"] == "p1"


def test_load_workspace_config_json_string():
    from cecli.helpers.monorepo.config import load_workspace_config

    config_str = '{"name": "json-ws", "projects": []}'
    config = load_workspace_config(config_str)
    assert config["name"] == "json-ws"


def test_load_workspace_config_yaml_string():
    from cecli.helpers.monorepo.config import load_workspace_config

    config_str = "name: yaml-ws\nprojects: []"
    config = load_workspace_config(config_str)
    assert config["name"] == "yaml-ws"
