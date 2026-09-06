import pytest

from cecli.helpers.model_config.registry import clear_default_registry
from cecli.models import Model


# Model Fixtures
@pytest.fixture(autouse=True)
def _clear_model_config_default_registry():
    """Reset the per-model default registry between tests."""
    clear_default_registry()


# Model Fixtures
@pytest.fixture
def gpt35_model():
    """Common GPT-3.5-turbo model fixture used across test files."""
    return Model("gpt-3.5-turbo")


@pytest.fixture
def gpt4_model():
    """Common GPT-4 model fixture for tests requiring GPT-4."""
    return Model("gpt-4")


# from pyinstrument import Profiler

# @pytest.fixture(autouse=True, scope="session")
# def profile_suite():
#     profiler = Profiler()
#     profiler.start()
#
#     yield  # The entire test suite runs here
#
#     profiler.stop()
#
#     # Save the interactive HTML report
#     output_html_path = "pytest_profile.html"
#     with open(output_html_path, "w", encoding="utf-8") as f:
#         f.write(profiler.output_html())
#
#     print(f"\n[Pyinstrument] Flame graph saved to: {output_html_path}")
