"""Tests for per-step workflow ``post_run`` hooks."""

from types import SimpleNamespace

import pytest

from cecli.helpers.workflows.hooks import WorkflowRunContext, run_task_hooks
from cecli.helpers.workflows.models import WorkflowConfig

STEPS = {"start": "start prompt", "fix": "fix prompt"}


async def jump_to_fix(coder, context):
    return context.jump("fix", "only this prompt")


def stop_run(coder, context):
    return context.stop()


def return_tuple(coder, context):
    return ("fix", "tuple prompt")


def continue_run(coder, context):
    return True


def _context(post_run, step_name="start", status="ok", error=None):
    task = SimpleNamespace(post_run=post_run)
    workflow = WorkflowConfig(name="demo", tasks=[])
    return WorkflowRunContext(
        coder=SimpleNamespace(root="/tmp"),
        workflow=workflow,
        task=task,
        steps=dict(STEPS),
        step_name=step_name,
        prompt=STEPS[step_name],
        status=status,
        error=error,
    )


def test_jump_sets_directive_and_returns_true():
    context = _context(jump_to_fix)

    assert context.jump("fix", "new") is True
    assert context.directive == ("fix", "new")


def test_stop_sets_false_directive():
    context = _context(stop_run)

    assert context.stop() is False
    assert context.directive is False


def test_available_steps_is_a_copy():
    context = _context(None)

    available = context.available_steps
    available["start"] = "changed"

    assert context.steps["start"] == "start prompt"
    assert context.available_steps == STEPS


@pytest.mark.asyncio
async def test_string_hook_resolves_and_jumps():
    context = _context(f"{__name__}:jump_to_fix")

    result = await run_task_hooks(context.coder, context)

    assert result == ("fix", "only this prompt")
    assert context.directive == ("fix", "only this prompt")


@pytest.mark.asyncio
async def test_hook_can_return_a_tuple_directly():
    context = _context(return_tuple)

    assert await run_task_hooks(context.coder, context) == ("fix", "tuple prompt")


@pytest.mark.asyncio
async def test_false_stops_the_run():
    context = _context(stop_run)

    assert await run_task_hooks(context.coder, context) is False


@pytest.mark.asyncio
async def test_true_continues():
    context = _context(continue_run)

    assert await run_task_hooks(context.coder, context) is None


@pytest.mark.asyncio
async def test_no_hook_continues():
    context = _context(None)

    assert await run_task_hooks(context.coder, context) is None


def test_task_level_post_run_is_parsed_from_yaml_shape():
    wf = WorkflowConfig.from_dict(
        {
            "name": "demo",
            "tasks": [
                {
                    "name": "start",
                    "prompt": "go",
                    "post_run": "mod:fn",
                }
            ],
        }
    )

    assert wf.tasks[0].post_run == "mod:fn"
    assert wf.to_dict()["tasks"][0]["post_run"] == "mod:fn"


def test_single_post_run_entry_is_not_a_list():
    wf = WorkflowConfig.from_dict(
        {"name": "demo", "tasks": [{"prompt": "go", "post_run": "mod:fn"}]}
    )

    assert wf.tasks[0].post_run == "mod:fn"


@pytest.mark.asyncio
async def test_python_file_with_post_run_method(tmp_path):
    hook_file = tmp_path / "hooks.py"
    hook_file.write_text(
        "async def post_run(coder, context):\n" '    return context.jump("fix", "from file")\n',
        encoding="utf-8",
    )
    context = _context(str(hook_file))

    assert await run_task_hooks(context.coder, context) == ("fix", "from file")


@pytest.mark.asyncio
async def test_inline_python_definition():
    context = _context("""
async def post_run(coder, context):
    return context.jump("fix", "inline def")
""")

    assert await run_task_hooks(context.coder, context) == ("fix", "inline def")


@pytest.mark.asyncio
async def test_inline_python_body():
    context = _context("""
if context.status == "error":
    return context.jump("fix", "inline body")

return True
""")

    assert await run_task_hooks(context.coder, context) is None

    context.status = "error"
    assert await run_task_hooks(context.coder, context) == ("fix", "inline body")


@pytest.mark.asyncio
async def test_bare_method_name_is_not_resolved():
    context = _context("jump_to_fix")

    assert await run_task_hooks(context.coder, context) is None
