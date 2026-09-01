import json
import os
import tempfile

import yaml

from cecli.args import get_parser
from cecli.helpers import config_utils
from cecli.main import YAML_TO_JSON_ARG_KEYS, convert_yaml_to_json_string


def test_cli_agent_config_merges_with_config_file():
    """CLI --agent-config must deep-merge with the config-file agent-config
    instead of replacing it wholesale (regression: file-only keys dropped)."""
    file_ac = {
        "command_timeout": 0,
        "skip_cli_confirmations": True,
        "tools_paths": ["/tmp/mytools"],
        "skills_paths": ["/tmp/skills"],
    }
    cli = json.dumps({"command_timeout": 120})
    merged = json.loads(convert_yaml_to_json_string(cli, file_ac))
    assert merged["command_timeout"] == 120  # CLI wins per-key
    assert merged["skip_cli_confirmations"] is True  # file-only key preserved
    assert merged["tools_paths"] == ["/tmp/mytools"]  # file-only key preserved
    assert merged["skills_paths"] == ["/tmp/skills"]  # file-only key preserved


def test_file_agent_config_given_as_json_string():
    """Merged config from read_and_merge_all_configs holds agent-config as a
    JSON string (YAML block scalar) - the helper must handle that form."""
    file_ac = '{"command_timeout": 0, "skills_paths": ["/tmp/skills"]}'
    merged = json.loads(convert_yaml_to_json_string('{"skip_cli_confirmations": true}', file_ac))
    assert merged["skip_cli_confirmations"] is True
    assert merged["command_timeout"] == 0
    assert merged["skills_paths"] == ["/tmp/skills"]


def test_no_file_agent_config_returns_cli_unchanged():
    """Without a config-file agent-config the merge must be a no-op."""
    cli = '{"command_timeout": 120}'
    assert convert_yaml_to_json_string(cli, None) == cli
    assert convert_yaml_to_json_string(cli, {}) == cli
    assert convert_yaml_to_json_string(cli, "not json") == cli


def test_nested_dict_keys_deep_merged():
    """Nested dicts under agent-config are merged recursively, CLI wins."""
    file_ac = {"nested": {"a": 1, "b": 2}}
    merged = json.loads(convert_yaml_to_json_string('{"nested": {"b": 9, "c": 3}}', file_ac))
    assert merged["nested"] == {"a": 1, "b": 9, "c": 3}


def test_cli_array_replaces_file_array():
    """Arrays are not deep-merged: CLI list values win wholesale."""
    file_ac = {"skills_paths": ["/tmp/file-skills"]}
    merged = json.loads(
        convert_yaml_to_json_string('{"skills_paths": ["/tmp/cli-skills"]}', file_ac)
    )
    assert merged["skills_paths"] == ["/tmp/cli-skills"]


def test_main_async_pipeline_preserves_file_keys(tmp_path):
    """Replicates main_async: merge config files -> temp yaml -> parser ->
    CLI parse -> temp file deleted -> convert + merge against merged_config.

    Guards against regressing to the broken baseline (re-parsing argv after
    the temp config file was already unlinked yields no config-file values).
    """
    conf = tmp_path / ".cecli.conf.yml"
    conf.write_text(
        "agent-config: |\n"
        '  {"skills_paths": ["./.cecli/skills"], "skills_init": ["android-cli"]}\n'
    )
    paths = [str(conf)]
    merged_config = config_utils.read_and_merge_all_configs(paths, [], paths)

    fd, tmp = tempfile.mkstemp(suffix=".yml", prefix="cecli_merged_")
    os.close(fd)
    with open(tmp, "w") as f:
        yaml.dump(merged_config, f)
    try:
        parser = get_parser([tmp], None)
        argv = ['--agent-config={"command_timeout": 0}']
        args, _ = parser.parse_known_args(argv)
    finally:
        os.unlink(tmp)  # main_async deletes the temp file before the merge point

    config_key = YAML_TO_JSON_ARG_KEYS["agent_config"]
    file_ac = merged_config.get(config_key)
    args.agent_config = convert_yaml_to_json_string(args.agent_config, file_ac)

    merged = json.loads(args.agent_config)
    assert merged["command_timeout"] == 0
    assert merged["skills_paths"] == ["./.cecli/skills"]
    assert merged["skills_init"] == ["android-cli"]


def test_all_yaml_to_json_args_deep_merge_with_config_file():
    """Every yaml-to-json arg converted in main_async deep-merges with the
    value for its hyphenated config-file key (CLI wins per-key, file-only
    keys preserved, no underscore-key variants)."""
    assert set(YAML_TO_JSON_ARG_KEYS) == {
        "agent_config",
        "tui_config",
        "mcp_servers",
        "custom",
        "security_config",
        "retries",
        "hooks",
        "workspaces",
        "model_providers",
        "server_config",
    }
    assert all("_" not in key for key in YAML_TO_JSON_ARG_KEYS.values())

    file_value = {
        "command_timeout": 0,
        "skills_paths": ["/tmp/skills"],
        "nested": {"a": 1, "b": 2},
    }
    cli_value = {"command_timeout": 120, "nested": {"b": 9}}

    for arg_name, config_key in YAML_TO_JSON_ARG_KEYS.items():
        merged_config = {config_key: file_value}
        merged_arg = convert_yaml_to_json_string(
            json.dumps(cli_value), merged_config.get(config_key)
        )

        merged = json.loads(merged_arg)
        assert merged["command_timeout"] == 120  # CLI wins per-key
        assert merged["skills_paths"] == ["/tmp/skills"]  # file-only key preserved
        assert merged["nested"] == {"a": 1, "b": 9}  # nested deep-merged
