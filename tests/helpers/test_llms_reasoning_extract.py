"""extract_reasoning unit tests: shape handling + no double-counting.

``cecli.helpers.llms.utils.extract_reasoning`` reads reasoning from the three
wild shapes (``reasoning_content`` string, ``reasoning`` string,
``reasoning_details`` list). OpenRouter (and minimax via OpenRouter) sends BOTH
the flat ``reasoning`` string AND a ``reasoning_details`` list holding the same
incremental text on every delta; the extractor must use the structured list
authoritatively and NOT combine both (that doubled every reasoning fragment).
"""

from cecli.helpers.llms.utils import extract_reasoning


def test_reasoning_string_only():
    assert extract_reasoning({"reasoning": "think think"}) == "think think"


def test_reasoning_content_string_only():
    assert extract_reasoning({"reasoning_content": "deepseek thinks"}) == "deepseek thinks"


def test_reasoning_details_list_only():
    delta = {
        "reasoning_details": [
            {"type": "reasoning.text", "text": "first"},
            {"type": "reasoning.text", "text": "second"},
        ]
    }
    assert extract_reasoning(delta) == "first\nsecond"


def test_both_string_and_details_not_doubled():
    # The exact minimax/openrouter regression: same text in both fields.
    delta = {
        "reasoning": "The user asks hello",
        "reasoning_details": [{"type": "reasoning.text", "text": "The user asks hello"}],
    }
    assert extract_reasoning(delta) == "The user asks hello"


def test_details_wins_when_string_is_shorter_suffix():
    # Incremental deltas: the details list is authoritative even when the
    # flat string differs in length (it is the same content by construction).
    delta = {
        "reasoning": " suffix",
        "reasoning_details": [{"type": "reasoning.text", "text": "prefix suffix"}],
    }
    assert extract_reasoning(delta) == "prefix suffix"


def test_empty_details_falls_back_to_string():
    delta = {"reasoning": "fallback", "reasoning_details": []}
    assert extract_reasoning(delta) == "fallback"


def test_no_reasoning_returns_empty():
    assert extract_reasoning({"content": "hi"}) == ""
    assert extract_reasoning({}) == ""
