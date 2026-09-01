import time
import unittest

from cecli.helpers.nested import deep_merge


class TestPerformance(unittest.TestCase):
    def test_large_arrays_performance(self):
        dict1 = {"large_array": list(range(1000))}
        dict2 = {"large_array": list(range(1000, 2000))}
        start_time = time.time()
        deep_merge(dict1, dict2, deep_merge_arrays=True)
        end_time = time.time()
        self.assertLess(end_time - start_time, 0.1)

    def test_deep_copy_behavior(self):
        dict1 = {"a": [1], "b": {"c": [2]}}
        dict2 = {"a": [3], "b": {"c": [4]}}
        merged = deep_merge(dict1, dict2, deep_merge_arrays=True)
        merged["a"].append(4)
        merged["b"]["c"].append(5)
        self.assertEqual(dict1["a"], [1])
        self.assertEqual(dict1["b"]["c"], [2])


if __name__ == "__main__":
    unittest.main()
