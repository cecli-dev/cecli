"""Wire-format types for the System One evaluation endpoint.

The endpoint speaks a small, non-autoregressive protocol: a ``state`` plus a
map of typed ``questions`` in, a map of typed ``answers`` out. This module
owns the vocabulary of that protocol - question builders, the request payload,
and the typed answer objects returned after parsing.

Question types are ``noul`` (a yes/no probability), ``choice`` (pick one
option from a described set) and ``score`` (rate against an ordered rubric).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union

from cecli.helpers.system_one.config import DEFAULT_MODEL_NAME

#: Question types accepted by the endpoint.
NOUL = "noul"
CHOICE = "choice"
SCORE = "score"

QUESTION_TYPES = (NOUL, CHOICE, SCORE)

#: instructions/criteria accept plain strings or structured objects/arrays.
StructuredValue = Union[str, Dict[str, Any], List[Any]]


def noul(
    instructions: StructuredValue,
    true: Optional[StructuredValue] = None,
    false: Optional[StructuredValue] = None,
) -> Dict[str, Any]:
    """Build a yes/no question returning the probability the answer is yes."""
    question: Dict[str, Any] = {"type": NOUL, "instructions": instructions}

    if true is not None or false is not None:
        criteria: Dict[str, Any] = {}

        if true is not None:
            criteria["true"] = true

        if false is not None:
            criteria["false"] = false

        question["criteria"] = criteria

    return question


def choice(
    instructions: StructuredValue,
    criteria: Union[Mapping[str, Any], Iterable[str], None] = None,
) -> Dict[str, Any]:
    """Build a question that picks one option from ``criteria``.

    ``criteria`` maps each option to a rubric description; a bare iterable of
    option names is accepted and expanded to ``{option: None}``.
    """
    if criteria is None:
        options: Dict[str, Any] = {}
    elif isinstance(criteria, Mapping):
        options = dict(criteria)
    else:
        options = {str(name): None for name in criteria}

    return {"type": CHOICE, "instructions": instructions, "criteria": options}


def score(
    instructions: StructuredValue,
    criteria: Optional[List[StructuredValue]] = None,
) -> Dict[str, Any]:
    """Build a question that rates the state against ordered level rubrics."""
    if criteria is None:
        criteria = []

    return {"type": SCORE, "instructions": instructions, "criteria": list(criteria)}


@dataclass
class NoulAnswer:
    """A yes/no answer expressed as a probability of yes (0.0 - 1.0)."""

    probability: float
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def yes(self) -> bool:
        """Whether the answer favours "yes" at or above even odds."""
        return self.probability >= 0.5

    def to_dict(self) -> Dict[str, Any]:
        return {"type": NOUL, "noul": self.probability, "yes": self.yes}


@dataclass
class ChoiceAnswer:
    """The selected option plus the full probability distribution."""

    choice: str
    probabilities: Dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": CHOICE,
            "choice": self.choice,
            "probabilities": dict(self.probabilities),
            "confidence": self.confidence,
        }


@dataclass
class ScoreAnswer:
    """A probability-weighted rating that can land between rubric levels."""

    score: float
    legend: Dict[str, str] = field(default_factory=dict)
    probabilities: Dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def levels(self) -> List[str]:
        """Rubric descriptions ordered by level index."""
        return [self.legend[key] for key in sorted(self.legend, key=_level_sort_key)]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": SCORE,
            "score": self.score,
            "legend": dict(self.legend),
            "probabilities": dict(self.probabilities),
            "confidence": self.confidence,
        }


#: Any parsed answer.
Answer = Union[NoulAnswer, ChoiceAnswer, ScoreAnswer]


@dataclass
class SystemOneResponse:
    """A full evaluation: one answer per question, keyed as provided."""

    answers: Dict[str, Answer] = field(default_factory=dict)
    model: str = ""
    usage: Dict[str, int] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, question_id: str) -> Answer:
        return self.answers[question_id]

    def __contains__(self, question_id: object) -> bool:
        return question_id in self.answers

    def get(self, question_id: str, default: Any = None) -> Any:
        return self.answers.get(question_id, default)

    def to_dict(self) -> Dict[str, Any]:
        """Return the response as plain nested dicts (JSON-safe)."""
        return {
            "model": self.model,
            "answers": {key: answer.to_dict() for key, answer in self.answers.items()},
            "usage": dict(self.usage),
        }


def build_payload(
    state: Any,
    questions: Mapping[str, Dict[str, Any]],
    model: Optional[str] = None,
    default_model: Optional[str] = None,
) -> Dict[str, Any]:
    """Assemble the request body sent to the evaluation endpoint."""
    return {
        "state": state,
        "model": model or default_model or DEFAULT_MODEL_NAME,
        "questions": {str(key): dict(value) for key, value in questions.items()},
    }


def parse_response(payload: Mapping[str, Any]) -> SystemOneResponse:
    """Convert a decoded JSON response body into a :class:`SystemOneResponse`."""
    if not isinstance(payload, Mapping):
        raise ValueError(f"System One response must be an object, got {type(payload).__name__}")

    answers: Dict[str, Answer] = {}
    raw_answers = payload.get("answers") or {}

    for question_id, raw_answer in raw_answers.items():
        answers[str(question_id)] = parse_answer(raw_answer)

    usage_raw = payload.get("usage") or {}
    usage = {str(key): int(value or 0) for key, value in usage_raw.items()}

    return SystemOneResponse(
        answers=answers,
        model=str(payload.get("model") or ""),
        usage=usage,
        raw=dict(payload),
    )


def parse_answer(raw: Any) -> Answer:
    """Parse a single answer object by its ``type`` discriminator."""
    if not isinstance(raw, Mapping):
        raise ValueError(f"System One answer must be an object, got {type(raw).__name__}")

    question_type = str(raw.get("type") or "")

    if question_type == NOUL:
        return NoulAnswer(probability=_as_float(raw.get("noul")), raw=dict(raw))

    if question_type == CHOICE:
        return ChoiceAnswer(
            choice=str(raw.get("choice") or ""),
            probabilities=_as_float_map(raw.get("probabilities")),
            confidence=_as_float(raw.get("confidence")),
            raw=dict(raw),
        )

    if question_type == SCORE:
        return ScoreAnswer(
            score=_as_float(raw.get("score")),
            legend={str(k): str(v) for k, v in (raw.get("legend") or {}).items()},
            probabilities=_as_float_map(raw.get("probabilities")),
            confidence=_as_float(raw.get("confidence")),
            raw=dict(raw),
        )

    raise ValueError(f"Unknown System One answer type: {question_type!r}")


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_float_map(value: Any) -> Dict[str, float]:
    if not isinstance(value, Mapping):
        return {}

    return {str(key): _as_float(item) for key, item in value.items()}


def _level_sort_key(key: str) -> Any:
    try:
        return (0, int(key))
    except (TypeError, ValueError):
        return (1, key)
