import pytest

from cecli.helpers.monorepo.config import load_workspace_config


def test_load_workspace_config_multiple_active_error():
    config_list = [
        {"name": "ws1", "active": True, "projects": []},
        {"name": "ws2", "active": True, "projects": []},
    ]

    # Mocking what would be in the config file/arg
    with pytest.raises(ValueError, match="Multiple workspaces marked as active: ws1, ws2"):
        # We simulate the loaded config being a list
        from unittest.mock import mock_open, patch

        import yaml

        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=yaml.dump({"workspace": config_list}))):
                load_workspace_config()


def test_load_workspace_config_select_by_name():
    config_list = [
        {"name": "ws1", "active": True, "projects": []},
        {"name": "ws2", "active": False, "projects": []},
    ]

    from unittest.mock import mock_open, patch

    import yaml

    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=yaml.dump({"workspace": config_list}))):
            # Should select ws2 even if ws1 is active
            config = load_workspace_config(name="ws2")
            assert config["name"] == "ws2"


def test_load_workspace_config_no_active_uses_first_if_only_one():
    config_list = [{"name": "ws1", "projects": []}]

    from unittest.mock import mock_open, patch

    import yaml

    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=yaml.dump({"workspace": config_list}))):
            config = load_workspace_config()
            assert config["name"] == "ws1"


def test_load_workspace_config_single_dict_is_active_by_default():
    config_dict = {"name": "single-ws", "projects": []}

    from unittest.mock import mock_open, patch

    import yaml

    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=yaml.dump({"workspace": config_dict}))):
            # Should work even if no name is passed and active is not set
            config = load_workspace_config()
            assert config["name"] == "single-ws"


def test_load_workspace_config_multiple_in_list_none_active_picks_none():
    config_list = [{"name": "ws1", "projects": []}, {"name": "ws2", "projects": []}]

    from unittest.mock import mock_open, patch

    import yaml

    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=yaml.dump({"workspace": config_list}))):
            # With multiple and none active, it should return empty if no name provided
            config = load_workspace_config()
            assert config == {}
