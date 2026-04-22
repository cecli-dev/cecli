from abc import ABC, abstractmethod

from cecli.tools.utils.helpers import handle_tool_error
from cecli.tools.utils.output import print_tool_response


class BaseTool(ABC):
    """Abstract base class for all tools."""

    # Class properties that must be defined by subclasses
    # Note: NORM_NAME should be the lowercase version of the function name in the SCHEMA
    NORM_NAME = None
    SCHEMA = None

    # Invocation tracking for detecting repeated tool calls
    _invocations = {}  # Dict to store last 3 invocations per tool
    _invocation_summary = set()  # Set to track distinct tool names
    TRACK_INVOCATIONS = True  # Default to True, subclasses can override

    @classmethod
    @abstractmethod
    def execute(cls, coder, **params):
        """
        Execute the tool with the given parameters.

        Args:
            coder: The Coder instance
            **params: Tool-specific parameters

        Returns:
            str: Result message
        """
        pass

    @classmethod
    def process_response(cls, coder, params):
        """
        Process the tool response by creating an instance and calling execute.

        Args:
            coder: The Coder instance
            params: Dictionary of parameters

        Returns:
            str: Result message
        """

        # Validate required parameters from SCHEMA
        if cls.SCHEMA and "function" in cls.SCHEMA:
            function_schema = cls.SCHEMA["function"]

            if "parameters" in function_schema and "required" in function_schema["parameters"]:
                required_params = function_schema["parameters"]["required"]
                properties = function_schema["parameters"].get("properties", {})

                # Auto-correction: If a required parameter is missing but it's an array,
                # and the current params look like a single item of that array, wrap it.
                if len(required_params) == 1:
                    missing_param = required_params[0]
                    if missing_param not in params and params:
                        param_schema = properties.get(missing_param, {})
                        if param_schema.get("type") == "array":
                            params = {missing_param: [params]}

                # Auto-correction: If a required parameter is present but is a dict instead of an array
                for param_name in required_params:
                    if param_name in params:
                        param_schema = properties.get(param_name, {})
                        if param_schema.get("type") == "array" and isinstance(
                            params[param_name], dict
                        ):
                            params[param_name] = [params[param_name]]

                missing_params = [param for param in required_params if param not in params]
                if missing_params:
                    tool_name = function_schema.get("name", "Unknown Tool")
                    error_msg = (
                        f"Missing required parameters for {tool_name}: {', '.join(missing_params)}"
                    )
                    return handle_tool_error(coder, tool_name, ValueError(error_msg))

        # Check for repeated invocations if TRACK_INVOCATIONS is enabled
        if cls.TRACK_INVOCATIONS:
            tool_name = None
            if cls.SCHEMA and "function" in cls.SCHEMA:
                tool_name = cls.SCHEMA["function"].get("name", "Unknown Tool")
            else:
                tool_name = cls.__name__

            # Check if adding this tool would reach 3 distinct tools
            # If so, clear all tracking and start fresh without counting this tool
            if (
                len(cls._invocation_summary) + (0 if tool_name in cls._invocation_summary else 1)
                >= 3
            ):
                cls._invocations.clear()
                cls._invocation_summary.clear()
            else:
                # Only add to summary if we didn't just clear everything
                cls._invocation_summary.add(tool_name)

            # Initialize invocation tracking for this tool if not exists
            if tool_name not in cls._invocations:
                cls._invocations[tool_name] = []

            # Check if current parameters match any of the last 3 invocations
            current_params_tuple = tuple(
                sorted(params.items())
            )  # Convert to sorted tuple for comparison

            for i, (prev_params_tuple, _) in enumerate(cls._invocations[tool_name]):
                if prev_params_tuple == current_params_tuple:
                    error_msg = (
                        f"Tool '{tool_name}' has been called with identical parameters recently. "
                        "This request is denied."
                    )
                    cls.on_duplicate_request(coder, **params)
                    return handle_tool_error(
                        coder, tool_name, ValueError(error_msg), add_traceback=False
                    )

            # Add current invocation to history (keeping only last 3)
            cls._invocations[tool_name].append((current_params_tuple, params))
            if len(cls._invocations[tool_name]) > 3:
                cls._invocations[tool_name] = cls._invocations[tool_name][-3:]

        try:
            return cls.execute(coder, **params)
        except Exception as e:
            return handle_tool_error(coder, cls.SCHEMA.get("function").get("name"), e)

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):
        print_tool_response(coder=coder, mcp_server=mcp_server, tool_response=tool_response)

    @classmethod
    def on_duplicate_request(cls, coder, **kwargs):
        pass

    @classmethod
    def clear_invocation_cache(cls):
        cls._invocations.clear()
        cls._invocation_summary.clear()
