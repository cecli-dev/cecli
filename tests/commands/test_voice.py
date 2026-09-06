import asyncio
import queue
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from cecli.commands.voice import VoiceCommand
from cecli.voice import SoundDeviceError


@pytest.fixture
def voice_context():
    io = MagicMock(placeholder="draft")
    coder = SimpleNamespace(
        tui=None,
        voice_language=None,
        voice_format=None,
        voice_input_device=None,
        get_user_language=MagicMock(return_value="English"),
    )
    recorder = MagicMock()
    recorder.record_and_transcribe = AsyncMock(return_value="final transcript")
    return io, coder, recorder


@pytest.mark.asyncio
async def test_tui_command_delegates_before_initialization(voice_context):
    io, coder, recorder = voice_context
    tui = MagicMock()
    coder.tui = MagicMock(return_value=tui)

    with patch("cecli.commands.voice.voice.Voice") as voice_class:
        result = await VoiceCommand.execute(io, coder, "")

    assert result == ""
    tui.call_from_thread.assert_called_once_with(tui.action_start_voice)
    tui.action_start_voice.assert_not_called()
    voice_class.assert_not_called()
    coder.get_user_language.assert_not_called()
    io.update_spinner.assert_not_called()


@pytest.mark.asyncio
async def test_background_command_uses_voice_binding_and_callbacks(voice_context):
    io, coder, recorder = voice_context
    tui = MagicMock()
    tui.get_keys_for.return_value = "alt+r"
    coder.tui = MagicMock(return_value=tui)
    stop_queue = queue.Queue()

    async def record(history, **kwargs):
        assert history is None
        assert kwargs["stop_queue"] is stop_queue
        assert kwargs["stop_binding"] == "alt+r"
        assert kwargs["language"] == "es"
        kwargs["on_text"]("partial transcript")
        kwargs["on_status"]("\n⬤ recording: alt+r to stop")
        kwargs["on_status"]("\n⬤ Transcribing")
        kwargs["on_status"]("\nMicrophone warning\n")
        kwargs["on_status"](None)
        return "final transcript"

    recorder.record_and_transcribe.side_effect = record
    result = await VoiceCommand.execute(
        io, coder, "", voice_instance=recorder, stop_queue=stop_queue, voice_language="Spanish"
    )

    assert result == ""
    assert io.placeholder == "final transcript"
    tui.call_from_thread.assert_not_called()
    tui.get_keys_for.assert_called_once_with("voice")
    assert tui.set_input_value.call_args_list == [
        call("partial transcript"),
        call("final transcript"),
    ]
    assert tui.refresh.call_count == 2
    assert io.update_spinner.call_args_list == [
        call("⬤ recording"),
        call("⬤ recording: alt+r to stop"),
        call("⬤ Transcribing"),
    ]
    assert io.tool_output.call_args_list == [call("Microphone warning"), call("")]
    recorder.close.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("dead_tui_reference", [False, True])
async def test_cli_preserves_enter_mode_and_partial_placeholder(voice_context, dead_tui_reference):
    io, coder, recorder = voice_context

    if dead_tui_reference:
        coder.tui = MagicMock(return_value=None)

    async def record(history, **kwargs):
        assert history is None
        assert kwargs["stop_queue"] is None
        assert kwargs["stop_binding"] is None
        kwargs["on_text"]("partial")
        assert io.placeholder == "partial"
        kwargs["on_status"]("\n⬤ recording")
        kwargs["on_status"](None)
        return "final transcript"

    recorder.record_and_transcribe.side_effect = record
    await VoiceCommand.execute(io, coder, "", voice_instance=recorder)

    assert io.placeholder == "final transcript"
    io.tool_output.assert_any_call("\n⬤ recording")
    io.tool_output.assert_any_call("")
    recorder.close.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize("outcome", ["success", "empty", "error", "cancel"])
async def test_recorder_ownership_and_cleanup(voice_context, owned, outcome):
    io, coder, recorder = voice_context
    coder.voice_format = "flac"
    coder.voice_input_device = "USB microphone"
    coder.get_user_language.return_value = "German"

    if outcome == "error":
        recorder.record_and_transcribe.side_effect = RuntimeError("device lost")
    elif outcome == "cancel":
        recorder.record_and_transcribe.side_effect = asyncio.CancelledError()
    elif outcome == "empty":
        recorder.record_and_transcribe.return_value = None

    with (
        patch.dict(sys.modules, {"moonshine_voice": MagicMock()}),
        patch("cecli.commands.voice.voice.Voice", return_value=recorder) as voice_class,
    ):
        kwargs = {} if owned else {"voice_instance": recorder}

        if outcome == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await VoiceCommand.execute(io, coder, "", **kwargs)
        else:
            await VoiceCommand.execute(io, coder, "", **kwargs)

    if owned:
        voice_class.assert_called_once_with(audio_format="flac", device_name="USB microphone")
        recorder.close.assert_called_once_with()
    else:
        voice_class.assert_not_called()
        recorder.close.assert_not_called()

    assert recorder.record_and_transcribe.await_args.kwargs["language"] == "de"

    if outcome == "error":
        io.tool_error.assert_called_once_with("Unable to transcribe: device lost")
    else:
        io.tool_error.assert_not_called()

    assert io.placeholder == ("final transcript" if outcome == "success" else "draft")


@pytest.mark.asyncio
async def test_missing_moonshine_reports_dependency(voice_context):
    io, coder, recorder = voice_context

    with (
        patch.dict(sys.modules, {"moonshine_voice": None}),
        patch("cecli.commands.voice.voice.Voice") as voice_class,
    ):
        await VoiceCommand.execute(io, coder, "")

    voice_class.assert_not_called()
    assert "pip install moonshine-voice" in io.tool_error.call_args.args[0]
    io.update_spinner.assert_not_called()


@pytest.mark.asyncio
async def test_sound_device_initialization_failure_is_reported(voice_context):
    io, coder, recorder = voice_context

    with (
        patch.dict(sys.modules, {"moonshine_voice": MagicMock()}),
        patch("cecli.commands.voice.voice.Voice", side_effect=SoundDeviceError("no portaudio")),
    ):
        await VoiceCommand.execute(io, coder, "")

    assert "portaudio" in io.tool_error.call_args.args[0]
    io.update_spinner.assert_not_called()


def test_help_describes_tui_toggle_and_cli_enter():
    help_text = VoiceCommand.get_help()
    assert "Ctrl+R" in help_text
    assert "/voice also toggles recording" in help_text
    assert "press Enter to stop" in help_text
