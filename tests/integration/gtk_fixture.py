"""Minimal GTK3 window used by the Linux AT-SPI acceptance tests.

Run it directly in a graphical session with PyGObject installed. The window is
deterministic so a bridge snapshot can be asserted without depending on the
user's desktop applications.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Show the fixture window until it is closed; return a process exit code."""

    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
    except (ImportError, ValueError) as exc:
        print(f"PyGObject with GTK3 is required: {exc}", file=sys.stderr)
        return 2

    window = Gtk.Window(title="cecli GTK Fixture")
    window.set_default_size(420, 220)
    window.set_border_width(12)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    window.add(box)

    entry = Gtk.Entry()
    entry.set_name("cecli-entry")
    _set_accessible_name(entry, "Text Editor")
    box.pack_start(entry, False, False, 0)

    save = Gtk.Button(label="Save")
    save.set_name("cecli-save")
    _set_accessible_name(save, "Save")
    box.pack_start(save, False, False, 0)

    status = Gtk.Label(label="Ready")
    status.set_name("cecli-status")
    _set_accessible_name(status, "Status Label")
    box.pack_start(status, False, False, 0)

    def on_save(_button: object) -> None:
        status.set_text("Saved")

    save.connect("clicked", on_save)
    window.connect("destroy", Gtk.main_quit)

    window.show_all()
    print("cecli-gtk-fixture:ready", flush=True)
    Gtk.main()
    return 0


def _set_accessible_name(widget: object, name: str) -> None:
    """Set the ATK accessible name when the binding exposes it."""

    setter = getattr(widget, "set_accessible_name", None)

    if callable(setter):
        setter(name)
        return

    get_accessible = getattr(widget, "get_accessible", None)

    if callable(get_accessible):
        accessible = get_accessible()
        accessible.set_name(name)


if __name__ == "__main__":
    raise SystemExit(main())
