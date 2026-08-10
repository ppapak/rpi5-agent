"""
Entry point: wake-word loop and command routing.

Run as `python -m native_ai` from $BASE_DIR (which is what the systemd unit
does). Which features exist is decided entirely by the flags in .env, so this
file is identical on every board.
"""
import json
import threading

from vosk import KaldiRecognizer, Model

from . import audio, config, llm
from .memory import get_memory


def _build_router():
    """
    Assemble the (predicate, handler) list for the enabled features.

    Handlers take the spoken command and return True once they have answered;
    anything unclaimed falls through to the LLM.
    """
    routes = []

    if config.FEATURE_VISION:
        from . import vision

        threading.Thread(target=vision.start(), daemon=True).start()

        def look(cmd):
            print("AI: [looking]", flush=True)
            vision.trigger_event.set()
            return True

        routes.append((lambda c: "what do you see" in c or "look" in c, look))

    if config.FEATURE_BATTERY:
        from . import battery

        def report_battery(cmd):
            try:
                voltage, _current, _power, percentage = battery.get_telemetry()
                if voltage is not None:
                    response = f"The battery is at {int(percentage)} percent charge remaining."
                else:
                    response = "The battery sensor is offline."
            except Exception as e:
                response = f"Hardware fault: {e}"

            print(f"AI: {response}", flush=True)
            audio.speak(response)
            get_memory().save(cmd, response)
            return True

        routes.append((lambda c: "battery" in c, report_battery))

    return routes


def _handle(cmd, routes):
    lowered = cmd.lower()
    for matches, handler in routes:
        if matches(lowered):
            handler(cmd)
            return
    print("AI: ", end="", flush=True)
    llm.stream_think(cmd)


def main():
    print(f"[SYSTEM STARTUP] {config.summary()}", flush=True)

    audio.generate_beep_file()
    threading.Thread(target=audio.piper_worker, daemon=True).start()

    routes = _build_router()

    memory = get_memory()
    for worker in memory.start_workers():
        threading.Thread(target=worker, daemon=True).start()

    print("[SYSTEM STARTUP] Loading speech recognition model into memory...", flush=True)
    stt_model = Model(config.VOSK_MODEL_PATH)
    print("[SYSTEM STARTUP] Speech recognition engine active.", flush=True)

    print("[SYSTEM STARTUP] Verifying server connection state...", flush=True)
    llm.wait_for_server()

    online_msg = f"{config.WAKE_WORD.capitalize()} online. How can I help you?"
    print(f"\n>>> {online_msg}", flush=True)
    audio.speak(online_msg)

    pa, stream = audio.open_input_stream()
    stream.start_stream()
    rec = KaldiRecognizer(stt_model, config.SAMPLE_RATE)
    in_command_mode = False

    try:
        while True:
            data = audio.audio_queue.get()
            if not rec.AcceptWaveform(data):
                # The wake word usually shows up in a partial result well before
                # the utterance is final.
                partial = json.loads(rec.PartialResult())["partial"]
                if config.WAKE_WORD in partial:
                    in_command_mode = True
                continue

            result = json.loads(rec.Result())["text"]
            if in_command_mode and len(result) > 1:
                cmd = result.partition(config.WAKE_WORD)[2].strip()
                if len(cmd) > 1:
                    print("\n[WAKE WORD DETECTED]", flush=True)
                    print(f"USER: {cmd}", flush=True)
                    audio.play_beep()
                    _handle(cmd, routes)
                in_command_mode = False
                rec.Reset()

    except KeyboardInterrupt:
        pass
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


if __name__ == "__main__":
    main()
