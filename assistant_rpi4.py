'''
MIT License

Copyright (c) 2026 Panagiotis (Panos) Papakonstantinou

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the 'Software'), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED 'AS IS', WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''
import os
os.environ['LIBCAMERA_LOG_LEVELS'] = 'ERROR'

import sys
import urllib.request
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
import datetime
import cv2
import numpy as np
from pathlib import Path
from ctypes import *
from dotenv import load_dotenv
from vosk import Model, KaldiRecognizer
from picamera2 import Picamera2

import battery

load_dotenv()

AGENT_NAME = os.getenv('AGENT_NAME', 'Agent')
WAKE_WORD = AGENT_NAME.lower()
BASE_DIR = os.getenv('BASE_DIR', '')

if not BASE_DIR:
    raise ValueError('BASE_DIR not set in environment. Check your .env file.')

WORKSPACE_DIR = os.path.join(BASE_DIR, 'workspace')
HISTORY_FILE = os.path.join(WORKSPACE_DIR, 'history.md')
BEEP_FILE = '/tmp/assistant_beep.wav'

MODEL_PATH = os.path.join(BASE_DIR, os.getenv('VOSK_MODEL_NAME', 'vosk-model-small-en-us-0.15'))
PIPER_PATH = os.path.join(BASE_DIR, os.getenv('PIPER_BIN_PATH', 'piper/piper/piper'))
VOICE_MODEL = os.path.join(BASE_DIR, os.getenv('PIPER_MODEL_NAME', 'piper/en_US-lessac-medium.onnx'))

VISION_DIR = os.path.join(BASE_DIR, 'vision')
VISION_PROTOTXT = os.path.join(VISION_DIR, 'ssd_mobilenet_v2_coco_2018_03_29.pbtxt')
VISION_MODEL = os.path.join(VISION_DIR, 'frozen_inference_graph.pb')

VISION_PROTOTXT_URL = 'https://raw.githubusercontent.com/opencv/opencv_extra/master/testdata/dnn/ssd_mobilenet_v2_coco_2018_03_29.pbtxt'
VISION_MODEL_URL = 'https://github.com/spmallick/learnopencv/raw/master/Deep-Learning-with-OpenCV-DNN-Module/input/frozen_inference_graph.pb'

os.makedirs(VISION_DIR, exist_ok=True)

def download_file_atomic(url, dest):
    tmp_dest = dest + '.tmp'
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            total_length = r.headers.get('content-length')
            dl = 0
            total_bytes = int(total_length) if total_length else None
            with open(tmp_dest, 'wb') as f:
                for chunk in r.iter_content(chunk_size=16384):
                    if chunk:
                        f.write(chunk)
                        dl += len(chunk)
                        if total_bytes:
                            percent = int(100 * dl / total_bytes)
                            print(f'Progress: {percent}% ({dl // 1024} KB / {total_bytes // 1024} KB)', end='\r', flush=True)
                        else:
                            print(f'Downloaded: {dl // 1024} KB', end='\r', flush=True)
        print('\nDownload complete.', flush=True)
        os.rename(tmp_dest, dest)
    except Exception as e:
        if os.path.exists(tmp_dest):
            os.remove(tmp_dest)
        raise e

if not os.path.exists(VISION_PROTOTXT):
    print(f'Downloading Vision Pbtxt to {VISION_PROTOTXT}...', flush=True)
    try:
        download_file_atomic(VISION_PROTOTXT_URL, VISION_PROTOTXT)
        print('Vision Pbtxt downloaded successfully.', flush=True)
    except Exception as e:
        print(f'Network download failed: {e}', flush=True)

if not os.path.exists(VISION_MODEL):
    print(f'Downloading Vision Model to {VISION_MODEL}...', flush=True)
    try:
        download_file_atomic(VISION_MODEL_URL, VISION_MODEL)
        print('Vision Model downloaded successfully.', flush=True)
    except Exception as e:
        print(f'Network download failed: {e}', flush=True)

def py_error_handler(filename, line, function, err, fmt): pass
ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)
c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)
try:
    asound = cdll.LoadLibrary('libasound.so.2')
    asound.snd_lib_error_set_handler(c_error_handler)
except Exception:
    pass

LLAMA_API_URL = os.getenv('LLAMA_API_URL', 'http://localhost:8080/completion')
HEALTH_URL = os.getenv('HEALTH_URL', 'http://localhost:8080/health')

COCO_LABELS = {
    1: 'person', 2: 'bicycle', 3: 'car', 4: 'motorcycle', 5: 'airplane',
    6: 'bus', 7: 'train', 8: 'truck', 9: 'boat', 10: 'traffic light',
    11: 'fire hydrant', 13: 'stop sign', 14: 'parking meter', 15: 'bench',
    16: 'bird', 17: 'cat', 18: 'dog', 19: 'horse', 20: 'sheep',
    21: 'cow', 22: 'elephant', 23: 'bear', 24: 'zebra', 25: 'giraffe',
    27: 'backpack', 28: 'umbrella', 31: 'handbag', 32: 'tie', 33: 'suitcase',
    34: 'frisbee', 35: 'skis', 36: 'snowboard', 37: 'sports ball', 38: 'kite',
    39: 'baseball bat', 40: 'baseball glove', 41: 'skateboard', 42: 'surfboard',
    43: 'tennis racket', 44: 'bottle', 46: 'wine glass', 47: 'cup', 48: 'fork',
    49: 'knife', 50: 'spoon', 51: 'bowl', 52: 'banana', 53: 'apple',
    54: 'sandwich', 55: 'orange', 56: 'broccoli', 57: 'carrot', 58: 'hot dog',
    59: 'pizza', 60: 'donut', 61: 'cake', 62: 'chair', 63: 'couch',
    64: 'potted plant', 65: 'bed', 67: 'dining table', 70: 'toilet',
    72: 'tv', 73: 'laptop', 74: 'mouse', 75: 'remote', 76: 'keyboard',
    77: 'cell phone', 78: 'microwave', 79: 'oven', 80: 'toaster', 81: 'sink',
    82: 'refrigerator', 84: 'book', 85: 'clock', 86: 'vase', 87: 'scissors',
    88: 'teddy bear', 89: 'hair drier', 90: 'toothbrush'
}

os.makedirs(WORKSPACE_DIR, exist_ok=True)
tts_queue = queue.Queue(maxsize=50)
audio_queue = queue.Queue(maxsize=100)
HTTP_SESSION = requests.Session()

stt_model = None
net = None
vision_trigger_event = threading.Event()

def get_article(word):
    # Determines if 'a' or 'an' is appropriate
    return 'an' if word[0].lower() in 'aeiou' else 'a'

def vision_worker():
    global net, COCO_LABELS
    while True:
        vision_trigger_event.wait()
        vision_trigger_event.clear()
        
        if net is None:
            tts_queue.put('Vision subsystem offline.')
            continue

        try:
            camera_module = Picamera2()
            camera_configuration = camera_module.create_still_configuration()
            camera_configuration['main']['size'] = (300, 300)
            camera_configuration['main']['format'] = 'RGB888'
            
            camera_module.configure(camera_configuration)
            camera_module.start()
            
            image_array = camera_module.capture_array()
            
            camera_module.stop()
            camera_module.close()

            if image_array is None:
                print('\n[VISION ERROR] Image matrix failed to populate.', flush=True)
                continue

            blob = cv2.dnn.blobFromImage(
                image_array, 
                size=(300, 300), 
                swapRB=True, 
                crop=False
            )
            
            net.setInput(blob)
            detections = net.forward()
            
            seen_objects = []
            for i in range(detections.shape[2]):
                confidence = detections[0, 0, i, 2]
                if confidence > 0.30:
                    idx = int(detections[0, 0, i, 1])
                    if idx in COCO_LABELS and COCO_LABELS[idx] not in seen_objects:
                        seen_objects.append(COCO_LABELS[idx])

            if not seen_objects:
                response = 'I do not see any familiar objects.'
            elif len(seen_objects) == 1:
                obj = seen_objects[0]
                response = f'I see {get_article(obj)} {obj}.'
            else:
                # Build list with proper articles
                formatted_items = [f'{get_article(obj)} {obj}' for obj in seen_objects]
                items = ', '.join(formatted_items[:-1])
                response = f'I see {items}, and {formatted_items[-1]}.'
            
            print(f'\n[VISION] AI: {response}', flush=True)
            tts_queue.put(response)
            chat_memory.save('what do you see', response)

        except Exception as e:
            print(f'\n[VISION ERROR] {e}', flush=True)
            tts_queue.put('Processing failure in vision subsystem.')

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
                p_piper.stdin.write(f'{clean_text}\n'.encode('utf-8'))
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

    def save(self, u, a):
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write(f'U: {u}\nA: {a}\n---\n')

    def get_recent_history(self):
        if not os.path.exists(self.path): return ''
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                content = f.read()
            turns = [t.strip() for t in content.split('---') if t.strip()]
            
            if not turns:
                return ''
                
            formatted_history = ''
            turn = turns[-1]
            lines = turn.split('\n')
            if len(lines) >= 2:
                u_text = lines[0][3:] if lines[0].startswith('U: ') else lines[0]
                a_text = lines[1][3:] if lines[1].startswith('A: ') else lines[1]
                formatted_history = f'<|im_start|>user\n{u_text}<|im_end|>\n<|im_start|>assistant\n{a_text}<|im_end|>\n'
            return formatted_history
        except Exception:
            return ''

chat_memory = Memory(HISTORY_FILE)

def stream_think(prompt, sys_context=''):
    recent_history_turn = chat_memory.get_recent_history()
    now = datetime.datetime.now()
    timestamp_info = f'Date: {now.strftime("%A, %B %d, %Y")}. Time: {now.strftime("%H:%M")}.'

    SYSTEM_PROMPT = (
        f'You are {AGENT_NAME}, a hardware integrated polite voice assistant. '
        f'You possess a camera and run on a 7 volt battery. '
        f'Constraint 1: Never say As an AI or deny having physical sensors. '
        f'Constraint 2: Responses MUST be short, maximum 1 or 2 sentences. Zero conversational filler. '
        f'{timestamp_info}'
    )

    if sys_context:
        SYSTEM_PROMPT += f'\nCURRENT SENSOR DATA: {sys_context}'

    full_prompt = (
        f'<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n'
        f'{recent_history_turn}'
        f'<|im_start|>user\n{prompt}<|im_end|>\n'
        f'<|im_start|>assistant\n'
    )

    full_text, sentence = [], []
    is_thinking = False

    payload = {
        'prompt': full_prompt, 
        'stream': True,
        'cache_prompt': True, 
        'n_predict': 128,
        'stop': ['<|im_end|>', '<|im_start|>', 'U:', 'A:', 'user:']
    }

    try:
        with HTTP_SESSION.post(LLAMA_API_URL, json=payload, stream=True) as r:
            for line in r.iter_lines():
                if not line: continue
                try:
                    data = json.loads(line.decode('utf-8')[6:])
                    token = data.get('content', '')
                except Exception:
                    continue

                if any(x in token.lower() for x in ['thought', '<|']):
                    is_thinking = True; continue
                if is_thinking and ('>' in token or '\n' in token):
                    is_thinking = False; continue
                if is_thinking: continue

                print(token, end='', flush=True)
                full_text.append(token)
                sentence.append(token)

                if any(c in token for c in '.!?\n,:;'):
                    chunk = ''.join(sentence).strip()
                    if len(chunk) > 1: tts_queue.put(chunk)
                    sentence.clear()

            print('\n', flush=True) 
            if sentence: tts_queue.put(''.join(sentence).strip())
            chat_memory.save(prompt, ''.join(full_text).strip())
    except Exception as e: 
        print(f'LLM Connection Error: {e}', flush=True)

def audio_callback(in_data, frame_count, time_info, status):
    try:
        audio_queue.put_nowait(in_data)
    except queue.Full: pass
    return (None, pyaudio.paContinue)

def main():
    global stt_model, net
    generate_beep_file()
    threading.Thread(target=piper_worker, daemon=True).start()
    threading.Thread(target=vision_worker, daemon=True).start()
    
    print('[SYSTEM STARTUP] Loading computer vision graph weights...', flush=True)
    try:
        if os.path.exists(VISION_PROTOTXT) and os.path.exists(VISION_MODEL):
            net = cv2.dnn.readNetFromTensorflow(VISION_MODEL, VISION_PROTOTXT)
            net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
            print('[SYSTEM STARTUP] Computer vision neural network initialized successfully.', flush=True)
        else:
            print('[SYSTEM STARTUP] Vision assets completely missing.', flush=True)
            net = None
    except Exception as e:
        print(f'[SYSTEM STARTUP] Neural network critical loading failure: error={e}', flush=True)
        net = None

    print(f'[SYSTEM STARTUP] Map complete. Loaded {len(COCO_LABELS)} tracking labels.', flush=True)

    print('[SYSTEM STARTUP] Loading speech recognition model into memory...', flush=True)
    stt_model = Model(MODEL_PATH)
    print('[SYSTEM STARTUP] Speech recognition engine active.', flush=True)

    print('[SYSTEM STARTUP] Verifying server connection state...', flush=True)
    while True:
        try:
            if requests.get(HEALTH_URL, timeout=1).status_code == 200: break
        except Exception:
            time.sleep(1)

    online_msg = f'{WAKE_WORD.capitalize()} online. How can I help you?'
    print(f'\n>>> {online_msg}', flush=True)
    tts_queue.put(online_msg)
    
    pa = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, 
                     frames_per_buffer=2048, stream_callback=audio_callback)
    
    stream.start_stream()
    rec = KaldiRecognizer(stt_model, 16000)
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
                        cmd_lower = cmd.lower()
                        
                        if 'what do you see' in cmd_lower or 'look' in cmd_lower:
                            print('\n[WAKE WORD DETECTED]', flush=True)
                            print(f'USER: {cmd}', flush=True)
                            play_beep()
                            vision_trigger_event.set()
                        elif 'battery' in cmd_lower:
                            try:
                                voltage, current, power, percentage = battery.get_telemetry()
                                if voltage is not None:
                                    direct_response = f'The battery is at {int(percentage)} percent charge remaining.'
                                else:
                                    direct_response = 'The battery sensor is offline.'
                            except Exception as e:
                                direct_response = f'Hardware fault: {e}'
                                
                            print('\n[WAKE WORD DETECTED]', flush=True)
                            print(f'USER: {cmd}', flush=True)
                            print(f'AI: {direct_response}', flush=True)
                            play_beep()
                            tts_queue.put(direct_response)
                            chat_memory.save(cmd, direct_response)
                        else:
                            print('\n[WAKE WORD DETECTED]', flush=True)
                            print(f'USER: {cmd}', flush=True)
                            print('AI: ', end='', flush=True)
                            play_beep()
                            stream_think(cmd, sys_context='')
                            
                    in_command_mode = False
                    rec.Reset()
                
    except KeyboardInterrupt: pass
    finally:
        stream.stop_stream(); stream.close(); pa.terminate()

if __name__ == '__main__':
    main()