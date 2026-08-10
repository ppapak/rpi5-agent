"""
Single source of truth for every runtime setting.

Import this before anything that talks to Hugging Face or ChromaDB: it resolves
the embedding model (downloading it on first run) and then pins the process into
offline mode, which only works if it happens before those libraries load.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# The deployed layout is $BASE_DIR/native_ai/config.py with the .env one level
# up, so look there as well as in the working directory.
_PACKAGE_PARENT = Path(__file__).resolve().parent.parent
load_dotenv()
load_dotenv(_PACKAGE_PARENT / ".env")


def _flag(name, default=0):
    """Read a 0/1 feature flag."""
    return os.getenv(name, str(default)).strip() in ("1", "true", "True", "yes")


def _env(name, legacy_name, default):
    """Read `name`, falling back to a legacy spelling of the same key."""
    return os.getenv(name) or os.getenv(legacy_name) or default


# --- Identity ---
AGENT_NAME = os.getenv("AGENT_NAME", "Agent")
WAKE_WORD = AGENT_NAME.lower()

# Defaulting rather than raising: a missing BASE_DIR used to kill the service on
# first boot, before the user ever got to see a log line.
BASE_DIR = os.getenv("BASE_DIR") or os.path.expanduser("~/native-ai")

WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")
HISTORY_FILE = os.path.join(WORKSPACE_DIR, "history.md")
BEEP_FILE = "/tmp/assistant_beep.wav"

# --- Feature flags (set per board by the installer) ---
FEATURE_RAG = _flag("FEATURE_RAG", 1)
FEATURE_VISION = _flag("FEATURE_VISION", 0)
FEATURE_BATTERY = _flag("FEATURE_BATTERY", 0)
FEATURE_TOOLS = _flag("FEATURE_TOOLS", 0)

# --- Audio / speech ---
SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", "48000"))
FRAMES_PER_BUFFER = int(os.getenv("FRAMES_PER_BUFFER", "2048"))

VOSK_MODEL_PATH = os.path.join(BASE_DIR, os.getenv("VOSK_MODEL_NAME", "vosk-model-small-en-us-0.15"))
# PIPER_BINARY_PATH / PIPER_VOICE_MODEL are the pre-0.2 spellings, still honoured
# so an existing .env keeps working.
PIPER_PATH = os.path.join(BASE_DIR, _env("PIPER_BIN_PATH", "PIPER_BINARY_PATH", "piper/piper/piper"))
VOICE_MODEL = os.path.join(BASE_DIR, _env("PIPER_MODEL_NAME", "PIPER_VOICE_MODEL", "piper/en_US-lessac-medium.onnx"))

# --- Inference server ---
LLAMA_API_URL = os.getenv("LLAMA_API_URL", "http://localhost:8080/completion")
HEALTH_URL = os.getenv("HEALTH_URL", "http://localhost:8080/health")
PROMPT_FORMAT = os.getenv("PROMPT_FORMAT", "gemma")
N_PREDICT = int(os.getenv("N_PREDICT", "128"))

# --- Memory ---
DIST_THRESHOLD = float(os.getenv("DIST_THRESHOLD", "0.7"))
PAST_DISCUSSIONS = int(os.getenv("PAST_DISCUSSIONS", "3"))

# --- Vision (Pi 4) ---
VISION_DIR = os.path.join(BASE_DIR, "vision")
VISION_PROTOTXT = os.path.join(VISION_DIR, "ssd_mobilenet_v2_coco_2018_03_29.pbtxt")
VISION_MODEL = os.path.join(VISION_DIR, "frozen_inference_graph.pb")
VISION_PROTOTXT_URL = "https://raw.githubusercontent.com/opencv/opencv_extra/master/testdata/dnn/ssd_mobilenet_v2_coco_2018_03_29.pbtxt"
VISION_MODEL_URL = "https://github.com/spmallick/learnopencv/raw/master/Deep-Learning-with-OpenCV-DNN-Module/input/frozen_inference_graph.pb"
VISION_CONFIDENCE = float(os.getenv("VISION_CONFIDENCE", "0.30"))

# --- Tools (optional) ---
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8081/")
SMTP_SERVER = os.getenv("SMTP_SERVER", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD", "")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL", "")

# --- Embedding model (RAG only) ---
EMBEDDING_MODEL_SETTING = os.getenv("EMBEDDING_MODEL_NAME_OR_PATH", "all-MiniLM-L6-v2")

if os.path.exists(EMBEDDING_MODEL_SETTING):
    EMBEDDING_MODEL = EMBEDDING_MODEL_SETTING
else:
    EMBEDDING_MODEL = os.path.join(BASE_DIR, EMBEDDING_MODEL_SETTING)

if FEATURE_RAG and not os.path.exists(EMBEDDING_MODEL):
    print(f"Embedding model not found at local path: {EMBEDDING_MODEL}")
    print("Connecting to Hugging Face to download required model files...")
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id="sentence-transformers/all-MiniLM-L6-v2",
            local_dir=EMBEDDING_MODEL,
            local_files_only=False,
        )
        print("Model downloaded successfully.")
    except Exception as e:
        print(f"Network download failed: {e}")

# --- Force offline once the one-time download above is done ---
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"
os.environ["ANONYMIZED_TELEMETRY"] = "False"

try:
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
except OSError as e:
    # Importing config must never be the thing that kills the service; let the
    # first actual read or write report the problem with context.
    print(f"Warning: could not create {WORKSPACE_DIR}: {e}")


def summary():
    """One-line-per-setting dump for the startup log."""
    features = [
        name
        for name, on in (
            ("rag", FEATURE_RAG),
            ("vision", FEATURE_VISION),
            ("battery", FEATURE_BATTERY),
            ("tools", FEATURE_TOOLS),
        )
        if on
    ]
    return (
        f"agent={AGENT_NAME} base_dir={BASE_DIR} prompt={PROMPT_FORMAT} "
        f"rate={SAMPLE_RATE} features={','.join(features) or 'none'}"
    )
