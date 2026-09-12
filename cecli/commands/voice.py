from typing import List

import cecli.voice as voice
from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import format_command_result


class VoiceCommand(BaseCommand):
    NORM_NAME = "voice"
    DESCRIPTION = "Record and transcribe voice input"

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Record inline in the CLI, or toggle background recording in the TUI."""
        tui = coder.tui() if coder.tui else None
        stop_queue = kwargs.get("stop_queue")

        if tui is not None and stop_queue is None:
            tui.call_from_thread(tui.action_start_voice)
            return ""

        voice_language = kwargs.get("voice_language") or getattr(coder, "voice_language", None)
        voice_format = kwargs.get("voice_format") or getattr(coder, "voice_format", None)
        voice_input_device = kwargs.get("voice_input_device") or getattr(
            coder, "voice_input_device", None
        )

        detected_language = None
        get_user_language = getattr(coder, "get_user_language", None)

        if get_user_language:
            detected_language = get_user_language()

        resolved_language = voice.resolve_moonshine_language(voice_language, detected_language)
        voice_instance = kwargs.get("voice_instance")
        owns_voice = voice_instance is None

        if owns_voice:
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
            if tui is not None:
                tui.set_input_value(partial)
                tui.refresh()
            else:
                io.placeholder = partial

        def on_status(message):
            if tui is not None:
                if "⬤ recording" in str(message) or "⬤ Transcribing" in str(message):
                    tui.set_voice_hint((message or "").strip())
                else:
                    io.tool_output((message or "").strip())
            else:
                io.tool_output(message or "")

        stop_binding = tui.get_keys_for("voice") if tui is not None else None

        try:
            if tui is not None:
                tui.set_voice_hint("⬤ recording")
            else:
                io.update_spinner("⬤ recording")
            text = await voice_instance.record_and_transcribe(
                None,
                language=resolved_language,
                on_text=on_text,
                on_status=on_status,
                stop_binding=stop_binding,
                stop_queue=stop_queue,
            )
        except Exception as err:
            io.tool_error(f"Unable to transcribe: {err}")
            return format_command_result(io, "voice", f"Transcription error: {err}")
        finally:
            if owns_voice:
                voice_instance.close()

        if text:
            io.placeholder = text

            if tui is not None:
                tui.set_input_value(text)
                tui.refresh()
                return ""

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
        help_text += (
            "\nIn the TUI, use the voice shortcut (Ctrl+R by default) to start and stop"
            " background recording. /voice also toggles recording. Outside the TUI,"
            " press Enter to stop.\n"
        )
        help_text += "Requirements:\n"
        help_text += "  - moonshine-voice, sounddevice, and soundfile Python packages\n"
        help_text += "  - PortAudio library installed (for sounddevice)\n"
        help_text += "\nThe transcribed text will be placed in the input prompt for editing.\n"
        return help_text
