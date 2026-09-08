---
parent: Usage
nav_order: 100
description: Use your voice, not your hands
---

# Voice Mode

`/voice` records your microphone and transcribes your speech locally (on-device with [Moonshine AI's lightweight STT models](https://github.com/moonshine-ai/moonshine)), placing the transcript in the input field where you can edit it before submitting.

## How to use voice-to-code

Type `/voice` and press Enter to start recording. Speak, then press Enter again (or your configured submit key) to stop and transcribe.

In the TUI you can start a recording at any time by pressing `ctrl+r`.

---

## Audio setup in WSL

If you run cecli from WSL (Windows Subsystem for Linux), `/voice` needs a little extra setup to reach your Windows microphone. WSLg bridges audio through PulseAudio, but `sounddevice` (via PortAudio) talks to ALSA, so we route ALSA through Pulse to WSLg's `RDPSource`. On a native Linux or Windows install this isn't needed.

1. **Check the Windows mic.** Verify your microphone is set as the **default input device** (Settings → System → Sound → Input) and that apps may access it (Settings → Privacy & security → Microphone).

2. **Install PortAudio and the ALSA → Pulse plugin plus the PulseAudio utilities.**

   - Fedora:

       ```bash
       sudo dnf install -y portaudio alsa-utils pulseaudio-utils alsa-plugins-pulseaudio
       ```

   - Debian / Ubuntu:

       ```bash
       sudo apt install -y libportaudio2 alsa-utils pulseaudio-utils libasound2-plugins
       ```


> **After installing PortAudio**, close and reopen your terminal (or restart WSL) so
> `sounddevice` picks up the newly installed PortAudio library — a running Python
> process keeps whichever PortAudio it loaded first. Also make sure Windows grants
> microphone access to WSLg (Settings → Privacy & security → Microphone →
> *allow desktop apps* / "Windows Subsystem for Linux").

3. **Route ALSA through PulseAudio.** Create `~/.asoundrc`:

   ```bash
   printf 'pcm.!default { type pulse }\nctl.!default { type pulse }\n' > ~/.asoundrc
   ```

4. **Verify the mic is captured** (optional). Speak while this runs for a couple of seconds; an RMS well above `0` means WSLg is forwarding your mic:

   ```bash
   PULSE_SERVER=unix:/mnt/wslg/PulseServer \
   parec -d RDPSource --format=s16le --rate=44100 --channels=1 | \
     head -c 176400 | \
     python3 -c "import sys, numpy as np; a=np.frombuffer(sys.stdin.buffer.read(), np.int16)/32768.0; print('RMS', round(float(np.sqrt(np.mean(a**2))),4))"
   ```

Once this is in place, `/voice` records from your Windows microphone and transcribes it on-device with [Moonshine AI's models](https://github.com/moonshine-ai/moonshine).
