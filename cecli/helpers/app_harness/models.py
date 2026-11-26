"""Data models for app-harness bridge responses.

The shapes mirror ``crates/ce-app-bridge/src/protocol.rs``. Every model exposes
``from_dict`` and tolerates missing or null fields, because the bridge may omit
optional data and older bridges answer with a subset of the fields.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Point:
    """A screen-space point in physical pixels."""

    x: int = 0
    y: int = 0

    def to_dict(self) -> dict[str, int]:
        """Return a JSON-serializable representation."""

        return {"x": self.x, "y": self.y}


@dataclass
class Rect:
    """A screen-space rectangle in physical pixels."""

    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Rect:
        """Build a rectangle from a bridge payload."""

        data = data or {}
        return cls(
            left=_as_int(data.get("left")),
            top=_as_int(data.get("top")),
            width=_as_int(data.get("width")),
            height=_as_int(data.get("height")),
        )

    @property
    def right(self) -> int:
        """Right edge of the rectangle."""

        return self.left + self.width

    @property
    def bottom(self) -> int:
        """Bottom edge of the rectangle."""

        return self.top + self.height

    @property
    def center(self) -> Point:
        """Center of the rectangle."""

        return Point(self.left + self.width // 2, self.top + self.height // 2)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)


@dataclass
class Window:
    """A visible top-level application window."""

    handle: str = ""
    pid: int = 0
    process_name: str | None = None
    title: str = ""
    class_name: str | None = None
    bounds: Rect | None = None
    foreground: bool = False
    dialog: bool = False
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Window:
        """Build a window from a bridge payload."""

        data = data or {}
        return cls(
            handle=_as_str(data.get("handle")),
            pid=_as_int(data.get("pid")),
            process_name=_as_optional_str(data.get("process_name")),
            title=_as_str(data.get("title")),
            class_name=_as_optional_str(data.get("class_name")),
            bounds=_as_rect(data.get("bounds")),
            foreground=_as_bool(data.get("foreground")),
            dialog=_as_bool(data.get("dialog")),
            enabled=_as_bool(data.get("enabled"), default=True),
        )

    @property
    def process_id(self) -> int:
        """Alias for :attr:`pid`."""

        return self.pid

    @property
    def center(self) -> Point | None:
        """Center of the window bounds when the bridge supplied them."""

        return self.bounds.center if self.bounds is not None else None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)


@dataclass
class ScrollState:
    """Scroll position and viewport share as percentages."""

    horizontal_percent: float | None = None
    vertical_percent: float | None = None
    horizontal_view_percent: float | None = None
    vertical_view_percent: float | None = None
    horizontal: bool = False
    vertical: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation without empty fields."""

        data: dict[str, Any] = {}

        for key in (
            "horizontal_percent",
            "vertical_percent",
            "horizontal_view_percent",
            "vertical_view_percent",
        ):
            value = getattr(self, key)

            if value is not None:
                data[key] = value

        if self.horizontal:
            data["horizontal"] = True

        if self.vertical:
            data["vertical"] = True

        return data


@dataclass
class Element:
    """One accessibility node inside a window snapshot."""

    id: int = 0
    runtime_id: str = ""
    control_type: str = ""
    name: str | None = None
    automation_id: str | None = None
    class_name: str | None = None
    value: str | None = None
    enabled: bool = True
    offscreen: bool = False
    bounds: Rect | None = None
    patterns: list[str] = field(default_factory=list)
    sensitive: bool = False
    depth: int = 0
    parent: int | None = None
    path: str | None = None
    scroll: ScrollState | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Element:
        """Build an element from a bridge payload."""

        data = data or {}
        return cls(
            id=_as_int(data.get("id")),
            runtime_id=_as_str(data.get("runtime_id")),
            control_type=_as_str(data.get("control_type")),
            name=_as_optional_str(data.get("name")),
            automation_id=_as_optional_str(data.get("automation_id")),
            class_name=_as_optional_str(data.get("class_name")),
            value=_as_optional_str(data.get("value")),
            enabled=_as_bool(data.get("enabled"), default=True),
            offscreen=_as_bool(data.get("offscreen")),
            bounds=_as_rect(data.get("bounds")),
            patterns=_as_str_list(data.get("patterns")),
            sensitive=_as_bool(data.get("sensitive")),
            depth=_as_int(data.get("depth")),
            parent=_as_optional_int(data.get("parent")),
            path=_as_optional_str(data.get("path")),
            scroll=_as_scroll_state(data.get("scroll")),
        )

    @property
    def role(self) -> str:
        """Alias for :attr:`control_type` used by selector arguments."""

        return self.control_type

    def bind(self, client: Any, window: Any) -> Element:
        """Attach the client and window used by action methods."""

        object.__setattr__(self, "_client", client)
        object.__setattr__(self, "_window", window)

        return self

    @property
    def center(self) -> Point | None:
        """Center of the element bounds when the bridge supplied them."""

        return self.bounds.center if self.bounds is not None else None

    def target(self) -> dict[str, Any]:
        """Return the bridge element reference for this control."""

        target: dict[str, Any] = {"id": self.id}

        if self.runtime_id:
            target["runtime_id"] = self.runtime_id

        if self.path:
            target["path"] = self.path

        if self.automation_id:
            target["automation_id"] = self.automation_id

        if self.name:
            target["name"] = self.name

        if self.role:
            target["role"] = self.role

        return target

    def selector(self) -> str:
        """Return the most stable selector expression for this control."""

        if self.automation_id:
            return f'[automation_id="{_selector_value(self.automation_id)}"]'
        role = self.role or "*"
        if self.name:
            return f'{role}[name="{_selector_value(self.name)}"]'

        return role

    def click(
        self,
        at: Any = None,
        button: str = "left",
        count: int = 1,
        pointer: bool = False,
    ) -> ActionResult:
        """Click the control semantically or at a screen point."""

        if at is None and not pointer:
            if button == "left" and count == 1:
                client, window = self._require_binding()

                return client.click(window, self.target())

            return self._action("click", button=button, count=count)

        point = self._pointer_point(at)

        if button == "left" and count == 1:
            client, window = self._require_binding()

            return client.click(window, self.target(), point.to_dict())

        return self._action("click", point=point.to_dict(), button=button, count=count)

    def double_click(self, at: Any = "center") -> ActionResult:
        """Double-click the control at ``at``."""

        return self._pointer_action("double_click", at)

    def right_click(self, at: Any = "center") -> ActionResult:
        """Right-click the control at ``at``."""

        return self._pointer_action("right_click", at)

    def hover(self, at: Any = "center") -> ActionResult:
        """Move the pointer over the control at ``at``."""

        return self._pointer_action("hover", at)

    def invoke(self) -> ActionResult:
        """Invoke the control's default action."""

        return self._action("invoke")

    def set_value(self, value: str) -> ActionResult:
        """Write ``value`` to the control."""

        return self._action("set_value", value=value)

    def get_value(self) -> ActionResult:
        """Read the control's value."""

        return self._action("get_value")

    def focus(self) -> ActionResult:
        """Move focus to the control."""

        return self._action("focus")

    def select(self) -> ActionResult:
        """Select the control itself."""

        return self._action("select")

    @property
    def scroll_position(self) -> tuple[float | None, float | None]:
        """Return ``(horizontal, vertical)`` scroll percentages when known."""

        if self.scroll is None:
            return (None, None)

        return (self.scroll.horizontal_percent, self.scroll.vertical_percent)

    def scroll_to(
        self, horizontal: float | None = None, vertical: float | None = None
    ) -> ActionResult:
        """Scroll this control to a percentage along either axis."""

        return self._action("scroll_to", horizontal_percent=horizontal, vertical_percent=vertical)

    def scroll_into_view(self) -> ActionResult:
        """Scroll the control into view."""

        return self._action("scroll_into_view")

    def type_text(self, text: str, replace: bool = True, commit: bool = False) -> ActionResult:
        """Type literal ``text`` into the control."""

        client, window = self._require_binding()
        method = getattr(client, "type_text", None)

        if callable(method):
            return method(window, text, self.target(), replace=replace, commit=commit)

        return self._action("type_text", text=text)

    def edit_text(self, text: str) -> ActionResult:
        """Replace the control's text with ``text``."""

        client, window = self._require_binding()
        method = getattr(client, "edit_text", None)

        if callable(method):
            return method(window, text, self.target())

        return self._action("edit_text", text=text)

    def to_dict(self, lean: bool = False) -> dict[str, Any]:
        """Return a JSON-serializable representation.

        A lean record keeps only what is needed to choose and drive a control:
        identity, tree position, role, label, value, state flags and compact
        geometry strings. Runtime ids and pattern lists stay behind
        ``--verbose``.
        """

        data = asdict(self)

        if not lean:
            return data

        return {
            "id": data["id"],
            "parent": data["parent"],
            "depth": data["depth"],
            "control_type": data["control_type"],
            "name": data["name"],
            "value": data["value"],
            "enabled": data["enabled"],
            "offscreen": data["offscreen"],
            "sensitive": data["sensitive"],
            "bounds": _format_bounds(self.bounds),
            "center": _format_point(self.center),
            "scroll": _format_scroll(self.scroll),
        }

    def __str__(self) -> str:
        """Render one line of the human-readable snapshot tree."""

        parts = [f"[{self.id}]", self.control_type or "?"]

        if self.name:
            parts.append(f'"{self.name}"')

        if self.value is not None and self.value != "":
            parts.append(f"= {self.value}")

        flags = []

        if self.sensitive:
            flags.append("sensitive")

        if self.offscreen:
            flags.append("offscreen")

        if not self.enabled:
            flags.append("disabled")

        if flags:
            parts.append("(" + ", ".join(flags) + ")")

        return " ".join(parts)

    def _action(self, action: str, **args: Any) -> ActionResult:
        """Send ``action`` for this element through the bound client."""

        client, window = self._require_binding()

        return client.action(window, action, target=self.target(), **args)

    def _pointer_action(self, action: str, at: Any) -> ActionResult:
        """Resolve ``at`` to a screen point and send a pointer action."""

        point = self._pointer_point(at)

        return self._action(action, point=point.to_dict())

    def _pointer_point(self, at: Any) -> Point:
        """Resolve ``at`` to a :class:`Point`, defaulting to the center."""

        if at is None or at == "center":
            center = self.center

            if center is None:
                raise ValueError(f"element {self.id} has no bounds for a pointer action")

            return center

        if isinstance(at, Point):
            return at

        if isinstance(at, dict):

            if "x" in at and "y" in at:
                return Point(int(at["x"]), int(at["y"]))

            raise ValueError("point mapping needs x and y")

        if isinstance(at, (tuple, list)) and len(at) == 2:
            return Point(int(at[0]), int(at[1]))

        raise ValueError(f"unsupported point {at!r}; use 'center', Point, (x, y) or {{x, y}}")

    def _require_binding(self) -> tuple[Any, Any]:
        """Return the bound client/window or raise a clear error."""

        client = getattr(self, "_client", None)
        window = getattr(self, "_window", None)

        if client is None or window is None:
            from .client import AppHarnessError

            raise AppHarnessError(
                "invalid_request",
                f"element {self.id} is not bound to a client; call Element.bind(client, window) "
                "or Snapshot.bind(...) before acting",
            )

        return client, window


@dataclass
class Snapshot:
    """A window together with its flattened element tree."""

    window: Window | None = None
    elements: list[Element] = field(default_factory=list)
    truncated: bool = False
    max_depth: int = 0
    max_elements: int = 0
    total_elements: int = 0
    truncated_by: str | None = None
    children_cut: bool = False
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any] | None,
        client: Any = None,
        window: Any = None,
    ) -> Snapshot:
        """Build a snapshot from a bridge payload."""

        data = data or {}
        raw_elements = data.get("elements")
        elements = (
            [_as_element(item) for item in raw_elements] if isinstance(raw_elements, list) else []
        )
        window_data = data.get("window")
        total = _as_optional_int(data.get("total_elements"))
        snapshot = cls(
            window=Window.from_dict(window_data) if isinstance(window_data, dict) else None,
            elements=elements,
            truncated=_as_bool(data.get("truncated")),
            max_depth=_as_int(data.get("max_depth")),
            max_elements=_as_int(data.get("max_elements")),
            total_elements=total if total is not None else len(elements),
            truncated_by=_as_optional_str(data.get("truncated_by")),
            children_cut=_as_bool(data.get("children_cut")),
            notes=_as_str_list(data.get("notes")),
        )

        if client is not None:
            snapshot.bind(client, window)

        return snapshot

    def bind(self, client: Any, window: Any = None) -> Snapshot:
        """Attach ``client`` and ``window`` to this snapshot's elements."""

        if window is None and self.window is not None:
            window = self.window.handle or self.window.title or None

        for element in self.elements:
            element.bind(client, window)

        object.__setattr__(self, "_client", client)
        object.__setattr__(self, "_window", window)

        return self

    def find(
        self,
        name: str | None = None,
        role: str | None = None,
        automation_id: str | None = None,
    ) -> Element | None:
        """Return the first element matching every provided selector."""

        for element in self.elements:
            if name is not None and element.name != name:
                continue

            if role is not None and not _matches_role(element.control_type, role):
                continue

            if automation_id is not None and element.automation_id != automation_id:
                continue

            return element

        return None

    @property
    def summary(self) -> str:
        """One-line description of the snapshot for scripts and logs."""

        title = self.window.title if self.window else ""
        suffix = " (truncated)" if self.truncated else ""
        return f"{title or '<window>'}: {len(self.elements)}/{self.total_elements} elements{suffix}"

    def to_dict(self, lean: bool = False) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        data = asdict(self)

        if not data.get("notes"):
            data.pop("notes", None)

        if lean:
            data["elements"] = [element.to_dict(lean=True) for element in self.elements]

        return data


@dataclass
class ActionResult:
    """Outcome of an action request."""

    action: str = ""
    delivered: bool = False
    verified: bool = False
    uncertain: bool = False
    value: str | None = None
    message: str | None = None
    element: dict[str, Any] | None = None
    outcome: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ActionResult:
        """Build an action result from a bridge payload."""

        data = data or {}
        return cls(
            action=_as_str(data.get("action")),
            delivered=_as_bool(data.get("delivered")),
            verified=_as_bool(data.get("verified")),
            uncertain=_as_bool(data.get("uncertain")),
            value=_as_optional_str(data.get("value")),
            message=_as_optional_str(data.get("message")),
            element=_as_element_dict(data.get("element")),
            outcome=_as_optional_str(data.get("outcome")),
        )

    @property
    def ok(self) -> bool:
        """True when the action was delivered and confirmed."""

        return self.delivered and self.verified and not self.uncertain

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)


@dataclass
class CheckResult:
    """One diagnostic check from a doctor report."""

    name: str = ""
    ok: bool = False
    detail: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CheckResult:
        """Build a check result from a bridge payload."""

        data = data or {}
        return cls(
            name=_as_str(data.get("name")),
            ok=_as_bool(data.get("ok")),
            detail=_as_str(data.get("detail")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)


@dataclass
class DoctorReport:
    """Backend and permission diagnostics."""

    platform: str = ""
    backend: str = ""
    health: str = "unavailable"
    permissions: dict[str, str] = field(default_factory=dict)
    checks: list[CheckResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> DoctorReport:
        """Build a doctor report from a bridge payload."""

        data = data or {}
        permissions = data.get("permissions")
        checks = data.get("checks")
        return cls(
            platform=_as_str(data.get("platform")),
            backend=_as_str(data.get("backend")),
            health=_as_str(data.get("health"), default="unavailable"),
            permissions=(
                {str(key): str(value) for key, value in permissions.items()}
                if isinstance(permissions, dict)
                else {}
            ),
            checks=(
                [CheckResult.from_dict(item) for item in checks] if isinstance(checks, list) else []
            ),
            notes=_as_str_list(data.get("notes")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)


@dataclass
class StateInfo:
    """Bridge identity and capabilities."""

    platform: str = ""
    version: str = ""
    backend: str = ""
    capabilities: list[str] = field(default_factory=list)
    health: str = "unavailable"
    pid: int = 0
    mode: str = ""
    protocol_version: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> StateInfo:
        """Build state information from a bridge payload."""

        data = data or {}
        return cls(
            platform=_as_str(data.get("platform")),
            version=_as_str(data.get("version")),
            backend=_as_str(data.get("backend")),
            capabilities=_as_str_list(data.get("capabilities")),
            health=_as_str(data.get("health"), default="unavailable"),
            pid=_as_int(data.get("pid")),
            mode=_as_str(data.get("mode")),
            protocol_version=_as_str(data.get("protocol_version")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)


@dataclass
class ErrorDetails:
    """Structured hints that help a caller recover from a bridge error."""

    candidates: list[str] = field(default_factory=list)
    last_observed: str | None = None
    scope: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ErrorDetails | None:
        """Build details from an error payload; ``None`` when nothing is useful."""

        if not isinstance(data, dict):
            return None

        details = cls(
            candidates=_as_str_list(data.get("candidates")),
            last_observed=_as_optional_str(data.get("last_observed")),
            scope=_as_optional_str(data.get("scope")),
        )
        return details if details.to_dict() else None

    def to_dict(self) -> dict[str, Any]:
        """Return only the fields the bridge actually supplied."""

        data: dict[str, Any] = {}

        if self.candidates:
            data["candidates"] = list(self.candidates)

        if self.last_observed is not None:
            data["last_observed"] = self.last_observed

        if self.scope is not None:
            data["scope"] = self.scope

        return data


def _format_bounds(bounds: Rect | None) -> str | None:
    """Render bounds as the compact ``left,top,width,height`` string."""

    if bounds is None:
        return None

    return f"{bounds.left},{bounds.top},{bounds.width},{bounds.height}"


def _format_point(point: Point | None) -> str | None:
    """Render a point as the compact ``x,y`` string."""

    if point is None:
        return None

    return f"{point.x},{point.y}"


def _format_scroll(scroll: ScrollState | None) -> str | None:
    """Render scroll state as the compact ``h,v`` percentage string."""

    if scroll is None:
        return None

    horizontal = "-" if scroll.horizontal_percent is None else f"{scroll.horizontal_percent:g}"
    vertical = "-" if scroll.vertical_percent is None else f"{scroll.vertical_percent:g}"

    return f"{horizontal},{vertical}"


def _selector_value(value: str) -> str:
    """Escape a quoted selector attribute value."""

    return value.replace("\\", "\\\\").replace('"', '\\"')


def _as_optional_float(value: Any) -> float | None:
    """Coerce a bridge number to float, or return ``None``."""

    if value is None:
        return None

    try:
        return float(value)

    except (TypeError, ValueError):
        return None


def _as_scroll_state(data: Any) -> ScrollState | None:
    """Build scroll state from a bridge payload; ``None`` when absent."""

    if not isinstance(data, dict):
        return None

    return ScrollState(
        horizontal_percent=_as_optional_float(data.get("horizontal_percent")),
        vertical_percent=_as_optional_float(data.get("vertical_percent")),
        horizontal_view_percent=_as_optional_float(data.get("horizontal_view_percent")),
        vertical_view_percent=_as_optional_float(data.get("vertical_view_percent")),
        horizontal=_as_bool(data.get("horizontal")),
        vertical=_as_bool(data.get("vertical")),
    )


def _as_element(data: Any) -> Element:
    return Element.from_dict(data if isinstance(data, dict) else {})


def _matches_role(control_type: str, role: str) -> bool:
    return control_type.strip().lower() == role.strip().lower()


def error_details(value: Any) -> dict[str, Any] | None:
    details = ErrorDetails.from_dict(value if isinstance(value, dict) else None)
    return details.to_dict() if details is not None else None


def _as_rect(data: Any) -> Rect | None:
    if isinstance(data, dict):
        return Rect.from_dict(data)

    return None


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default

    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}

    return bool(value)


def _as_int(value: Any, default: int = 0) -> int:
    converted = _as_optional_int(value)
    return default if converted is None else converted


def _as_optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any, default: str = "") -> str:
    converted = _as_optional_str(value)
    return default if converted is None else converted


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None

    return str(value)


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []

    return [str(item) for item in value if item is not None]


def _as_element_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None
