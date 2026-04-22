import json
import os

from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import ToolError
from cecli.tools.utils.output import color_markers, tool_footer, tool_header

try:
    import cymbal

    CYMBAL_AVAILABLE = True
except ImportError:
    CYMBAL_AVAILABLE = False


class Tool(BaseTool):
    NORM_NAME = "exploresymbols"
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "ExploreSymbols",
            "description": (
                "Search, investigate, and find references to symbols using the Cymbal code indexing"
                " library. This is the preferred tool for analyzing code structure."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "symbol": {
                                    "type": "string",
                                    "description": (
                                        "The symbol name to search for, investigate, or find"
                                        " references to. This should be a single symbol"
                                        " (e.g. method, function, or class name)."
                                    ),
                                },
                                "action": {
                                    "type": "string",
                                    "enum": ["search", "investigate", "find_references"],
                                    "description": (
                                        "Action to perform: 'search', 'investigate', or"
                                        " 'find_references'.\n\nNote: For the 'investigate' action,"
                                        " you can use filename-based disambiguation:\n  - '{file"
                                        " name}:{symbol}' to specify a symbol in a particular file"
                                        " (e.g., 'config.go:Config')\n"
                                    ),
                                },
                                "limit": {
                                    "type": "integer",
                                    "description": (
                                        "Maximum number of results to return. Defaults to 15."
                                    ),
                                    "default": 15,
                                },
                            },
                            "required": ["symbol", "action"],
                        },
                        "description": (
                            "Array of exploration queries. Maximum of 5 queries at a time."
                        ),
                    }
                },
                "required": ["queries"],
            },
        },
    }

    @classmethod
    def execute(cls, coder, queries, **kwargs):
        """
        Search, investigate, or find references to symbols using the Cymbal code indexing library.

        Args:
            coder: The Coder instance.
            queries (list): Array of exploration queries {symbol, action, limit}.

        Returns:
            str: Formatted results from the Cymbal operations.
        """
        try:
            # Check if cymbal is available
            if not CYMBAL_AVAILABLE:
                coder.io.tool_error(
                    "Cymbal library is not available. Please install it with: pip install py-cymbal"
                )
                return "Error: Cymbal library is not available"

            # Initialize Cymbal and index if necessary
            c = cymbal.Cymbal()
            repo_path = getattr(coder, "root", ".")

            try:
                # If we can't get a db_path or it doesn't exist, index it.
                if not os.path.exists(c.db_path):
                    c.index(repo_path)
            except Exception as e:
                error_msg = f"Failed to index repository: {str(e)}"
                coder.io.tool_error(error_msg)
                return f"Error: {error_msg}"

            all_results = []
            all_failed_queries = []
            total_successful_queries = 0

            for query in queries:
                symbol = query.get("symbol")
                action = query.get("action")
                limit = query.get("limit", 15)

                try:
                    if action == "search":
                        results = c.search(symbol, limit=limit)
                        all_results.append(cls._format_search_results(results, symbol))
                    elif action == "investigate":
                        # Parse symbol for file hint format: {file}:{symbol} or {package}.{symbol}
                        symbol_name = symbol
                        file_hint = ""

                        # Check for file:symbol format (e.g., "config.go:Config")
                        if ":" in symbol:
                            parts = symbol.split(":", 1)
                            if len(parts) == 2:
                                file_hint = parts[0]
                                symbol_name = parts[1]

                        try:
                            investigation = c.investigate(symbol_name, file_hint)
                            all_results.append(
                                cls._format_investigation_results(investigation, symbol)
                            )
                        except Exception as e:
                            if "multiple matches" in str(e).lower():
                                # Fallback to search to show locations
                                results = c.search(symbol_name, limit=10)
                                locations = "\n".join(
                                    [f"- {r['file']}:{r['start_line']}" for r in results]
                                )
                                msg = (
                                    f"Error: Multiple matches found for '{symbol}'.\nPlease use a"
                                    " more specific name or check the locations"
                                    f" below:\n{locations}"
                                )
                                all_results.append(msg)
                            else:
                                raise e
                    elif action == "find_references":
                        references = c.find_references(symbol, limit=limit)
                        all_results.append(cls._format_reference_results(references, symbol))
                    else:
                        all_failed_queries.append(
                            f"Error for symbol '{symbol}': Unknown action '{action}'"
                        )
                        continue

                    total_successful_queries += 1
                except Exception as e:
                    all_failed_queries.append(f"Error for symbol '{symbol}': {str(e)}")

            if total_successful_queries == 0:
                error_msg = "No queries were successfully executed:\n" + "\n".join(
                    all_failed_queries
                )
                raise ToolError(error_msg)

            if all_failed_queries:
                for failed_msg in all_failed_queries:
                    coder.io.tool_error(failed_msg)
            else:
                coder.io.tool_output("✅ All queries successful.")

            return "\n\n" + "=" * 40 + "\n\n".join(all_results)

        except Exception as e:
            coder.io.tool_error(f"Error in ExploreSymbols: {str(e)}")
            return f"Error: {str(e)}"

    @classmethod
    def _format_search_results(cls, results, symbol):
        """Format search results for display."""
        if not results:
            return f"No symbols found matching '{symbol}'"

        formatted = [f"Found {len(results)} symbols matching '{symbol}':"]
        for i, result in enumerate(results[:15], 1):
            # Extract symbol attributes (adjust based on actual cymbal result structure)
            # Extract symbol attributes from dictionary
            name = result.get("name", "Unknown")
            kind = result.get("kind", "unknown")
            file = result.get("file", "Unknown")
            start_line = result.get("start_line", 0)

            formatted.append(f"{i}. {name} ({kind}) at {file}:{start_line}")

        if len(results) > 15:
            formatted.append(f"... and {len(results) - 15} more results")

        return "\n".join(formatted)

    @classmethod
    def _format_investigation_results(cls, investigation, symbol):
        """Format investigation results for display."""
        if not investigation:
            return f"No information found for symbol '{symbol}'"

        formatted = [f"Investigation of symbol '{symbol}':"]

        # Extract definition information
        definition = investigation.get("symbol")
        if definition:
            def_name = definition.get("name", symbol)
            def_file = definition.get("file", "Unknown")
            def_line = definition.get("start_line", 0)
            def_kind = definition.get("kind", "unknown")
            formatted.append(f"Definition: {def_name} ({def_kind}) at {def_file}:{def_line}")

        references = investigation.get("refs", [])
        ref_count = len(references) if references else 0
        formatted.append(f"\nReferences found: {ref_count}")

        if references and ref_count > 0:
            formatted.append("Top references:")
            for i, ref in enumerate(references[:10], 1):
                ref_file = ref.get("file", "Unknown")
                ref_line = ref.get("line", 0)
                formatted.append(f"{i}. {ref_file}:{ref_line}")

            if ref_count > 10:
                formatted.append(f"... and {ref_count - 10} more references")

        return "\n".join(formatted)

    @classmethod
    def _format_reference_results(cls, references, symbol):
        """Format reference finding results for display."""
        if not references:
            return f"No references found for symbol '{symbol}'"

        formatted = [f"Found {len(references)} references to '{symbol}':"]
        for i, ref in enumerate(references[:15], 1):
            # Extract reference attributes from dictionary
            file = ref.get("file", "Unknown")
            line = ref.get("line", 0)

            formatted.append(f"{i}. {file}:{line}")

        if len(references) > 15:
            formatted.append(f"... and {len(references) - 15} more references")

        return "\n".join(formatted)

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):
        """Format output for ExploreSymbols tool."""
        color_start, color_end = color_markers(coder)

        try:
            params = json.loads(tool_response.function.arguments)
        except json.JSONDecodeError:
            coder.io.tool_error("Invalid Tool JSON")
            return

        # Output header
        tool_header(coder=coder, mcp_server=mcp_server, tool_response=tool_response)

        # Output each query with the requested format
        queries = params.get("queries", [])
        if queries:
            coder.io.tool_output("")
            for i, query in enumerate(queries):
                symbol = query.get("symbol", "")
                action = query.get("action", "")
                limit = query.get("limit", 15)

                # Format as "{action}: • {symbol} • {limit}" with action wrapped in color markers
                # Capitalize action and replace underscores with spaces
                formatted_action = action
                formatted_query = f"{color_start}{formatted_action}:{color_end} {symbol} • {limit}"
                coder.io.tool_output(formatted_query)
            coder.io.tool_output("")

        # Output footer
        tool_footer(coder=coder, tool_response=tool_response)
