"""SearchFacts tool – full-text search across the Memorizer fact database.

Only accessible to the memorizer sub-agent.
"""

from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.responses import ToolResponse


class Tool(BaseTool):
    NORM_NAME = "searchfacts"
    RESULT_TYPE = "list"
    TRACK_INVOCATIONS = False
    VALIDATIONS = {
        "words": ["coerce_list"],
        "tags": ["coerce_list"],
    }
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "SearchFacts",
            "description": (
                "Search the fact database by keyword.  Optional tag filter "
                "narrows results to facts with at least one matching tag."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "words": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Search terms.  Each word is matched as a prefix "
                            "against the fact text using FTS5."
                        ),
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional tag filter.  Only facts with at least "
                            "one of these tags are returned."
                        ),
                    },
                },
                "required": ["words"],
            },
        },
    }

    @classmethod
    async def execute(cls, coder, **kwargs):
        from cecli.helpers.memory.utils import search_facts

        response = ToolResponse(cls.NORM_NAME, result_type=cls.RESULT_TYPE)
        words = kwargs.get("words", [])
        tags = kwargs.get("tags")

        if not words or not isinstance(words, list):
            response.append_error("'words' must be a non-empty array of strings.")

            return response

        try:
            results = search_facts(coder, words=words, tags=tags)

            for r in results:
                response.append_result(
                    {
                        "id_fact": r["id_fact"],
                        "fact": r["fact"],
                        "date": r["date"],
                        "tags": r["tags"],
                    }
                )
        except Exception as exc:
            response.append_error(f"SearchFacts failed: {exc}")

        return response
