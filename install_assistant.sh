#!/bin/bash
set -euo pipefail

# ============================================================
# 1. IDENTITY & SYSTEM DEPENDENCIES
# ============================================================
REAL_USER=${SUDO_USER:-$(whoami)}
USER_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
BASE_DIR="$USER_HOME/native-ai"
MODEL_DIR="$BASE_DIR/models"
MODEL_FILE="$MODEL_DIR/gemma-4-e4b.gguf"

echo "--- Deploying for User: $REAL_USER in $BASE_DIR ---"

echo "[1/7] Verifying system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y -qq git build-essential cmake portaudio19-dev python3-venv python3-dev unzip curl wget alsa-utils

# CRITICAL FIX: Ensure user has hardware audio access
sudo usermod -aG audio "$REAL_USER"

mkdir -p "$MODEL_DIR" "$BASE_DIR/piper" "$BASE_DIR/workspace"

# ============================================================
# 2. GENERATE UNINSTALL SCRIPT
# ============================================================
cat << 'UN' > "$BASE_DIR/uninstall.sh"
#!/bin/bash
echo "--- Starting Removal ---"
sudo systemctl stop voice-assistant llama-server 2>/dev/null || true
sudo systemctl disable voice-assistant llama-server 2>/dev/null || true
sudo rm -f /etc/systemd/system/voice-assistant.service
sudo rm -f /etc/systemd/system/llama-server.service
sudo systemctl daemon-reload

BASE_DIR="$(dirname "$(realpath "$0")")"
sudo rm -f /tmp/assistant_beep.wav
if [ -d "$BASE_DIR" ]; then
    echo "Deleting $BASE_DIR..."
    rm -rf "$BASE_DIR"
fi
echo "--- REMOVAL COMPLETE ---"
UN
chmod +x "$BASE_DIR/uninstall.sh"

# ============================================================
# 3. LLAMA.CPP COMPILATION
# ============================================================
echo "[2/7] Checking Inference Engine..."
if [ ! -f "$BASE_DIR/llama.cpp/build/bin/llama-server" ]; then
    echo "Cloning and building llama.cpp (this will take a moment)..."
    cd "$BASE_DIR"
    git clone https://github.com/ggerganov/llama.cpp
    cd llama.cpp
    mkdir build && cd build
    cmake ..
    cmake --build . --config Release -j 4
else
    echo "[*] llama-server binary exists."
fi

# ============================================================
# 4. ASSET DOWNLOADS
# ============================================================
echo "[3/7] Syncing Models and Voice Assets..."

# LLM
if [ ! -f "$MODEL_FILE" ]; then
    wget -nc https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q4_K_M.gguf -O "$MODEL_FILE"
fi

# Piper TTS
cd "$BASE_DIR/piper"
if [ ! -f "piper/piper" ]; then
    wget -qnc https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_arm64.tar.gz
    tar -xf piper_arm64.tar.gz
fi

if [ ! -f "en_US-lessac-medium.onnx" ]; then
    wget -qnc https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx -O en_US-lessac-medium.onnx
fi

if [ ! -f "en_US-lessac-medium.onnx.json" ]; then
    wget -qnc https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json -O en_US-lessac-medium.onnx.json
fi

# CRITICAL FIX: Vosk STT Model (Was missing entirely)
cd "$BASE_DIR"
if [ ! -d "vosk-model-small-en-us-0.15" ]; then
    wget -qnc https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
    unzip -q vosk-model-small-en-us-0.15.zip
    rm vosk-model-small-en-us-0.15.zip
fi

# ============================================================
# 5. PYTHON ENVIRONMENT
# ============================================================
echo "[4/7] Configuring Virtual Environment..."
cd "$BASE_DIR"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
./venv/bin/pip install --upgrade -q pip
# CRITICAL FIX: Added chromadb and sentence-transformers
./venv/bin/pip install -q vosk requests pyaudio chromadb sentence-transformers python-dotenv

# ============================================================
# 6. ASSISTANT ORCHESTRATOR
# ============================================================
echo "[5/7] Writing Orchestrator Logic..."
cat << 'PYTHON' > "$BASE_DIR/assistant.py"
"""
MIT License

Copyright (c) 2026 Panagiotis (Panos) Papakonstantinou

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Configuration Mapping ---
AGENT_NAME = os.getenv("AGENT_NAME", "Agent")
WAKE_WORD = AGENT_NAME.lower()
BASE_DIR = os.getenv("BASE_DIR", "")

if not BASE_DIR:
    raise ValueError("BASE_DIR not set in environment. Check your .env file.")

WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")
HISTORY_FILE = os.path.join(WORKSPACE_DIR, "history.md")
BEEP_FILE = "/tmp/assistant_beep.wav"

# Model Paths
MODEL_PATH = os.path.join(BASE_DIR, os.getenv("VOSK_MODEL_NAME", "vosk-model-small-en-us-0.15"))
PIPER_PATH = os.path.join(BASE_DIR, os.getenv("PIPER_BIN_PATH", "piper/piper/piper"))
VOICE_MODEL = os.path.join(BASE_DIR, os.getenv("PIPER_MODEL_NAME", "piper/en_US-lessac-medium.onnx"))
EMBEDDING_MODEL_SETTING = os.getenv("EMBEDDING_MODEL_NAME_OR_PATH", "all-MiniLM-L6-v2")

# Robust multi-layer path resolution for the embedding model
if os.path.exists(EMBEDDING_MODEL_SETTING):
    EMBEDDING_MODEL = EMBEDDING_MODEL_SETTING
elif os.path.exists(os.path.join(BASE_DIR, EMBEDDING_MODEL_SETTING)):
    EMBEDDING_MODEL = os.path.join(BASE_DIR, EMBEDDING_MODEL_SETTING)
else:
    EMBEDDING_MODEL = os.path.join(BASE_DIR, EMBEDDING_MODEL_SETTING)

# Conditional online download block executed prior to enforcing offline mode
if not os.path.exists(EMBEDDING_MODEL):
    print(f"Embedding model not found at local path: {EMBEDDING_MODEL}")
    print("Connecting to Hugging Face to download required model files...")
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(
            repo_id="sentence-transformers/all-MiniLM-L6-v2",
            local_dir=EMBEDDING_MODEL,
            local_files_only=False
        )
        print("Model downloaded successfully.")
    except Exception as e:
        print(f"Network download failed: {e}")

# --- Force Offline Environment ---
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"
os.environ["ANONYMIZED_TELEMETRY"] = "False"

import json
import subprocess
import pyaudio
import math
import struct
import wave
import threading
import queue
import time
import requests
import re
import hashlib
import datetime
from pathlib import Path
from ctypes import *

# Third-party dependencies
import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions
from vosk import Model, KaldiRecognizer

# --- ALSA Error Suppression ---
def py_error_handler(filename, line, function, err, fmt): pass
ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)
c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)
try:
    asound = cdll.LoadLibrary('libasound.so.2')
    asound.snd_lib_error_set_handler(c_error_handler)
except Exception:
    pass

# API URLs
LLAMA_API_URL = os.getenv("LLAMA_API_URL", "http://localhost:8080/completion")
HEALTH_URL = os.getenv("HEALTH_URL", "http://localhost:8080/health")

# Constants
DIST_THRESHOLD = float(os.getenv("DIST_THRESHOLD", 0.7))

# --- Initialization ---
os.makedirs(WORKSPACE_DIR, exist_ok=True)
stt_model = Model(MODEL_PATH)
tts_queue = queue.Queue(maxsize=50)
audio_queue = queue.Queue(maxsize=100)
HTTP_SESSION = requests.Session()

def piper_worker():
    aplay_cmd = ['aplay', '-D', 'default', '-r', '22050', '-f', 'S16_LE', '-t', 'raw', '-q']
    piper_cmd = [PIPER_PATH, '--model', VOICE_MODEL, '--output_raw']
    try:
        p_piper = subprocess.Popen(piper_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        p_aplay = subprocess.Popen(aplay_cmd, stdin=p_piper.stdout, stderr=subprocess.DEVNULL)
        while True:
            text = tts_queue.get()
            if text is None: break
            clean_text = text.replace('\n', ' ').strip()
            if clean_text:
                p_piper.stdin.write(f"{clean_text}\n".encode('utf-8'))
                p_piper.stdin.flush()
            tts_queue.task_done()
    except Exception:
        pass

def play_beep():
    subprocess.run(['aplay', '-D', 'default', '-q', BEEP_FILE], stderr=subprocess.DEVNULL)

def generate_beep_file():
    if not os.path.exists(BEEP_FILE):
        sr, dur, freq = 16000, 0.1, 1000
        s = [int(32767 * 0.5 * math.sin(2 * math.pi * freq * i / sr)) for i in range(int(sr * dur))]
        with wave.open(BEEP_FILE, 'w') as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(sr)
            f.writeframes(struct.pack('<' + 'h' * len(s), *s))

class Memory:
    def __init__(self, path):
        self.path = path
        self.workspace_dir = os.path.dirname(path)
        # Disable ChromaDB telemetry for offline use
        self.chroma_client = chromadb.PersistentClient(
            path=os.path.join(self.workspace_dir, ".chroma_db"),
            settings=Settings(anonymized_telemetry=False)
        )
        # Model must be present in local cache or local directory path
        self.emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL,
            device="cpu"
        )
        self.knowledge_col = self.chroma_client.get_or_create_collection(
            "knowledge", 
            embedding_function=self.emb_fn
        )
        self.file_registry = {} 

    def save(self, u, a):
        with open(self.path, "a", encoding='utf-8') as f:
            f.write(f"U: {u}\nA: {a}\n---\n")

    def sync_workspace(self):
        while True:
            try:
                for filename in os.listdir(self.workspace_dir):
                    if filename.startswith(".") or filename == "history.md": continue
                    file_path = os.path.join(self.workspace_dir, filename)
                    if not os.path.isfile(file_path): continue
                    
                    mtime = os.path.getmtime(file_path)
                    if file_path not in self.file_registry or mtime > self.file_registry[file_path]:
                        self._index_file(file_path)
                        self.file_registry[file_path] = mtime
            except Exception as e:
                print(f"Sync Error: {e}")
            time.sleep(5)

    def _index_file(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            chunks = [c.strip() for c in content.split("\n\n") if len(c.strip()) > 10]
            for i, chunk in enumerate(chunks):
                chunk_id = f"{hashlib.md5(file_path.encode()).hexdigest()}_{i}"
                self.knowledge_col.upsert(
                    documents=[chunk],
                    ids=[chunk_id],
                    metadatas=[{"source": file_path}]
                )
        except Exception:
            pass

    def get_recent_history(self, n=3):
        if not os.path.exists(self.path): return ""
        try:
            with open(self.path, "r", encoding='utf-8') as f:
                content = f.read()
            turns = [t.strip() for t in content.split("---") if t.strip()]
            return "\n\n".join(turns[-n:])
        except Exception:
            return ""

    def get_context_optimized(self, prompt):
        recent_history = self.get_recent_history(n=3)
        knowledge_text = ""
        try:
            k_results = self.knowledge_col.query(query_texts=[prompt], n_results=2)
            if k_results['documents'] and k_results['distances'][0][0] < DIST_THRESHOLD:
                knowledge_text = " | ".join(k_results['documents'][0])
        except Exception:
            pass
        return recent_history, knowledge_text

chat_memory = Memory(HISTORY_FILE)

def stream_think(prompt):
    recent_history, knowledge = chat_memory.get_context_optimized(prompt)
    now = datetime.datetime.now()
    timestamp_info = f"Date: {now.strftime('%A, %B %d, %Y')}. Time: {now.strftime('%H:%M')}."

    SYSTEM_PROMPT = (f"You are {AGENT_NAME}, a voice assistant. Be very polite. No fluff. Short sentences. {timestamp_info}\n"
                    "Ignore homophones; input is verbal dictation.\n"
                    "Priority: Last Response > Knowledge Base."
    )

    full_prompt = (
        f"<start_of_turn>system\n{SYSTEM_PROMPT}<end_of_turn>\n"
        f"<start_of_turn>user\n"
        f"RECENT HISTORY:\n{recent_history}\n\n"
        f"KNOWLEDGE:\n{knowledge}\n\n"
        f"USER QUERY: {prompt}<end_of_turn>\n"
        f"<start_of_turn>model\n"
    )

    full_text, sentence = [], []
    is_thinking = False

    payload = {
        "prompt": full_prompt, 
        "stream": True,
        "cache_prompt": True, 
        "n_predict": 128,
        "stop": ["<end_of_turn>", "USER QUERY:", "RECENT HISTORY:"]
    }

    try:
        with HTTP_SESSION.post(LLAMA_API_URL, json=payload, stream=True) as r:
            for line in r.iter_lines():
                if not line: continue
                try:
                    data = json.loads(line.decode('utf-8')[6:])
                    token = data.get("content", "")
                except Exception:
                    continue

                if any(x in token.lower() for x in ["thought", "<|"]):
                    is_thinking = True; continue
                if is_thinking and (">" in token or "\n" in token):
                    is_thinking = False; continue
                if is_thinking: continue

                print(token, end="", flush=True)
                full_text.append(token)
                sentence.append(token)

                if any(c in token for c in ".!?\n,:;"):
                    chunk = "".join(sentence).strip()
                    if len(chunk) > 1: tts_queue.put(chunk)
                    sentence.clear()

            print("\n") 
            if sentence: tts_queue.put("".join(sentence).strip())
            chat_memory.save(prompt, "".join(full_text).strip())
    except Exception as e: 
        print(f"LLM Connection Error: {e}")

def audio_callback(in_data, frame_count, time_info, status):
    try:
        audio_queue.put_nowait(in_data)
    except queue.Full: pass
    return (None, pyaudio.paContinue)

def main():
    generate_beep_file()
    threading.Thread(target=piper_worker, daemon=True).start()
    threading.Thread(target=chat_memory.sync_workspace, daemon=True).start()

    while True:
        try:
            if requests.get(HEALTH_URL, timeout=1).status_code == 200: break
        except Exception:
            time.sleep(1)

    online_msg = f"{WAKE_WORD.capitalize()} online. How can I help you?"
    print(f"\n>>> {online_msg}")
    tts_queue.put(online_msg)
    
    pa = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=48000, input=True, 
                     frames_per_buffer=2048, stream_callback=audio_callback)
    
    stream.start_stream()
    rec = KaldiRecognizer(stt_model, 48000)
    in_command_mode = False

    try:
        while True:
            data = audio_queue.get() 
            if not rec.AcceptWaveform(data):
                partial = json.loads(rec.PartialResult())['partial']
                if WAKE_WORD in partial:
                    in_command_mode = True
            else:
                result = json.loads(rec.Result())['text']
                if in_command_mode and len(result) > 1:
                    cmd = result.partition(WAKE_WORD)[2].strip()
                    if len(cmd) > 1:
                        print("\n[WAKE WORD DETECTED]")
                        print(f"USER: {cmd}")
                        print("AI: ", end="", flush=True)
                        play_beep()
                        stream_think(cmd)
                    in_command_mode = False
                    rec.Reset()
                
    except KeyboardInterrupt: pass
    finally:
        stream.stop_stream(); stream.close(); pa.terminate()

if __name__ == "__main__":
    main()
PYTHON

# Inject dynamic BASE_DIR
sed -i "s|PATH_PLACEHOLDER|$BASE_DIR|" "$BASE_DIR/assistant.py"

# ============================================================
# 7. SYSTEMD SERVICES
# ============================================================
echo "[6/7] Installing Systemd Services..."
sudo tee /etc/systemd/system/llama-server.service > /dev/null <<EOF
[Unit]
Description=Llama Server
After=network.target
[Service]
User=$REAL_USER
WorkingDirectory=$BASE_DIR
ExecStart=$BASE_DIR/llama.cpp/build/bin/llama-server -m $MODEL_FILE -c 4096 --threads 4 --prio 2 --no-mmap
Restart=always
[Install]
WantedBy=multi-user.target
EOF

# CRITICAL FIX: Ensure ALSA/Pulse environments are set so background PyAudio works
sudo tee /etc/systemd/system/voice-assistant.service > /dev/null <<EOF
[Unit]
Description=Voice Assistant
After=llama-server.service sound.target
Requires=sound.target
[Service]
User=$REAL_USER
WorkingDirectory=$BASE_DIR
Environment="XDG_RUNTIME_DIR=/run/user/$(id -u $REAL_USER)"
ExecStart=$BASE_DIR/venv/bin/python3 $BASE_DIR/assistant.py
Restart=always
CPUSchedulingPolicy=rr
CPUSchedulingPriority=50
Nice=-15
[Install]
WantedBy=multi-user.target
EOF

# ============================================================
# 8. START
# ============================================================
echo "[7/7] Launching Services..."
sudo chown -R $REAL_USER:$REAL_USER "$BASE_DIR"

sudo systemctl daemon-reload
sudo systemctl enable llama-server voice-assistant
sudo systemctl restart llama-server voice-assistant

echo "--- DEPLOYMENT COMPLETE ---"
echo "To uninstall, run: $BASE_DIR/uninstall.sh"