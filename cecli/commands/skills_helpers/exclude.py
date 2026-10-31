from cecli.commands.utils.helpers import format_command_result


async def cmd_exclude(io, coder, args):
    """Exclude one or more skills by name, adding them to the blacklist."""
    if not args.strip():
        io.tool_output("Usage: /skills exclude <skill-name>")
        return format_command_result(io, "exclude-skill", "Usage: /skills exclude <skill-name>")

    skill_names = args.strip().split()

    if not hasattr(coder, "edit_format") or coder.edit_format not in ("agent", "subagent"):
        io.tool_output("Skill exclusion is only available in agent mode.")
        return format_command_result(
            io, "exclude-skill", "Skill exclusion is only available in agent mode"
        )

    if not hasattr(coder, "skills_manager") or coder.skills_manager is None:
        io.tool_output("Skills manager is not initialized. Skills may not be configured.")
        if hasattr(coder, "skills_directory_paths") and not coder.skills_directory_paths:
            io.tool_output(
                "No skills directories configured. Use --skills-paths to configure skill"
                " directories."
            )
        return format_command_result(io, "exclude-skill", "Skills manager is not initialized")

    results = []
    for skill_name in skill_names:
        result = coder.skills_manager.exclude_skill(skill_name)
        results.append(result)

    return format_command_result(io, "exclude-skill", "\n".join(results))


def get_completions(io, coder):
    """Get completion options for the exclude subcommand."""
    if not hasattr(coder, "skills_manager") or coder.skills_manager is None:
        return []

    try:
        skills = coder.skills_manager.find_skills()
        return [skill.name for skill in skills]
    except Exception:
        return []
