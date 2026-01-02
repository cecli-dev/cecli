from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class LoadSkillCommand(BaseCommand):
    NORM_NAME = "load-skill"
    DESCRIPTION = "Load a skill by name (agent mode only)"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the load-skill command with given parameters."""
        if not args.strip():
            io.tool_output("Usage: /load-skill <skill-name>")
            return format_command_result(io, "load-skill", "Usage: /load-skill <skill-name>")

        skill_name = args.strip()

        # Check if we're in agent mode
        if not hasattr(coder, "edit_format") or coder.edit_format != "agent":
            io.tool_output("Skill loading is only available in agent mode.")
            return format_command_result(
                io, "load-skill", "Skill loading is only available in agent mode"
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
            return format_command_result(io, "load-skill", "Skills manager is not initialized")

        # Use the instance method on skills_manager
        result = coder.skills_manager.load_skill(skill_name)
        io.tool_output(result)
        return format_command_result(io, "load-skill", f"Loaded skill: {skill_name}")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for load-skill command."""
        if not hasattr(coder, "skills_manager") or coder.skills_manager is None:
            return []

        try:
            skills = coder.skills_manager.find_skills()
            return [skill.name for skill in skills]
        except Exception:
            return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the load-skill command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /load-skill <skill-name>  # Load a skill by name\n"
        help_text += "\nExamples:\n"
        help_text += "  /load-skill pdf  # Load the PDF skill\n"
        help_text += "  /load-skill web  # Load the web skill\n"
        help_text += (
            "\nThis command loads a skill by name. Skills are only available in agent mode.\n"
        )
        help_text += "Skills provide additional functionality and tools to the agent.\n"
        return help_text
