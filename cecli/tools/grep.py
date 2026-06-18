import shutil
from pathlib import Path

import oslex

from cecli.helpers.hashline import strip_hashline
from cecli.run_cmd import run_cmd_subprocess
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import ToolError
from cecli.tools.utils.output import color_markers, tool_footer, tool_header
from cecli.tools.validations import ToolValidations


class Tool(BaseTool):
    NORM_NAME = "grep"
    VALIDATIONS = {
        "searches": ["coerce_list"],
        "searches[]": ["coerce_dict"],
    }
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "Grep",
            "description": "Search for patterns in files. Supports multiple search operations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "searches": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "pattern": {
                                    "type": "string",
                                    "description": "The pattern to search for.",
                                },
                                "file_glob": {
                                    "type": "string",
                                    "default": "*",
                                    "description": "Glob pattern for files to search.",
                                },
                                "directory": {
                                    "type": "string",
                                    "default": ".",
                                    "description": "Directory to search in.",
                                },
                                "use_regex": {
                                    "type": "boolean",
                                    "default": True,
                                    "description": "Whether to use regex.",
                                },
                                "case_insensitive": {
                                    "type": "boolean",
                                    "default": True,
                                    "description": "Whether to perform a case-insensitive search.",
                                },
                            },
                            "required": ["pattern"],
                        },
                        "description": "Array of search operations to perform.",
                    }
                },
                "required": ["searches"],
            },
        },
    }

    @classmethod
    def _find_search_tool(self):
        """Find the best available command-line search tool (rg, ag, grep)."""
        if shutil.which("rg"):
            return "rg", shutil.which("rg")
        elif shutil.which("ag"):
            return "ag", shutil.which("ag")
        elif shutil.which("grep"):
            return "grep", shutil.which("grep")
        else:
            return None, None

    @classmethod
    def execute(
        cls,
        coder,
        searches=None,
        **kwargs,
    ):
        """
        Search for lines matching patterns in files within the project repository.
        Uses rg (ripgrep), ag (the silver searcher), or grep, whichever is available.
        """
        if not isinstance(searches, list):
            # Handle legacy single-search call if necessary, or just error
            return "Error: 'searches' parameter must be an array."

        repo = coder.repo
        if not repo:
            coder.io.tool_error("Not in a git repository.")
            return "Error: Not in a git repository."

        tool_name, tool_path = cls._find_search_tool()
        if not tool_path:
            coder.io.tool_error("No search tool (rg, ag, grep) found in PATH.")
            return "Error: No search tool (rg, ag, grep) found."

        all_results = []
        for search_op in searches:
            pattern = strip_hashline(search_op.get("pattern"))
            file_pattern = search_op.get("file_glob", "*")
            directory = search_op.get("directory", search_op.get("path", "."))
            use_regex = search_op.get("use_regex", True)
            case_insensitive = search_op.get("case_insensitive", True)
            context_before = search_op.get("context_before", 2)
            context_after = search_op.get("context_after", 2)

            try:
                search_dir_path = Path(repo.root) / directory

                # Build the command arguments based on the available tool
                cmd_args = [tool_path]

                # Common options or tool-specific equivalents
                if tool_name in ["rg", "grep"]:
                    cmd_args.append("-n")  # Line numbers for rg and grep

                if tool_name in ["rg"]:
                    cmd_args.append("--heading")  # Filename above output for ripgrep

                # Context lines
                if context_before > 0:
                    cmd_args.extend(["-B", str(context_before)])
                if context_after > 0:
                    cmd_args.extend(["-A", str(context_after)])

                # Case sensitivity
                if case_insensitive:
                    cmd_args.append("-i")

                # Pattern type
                if use_regex:
                    if tool_name == "grep":
                        cmd_args.append("-E")
                else:
                    if tool_name == "rg":
                        cmd_args.append("-F")
                    elif tool_name == "ag":
                        cmd_args.append("-Q")
                    elif tool_name == "grep":
                        cmd_args.append("-F")

                # File filtering
                if file_pattern != "*":
                    if tool_name == "rg":
                        cmd_args.extend(["-g", file_pattern])
                    elif tool_name == "ag":
                        cmd_args.extend(["-G", file_pattern])
                    elif tool_name == "grep":
                        cmd_args.append("-r")
                        cmd_args.append(f"--include={file_pattern}")
                elif tool_name == "grep":
                    cmd_args.append("-r")

                if tool_name == "grep":
                    cmd_args.append("--exclude-dir=.git")

                # Add pattern and directory path
                cmd_args.extend(["--", pattern, str(search_dir_path)])

                command_string = oslex.join(cmd_args)
                coder.io.tool_output(
                    f"⛭ Executing {tool_name}: {command_string}", type="tool-result"
                )

                exit_status, combined_output = run_cmd_subprocess(
                    command_string,
                    verbose=coder.verbose,
                    cwd=coder.root,
                    should_print=False,
                )

                output_content = combined_output or ""

                if exit_status == 0:
                    max_output_lines = 50
                    output_lines = output_content.splitlines()
                    if len(output_lines) > max_output_lines:
                        truncated_output = "\n".join(output_lines[:max_output_lines])
                        all_results.append(
                            f"Matches for '{pattern}'"
                            f" (truncated):\n```text\n{truncated_output}\n..."
                            f" ({len(output_lines) - max_output_lines} more lines)\n```"
                        )
                    else:
                        all_results.append(
                            f"Matches for '{pattern}':\n```text\n{output_content}\n```"
                        )
                elif exit_status == 1:
                    all_results.append(f"No matches found for '{pattern}'.")
                else:
                    all_results.append(f"Error searching for '{pattern}': {output_content}")

            except Exception as e:
                all_results.append(f"Error executing search for '{pattern}': {str(e)}")

        final_message = "\n\n".join(all_results)

        return final_message

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):
        """Format output for Grep tool."""
        color_start, color_end = color_markers(coder)

        # Output header
        tool_header(coder=coder, mcp_server=mcp_server, tool_response=tool_response)

        try:
            params = ToolValidations.validate_params(
                tool_response.function.arguments, cls.VALIDATIONS, cls.SCHEMA
            )
        except ToolError:
            coder.io.tool_error("Invalid Tool JSON")
            return

        # Output each search operation with the requested format
        searches = params.get("searches", [])
        if searches:
            coder.io.tool_output("")
            for i, search_op in enumerate(searches):
                pattern = search_op.get("pattern", "")
                file_pattern = search_op.get("file_glob", "*")
                directory = search_op.get("directory", ".")
                use_regex = search_op.get("use_regex", False)
                case_insensitive = search_op.get("case_insensitive", False)
                context_before = search_op.get("context_before", 5)
                context_after = search_op.get("context_after", 5)

                # Format as "search: • pattern • file_pattern • directory • options"
                formatted_query = (
                    f"{color_start}search_{i + 1}:{color_end} {pattern} • {file_pattern} •"
                    f" {directory}"
                )

                # Add options if they differ from defaults
                options = []
                if use_regex:
                    options.append("regex")
                if case_insensitive:
                    options.append("case-insensitive")
                if context_before != 5 or context_after != 5:
                    options.append(f"context:{context_before}/{context_after}")

                if options:
                    formatted_query += f" • {' '.join(options)}"

                coder.io.tool_output(formatted_query)
            coder.io.tool_output("")

        tool_footer(coder=coder, tool_response=tool_response, params=params)
