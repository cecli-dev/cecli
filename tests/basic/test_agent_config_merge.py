import json

import pytest

from cecli.args import get_parser
from cecli.main import convert_yaml_to_json_string, merge_cli_agent_config


@pytest.fixture
def parser_factory(tmp_path):
    """Build a parser whose default config file contains the given YAML."""

    def _factory(conf_text):
        conf = tmp_path / ".cecli.conf.yml"
        conf.write_text(conf_text)
        return get_parser([str(conf)], None)

    return _factory


def _finalize(parser, argv):
    """Replicate main_async argument post-processing (parse -> convert -> merge)."""
    args, _ = parser.parse_known_args(argv)
    if hasattr(args, "agent_config") and args.agent_config is not None:
        args.agent_config = convert_yaml_to_json_string(args.agent_config)
        merge_cli_agent_config(args, parser, argv)
    return args


def test_cli_agent_config_merges_with_config_file(parser_factory):
    """CLI --agent-config must deep-merge with the config-file agent-config
    instead of replacing it wholesale (regression: file-only keys dropped)."""
    parser = parser_factory(
        """
agent-config:
  command_timeout: 0
  skip_cli_confirmations: true
  tools_paths:
    - /tmp/mytools
  skills_paths:
    - /tmp/skills
"""
    )
    cli = json.dumps({"command_timeout": 120})
    args = _finalize(parser, [f"--agent-config={cli}"])

    merged = json.loads(args.agent_config)
    assert merged["command_timeout"] == 120  # CLI wins per-key
    assert merged["skip_cli_confirmations"] is True  # file-only key preserved
    assert merged["tools_paths"] == ["/tmp/mytools"]  # file-only key preserved
    assert merged["skills_paths"] == ["/tmp/skills"]  # file-only key preserved


def test_cli_agent_config_separate_flag_value(parser_factory):
    """--agent-config passed as two tokens (flag + value) also merges."""
    parser = parser_factory(
        "agent-config:\n  command_timeout: 0\n  skills_paths: [/tmp/skills]\n"
    )
    args = _finalize(parser, ["--agent-config", '{"skip_cli_confirmations": true}'])

    merged = json.loads(args.agent_config)
    assert merged["skip_cli_confirmations"] is True
    assert merged["command_timeout"] == 0
    assert merged["skills_paths"] == ["/tmp/skills"]


def test_agent_config_from_file_unchanged_without_cli(parser_factory):
    """Without a CLI --agent-config the merge must be a no-op."""
    parser = parser_factory(
        "agent-config:\n  command_timeout: 0\n  tools_paths: [/tmp/t]\n"
    )
    args = _finalize(parser, [])

    merged = json.loads(args.agent_config)
    assert merged["command_timeout"] == 0
    assert merged["tools_paths"] == ["/tmp/t"]


def test_nested_dict_keys_deep_merged(parser_factory):
    """Nested dicts under agent-config are merged recursively, CLI wins."""
    parser = parser_factory("agent-config:\n  nested:\n    a: 1\n    b: 2\n")
    args = _finalize(parser, ["--agent-config", '{"nested": {"b": 9, "c": 3}}'])

    merged = json.loads(args.agent_config)
    assert merged["nested"] == {"a": 1, "b": 9, "c": 3}


def test_cli_wins_over_env_var_per_key(parser_factory, monkeypatch):
    """CLI --agent-config merges with the CECLI_AGENT_CONFIG env var, CLI wins."""
    parser = parser_factory("agent-config:\n  command_timeout: 5\n")
    monkeypatch.setenv("CECLI_AGENT_CONFIG", '{"command_timeout": 0, "tools_paths": ["/tmp/env"]}')
    args = _finalize(parser, ["--agent-config", '{"skip_cli_confirmations": true}'])

    merged = json.loads(args.agent_config)
    assert merged["skip_cli_confirmations"] is True  # CLI-only key
    assert merged["tools_paths"] == ["/tmp/env"]  # env-only key preserved
    assert merged["command_timeout"] == 0  # env beats file (CLI > env > file), CLI absent for this key
