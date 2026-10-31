from cecli.commands.utils.helpers import format_command_result


async def cmd_list(io, coder):
    """List all available skills with their states and file paths."""
    if not hasattr(coder, "skills_manager") or coder.skills_manager is None:
        io.tool_output("Skills manager is not initialized. Skills may not be configured.")
        if hasattr(coder, "skills_directory_paths") and not coder.skills_directory_paths:
            io.tool_output(
                "No skills directories configured. Use --skills-paths to configure skill"
                " directories."
            )
        return format_command_result(io, "list-skills", "Skills manager is not initialized")

    try:
        formatted = coder.skills_manager.get_skills_list_formatted()
        return format_command_result(io, "list-skills", formatted)
    except Exception as e:
        error_msg = f"Error listing skills: {e}"
        return format_command_result(io, "list-skills", error_msg)
