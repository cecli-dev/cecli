import traceback

from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.responses import ToolResponse


class Tool(BaseTool):
    NORM_NAME = "undochange"
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "UndoChange",
            "description": "Undo a previously applied change.",
            "parameters": {
                "type": "object",
                "properties": {
                    "change_id": {"type": "string"},
                    "file_path": {"type": "string"},
                },
            },
        },
    }

    @classmethod
    def execute(cls, coder, change_id=None, file_path=None, **kwargs):
        """
        Undo a specific change by ID, or the last change to a file.

        Parameters:
        - coder: The Coder instance
        - change_id: ID of the change to undo
        - file_path: Path to file where the last change should be undone

        Returns a result message.
        """
        # Note: Undo does not have a dry_run parameter as it's inherently about reverting a previous action.
        coder.edit_allowed = False
        response = ToolResponse(cls.NORM_NAME)

        try:
            # Validate parameters
            if change_id is None and file_path is None:
                coder.io.tool_error("Must specify either change_id or file_path for UndoChange")
                response.append_result("Error: Must specify either change_id or file_path")
                return response

            # If file_path is specified, get the most recent change for that file
            if file_path:
                abs_path = coder.abs_root_path(file_path)
                rel_path = coder.get_rel_fname(abs_path)

                change_id = coder.change_tracker.get_last_change(rel_path)
                if not change_id:
                    coder.io.tool_error(f"No tracked changes found for file '{file_path}' to undo.")
                    response.append_result(f"Error: No changes found for file '{file_path}'")
                    return response

            # Attempt to get undo information from the tracker
            success, message, change_info = coder.change_tracker.undo_change(change_id)

            if not success:
                coder.io.tool_error(f"Failed to undo change '{change_id}': {message}")
                response.append_result(f"Error: {message}")
                return response

            # Apply the undo by restoring the original content
            if change_info:
                file_path = change_info["file_path"]
                abs_path = coder.abs_root_path(file_path)
                # Write the original content back to the file
                coder.io.write_text(abs_path, change_info["original"])
                coder.coder_edited_files.add(
                    file_path
                )  # Track that the file was modified by the undo

                change_type = change_info["type"]
                coder.io.tool_output(
                    f"✓ Undid {change_type} change '{change_id}' in {file_path}", type="tool-result"
                )
                response.append_result(f"Successfully undid {change_type} change '{change_id}'.")
                return response
            else:
                # This case should ideally not be reached if tracker returns success
                coder.io.tool_error(
                    f"Failed to undo change '{change_id}': Change info missing after successful"
                    " tracker update."
                )
                response.append_result(
                    f"Error: Failed to undo change '{change_id}' (missing change info)"
                )
                return response

        except Exception as e:
            coder.io.tool_error(f"Error in UndoChange: {str(e)}\n{traceback.format_exc()}")
            response.append_result(f"Error: {str(e)}")
            return response
