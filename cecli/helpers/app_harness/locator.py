"""Playwright-style selectors evaluated against one accessibility snapshot.

A selector is a comma-separated list of groups. Each group is a chain of
compounds joined by descendant (a single space) or direct-child (``>``)
combinators. A compound is an optional role followed by attribute filters and
optional pseudo-classes::

    selector   := group ("," group)*
    group      := compound (combinator compound)*
    combinator := ">" | whitespace
    compound   := role? attribute* pseudo*
    role       := "*" | identifier
    attribute  := "[" key ("=" | "*=" | "^=" | "$=") value "]"
    key        := name | value | role | enabled | sensitive | offscreen
    pseudo     := ":nth(" positive-integer ")" | ":enabled" | ":visible"

Supported behaviour:

* Roles are compared case-insensitively against ``control_type`` after
  normalizing separators, so ``data_item``, ``DataItem`` and ``Data Item``
  all match the same control. ``*`` matches every role.
* ``[name=...]``, ``[value=...]`` and ``[role=...]`` are case-insensitive
  string matches. ``*=`` is substring, ``^=`` prefix and ``$=`` suffix.
  Missing names and values compare as the empty string.
* ``[enabled=true|false]``, ``[sensitive=true|false]`` and
  ``[offscreen=true|false]`` accept only ``=``. ``:enabled`` is shorthand
  for ``[enabled=true]`` and ``:visible`` for ``[offscreen=false]``.
* The bridge match spec cannot express ``offscreen``, so selectors using
  ``:visible`` or ``[offscreen=...]`` fall back to the snapshot path.
* ``:nth(n)`` is 1-based and applies to the match set produced so far by its
  compound. An out-of-range ``n`` produces no matches.
* ``>`` keeps only direct children and a space keeps all descendants, using
  the snapshot's ``id``/``parent`` links.
* Groups are unioned, returned in document order (the input list order) and
  deduplicated by id.

Value quoting accepts single or double quotes and backslash escapes. Unquoted
values may not contain whitespace. The parser raises :class:`ValueError` with
the selector and an approximate position for anything it cannot parse.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Sequence

from .constants import DEFAULT_LOCATOR_LIMIT, LOCATOR_POLL_SECONDS, TARGET_MISSING_KINDS
from .models import ActionResult, Element

if TYPE_CHECKING:
    from .client import AppHarnessError

_ATTRIBUTE_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*(\*=|\^=|\$=|=)\s*(.+)$", re.DOTALL)
_BOOLEAN_ATTRIBUTES = ("enabled", "sensitive", "offscreen")
_STRING_ATTRIBUTES = ("name", "value", "role", "automation_id")
_MATCH_OPERATORS = {"=": "eq", "*=": "contains", "^=": "prefix", "$=": "suffix"}


@dataclass(frozen=True)
class AttributeMatcher:
    """One parsed ``[key operator value]`` filter."""

    name: str
    operator: str
    value: str

    def matches(self, element: Element) -> bool:
        """Return whether ``element`` satisfies this filter."""

        if self.name in _BOOLEAN_ATTRIBUTES:
            return bool(getattr(element, self.name)) is (self.value == "true")

        if self.name == "role":
            actual = _normalize_role(element.control_type or "")
            expected = _normalize_role(self.value)
        else:
            actual = _element_string(element, self.name)
            expected = self.value

        return _string_match(actual, expected, self.operator)


@dataclass(frozen=True)
class CompoundSelector:
    """One compound in a selector chain.

    ``combinator`` is ``None`` for the first compound of a group, ``"child"``
    for ``>`` and ``"descendant"`` for a space. ``group`` distinguishes the
    comma-separated alternatives of the original selector.
    """

    role: str | None = None
    attributes: tuple[AttributeMatcher, ...] = ()
    nth: int | None = None
    combinator: str | None = None
    group: int = 0

    def matches(self, element: Element) -> bool:
        """Return whether role and attributes match, ignoring ``nth``.

        Position-based ``:nth()`` needs the surrounding match set, so it is
        applied by :func:`select` rather than here.
        """

        if self.role is not None and self.role != "*":
            if _normalize_role(self.role) != _normalize_role(element.control_type or ""):
                return False

        return all(matcher.matches(element) for matcher in self.attributes)


@dataclass(frozen=True)
class MatchPlan:
    """A server-side match spec plus the chain it was compiled from.

    ``spec`` is the ``match`` object for ``POST /api/app/find``. When
    ``compounds`` holds more than one entry, the caller re-checks the full chain
    client-side over the returned elements and their ``parent`` links.
    """

    spec: dict[str, Any]
    compounds: tuple[CompoundSelector, ...]

    @property
    def simple(self) -> bool:
        """True when the spec fully expresses a single-compound selector."""

        return len(self.compounds) == 1


def parse(selector: str) -> list[CompoundSelector]:
    """Parse ``selector`` into a flat list of compounds, in source order."""

    if not isinstance(selector, str):
        raise ValueError("selector must be a string")

    text = selector.strip()

    if not text:
        raise ValueError("selector must not be empty")

    scanner = _Scanner(text)
    compounds: list[CompoundSelector] = []
    group = 0

    while True:
        compounds.extend(_parse_group(scanner, group))
        scanner.skip_whitespace()

        if scanner.at_end():
            break

        if scanner.peek() != ",":
            scanner.fail(f"unexpected {scanner.peek()!r}")

        scanner.advance()
        scanner.skip_whitespace()

        if scanner.at_end():
            scanner.fail("expected a selector after ','")

        group += 1

    return compounds


def select(
    elements: Sequence[Element],
    selector: str | Sequence[CompoundSelector],
):
    """Return ``elements`` matching a selector, in document order.

    ``selector`` may be a selector string or the result of :func:`parse`.
    Document order is the order of the supplied list; parent links are read
    from ``Element.parent`` and identities from ``Element.id``.
    """

    compounds = parse(selector) if isinstance(selector, str) else list(selector)

    if not compounds:
        return []

    ordered = list(elements)
    matched_ids: set[int] = set()

    for group in _group_compounds(compounds):
        matched_ids.update(element.id for element in _evaluate_group(ordered, group))

    selected: list[Element] = []
    seen_ids: set[int] = set()

    for element in ordered:
        if element.id in matched_ids and element.id not in seen_ids:
            seen_ids.add(element.id)
            selected.append(element)

    return selected


def compile_match(selector: str | Sequence[CompoundSelector]) -> MatchPlan | None:
    """Compile the last compound of a selector into a server match spec.

    Returns ``None`` when the server cannot express the selector faithfully:
    multiple groups, ``:nth()``, a wildcard trailing compound in a chain, or an
    ancestor that cannot be requested by role. Callers then fall back to the
    snapshot path. Only the last compound carries the name/value/state filters;
    ancestor roles are added to ``roles`` so their nodes come back for parent
    link traversal.
    """

    compounds = parse(selector) if isinstance(selector, str) else list(selector)

    if not compounds:
        return None

    groups = _group_compounds(compounds)

    if len(groups) != 1:
        return None

    group = groups[0]
    last = group[-1]

    if last.nth is not None:
        return None

    if len(group) > 1 and last.role in (None, "*"):
        return None

    spec: dict[str, Any] = {}
    roles: list[str] = []

    if last.role and last.role != "*":
        roles.append(last.role)

    for matcher in last.attributes:

        if matcher.name == "role":

            if matcher.operator != "=" or last.role or matcher.value == "*":
                return None

            roles.append(matcher.value)
        elif matcher.name in ("name", "value"):

            if matcher.name in spec:
                return None

            spec[matcher.name] = {
                "op": _MATCH_OPERATORS[matcher.operator],
                "value": matcher.value,
            }
        else:

            if matcher.name in spec:
                return None

            if matcher.name == "offscreen":
                return None
            spec[matcher.name] = matcher.value == "true"

    for compound in group[:-1]:

        if compound.nth is not None or compound.attributes:
            return None

        if compound.role in (None, "*"):
            return None

        if compound.role not in roles:
            roles.append(compound.role)

    if roles:
        spec["roles"] = roles

    return MatchPlan(spec=spec, compounds=tuple(group))


class Locator:
    """A selector bound to a window that re-resolves before every action."""

    def __init__(
        self,
        client: Any,
        window: str,
        selector: str,
        *,
        timeout_ms: int | None = None,
        limit: int = DEFAULT_LOCATOR_LIMIT,
        max_depth: int | None = None,
        max_elements: int | None = None,
        exclude_roles: Sequence[str] | None = None,
    ) -> None:
        """Parse ``selector`` eagerly so malformed input fails fast."""

        try:
            parse(selector)
        except ValueError as exc:
            from .client import AppHarnessError

            raise AppHarnessError("invalid_request", str(exc)) from exc

        self.client = client
        self.window = window
        self._selector = selector
        self.limit = limit
        self.max_depth = max_depth
        self.max_elements = max_elements
        self.exclude_roles = exclude_roles
        self.timeout_ms = max(1, client.timeout_ms if timeout_ms is None else timeout_ms)

    def selector(self) -> str:
        """The selector string this locator resolves."""

        return self._selector

    def click(self, at: Any = None, button: str = "left", count: int = 1) -> ActionResult:
        """Click the resolved element, or a screen point inside it."""

        element = self.wait()

        if at is None and button == "left" and count == 1:
            return self._dispatch("click", element)

        return element.click(at=at, button=button, count=count)

    def double_click(self, at: Any = "center") -> ActionResult:
        """Double-click the resolved element at ``at``."""

        return self.wait().double_click(at=at)

    def right_click(self, at: Any = "center") -> ActionResult:
        """Right-click the resolved element at ``at``."""

        return self.wait().right_click(at=at)

    def hover(self, at: Any = "center") -> ActionResult:
        """Move the pointer over the resolved element at ``at``."""

        return self.wait().hover(at=at)

    def invoke(self) -> ActionResult:
        """Invoke the resolved element's default action."""

        return self._dispatch("invoke", self.wait())

    def set_value(self, value: str) -> ActionResult:
        """Write ``value`` to the resolved element."""

        return self._dispatch("set_value", self.wait(), value=value)

    def get_value(self) -> ActionResult:
        """Read the resolved element's value."""

        return self._dispatch("get_value", self.wait())

    def focus(self) -> ActionResult:
        """Move focus to the resolved element."""

        return self._dispatch("focus", self.wait())

    def select(self) -> ActionResult:
        """Select the resolved element itself."""

        return self.wait().select()

    def scroll_into_view(self) -> ActionResult:
        """Scroll the resolved element into view."""

        return self.wait().scroll_into_view()

    def scroll_to(
        self, horizontal: float | None = None, vertical: float | None = None
    ) -> ActionResult:
        """Scroll the resolved element to a percentage along either axis."""

        return self.wait().scroll_to(horizontal=horizontal, vertical=vertical)

    def type_text(self, text: str, replace: bool = True, commit: bool = False) -> ActionResult:
        """Type literal ``text`` into the resolved element."""

        return self.wait().type_text(text, replace=replace, commit=commit)

    def edit_text(self, text: str) -> ActionResult:
        """Replace the resolved element's text with ``text``."""

        return self.wait().edit_text(text)

    def nth(self, index: int, timeout_ms: int | None = None) -> Element:
        """Return the one-based ``index`` match, polling until it appears."""

        if isinstance(index, bool) or not isinstance(index, int) or index < 1:
            raise ValueError("nth index is 1-based and must be a positive integer")

        return self._poll_nth(index, timeout_ms)

    def pick(self, predicate: Callable[[Element], bool], timeout_ms: int | None = None) -> Element:
        """Return the single current match satisfying ``predicate``."""

        return self._poll_pick(predicate, timeout_ms)

    def all(self, limit: int | None = None) -> list[Element]:
        """Return every current match without requiring a single hit."""

        matches, count, _ = self.client.find_elements(
            self.window,
            self._selector,
            self.limit,
            self.max_depth,
            self.max_elements,
            self.exclude_roles,
        )

        if limit is not None and limit >= 0:
            matches = matches[:limit]

        return [self._bind(element) for element in matches]

    def cell(self, row: int, column: int) -> ActionResult:
        """Address one cell of the grid this locator resolves to.

        The grid is re-resolved first, so a sheet switch or a new workbook cannot
        silently redirect the lookup to another table.
        """

        self.client.snapshot(self.window, self.max_depth, self.max_elements, self.exclude_roles)
        grid = self.wait()

        return self.client.cell_at(self.window, row, column, _target_for(grid))

    def wait(self, timeout_ms: int | None = None) -> Element:
        """Return the single match, polling until it appears or time runs out."""

        return self._poll(lambda element: True, timeout_ms=timeout_ms, state_label=None)

    def wait_for(
        self,
        *,
        visible: bool | None = None,
        enabled: bool | None = None,
        value: str | None = None,
        timeout_ms: int | None = None,
    ) -> Element:
        """Return the single match once every requested state holds.

        ``visible`` requires the element to be on screen (``offscreen`` false),
        ``enabled`` requires the control state and ``value`` compares exactly. A
        missing element raises ``not_found`` while an element that never reaches
        the requested state raises ``timeout``.
        """

        def state_holds(element: Element) -> bool:
            if visible is not None and bool(element.offscreen) == visible:
                return False

            if enabled is not None and bool(element.enabled) is not enabled:
                return False

            if value is not None and (element.value or "") != value:
                return False

            return True

        state_label = self._state_label(visible, enabled, value)

        return self._poll(state_holds, timeout_ms=timeout_ms, state_label=state_label)

    def _dispatch(self, action: str, element: Element, value: str | None = None) -> ActionResult:
        """Send a semantic action for ``element`` through the client."""

        from .client import AppHarnessError

        target = _target_for(element)

        try:
            if action == "click":
                return self.client.click(self.window, target)

            if action == "invoke":
                return self.client.invoke(self.window, target)

            if action == "set_value":
                return self.client.set_value(
                    self.window, value if value is not None else "", target
                )

            if action == "get_value":
                return self.client.get_value(self.window, target)

            return self.client.focus(self.window, target)
        except AppHarnessError as exc:
            if exc.kind in TARGET_MISSING_KINDS:
                raise AppHarnessError(
                    "stale_target",
                    f"element for {self._selector!r} disappeared before {action}: {exc}",
                ) from exc

            raise

    def _poll(
        self,
        predicate: Callable[[Element], bool],
        *,
        timeout_ms: int | None,
        state_label: str | None,
    ) -> Element:
        """Poll ``find_elements`` until one match satisfies ``predicate``."""

        timeout = max(1, self.timeout_ms if timeout_ms is None else timeout_ms)
        deadline = time.monotonic() + timeout / 1000.0
        saw_element = False

        while True:
            self.client.refresh()
            matches, count, _ = self._find_matches()

            if count > 1:
                from .client import AppHarnessError

                raise AppHarnessError("invalid_request", self._ambiguous_message(matches, count))

            if count == 1 and matches and predicate(matches[0]):
                return self._bind(matches[0])

            if count == 1 and matches:
                saw_element = True

            remaining = deadline - time.monotonic()

            if remaining <= 0:
                raise self._timeout_error(timeout, saw_element=saw_element, state_label=state_label)

            time.sleep(min(LOCATOR_POLL_SECONDS, remaining))

    def _poll_nth(self, index: int, timeout_ms: int | None) -> Element:
        """Poll until at least ``index`` matches exist, then return that one."""

        timeout = max(1, self.timeout_ms if timeout_ms is None else timeout_ms)
        deadline = time.monotonic() + timeout / 1000.0

        while True:
            self.client.refresh()
            matches, count, _ = self._find_matches()

            if len(matches) >= index:
                return self._bind(matches[index - 1])

            remaining = deadline - time.monotonic()

            if remaining <= 0:
                from .client import AppHarnessError

                raise AppHarnessError(
                    "not_found",
                    f"selector {self._selector!r} matched {max(len(matches), count)} "
                    f"elements in window {self.window!r}; wanted #{index} after {timeout} ms",
                )

            time.sleep(min(LOCATOR_POLL_SECONDS, remaining))

    def _poll_pick(self, predicate: Callable[[Element], bool], timeout_ms: int | None) -> Element:
        """Poll until exactly one match satisfies ``predicate``."""

        timeout = max(1, self.timeout_ms if timeout_ms is None else timeout_ms)
        deadline = time.monotonic() + timeout / 1000.0

        while True:
            self.client.refresh()
            matches, _, _ = self._find_matches()
            selected = [element for element in matches if predicate(element)]

            if len(selected) == 1:
                return self._bind(selected[0])

            if len(selected) > 1:
                from .client import AppHarnessError

                raise AppHarnessError(
                    "invalid_request",
                    f"predicate matched {len(selected)} elements for {self._selector!r} "
                    f"in window {self.window!r}; use a narrower predicate",
                )

            remaining = deadline - time.monotonic()

            if remaining <= 0:
                from .client import AppHarnessError

                raise AppHarnessError(
                    "not_found",
                    f"no element for {self._selector!r} in window {self.window!r} "
                    f"satisfied the predicate after {timeout} ms",
                )

            time.sleep(min(LOCATOR_POLL_SECONDS, remaining))

    def _find_matches(self) -> tuple[list[Element], int, bool]:
        """Return the current selector matches, count and truncation flag."""

        return self.client.find_elements(
            self.window,
            self._selector,
            self.limit,
            self.max_depth,
            self.max_elements,
            self.exclude_roles,
        )

    def _bind(self, element: Element) -> Element:
        """Attach this locator's client and window to ``element``."""

        return element.bind(self.client, self.window)

    def _ambiguous_message(self, matches: Sequence[Element], count: int) -> str:
        """Describe an ambiguous selector result."""

        candidates = ", ".join(_describe(element) for element in matches[:3]) or "none listed"

        return (
            f"selector {self._selector!r} matched {count} elements in window "
            f"{self.window!r}; use a more specific selector. "
            f"First candidates: {candidates}"
        )

    def _state_label(
        self, visible: bool | None, enabled: bool | None, value: str | None
    ) -> str | None:
        """Describe the requested states for timeout messages."""

        parts: list[str] = []

        if visible is not None:
            parts.append("visible" if visible else "offscreen")

        if enabled is not None:
            parts.append("enabled" if enabled else "disabled")

        if value is not None:
            parts.append(f"value {value!r}")

        return " and ".join(parts) or None

    def _timeout_error(
        self, timeout: int, *, saw_element: bool, state_label: str | None
    ) -> AppHarnessError:
        """Build a ``timeout`` or ``not_found`` error for an exhausted poll."""

        from .client import AppHarnessError

        if saw_element and state_label is not None:
            return AppHarnessError(
                "timeout",
                f"element for {self._selector!r} in window {self.window!r} did not become "
                f"{state_label} after {timeout} ms",
            )

        return AppHarnessError(
            "not_found",
            f"no element matches {self._selector!r} in window {self.window!r} "
            f"after {timeout} ms",
        )


def _target_for(element: Element) -> dict[str, Any]:
    """Return the minimal bridge reference for ``element``."""

    target: dict[str, Any] = {"id": element.id}

    if element.runtime_id:
        target["runtime_id"] = element.runtime_id

    if element.path:
        target["path"] = element.path

    return target


def _describe(element: Element) -> str:
    """Describe one element for ambiguity messages."""

    label = element.control_type or "?"

    if element.name:
        label = f"{label} {element.name!r}"

    return f"{label} (id={element.id})"


def _group_compounds(compounds: Sequence[CompoundSelector]) -> list[list[CompoundSelector]]:
    groups: list[list[CompoundSelector]] = []

    for compound in compounds:

        if not groups or compound.combinator is None:
            groups.append([compound])
        else:
            groups[-1].append(compound)

    return groups


def _evaluate_group(
    elements: Sequence[Element], compounds: Sequence[CompoundSelector]
) -> list[Element]:
    selected: list[Element] = []

    for index, compound in enumerate(compounds):

        if index == 0:
            candidates = list(elements)
        elif compound.combinator == "child":
            parent_ids = {element.id for element in selected}
            candidates = [element for element in elements if element.parent in parent_ids]
        else:
            candidates = _descendants(elements, {element.id for element in selected})

        selected = [element for element in candidates if compound.matches(element)]

        if compound.nth is not None:

            if 0 < compound.nth <= len(selected):
                selected = [selected[compound.nth - 1]]
            else:
                selected = []

    return selected


def _descendants(elements: Sequence[Element], root_ids: set[int]) -> list[Element]:
    children: dict[int, list[int]] = {}

    for element in elements:

        if element.parent is not None:
            children.setdefault(element.parent, []).append(element.id)

    descendant_ids: set[int] = set()
    frontier = set(root_ids)

    while frontier:
        next_frontier: set[int] = set()

        for parent_id in frontier:

            for child_id in children.get(parent_id, ()):

                if child_id not in descendant_ids:
                    descendant_ids.add(child_id)
                    next_frontier.add(child_id)

        frontier = next_frontier

    return [element for element in elements if element.id in descendant_ids]


def _parse_group(scanner: _Scanner, group: int) -> list[CompoundSelector]:
    scanner.skip_whitespace()

    if scanner.at_end() or scanner.peek() in (",", ">"):
        scanner.fail("expected a selector")

    compounds = [_parse_compound(scanner, group, combinator=None)]

    while True:
        had_whitespace = scanner.skip_whitespace()

        if scanner.at_end() or scanner.peek() == ",":
            break

        if scanner.peek() == ">":
            scanner.advance()
            scanner.skip_whitespace()

            if scanner.at_end() or scanner.peek() in (",", ">"):
                scanner.fail("expected a selector after '>'")

            combinator = "child"
        elif had_whitespace:
            combinator = "descendant"
        else:
            scanner.fail(f"unexpected {scanner.peek()!r}")

        compounds.append(_parse_compound(scanner, group, combinator=combinator))

    return compounds


def _parse_compound(scanner: _Scanner, group: int, combinator: str | None) -> CompoundSelector:
    role: str | None = None

    if scanner.peek() == "*":
        role = "*"
        scanner.advance()
    elif scanner.peek().isalpha() or scanner.peek() == "_":
        role = scanner.read_identifier()

    attributes: list[AttributeMatcher] = []
    nth: int | None = None

    while scanner.peek() == "[":
        attributes.append(_parse_attribute(scanner))

    while scanner.peek() == ":":
        parsed_nth, state = _parse_pseudo(scanner)

        if parsed_nth is not None:
            nth = parsed_nth

        if state is not None:
            attributes.append(state)

    if role is None and not attributes and nth is None:
        scanner.fail("expected a role, attribute selector or pseudo-class")

    return CompoundSelector(
        role=role,
        attributes=tuple(attributes),
        nth=nth,
        combinator=combinator,
        group=group,
    )


def _parse_attribute(scanner: _Scanner) -> AttributeMatcher:
    body = scanner.read_bracket_body()
    match = _ATTRIBUTE_PATTERN.match(body.strip())

    if match is None:
        scanner.fail(f"invalid attribute selector [{body}]")

    name, operator, raw_value = match.groups()
    name = name.lower()

    if name not in _BOOLEAN_ATTRIBUTES and name not in _STRING_ATTRIBUTES:
        scanner.fail(f"unsupported attribute {name!r}")

    value = _unquote(raw_value, scanner)

    if name in _BOOLEAN_ATTRIBUTES:

        if operator != "=":
            scanner.fail(f"[{name}] only supports '='")

        if value.lower() not in ("true", "false"):
            scanner.fail(f"[{name}] expects true or false")

        value = value.lower()

    return AttributeMatcher(name=name, operator=operator, value=value)


def _parse_pseudo(scanner: _Scanner) -> tuple[int | None, AttributeMatcher | None]:
    """Parse one pseudo-class into an ``nth`` index or a state matcher."""

    scanner.advance()
    name = scanner.read_identifier()

    if not name:
        scanner.fail("expected a pseudo-class after ':'")

    lowered = name.lower()

    if lowered == "enabled":
        return None, AttributeMatcher(name="enabled", operator="=", value="true")

    if lowered == "visible":
        return None, AttributeMatcher(name="offscreen", operator="=", value="false")

    if lowered != "nth":
        scanner.fail(f"unsupported pseudo-class ':{name}'")

    if scanner.peek() != "(":
        scanner.fail("expected '(' after :nth")

    scanner.advance()
    digits = scanner.read_digits()

    if not digits:
        scanner.fail(":nth expects a positive integer")

    if scanner.peek() != ")":
        scanner.fail("expected ')' after :nth argument")

    scanner.advance()
    value = int(digits)

    if value < 1:
        scanner.fail(":nth expects a positive integer")

    return value, None


def _unquote(raw: str, scanner: _Scanner) -> str:
    value = raw.strip()

    if value and value[0] in ("'", '"'):

        if len(value) < 2 or value[-1] != value[0]:
            scanner.fail("unterminated quoted value")

        value = value[1:-1]

    elif any(character.isspace() for character in value):
        scanner.fail("values containing whitespace must be quoted")

    return _unescape(value)


def _unescape(value: str) -> str:
    characters: list[str] = []
    index = 0

    while index < len(value):

        if value[index] == "\\" and index + 1 < len(value):
            characters.append(value[index + 1])
            index += 2
            continue

        characters.append(value[index])
        index += 1

    return "".join(characters)


def _normalize_role(role: str) -> str:
    return re.sub(r"[^a-z0-9]", "", role.casefold())


def _element_string(element: Element, name: str) -> str:
    return getattr(element, name, None) or ""


def _string_match(actual: str, expected: str, operator: str) -> bool:
    actual = actual.casefold()
    expected = expected.casefold()

    if operator == "=":
        return actual == expected

    if operator == "*=":
        return expected in actual

    if operator == "^=":
        return actual.startswith(expected)

    return actual.endswith(expected)


class _Scanner:
    """Cursor over a selector string with selector-aware error messages."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.position = 0

    def at_end(self) -> bool:
        return self.position >= len(self.text)

    def peek(self) -> str:
        return "" if self.at_end() else self.text[self.position]

    def advance(self) -> None:
        self.position += 1

    def skip_whitespace(self) -> bool:
        start = self.position

        while not self.at_end() and self.text[self.position].isspace():
            self.position += 1

        return self.position > start

    def read_identifier(self) -> str:
        start = self.position

        while not self.at_end() and (
            self.text[self.position].isalnum() or self.text[self.position] == "_"
        ):
            self.position += 1

        return self.text[start : self.position]

    def read_digits(self) -> str:
        start = self.position

        while not self.at_end() and self.text[self.position].isdigit():
            self.position += 1

        return self.text[start : self.position]

    def read_bracket_body(self) -> str:
        start = self.position
        self.advance()
        quote = ""

        while not self.at_end():
            character = self.text[self.position]

            if quote:

                if character == "\\":
                    self.advance()

                    if not self.at_end():
                        self.advance()

                    continue

                if character == quote:
                    quote = ""

                self.advance()
                continue

            if character in ("'", '"'):
                quote = character
            elif character == "]":
                body = self.text[start + 1 : self.position]
                self.advance()
                return body
            elif character == "[":
                self.fail("nested '[' is not allowed")

            self.advance()

        self.fail("unterminated '['")

    def fail(self, message: str) -> None:
        raise ValueError(
            f"invalid selector {self.text!r} at position {self.position + 1}: {message}"
        )
