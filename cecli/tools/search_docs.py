"""SearchDocs tool - on-demand cecli documentation search for the creator agent."""

from cecli.help import locate_doc_chunk
from cecli.tools.utils.base_tool import BaseTool
from cecli.tools.utils.helpers import is_creator_coder
from cecli.tools.utils.responses import ToolResponse

_MAX_DISTANCE = 1.45
_FETCH_FACTOR = 3


class Tool(BaseTool):
    NORM_NAME = "searchdocs"
    RESULT_TYPE = "list"
    TRACK_INVOCATIONS = False
    SCHEMA = {
        "type": "function",
        "function": {
            "name": "SearchDocs",
            "description": (
                "Look up cecli's bundled documentation on demand. A query returns "
                "ranked, feed-back-able addresses (path#heading-slug) to read next; "
                "a path reads one file, section, config key, or listing. Scoped to "
                "the creator sub-agent."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "What to look up, e.g. 'custom command format', "
                            "'hook payload schema', or 'MCP server config'. Returns "
                            "ranked addresses to pass back as 'path'. Omit when "
                            "using 'path'."
                        ),
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Docs-relative path, URL, directory, or glob. An exact "
                            "file returns the whole file; 'config/' or 'config/*.md' "
                            "lists matches; '/' lists the docs root. Append #heading "
                            "or #config-key to read one section or key pair, e.g. "
                            "'config/conf.md#Merge Precedence' or "
                            "'config/conf.md#dark-mode'. A bare '#' returns the "
                            "file's outline. Omit when using 'query'."
                        ),
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["addresses", "content"],
                        "default": "addresses",
                        "description": (
                            "Query result style: 'addresses' returns ranked paths "
                            "to read next; 'content' returns documentation text "
                            "chunks with path, heading, and line range plus "
                            "navigation hints."
                        ),
                    },
                    "max_results": {
                        "type": "integer",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20,
                        "description": (
                            "Maximum number of addresses, chunks plus navigation "
                            "entries for a query, or matching files and directories "
                            "combined for a path."
                        ),
                    },
                },
                "required": [],
            },
        },
    }

    @classmethod
    async def execute(cls, coder, query=None, path=None, mode=None, max_results=5, **kwargs):
        """Search documentation, read one file, or browse docs paths.

        ``query`` returns ranked addresses unless ``mode="content"``, which
        returns text chunks plus navigation hints. ``path`` returns the whole
        markdown file for an exact match, a section or config key for an anchor,
        an outline for a bare ``#``, or matching files and subdirectories for a
        directory or glob.
        This is the creator's only documentation path: retrieval is explicit
        rather than injected automatically into the conversation.
        """
        from cecli.helpers.conversation import ConversationService

        response = ToolResponse(cls.NORM_NAME, result_type=cls.RESULT_TYPE)

        if not is_creator_coder(coder):
            response.append_error("SearchDocs is scoped to the creator sub-agent.")
            return response

        query = str(query or "").strip()
        path = str(path or "").strip()
        mode = str(mode or "addresses").strip().lower()

        if mode not in ("addresses", "content"):
            response.append_error("'mode' must be 'addresses' or 'content'.")
            return response

        if query and path:
            response.append_error("Pass either 'query' (search) or 'path' (read/browse), not both.")
            return response

        if not query and not path:
            response.append_error(
                "Provide 'query' to search or 'path' to read/browse documentation."
            )
            return response

        try:
            limit = max(1, min(int(max_results or 5), 20))
        except (TypeError, ValueError):
            limit = 5

        try:
            chunks = ConversationService.get_chunks(coder)
        except Exception as exc:
            response.append_error(f"SearchDocs failed: {exc}")
            return response

        if path:
            _append_path_results(response, chunks, coder, path, limit)
            return response

        if mode == "content":
            _append_content_results(response, chunks, coder, query, limit)
        else:
            _append_address_results(response, chunks, coder, query, limit)

        return response


def _navigation_has_results(navigation):
    return bool(navigation.get("files") or navigation.get("sections"))


def _append_path_results(response, chunks, coder, path, limit):
    retrieve_doc = getattr(chunks, "retrieve_creator_doc", None)

    if not callable(retrieve_doc):
        response.append_error("SearchDocs path lookup is unavailable.")
        return

    try:
        result = retrieve_doc(coder, path, n_results=limit)
    except Exception as exc:
        response.append_error(f"SearchDocs failed: {exc}")
        return

    if not isinstance(result, dict):
        result = {}

    if result.get("error"):
        response.append_error(str(result["error"]))
        return

    toc = result.get("toc")

    if isinstance(toc, dict):
        response.append_result(
            _format_doc_toc(toc),
            metadata={
                "type": "doc_toc",
                "path": toc.get("path", ""),
                "sections": len(toc.get("sections") or []),
                "keys": len(toc.get("keys") or []),
            },
        )
        return

    file = result.get("file")

    if file:
        response.append_result(
            _format_doc_file(file),
            metadata=_doc_file_metadata(file),
        )
        return

    files = result.get("files") or []
    dirs = result.get("dirs") or []

    if files or dirs:
        response.append_result(
            _format_doc_paths(result),
            metadata={
                "type": "doc_paths",
                "path": result.get("path", ""),
                "count": len(files) + len(dirs),
                "total": result.get("total", len(files) + len(dirs)),
            },
        )
        return

    suggestions = result.get("suggestions") or []

    if suggestions:
        response.append_result(
            _format_doc_suggestions(result),
            metadata={"type": "doc_path_suggestions", "path": result.get("path", "")},
        )
        return

    response.append_result(f"No documentation matched path={path!r}.")


def _doc_file_metadata(file):
    metadata = {
        "type": "doc_file",
        "path": file.get("path", ""),
        "url": file.get("url", ""),
        "lines": file.get("lines", 0),
    }

    if file.get("key"):
        metadata["key"] = file["key"]
        metadata["value"] = file.get("key_value", "")
        metadata["range"] = [file.get("start_line"), file.get("end_line")]
    elif file.get("section"):
        metadata["section"] = file["section"]
        metadata["level"] = file.get("level")
        metadata["range"] = [file.get("start_line"), file.get("end_line")]

    return metadata


def _format_doc_file(file):
    path = _xml_attr(file.get("path", ""))
    url = _xml_attr(file.get("url") or "")
    attrs = f' path="{path}"'
    section = _xml_attr(file.get("section") or "")
    key = _xml_attr(file.get("key") or "")
    level = _xml_attr(file.get("level", ""))
    start_line = file.get("start_line")
    end_line = file.get("end_line")
    lines = file.get("lines", 0)

    if url:
        attrs += f' url="{url}"'

    if key:
        attrs += f' key="{key}"'
        attrs += f' lines="{start_line}-{end_line}"'
        attrs += f' of_lines="{lines}"'
    elif section:
        attrs += f' section="{section}" level="{level}"'
        attrs += f' lines="{start_line}-{end_line}"'
        attrs += f' of_lines="{lines}"'
    elif lines:
        attrs += f' lines="{lines}"'

    return f"<doc_file{attrs}>\n{file.get('text', '')}\n</doc_file>"


def _doc_size_label(item):
    """Return the ``N lines, M sections`` label for one path entry."""
    label = f"{item.get('lines', 0)} lines"
    sections = item.get("sections") or 0

    if sections:
        label += f", {sections} sections"

    return label


def _format_doc_paths(result):
    files = result.get("files") or []
    dirs = result.get("dirs") or []
    count = len(files) + len(dirs)
    total = result.get("total", count)
    browse_path = result.get("path") or "."
    attrs = f' path="{browse_path}" count="{count}"'

    if total > count:
        attrs += f' total="{total}"'

    lines = [f"<doc_paths{attrs}>"]

    for item in dirs:
        lines.append(f"- {item.get('path', '')}/ (dir, {item.get('count', 0)} files)")

    for item in files:
        description = item.get("description") or ""
        url = item.get("url") or ""
        trailing = f" {description}" if description else ""

        if url:
            trailing += f" {url}"

        lines.append(f"- {item.get('path', '')} ({_doc_size_label(item)}){trailing}")

    lines.append("</doc_paths>")
    return "\n".join(lines)


def _format_doc_suggestions(result):
    path = result.get("path") or ""
    suggestions = result.get("suggestions") or []
    lines = [f'No exact match for path="{path}". Did you mean:']

    for item in suggestions:
        description = item.get("description") or ""
        url = item.get("url") or ""
        trailing = f" {description}" if description else ""

        if url:
            trailing += f" {url}"

        lines.append(f"- {item.get('path', '')} ({_doc_size_label(item)}){trailing}")

    return "\n".join(lines)


def _format_navigation(navigation, query):
    files = navigation.get("files") or []
    sections = navigation.get("sections") or []

    if not files and not sections:
        return ""

    lines = ["<doc_navigation>", f"Query terms: {query}"]

    if files:
        lines.append("Files with the most query terms:")

        for item in files:
            terms = ", ".join(item.get("matched_terms") or [])
            url = item.get("url") or ""
            url_attr = f" {url}" if url else ""
            lines.append(
                f"- {item.get('path', '')} ({item.get('score', 0)} terms: {terms}; "
                f"{item.get('section_count', 0)} matching sections){url_attr}"
            )

    if sections:
        lines.append("Sections with the most query terms:")

        for item in sections:
            terms = ", ".join(item.get("matched_terms") or [])
            url = item.get("url") or ""
            url_attr = f" {url}" if url else ""
            address = item.get("address") or ""
            address_attr = f" address={address}" if address else ""
            lines.append(
                f"- {item.get('path', '')}:{item.get('line', 0)} "
                f"{item.get('heading', '')} ({item.get('score', 0)} terms: {terms})"
                f"{url_attr}{address_attr}"
            )

    lines.append("</doc_navigation>")

    return "\n".join(lines)


def _append_dropped_notice(response, dropped):
    """Disclose results withheld for scoring below the relevance threshold."""
    if dropped <= 0:
        return

    noun = "result" if dropped == 1 else "results"
    response.append_result(
        f'<doc_notice dropped="{dropped}">{dropped} more {noun} scored below the '
        "relevance threshold.</doc_notice>",
        metadata={"type": "doc_notice", "dropped": dropped},
    )


def _append_content_results(response, chunks, coder, query, limit):
    """Append documentation chunks, a navigation block, and a floor notice."""
    try:
        docs = chunks.retrieve_creator_docs(coder, query, n_results=limit * _FETCH_FACTOR)
    except Exception as exc:
        response.append_error(f"SearchDocs failed: {exc}")
        return

    docs = docs or []
    accepted = [doc for doc in docs if doc.get("distance", 0.0) <= _MAX_DISTANCE]
    kept = accepted[:limit]
    dropped = len(docs) - len(accepted)
    navigation = {}
    retrieve_navigation = getattr(chunks, "retrieve_creator_doc_navigation", None)

    if callable(retrieve_navigation):
        try:
            navigation = retrieve_navigation(coder, query, n_files=limit, n_sections=limit)
        except Exception:
            navigation = {}

        if not isinstance(navigation, dict):
            navigation = {}

    if not kept and not _navigation_has_results(navigation):
        response.append_result("No documentation matched this query.")
        _append_dropped_notice(response, dropped)
        return

    for doc in kept:
        url = doc.get("url", "")
        document = doc.get("document", "")
        url_attr = f' from_url="{url}"' if url else ""
        location = locate_doc_chunk(doc.get("id", "")) or {}
        path = _xml_attr(location.get("path", ""))
        heading = _xml_attr(location.get("heading", ""))
        start_line = location.get("start_line")
        end_line = location.get("end_line")
        location_attrs = ""
        metadata = {"id": doc.get("id", ""), "url": url}

        if path:
            location_attrs += f' path="{path}"'
            metadata["path"] = location["path"]

        if heading:
            location_attrs += f' heading="{heading}"'
            metadata["heading"] = location["heading"]

        if start_line:
            location_attrs += f' lines="{start_line}-{end_line}"'
            metadata["range"] = [start_line, end_line]

        response.append_result(
            f"<doc{url_attr}{location_attrs}>\n{document}\n</doc>",
            metadata=metadata,
        )

    navigation_text = _format_navigation(navigation, query)

    if navigation_text:
        response.append_result(
            navigation_text,
            metadata={
                "type": "doc_navigation",
                "query": query,
                "files": len(navigation.get("files") or []),
                "sections": len(navigation.get("sections") or []),
            },
        )

    _append_dropped_notice(response, dropped)


def _append_address_results(response, chunks, coder, query, limit):
    """Append ranked, feed-back-able documentation addresses."""
    retrieve_addresses = getattr(chunks, "retrieve_creator_doc_addresses", None)

    if not callable(retrieve_addresses):
        response.append_error("Documentation address ranking is unavailable.")
        return

    try:
        result = retrieve_addresses(coder, query, n_results=limit)
    except Exception as exc:
        response.append_error(f"SearchDocs failed: {exc}")
        return

    if not isinstance(result, dict):
        result = {}

    addresses = result.get("addresses") or []

    if not addresses:
        response.append_result("No documentation matched this query.")
        return

    response.append_result(
        _format_doc_addresses(result, query),
        metadata={
            "type": "doc_addresses",
            "query": query,
            "count": len(addresses),
            "total": result.get("total", len(addresses)),
        },
    )


def _format_doc_addresses(result, query):
    """Format ranked addresses as a ``<doc_addresses>`` listing."""
    addresses = result.get("addresses") or []
    total = result.get("total") or len(addresses)
    label = _xml_attr(query)
    attrs = f' query="{label}" count="{len(addresses)}"'

    if total > len(addresses):
        attrs += f' total="{total}"'

    lines = [f"<doc_addresses{attrs}>"]

    for address in addresses:
        target = _xml_attr(address.get("address", ""))

        if address.get("kind") == "section":
            lines.append(f'- {target} {address.get("heading", "")}')
        else:
            description = address.get("description") or ""
            suffix = f" {description}" if description else ""
            lines.append(f"- {target}{suffix}")

    lines.append("</doc_addresses>")

    return "\n".join(lines)


def _format_doc_toc(toc):
    """Format a file outline as a ``<doc_toc>`` listing of resolvable slugs."""
    path = _xml_attr(toc.get("path", ""))
    url = _xml_attr(toc.get("url") or "")
    sections = toc.get("sections") or []
    keys = toc.get("keys") or []
    attrs = f' path="{path}"'

    if url:
        attrs += f' url="{url}"'

    attrs += f' count="{len(sections)}"'

    if keys:
        attrs += f' keys="{len(keys)}"'

    lines = [f"<doc_toc{attrs}>"]

    for section in sections:
        heading = section.get("heading", "")
        slug = section.get("slug", "")
        start = section.get("start", 0)
        end = max(start, section.get("end", start) - 1)
        lines.append(f"- {slug} {heading} (L{start}-{end})")

    lines.append("</doc_toc>")

    return "\n".join(lines)


def _xml_attr(value):
    """Escape a value for a quoted XML-style attribute."""
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
