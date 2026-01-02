import os
import tempfile
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
            # Check for image first
            image = ImageGrab.grabclipboard()
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

            # If not an image, try to get text
            text = pyperclip.paste()
            if text:
                io.tool_output(text)
                return format_command_result(io, "paste", "Pasted text from clipboard")

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
