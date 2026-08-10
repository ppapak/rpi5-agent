# Configuration

Two layers, with different lifetimes:

- **`profiles/<board>.conf`** — what the *hardware* is. Read by the scripts at
  install time. Changing one requires re-running the installer.
- **`$BASE_DIR/.env`** — how the *assistant* behaves. Read at every startup.
  Changing one needs only `sudo systemctl restart voice-assistant`.

The installer seeds `.env` from [`.env.example`](../.env.example) and stamps in
the board's values. Delete `.env` and re-run the installer to regenerate it.

## `.env` reference

### Identity

| Key | Default | Meaning |
| :--- | :--- | :--- |
| `AGENT_NAME` | `Agent` | The assistant's name, and lowercased, the wake word. Pick a common English word — Vosk's small model recognises invented names poorly. |
| `BASE_DIR` | `~/native-ai` | Install directory. Every other path is resolved relative to it. Set by the installer. |

### Board runtime

Set from the board profile at install time. Change these only if you know the
hardware changed.

| Key | Meaning |
| :--- | :--- |
| `SAMPLE_RATE` | Mic capture rate. Must match what the card provides — a mismatch produces silence or garbled recognition. |
| `FRAMES_PER_BUFFER` | Capture buffer size. Raise it if the journal reports input overruns. |
| `PROMPT_FORMAT` | `gemma` or `chatml`. Must match the loaded model's training format; the wrong one produces rambling or empty replies. |
| `FEATURE_RAG` | Retrieval over `workspace/` via ChromaDB. Needs the `requirements-pi5.txt` dependencies. |
| `FEATURE_VISION` | Camera object detection. Needs opencv and picamera2. |
| `FEATURE_BATTERY` | INA219 telemetry. Needs `smbus2` and I²C enabled. |
| `FEATURE_TOOLS` | `[WRITE:]` / `[EMAIL:]` tool calls — see [tools.md](tools.md). |

Turning a feature on without its dependencies installed will fail at startup.
Add the packages to the board's requirements file and re-run the installer.

### Inference

| Key | Default | Meaning |
| :--- | :--- | :--- |
| `LLAMA_API_URL` | `http://localhost:8080/completion` | Completion endpoint. Point it at another machine to offload inference. |
| `HEALTH_URL` | `http://localhost:8080/health` | Polled at startup until the model has loaded. |
| `N_PREDICT` | `128` | Maximum tokens per reply. The single most effective latency knob. |

### Assets

Paths relative to `BASE_DIR`.

| Key | Default |
| :--- | :--- |
| `VOSK_MODEL_NAME` | `vosk-model-small-en-us-0.15` |
| `PIPER_BIN_PATH` | `piper/piper/piper` |
| `PIPER_MODEL_NAME` | `piper/en_US-lessac-medium.onnx` |
| `EMBEDDING_MODEL_NAME_OR_PATH` | `all-MiniLM-L6-v2` |

`PIPER_BINARY_PATH` and `PIPER_VOICE_MODEL` are the pre-0.2 spellings of the two
Piper keys. They are still honoured so existing `.env` files keep working, but
new installs should use the names above.

### Memory and vision tuning

| Key | Default | Meaning |
| :--- | :--- | :--- |
| `DIST_THRESHOLD` | `0.7` | Maximum vector distance for a workspace chunk to count as relevant. Lower is stricter; raise it if the assistant ignores your files. |
| `PAST_DISCUSSIONS` | `3` | How many past turns to replay into the prompt. |
| `VISION_CONFIDENCE` | `0.30` | Minimum detection confidence before an object is spoken. |

### Tools

`SMTP_SERVER`, `SMTP_PORT`, `SENDER_EMAIL`, `SENDER_PASSWORD`, `RECEIVER_EMAIL`
— only read when `FEATURE_TOOLS=1`. See [tools.md](tools.md).

`.env` is gitignored and holds a password in plaintext. Keep it at mode `600`.

## Profile reference

| Key | Meaning |
| :--- | :--- |
| `BOARD_ID`, `BOARD_NAME` | Identifier and display name. |
| `DT_MODEL_MATCH` | Substring matched against `/proc/device-tree/model` for auto-detection. |
| `ALSA_CARD`, `ALSA_HW_DEVICE` | Card name and `hw:` device for `/etc/asound.conf`. |
| `ALSA_PLAYBACK_CHANNELS` | Explicit dmix channel count; blank omits it. |
| `AUDIO_SOFTVOL` | `1` inserts softvol/micboost layers for HATs with no hardware mixer. |
| `AUDIO_DRIVER_REPO`, `AUDIO_DRIVER_STATE` | Optional vendor driver to clone and an `alsactl` state to restore. |
| `FIRMWARE_SETTINGS` | Array of `key\|value` entries applied to `config.txt`. An empty value writes a bare line. |
| `VC4_NOAUDIO` | `1` appends `,noaudio` to the vc4 overlay so HDMI does not claim a card index. |
| `SWAP_FIXED_MIB` | Fixed swapfile size; blank leaves swap off. |
| `TMP_REMOUNT` | Enlarges `/tmp` during the build; blank skips it. |
| `LLM_MODEL_FILE`, `LLM_MODEL_URL` | The GGUF to download. |
| `LLM_CTX`, `LLM_THREADS` | llama-server context size and thread count. |
| `SAMPLE_RATE`, `PROMPT_FORMAT`, `FEATURE_*` | Seeded into `.env`; see above. |
| `EXTRA_APT` | Extra apt packages. |
| `REQUIREMENTS_FILE` | Which requirements file the venv installs. |
| `VENV_SYSTEM_SITE_PACKAGES` | `1` when the venv must see apt-installed Python packages (picamera2). |

## Adding a board

1. Copy the closest existing profile:
   `cp profiles/pi5.conf profiles/zero2w.conf`.
2. Set `BOARD_ID`, `BOARD_NAME`, and `DT_MODEL_MATCH` — check the target's
   `/proc/device-tree/model` for the exact string.
3. Adjust the audio, firmware, and model keys.
4. If it needs different Python packages, add `requirements-zero2w.txt` and
   point `REQUIREMENTS_FILE` at it.
5. Preview before committing to it:
   `./scripts/system-setup.sh --board zero2w --dry-run` and
   `./scripts/install.sh --board zero2w --dry-run`.

No script changes are needed — both discover profiles from the directory.

A genuinely new *chat format* is the one case that also needs Python: add a
`PromptTemplate` subclass in [`src/native_ai/prompts.py`](../src/native_ai/prompts.py)
and register it in `TEMPLATES`.
