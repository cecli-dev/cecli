from cecli.tools.utils.base_tool import BaseTool


class Tool(BaseTool):
    NORM_NAME = "loadskill"
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "LoadSkill",
            "description": (
                "Load a skill by name (agent mode only). Adds skill to include list and removes"
                " from exclude list."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "Name of the skill to load",
                    },
                },
                "required": ["skill_name"],
            },
        },
    }

    @classmethod
    def execute(cls, coder, skill_name):
        """
        Load a skill by name (agent mode only).
        """
        if not skill_name:
            return "Error: Skill name is required."

        # Check if we're in agent mode
        if not hasattr(coder, "edit_format") or coder.edit_format != "agent":
            return "Error: Skill loading is only available in agent mode."

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
        return coder.skills_manager.load_skill(skill_name)
