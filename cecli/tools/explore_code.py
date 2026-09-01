import os

from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import ToolError
from cecli.tools.utils.output import color_markers, tool_footer, tool_header
from cecli.tools.utils.responses import ToolResponse
from cecli.tools.validations import ToolValidations

cwd = os.getcwd()

try:
    import cymbal

    CYMBAL_AVAILABLE = True
except ImportError:
    CYMBAL_AVAILABLE = False
finally:
    os.chdir(cwd)


class Tool(BaseTool):
    NORM_NAME = "explorecode"
    VALIDATIONS = {
        "queries": ["coerce_list"],
        "queries[]": ["coerce_dict"],
    }
    RESULT_TYPE = "list"
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "ExploreCode",
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
        response = ToolResponse(cls.NORM_NAME, result_type="list")
        try:
            # Check if cymbal is available
            if not CYMBAL_AVAILABLE:
                coder.io.tool_error(
                    "Cymbal library is not available. Please install it with: pip install py-cymbal"
                )
                response.append_error("Cymbal library is not available")
                return response

            # Initialize Cymbal and index if necessary
            c = cymbal.Cymbal()
            repo_path = getattr(coder, "root", ".")

            try:
                # Always index to ensure we have the latest data
                c.index(repo_path)
            except Exception as e:
                error_msg = f"Failed to index repository: {str(e)}"
                coder.io.tool_error(error_msg)
                response.append_error(error_msg)
                return response
            all_failed_queries = []
            total_successful_queries = 0

            for query in queries:
                symbol = query.get("symbol")
                action = query.get("action")
                limit = query.get("limit", 15)

                try:
                    if action == "search":
                        # Sanitize symbol: Cymbal's CLI interprets hyphens as SQL operators.
                        # Replace hyphens with underscores (common in code) and strip special chars.
                        safe_symbol = symbol.replace("-", "_") if symbol else symbol
                        results = c.search(safe_symbol, limit=limit)
                        results = cls._filter_gitignored(results, coder)
                        response.append_result(content=cls._format_search_results(results, symbol))
                    elif action == "investigate":
                        symbol_name = symbol
                        file_hint = ""
                        if ":" in symbol:
                            parts = symbol.split(":", 1)
                            if len(parts) == 2:
                                file_hint = parts[0]
                                symbol_name = parts[1]

                        # Sanitize for Cymbal search
                        safe_name = symbol_name.replace("-", "_") if symbol_name else symbol_name

                        try:
                            investigation = c.investigate(safe_name, file_hint)
                            investigation = cls._filter_investigation_gitignored(
                                investigation, coder
                            )
                            response.append_result(
                                content=cls._format_investigation_results(investigation, symbol)
                            )
                        except Exception as e:
                            if "multiple matches" in str(e).lower():
                                results = c.search(symbol_name, limit=10)
                                response.append_result(
                                    content=(
                                        f"Error: Multiple matches found for '{symbol}'.\n"
                                        f"Please use a more specific name or check the locations"
                                        f" below:\n"
                                        + "\n".join(
                                            f"- {r.get('rel_path') or r.get('file', '')}:{r.get('start_line', 0)}"
                                            for r in results
                                        )
                                    )
                                )
                            else:
                                raise e
                    elif action == "find_references":
                        safe_symbol = symbol.replace("-", "_") if symbol else symbol
                        references = c.find_references(safe_symbol, limit=limit)
                        references = cls._filter_gitignored(references, coder)
                        response.append_result(
                            content=cls._format_reference_results(references, symbol)
                        )
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
                response.append_error(error_msg)
                return response

            if all_failed_queries:
                for failed_msg in all_failed_queries:
                    coder.io.tool_error(failed_msg)
            else:
                coder.io.tool_output("\u2713 All queries successful.", type="tool-result")

            return response

        except Exception as e:
            coder.io.tool_error(f"Error in ExploreCode: {str(e)}")
            response.append_error(str(e))
            return response
        finally:
            if "c" in locals():
                c.close()

    @classmethod
    def _filter_gitignored(cls, results, coder):
        """Filter out results whose file path is git-ignored."""

        if not results or not hasattr(coder, "repo") or not coder.repo:
            return results

        filtered = []
        for r in results:
            file_path = r.get("rel_path") or r.get("file", "")
            if not file_path:
                filtered.append(r)
                continue
            if not coder.repo.git_ignored_file(file_path):
                filtered.append(r)

        return filtered

    @classmethod
    def _filter_investigation_gitignored(cls, investigation, coder):
        """Filter git-ignored entries from an investigation result."""

        if not investigation or not hasattr(coder, "repo") or not coder.repo:
            return investigation

        # Filter references
        if "refs" in investigation:
            investigation["refs"] = cls._filter_gitignored(investigation["refs"], coder)

        # Filter impact/callers
        if "impact" in investigation:
            investigation["impact"] = cls._filter_gitignored(investigation["impact"], coder)

        return investigation

    @classmethod
    def _format_search_results(cls, results, symbol):
        """Format search results for display."""
        if not results:
            return f"No symbols found matching '{symbol}'"

        formatted = [f"Found {len(results)} symbols matching '{symbol}':"]
        for i, result in enumerate(results[:15], 1):
            name = result.get("name", "Unknown")
            kind = result.get("kind", "unknown")
            file = result.get("rel_path") or result.get("file", "Unknown")
            start_line = result.get("start_line", 0)
            signature = result.get("signature", "")
            parent = result.get("parent")

            location = f"{file}:{start_line}"
            if parent:
                location = f"{location} (in {parent})"

            formatted.append(f"{i}. {name}{signature} ({kind}) at {location}")

        if len(results) > 15:
            formatted.append(f"... and {len(results) - 15} more results")

        return "\n".join(formatted)

    @classmethod
    def _format_investigation_results(cls, investigation, symbol):
        """Format investigation results for display."""
        if not investigation:
            return f"No information found for symbol '{symbol}'"

        # Handle nested structure if present
        if "results" in investigation and "result" in investigation["results"]:
            investigation = investigation["results"]["result"]

        formatted = [f"Investigation of symbol '{symbol}':"]

        # Extract definition information
        definition = investigation.get("symbol")
        if definition:
            def_name = definition.get("name", symbol)
            def_file = definition.get("rel_path") or definition.get("file", "Unknown")
            def_line = definition.get("start_line", 0)
            def_kind = definition.get("kind", "unknown")
            def_sig = definition.get("signature", "")
            formatted.append(
                f"Definition: {def_name}{def_sig} ({def_kind}) at {def_file}:{def_line}"
            )

        # Source code snippet
        source = investigation.get("source")
        if source:
            formatted.append("\nSource Code:")
            formatted.append("```python")
            formatted.append(source.strip())
            formatted.append("```")

        # References
        references = investigation.get("refs", [])
        ref_count = len(references) if references else 0
        formatted.append(f"\nReferences found: {ref_count}")

        if references and ref_count > 0:
            formatted.append("Top references:")
            for i, ref in enumerate(references[:10], 1):
                ref_file = ref.get("rel_path") or ref.get("file", "Unknown")
                ref_line = ref.get("line", 0)
                formatted.append(f"{i}. {ref_file}:{ref_line}")

            if ref_count > 10:
                formatted.append(f"... and {ref_count - 10} more references")

        # Impact / Callers
        impact = investigation.get("impact", [])
        if impact:
            formatted.append("\nImpact (Callers):")
            for i, imp in enumerate(impact[:10], 1):
                imp_file = imp.get("rel_path") or imp.get("file", "Unknown")
                imp_line = imp.get("line", 0)
                imp_caller = imp.get("caller", "unknown")
                formatted.append(f"{i}. {imp_caller} at {imp_file}:{imp_line}")

            if len(impact) > 10:
                formatted.append(f"... and {len(impact) - 10} more callers")

        return "\n".join(formatted)

    @classmethod
    def _format_reference_results(cls, references, symbol):
        """Format reference finding results for display."""
        if not references:
            return f"No references found for symbol '{symbol}'"

        formatted = [f"Found {len(references)} references to '{symbol}':"]
        for i, ref in enumerate(references[:15], 1):
            file = ref.get("rel_path") or ref.get("file", "Unknown")
            line = ref.get("line", 0)
            context = ref.get("context", [])

            formatted.append(f"{i}. {file}:{line}")
            if context:
                formatted.append("   Context:")
                for line_text in context:
                    formatted.append(f"     {line_text.strip()}")

        if len(references) > 15:
            formatted.append(f"... and {len(references) - 15} more references")

        return "\n".join(formatted)

    @classmethod
    def format_output(cls, coder, mcp_server, tool_response):
        """Format output for ExploreCode tool."""
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
        tool_footer(coder=coder, tool_response=tool_response, params=params)
