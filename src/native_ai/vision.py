"""
Camera object detection (Pi 4).

Imports cv2 and picamera2 lazily so a board with FEATURE_VISION=0 never needs
either package installed.
"""
import os
import threading

import requests

from . import audio, config
from .memory import get_memory

COCO_LABELS = {
    1: "person", 2: "bicycle", 3: "car", 4: "motorcycle", 5: "airplane",
    6: "bus", 7: "train", 8: "truck", 9: "boat", 10: "traffic light",
    11: "fire hydrant", 13: "stop sign", 14: "parking meter", 15: "bench",
    16: "bird", 17: "cat", 18: "dog", 19: "horse", 20: "sheep",
    21: "cow", 22: "elephant", 23: "bear", 24: "zebra", 25: "giraffe",
    27: "backpack", 28: "umbrella", 31: "handbag", 32: "tie", 33: "suitcase",
    34: "frisbee", 35: "skis", 36: "snowboard", 37: "sports ball", 38: "kite",
    39: "baseball bat", 40: "baseball glove", 41: "skateboard", 42: "surfboard",
    43: "tennis racket", 44: "bottle", 46: "wine glass", 47: "cup", 48: "fork",
    49: "knife", 50: "spoon", 51: "bowl", 52: "banana", 53: "apple",
    54: "sandwich", 55: "orange", 56: "broccoli", 57: "carrot", 58: "hot dog",
    59: "pizza", 60: "donut", 61: "cake", 62: "chair", 63: "couch",
    64: "potted plant", 65: "bed", 67: "dining table", 70: "toilet",
    72: "tv", 73: "laptop", 74: "mouse", 75: "remote", 76: "keyboard",
    77: "cell phone", 78: "microwave", 79: "oven", 80: "toaster", 81: "sink",
    82: "refrigerator", 84: "book", 85: "clock", 86: "vase", 87: "scissors",
    88: "teddy bear", 89: "hair drier", 90: "toothbrush",
}

trigger_event = threading.Event()

_net = None


def get_article(word):
    """'a' or 'an', so the spoken sentence does not grate."""
    return "an" if word[0].lower() in "aeiou" else "a"


def download_file_atomic(url, dest):
    """Download to a .tmp sibling and rename, so a killed run leaves no stub."""
    tmp_dest = dest + ".tmp"
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            total_length = r.headers.get("content-length")
            downloaded = 0
            total_bytes = int(total_length) if total_length else None
            with open(tmp_dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=16384):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_bytes:
                        percent = int(100 * downloaded / total_bytes)
                        print(
                            f"Progress: {percent}% ({downloaded // 1024} KB / {total_bytes // 1024} KB)",
                            end="\r",
                            flush=True,
                        )
                    else:
                        print(f"Downloaded: {downloaded // 1024} KB", end="\r", flush=True)
        print("\nDownload complete.", flush=True)
        os.rename(tmp_dest, dest)
    except Exception:
        if os.path.exists(tmp_dest):
            os.remove(tmp_dest)
        raise


def ensure_assets():
    """Fetch the MobileNet-SSD graph and its config on first run."""
    os.makedirs(config.VISION_DIR, exist_ok=True)
    for url, dest, label in (
        (config.VISION_PROTOTXT_URL, config.VISION_PROTOTXT, "Vision Pbtxt"),
        (config.VISION_MODEL_URL, config.VISION_MODEL, "Vision Model"),
    ):
        if os.path.exists(dest):
            continue
        print(f"Downloading {label} to {dest}...", flush=True)
        try:
            download_file_atomic(url, dest)
            print(f"{label} downloaded successfully.", flush=True)
        except Exception as e:
            print(f"Network download failed: {e}", flush=True)


def load_network():
    """Load the DNN into memory. Leaves _net as None on any failure."""
    global _net
    import cv2

    print("[SYSTEM STARTUP] Loading computer vision graph weights...", flush=True)
    try:
        if os.path.exists(config.VISION_PROTOTXT) and os.path.exists(config.VISION_MODEL):
            _net = cv2.dnn.readNetFromTensorflow(config.VISION_MODEL, config.VISION_PROTOTXT)
            _net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            _net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
            print("[SYSTEM STARTUP] Computer vision neural network initialized successfully.", flush=True)
        else:
            print("[SYSTEM STARTUP] Vision assets completely missing.", flush=True)
            _net = None
    except Exception as e:
        print(f"[SYSTEM STARTUP] Neural network critical loading failure: error={e}", flush=True)
        _net = None
    print(f"[SYSTEM STARTUP] Map complete. Loaded {len(COCO_LABELS)} tracking labels.", flush=True)


def _describe(seen_objects):
    if not seen_objects:
        return "I do not see any familiar objects."
    if len(seen_objects) == 1:
        obj = seen_objects[0]
        return f"I see {get_article(obj)} {obj}."
    formatted = [f"{get_article(obj)} {obj}" for obj in seen_objects]
    return f"I see {', '.join(formatted[:-1])}, and {formatted[-1]}."


def worker():
    """Daemon thread: on trigger, capture one frame and speak what is in it."""
    import cv2
    from picamera2 import Picamera2

    while True:
        trigger_event.wait()
        trigger_event.clear()

        if _net is None:
            audio.speak("Vision subsystem offline.")
            continue

        try:
            camera = Picamera2()
            camera_configuration = camera.create_still_configuration()
            camera_configuration["main"]["size"] = (300, 300)
            camera_configuration["main"]["format"] = "RGB888"

            camera.configure(camera_configuration)
            camera.start()
            image_array = camera.capture_array()
            camera.stop()
            camera.close()

            if image_array is None:
                print("\n[VISION ERROR] Image matrix failed to populate.", flush=True)
                continue

            blob = cv2.dnn.blobFromImage(image_array, size=(300, 300), swapRB=True, crop=False)
            _net.setInput(blob)
            detections = _net.forward()

            seen_objects = []
            for i in range(detections.shape[2]):
                confidence = detections[0, 0, i, 2]
                if confidence <= config.VISION_CONFIDENCE:
                    continue
                idx = int(detections[0, 0, i, 1])
                if idx in COCO_LABELS and COCO_LABELS[idx] not in seen_objects:
                    seen_objects.append(COCO_LABELS[idx])

            response = _describe(seen_objects)
            print(f"\n[VISION] AI: {response}", flush=True)
            audio.speak(response)
            get_memory().save("what do you see", response)

        except Exception as e:
            print(f"\n[VISION ERROR] {e}", flush=True)
            audio.speak("Processing failure in vision subsystem.")


def start():
    """Prepare assets, load the graph, and return the worker for threading."""
    # libcamera is chatty on stdout; quiet it before picamera2 pulls it in.
    os.environ.setdefault("LIBCAMERA_LOG_LEVELS", "ERROR")
    ensure_assets()
    load_network()
    return worker
