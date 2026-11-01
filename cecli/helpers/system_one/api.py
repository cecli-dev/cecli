"""Application-level API over the System One endpoint.

Mirrors the shape of the ``von`` SDK so a decision reads like a single call
rather than a hand-built question map::

    from cecli.helpers import system_one

    r = await system_one.decide(
        state="Payment gateway timeouts on charge authorizations.",
        choices={"billing": "Payments and refunds", "infra": "Bugs and outages"},
        instructions="Which team owns this?",
    )
    r.choice, r.confidence, r.probabilities

``decide`` wraps a Choice question, ``judge`` a Noul (yes/no) question and
``rate`` a Score question; :func:`system_one` (alias :func:`ask`) covers the
multi-question case where several questions share one pass over the state.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Union

from cecli.helpers.system_one.client import SystemOneClient
from cecli.helpers.system_one.types import (
    ChoiceAnswer,
    NoulAnswer,
    ScoreAnswer,
    SystemOneResponse,
    choice,
    noul,
    score,
)

#: Question ids used when a single-question helper builds its own question map.
DECIDE_QUESTION_ID = "decision"
JUDGE_QUESTION_ID = "judgment"
RATE_QUESTION_ID = "rating"


async def ask(
    state: Any,
    questions: Mapping[str, Dict[str, Any]],
    model: Optional[str] = None,
    client: Optional[SystemOneClient] = None,
) -> SystemOneResponse:
    """Evaluate ``state`` against a map of typed questions (one request)."""
    return await (client or SystemOneClient()).evaluate(state, questions, model=model)


async def system_one(
    state: Any,
    questions: Mapping[str, Dict[str, Any]],
    model: Optional[str] = None,
    client: Optional[SystemOneClient] = None,
) -> SystemOneResponse:
    """Evaluate ``state`` against several questions in one request.

    Name-for-name parity with the ``von`` SDK's ``system_one()``; :func:`ask`
    is the same call under a name that reads better when the module itself is
    already imported as ``system_one``.
    """
    return await ask(state, questions, model=model, client=client)


async def decide(
    state: Any,
    choices: Union[Mapping[str, Any], Iterable[str]],
    instructions: str = "Which option best describes the state?",
    model: Optional[str] = None,
    client: Optional[SystemOneClient] = None,
) -> ChoiceAnswer:
    """Pick one option from ``choices`` for ``state``.

    ``choices`` maps an option to its rubric description, or is a bare
    iterable of option names when no rubric text is needed.
    """
    response = await ask(
        state,
        {DECIDE_QUESTION_ID: choice(instructions, choices)},
        model=model,
        client=client,
    )

    return _unwrap_choice(response)


async def judge(
    state: Any,
    instructions: str = "Is the statement in the instructions true of the state?",
    criteria: Optional[Mapping[str, Any]] = None,
    model: Optional[str] = None,
    client: Optional[SystemOneClient] = None,
) -> NoulAnswer:
    """Answer a yes/no question about ``state`` as a probability of yes.

    ``criteria`` describes what yes and no mean (``{"true": ..., "false":
    ...}``); omitting it is the weakest path, so prefer passing it or phrasing
    the decision as a described Choice.
    """
    if not isinstance(criteria, Mapping):
        criteria = _true_false_criteria(criteria) or {}

    response = await ask(
        state,
        {
            JUDGE_QUESTION_ID: noul(
                instructions, true=criteria.get("true"), false=criteria.get("false")
            )
        },
        model=model,
        client=client,
    )

    return _unwrap_noul(response)


async def rate(
    state: Any,
    levels: List[Any],
    instructions: str = "Rate the state against the rubric levels.",
    model: Optional[str] = None,
    client: Optional[SystemOneClient] = None,
) -> ScoreAnswer:
    """Rate ``state`` along an ordered rubric of ``levels``."""
    response = await ask(
        state,
        {RATE_QUESTION_ID: score(instructions, levels)},
        model=model,
        client=client,
    )

    return _unwrap_score(response)


def _true_false_criteria(criteria: Any) -> Optional[Dict[str, Any]]:
    """Accept ``criteria`` given as a mapping or a (true, false) pair."""
    if criteria is None:
        return None

    if isinstance(criteria, Mapping):
        return {
            "true": criteria.get("true"),
            "false": criteria.get("false"),
        }

    if isinstance(criteria, (list, tuple)) and len(criteria) == 2:
        return {"true": criteria[0], "false": criteria[1]}

    return None


def _unwrap_choice(response: SystemOneResponse) -> ChoiceAnswer:
    answer = _single(response)

    if not isinstance(answer, ChoiceAnswer):
        raise TypeError(f"Expected a choice answer, got {type(answer).__name__}")

    return answer


def _unwrap_noul(response: SystemOneResponse) -> NoulAnswer:
    answer = _single(response)

    if not isinstance(answer, NoulAnswer):
        raise TypeError(f"Expected a noul answer, got {type(answer).__name__}")

    return answer


def _unwrap_score(response: SystemOneResponse) -> ScoreAnswer:
    answer = _single(response)

    if not isinstance(answer, ScoreAnswer):
        raise TypeError(f"Expected a score answer, got {type(answer).__name__}")

    return answer


def _single(response: SystemOneResponse) -> Any:
    answers = list(response.answers.values())

    if not answers:
        raise ValueError("System One response carried no answers")

    return answers[0]
