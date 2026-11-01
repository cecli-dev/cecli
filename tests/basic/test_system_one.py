"""Tests for the System One helper: endpoint config, wire format, parsing.

These cover the shapes the /v1/systemone endpoint accepts and returns, using a
stubbed transport so no server or API key is involved.
"""

import json
import os
import tempfile

import pytest
import yaml

from cecli.args import get_parser
from cecli.helpers import config_utils, system_one
from cecli.hooks.helpers import HookHelpers
from cecli.main import convert_yaml_to_json_string


@pytest.fixture(autouse=True)
def clean_config():
    system_one.reset()
    yield
    system_one.reset()


@pytest.fixture
def transport(monkeypatch):
    """Capture request payloads and reply with a canned response body."""

    class Stub:
        def __init__(self):
            self.payloads = []
            self.responses = []

        def reply(self, body):
            self.responses.append(body)

        async def _post(self, payload):
            self.payloads.append(payload)

            if self.responses:
                return self.responses.pop(0)

            raise AssertionError("no canned response queued")

    stub = Stub()
    monkeypatch.setattr(system_one.SystemOneClient, "_post", stub._post)

    return stub


def _noul_body(question_id="q"):
    return {
        "model": "von-1.3.0",
        "answers": {question_id: {"type": "noul", "noul": 0.95}},
        "usage": {"input_tokens": 296, "output_tokens": 20},
    }


def _choice_body(question_id="decision"):
    return {
        "model": "von-1.3.0",
        "answers": {
            question_id: {
                "type": "choice",
                "choice": "billing",
                "probabilities": {"billing": 0.88, "technical": 0.12},
                "confidence": 0.81,
            }
        },
        "usage": {"input_tokens": 318, "output_tokens": 34},
    }


def _score_body(question_id="rating"):
    return {
        "model": "von-1.3.0",
        "answers": {
            question_id: {
                "type": "score",
                "score": 1.05,
                "legend": {"0": "Calm", "1": "Frustrated", "2": "Very angry"},
                "probabilities": {"0": 0.0, "1": 0.95, "2": 0.05},
                "confidence": 0.92,
            }
        },
        "usage": {"input_tokens": 304, "output_tokens": 18},
    }


class Coder:
    """Minimal coder stand-in for the hook helper."""


# --------------------------------------------------------------------------
# endpoint configuration


def test_default_endpoint_is_local_and_vendor_neutral():
    config = system_one.SystemOneConfig()

    assert config.api_base == "http://127.0.0.1:8000"
    assert config.endpoint_url == "http://127.0.0.1:8000/v1/systemone"
    assert config.api_key_env == ["SYSTEM_ONE_API_KEY"]


def test_from_env_only_reads_system_one_vars(monkeypatch):
    monkeypatch.setenv("SYSTEM_ONE_API_BASE", "http://decide.internal:9000")
    monkeypatch.setenv("SYSTEM_ONE_MODEL", "von-1.3.0")
    monkeypatch.setenv("VON_BASE_URL", "http://should-be-ignored:1")

    config = system_one.SystemOneConfig.from_env()

    assert config.api_base == "http://decide.internal:9000"
    assert config.model_name == "von-1.3.0"


def test_from_dict_reads_documented_keys():
    config = system_one.SystemOneConfig.from_dict(
        {
            "api_base": "http://127.0.0.1:8000/",
            "api_key_env": ["LITELLM_API_KEY"],
            "model_name": "von-latest",
            "extra_headers": {"optional": "a", "optional2": "b"},
        }
    )

    assert config.api_base == "http://127.0.0.1:8000"
    assert config.api_key_env == ["LITELLM_API_KEY"]
    assert config.model_name == "von-latest"
    assert config.extra_headers == {"optional": "a", "optional2": "b"}


def test_from_dict_accepts_key_spelling_variants():
    config = system_one.SystemOneConfig.from_dict(
        {"api-base": "http://h:1/v1", "model": "m-1", "headers": {"x-a": "1"}}
    )

    assert config.endpoint_url == "http://h:1/v1/systemone"
    assert config.model_name == "m-1"
    assert config.extra_headers == {"x-a": "1"}


def test_string_api_key_env_is_promoted_to_list():
    config = system_one.SystemOneConfig.from_dict({"api_key_env": "MY_KEY"})

    assert config.api_key_env == ["MY_KEY"]


def test_api_key_and_headers_are_assembled(monkeypatch):
    monkeypatch.delenv("SYSTEM_ONE_API_KEY", raising=False)

    config = system_one.SystemOneConfig.from_dict({"extra_headers": {"x-trace": "1"}})

    assert "Authorization" not in config.build_headers()
    assert config.build_headers()["x-trace"] == "1"

    monkeypatch.setenv("SYSTEM_ONE_API_KEY", "secret")

    assert config.build_headers()["Authorization"] == "Bearer secret"


def test_configured_key_env_names_are_the_only_ones_probed(monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "lit")
    monkeypatch.setenv("SYSTEM_ONE_API_KEY", "one")

    config = system_one.SystemOneConfig.from_dict({"api_key_env": ["LITELLM_API_KEY"]})

    assert config.resolve_api_key() == "lit"
    assert system_one.SystemOneConfig.from_env().resolve_api_key() == "one"


def test_configure_installs_and_reset_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("SYSTEM_ONE_API_BASE", "http://env-host:8000")

    assert not system_one.is_configured()
    assert system_one.get_config().api_base == "http://env-host:8000"

    assert system_one.configure({"api_base": "http://cli-host:8000"}) is not None
    assert system_one.get_config().api_base == "http://cli-host:8000"

    # An empty payload (the {} a config-file merge can leave behind) is a no-op.
    assert system_one.configure({}) is None
    assert system_one.get_config().api_base == "http://cli-host:8000"

    system_one.reset()

    assert system_one.get_config().api_base == "http://env-host:8000"


# --------------------------------------------------------------------------
# wire format: questions


def test_noul_question_shape():
    assert system_one.noul("Is this urgent?") == {"type": "noul", "instructions": "Is this urgent?"}


def test_noul_question_with_criteria():
    question = system_one.noul("Is this urgent?", true="Time sensitive", false="No urgency")

    assert question["criteria"] == {"true": "Time sensitive", "false": "No urgency"}


def test_choice_question_from_map_and_from_names():
    from_map = system_one.choice("Who owns this?", {"billing": "Payments", "infra": "Bugs"})

    assert from_map["type"] == "choice"
    assert from_map["criteria"] == {"billing": "Payments", "infra": "Bugs"}

    from_names = system_one.choice("Who owns this?", ["billing", "infra"])

    assert from_names["criteria"] == {"billing": None, "infra": None}


def test_score_question_keeps_level_order():
    question = system_one.score("How frustrated?", ["Calm", "Frustrated", "Very angry"])

    assert question == {
        "type": "score",
        "instructions": "How frustrated?",
        "criteria": ["Calm", "Frustrated", "Very angry"],
    }


def test_instructions_may_be_structured():
    instructions = {
        "potential_duplicate": {"name": "John Smith"},
        "question": "Is the resume for the same person as `potential_duplicate`?",
    }
    question = system_one.noul(instructions)

    assert question["instructions"] == instructions


def test_build_payload_carries_state_model_and_questions():
    payload = system_one.build_payload(
        {"ticket": "INC-1"}, {"a": system_one.noul("urgent?")}, default_model="von-1.3.0"
    )

    assert payload["state"] == {"ticket": "INC-1"}
    assert payload["model"] == "von-1.3.0"
    assert payload["questions"] == {"a": {"type": "noul", "instructions": "urgent?"}}


# --------------------------------------------------------------------------
# wire format: answers


def test_parse_noul_answer():
    response = system_one.parse_response(_noul_body())
    answer = response.answers["q"]

    assert isinstance(answer, system_one.NoulAnswer)
    assert answer.probability == 0.95
    assert answer.yes is True
    assert answer.to_dict() == {"type": "noul", "noul": 0.95, "yes": True}
    assert response.model == "von-1.3.0"
    assert response.usage == {"input_tokens": 296, "output_tokens": 20}


def test_parse_choice_answer():
    answer = system_one.parse_response(_choice_body()).answers["decision"]

    assert isinstance(answer, system_one.ChoiceAnswer)
    assert answer.choice == "billing"
    assert answer.probabilities == {"billing": 0.88, "technical": 0.12}
    assert answer.confidence == 0.81
    assert set(answer.to_dict()) == {"type", "choice", "probabilities", "confidence"}


def test_parse_score_answer_and_levels():
    answer = system_one.parse_response(_score_body()).answers["rating"]

    assert isinstance(answer, system_one.ScoreAnswer)
    assert answer.score == 1.05
    assert answer.levels == ["Calm", "Frustrated", "Very angry"]
    assert answer.probabilities == {"0": 0.0, "1": 0.95, "2": 0.05}
    assert answer.to_dict()["legend"]["2"] == "Very angry"


def test_missing_numeric_fields_default_to_zero():
    answer = system_one.parse_answer({"type": "choice", "choice": "billing"})

    assert answer.choice == "billing"
    assert answer.probabilities == {}
    assert answer.confidence == 0.0


def test_non_numeric_values_do_not_crash_parsing():
    answer = system_one.parse_answer({"type": "noul", "noul": "0.7"})

    assert answer.probability == 0.7


def test_unknown_answer_type_is_rejected():
    with pytest.raises(ValueError, match="Unknown System One answer type"):
        system_one.parse_answer({"type": "wizard", "wizard": 1})


def test_non_object_answer_is_rejected():
    with pytest.raises(ValueError, match="must be an object"):
        system_one.parse_answer("noul")


def test_response_is_lookup_friendly():
    response = system_one.parse_response(_noul_body("urgent"))

    assert "urgent" in response
    assert response["urgent"].probability == 0.95
    assert response.get("missing") is None
    assert response.to_dict()["answers"]["urgent"]["type"] == "noul"


# --------------------------------------------------------------------------
# application api: decide / judge / rate / ask


async def test_decide_sends_choice_question_and_parses(transport):
    transport.reply(_choice_body())

    answer = await system_one.decide(
        state="Disk volume /var/log at 98%.",
        choices={"sre": "Infrastructure", "app": "Application code"},
        instructions="Who owns this?",
    )

    question = transport.payloads[0]["questions"]["decision"]

    assert question["type"] == "choice"
    assert question["criteria"] == {"sre": "Infrastructure", "app": "Application code"}
    assert answer.choice == "billing"
    assert transport.payloads[0]["model"] == system_one.get_config().model_name


async def test_judge_sends_noul_question_with_criteria(transport):
    transport.reply(_noul_body("judgment"))

    answer = await system_one.judge(
        state="Connection pool exhausted.",
        instructions="Is this blocking customers?",
        criteria={"true": "Requests fail", "false": "Internal only"},
    )

    question = transport.payloads[0]["questions"]["judgment"]

    assert question["type"] == "noul"
    assert question["criteria"] == {"true": "Requests fail", "false": "Internal only"}
    assert answer.probability == 0.95


async def test_judge_ignores_unrecognized_criteria_keys(transport):
    transport.reply(_noul_body("judgment"))

    await system_one.judge(state="x", instructions="y?", criteria={"true": "a", "extra": 1})

    assert transport.payloads[0]["questions"]["judgment"]["criteria"] == {"true": "a"}


async def test_judge_accepts_a_true_false_pair(transport):
    transport.reply(_noul_body("judgment"))

    await system_one.judge(state="x", instructions="y?", criteria=["blocking", "internal only"])

    assert transport.payloads[0]["questions"]["judgment"]["criteria"] == {
        "true": "blocking",
        "false": "internal only",
    }


async def test_judge_without_criteria_omits_the_field(transport):
    transport.reply(_noul_body("judgment"))

    await system_one.judge(state="x", instructions="Is this true?")

    assert "criteria" not in transport.payloads[0]["questions"]["judgment"]


async def test_rate_sends_score_question(transport):
    transport.reply(_score_body())

    answer = await system_one.rate(
        state="Memory at 98%.",
        levels=["Nominal", "Degraded", "Critical"],
        instructions="Assess degradation.",
    )

    assert transport.payloads[0]["questions"]["rating"]["criteria"] == [
        "Nominal",
        "Degraded",
        "Critical",
    ]
    assert answer.score == 1.05


async def test_ask_evaluates_several_questions_in_one_request(transport):
    transport.reply(
        {
            "model": "von-1.3.0",
            "answers": {
                "intent": {"type": "choice", "choice": "payment_failure", "probabilities": {}},
                "is_urgent": {"type": "noul", "noul": 0.9},
            },
            "usage": {"input_tokens": 300, "output_tokens": 20},
        }
    )

    response = await system_one.ask(
        state={"ticket": "INC-4091", "message": "Gateway timeouts."},
        questions={
            "intent": system_one.choice(
                "Nature of the ticket?", {"payment_failure": "Charges fail"}
            ),
            "is_urgent": system_one.noul("Needs immediate intervention?"),
        },
    )

    assert len(transport.payloads) == 1
    assert sorted(transport.payloads[0]["questions"]) == ["intent", "is_urgent"]
    assert response["intent"].choice == "payment_failure"
    assert response["is_urgent"].probability == 0.9


async def test_system_one_call_matches_ask(transport):
    transport.reply(_noul_body("is_urgent"))

    response = await system_one.system_one(
        state="Payouts failing.",
        questions={"is_urgent": system_one.noul("Urgent?")},
    )

    assert response["is_urgent"].probability == 0.95
    assert response.model == "von-1.3.0"


async def test_model_override_reaches_the_payload(transport):
    transport.reply(_noul_body("judgment"))

    await system_one.judge(state="x", instructions="y?", model="custom-model")

    assert transport.payloads[0]["model"] == "custom-model"


async def test_request_uses_configured_endpoint_and_headers(monkeypatch):
    import httpx

    monkeypatch.setenv("SYSTEM_ONE_API_KEY", "secret")
    system_one.configure(
        {
            "api_base": "http://decide.test:8000",
            "model_name": "von-1.3.0",
            "extra_headers": {"x-a": "b"},
        }
    )

    seen = {}
    _fake_httpx_client(monkeypatch, seen, [httpx.Response(200, json=_noul_body("judgment"))])

    answer = await system_one.judge(state="x", instructions="blocking?")

    assert seen["url"] == "http://decide.test:8000/v1/systemone"
    assert seen["headers"]["Authorization"] == "Bearer secret"
    assert seen["headers"]["x-a"] == "b"
    assert seen["json"]["model"] == "von-1.3.0"
    assert answer.probability == 0.95


async def test_rate_limited_responses_are_retried(monkeypatch):
    import asyncio

    import httpx

    async def _no_sleep(*args, **kwargs):
        return None

    system_one.configure({"api_base": "http://decide.test:8000", "max_retries": 2})
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    seen = {"count": 0}
    responses = [
        httpx.Response(429, text="slow down"),
        httpx.Response(529, text="overloaded"),
        httpx.Response(200, json=_noul_body("judgment")),
    ]

    _fake_httpx_client(monkeypatch, seen, responses)

    answer = await system_one.judge(state="x", instructions="blocking?")

    assert answer.probability == 0.95
    assert seen["count"] == 3


async def test_missing_api_key_is_named_in_auth_errors(monkeypatch):
    import httpx

    monkeypatch.delenv("SYSTEM_ONE_API_KEY", raising=False)
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    system_one.configure(
        {
            "api_base": "http://decide.test:8000",
            "api_key_env": ["SYSTEM_ONE_API_KEY", "LITELLM_API_KEY"],
            "max_retries": 0,
        }
    )

    _fake_httpx_client(
        monkeypatch,
        {"count": 0},
        [httpx.Response(403, json={"detail": "Must supply an API key"})],
    )

    with pytest.raises(system_one.SystemOneError) as excinfo:
        await system_one.judge(state="x", instructions="y?")

    message = str(excinfo.value)

    assert "SYSTEM_ONE_API_KEY, LITELLM_API_KEY" in message
    assert "No API key was sent" in message


async def test_error_status_raises_system_one_error(monkeypatch):
    import httpx

    system_one.configure({"api_base": "http://decide.test:8000", "max_retries": 0})

    _fake_httpx_client(
        monkeypatch,
        {"count": 0},
        [httpx.Response(422, json={"detail": "missing field: questions"})],
    )

    with pytest.raises(system_one.SystemOneError) as excinfo:
        await system_one.judge(state="x", instructions="y?")

    assert excinfo.value.status_code == 422
    assert "missing field" in str(excinfo.value)


def _fake_httpx_client(monkeypatch, seen, responses):
    """Replace the client's AsyncClient with one that replays *responses* in order.

    SystemOneClient imports its http module through :mod:`cecli.http`, which
    resolves to ``httpx2`` when the installed mcp SDK is >= 2, so patch that
    module rather than plain ``httpx``.
    """

    from cecli.http import httpx as client_httpx

    class FakeClient:
        def __init__(self, *args, **kwargs):
            seen.setdefault("init", kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            seen["url"] = url
            seen["json"] = json
            seen["headers"] = headers
            seen["count"] = seen.get("count", 0) + 1

            return responses.pop(0)

    monkeypatch.setattr(client_httpx, "AsyncClient", FakeClient)

    return FakeClient


# --------------------------------------------------------------------------
# hook helper


async def test_hook_helper_questions_form_returns_dicts(transport):
    transport.reply(_noul_body("is_urgent"))

    result = await HookHelpers.system_one(
        Coder(),
        state="Help! My payouts have been failing for 3 days.",
        questions={"is_urgent": "Does this convey urgency?"},
    )

    assert result == {
        "model": "von-1.3.0",
        "usage": {"input_tokens": 296, "output_tokens": 20},
        "answers": {"is_urgent": {"type": "noul", "noul": 0.95, "yes": True}},
    }


async def test_hook_helper_decide_form(transport):
    transport.reply(_choice_body())

    result = await HookHelpers.system_one(
        Coder(),
        state="Database replication lag exceeded 45 seconds.",
        decide={
            "choices": {"infrastructure": "Hardware or network", "billing": "Invoices"},
            "instructions": "Classify the root cause domain.",
        },
    )

    decision = result["answers"]["decision"]

    assert decision["type"] == "choice"
    assert decision["choice"] == "billing"
    assert decision["confidence"] == 0.81
    assert transport.payloads[0]["questions"]["decision"]["type"] == "choice"


async def test_hook_helper_judge_and_rate_forms(transport):
    transport.reply(_noul_body("judgment"))
    transport.reply(_score_body())

    judged = await HookHelpers.system_one(
        Coder(),
        state="x",
        judge={"instructions": "Blocking?", "criteria": {"true": "yes means blocking"}},
    )
    rated = await HookHelpers.system_one(
        Coder(), state="x", rate={"levels": ["Low", "High"], "instructions": "Severity?"}
    )

    assert judged["answers"]["judgment"]["type"] == "noul"
    assert rated["answers"]["rating"]["type"] == "score"
    assert rated["answers"]["rating"]["score"] == 1.05
    assert transport.payloads[1]["questions"]["rating"]["criteria"] == ["Low", "High"]


async def test_hook_helper_rate_accepts_a_bare_level_list(transport):
    transport.reply(_score_body())

    await HookHelpers.system_one(Coder(), state="x", rate=["Nominal", "Degraded", "Critical"])

    assert transport.payloads[0]["questions"]["rating"]["criteria"] == [
        "Nominal",
        "Degraded",
        "Critical",
    ]


async def test_hook_helper_defaults_state_to_the_conversation(transport, monkeypatch):
    transport.reply(_noul_body("judgment"))

    messages = [{"role": "user", "content": "payouts are failing"}]
    monkeypatch.setattr(HookHelpers, "get_messages", staticmethod(lambda coder, last_n: messages))

    await HookHelpers.system_one(Coder(), judge="Urgent?")

    assert transport.payloads[0]["state"] == messages


async def test_hook_helper_requires_exactly_one_form(transport):
    with pytest.raises(ValueError, match="exactly one of"):
        await HookHelpers.system_one(Coder(), state="x")

    with pytest.raises(ValueError, match="exactly one of"):
        await HookHelpers.system_one(Coder(), state="x", judge="a?", decide={"choices": ["a"]})


async def test_hook_helper_rejects_a_bad_question_value(transport):
    with pytest.raises(TypeError, match="must be a dict or instructions string"):
        await HookHelpers.system_one(Coder(), state="x", questions={"bad": 17})


# --------------------------------------------------------------------------
# integrations: the shorthand vocabulary subsystems call through


def test_build_questions_maps_each_form_to_the_wire_format():
    from cecli.helpers.system_one import integrations

    assert integrations.build_questions(questions={"a": system_one.noul("q?")}) == {
        "a": {"type": "noul", "instructions": "q?"}
    }
    assert integrations.build_questions(decide={"choices": {"x": "X"}}) == {
        "decision": {
            "type": "choice",
            "instructions": integrations.DEFAULT_DECIDE_INSTRUCTIONS,
            "criteria": {"x": "X"},
        }
    }
    assert integrations.build_questions(judge="blocking?") == {
        "judgment": {"type": "noul", "instructions": "blocking?"}
    }
    assert integrations.build_questions(rate=["Low", "High"]) == {
        "rating": {
            "type": "score",
            "instructions": integrations.DEFAULT_RATE_INSTRUCTIONS,
            "criteria": ["Low", "High"],
        }
    }


def test_build_questions_expands_string_shorthands():
    from cecli.helpers.system_one import integrations

    built = integrations.build_questions(questions={"is_urgent": "Urgent?"})

    assert built == {"is_urgent": {"type": "noul", "instructions": "Urgent?"}}


def test_build_questions_drops_unrecognized_judge_criteria():
    from cecli.helpers.system_one import integrations

    built = integrations.build_questions(
        judge={"instructions": "y?", "criteria": {"true": "a", "maybe": "b"}}
    )

    assert built["judgment"]["criteria"] == {"true": "a"}


def test_build_questions_requires_exactly_one_form():
    from cecli.helpers.system_one import integrations

    with pytest.raises(ValueError, match="exactly one of"):
        integrations.build_questions()

    with pytest.raises(ValueError, match="exactly one of"):
        integrations.build_questions(judge="a?", decide=["a", "b"])


def test_build_questions_rejects_a_bad_question_value():
    from cecli.helpers.system_one import integrations

    with pytest.raises(TypeError, match="must be a dict or instructions string"):
        integrations.build_questions(questions={"bad": 17})


async def test_evaluate_returns_plain_dicts(transport):
    from cecli.helpers.system_one import integrations

    transport.reply(_choice_body())

    result = await integrations.evaluate("some state", decide={"choices": ["a", "b"]})

    assert isinstance(result, dict)
    assert set(result) == {"model", "usage", "answers"}
    assert result["answers"]["decision"]["type"] == "choice"
    assert isinstance(result["answers"]["decision"]["probabilities"], dict)


# --------------------------------------------------------------------------
# --system-one / config-file plumbing


def _resolve_system_one_arg(tmp_path, file_config, cli_json):
    """Replicate the config-file -> parser -> deep-merge path main_async uses."""
    conf = tmp_path / ".cecli.conf.yml"
    conf.write_text("system-one: |\n  " + json.dumps(file_config) + "\n")
    paths = [str(conf)]
    merged_config = config_utils.read_and_merge_all_configs(paths, [], paths)

    fd, tmp = tempfile.mkstemp(suffix=".yml", prefix="cecli_merged_")
    os.close(fd)
    with open(tmp, "w") as handle:
        yaml.dump(merged_config, handle)

    try:
        parser = get_parser([tmp], None)
        argv = [f"--system-one={cli_json}"] if cli_json else []
        args, _ = parser.parse_known_args(argv)
    finally:
        os.unlink(tmp)

    return convert_yaml_to_json_string(args.system_one, merged_config.get("system-one"))


def test_config_file_supplies_the_endpoint(tmp_path):
    resolved = _resolve_system_one_arg(
        tmp_path,
        {"api_base": "http://file-host:8000", "model_name": "von-1.3.0"},
        None,
    )

    assert system_one.configure(json.loads(resolved)) is not None
    config = system_one.get_config()

    assert config.api_base == "http://file-host:8000"
    assert config.model_name == "von-1.3.0"


def test_cli_system_one_deep_merges_over_the_config_file(tmp_path):
    resolved = _resolve_system_one_arg(
        tmp_path,
        {"api_base": "http://file-host:8000", "api_key_env": ["FILE_KEY"]},
        json.dumps({"api_base": "http://cli-host:9000"}),
    )

    assert system_one.configure(json.loads(resolved)) is not None
    config = system_one.get_config()

    assert config.api_base == "http://cli-host:9000"  # CLI wins per key
    assert config.api_key_env == ["FILE_KEY"]  # file-only key preserved


def test_extra_headers_survive_the_config_round_trip(tmp_path):
    resolved = _resolve_system_one_arg(
        tmp_path,
        {"api_base": "http://h:1", "extra_headers": {"optional": "a"}},
        json.dumps({"extra_headers": {"optional2": "b"}}),
    )

    system_one.configure(json.loads(resolved))

    assert system_one.get_config().extra_headers == {"optional": "a", "optional2": "b"}
