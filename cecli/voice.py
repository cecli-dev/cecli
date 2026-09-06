"""On-device voice recording and transcription.

Records microphone audio (via ``sounddevice``) and transcribes it locally using
Moonshine's on-device models instead of sending the audio to OpenAI's Whisper
API. The model is downloaded and cached on first use. When an ``on_text``
callback is supplied the transcriber streams partial transcripts back as the
model generates them, so callers can feed the user's input in chunks.
"""

import asyncio
import os
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor

# Below this RMS level a recording is treated as silent (no usable mic input).
_SILENCE_RMS_THRESHOLD = 0.005

# Moonshine voice-asset language tags (ISO639-1) whose models are shipped.
_MOONSHINE_LANGUAGES = ("ar", "es", "de", "en", "ja", "ko", "vi", "uk", "zh", "tl")

# Human-readable language names -> Moonshine tags. These cover the values that
# ``coder.get_user_language()`` returns (via ``normalize_language``).
_LANGUAGE_NAME_TO_CODE = {
    "english": "en",
    "spanish": "es",
    "german": "de",
    "arabic": "ar",
    "japanese": "ja",
    "korean": "ko",
    "vietnamese": "vi",
    "ukrainian": "uk",
    "chinese": "zh",
    "mandarin": "zh",
    "tagalog": "tl",
}

# Languages whose tokenizer does not use the Latin alphabet require a higher
# hallucination-detection threshold in Moonshine's transcriber.
_NON_LATIN_LANGUAGES = frozenset(("ar", "ja", "zh", "ko", "uk"))

# Languages that ship a streaming model. Korean and Ukrainian do not yet, so
# those fall back to the buffered (non-streaming) path even with ``on_text``.
_STREAMING_LANGUAGES = frozenset(("ar", "de", "es", "en", "ja", "tl", "vi", "zh"))

# Sentinel placed on the cross-process text queue once streaming is finished.
_STREAM_END = "\0__MOONSHINE_STREAM_END__"


class SoundDeviceError(Exception):
    """Raised when the audio recording stack cannot be initialized."""


def resolve_moonshine_language(voice_language=None, user_language=None):
    """Resolve the Moonshine model language from a voice-language setting.

    Precedence is an explicit ``voice_language`` value, then the detected
    user/chat language, finally ``en``. Each input may be an ISO639-1 code or a
    human-readable language name (e.g. ``English``).
    """
    code = _normalize_moonshine_language(voice_language)

    if code:
        return code

    code = _normalize_moonshine_language(user_language)

    if code:
        return code

    return "en"


class Voice:
    """Record microphone audio and transcribe it on-device with Moonshine."""

    def __init__(self, audio_format="wav", device_name=None):
        try:
            import sounddevice  # noqa: F401
            import soundfile  # noqa: F401
        except (ImportError, OSError) as exc:
            raise SoundDeviceError(str(exc)) from exc

        self.audio_format = audio_format
        self.device_name = device_name
        self._executor = ProcessPoolExecutor(max_workers=1)

    async def record_and_transcribe(
        self, history=None, language=None, on_text=None, on_status=None, stop_binding=None
    ):
        loop = asyncio.get_running_loop()
        stdin_fd = sys.stdin.fileno()

        text_queue = None
        status_queue = None
        drain_task = None
        status_drain_task = None
        manager = None

        if on_text is not None or on_status is not None:
            import multiprocessing

            manager = multiprocessing.Manager()

            if on_text is not None:
                text_queue = manager.Queue()
                drain_task = loop.create_task(_drain_text_queue(text_queue, on_text))

            if on_status is not None:
                status_queue = manager.Queue()
                status_drain_task = loop.create_task(_drain_status_queue(status_queue, on_status))

        try:
            return await loop.run_in_executor(
                self._executor,
                _run_record_process,
                stdin_fd,
                self.audio_format,
                self.device_name,
                history,
                language,
                text_queue,
                status_queue,
                stop_binding,
            )
        finally:
            if drain_task is not None:
                try:
                    await asyncio.wait_for(drain_task, timeout=5)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    drain_task.cancel()

            if status_drain_task is not None:
                try:
                    await asyncio.wait_for(status_drain_task, timeout=5)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    status_drain_task.cancel()

            if manager is not None:
                manager.shutdown()


def _run_record_process(
    stdin_fd,
    audio_format,
    device_name,
    history,
    language,
    text_queue=None,
    status_queue=None,
    stop_binding=None,
):
    """Record mic audio and transcribe it on-device with Moonshine.

    Runs in a worker process so blocking mic/recording and model inference do
    not stall the asyncio event loop. When ``text_queue`` is provided and the
    language has a streaming model the audio is streamed into a Moonshine
    ``Transcriber`` and intermediate transcripts are pushed onto the queue as
    they are produced. The ``history`` context the
    cloud API accepted is not applied; Moonshine transcription runs on-device.
    """
    import queue

    import sounddevice as sd
    import soundfile as sf

    # Re-link terminal input so `sys.stdin.readline()` below waits for ENTER.
    sys.stdin = os.fdopen(os.dup(stdin_fd))

    q = queue.Queue()

    def callback(indata, frames, time, status):
        q.put(indata.copy())

    try:
        # Device setup.
        device_id = None

        if device_name:
            for i, d in enumerate(sd.query_devices()):
                if device_name in d["name"]:
                    device_id = i
                    break

        info = sd.query_devices(device_id, "input")
        sample_rate = int(info["default_samplerate"])

        if text_queue is not None and language in _STREAMING_LANGUAGES:
            return _record_and_stream(
                q,
                callback,
                sample_rate,
                device_id,
                language,
                text_queue,
                status_queue,
                stop_binding,
            )

        # Buffered path: record into a temp WAV, then transcribe the whole clip.
        with tempfile.NamedTemporaryFile(suffix=f".{audio_format}", delete=False) as tmp_file:
            temp_path = tmp_file.name

        try:
            with sd.InputStream(
                samplerate=sample_rate, channels=1, callback=callback, device=device_id
            ):
                _status(status_queue, f"\nRecording... Press {stop_binding or 'Enter'} to stop.")
                sys.stdin.readline()

            # Write buffered audio using the named path.
            total_energy = 0.0
            total_samples = 0

            with sf.SoundFile(
                temp_path, mode="w", samplerate=sample_rate, channels=1, format="WAV"
            ) as file:
                while not q.empty():
                    block = q.get()
                    file.write(block)
                    total_energy += float((block * block).sum())
                    total_samples += block.size

            if total_samples and (total_energy / total_samples) ** 0.5 < _SILENCE_RMS_THRESHOLD:
                _status(
                    status_queue,
                    "\nNo audio detected on the input device - check that your microphone is "
                    "selected, unmuted, and reachable from this session.",
                )

            # On-device transcription.
            _status(status_queue, "\nTranscribing...")
            return _transcribe_local(temp_path, language)
        finally:
            # Manual cleanup since delete=False was used.
            if os.path.exists(temp_path):
                os.remove(temp_path)
    finally:
        if text_queue is not None:
            text_queue.put(_STREAM_END)

        if status_queue is not None:
            status_queue.put(_STREAM_END)


def _record_and_stream(
    q, callback, sample_rate, device_id, language, text_queue, status_queue=None, stop_binding=None
):
    """Stream mic audio into a Moonshine transcriber, pushing partial text out.

    A feeder thread drains the recording queue into ``Transcriber.add_audio()``
    so the sounddevice callback stays non-blocking. The running transcript is
    forwarded cumulatively to ``text_queue`` so the caller can show the full
    transcript so far; the final assembled text is also returned.
    """
    import threading

    import sounddevice as sd
    from moonshine_voice.transcriber import LineCompleted, LineStarted, LineTextChanged

    transcriber = _build_transcriber(language)

    completed_lines = []
    current_line = ""

    last_pushed = ""

    def _push_cumulative():
        nonlocal last_pushed

        parts = [part.strip() for part in completed_lines if part and part.strip()]

        current = current_line.strip()

        if current:
            parts.append(current)

        if parts:
            joined = " ".join(parts)

            if joined != last_pushed:
                text_queue.put(joined)
                last_pushed = joined

    def on_event(event):
        nonlocal current_line

        if event is None or event.line is None:
            return

        if isinstance(event, LineStarted):
            current_line = ""
            _push_cumulative()
        elif isinstance(event, LineTextChanged):
            current_line = event.line.text or ""
            _push_cumulative()
        elif isinstance(event, LineCompleted):
            text = (event.line.text or "").strip()

            if text:
                completed_lines.append(text)

            current_line = ""
            _push_cumulative()

    transcriber.add_listener(on_event)
    transcriber.start()

    total_energy = 0.0
    total_samples = 0

    def feed():
        nonlocal total_energy, total_samples

        while True:
            block = q.get()

            if block is None:
                break

            data = block.reshape(-1).tolist()
            transcriber.add_audio(data, sample_rate)
            total_energy += float((block * block).sum())
            total_samples += block.size

    feed_thread = threading.Thread(target=feed, daemon=True)
    feed_thread.start()

    try:
        with sd.InputStream(
            samplerate=sample_rate, channels=1, callback=callback, device=device_id
        ):
            _status(status_queue, f"\nRecording... Press {stop_binding or 'Enter'} to stop.")
            sys.stdin.readline()
    finally:
        q.put(None)
        feed_thread.join()

    if total_samples and (total_energy / total_samples) ** 0.5 < _SILENCE_RMS_THRESHOLD:
        _status(
            status_queue,
            "\nNo audio detected on the input device - check that your microphone is "
            "selected, unmuted, and reachable from this session.",
        )

    try:
        transcript = transcriber.stop()
    finally:
        transcriber.close()

    return _join_transcript(transcript)


def _transcribe_local(wav_path, language="en"):
    """Transcribe a mono WAV on-device using Moonshine.

    Downloads and caches the model via ``moonshine_voice`` on first use. The
    ``language`` is a Moonshine tag (``en``, ``es``, ``zh``, ...).
    """
    from moonshine_voice.utils import load_wav_file

    audio_data, sample_rate = load_wav_file(wav_path)
    transcriber = _build_transcriber(language)

    try:
        transcript = transcriber.transcribe_without_streaming(audio_data, sample_rate=sample_rate)
    finally:
        transcriber.close()

    return _join_transcript(transcript)


def _build_transcriber(language):
    from moonshine_voice import Transcriber, get_model_for_language

    language = language or "en"

    model_root, model_arch = get_model_for_language(
        language,
        _model_arch_for_language(language),
        # Moonshine draws tqdm bars to stderr unless a progress callback is
        # supplied; give it a no-op so the bars don't scribble into the TUI's
        # captured stderr stream.
        on_progress=_silent_progress,
    )

    options = None

    if language in _NON_LATIN_LANGUAGES:
        options = {"max_tokens_per_second": 13.0}

    return Transcriber(
        model_path=model_root,
        model_arch=model_arch,
        options=options,
    )


def _model_arch_for_language(language):
    from moonshine_voice import ModelArch

    if language == "en":
        return ModelArch.SMALL_STREAMING

    return None


def _normalize_moonshine_language(value):
    if not value:
        return None

    normalized = value.strip().lower()

    if normalized in _MOONSHINE_LANGUAGES:
        return normalized

    # Strip a locale/script variant, e.g. ``zh-CN`` -> ``zh`` or ``en_US`` -> ``en``.
    primary = normalized.replace("-", "_").split("_")[0]

    if primary in _MOONSHINE_LANGUAGES:
        return primary

    return _LANGUAGE_NAME_TO_CODE.get(normalized)


def _join_transcript(transcript):
    lines = [line.text.strip() for line in transcript.lines if line.text and line.text.strip()]

    return " ".join(lines) if lines else None


async def _drain_text_queue(text_queue, on_text):
    """Forward partial transcripts from the worker to ``on_text``.

    Runs as an asyncio task so the blocking ``text_queue.get`` calls are
    marshalled onto a worker thread without stalling the event loop.
    """
    loop = asyncio.get_running_loop()

    while True:
        item = await loop.run_in_executor(None, text_queue.get)

        if item == _STREAM_END:
            break

        try:
            on_text(item)
        except Exception:
            pass


async def _drain_status_queue(status_queue, on_status):
    """Forward status messages from the worker to ``on_status``."""
    loop = asyncio.get_running_loop()

    while True:
        item = await loop.run_in_executor(None, status_queue.get)

        if item == _STREAM_END:
            break

        try:
            on_status(item)
        except Exception:
            pass


def _status(status_queue, message):
    """Report a status message to the caller, or ``print`` it when no queue is used."""
    if status_queue is not None:
        status_queue.put(message)
    else:
        print(message)


def _silent_progress(fraction, file):
    """No-op progress callback used to silence Moonshine's tqdm download bar."""
    pass
