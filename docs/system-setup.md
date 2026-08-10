# System & Hardware Provisioning

**Target OS:** Raspberry Pi OS Trixie (64-bit)
**Applies to:** both boards — see [hardware.md](hardware.md)

Run this once on a fresh image, before [install.md](install.md). It configures
the OS and the hardware; it does not install the assistant.

## What it does

1. **System update** — full upgrade, plus `locales-all`, `git` and `alsa-utils`.
2. **Locale** — generates `en_US.UTF-8` and stops SSH clients from injecting a
   locale the Pi has not generated, which otherwise produces warnings on every
   login.
3. **Firmware** — writes the board's overlays into `/boot/firmware/config.txt`:
   the sound card, and per board the NVMe PCIe speed (Pi 5) or the camera, I²C,
   SPI and I²S interfaces (Pi 4).
4. **Audio routing** — writes `/etc/asound.conf` with a `dmix`/`dsnoop` layer so
   the assistant and any shell command can share the card instead of fighting
   over it. On the Pi 4 it adds `softvol` controls, because the VoiceHAT has no
   hardware mixer.
5. **Swap** — disabled on the Pi 5; a fixed 4 GB swapfile on the Pi 4, without
   which the llama.cpp build runs out of memory.
6. **USB gadget mode** — `rpi-usb-gadget on`, so you can reach the Pi over a
   single USB-C cable with no network.

Every step is idempotent. Re-running the script leaves `config.txt` byte-identical.

## Running it

```bash
git clone <this-repo> native-ai && cd native-ai

./scripts/system-setup.sh
```

The board is detected from `/proc/device-tree/model`. To override or preview:

```bash
./scripts/system-setup.sh --board pi4     # force a profile
./scripts/system-setup.sh --dry-run       # print every action, change nothing
```

The script re-runs itself under `sudo` if needed.

## After it finishes

```bash
sudo reboot
```

The reboot is required: the firmware overlays only take effect at boot, and if
your user was just added to the `audio` group, systemd will not honour that
membership until then.

## Verifying

```bash
aplay -l      # your HAT should be listed
arecord -l    # the capture device should be listed
aplay /usr/share/sounds/alsa/Front_Center.wav
arecord -d 3 -f cd /tmp/test.wav && aplay /tmp/test.wav
```

Adjust levels with `alsamixer -c Zero` (Pi 5) or `alsamixer -c sndrpigooglevoi`
(Pi 4).

If `aplay -l` shows no card, check that the overlay landed:

```bash
grep -E 'dtoverlay|dtparam' /boot/firmware/config.txt
```

Next: [install.md](install.md).
