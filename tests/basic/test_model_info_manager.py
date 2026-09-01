import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from cecli.models import ModelInfoManager


class TestModelInfoManager(TestCase):
    def setUp(self):
        self.original_env = os.environ.copy()
        self.manager = ModelInfoManager()
        # Create a temporary directory for cache
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager.cache_dir = Path(self.temp_dir.name)
        self.manager.cache_file = self.manager.cache_dir / "model_prices_and_context_window.json"
        self.manager.cache_dir.mkdir(exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_lazy_loading_cache(self):
        # Create a cache file
        self.manager.cache_file.write_text('{"test_model": {"max_tokens": 4096}}')

        # Verify cache is not loaded on initialization
        self.assertFalse(self.manager._cache_loaded)
        self.assertIsNone(self.manager.content)

        # Access content through get_model_from_cached_json_db
        with patch.object(self.manager, "_load_cache", wraps=self.manager._load_cache) as mock_load:
            result = self.manager.get_model_from_cached_json_db("test_model")

            # Verify cache was loaded lazily on first access
            self.assertTrue(self.manager._cache_loaded)
            self.assertIsNotNone(self.manager._raw_content)
            self.assertEqual(result, {"max_tokens": 4096})

            # Verify _load_cache was called exactly once (lazy load on demand)
            mock_load.assert_called_once()
