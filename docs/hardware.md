# Hardware

Two builds are supported. The Pi 5 build is the reference: more memory, a much
larger model, and retrieval over your files. The Pi 4 build trades that for
sensors — a camera and a battery gauge — on a smaller model.

## Raspberry Pi 5 build

| Component | Specification |
| :--- | :--- |
| **SBC** | Raspberry Pi 5 Model B, 8 GB |
| **Cooling** | Raspberry Pi Active Cooler |
| **Timekeeping** | RTC battery |
| **Power management** | Geekworm X1200 UPS + 2× 18650 cells |
| **Enclosure** | Geekworm X1200-C1 case |
| **Storage** | Waveshare 256 GB NVMe 2242 |
| **Audio I/O** | Raspiaudio Pi Audio Drive |

Notes:

- The 8 GB model matters. Gemma 4 E4B at 4096 context plus ChromaDB and a
  sentence-transformers model does not fit comfortably in less.
- NVMe runs at PCIe Gen 3, which `system-setup.sh` enables via
  `dtparam=pciex1_gen=3`. This is above the officially rated speed; if the drive
  misbehaves, remove that line from `profiles/pi5.conf` and re-run the script.
- The Raspiaudio board presents as card `Zero`.

## Raspberry Pi 4 build

| Component | Specification |
| :--- | :--- |
| **SBC** | Raspberry Pi 4 Model B |
| **Audio I/O** | Google VoiceHAT (`googlevoicehat-soundcard`) |
| **Camera** | OV5647 module (`dtoverlay=ov5647`) |
| **Battery telemetry** | INA219 current/voltage sensor at I²C address `0x42` |
| **Storage** | microSD, 32 GB or larger |

Notes:

- The VoiceHAT has no hardware mixer, so `system-setup.sh` inserts ALSA
  `softvol` layers to give you `Master` and `MicMaster` controls. Adjust with
  `alsamixer -c sndrpigooglevoi`.
- A fixed 4 GB swapfile is configured because the llama.cpp build exhausts RAM
  otherwise.
- The INA219 driver in [`src/native_ai/battery.py`](../src/native_ai/battery.py)
  is calibrated for 16 V / 5 A and reports percentage against a 6.0 V–8.4 V
  range (a 2S lithium pack). Change `get_telemetry()` if your pack differs.
- The camera and I²C need `dtparam=i2c_arm=on` and the `ov5647` overlay, both
  applied by `system-setup.sh`.

## Shared requirements

- **Raspberry Pi OS Trixie, 64-bit.** The installer refuses to run on a 32-bit
  system: Piper and llama.cpp are fetched as arm64 builds.
- A microphone and speaker wired to the HAT.
- Network access for the first install only. After that everything runs offline —
  the assistant sets `TRANSFORMERS_OFFLINE` at startup.
