from cecli.commands.utils.helpers import format_command_result


async def cmd_load(io, coder, args):
    """Load one or more skills by name."""
    if not args.strip():
        io.tool_output("Usage: /skills load <skill-name>")
        return format_command_result(io, "load-skill", "Usage: /skills load <skill-name>")

    skill_names = args.strip().split()

    io.tool_output(coder.edit_format)
    if not hasattr(coder, "edit_format") or coder.edit_format not in ("agent", "subagent"):
        io.tool_output("Skill loading is only available in agent mode.")
        return format_command_result(
            io, "load-skill", "Skill loading is only available in agent mode"
        )

    if not hasattr(coder, "skills_manager") or coder.skills_manager is None:
        io.tool_output("Skills manager is not initialized. Skills may not be configured.")
        if hasattr(coder, "skills_directory_paths") and not coder.skills_directory_paths:
            io.tool_output(
                "No skills directories configured. Use --skills-paths to configure skill"
                " directories."
            )
        return format_command_result(io, "load-skill", "Skills manager is not initialized")

    results = []
    for skill_name in skill_names:
        result = coder.skills_manager.load_skill(skill_name)
        results.append(result)

    return format_command_result(io, "load-skill", "\n".join(results))


def get_completions(io, coder):
    """Get completion options for the load subcommand."""
    if not hasattr(coder, "skills_manager") or coder.skills_manager is None:
        return []

    try:
        skills = coder.skills_manager.find_skills()
        return [skill.name for skill in skills]
    except Exception:
        return []
