import pytest

from cecli.models import Model


# Model Fixtures
@pytest.fixture
def gpt35_model():
    """Common GPT-3.5-turbo model fixture used across test files."""
    return Model("gpt-3.5-turbo")


@pytest.fixture
def gpt4_model():
    """Common GPT-4 model fixture for tests requiring GPT-4."""
    return Model("gpt-4")
