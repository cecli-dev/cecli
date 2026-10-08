---
parent: Configuration
nav_order: 46
description: Configure a System One decision endpoint for instant structured judgements.
---

# System One

A *System One* endpoint answers **typed questions** about a *state* in a single non-generative pass:
no tokens are streamed, and what comes back is a probability distribution rather than prose. It is
the fast, cheap complement to a chat model - routing, triage, gating, scoring and other "which one
of these?" decisions.

`cecli` speaks the `POST {api_base}/v1/systemone` wire format, so any server implementing it works:
a self-hosted decision server (`von serve`), a gateway, or a hosted evaluation API.

## Configuration

The endpoint is described with the same keys as a [model provider](model-providers.md), so
`system-one` reads like a slimmed-down `model-providers` entry:

| Key | Required | Default | Description |
|-----|----------|---------|-------------|
| `api_base` | No | `http://127.0.0.1:8000` | Base URL of the endpoint. A trailing `/v1` is accepted; `/systemone` is appended as needed. |
| `api_key_env` | No | `["SYSTEM_ONE_API_KEY"]` | Environment variable names to probe, in order, for the bearer token. The first non-empty one wins. |
| `model_name` | No | `von-latest` | Model name sent in every request body. |
| `extra_headers` | No | `{}` | Additional request headers, e.g. per-tenant routing or tracing headers. |
| `timeout` | No | `30` | Request timeout in seconds. |
| `max_retries` | No | `2` | Retries for `429`/`529` responses, with exponential backoff. |

In `~/.cecli/conf.yml` or `.cecli.conf.yml`:

```yaml
system-one:
  api_base: "http://127.0.0.1:8000"
  api_key_env:
    - "SYSTEM_ONE_API_KEY"
  model_name: "von-1.3.0"
  extra_headers:
    x-tenant: "acme"
```

Or on the command line as a JSON/YAML string:

```bash
cecli --system-one '{"api_base": "http://127.0.0.1:8000", "model_name": "von-1.3.0"}'
```

CLI values are deep-merged over the config file, so a `--system-one` flag overrides individual keys
without discarding the rest of the file's settings.

## Environment variables

With no configuration at all, only these variables are consulted. Nothing is probed for third-party
vendors: naming another environment variable or a remote endpoint is always an explicit
configuration choice, made with `api_base` and `api_key_env` above.

| Variable | Effect |
|----------|--------|
| `SYSTEM_ONE_API_BASE` | Overrides the default `api_base` of `http://127.0.0.1:8000`. |
| `SYSTEM_ONE_API_KEY` | Sent as `Authorization: Bearer <value>` when no key is found via `api_key_env`. |
| `SYSTEM_ONE_MODEL` | Overrides the default `model_name`. |

Configuration (CLI or config file) always wins over the environment for the keys it sets.

## Question types

Every request carries a `state` and a map of `questions`; the response returns one `answer` per
question under the same ids.

| Type | Question | Answer |
|------|----------|--------|
| `noul` | A yes/no question, optionally with `true`/`false` criteria. | `noul`: probability of yes (0.0 - 1.0). |
| `choice` | What to decide, plus a `criteria` map of option to description (up to 255 options). | `choice`, `probabilities`, `confidence`. |
| `score` | What to rate, plus an ordered `criteria` list of levels (2 - 10). | `score`, `legend`, `probabilities`, `confidence`. |

`instructions` and criteria values may be strings, objects or arrays, so a long question can carry
its own reference data and point at it by name in backticks.

## Using it from Python

The module mirrors the shape of the decision-model SDKs: one call per decision.

```python
import asyncio
from cecli.helpers import system_one

async def triage(message):
    owner = await system_one.decide(
        state=message,
        choices={"billing": "Payments, refunds", "technical": "Bugs, outages"},
        instructions="Which team should handle this?",
    )
    urgent = await system_one.judge(
        state=message,
        instructions="Does this need immediate attention?",
        criteria={"true": "Explicitly time-sensitive", "false": "No urgency"},
    )
    mood = await system_one.rate(
        state=message,
        levels=["Calm", "Frustrated", "Very angry"],
        instructions="How frustrated is the customer?",
    )

    return owner.choice, urgent.probability, mood.score
```

| Call | Returns |
|------|---------|
| `decide(state, choices, instructions)` | `ChoiceAnswer` - `.choice`, `.probabilities`, `.confidence` |
| `judge(state, instructions, criteria=None)` | `NoulAnswer` - `.probability`, `.yes` |
| `rate(state, levels, instructions)` | `ScoreAnswer` - `.score`, `.levels`, `.legend`, `.confidence` |
| `ask(state, questions)` | `SystemOneResponse` - `.answers`, `.model`, `.usage`, indexable by question id |

`system_one(state, questions)` is the same call as `ask`, named for parity with the `von` SDK.

Several questions over one state cost one request, built with the question helpers:

```python
response = await system_one.system_one(
    state={"ticket": "INC-4091", "message": "Gateway timeouts on authorizations."},
    questions={
        "intent": system_one.choice(
            "Nature of the ticket?", {"payment_failure": "Charges fail", "access_issue": "Login fails"}
        ),
        "is_urgent": system_one.noul("Needs immediate SLA intervention?"),
        "severity": system_one.score("Rate severity.", ["Low", "Medium", "High", "Critical"]),
    },
)

response["intent"].choice     # 'payment_failure'
response["is_urgent"].probability
response["severity"].score
response.to_dict()            # plain nested dicts
```

Anything other than `2xx` raises `system_one.SystemOneError` (with `.status_code` when the request
itself succeeded); `429` and `529` are retried first, per `max_retries`.

`cecli.helpers.system_one.integrations` holds the shorthand vocabulary on top of
these calls - `evaluate(state, questions=…, decide=…, judge=…, rate=…)` and its
`build_questions()` translator - so cecli's own subsystems stay one-liners. Use it
when you want dict results keyed by question id rather than typed answer objects.
itself succeeded); `429` and `529` are retried first, per `max_retries`.

## Hook helper

Python hooks get the same decisions through
[`HookHelpers.system_one()`](hooks.md#system_onecoder-statenone-questionsnone-decidenone-judgenone-ratenone-modelnone-last_n20),
which returns plain dicts and defaults its state to the recent conversation:

```python
from cecli.hooks import BaseHook, HookHelpers
from cecli.hooks.types import HookType

class TriageHook(BaseHook):
    type = HookType.POST_TOOL

    async def execute(self, coder, metadata):
        verdict = await HookHelpers.system_one(
            coder,
            state=metadata["output"],
            judge="Does this output contain a secret or credential?",
        )

        if verdict["answers"]["judgment"]["noul"] > 0.8:
            print("Redact before continuing")

        return True
```

## Notes

- **Describe the options.** A `judge` call without `criteria` is the weakest path; either say what
  yes and no mean, or phrase the decision as a described `choice`.
- **Act on confidence, not just the answer.** `confidence` is derived from the distribution, so a
  high-confidence `choice` can be acted on automatically while a low-confidence one should be
  escalated to a model or to the user.
- **Keep states small.** Long states are truncated by most servers; pass the record or the message
  that matters rather than the whole transcript.
