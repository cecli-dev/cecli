import unittest

import yaml

from cecli.helpers.nested import deep_merge


class TestEdgeCases(unittest.TestCase):
    def test_empty_arrays(self):
        dict1 = {"skills_paths": []}
        dict2 = {"skills_paths": ["./project-skills"]}
        expected = {"skills_paths": ["./project-skills"]}
        merged = deep_merge(dict1, dict2, deep_merge_arrays=True)
        self.assertEqual(merged, expected)

    def test_null_and_missing_values(self):
        # When deep_merge_arrays=True, a None value in dict2 means "not set"
        # and should preserve dict1's value rather than overwriting with None.
        dict1 = {"skills_paths": ["./project-skills"]}
        dict2 = {"skills_paths": None}
        expected = {"skills_paths": ["./project-skills"]}
        merged = deep_merge(dict1, dict2, deep_merge_arrays=True)
        self.assertEqual(merged, expected)

        # When deep_merge_arrays=False, None should still overwrite (shallow behavior).
        dict1 = {"skills_paths": ["./project-skills"]}
        dict2 = {"skills_paths": None}
        expected_shallow = {"skills_paths": None}
        merged_shallow = deep_merge(dict1, dict2, deep_merge_arrays=False)
        self.assertEqual(merged_shallow, expected_shallow)

        # Missing key in dict2 should preserve dict1's value.
        dict1 = {"skills_paths": ["./project-skills"]}
        dict2 = {}
        expected = {"skills_paths": ["./project-skills"]}
        merged = deep_merge(dict1, dict2, deep_merge_arrays=True)
        self.assertEqual(merged, expected)

    def test_non_array_fields_unchanged(self):
        dict1 = {"model": "gpt-4", "temperature": 0.5}
        dict2 = {"model": "claude-2", "dark_mode": True}
        expected = {"model": "claude-2", "temperature": 0.5, "dark_mode": True}
        merged = deep_merge(dict1, dict2, deep_merge_arrays=True)
        self.assertEqual(merged, expected)

    def test_malformed_yaml(self):
        """Verify graceful error handling with invalid YAML syntax."""
        malformed_yaml = "skills_paths: [unclosed quote\n"
        with self.assertRaises(yaml.YAMLError):
            yaml.safe_load(malformed_yaml)

        # Verify the try-except pattern works without crashing
        try:
            yaml.safe_load(malformed_yaml)
        except yaml.YAMLError:
            pass  # Expected — graceful handling confirmed


if __name__ == "__main__":
    unittest.main()
