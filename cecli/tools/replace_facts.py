"""ReplaceFacts tool – atomically add and/or remove facts.

Only accessible to the memorizer sub-agent.
"""

from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.responses import ToolResponse


class Tool(BaseTool):
    NORM_NAME = "replacefacts"
    RESULT_TYPE = "list"
    TRACK_INVOCATIONS = False
    VALIDATIONS = {
        "inserts": ["coerce_list"],
        "inserts[]": ["coerce_dict"],
        "deletes": ["coerce_list"],
    }
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "ReplaceFacts",
            "description": (
                "Atomically insert new facts (with optional tags) and delete "
                "stale / conflicting facts by id.  Use this to keep the fact "
                "database clean and up-to-date."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "inserts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "fact": {
                                    "type": "string",
                                    "description": "The fact text to store.",
                                },
                                "tags": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Optional tags to associate with the fact.",
                                },
                            },
                            "required": ["fact"],
                        },
                        "description": "Array of {fact, tags?} objects to insert.",
                    },
                    "deletes": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": (
                            "Optional array of fact ids to remove (use ids "
                            "returned by SearchFacts)."
                        ),
                    },
                },
                "required": ["inserts"],
            },
        },
    }

    @classmethod
    async def execute(cls, coder, **kwargs):
        from cecli.helpers.memory.utils import add_fact, remove_facts

        response = ToolResponse(cls.NORM_NAME, result_type=cls.RESULT_TYPE)
        inserts = kwargs.get("inserts", [])
        deletes = kwargs.get("deletes", [])

        if not isinstance(inserts, list):
            response.append_error("'inserts' must be an array of {fact, tags?} objects.")

            return response

        if not isinstance(deletes, list):
            deletes = []

        try:
            added = 0

            for item in inserts:
                if not isinstance(item, dict):
                    response.append_error(
                        "Each entry in 'inserts' must be an object with 'fact' and optional 'tags'."
                    )

                    continue

                fact = item.get("fact", "")

                if not fact:
                    continue

                tags = item.get("tags", [])

                if not isinstance(tags, list):
                    tags = []

                id_fact = add_fact(coder, fact=fact, tags=tags)
                added += 1

                response.append_result({"id_fact": id_fact, "action": "inserted"})

            if deletes:
                cleaned = remove_facts(
                    coder, id_facts=[int(d) for d in deletes if isinstance(d, (int, float))]
                )

                response.append_result({"count": cleaned, "action": "deleted"})

        except Exception as exc:
            response.append_error(f"ReplaceFacts failed: {exc}")

        return response
