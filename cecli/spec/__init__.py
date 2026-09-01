"""Spec-driven development: EARS, workspace todos, generate/refine, implement focus."""

from cecli.spec.ears import analyze_requirements, analyze_traceability, build_spec_index
from cecli.spec.jobs import SpecGenerationJob, spec_gen_timeout_s
from cecli.spec.progress import (
    ImplementationStep,
    implementation_steps,
    mark_implementation_step_done,
    materialize_checklist_from_tasks_md,
    merge_agent_progress_into_tasks_md,
    next_open_implementation_step,
    try_mark_focus_step_complete,
)
from cecli.spec.pubspec_repair import (
    PubspecRepairResult,
    find_missing_pubspec_dependencies,
    repair_pubspec_dependencies,
)

__all__ = [
    "ImplementationStep",
    "PubspecRepairResult",
    "SpecGenerationJob",
    "analyze_requirements",
    "analyze_traceability",
    "build_spec_index",
    "find_missing_pubspec_dependencies",
    "implementation_steps",
    "mark_implementation_step_done",
    "materialize_checklist_from_tasks_md",
    "merge_agent_progress_into_tasks_md",
    "next_open_implementation_step",
    "repair_pubspec_dependencies",
    "spec_gen_timeout_s",
    "try_mark_focus_step_complete",
]
