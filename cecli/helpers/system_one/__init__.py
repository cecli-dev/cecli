"""System One decision endpoints, speaking the ``/v1/systemone`` wire format.

Three layers live here, from the wire up:

- :mod:`cecli.helpers.system_one.types` - the question/answer vocabulary
  (``noul`` / ``choice`` / ``score``) and the parsing of response bodies.
- :mod:`cecli.helpers.system_one.api` - one call per decision (:func:`decide`,
  :func:`judge`, :func:`rate`) plus :func:`system_one` / :func:`ask` for
  several questions over one state.
- :mod:`cecli.helpers.system_one.integrations` - the shorthand forms other cecli
  subsystems (hooks today) use, so their call sites stay one-liners.

Endpoint settings come from ``--system-one`` (or the ``system-one`` config-file
key), installed with :func:`configure`, or from ``SYSTEM_ONE_*`` defaults.
"""

from cecli.helpers.system_one.api import (
    DECIDE_QUESTION_ID,
    JUDGE_QUESTION_ID,
    RATE_QUESTION_ID,
    ask,
    decide,
    judge,
    rate,
    system_one,
)
from cecli.helpers.system_one.client import SystemOneClient, SystemOneError
from cecli.helpers.system_one.config import (
    DEFAULT_API_BASE,
    ENDPOINT_PATH,
    SystemOneConfig,
    configure,
    get_config,
    is_configured,
    reset,
)
from cecli.helpers.system_one.types import (
    CHOICE,
    NOUL,
    QUESTION_TYPES,
    SCORE,
    ChoiceAnswer,
    NoulAnswer,
    ScoreAnswer,
    SystemOneResponse,
    build_payload,
    choice,
    noul,
    parse_answer,
    parse_response,
    score,
)

__all__ = [
    "CHOICE",
    "DEFAULT_API_BASE",
    "DECIDE_QUESTION_ID",
    "JUDGE_QUESTION_ID",
    "RATE_QUESTION_ID",
    "ENDPOINT_PATH",
    "NOUL",
    "QUESTION_TYPES",
    "SCORE",
    "ChoiceAnswer",
    "NoulAnswer",
    "ScoreAnswer",
    "SystemOneClient",
    "SystemOneConfig",
    "SystemOneError",
    "SystemOneResponse",
    "ask",
    "build_payload",
    "choice",
    "configure",
    "decide",
    "get_config",
    "is_configured",
    "judge",
    "noul",
    "parse_answer",
    "parse_response",
    "rate",
    "reset",
    "score",
    "system_one",
]
