"""Shorthand decision calls for cecli subsystems.

The application api in :mod:`cecli.helpers.system_one.api` takes an explicit
wire-format question map. Subsystems inside cecli - hooks today, likely tools
and commands next - would rather ask in a smaller vocabulary: one of
``questions``, ``decide``, ``judge`` or ``rate`` over a state. This module owns
that translation so call sites stay one-liners instead of duplicating the
normalization rules.

Every entry point returns plain dicts (``response.to_dict()``), which is what
hook authors log, store and compare.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Union

from cecli.helpers.system_one.api import (
    DECIDE_QUESTION_ID,
    JUDGE_QUESTION_ID,
    RATE_QUESTION_ID,
    ask,
)
from cecli.helpers.system_one.types import choice, noul, score

#: Instructions used when a shorthand omits an explicit question.
DEFAULT_DECIDE_INSTRUCTIONS = "Which option best describes the state?"
DEFAULT_RATE_INSTRUCTIONS = "Rate the state against the rubric levels."


async def evaluate(
    state: Any,
    questions: Optional[Mapping[str, Any]] = None,
    decide: Optional[Union[str, Mapping[str, Any]]] = None,
    judge: Optional[Union[str, Mapping[str, Any]]] = None,
    rate: Optional[Union[List[Any], Mapping[str, Any]]] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Ask exactly one of the four forms about ``state``.

    Returns ``{"model": str, "usage": {...}, "answers": {id: {...}}}``; the
    single-question shorthands land under ``decision``, ``judgment`` and
    ``rating`` respectively.

    Raises:
        ValueError: If other than exactly one form is given.
        TypeError: If a ``questions`` entry is neither a dict nor a string.
    """
    payload = build_questions(questions, decide, judge, rate)
    response = await ask(state, payload, model=model)

    return response.to_dict()


def build_questions(
    questions: Optional[Mapping[str, Any]] = None,
    decide: Optional[Union[str, Mapping[str, Any]]] = None,
    judge: Optional[Union[str, Mapping[str, Any]]] = None,
    rate: Optional[Union[List[Any], Mapping[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Normalize the shorthand forms into one wire-format question map."""
    forms = (
        ("questions", questions),
        ("decide", decide),
        ("judge", judge),
        ("rate", rate),
    )
    provided = [name for name, value in forms if value is not None]

    if len(provided) != 1:
        raise ValueError(
            f"evaluate() takes exactly one of {'/'.join(name for name, _ in forms)},"
            f" got {len(provided)}"
        )

    if questions is not None:
        return {
            str(question_id): _coerce_question(question_id, spec)
            for question_id, spec in questions.items()
        }

    if decide is not None:
        options, instructions = _decide_args(decide)

        return {DECIDE_QUESTION_ID: choice(instructions, options)}

    if judge is not None:
        instructions, criteria = _judge_args(judge)

        return {JUDGE_QUESTION_ID: noul(instructions, **criteria)}

    levels, instructions = _rate_args(rate)

    return {RATE_QUESTION_ID: score(instructions, levels)}


def _coerce_question(question_id: Any, spec: Any) -> Dict[str, Any]:
    """Expand a shorthand question value into a wire-format question dict."""
    if isinstance(spec, str):
        return noul(spec)

    if isinstance(spec, Mapping):
        return dict(spec)

    raise TypeError(
        f"Question {question_id!r} must be a dict or instructions string,"
        f" got {type(spec).__name__}"
    )


def _decide_args(decide: Union[str, Mapping[str, Any]]) -> tuple:
    """Normalize a ``decide=`` shorthand to ``(options, instructions)``."""
    if isinstance(decide, str):
        return [decide], DEFAULT_DECIDE_INSTRUCTIONS

    spec = dict(decide)

    return (
        spec.get("choices", spec.get("criteria", {})),
        spec.get("instructions", DEFAULT_DECIDE_INSTRUCTIONS),
    )


def _judge_args(judge: Union[str, Mapping[str, Any]]) -> tuple:
    """Normalize a ``judge=`` shorthand to ``(instructions, criteria)``."""
    if isinstance(judge, str):
        return judge, {}

    spec = dict(judge)
    criteria = spec.get("criteria") or {}

    return spec.get("instructions", ""), {
        key: value for key, value in criteria.items() if key in ("true", "false")
    }


def _rate_args(rate: Union[List[Any], Mapping[str, Any]]) -> tuple:
    """Normalize a ``rate=`` shorthand to ``(levels, instructions)``."""
    if isinstance(rate, Mapping):
        spec = dict(rate)

        return (
            spec.get("levels", spec.get("criteria", [])),
            spec.get("instructions", DEFAULT_RATE_INSTRUCTIONS),
        )

    return list(rate), DEFAULT_RATE_INSTRUCTIONS


__all__ = [
    "DEFAULT_DECIDE_INSTRUCTIONS",
    "DEFAULT_RATE_INSTRUCTIONS",
    "build_questions",
    "evaluate",
]
