from cecli.tools.utils.base_tool import BaseTool


class Tool(BaseTool):
    NORM_NAME = "removeskill"
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "RemoveSkill",
            "description": (
                "Remove a skill by name (agent mode only). Removes skill from include list and adds"
                " to exclude list."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "Name of the skill to remove",
                    },
                },
                "required": ["skill_name"],
            },
        },
    }

    @classmethod
    def execute(cls, coder, skill_name):
        """
        Remove a skill by name (agent mode only).
        """
        if not skill_name:
            return "Error: Skill name is required."

        # Check if we're in agent mode
        if not hasattr(coder, "edit_format") or coder.edit_format != "agent":
            return "Error: Skill removal is only available in agent mode."

        # Check if skills_manager is available
        if not hasattr(coder, "skills_manager") or coder.skills_manager is None:
            error_msg = "Error: Skills manager is not initialized. Skills may not be configured."
            # Check if skills directories are configured
            if hasattr(coder, "skills_directory_paths") and not coder.skills_directory_paths:
                error_msg += (
                    "\nNo skills directories configured. Use --skills-paths to configure skill"
                    " directories."
                )
            return error_msg

        # Use the instance method on skills_manager
        return coder.skills_manager.remove_skill(skill_name)
