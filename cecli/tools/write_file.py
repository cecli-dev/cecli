import os

from cecli.helpers import nested
from cecli.helpers.hashline import strip_hashline
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import (
    ToolError,
    apply_change,
    is_creator_coder,
    is_path_within_root,
    read_text_preserving_newlines,
    resolve_paths,
)
from cecli.tools.utils.output import color_markers, tool_footer, tool_header
from cecli.tools.utils.responses import ToolResponse
from cecli.tools.validations import ToolValidations


class Tool(BaseTool):
    NORM_NAME = "writefile"
    RESULT_TYPE = "list"
    TRACK_INVOCATIONS = False
    VALIDATIONS = {
        "file_path": ["coerce_str"],
        "overwrite": ["coerce_bool"],
    }
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "WriteFile",
            "description": (
                "Create a new file or write full contents to a file in a single step. "
                "Automatically creates parent directories if needed and adds the file to editable context. "
                "Prefer EditFile for targeted line modifications to existing files; use WriteFile when "
                "creating a new file or replacing an entire file's contents."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": (
                            "The file path to create or write, relative to the project root or absolute."
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "The full text content to write to the file.",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": (
                            "Whether to overwrite the file if it already exists and is non-empty. "
                            "Defaults to true."
                        ),
                    },
                },
                "required": ["file_path", "content"],
            },
        },
    }

    @classmethod
    def _extract_entries(cls, file_path=None, content=None, overwrite=True, **kwargs):
        """Normalize single-file or batch parameters into a list of write entries."""
        files = kwargs.get("files") or kwargs.get("writes")
        if isinstance(files, list) and files:
            entries = []
            for item in files:
                if not isinstance(item, dict):
                    continue
                fp = nested.getter(item, ["file_path", "path", "filename", "file"])
                text = nested.getter(item, ["content", "text", "contents", "body"])
                ov = item.get("overwrite", overwrite if overwrite is not None else True)
                entries.append((fp, text, bool(ov)))
            return entries

        fp = file_path or nested.getter(kwargs, ["path", "filename", "file"])
        text = content if content is not None else nested.getter(kwargs, ["text", "contents", "body"])
        ov = True if overwrite is None else bool(overwrite)
        return [(fp, text, ov)]

    @classmethod
    def execute(
        cls,
        coder,
        file_path=None,
        content=None,
        overwrite=True,
        change_id=None,
        dry_run=False,
        **kwargs,
    ):
        """Create or write one or more files and add them to editable context."""
        from cecli.helpers.conversation import ConversationService

        response = ToolResponse(cls.NORM_NAME, result_type=cls.RESULT_TYPE)
        try:
            entries = cls._extract_entries(
                file_path=file_path, content=content, overwrite=overwrite, **kwargs
            )
            if not entries:
                raise ToolError("WriteFile requires 'file_path' and 'content'")

            for idx, (fp, raw_content, allow_overwrite) in enumerate(entries):
                if not fp or not isinstance(fp, str) or not fp.strip():
                    raise ToolError(f"Write {idx + 1}: missing required 'file_path' parameter")
                if raw_content is None:
                    raise ToolError(f"Write {idx + 1}: missing required 'content' parameter for '{fp}'")
                if not isinstance(raw_content, str):
                    raw_content = str(raw_content)

                abs_path, rel_path = resolve_paths(coder, fp)

                if not is_creator_coder(coder) and not is_path_within_root(abs_path, coder.root):
                    raise ToolError(
                        f"Access denied: '{fp}' is outside the project root ({coder.root})"
                    )

                if os.path.isdir(abs_path):
                    raise ToolError(f"Cannot write to '{fp}': path is a directory")

                if abs_path in getattr(coder, "abs_read_only_fnames", set()):
                    raise ToolError(
                        f"File '{fp}' is marked read-only in context. "
                        "Make it editable with `ManageResources` before writing."
                    )

                existed = os.path.isfile(abs_path)
                original_content = ""
                if existed:
                    existing_text = read_text_preserving_newlines(coder, abs_path)
                    original_content = existing_text if existing_text is not None else ""
                    if original_content.strip() and not allow_overwrite:
                        raise ToolError(
                            f"File '{fp}' already exists and is non-empty (overwrite=False). "
                            "Use `EditFile` for targeted edits or set `overwrite=True`."
                        )

                # Strip any virtual hashline prefixes if the model copied ReadFile lines
                clean_content = raw_content
                if clean_content:
                    stripped = strip_hashline(clean_content)
                    while stripped != clean_content:
                        clean_content = stripped
                        stripped = strip_hashline(clean_content)

                if dry_run:
                    action = "overwrite" if existed else "create"
                    response.append_result(
                        content=f"Dry run: Would {action} {rel_path} ({len(clean_content.splitlines())} lines)",
                        metadata={"file_path": rel_path, "dry_run": True},
                    )
                    continue

                parent_dir = os.path.dirname(abs_path)
                if parent_dir:
                    os.makedirs(parent_dir, exist_ok=True)

                coder.abs_fnames.add(abs_path)
                if hasattr(coder, "file_read_cache"):
                    coder.file_read_cache.discard(abs_path)

                metadata = {
                    "action": "overwrite" if existed else "create",
                    "lines": len(clean_content.splitlines()),
                    "bytes": len(clean_content.encode("utf-8")),
                }

                final_change_id = apply_change(
                    coder,
                    abs_path,
                    rel_path,
                    original_content,
                    clean_content,
                    "writefile",
                    metadata,
                    change_id,
                )

                coder.files_edited_by_tools.add(rel_path)
                if getattr(coder, "uuid", None):
                    ConversationService.get_chunks(coder).notify_file_edited(abs_path)

                action_verb = "Wrote" if existed else "Created and wrote"
                line_count = len(clean_content.splitlines())
                response.append_result(
                    content=f"✓ {action_verb} {rel_path} ({line_count} lines)",
                    metadata={
                        "change_id": final_change_id,
                        "file_path": rel_path,
                        "created": not existed,
                        "lines": line_count,
                    },
                )

            coder.context_blocks_cache = {}
            coder.edit_allowed = True
            return response

        except ToolError as e:
            response.append_error(str(e))
            return response
        except Exception as e:
            response.append_error(str(e))
            return response

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):
        color_start, color_end = color_markers(coder)
        tool_header(coder=coder, mcp_server=mcp_server, tool_response=tool_response)

        try:
            params = ToolValidations.validate_params(
                tool_response.function.arguments, cls.VALIDATIONS, cls.SCHEMA
            )
        except ToolError:
            coder.io.tool_error("Invalid Tool JSON")
            return

        fp = params.get("file_path") or nested.getter(params, ["path", "filename", "file"])
        content = params.get("content")
        if content is None:
            content = nested.getter(params, ["text", "contents", "body"]) or ""

        if fp:
            coder.io.tool_output("")
            coder.io.tool_output(f"{color_start}file_path:{color_end} {fp}")
            line_count = len(str(content).splitlines()) if content else 0
            coder.io.tool_output(f"{color_start}lines:{color_end} {line_count}")
            coder.io.tool_output("")

        tool_footer(coder=coder, tool_response=tool_response, params=params)
