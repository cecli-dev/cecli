import json
import os
import unittest

import yaml

from cecli.helpers.nested import (  # noqa: E402
    deep_merge_config_dicts,
)


class TestConfigLoading(unittest.TestCase):

    def setUp(self):
        # Create mock config files
        self.conf_dir = "temp_test_conf"
        os.makedirs(self.conf_dir, exist_ok=True)

        self.git_root_conf_path = os.path.join(self.conf_dir, ".cecli.conf.yml")
        self.user_conf_dir = os.path.join(self.conf_dir, "user")
        os.makedirs(self.user_conf_dir, exist_ok=True)
        self.user_conf_path = os.path.join(self.user_conf_dir, ".cecli.conf.yml")
        self.legacy_conf_path = os.path.join(self.conf_dir, ".cecli", "conf.yml")
        os.makedirs(os.path.dirname(self.legacy_conf_path), exist_ok=True)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.conf_dir)

    def test_multiple_config_files_deep_merge(self):
        # 1. Create mock config files with content
        legacy_content = {"skills_paths": ["/legacy/skills"], "model": "gpt-3.5"}
        user_content = {"skills_paths": ["/user/skills"], "model": "gpt-4", "temperature": 0.5}
        git_root_content = {"skills_paths": ["./project/skills"], "temperature": 0.7}

        with open(self.legacy_conf_path, "w") as f:
            yaml.dump(legacy_content, f)
        with open(self.user_conf_path, "w") as f:
            yaml.dump(user_content, f)
        with open(self.git_root_conf_path, "w") as f:
            yaml.dump(git_root_content, f)

        # 2. Simulate the loading and merging process from main.py.
        # The fix reads ALL config files (both .cecli/conf.yml and
        # .cecli.conf.yml) from disk and deep-merges them together,
        # replacing configargparse's shallow-merged result for array fields.

        all_config_dicts = [
            legacy_content,
            user_content,
            git_root_content,
        ]
        merged_config = deep_merge_config_dicts(all_config_dicts)

        # Non-array fields: last file wins (deep_merge overwrites scalars)
        # Array fields: concatenated with dedup across ALL config files
        final_config = merged_config

        # 3. Assert the final merged config is correct
        # skills_paths: all three sources concatenated (deep merge)
        # model: last .cecli.conf.yml wins (scalar overwrite)
        # temperature: last .cecli.conf.yml wins (scalar overwrite)
        expected = {
            "skills_paths": ["/legacy/skills", "/user/skills", "./project/skills"],
            "model": "gpt-4",
            "temperature": 0.7,
        }
        self.assertEqual(final_config["skills_paths"], expected["skills_paths"])
        self.assertEqual(final_config["model"], expected["model"])
        self.assertEqual(final_config["temperature"], expected["temperature"])

    def test_config_precedence_order(self):
        # Files are loaded in order, later files override earlier ones
        # .cecli/conf.yml (shallow) < .cecli.conf.yml (deep) < git_root/.cecli.conf.yml (deep)

        # Create files
        with open(self.legacy_conf_path, "w") as f:
            yaml.dump({"a": 1, "b": [10]}, f)
        with open(self.user_conf_path, "w") as f:
            yaml.dump({"a": 2, "b": [20]}, f)
        with open(self.git_root_conf_path, "w") as f:
            yaml.dump({"a": 3, "b": [30]}, f)

        # Simulate loading
        # Configargparse shallow merges all first. The last value for 'a' and 'b' wins.
        # Our manual deep merge will then be applied.

        # 1. Base from shallow file
        base_config = yaml.safe_load(open(self.legacy_conf_path))

        # 2. Deep merge the others

        # Manually simulate the process
        # Start with shallow merge result
        temp_merged = {}
        temp_merged.update(base_config)
        temp_merged.update(yaml.safe_load(open(self.user_conf_path)))
        temp_merged.update(yaml.safe_load(open(self.git_root_conf_path)))

        # Now, apply our deep merge logic for array fields
        final_config = deep_merge_config_dicts(
            [
                base_config,
                yaml.safe_load(open(self.user_conf_path)),
                yaml.safe_load(open(self.git_root_conf_path)),
            ]
        )

        # 'a' is a scalar, so last one wins
        self.assertEqual(final_config["a"], 3)
        # 'b' is an array, should be deep merged
        self.assertEqual(final_config["b"], [10, 20, 30])

    def test_agent_config_json_parsing(self):
        # This tests that a JSON string field like 'agent_config' is correctly merged
        conf1 = {"agent_config": {"skills_paths": ["/path1"], "tools_includelist": ["tool-a"]}}
        conf2 = {
            "agent_config": {"skills_paths": ["/path2"], "tools_includelist": ["tool-b", "tool-a"]}
        }

        # Simulate loading from two .cecli.conf.yml files
        merged = deep_merge_config_dicts([conf1, conf2])

        # The result is a Python dict. In main.py, this would be re-serialized to JSON.
        expected_agent_config = {
            "skills_paths": ["/path1", "/path2"],
            "tools_includelist": ["tool-a", "tool-b"],
        }

        self.assertEqual(merged["agent_config"], expected_agent_config)

        # Test the re-serialization step
        final_json_string = json.dumps(merged["agent_config"])
        parsed_final = json.loads(final_json_string)

        # Sort lists for comparison since order inside JSON can be tricky
        self.assertEqual(
            sorted(parsed_final["skills_paths"]), sorted(expected_agent_config["skills_paths"])
        )
        self.assertEqual(
            sorted(parsed_final["tools_includelist"]),
            sorted(expected_agent_config["tools_includelist"]),
        )


if __name__ == "__main__":
    unittest.main()
