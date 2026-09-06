from typing import List

import cecli.voice as voice
from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class VoiceCommand(BaseCommand):
    NORM_NAME = "voice"
    DESCRIPTION = "Record and transcribe voice input"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Execute the voice command with given parameters."""
        # Get voice parameters from kwargs or coder.
        voice_language = kwargs.get("voice_language") or getattr(coder, "voice_language", None)
        voice_format = kwargs.get("voice_format") or getattr(coder, "voice_format", None)
        voice_input_device = kwargs.get("voice_input_device") or getattr(
            coder, "voice_input_device", None
        )

        # Resolve the Moonshine model language: an explicit voice-language
        # setting, then the detected user/chat language, finally English.
        detected_language = None
        get_user_language = getattr(coder, "get_user_language", None)
        if get_user_language:
            detected_language = get_user_language()

        resolved_language = voice.resolve_moonshine_language(voice_language, detected_language)

        # Get voice instance from kwargs or create new one.
        voice_instance = kwargs.get("voice_instance")

        if not voice_instance:
            try:
                import moonshine_voice  # noqa: F401
            except ImportError:
                io.tool_error(
                    "To use /voice you must install `moonshine-voice` (pip install moonshine-voice)."
                )
                return format_command_result(io, "voice", "moonshine-voice not installed")

            try:
                voice_instance = voice.Voice(
                    audio_format=voice_format or "wav", device_name=voice_input_device
                )
            except voice.SoundDeviceError:
                io.tool_error(
                    "Unable to import `sounddevice` and/or `soundfile`, is portaudio installed?"
                )
                return format_command_result(io, "voice", "Sound device error")

        def on_text(partial):
            # Stream partial transcripts into the input field as they are generated.
            if coder.tui and coder.tui():
                coder.tui().set_input_value(partial)
                coder.tui().refresh()
            else:
                io.placeholder = partial

        def on_status(message):
            # Surface worker status messages (recording/transcribing) in the TUI.
            if coder.tui and coder.tui():
                if "Recording..." in str(message) or "Transcribing..." in str(message):
                    io.update_spinner((message or "").strip())
                else:
                    io.tool_output((message or "").strip())
            else:
                io.tool_output(message or "")

        stop_binding = None
        if coder.tui and coder.tui():
            try:
                stop_binding = coder.tui().get_keys_for("submit")
            except Exception:
                stop_binding = None

        try:
            io.update_spinner("Recording...")
            text = await voice_instance.record_and_transcribe(
                None,
                language=resolved_language,
                on_text=on_text,
                on_status=on_status,
                stop_binding=stop_binding,
            )
        except Exception as err:
            io.tool_error(f"Unable to transcribe: {err}")
            return format_command_result(io, "voice", f"Transcription error: {err}")

        if text:
            io.placeholder = text

            if coder.tui and coder.tui():
                coder.tui().set_input_value(text)
                coder.tui().refresh()
                return ""  # For the TUI the result is already in the input field!

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
            "\nThis command records audio from your microphone and transcribes it on-device"
            " using the Moonshine on-device model. The language is resolved from your"
            " /voice-language setting, falling back to your chat language, then English.\n"
        )
        help_text += "Requirements:\n"
        help_text += "  - moonshine-voice, sounddevice, and soundfile Python packages\n"
        help_text += "  - PortAudio library installed (for sounddevice)\n"
        help_text += "\nThe transcribed text will be placed in the input prompt for editing.\n"
        return help_text
