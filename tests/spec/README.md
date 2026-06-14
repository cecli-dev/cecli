# cecli.spec tests

Standalone unit tests for the spec-driven development stack (`cecli/spec/`):
EARS lint/index/trace, workspace todos, generate/refine prompts, implement focus,
agent todo linking, and job types.

**No BrightVision or HTTP dependencies** — safe to run from the cecli repo alone.

## Run

From BrightVision root (recommended — uses repo `.venv`):

```bash
source activate.sh
pip install -e cecli
python -m pytest cecli/tests/spec/ -q
```

From cecli submodule root:

```bash
pip install -e .
python -m pytest tests/spec/ -q
```

Parent repo gate (unit + HTTP integration):

```bash
yarn verify:ears
```

## Layout

| File | Covers |
|------|--------|
| `test_spec_package.py` | Import smoke, no `bright_vision_core` imports |
| `test_ears_*.py` | Lint, index, trace, repair, report, prompt |
| `test_workspace_*.py` | Paths + todos persistence |
| `test_todo_*.py` | Markdown, phased generate, EARS in prompts |
| `test_spec_*.py` | Layers, steering, focus, gen agent, jobs, debug |
| `test_agent_todos.py` | Agent todo.txt ↔ workspace tasks |
| `test_implement_workspace.py` | Implement-step blocks |
