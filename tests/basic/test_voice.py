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
def mock_litellm():
    mock_llm = MagicMock()
    mock_llm.transcription = MagicMock(return_value=MagicMock(text="Test transcription"))
    return mock_llm


@pytest.mark.asyncio
async def test_voice_init_default():
    """Test Voice initialization with default parameters."""
    voice = Voice()
    assert voice.audio_format == "wav"
    assert voice.device_name is None
    assert voice._executor is not None


@pytest.mark.asyncio
async def test_voice_init_with_device():
    """Test Voice initialization with specific device name."""
    voice = Voice(device_name="test_device", audio_format="mp3")
    assert voice.device_name == "test_device"
    assert voice.audio_format == "mp3"


@pytest.mark.asyncio
async def test_record_and_transcribe_success():
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
async def test_record_and_transcribe_exception():
    """Test that exceptions in transcription are caught and return None."""
    voice = Voice()

    # Mock the executor's run_in_executor to raise an exception
    mock_future = asyncio.Future()
    mock_future.set_exception(Exception("Test error"))

    with (
        patch.object(asyncio, "get_running_loop") as mock_loop,
        patch("sys.stdin.fileno", return_value=42),
    ):
        mock_loop.return_value.run_in_executor = MagicMock(return_value=mock_future)

        result = await voice.record_and_transcribe()

        assert result is None


@pytest.mark.asyncio
async def test_record_and_transcribe_with_device():
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
    mock_litellm = MagicMock()
    mock_litellm.transcription = MagicMock(return_value=MagicMock(text="Test transcription"))

    with (
        patch.dict("sys.modules", {"sounddevice": mock_sd, "soundfile": mock_sf}),
        patch("cecli.llm.litellm", mock_litellm),
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

        # Mock litellm
        mock_litellm = MagicMock()
        mock_litellm.transcription = MagicMock(return_value=MagicMock(text="Test transcription"))

        with patch("cecli.llm.litellm", mock_litellm):
            # Mock stdin.readline to simulate user pressing ENTER
            with patch("sys.stdin.readline", return_value=""):
                from cecli.voice import _run_record_process

                result = _run_record_process(stdin_fd, audio_format, device_name, None, None)

                # Should still work with device_id=None
                assert result == "Test transcription"
