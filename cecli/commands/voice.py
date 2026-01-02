import os
from typing import List

import cecli.voice as voice
from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result
from cecli.llm import litellm


class VoiceCommand(BaseCommand):
    NORM_NAME = "voice"
    DESCRIPTION = "Record and transcribe voice input"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the voice command with given parameters."""
        # Get voice parameters from kwargs or coder
        voice_language = kwargs.get("voice_language") or getattr(coder, "voice_language", None)
        voice_format = kwargs.get("voice_format") or getattr(coder, "voice_format", None)
        voice_input_device = kwargs.get("voice_input_device") or getattr(
            coder, "voice_input_device", None
        )

        # Get voice instance from kwargs or create new one
        voice_instance = kwargs.get("voice_instance")

        if not voice_instance:
            if "OPENAI_API_KEY" not in os.environ:
                io.tool_error("To use /voice you must provide an OpenAI API key.")
                return format_command_result(io, "voice", "OpenAI API key required")

            try:
                voice_instance = voice.Voice(
                    audio_format=voice_format or "wav", device_name=voice_input_device
                )
            except voice.SoundDeviceError:
                io.tool_error(
                    "Unable to import `sounddevice` and/or `soundfile`, is portaudio installed?"
                )
                return format_command_result(io, "voice", "Sound device error")

        try:
            io.update_spinner("Recording...")
            text = await voice_instance.record_and_transcribe(None, language=voice_language)
        except litellm.OpenAIError as err:
            io.tool_error(f"Unable to use OpenAI whisper model: {err}")
            return format_command_result(io, "voice", f"OpenAI error: {err}")

        if text:
            io.placeholder = text

        if coder.tui and coder.tui():
            coder.tui().set_input_value(text)
            coder.tui().refresh()

        return format_command_result(io, "voice", "Voice recorded and transcribed")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Get completion options for voice command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        """Get help text for the voice command."""
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /voice  # Record and transcribe voice input\n"
        help_text += (
            "\nThis command records audio from your microphone and transcribes it using OpenAI's"
            " Whisper model.\n"
        )
        help_text += "Requirements:\n"
        help_text += "  - OPENAI_API_KEY environment variable must be set\n"
        help_text += "  - PortAudio library installed (for sounddevice)\n"
        help_text += "  - sounddevice and soundfile Python packages\n"
        help_text += "\nThe transcribed text will be placed in the input prompt for editing.\n"
        return help_text
