"""Shared shortcuts and border subtitles for the floating overlay panels."""

from textual.binding import Binding

SUBTITLE_SEPARATOR = " • "

OVERLAY_BINDINGS = [
    Binding("exclamation_mark", "open_commands_panel", "Commands", show=False),
    Binding("shift+1", "open_commands_panel", "Commands", show=False),
    Binding("at", "open_plans_panel", "Plans", show=False),
    Binding("shift+2", "open_plans_panel", "Plans", show=False),
    Binding("number_sign", "open_asides_panel", "Asides", show=False),
    Binding("shift+3", "open_asides_panel", "Asides", show=False),
]


class OverlayPanelActions:
    """Panel actions that switch between the floating overlay panels."""

    def action_open_commands_panel(self) -> None:
        self.app.open_panel("commands")

    def action_open_plans_panel(self) -> None:
        self.app.open_panel("plans")

    def action_open_asides_panel(self) -> None:
        self.app.open_panel("asides")


def refresh_overlay_subtitles(app) -> None:
    """Label every overlay panel with the shared 1-based shortcut numbers."""
    selectors = getattr(app, "PANELS", None)

    if not selectors:
        return

    subtitle = SUBTITLE_SEPARATOR.join(
        f"{name} (shift+{index})" for index, name in enumerate(selectors, start=1)
    )

    for selector in selectors.values():
        try:
            app.query_one(selector).border_subtitle = subtitle
        except Exception:
            pass
