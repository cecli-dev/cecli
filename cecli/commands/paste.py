import base64
import os
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from typing import List

import pyperclip
from PIL import Image, ImageGrab

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class PasteCommand(BaseCommand):
    NORM_NAME = "paste"
    DESCRIPTION = (
        "Paste image/text from the clipboard into the chat. Optionally provide a name for the"
        " image."
    )

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        try:
            image = cls._grab_clipboard_image(io)

            if not isinstance(image, Image.Image):
                # Fall back to text when there is no image
                text = cls._read_clipboard_text(io)
                if text:
                    if coder.tui and coder.tui():
                        coder.tui().set_input_value(text)
                    else:
                        coder.io.set_placeholder(text)

                    return format_command_result(io, "paste", "Pasted text from clipboard")

                # On WSL the clipboard is owned by Windows and images are not always
                # bridged to X11/Wayland, so probe the Windows clipboard directly.
                if cls._is_wsl():
                    image = cls._grab_clipboard_image_windows(io)

            if isinstance(image, Image.Image):
                if args.strip():
                    filename = args.strip()
                    ext = os.path.splitext(filename)[1].lower()
                    if ext in (".jpg", ".jpeg", ".png"):
                        basename = filename
                    else:
                        basename = f"{filename}.png"
                else:
                    basename = "clipboard_image.png"

                temp_dir = tempfile.mkdtemp()
                temp_file_path = os.path.join(temp_dir, basename)
                image_format = "PNG" if basename.lower().endswith(".png") else "JPEG"
                if image_format == "JPEG" and image.mode not in ("RGB", "L", "CMYK"):
                    image = image.convert("RGB")

                image.save(temp_file_path, image_format)

                abs_file_path = Path(temp_file_path).resolve()

                # Check if a file with the same name already exists in the chat
                existing_file = next(
                    (f for f in coder.abs_fnames if Path(f).name == abs_file_path.name), None
                )
                if existing_file:
                    coder.abs_fnames.remove(existing_file)
                    io.tool_output(f"Replaced existing image in the chat: {existing_file}")

                coder.abs_fnames.add(str(abs_file_path))
                io.tool_output(f"Added clipboard image to the chat: {abs_file_path}")
                coder.check_added_files()

                return format_command_result(io, "paste", f"Added clipboard image: {abs_file_path}")

            io.tool_error("No image or text content found in clipboard.")
            return format_command_result(
                io, "paste", "No content found in clipboard", Exception("No content")
            )

        except Exception as e:
            io.tool_error(f"Error processing clipboard content: {e}")
            return format_command_result(io, "paste", f"Error: {str(e)}", e)

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for paste command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the paste command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /paste                    # Paste image or text from clipboard\n"
        help_text += "  /paste image.png          # Paste image with specific filename\n"
        help_text += (
            "\nNote: This command pastes content from your system clipboard into the chat.\n"
        )
        help_text += (
            "If an image is in the clipboard, it will be saved as a file and added to the chat.\n"
        )
        help_text += "If text is in the clipboard, it will be displayed in the chat.\n"
        return help_text

    @classmethod
    def _grab_clipboard_image(cls, io):
        """Return an image from the clipboard, or None if it cannot be read."""
        try:
            return ImageGrab.grabclipboard()
        except Exception as e:
            # WAYLAND_DISPLAY can be set with no live compositor (e.g. WSLg or a
            # stale SSH env), which makes the Wayland probe fail even though the
            # bridged X11 clipboard works. Retry once over X11.
            if os.environ.get("WAYLAND_DISPLAY"):
                cls._log_clipboard_error(io, f"Wayland image probe failed: {e}")
                return cls._grab_clipboard_image_x11(io)

            # The image probe can fail even when the text clipboard works, so keep
            # it quiet unless the user asked for detail.
            cls._log_clipboard_error(io, f"Clipboard image read failed: {e}")
            return None

    @classmethod
    def _grab_clipboard_image_x11(cls, io):
        """Retry the image probe with the Wayland display disabled."""
        wayland_display = os.environ.pop("WAYLAND_DISPLAY", None)
        try:
            return ImageGrab.grabclipboard()
        except Exception as e:
            cls._log_clipboard_error(io, f"Clipboard image read failed over X11: {e}")
            return None
        finally:
            if wayland_display is not None:
                os.environ["WAYLAND_DISPLAY"] = wayland_display

    @classmethod
    def _grab_clipboard_image_windows(cls, io):
        """Read an image from the Windows clipboard via PowerShell (WSL only)."""
        powershell = shutil.which("powershell.exe")
        if not powershell:
            return None

        script = (
            "Add-Type -AssemblyName System.Windows.Forms,System.Drawing\n"
            "$img = [System.Windows.Forms.Clipboard]::GetImage()\n"
            "if ($img -eq $null) { exit 1 }\n"
            "$ms = New-Object System.IO.MemoryStream\n"
            "$img.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)\n"
            "[Convert]::ToBase64String($ms.ToArray())\n"
        )
        try:
            result = subprocess.run(
                [powershell, "-NoProfile", "-STA", "-Command", script],
                capture_output=True,
                timeout=30,
            )
        except Exception as e:
            cls._log_clipboard_error(io, f"Windows clipboard image read failed: {e}")
            return None

        if result.returncode != 0 or not result.stdout.strip():
            detail = result.stderr.decode("utf-8", "replace").strip()
            cls._log_clipboard_error(io, f"Windows clipboard image read failed: {detail}")
            return None

        try:
            image = Image.open(BytesIO(base64.b64decode(result.stdout)))
            image.load()
            return image
        except Exception as e:
            cls._log_clipboard_error(io, f"Windows clipboard image decode failed: {e}")
            return None

    @classmethod
    def _is_wsl(cls):
        """Detect whether the process is running inside WSL."""
        if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
            return True

        try:
            with open("/proc/version", "r", encoding="utf-8", errors="ignore") as f:
                return "microsoft" in f.read().lower()
        except OSError:
            return False

    @classmethod
    def _read_clipboard_text(cls, io):
        """Return clipboard text, or an empty string if it is empty/unavailable."""
        try:
            return pyperclip.paste() or ""
        except Exception as e:
            # pyperclip's WSL backend raises on an empty Windows clipboard
            # (GetBytes(null)), which is not an error worth surfacing.
            cls._log_clipboard_error(io, f"Clipboard text read failed: {e}")
            return ""

    @classmethod
    def _log_clipboard_error(cls, io, message):
        """Surface clipboard probe errors only in verbose mode."""
        if getattr(io, "verbose", False):
            io.tool_error(message)
