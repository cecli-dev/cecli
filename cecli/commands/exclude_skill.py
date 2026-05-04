from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class ExcludeSkillCommand(BaseCommand):
    NORM_NAME = "exclude-skill"
    DESCRIPTION = "Exclude a skill by name (agent mode only)"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the exclude-skill command with given parameters."""
        if not args.strip():
            io.tool_output("Usage: /exclude-skill <skill-name>")
            return format_command_result(io, "exclude-skill", "Usage: /exclude-skill <skill-name>")

        skill_names = args.strip().split()

        # Check if we're in agent mode
        if not hasattr(coder, "edit_format") or coder.edit_format != "agent":
            io.tool_output("Skill exclusion is only available in agent mode.")
            return format_command_result(
                io, "exclude-skill", "Skill exclusion is only available in agent mode"
            )

        # Check if skills_manager is available
        if not hasattr(coder, "skills_manager") or coder.skills_manager is None:
            io.tool_output("Skills manager is not initialized. Skills may not be configured.")
            # Check if skills directories are configured
            if hasattr(coder, "skills_directory_paths") and not coder.skills_directory_paths:
                io.tool_output(
                    "No skills directories configured. Use --skills-paths to configure skill"
                    " directories."
                )
            return format_command_result(io, "exclude-skill", "Skills manager is not initialized")

        results = []
        for skill_name in skill_names:
            # Use the instance method on skills_manager
            result = coder.skills_manager.exclude_skill(skill_name)
            results.append(result)

        return format_command_result(io, "exclude-skill", "\n".join(results))

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for exclude-skill command."""
        if not hasattr(coder, "skills_manager") or coder.skills_manager is None:
            return []

        try:
            skills = coder.skills_manager.find_skills()
            return [skill.name for skill in skills]
        except Exception:
            return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the exclude-skill command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /exclude-skill <skill-name>...  # Exclude one or more skills by name\n"
        help_text += "\nExamples:\n"
        help_text += "  /exclude-skill pdf  # Exclude (blacklist) the PDF skill\n"
        help_text += "  /exclude-skill web pdf  # Exclude both web and PDF skills\n"
        help_text += (
            "\nThis command excludes one or more skills by name, adding them to the blacklist. "
            "Skills are only available in agent mode.\n"
        )
        help_text += "Excluded skills will be hidden from discovery and unavailable for loading.\n"
        return help_text
