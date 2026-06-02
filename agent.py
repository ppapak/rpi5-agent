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
import smtplib
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from ctypes import *
from dotenv import load_dotenv

# External Libraries
import chromadb
from chromadb.utils import embedding_functions
from vosk import Model, KaldiRecognizer

# Load environment variables
load_dotenv()

# --- ALSA Error Suppression ---
def py_error_handler(filename, line, function, err, fmt): pass
ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)
c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)
try:
    asound = cdll.LoadLibrary('libasound.so.2')
    asound.snd_lib_error_set_handler(c_error_handler)
except Exception: pass

# --- Configuration Mapping ---
AGENT_NAME = os.getenv("AGENT_NAME", "Agent")
WAKE_WORD = AGENT_NAME.lower()
BASE_DIR = os.getenv("BASE_DIR", ".")
WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")
HISTORY_FILE = os.path.join(WORKSPACE_DIR, "history.md")
BEEP_FILE = "/tmp/assistant_beep.wav"

# Paths
MODEL_PATH = os.path.join(BASE_DIR, os.getenv("VOSK_MODEL_NAME", "vosk-model-small-en-us-0.15"))
PIPER_PATH = os.path.join(BASE_DIR, os.getenv("PIPER_BINARY_PATH", "piper/piper/piper"))
VOICE_MODEL = os.path.join(BASE_DIR, os.getenv("PIPER_VOICE_MODEL", "piper/en_US-lessac-medium.onnx"))

# Network
LLAMA_API_URL = os.getenv("LLAMA_API_URL", "http://localhost:8080/completion")
HEALTH_URL = os.getenv("HEALTH_URL", "http://localhost:8080/health")
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8081/")

# Email
SMTP_SERVER = os.getenv("SMTP_SERVER", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD", "")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL", "")

# Logic
DIST_THRESHOLD = float(os.getenv("DIST_THRESHOLD", 0.5))
PAST_DISCUSSIONS = int(os.getenv("PAST_DISCUSSIONS", 3))

# --- Initialization ---
os.makedirs(WORKSPACE_DIR, exist_ok=True)
stt_model = Model(MODEL_PATH)
tts_queue = queue.Queue(maxsize=50)
audio_queue = queue.Queue(maxsize=100)
HTTP_SESSION = requests.Session()

# --- Tools ---
def tool_web_search(query):
    try:
        r = HTTP_SESSION.get(SEARXNG_URL, params={'q': query, 'format': 'json'}, timeout=10)
        results = r.json().get('results', [])
        return "\n".join([f"{res['title']}: {res['content']}" for res in results[:3]])[:1000]
    except Exception as e: return f"Search Error: {e}"

def tool_write_file(filename, content):
    try:
        filename = filename.strip()
        if filename.lower() == "history.md":
            return "Error: history.md is a protected system log."
        path = (Path(WORKSPACE_DIR) / filename).resolve()
        if not str(path).startswith(os.path.abspath(WORKSPACE_DIR)): 
            return "Access Denied: Path outside workspace."
        if not content: return "Error: No content provided."
        path.write_text(content.strip(), encoding='utf-8')
        return f"File {filename} successfully updated."
    except Exception as e: return f"Write Error: {e}"

def tool_send_email(subject, body):
    try:
        if not body or len(body.strip()) < 5:
            return "Error: Email body too short."
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = RECEIVER_EMAIL
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        return "Email sent successfully."
    except Exception as e: return f"Email Error: {e}"

# --- Voice Logic ---
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
    except Exception: pass

def play_beep():
    subprocess.run(['aplay', '-D', 'default', '-q', BEEP_FILE], stderr=subprocess.DEVNULL)

def generate_beep_file():
    if not os.path.exists(BEEP_FILE):
        sr, dur, freq = 16000, 0.1, 1000
        s = [int(32767 * 0.5 * math.sin(2 * math.pi * freq * i / sr)) for i in range(int(sr * dur))]
        with wave.open(BEEP_FILE, 'w') as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(sr)
            f.writeframes(struct.pack('<' + 'h' * len(s), *s))

# --- Memory Management ---
class Memory:
    def __init__(self, path):
        self.path = path
        self.workspace_dir = os.path.dirname(path)
        self.chroma_client = chromadb.PersistentClient(path=os.path.join(self.workspace_dir, ".chroma_db"))
        self.emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        self.knowledge_col = self.chroma_client.get_or_create_collection("knowledge", embedding_function=self.emb_fn)
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
            except Exception as e: print(f"Sync Error: {e}")
            time.sleep(10)

    def _index_file(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            chunks = [c.strip() for c in content.split("\n\n") if len(c.strip()) > 10]
            for i, chunk in enumerate(chunks):
                chunk_id = f"{hashlib.md5(file_path.encode()).hexdigest()}_{i}"
                self.knowledge_col.upsert(documents=[chunk], ids=[chunk_id], metadatas=[{"source": file_path}])
        except Exception: pass

    def get_recent_history(self, n=3):
        if not os.path.exists(self.path): return ""
        try:
            with open(self.path, "r", encoding='utf-8') as f:
                content = f.read()
            turns = [t.strip() for t in content.split("---") if t.strip()]
            return "\n\n".join(turns[-n:])
        except Exception: return ""

    def get_context_optimized(self, prompt):
        recent_history = self.get_recent_history(n=PAST_DISCUSSIONS)
        knowledge_text = ""
        try:
            k_results = self.knowledge_col.query(query_texts=[prompt], n_results=2)
            if k_results['documents'] and k_results['distances'][0][0] < DIST_THRESHOLD:
                knowledge_text = " | ".join(k_results['documents'][0])
        except Exception: pass
        return recent_history, knowledge_text

chat_memory = Memory(HISTORY_FILE)

# --- Core LLM Logic ---
def stream_think(prompt, rec):
    active_prompt = prompt
    while True:
        recent_history, knowledge = chat_memory.get_context_optimized(active_prompt)
        now = datetime.datetime.now()
        timestamp_info = f"Date: {now.strftime('%A, %B %d, %Y')}. Time: {now.strftime('%H:%M')}."

        SYSTEM_PROMPT = (
            f"You are {AGENT_NAME}, a voice assistant. Be polite, direct, and concise. {timestamp_info}\n"
            "Tools:\n"
            "- [SEARCH: query]\n"
            "- [WRITE: name.md | content]\n"
            "- [EMAIL: subject | body] Do not ask for my email address. The tool has it.\n"
            "Style: Short sentences, no markdown, no emojis.\n"
            "MANDATORY: Speak response fully, then use tools at the end.\n"
        )

        full_prompt = (
            f"<start_of_turn>system\n{SYSTEM_PROMPT}<end_of_turn>\n"
            f"<start_of_turn>user\n"
            f"HISTORY:\n{recent_history}\n"
            f"KNOWLEDGE:\n{knowledge}\n"
            f"QUERY: {active_prompt}<end_of_turn>\n"
            f"<start_of_turn>model\n"
        )

        full_text, sentence = [], []
        tool_triggered = None
        payload = {"prompt": full_prompt, "stream": True, "cache_prompt": True, "stop": ["<end_of_turn>", "USER:", "Observation:"]}

        try:
            with HTTP_SESSION.post(LLAMA_API_URL, json=payload, stream=True) as r:
                for line in r.iter_lines():
                    if not line: continue
                    data = json.loads(line.decode('utf-8')[6:])
                    token = data.get("content", "")
                    print(token, end="", flush=True)
                    full_text.append(token); sentence.append(token)
                    
                    combined = "".join(full_text)
                    match = re.search(r"\[(SEARCH|WRITE|EMAIL):\s*(.*?)\]", combined, re.DOTALL)
                    if match:
                        tool_triggered = (match.group(1), match.group(2))
                        sentence.clear()
                        break
                    
                    current_buffer = "".join(sentence)
                    if "[" not in current_buffer and any(c in token for c in ".!?\n"):
                        chunk = current_buffer.strip()
                        if len(chunk) > 1: tts_queue.put(chunk)
                        sentence.clear()

            if tool_triggered:
                t_type, t_arg = tool_triggered
                obs = "Error: Invalid tool format."
                
                if t_type == "SEARCH": obs = tool_web_search(t_arg)
                elif t_type == "WRITE" and '|' in t_arg:
                    p = t_arg.split('|', 1)
                    obs = tool_write_file(p[0].strip(), p[1].strip())
                elif t_type == "EMAIL" and '|' in t_arg:
                    p = t_arg.split('|', 1)
                    obs = tool_send_email(p[0].strip(), p[1].strip())
                
                print(f"\n[OBSERVATION: {obs}]")
                active_prompt = f"Observation: {obs}\nAction: Now provide the final response."
                continue 
            else:
                if sentence:
                    final_chunk = "".join(sentence).strip()
                    if "[" not in final_chunk: tts_queue.put(final_chunk)
                chat_memory.save(prompt, "".join(full_text).strip())
                break
        except Exception as e:
            print(f"LLM Error: {e}")
            break

def audio_callback(in_data, frame_count, time_info, status):
    try: audio_queue.put_nowait(in_data)
    except queue.Full: pass
    return (None, pyaudio.paContinue)

def main():
    generate_beep_file()
    threading.Thread(target=piper_worker, daemon=True).start()
    threading.Thread(target=chat_memory.sync_workspace, daemon=True).start()

    while True:
        try:
            if requests.get(HEALTH_URL, timeout=1).status_code == 200: break
        except Exception: time.sleep(1)

    print(f"\n>>> {WAKE_WORD.capitalize()} online.")
    tts_queue.put(f"{WAKE_WORD} online. How can I help you?")
    
    pa = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=48000, input=True, 
                     frames_per_buffer=2048, stream_callback=audio_callback)
    
    rec = KaldiRecognizer(stt_model, 48000)
    in_command_mode = False

    try:
        while True:
            data = audio_queue.get() 
            if not rec.AcceptWaveform(data):
                partial = json.loads(rec.PartialResult())['partial']
                if WAKE_WORD in partial:
                    if not in_command_mode:
                        print("\n[WAKE WORD DETECTED]")
                    in_command_mode = True
            else:
                result = json.loads(rec.Result())['text']
                if in_command_mode and len(result) > 1:
                    cmd = result.partition(WAKE_WORD)[2].strip()
                    if len(cmd) > 1:
                        print(f"\nUSER: {cmd}")
                        play_beep()
                        stream_think(cmd, rec)
                    in_command_mode = False
                    rec.Reset()
                
    except KeyboardInterrupt: pass
    finally:
        stream.stop_stream(); stream.close(); pa.terminate()

if __name__ == "__main__":
    main()