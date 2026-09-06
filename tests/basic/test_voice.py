import asyncio
from unittest.mock import MagicMock, mock_open, patch

import pytest

from cecli.voice import Voice


@pytest.fixture
def mock_sounddevice():
    mock_sd = MagicMock()
    mock_sd.query_devices.return_value = [
        {"name": "test_device", "max_input_channels": 2, "default_samplerate": 44100},
        {"name": "another_device", "max_input_channels": 1, "default_samplerate": 48000},
    ]
    return mock_sd


@pytest.fixture
def mock_soundfile():
    mock_sf = MagicMock()
    mock_sf.SoundFile = MagicMock()
    return mock_sf


@pytest.fixture
def mock_audio_libs():
    """Expose fake sounddevice/soundfile modules so ``Voice()`` can be built."""
    with patch.dict(
        "sys.modules",
        {"sounddevice": MagicMock(), "soundfile": MagicMock()},
    ):
        yield


@pytest.mark.asyncio
async def test_voice_init_default(mock_audio_libs):
    """Test Voice initialization with default parameters."""
    voice = Voice()
    assert voice.audio_format == "wav"
    assert voice.device_name is None
    assert voice._executor is not None


@pytest.mark.asyncio
async def test_voice_init_with_device(mock_audio_libs):
    """Test Voice initialization with specific device name."""
    voice = Voice(device_name="test_device", audio_format="mp3")
    assert voice.device_name == "test_device"
    assert voice.audio_format == "mp3"


@pytest.mark.asyncio
async def test_record_and_transcribe_success(mock_audio_libs):
    """Test successful recording and transcription."""
    voice = Voice()

    # Mock the executor's run_in_executor to return a successful transcription
    mock_future = asyncio.Future()
    mock_future.set_result("Test transcription result")

    with (
        patch.object(asyncio, "get_running_loop") as mock_loop,
        patch("sys.stdin.fileno", return_value=42),
    ):
        mock_loop.return_value.run_in_executor = MagicMock(return_value=mock_future)

        result = await voice.record_and_transcribe(history="Previous context", language="en")

        # Verify the executor was called with correct arguments
        mock_loop.return_value.run_in_executor.assert_called_once()
        call_args = mock_loop.return_value.run_in_executor.call_args
        assert call_args[0][0] == voice._executor  # executor
        assert call_args[0][1].__name__ == "_run_record_process"  # function
        assert call_args[0][2] == 42  # stdin_fd
        assert call_args[0][3] == "wav"  # audio_format
        assert call_args[0][4] is None  # device_name
        assert call_args[0][5] == "Previous context"  # history
        assert call_args[0][6] == "en"  # language

        assert result == "Test transcription result"


@pytest.mark.asyncio
async def test_record_and_transcribe_exception(mock_audio_libs):
    """Test that exceptions in transcription propagate to the caller."""
    voice = Voice()

    # Mock the executor's run_in_executor to raise an exception
    mock_future = asyncio.Future()
    mock_future.set_exception(Exception("Test error"))

    with (
        patch.object(asyncio, "get_running_loop") as mock_loop,
        patch("sys.stdin.fileno", return_value=42),
    ):
        mock_loop.return_value.run_in_executor = MagicMock(return_value=mock_future)

        with pytest.raises(Exception, match="Test error"):
            await voice.record_and_transcribe()


@pytest.mark.asyncio
async def test_record_and_transcribe_with_device(mock_audio_libs):
    """Test recording with specific device name."""
    voice = Voice(device_name="test_device")

    mock_future = asyncio.Future()
    mock_future.set_result("Test transcription")

    with (
        patch.object(asyncio, "get_running_loop") as mock_loop,
        patch("sys.stdin.fileno", return_value=42),
    ):
        mock_loop.return_value.run_in_executor = MagicMock(return_value=mock_future)

        result = await voice.record_and_transcribe()

        call_args = mock_loop.return_value.run_in_executor.call_args
        assert call_args[0][4] == "test_device"  # device_name should be passed
        assert result == "Test transcription"


def test_run_record_process_device_selection():
    """Test device selection logic in _run_record_process."""
    stdin_fd = 42  # Mocked file descriptor
    audio_format = "wav"
    device_name = "test_device"
    history = "test history"
    language = "en"

    # Mock dependencies
    mock_sd = MagicMock()
    mock_sf = MagicMock()
    mock_sf.SoundFile = MagicMock()

    with (
        patch.dict("sys.modules", {"sounddevice": mock_sd, "soundfile": mock_sf}),
        patch("cecli.voice._transcribe_local", return_value="Test transcription"),
        patch("tempfile.NamedTemporaryFile") as mock_tempfile,
        patch("builtins.open", mock_open()),
        patch("os.remove"),
        patch("os.path.exists", return_value=True),
        patch("os.dup"),
        patch("os.fdopen"),
    ):
        # Setup mocks
        # Mock query_devices to handle both calls:
        # 1. sd.query_devices() - returns list of devices
        # 2. sd.query_devices(device_id, "input") - returns device info dict
        def query_devices_side_effect(device_id=None, kind=None):
            if device_id is None and kind is None:
                return [
                    {"name": "test_device", "default_samplerate": 44100},
                    {"name": "other_device", "default_samplerate": 48000},
                ]
            elif device_id == 0 and kind == "input":
                return {"default_samplerate": 44100}
            elif device_id is None and kind == "input":
                return {"default_samplerate": 44100}
            else:
                return {"default_samplerate": 44100}

        mock_sd.query_devices.side_effect = query_devices_side_effect

        mock_temp_file = MagicMock()
        mock_temp_file.name = "/tmp/test.wav"
        mock_tempfile.return_value.__enter__.return_value = mock_temp_file

        mock_sf.SoundFile.return_value.__enter__.return_value.write = MagicMock()

        # Mock stdin.readline to simulate user pressing ENTER
        with patch("sys.stdin.readline", return_value=""):
            # Call the function
            from cecli.voice import _run_record_process

            result = _run_record_process(stdin_fd, audio_format, device_name, history, language)

            # Verify device was found
            mock_sd.query_devices.assert_called()
            # Should try to find device with name containing "test_device"
            assert result == "Test transcription"


def test_run_record_process_no_device_found():
    """Test _run_record_process when specified device is not found."""
    stdin_fd = 42  # Mocked file descriptor
    audio_format = "wav"
    device_name = "nonexistent_device"

    mock_sd = MagicMock()
    mock_sf = MagicMock()
    mock_sf.SoundFile = MagicMock()

    with (
        patch.dict("sys.modules", {"sounddevice": mock_sd, "soundfile": mock_sf}),
        patch("tempfile.NamedTemporaryFile") as mock_tempfile,
        patch("builtins.open", mock_open()),
        patch("os.remove"),
        patch("os.path.exists", return_value=True),
        patch("os.dup"),
        patch("os.fdopen"),
    ):
        # Setup mocks - device not found
        # Mock query_devices to handle both calls:
        # 1. sd.query_devices() - returns list of devices
        # 2. sd.query_devices(device_id, "input") - returns device info dict
        def query_devices_side_effect(device_id=None, kind=None):
            if device_id is None and kind is None:
                return [
                    {"name": "test_device", "default_samplerate": 44100},
                ]
            elif device_id is None and kind == "input":
                return {"default_samplerate": 44100}
            else:
                return {"default_samplerate": 44100}

        mock_sd.query_devices.side_effect = query_devices_side_effect

        mock_temp_file = MagicMock()
        mock_temp_file.name = "/tmp/test.wav"
        mock_tempfile.return_value.__enter__.return_value = mock_temp_file

        mock_sf.SoundFile.return_value.__enter__.return_value.write = MagicMock()

        with patch("cecli.voice._transcribe_local", return_value="Test transcription"):
            # Mock stdin.readline to simulate user pressing ENTER
            with patch("sys.stdin.readline", return_value=""):
                from cecli.voice import _run_record_process

                result = _run_record_process(stdin_fd, audio_format, device_name, None, None)

                # Should still work with device_id=None
                assert result == "Test transcription"


def test_resolve_moonshine_language():
    """Test language resolution precedence for the Moonshine model."""
    from cecli.voice import resolve_moonshine_language

    # Explicit voice-language value wins.
    assert resolve_moonshine_language("es", "English") == "es"
    assert resolve_moonshine_language("english", None) == "en"

    # Falls back to the detected user/chat language.
    assert resolve_moonshine_language(None, "Spanish") == "es"
    assert resolve_moonshine_language(None, "Chinese") == "zh"
    assert resolve_moonshine_language(None, "Mandarin") == "zh"

    # Unsupported/absent languages fall back to English.
    assert resolve_moonshine_language(None, "Russian") == "en"
    assert resolve_moonshine_language(None, None) == "en"
    assert resolve_moonshine_language("", None) == "en"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, False, 0, "", lambda: None])
async def test_stop_bridge_accepts_any_payload(payload):
    import queue

    from cecli.voice import _bridge_stop_queue

    source = queue.Queue()
    destination = queue.Queue()
    task = asyncio.create_task(_bridge_stop_queue(source, destination))
    await asyncio.sleep(0)
    assert not task.done()
    source.put(payload)
    await asyncio.wait_for(task, 1)
    assert destination.get_nowait() is None
    assert source.empty()


@pytest.mark.asyncio
@pytest.mark.parametrize("worker_error", [False, True])
async def test_cancellation_waits_before_manager_shutdown(mock_audio_libs, worker_error):
    import queue

    loop = asyncio.get_running_loop()
    worker_future = loop.create_future()
    manager = MagicMock()
    worker_stop_queue = queue.Queue()
    manager.Queue.return_value = worker_stop_queue

    with (
        patch("multiprocessing.Manager", return_value=manager),
        patch("cecli.voice.ProcessPoolExecutor"),
        patch("cecli.voice.sys.stdin") as stdin,
        patch.object(loop, "run_in_executor", return_value=worker_future) as submit,
    ):
        stdin.fileno.side_effect = AssertionError("queue mode accessed stdin")
        voice = Voice()
        task = asyncio.create_task(voice.record_and_transcribe(stop_queue=queue.Queue()))
        await asyncio.sleep(0)
        submit.assert_called_once()
        assert submit.call_args.args[2] is None
        assert submit.call_args.args[-1] is worker_stop_queue
        task.cancel()
        await asyncio.sleep(0)
        assert worker_stop_queue.get_nowait() is None
        assert not task.done()
        assert not worker_future.cancelled()
        manager.shutdown.assert_not_called()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        manager.shutdown.assert_not_called()

        if worker_error:
            worker_future.set_exception(RuntimeError("worker failed while stopping"))
        else:
            worker_future.set_result("finished")

        with pytest.raises(asyncio.CancelledError):
            await task

        manager.shutdown.assert_called_once()
        stdin.fileno.assert_not_called()
        voice.close()
        voice._executor.shutdown.assert_called_once_with(wait=True)


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("payload", [None, False])
def test_worker_queue_mode_skips_stdin(streaming, payload):
    import queue
    from types import SimpleNamespace

    from cecli.voice import _STREAM_END, _run_record_process

    stop_queue = queue.Queue()
    stop_queue.put(payload)
    text_queue = queue.Queue()
    status_queue = queue.Queue()
    sounddevice = MagicMock()
    sounddevice.query_devices.return_value = {"default_samplerate": 16000}
    transcriber = MagicMock()
    transcriber.stop.return_value = SimpleNamespace(lines=[SimpleNamespace(text="hello")])

    with (
        patch.dict(
            "sys.modules",
            {
                "sounddevice": sounddevice,
                "soundfile": MagicMock(),
                "moonshine_voice.transcriber": MagicMock(),
            },
        ),
        patch("cecli.voice.sys.stdin") as stdin,
        patch("cecli.voice.os.dup") as dup,
        patch("cecli.voice.os.fdopen") as fdopen,
        patch("cecli.voice.tempfile.NamedTemporaryFile") as tempfile,
        patch("cecli.voice.os.path.exists", return_value=False),
        patch("cecli.voice._transcribe_local", return_value="hello"),
        patch("cecli.voice._build_transcriber", return_value=transcriber),
    ):
        tempfile.return_value.__enter__.return_value.name = "unused.wav"
        result = _run_record_process(
            None,
            "wav",
            None,
            None,
            "en" if streaming else "ko",
            text_queue,
            status_queue,
            "ctrl+r",
            stop_queue,
        )
        assert result == "hello"
        assert stop_queue.empty()
        stdin.fileno.assert_not_called()
        stdin.readline.assert_not_called()
        dup.assert_not_called()
        fdopen.assert_not_called()
        assert text_queue.get_nowait() == _STREAM_END
        assert "ctrl+r" in status_queue.get_nowait()

        if streaming:
            transcriber.close.assert_called_once()
            transcriber.stop.assert_called_once()
            tempfile.assert_not_called()


@pytest.mark.parametrize("failure", ["start", "record", "stop"])
def test_streaming_closes_transcriber_on_errors(failure):
    import queue

    from cecli.voice import _record_and_stream

    sounddevice = MagicMock()
    transcriber = MagicMock()
    stop_queue = queue.Queue()
    stop_queue.put(None)

    if failure == "record":
        sounddevice.InputStream.return_value.__enter__.side_effect = RuntimeError("record")
    else:
        getattr(transcriber, failure).side_effect = RuntimeError(failure)

    with (
        patch.dict(
            "sys.modules",
            {
                "sounddevice": sounddevice,
                "moonshine_voice.transcriber": MagicMock(),
            },
        ),
        patch("cecli.voice._build_transcriber", return_value=transcriber),
    ):
        with pytest.raises(RuntimeError, match=failure):
            _record_and_stream(
                queue.Queue(),
                MagicMock(),
                16000,
                None,
                "en",
                queue.Queue(),
                status_queue=queue.Queue(),
                stop_queue=stop_queue,
            )

    transcriber.close.assert_called_once()


def test_wait_for_stop_preserves_cli_readline():
    from cecli.voice import _wait_for_stop

    with patch("cecli.voice.sys.stdin") as stdin:
        _wait_for_stop(None)
        stdin.readline.assert_called_once_with()
