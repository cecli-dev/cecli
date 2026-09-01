import unittest

from cecli.helpers.nested import deep_merge


class TestShallowMerge(unittest.TestCase):
    def test_shallow_merge_replaces_arrays(self):
        dict1 = {"skills_paths": ["./old-skills"]}
        dict2 = {"skills_paths": ["./new-skills"]}
        expected = {"skills_paths": ["./new-skills"]}
        merged = deep_merge(dict1, dict2, deep_merge_arrays=False)
        self.assertEqual(merged, expected)


if __name__ == "__main__":
    unittest.main()
