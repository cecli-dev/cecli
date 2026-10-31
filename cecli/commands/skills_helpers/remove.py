from cecli.commands.utils.helpers import format_command_result


async def cmd_remove(io, coder, args):
    """Remove one or more skills by name."""
    if not args.strip():
        io.tool_output("Usage: /skills remove <skill-name>")
        return format_command_result(io, "remove-skill", "Usage: /skills remove <skill-name>")

    skill_names = args.strip().split()

    if not hasattr(coder, "edit_format") or coder.edit_format not in ("agent", "subagent"):
        io.tool_output("Skill removal is only available in agent mode.")
        return format_command_result(
            io, "remove-skill", "Skill removal is only available in agent mode"
        )

    if not hasattr(coder, "skills_manager") or coder.skills_manager is None:
        io.tool_output("Skills manager is not initialized. Skills may not be configured.")
        if hasattr(coder, "skills_directory_paths") and not coder.skills_directory_paths:
            io.tool_output(
                "No skills directories configured. Use --skills-paths to configure skill"
                " directories."
            )
        return format_command_result(io, "remove-skill", "Skills manager is not initialized")

    results = []
    for skill_name in skill_names:
        result = coder.skills_manager.remove_skill(skill_name)
        results.append(result)

    return format_command_result(io, "remove-skill", "\n".join(results))


def get_completions(io, coder):
    """Get completion options for the remove subcommand."""
    if not hasattr(coder, "skills_manager") or coder.skills_manager is None:
        return []

    try:
        skills = coder.skills_manager.find_skills()
        return [skill.name for skill in skills]
    except Exception:
        return []
