"""
Audio plumbing: ALSA noise suppression, the mic capture queue, and the Piper
TTS worker that pipes synthesised speech straight into aplay.
"""
import math
import queue
import struct
import subprocess
import wave
from ctypes import CFUNCTYPE, c_char_p, c_int, cdll

import pyaudio

from . import config

# --- ALSA error suppression ---
# libasound writes a wall of warnings to stderr on every open; swallow them so
# the journal stays readable.
def _py_error_handler(filename, line, function, err, fmt):
    pass


_ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)
_c_error_handler = _ERROR_HANDLER_FUNC(_py_error_handler)
try:
    _asound = cdll.LoadLibrary("libasound.so.2")
    _asound.snd_lib_error_set_handler(_c_error_handler)
except Exception:
    pass

tts_queue = queue.Queue(maxsize=50)
audio_queue = queue.Queue(maxsize=100)


def piper_worker():
    """Consume text fragments and speak them. Runs as a daemon thread."""
    aplay_cmd = ["aplay", "-D", "default", "-r", "22050", "-f", "S16_LE", "-t", "raw", "-q"]
    piper_cmd = [config.PIPER_PATH, "--model", config.VOICE_MODEL, "--output_raw"]
    try:
        p_piper = subprocess.Popen(
            piper_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        subprocess.Popen(aplay_cmd, stdin=p_piper.stdout, stderr=subprocess.DEVNULL)
        while True:
            text = tts_queue.get()
            if text is None:
                break
            clean_text = text.replace("\n", " ").strip()
            if clean_text:
                p_piper.stdin.write(f"{clean_text}\n".encode("utf-8"))
                p_piper.stdin.flush()
            tts_queue.task_done()
    except Exception:
        pass


def speak(text):
    """Queue a line for the TTS worker."""
    tts_queue.put(text)


def play_beep():
    subprocess.run(["aplay", "-D", "default", "-q", config.BEEP_FILE], stderr=subprocess.DEVNULL)


def generate_beep_file():
    """Synthesise the wake-word acknowledgement tone once per boot."""
    import os

    if os.path.exists(config.BEEP_FILE):
        return
    sr, dur, freq = 16000, 0.1, 1000
    samples = [int(32767 * 0.5 * math.sin(2 * math.pi * freq * i / sr)) for i in range(int(sr * dur))]
    with wave.open(config.BEEP_FILE, "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes(struct.pack("<" + "h" * len(samples), *samples))


def audio_callback(in_data, frame_count, time_info, status):
    """PyAudio callback — never blocks; drops frames if the consumer stalls."""
    try:
        audio_queue.put_nowait(in_data)
    except queue.Full:
        pass
    return (None, pyaudio.paContinue)


def open_input_stream():
    """Open the mic at the board's sample rate. Returns (pyaudio, stream)."""
    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=config.SAMPLE_RATE,
        input=True,
        frames_per_buffer=config.FRAMES_PER_BUFFER,
        stream_callback=audio_callback,
    )
    return pa, stream
