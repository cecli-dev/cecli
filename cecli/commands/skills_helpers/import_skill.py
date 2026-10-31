from cecli.commands.utils.helpers import format_command_result


async def cmd_import(io, coder, args):
    """Import a skill from the community registry or skills.sh."""
    tokens = args.strip().split()
    global_install = "--global" in tokens or "-g" in tokens
    tokens = [token for token in tokens if token not in ("--global", "-g")]

    if not tokens:
        io.tool_output("Usage: /skills import [--global] <skill-name>")
        return format_command_result(
            io, "import-skill", "Usage: /skills import [--global] <skill-name>"
        )

    skill_name = " ".join(tokens)

    if not hasattr(coder, "edit_format") or coder.edit_format not in ("agent", "subagent"):
        io.tool_output("Skill import is only available in agent mode.")
        return format_command_result(
            io, "import-skill", "Skill import is only available in agent mode"
        )

    if not hasattr(coder, "skills_manager") or coder.skills_manager is None:
        io.tool_output("Skills manager is not initialized. Skills may not be configured.")
        return format_command_result(io, "import-skill", "Skills manager is not initialized")

    from cecli.helpers.extensions.skills_importer import (
        add_skill_to_config,
        install_skill,
    )

    root = getattr(coder, "primary_root", None) or getattr(coder, "root", None)
    result = install_skill(skill_name, global_install=global_install, root=root)

    if not result["ok"]:
        io.tool_output(result["message"])
        return format_command_result(io, "import-skill", result["message"])

    imported_name = result["name"]
    include_result = coder.skills_manager.include_skill(imported_name)
    config_result = add_skill_to_config(imported_name, root=root)

    message = (
        f"Imported skill '{imported_name}' from {result['source']} to {result['dest']}.\n\n"
        f"{include_result}\n\n"
        f"{config_result}"
    )

    return format_command_result(io, "import-skill", message)


def get_completions(io, coder):
    """Get completion options for the import subcommand."""
    candidates = ["--global"]

    try:
        from cecli.helpers.extensions.skills_importer import get_registry_skills

        candidates.extend(get_registry_skills())
    except Exception:
        pass

    return candidates
