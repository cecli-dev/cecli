"""Tests for the creator's installed-packages context block."""

from types import SimpleNamespace

from cecli.coders.agent_coder import AgentCoder
from cecli.helpers.creator import requirements


def test_installed_modules_uses_top_level_names(monkeypatch):
    monkeypatch.setattr(
        requirements,
        "packages_distributions",
        lambda: {
            "yaml": ["PyYAML"],
            "requests": ["requests"],
            "_private": ["internal"],
            "abc123__mypyc": ["compiled"],
            "": [],
        },
    )

    assert requirements.installed_modules() == ["requests", "yaml"]


def test_installed_modules_falls_back_to_distribution_names(monkeypatch):
    distribution = SimpleNamespace(metadata={"Name": "python-dotenv"})
    monkeypatch.setattr(requirements, "packages_distributions", lambda: {})
    monkeypatch.setattr(requirements, "distributions", lambda: [distribution])

    assert requirements.installed_modules() == ["python_dotenv"]


def test_packages_context_includes_interpreter_version(monkeypatch):
    monkeypatch.setattr(requirements, "installed_modules", lambda: ["requests"])

    environment, packages = requirements.packages_context()

    assert environment.startswith("Python ")
    assert packages == ["requests"]


def test_packages_context_none_without_modules(monkeypatch):
    monkeypatch.setattr(requirements, "installed_modules", lambda: [])

    assert requirements.packages_context() is None


def test_creator_context_lists_installed_modules(monkeypatch):
    monkeypatch.setattr(
        requirements,
        "packages_context",
        lambda: ("Python 3.14.0", ["requests", "rich", "yaml"]),
    )
    coder = SimpleNamespace(
        use_enhanced_context=True,
        agent_config={"creator_mode": True},
    )

    block = AgentCoder.get_creator_requirements_context(coder)

    assert '<context name="creator_requirements"' in block
    assert "Python 3.14.0 environment" in block
    assert "requests, rich, yaml" in block
    assert "Distribution names may" in block


def test_context_is_none_for_non_creator(monkeypatch):
    monkeypatch.setattr(
        requirements,
        "packages_context",
        lambda: ("Python 3.14.0", ["requests"]),
    )
    coder = SimpleNamespace(
        use_enhanced_context=True,
        agent_config={},
    )

    assert AgentCoder.get_creator_requirements_context(coder) is None


def _config(metadata):
    coder = SimpleNamespace(args=None, start_up_errors=[])

    return AgentCoder._get_agent_config(coder, config=metadata)


def test_searchdocs_is_default_excluded_but_available_to_creator():
    assert "searchdocs" in _config({})["tools_excludelist"]

    creator_config = _config({"creator_mode": True})
    assert "searchdocs" not in creator_config["tools_excludelist"]
    assert "creator_requirements" in creator_config["include_context_blocks"]


def test_creator_can_exclude_requirements_context():
    creator_config = _config(
        {
            "creator_mode": True,
            "exclude_context_blocks": ["creator_requirements"],
        }
    )

    assert "creator_requirements" not in creator_config["include_context_blocks"]
