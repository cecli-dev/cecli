import cecli.help as help_module
from cecli.help import navigate_docs


def _write_doc(root, relative_path, text):
    path = root / "website" / "docs" / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_navigate_docs_ranks_files_and_sections(monkeypatch, tmp_path):
    hooks = _write_doc(
        tmp_path,
        "config/hooks.md",
        "# Hook config\n\nhook config body\n\n## Config\n\nconfig details\n",
    )
    usage = _write_doc(tmp_path, "usage.md", "# Usage\n\nhook only\n")
    monkeypatch.setattr(help_module, "get_package_files", lambda: [hooks, usage])

    navigation = navigate_docs("hook config", n_files=1, n_sections=2)

    assert navigation["files"][0]["path"] == "config/hooks.md"
    assert navigation["files"][0]["matched_terms"] == ["hook", "config"]
    assert navigation["files"][0]["section_count"] == 2

    assert navigation["sections"][0]["path"] == "config/hooks.md"
    assert navigation["sections"][0]["heading"] == "Hook config"
    assert navigation["sections"][0]["line"] == 1
    assert navigation["sections"][0]["slug"] == "hook-config"
    assert navigation["sections"][0]["address"] == "config/hooks.md#hook-config"
    assert navigation["sections"][1]["heading"] == "Hook config > Config"


def test_navigate_docs_returns_empty_for_stopword_query():
    assert navigate_docs("the and") == {"files": [], "sections": []}


def test_iter_doc_sections_skips_front_matter_and_fenced_headings():
    text = "---\nparent: Test\n---\n\n# Top\n\n```markdown\n## Not a heading\n```\n\n## Real\n"

    sections = help_module._iter_doc_sections(text)

    assert [heading for heading, _, _ in sections] == ["Top", "Top > Real"]
    assert sections[0][1] == 5
