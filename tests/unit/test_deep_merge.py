import json
import unittest

from cecli.helpers.nested import (
    _deduplicate_list,
    deep_merge,
    deep_merge_config_dicts,
    is_cecli_conf_file,
)


class TestDeepMergeArrays(unittest.TestCase):
    def test_deep_merge_simple_arrays(self):
        dict1 = {
            "skills_paths": [".cecli/skills"],
            "subagent_paths": [".cecli/subagents"],
            "tools_paths": [".cecli/tools"],
            "allowed_commands": ["git", "npm"],
        }
        dict2 = {
            "skills_paths": ["./project-skills"],
            "subagent_paths": ["./custom-subagents"],
            "tools_paths": ["./project-tools"],
            "allowed_commands": ["docker", "git"],
        }
        expected = {
            "skills_paths": [".cecli/skills", "./project-skills"],
            "subagent_paths": [".cecli/subagents", "./custom-subagents"],
            "tools_paths": [".cecli/tools", "./project-tools"],
            "allowed_commands": ["git", "npm", "docker"],
        }
        merged = deep_merge(dict1, dict2, deep_merge_arrays=True)
        self.assertEqual(merged, expected)

    def test_deep_merge_with_duplicates(self):
        dict1 = {"skills_includelist": ["skill-a", "skill-b"]}
        dict2 = {"skills_includelist": ["skill-b", "skill-c"]}
        expected = {"skills_includelist": ["skill-a", "skill-b", "skill-c"]}
        merged = deep_merge(dict1, dict2, deep_merge_arrays=True)
        self.assertEqual(merged, expected)

    def test_deep_merge_order_preservation(self):
        dict1 = {"tools_includelist": ["tool-a", "tool-b"]}
        dict2 = {"tools_includelist": ["tool-c", "tool-d"]}
        expected = {"tools_includelist": ["tool-a", "tool-b", "tool-c", "tool-d"]}
        merged = deep_merge(dict1, dict2, deep_merge_arrays=True)
        self.assertEqual(merged, expected)

    def test_deep_merge_nested_arrays(self):
        dict1 = {"mcp_servers": [{"server-a": {"command": ["cmd1"]}}]}
        dict2 = {"mcp_servers": [{"server-b": {"command": ["cmd2"]}}]}
        expected = {
            "mcp_servers": [
                {"server-a": {"command": ["cmd1"]}},
                {"server-b": {"command": ["cmd2"]}},
            ]
        }
        merged = deep_merge(dict1, dict2, deep_merge_arrays=True)
        self.assertEqual(merged, expected)

    def test_json_field_serialization(self):
        dict1 = {"mcp_servers": {"server-a": {"command": ["cmd1"]}}}
        dict2 = {"mcp_servers": {"server-b": {"command": ["cmd2"]}}}
        merged = deep_merge(dict1, dict2, deep_merge_arrays=True)
        try:
            json.dumps(merged)
        except TypeError:
            self.fail("deep_merge result is not JSON serializable")

    def test_json_field_deep_merge(self):
        dict1 = {"mcp_servers": {"server-a": {"command": ["cmd1"]}}}
        dict2 = {"mcp_servers": {"server-b": {"command": ["cmd2"]}}}
        expected = {
            "mcp_servers": {"server-a": {"command": ["cmd1"]}, "server-b": {"command": ["cmd2"]}}
        }
        merged = deep_merge(dict1, dict2, deep_merge_arrays=True)
        self.assertEqual(merged, expected)


class TestConfigHelpers(unittest.TestCase):
    def test_is_cecli_conf_file(self):
        self.assertTrue(is_cecli_conf_file("/path/to/.cecli.conf.yml"))
        self.assertFalse(is_cecli_conf_file("/path/to/.cecli/conf.yml"))
        self.assertFalse(is_cecli_conf_file("conf.yml"))

    def test_deep_merge_config_dicts(self):
        config1 = {"a": [1], "b": 2}
        config2 = {"a": [3], "c": 4}
        config3 = {"a": [1, 5], "b": 6}
        configs = [config1, config2, config3]
        expected = {"a": [1, 3, 5], "b": 6, "c": 4}
        merged = deep_merge_config_dicts(configs)
        self.assertEqual(merged, expected)

    def test_deduplicate_list(self):
        list1 = [1, 2, {"a": 1}]
        list2 = [2, 3, {"a": 1}, {"b": 2}]
        expected = [1, 2, {"a": 1}, 3, {"b": 2}]
        result = _deduplicate_list(list1, list2)
        self.assertEqual(result, expected)
