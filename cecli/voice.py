import asyncio
import os
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor


class Voice:
    def __init__(self, audio_format="wav", device_name=None):
        self.audio_format = audio_format
        self.device_name = device_name
        self._executor = ProcessPoolExecutor(max_workers=1)

    async def record_and_transcribe(self, history=None, language=None):
        loop = asyncio.get_running_loop()
        stdin_fd = sys.stdin.fileno()

        try:
            return await loop.run_in_executor(
                self._executor,
                _run_record_process,
                stdin_fd,
                self.audio_format,
                self.device_name,
                history,
                language,
            )
        except Exception as e:
            print(f"Error in transcription: {e}")
            return None


def _run_record_process(stdin_fd, audio_format, device_name, history, language):
    import queue

    import sounddevice as sd
    import soundfile as sf

    from cecli.llm import litellm

    # Re-link terminal input
    sys.stdin = os.fdopen(os.dup(stdin_fd))

    q = queue.Queue()

    def callback(indata, frames, time, status):
        q.put(indata.copy())

    # 1. Securely create the temporary file
    # delete=False is required so we can close the handle and let 'soundfile' open it again
    with tempfile.NamedTemporaryFile(suffix=f".{audio_format}", delete=False) as tmp_file:
        temp_path = tmp_file.name

    try:
        # Device Setup
        device_id = None
        if device_name:
            for i, d in enumerate(sd.query_devices()):
                if device_name in d["name"]:
                    device_id = i
                    break

        info = sd.query_devices(device_id, "input")
        sample_rate = int(info["default_samplerate"])

        # Recording
        with sd.InputStream(
            samplerate=sample_rate, channels=1, callback=callback, device=device_id
        ):
            print("\nRecording... Press ENTER to stop.")
            sys.stdin.readline()

        # 2. Write buffered audio using the named path
        with sf.SoundFile(temp_path, mode="w", samplerate=sample_rate, channels=1) as file:
            while not q.empty():
                file.write(q.get())

        # 3. Transcription
        with open(temp_path, "rb") as fh:
            print("\nTranscribing...")
            transcript = litellm.transcription(
                model="whisper-1", file=fh, prompt=history, language=language
            )

        return transcript.text

    finally:
        # 4. Manual cleanup since delete=False was used
        if os.path.exists(temp_path):
            os.remove(temp_path)
