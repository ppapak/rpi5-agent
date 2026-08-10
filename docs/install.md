# Deploying the Assistant

**Prerequisite:** [system-setup.md](system-setup.md) has been run and the Pi has
rebooted. Audio must work — if `aplay /usr/share/sounds/alsa/Front_Center.wav`
is silent, fix that first; the assistant cannot.

**Install directory:** `~/native-ai` (referred to below as `$BASE_DIR`).

## Running the installer

```bash
cd native-ai
./scripts/install.sh
```

The board is detected automatically. To override or preview:

```bash
./scripts/install.sh --board pi5
./scripts/install.sh --dry-run
```

It is safe to re-run: existing downloads, the venv, and your `.env` are kept.

## What it installs

| Step | Result |
| :--- | :--- |
| 1 | apt build tools, plus per-board extras (`python3-picamera2` on the Pi 4) |
| 2 | llama.cpp cloned and built at `$BASE_DIR/llama.cpp` |
| 3 | the board's GGUF model, Piper voice, and the Vosk STT model |
| 4 | a venv at `$BASE_DIR/venv` from the profile's requirements file |
| 5 | the assistant package copied to `$BASE_DIR/native_ai`, and `$BASE_DIR/.env` |
| 6 | `llama-server.service` and `voice-assistant.service` |
| 7 | both services enabled and started |

The first run downloads several GB and compiles llama.cpp. Expect roughly 20
minutes on a Pi 5 and considerably longer on a Pi 4.

## Verifying

```bash
systemctl status llama-server voice-assistant
journalctl -u voice-assistant -f
```

A healthy startup logs the resolved configuration, loads the STT model, waits
for llama-server's health endpoint, and then speaks a greeting:

```
[SYSTEM STARTUP] agent=Agent base_dir=/home/pi/native-ai prompt=gemma rate=48000 features=rag,tools
[SYSTEM STARTUP] Loading speech recognition model into memory...
[SYSTEM STARTUP] Speech recognition engine active.
[SYSTEM STARTUP] Verifying server connection state...

>>> Agent online. How can I help you?
```

Then say the wake word followed by your question:

> *"Agent, what is the capital of France?"*

On the Pi 4, two commands are answered by hardware instead of the model:

> *"Agent, what do you see?"* — captures a frame and names the objects in it
> *"Agent, what is the battery?"* — reads the INA219 gauge

## Everyday operations

```bash
sudo systemctl restart voice-assistant    # after editing .env
sudo systemctl stop voice-assistant       # silence it without uninstalling
journalctl -u llama-server -n 50          # model loading problems
```

To change settings, edit `$BASE_DIR/.env` and restart — see
[configuration.md](configuration.md).

To pick up a newer llama.cpp:

```bash
./scripts/update-llama.sh
```

To deploy code changes, re-run `./scripts/install.sh`; it re-copies the package
and leaves your `.env` alone.

## Uninstalling

```bash
$BASE_DIR/uninstall.sh
```

This stops and removes both services and deletes `$BASE_DIR` — including
`workspace/` and `.env`. It asks for confirmation first. System-level changes
from `system-setup.sh` (`/etc/asound.conf`, `config.txt`) are left in place.

## Troubleshooting

**The service restarts in a loop.** Read the actual error:
`journalctl -u voice-assistant -n 50`. The usual causes are a missing model
asset (re-run the installer) or a `BASE_DIR` in `.env` that does not exist.

**No audio in or out, but `aplay` works from a shell.** The service runs as a
background unit; confirm your user is in the `audio` group (`groups`) and that
you rebooted after `system-setup.sh` added it.

**The wake word is never detected.** Vosk's small English model recognises
common words far more reliably than invented ones. Set `AGENT_NAME` in `.env` to
an ordinary word and restart.

**Replies are slow.** Check `journalctl -u llama-server` for the tokens/sec
figure. Lower `N_PREDICT` in `.env` for shorter answers, or drop `LLM_CTX` in the
board profile and re-run the installer.
