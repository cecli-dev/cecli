"""
Tests for cecli/helpers/plugin_manager.py
"""

import shutil
import sys
import tempfile
from pathlib import Path

from cecli.helpers.plugin_manager import (
    gensym,
    load_module,
    module_cache,
    normalize_filename,
)

# Add the project root to the path so we can import cecli modules
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


class TestPluginManager:
    """Test suite for plugin_manager.py"""

    def setup_method(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp(prefix="test_plugin_manager_")
        self.test_module_counter = 0
        # Clear the module cache before each test
        module_cache.clear()

    def teardown_method(self):
        """Clean up test environment"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        # Clear the module cache after each test
        module_cache.clear()

    def create_test_module(self, content=None, name=None):
        """Create a test Python module file"""
        if name is None:
            self.test_module_counter += 1
            name = f"test_module_{self.test_module_counter}"

        module_path = Path(self.temp_dir) / f"{name}.py"

        if content is None:
            content = f"""
print("Module {name} loaded!")
value = 0

def get_value():
    global value
    return value

def set_value(v):
    global value
    value = v
    return value

def increment():
    global value
    value += 1
    return value
"""

        module_path.write_text(content)
        return str(module_path)

    def test_gensym(self):
        """Test gensym function generates unique symbols"""
        # Test default parameters
        sym1 = gensym()
        sym2 = gensym()
        assert sym1 != sym2, "gensym should generate unique symbols"
        assert sym1.startswith("gensym_"), "Default prefix should be 'gensym_'"
        assert len(sym1) == 32 + len("gensym_"), "Default length should be 32 + prefix"

        # Test custom parameters
        sym3 = gensym(length=10, prefix="test_")
        assert sym3.startswith("test_"), "Should use custom prefix"
        assert len(sym3) == 10 + len("test_"), "Should use custom length"

        # Test multiple calls produce different results
        symbols = {gensym(8) for _ in range(100)}
        assert len(symbols) == 100, "Should generate unique symbols"

    def test_normalize_filename(self):
        """Test normalize_filename function"""
        # Basic filename
        assert normalize_filename("module.py") == "module"
        assert normalize_filename("my_module.py") == "my_module"

        # Files with invalid characters
        assert normalize_filename("my-module.py") == "my_module"
        assert normalize_filename("my.module.py") == "my_module"
        assert normalize_filename("123module.py") == "_123module"
        assert normalize_filename("module-name_v1.2.py") == "module_name_v1_2"

        # Already valid names
        assert normalize_filename("valid_name.py") == "valid_name"
        assert normalize_filename("_private.py") == "_private"

        # Case handling (should be lowercase)
        assert normalize_filename("ModuleName.py") == "modulename"
        assert normalize_filename("MY_MODULE.py") == "my_module"

    def test_load_module_basic(self):
        """Test basic module loading"""
        module_path = self.create_test_module()

        # Load module without explicit name
        module = load_module(module_path)
        assert module is not None
        assert hasattr(module, "get_value")
        assert hasattr(module, "set_value")
        assert hasattr(module, "increment")

        # Module should be executable
        assert module.get_value() == 0
        assert module.increment() == 1
        assert module.get_value() == 1

        # Module should be in sys.modules
        assert module.__name__ in sys.modules

    def test_load_module_with_explicit_name(self):
        """Test loading module with explicit name"""
        module_path = self.create_test_module()

        # Load with explicit name
        module = load_module(module_path, module_name="my_custom_module")
        assert module.__name__ == "my_custom_module"
        assert "my_custom_module" in sys.modules

        # Clean up from sys.modules
        if "my_custom_module" in sys.modules:
            del sys.modules["my_custom_module"]

    def test_load_module_caching(self):
        """Test that modules are cached by file path"""
        module_path = self.create_test_module()

        # First load
        module1 = load_module(module_path)
        initial_name = module1.__name__

        # Modify state
        module1.set_value(42)

        # Second load (should be cached)
        module2 = load_module(module_path)

        # Should be same object
        assert module1 is module2
        assert module2.__name__ == initial_name
        assert module2.get_value() == 42  # State should be preserved

        # Cache should contain the module
        abs_path = str(Path(module_path).resolve())
        assert abs_path in module_cache
        assert module_cache[abs_path] is module1

    def test_load_module_reload(self):
        """Test forced reload with reload=True"""
        module_path = self.create_test_module()

        # First load
        module1 = load_module(module_path)
        module1.set_value(100)

        # Force reload
        module2 = load_module(module_path, reload=True)

        # Should be different objects
        assert module1 is not module2
        assert module1.__name__ != module2.__name__

        # New module should have fresh state
        assert module2.get_value() == 0
        assert module1.get_value() == 100  # Original unchanged

        # Cache should now point to new module
        abs_path = str(Path(module_path).resolve())
        assert module_cache[abs_path] is module2
        assert module_cache[abs_path] is not module1

    def test_load_module_reload_with_explicit_name(self):
        """Test reload with explicit module name"""
        module_path = self.create_test_module()

        # Load with explicit name
        module1 = load_module(module_path, module_name="named_module")
        assert module1.__name__ == "named_module"
        module1.set_value(50)

        # Reload with same explicit name
        module2 = load_module(module_path, module_name="named_module", reload=True)
        assert module2.__name__ == "named_module"
        assert module2.get_value() == 0  # Fresh state
        assert module1 is not module2  # Different instances

        # Clean up from sys.modules
        if "named_module" in sys.modules:
            del sys.modules["named_module"]

    def test_loadmodule_cache_absolute_paths(self):
        """Test that cache uses absolute paths"""
        module_path = self.create_test_module()
        abs_path = str(Path(module_path).resolve())

        # Load with relative path
        module1 = load_module(module_path)

        # Load with absolute path (should be cached)
        module2 = load_module(abs_path)

        assert module1 is module2, "Should return same module for same absolute path"
        assert abs_path in module_cache

    def test_load_module_different_paths_same_file(self):
        """Test that different paths to same file use cache"""
        module_path = self.create_test_module()

        # Create a symlink to the same file
        symlink_path = Path(self.temp_dir) / "symlink_module.py"
        symlink_path.symlink_to(Path(module_path).resolve())

        # Load via original path
        module1 = load_module(module_path)
        module1.set_value(99)

        # Load via symlink (should be cached)
        module2 = load_module(str(symlink_path))

        assert module1 is module2, "Should return same module for same file"
        assert module2.get_value() == 99

        # Clean up symlink
        symlink_path.unlink()

    def test_load_module_error_handling(self):
        """Test error handling for non-existent files"""
        non_existent = Path(self.temp_dir) / "non_existent.py"

        # Should raise an error
        try:
            load_module(str(non_existent))
            assert False, "Should have raised an error"
        except Exception as e:
            # importlib should raise an error when file doesn't exist
            assert "non_existent" in str(e) or "No such file" in str(e)

    def test_load_module_with_code(self):
        """Test loading module with actual Python code"""
        module_path = self.create_test_module(content="""
def add(a, b):
    return a + b

def multiply(a, b):
    return a * b

class Calculator:
    def __init__(self, initial=0):
        self.value = initial

    def add(self, x):
        self.value += x
        return self.value
""")

        module = load_module(module_path)

        # Test functions
        assert module.add(2, 3) == 5
        assert module.multiply(2, 3) == 6

        # Test class
        calc = module.Calculator(10)
        assert calc.value == 10
        assert calc.add(5) == 15

    def test_module_name_generation(self):
        """Test that module names are generated correctly"""
        module_path = self.create_test_module(name="test-module.v1")

        module = load_module(module_path)
        module_name = module.__name__

        # Should start with normalized filename
        assert module_name.startswith("test_module_v1_")
        # Should have random suffix
        assert len(module_name) > len("test_module_v1_")

        # Different loads should have different names
        module2 = load_module(module_path, reload=True)
        assert module.__name__ != module2.__name__

    def test_cache_clear_on_reload(self):
        """Test that cache is properly updated on reload"""
        module_path = self.create_test_module()

        # Track all loaded modules
        modules = []

        # Load, reload, load sequence
        modules.append(load_module(module_path))
        modules.append(load_module(module_path, reload=True))
        modules.append(load_module(module_path))  # Should get the reloaded one

        # Verify relationships
        assert modules[0] is not modules[1], "First and reloaded should differ"
        assert modules[1] is modules[2], "Reloaded and cached should be same"
        assert modules[0] is not modules[2], "First and final cached should differ"

        # Cache should point to latest
        abs_path = str(Path(module_path).resolve())
        assert module_cache[abs_path] is modules[1]
        assert module_cache[abs_path] is modules[2]


if __name__ == "__main__":
    # Run tests if executed directly
    import pytest

    pytest.main([__file__, "-v"])
