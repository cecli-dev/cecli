# flake8: noqa: E501
"""
LLM-assisted three-layer todo spec generation and parsing.
"""

from __future__ import annotations

import os
import re
from typing import Literal

from cecli.spec.ears.prompt import format_spec_quality_for_prompt
from cecli.spec.todos import TodoItem

GenerateMode = Literal["generate", "refine"]
SpecSection = Literal["all", "requirements", "design", "tasks_md"]

_SECTION_HEADERS = {
    "## requirements": "requirements",
    "## design": "design",
    "## implementation tasks": "tasks_md",
    "## tasks": "tasks_md",
    "## implementation plan": "tasks_md",
    "## implementation steps": "tasks_md",
}

_DEEPEN_PASS_MARKER = "--- deepen pass ---"

# --- Kiro-style layer guidance (no curly braces: these are concatenated into
# --- .format() templates, so any "{" would be parsed as a field). ---

_REQUIREMENTS_FORMAT = """\
Write thorough, professional, Kiro-style requirements. Favor completeness over brevity — this is the contract the design and implementation are built against.
- Begin with a `### Introduction` section: 2–4 sentences describing the feature, who uses it, the problem it solves, and its scope and boundaries.
- Add one `### REQ-NNN: <title>` section per requirement, with a unique zero-padded id (REQ-001, REQ-002, …) and a short descriptive title.
- Under each requirement, write a `**User Story:** As a <role>, I want <capability>, so that <benefit>.` line. Use a concrete role (not just "user") whenever the feature implies one, and state a real benefit.
- Follow it with an `**Acceptance Criteria**` numbered list of EARS clauses. Each clause is a complete sentence using **THE** system **SHALL** with a trigger: **WHEN** <event>, **IF** <condition> **THEN**, **WHILE** <state>, or **WHERE** <feature> — or a ubiquitous **THE** system **SHALL** statement.
- Give every requirement at least two acceptance criteria. Across the whole document, deliberately cover the happy path, boundary and edge cases, invalid input and error handling, and the relevant non-functional needs (performance, security, privacy, accessibility, observability).
- Decompose broad features into at least three focused, independently testable requirements rather than one catch-all. Only a genuinely trivial feature should have fewer.
- Be specific and unambiguous: name concrete states, events, values, and limits instead of vague phrases like "handle errors", "fast", or "as needed".
"""

_DESIGN_FORMAT = """\
Be comprehensive and concrete — this is the technical blueprint an engineer implements directly from, so include enough detail that no major decision is left implicit. Use these level-3 (###) subsections:
- `### Overview` — what is being built and why, tied to the requirements; summarize the chosen approach and the key technical decisions and trade-offs.
- `### Architecture` — the major pieces and how requests and data flow between them; include a Mermaid or ASCII diagram when it clarifies the structure.
- `### Components and Interfaces` — each component, its single responsibility, and the key function/method/endpoint signatures (names, parameters, return types).
- `### Data Models` — important types and their fields, validation rules, and how they are persisted or transmitted.
- `### Error Handling` — the failure modes, how the system detects them, and both the user-visible and internal responses.
- `### Testing Strategy` — unit, integration, and end-to-end coverage, plus the edge cases and non-functional checks that need dedicated tests.
Ground the design in this repository: reference concrete modules, files, and existing patterns rather than inventing greenfield structure. Cite the REQ ids each component or decision satisfies (e.g. REQ-001), and make sure every requirement is covered by some part of the design.
"""

_TASKS_FORMAT = """\
Break the work into incremental, test-driven coding steps a developer can execute top to bottom:
- Use a numbered checklist (`- [ ] 1.`, `- [ ] 2.`, …); add sub-steps (1.1, 1.2) to decompose larger steps.
- Each step is a concrete, actionable coding task — write or modify specific code or tests — not project management, deployment, or manual QA.
- Keep each step small enough to complete and verify on its own, and sequence them so every step builds only on earlier ones (no forward references).
- Pair implementation steps with the tests that cover them; prefer writing or updating tests alongside or before the code.
- End each step with the requirement ids it implements (e.g. `_Requirements: REQ-001, REQ-002_`) and a `(depends: none|N)` marker.
- Cover every requirement and every major design component with at least one task; do not leave parts of the design unimplemented.
"""

# Shorter prompts for LLM e2e / dogfood on small Ollama models (BV_COMPACT_SPEC_GEN=1).
# Product UI keeps full Kiro-grade prompts unless the env is set.
_REQUIREMENTS_FORMAT_COMPACT = """\
Write concise requirements only:
- `### Introduction` — 2-3 sentences.
- Exactly **two** `### REQ-NNN` sections; each with one short **User Story** and **two** numbered acceptance lines.
- Every acceptance line MUST include both **WHEN** and **THE** system **SHALL** (copy the example shape exactly).
"""

_REQUIREMENTS_EXAMPLE_COMPACT = """\
Format example (replace feature text; keep the EARS shape):

### Introduction
Clients need a minimal health check before pairing.

### REQ-001: Liveness
**User Story:** As a client, I want a health endpoint, so that I can detect uptime.

**Acceptance Criteria**
1. **WHEN** a client sends `GET /health` **THE** system **SHALL** respond with HTTP 200 and a JSON status field.
2. **WHEN** the core is starting **THE** system **SHALL** respond with HTTP 503 until ready.

### REQ-002: Payload
**User Story:** As a client, I want a stable body shape, so that parsers do not break.

**Acceptance Criteria**
1. **WHEN** the health endpoint returns 200 **THE** system **SHALL** include a `status` string in the JSON body.
2. **WHEN** the status is ok **THE** system **SHALL** use the literal value `ok`.
"""

_DESIGN_FORMAT_COMPACT = """\
Keep the design under 35 lines. Use only these subsections:
- `### Overview` — 2-4 sentences citing REQ ids.
- `### Architecture` — a short bullet list citing REQ ids.
Do not add Components, Data Models, Error Handling, or Testing Strategy sections.
"""

_TASKS_FORMAT_COMPACT = """\
Exactly **two** numbered checklist items with `(depends: none|1)`; cite REQ ids in each line.
"""


def compact_spec_gen_enabled() -> bool:
    """True when LLM lanes should use shorter generate-spec prompts (faster 3b runs)."""
    return os.environ.get("BV_COMPACT_SPEC_GEN", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _requirements_format() -> str:
    return _REQUIREMENTS_FORMAT_COMPACT if compact_spec_gen_enabled() else _REQUIREMENTS_FORMAT


def _requirements_example() -> str:
    return _REQUIREMENTS_EXAMPLE_COMPACT if compact_spec_gen_enabled() else _REQUIREMENTS_EXAMPLE


def _design_format() -> str:
    return _DESIGN_FORMAT_COMPACT if compact_spec_gen_enabled() else _DESIGN_FORMAT


def _tasks_format() -> str:
    return _TASKS_FORMAT_COMPACT if compact_spec_gen_enabled() else _TASKS_FORMAT


def _design_example() -> str:
    return _DESIGN_EXAMPLE_COMPACT if compact_spec_gen_enabled() else _DESIGN_EXAMPLE


def _generate_all_layers_body() -> str:
    return (
        "## Requirements\n" + _requirements_format() + "\n"
        "## Design\n" + _design_format() + "\n"
        "## Implementation tasks\n" + _tasks_format() + "\n" + _ALL_EXAMPLE
    )


_REQUIREMENTS_EXAMPLE = """\
Format example (replace with the real feature; do not copy this content):

### Introduction
The health endpoint lets clients confirm the API is reachable before pairing.

### REQ-001: Health check
**User Story:** As a client app, I want a health endpoint, so that I can confirm the API is up.

**Acceptance Criteria**
1. **WHEN** a client sends `GET /health` **THE** system **SHALL** respond with HTTP 200 and a JSON status body.
2. **IF** the core is still starting **THEN THE** system **SHALL** respond with HTTP 503 and a retry hint.
"""

_DESIGN_EXAMPLE = """\
Format example (structure only):

### Overview
Implements REQ-001 as an HTTP route.
### Architecture
FastAPI app -> health handler -> status payload.
### Components and Interfaces
- `health()` returns the status payload — REQ-001.
### Data Models
A Status value with an "ok" boolean field.
### Error Handling
Return HTTP 503 while the core is starting (REQ-001).
### Testing Strategy
An HTTP test asserts 200 and a JSON body for REQ-001.
"""

_DESIGN_EXAMPLE_COMPACT = """\
Format example (structure only):

### Overview
Implements REQ-001 as an HTTP route (REQ-001).
### Architecture
- FastAPI route `GET /health` — REQ-001.
"""

_TASKS_EXAMPLE = """\
Format example:

- [ ] 1. Add the health route and status payload — _Requirements: REQ-001_ (depends: none)
  - [ ] 1.1 Return HTTP 503 while the core is starting (depends: none)
- [ ] 2. Add an HTTP test asserting 200 and a JSON body — _Requirements: REQ-001_ (depends: 1)
"""

_TASKS_EXAMPLE_COMPACT = """\
Format example (copy this shape exactly):

- [ ] 1. Add the health route — _Requirements: REQ-001_ (depends: none)
- [ ] 2. Add an HTTP test — _Requirements: REQ-001_ (depends: 1)
"""


def _tasks_example() -> str:
    return _TASKS_EXAMPLE_COMPACT if compact_spec_gen_enabled() else _TASKS_EXAMPLE


_ALL_EXAMPLE = """\
Format example (structure only; replace with the real feature):

## Requirements
### Introduction
The health endpoint lets clients confirm the API is reachable.

### REQ-001: Health check
**User Story:** As a client, I want a health endpoint, so that I can confirm the API is up.

**Acceptance Criteria**
1. **WHEN** a client sends `GET /health` **THE** system **SHALL** respond with HTTP 200 and a JSON status.
2. **IF** the core is still starting **THEN THE** system **SHALL** respond with HTTP 503.

## Design
### Overview
Implements REQ-001 as an HTTP route.
### Architecture
FastAPI app -> health handler -> status payload.
### Components and Interfaces
- `health()` returns the status payload — REQ-001.
### Data Models
A Status value with an "ok" boolean field.
### Error Handling
Return HTTP 503 while starting (REQ-001).
### Testing Strategy
An HTTP test asserts 200 for REQ-001.

## Implementation tasks
- [ ] 1. Add the health route — _Requirements: REQ-001_ (depends: none)
- [ ] 2. Add an HTTP test for the route — _Requirements: REQ-001_ (depends: 1)
"""

_GENERATE_TEMPLATE_PREFIX = (
    "You are a senior software architect writing a complete, production-grade spec-driven "
    "development plan for this repository. Do not edit any files.\n\n"
    "Feature request:\n{prompt}\n\n"
    "{existing}{ears_context}\n\n"
    "{depth}"
    "Respond with markdown only. Use exactly these three level-2 (##) headings and no other "
    "level-2 headings; use level-3 (###) for every subsection:\n\n"
)

_REQUIREMENTS_SECTION_PREFIX = (
    "You are a senior product engineer writing the requirements layer for a spec-driven task. "
    "Do not edit any files.\n\n"
    "Feature request:\n{prompt}\n\n"
    "{existing_requirements}{ears_context}\n\n"
    "{depth}"
    "Respond with markdown only, under a single level-2 heading:\n\n"
    "## Requirements\n"
)

_DESIGN_SECTION_PREFIX = (
    "You are a senior software architect writing the design layer for a spec-driven task. "
    "Do not edit any files.\n\n"
    "Task title: {title}\n\n"
    "## Requirements (approved — the design must satisfy every REQ id)\n{requirements}\n\n"
    "Design note:\n{prompt}\n\n"
    "{existing_design}{ears_context}\n\n"
    "{depth}"
    "Respond with markdown only, under a single level-2 heading:\n\n"
    "## Design\n"
)

_TASKS_SECTION_PREFIX = (
    "You are a senior engineer writing the implementation tasks layer for a spec-driven task. "
    "Do not edit any files.\n\n"
    "Task title: {title}\n\n"
    "## Requirements\n{requirements}\n\n"
    "## Design\n{design}\n\n"
    "Implementation note:\n{prompt}\n\n"
    "{existing_tasks}{ears_context}\n\n"
    "{depth}"
    "Respond with markdown only, under a single level-2 heading:\n\n"
    "## Implementation tasks\n"
)

_REFINE_TEMPLATE_PREFIX = (
    "You are a senior reviewer improving a spec-driven task to production grade. "
    "Do not edit any files.\n\n"
    "Task title: {title}\n\n"
    "## Requirements\n{requirements}\n\n"
    "## Design\n{design}\n\n"
    "## Implementation tasks\n{tasks_md}\n\n"
    "User note: {prompt}\n{ears_context}\n\n"
    "Output an improved version with the same three level-2 (##) headings "
    "(## Requirements, ## Design, ## Implementation tasks). {refine_depth}Follow this structure:\n\n"
)

# Thoroughness framing — added only in full (non-compact) mode. In compact mode these
# verbose instructions confuse small local models (e.g. llama3.2:3b) into emitting prose
# instead of the tight structure the compact format demands.
_GENERATE_DEPTH = (
    "Think carefully about the real problem behind the request, the users involved, the edge "
    "cases, and how this fits the existing codebase, then write a thorough plan — not a "
    "skeleton. Prefer completeness and precise wording over brevity; do not omit a section "
    "because the request is short.\n\n"
)
_REQUIREMENTS_DEPTH = (
    "Infer the unstated needs behind the request — the roles involved, the edge cases, the "
    "error and non-functional concerns — and capture them explicitly. Write a thorough, "
    "precisely worded set of requirements rather than a minimal one.\n\n"
)
_DESIGN_DEPTH = (
    "Produce a concrete, implementation-ready design grounded in this repository's real modules "
    "and patterns. Be thorough: explain the approach and trade-offs, not just the structure.\n\n"
)
_TASKS_DEPTH = (
    "Produce a complete, ordered plan that covers every requirement and design component as "
    "incremental, test-driven coding steps. Be thorough rather than high-level.\n\n"
)
_REFINE_DEPTH = (
    "Deepen every thin or vague section with concrete detail, sharpen weak wording, add missing "
    "edge cases and non-functional requirements, fix contradictions between layers, ensure every "
    "REQ id is covered by the design and tasks, and resolve every EARS issue listed above. Do "
    "not drop or weaken any content that is already strong. "
)
# Compact refine still needs the EARS-fix instruction (the gate enforces it) but stays terse.
_REFINE_DEPTH_COMPACT = (
    "Fix contradictions between layers, ensure every REQ id is covered, and resolve every EARS "
    "issue listed above. "
)


def _generate_depth() -> str:
    return "" if compact_spec_gen_enabled() else _GENERATE_DEPTH


def _requirements_depth() -> str:
    return "" if compact_spec_gen_enabled() else _REQUIREMENTS_DEPTH


def _design_depth() -> str:
    return "" if compact_spec_gen_enabled() else _DESIGN_DEPTH


def _tasks_depth() -> str:
    return "" if compact_spec_gen_enabled() else _TASKS_DEPTH


def _refine_depth() -> str:
    return _REFINE_DEPTH_COMPACT if compact_spec_gen_enabled() else _REFINE_DEPTH


def _optional_existing_block(label: str, text: str) -> str:
    body = (text or "").strip()
    if not body:
        return ""
    return f"Existing {label} (improve and extend):\n{body}\n\n"


def build_generate_message(
    prompt: str,
    *,
    mode: GenerateMode = "generate",
    item: TodoItem | None = None,
    section: SpecSection = "all",
) -> str:
    ears_context = ""
    if item and (mode == "refine" or section in ("all", "requirements")):
        ears_context = format_spec_quality_for_prompt(
            item.requirements,
            item.design,
            item.tasks_md,
        )
    if mode == "refine" and item:
        return _REFINE_TEMPLATE_PREFIX.format(
            title=item.title,
            requirements=item.requirements.strip() or "(empty)",
            design=item.design.strip() or "(empty)",
            tasks_md=item.tasks_md.strip() or "(empty)",
            prompt=prompt.strip() or "Review for consistency.",
            ears_context=ears_context,
            refine_depth=_refine_depth(),
        ) + (_requirements_format() + "\n" + _design_format() + "\n" + _tasks_format())
    if section == "requirements":
        existing = _optional_existing_block(
            "requirements draft",
            item.requirements if item else "",
        )
        return _REQUIREMENTS_SECTION_PREFIX.format(
            prompt=prompt.strip(),
            existing_requirements=existing,
            ears_context=ears_context,
            depth=_requirements_depth(),
        ) + (_requirements_format() + "\n" + _requirements_example())
    if section == "design" and item:
        return _DESIGN_SECTION_PREFIX.format(
            title=item.title,
            requirements=item.requirements.strip() or "(empty)",
            prompt=prompt.strip(),
            existing_design=_optional_existing_block("design draft", item.design),
            ears_context=ears_context,
            depth=_design_depth(),
        ) + (_design_format() + "\n" + _design_example())
    if section == "tasks_md" and item:
        return _TASKS_SECTION_PREFIX.format(
            title=item.title,
            requirements=item.requirements.strip() or "(empty)",
            design=item.design.strip() or "(empty)",
            prompt=prompt.strip(),
            existing_tasks=_optional_existing_block("implementation tasks draft", item.tasks_md),
            ears_context=ears_context,
            depth=_tasks_depth(),
        ) + (_tasks_format() + "\n" + _tasks_example())
    existing = ""
    if item and (item.requirements or item.design or item.tasks_md):
        existing = (
            "Existing draft (improve and extend):\n"
            f"Requirements:\n{item.requirements}\n\n"
            f"Design:\n{item.design}\n\n"
            f"Implementation tasks:\n{item.tasks_md}\n"
        )
    return (
        _GENERATE_TEMPLATE_PREFIX.format(
            prompt=prompt.strip(),
            existing=existing,
            ears_context=ears_context,
            depth=_generate_depth(),
        )
        + _generate_all_layers_body()
    )


def _parse_generated_layers_once(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {k: [] for k in ("requirements", "design", "tasks_md")}
    current: str | None = None

    for line in text.replace("\r\n", "\n").split("\n"):
        key = _SECTION_HEADERS.get(line.strip().lower())
        if key:
            current = key
            continue
        if current:
            sections[current].append(line)

    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _merge_parsed_layers(
    base: dict[str, str],
    overlay: dict[str, str],
) -> dict[str, str]:
    out = dict(base)
    for key, value in overlay.items():
        if (value or "").strip():
            out[key] = value
    return out


def parse_generated_layers(text: str, *, section: SpecSection = "all") -> dict[str, str]:
    """Extract requirements, design, and tasks_md from model markdown."""
    raw = (text or "").replace("\r\n", "\n")
    if _DEEPEN_PASS_MARKER in raw:
        head, _, tail = raw.partition(_DEEPEN_PASS_MARKER)
        out = _merge_parsed_layers(
            _parse_generated_layers_once(head),
            _parse_generated_layers_once(tail),
        )
    else:
        out = _parse_generated_layers_once(raw)

    if not any(out.values()):
        cleaned = _strip_fences(raw)
        if cleaned:
            if section == "design":
                out["design"] = cleaned
            elif section == "tasks_md":
                out["tasks_md"] = cleaned
            else:
                out["requirements"] = cleaned
    elif section == "tasks_md" and not (out.get("tasks_md") or "").strip():
        cleaned = _strip_fences(raw)
        if cleaned and re.search(r"(?m)^\s*(?:-\s*\[[ xX]\]\s*)?\d+\.", cleaned):
            out["tasks_md"] = cleaned
    return out


def merge_generated_layers(
    item: TodoItem,
    parsed: dict[str, str],
    *,
    section: SpecSection,
) -> dict[str, str]:
    """Merge parsed output with stored layers for phased apply."""
    if section == "all":
        return {
            "requirements": parsed.get("requirements", "") or item.requirements,
            "design": parsed.get("design", "") or item.design,
            "tasks_md": parsed.get("tasks_md", "") or item.tasks_md,
        }
    if section == "requirements":
        return {
            "requirements": parsed.get("requirements", "") or item.requirements,
            "design": item.design,
            "tasks_md": item.tasks_md,
        }
    if section == "design":
        return {
            "requirements": item.requirements,
            "design": parsed.get("design", "") or item.design,
            "tasks_md": item.tasks_md,
        }
    return {
        "requirements": item.requirements,
        "design": item.design,
        "tasks_md": parsed.get("tasks_md", "") or item.tasks_md,
    }


def validate_section_prerequisites(item: TodoItem, section: SpecSection) -> None:
    if section == "design" and not item.requirements.strip():
        raise ValueError("Generate requirements before design")
    if section == "tasks_md":
        if not item.requirements.strip():
            raise ValueError("Generate requirements before implementation tasks")
        if not item.design.strip():
            raise ValueError("Generate design before implementation tasks")


def _strip_fences(text: str) -> str:
    t = text.strip()
    m = re.match(r"^```(?:markdown|md)?\s*\n(.*)\n```\s*$", t, re.DOTALL | re.I)
    return m.group(1).strip() if m else t
