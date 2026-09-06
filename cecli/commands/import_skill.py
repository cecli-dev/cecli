from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class ImportSkillCommand(BaseCommand):
    NORM_NAME = "import-skill"
    DESCRIPTION = "Import a skill from the community registry or skills.sh (agent mode only)"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the import-skill command with given parameters."""
        tokens = args.strip().split()
        global_install = "--global" in tokens or "-g" in tokens
        tokens = [token for token in tokens if token not in ("--global", "-g")]

        if not tokens:
            io.tool_output("Usage: /import-skill [--global] <skill-name>")
            return format_command_result(
                io, "import-skill", "Usage: /import-skill [--global] <skill-name>"
            )

        skill_name = " ".join(tokens)

        # Importing (and including) skills is only available in agent mode.
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

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for import-skill command."""
        candidates = ["--global"]

        try:
            from cecli.helpers.extensions.skills_importer import get_registry_skills

            candidates.extend(get_registry_skills())
        except Exception:
            pass

        return candidates

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the import-skill command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += (
            "  /import-skill <skill-name>  # Import a skill into the project .cecli/skills\n"
        )
        help_text += (
            "  /import-skill --global <skill-name>  # Import a skill into ~/.cecli/skills\n"
        )
        help_text += "\nExamples:\n"
        help_text += (
            "  /import-skill files/docx  # Import the docx skill from the community registry\n"
        )
        help_text += "  /import-skill --global pdf  # Import the PDF skill globally\n"
        help_text += (
            "\nSkills are looked up in the cecli community registry first, then on skills.sh.\n"
        )
        help_text += "The imported skill is added to the current session like /include-skill.\n"
        return help_text
