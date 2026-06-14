"""Shared assertions for three-layer spec generation (pytest + LLM e2e)."""

from __future__ import annotations

from cecli.spec.layers import (
    assess_generated_spec_layers,
    design_references_requirements,
)

__all__ = [
    "SAMPLE_GENERATED_MARKDOWN",
    "assess_generated_spec_layers",
    "design_references_requirements",
]

SAMPLE_GENERATED_MARKDOWN = """\
## Requirements
### Introduction
A ping counter API exposes a health check and an increment endpoint for dogfooding.

### REQ-001: Health check
**User Story:** As a client, I want a health endpoint, so that I can confirm the API is reachable.

**Acceptance Criteria**
1. **WHEN** a client sends `GET /health` **THE** system **SHALL** respond with HTTP 200 and a JSON status.
2. **IF** the core is still starting **THEN THE** system **SHALL** respond with HTTP 503.

### REQ-002: Increment counter
**User Story:** As a client, I want to increment a counter, so that I can verify state changes.

**Acceptance Criteria**
1. **WHEN** a client sends `POST /count` **THE** system **SHALL** increment and return the new value.
2. **WHILE** the process is running **THE** system **SHALL** persist the count in memory.

## Design
### Overview
REQ-001 maps to HTTP routes; REQ-002 uses an in-process store.
### Architecture
A FastAPI app routes /health and /count to handlers backed by a singleton counter.
### Components and Interfaces
- `health()` returns the status payload — REQ-001.
- `increment()` and the `Counter` store — REQ-002.
### Data Models
A Counter value with an integer "value" field, held in memory.
### Error Handling
Return HTTP 503 while starting (REQ-001); reject unknown methods with 405.
### Testing Strategy
Unit tests for the store plus HTTP tests for REQ-001 and REQ-002.

## Implementation tasks
- [ ] 1. Add route for REQ-001 health check — _Requirements: REQ-001_ (depends: none)
- [ ] 2. Wire counter store and route for REQ-002 — _Requirements: REQ-002_ (depends: 1)
- [ ] 3. Add HTTP tests for REQ-001 and REQ-002 (depends: 2)
"""
