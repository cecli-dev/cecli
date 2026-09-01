import json


class ToolResponse:
    """Assists in formatting all tool call responses as JSON for the LLM.

    Every tool response is wrapped in JSON:

        {
            "result": [{"content": ..., "_": {...}}],
            "errors": [...],
            "details": [...]
        }

    Each result item has a ``content`` key (the primary output) and an
    ``_`` key (metadata).  Use ``append_result(content, metadata=None)``

    Usage inside a tool's ``execute`` method:

        response = ToolResponse("my_tool", result_type="str")
        response.append_result("Operation completed successfully")
        response.append_error("Minor warning: config file missing")
        response.append_detail("Extra context for the LLM")
        return response  # __str__ returns valid JSON

    Tools that set ``RESULT_TYPE = "list"`` at the class level will have
    result entries accumulated as a list instead of concatenated.
    """

    def __init__(self, tool_name, result_type="str"):
        self.tool_name = tool_name
        self.result_type = result_type
        self._result = "" if result_type == "str" else []
        self._errors = []
        self._details = []

    def append_result(self, content, metadata=None):
        """Append a result entry.

        If ``result_type`` is ``"str"`` the text is concatenated (with a
        newline separator for subsequent calls).  If ``result_type`` is
        ``"list"`` each call adds a new item to the results list.

        When metadata is provided (``result_type="list"`` only), it is
        stored under the ``_`` key alongside ``content``.

        Backward compat: if ``content`` is a dict *without* a ``content``
        key it is treated as the content value and metadata defaults to
        an empty dict.
        """

        if self.result_type == "str":
            if self._result:
                self._result += "\n" + str(content)
            else:
                self._result = str(content)
        else:
            item = {"content": content, "_": metadata or {}}
            self._result.append(item)

    def append_error(self, error):
        """Collect an error message."""

        self._errors.append(str(error))

    def append_detail(self, detail):
        """Collect an extraneous contextual detail for the LLM."""

        self._details.append(str(detail))

    def to_dict(self):
        """Return the response as a plain Python dictionary."""

        if self.result_type == "str":
            results = [{"content": self._result, "_": {}}] if self._result else []
        else:
            results = self._result

        return {
            "result": results,
            "errors": self._errors,
            "details": self._details,
        }

    def to_json(self):
        """Serialize the response to a JSON string."""

        return json.dumps(self.to_dict())

    def __str__(self):
        return self.to_json()

    @staticmethod
    def wrap(tool_name, result, errors=None):
        """Convenience that returns a populated ToolResponse.

        Useful when wrapping results from non-ToolResponse-aware code
        paths (e.g., MCP tool execution).

        Args:
            tool_name: Name of the tool.
            result: The result string to wrap.
            errors: Optional list of error strings.

        Returns:
            ToolResponse instance.
        """

        response = ToolResponse(tool_name)
        response.append_result(result)
        if errors:
            for error in errors:
                response.append_error(error)

        return response
