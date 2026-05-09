# Raspberry Pi 5 System & Hardware Provisioning
**Target OS:** Raspberry Pi OS Trixie (64-bit)  
**Target Hardware:** Pi 5, Raspiaudio Zero/Audio Drive, NVMe SSD

## 🛠 Setup Overview
This script automates the following high-level configurations:
1.  **System Optimization:** Disables swap and installs essential audio/git toolchains.
2.  **Locale Fixes:** Force-configures `en_US.UTF-8` and prevents SSH locale-injection errors.
3.  **Hardware Overclocking:** Enables **PCIe Gen 3** for the Waveshare NVMe.
4.  **Audio Routing:** Disables HDMI audio to prevent card-indexing conflicts and configures a custom **ALSA dmix/dsnoop** layer for shared hardware access.

## 🚀 Step 1: Create the Provisioning Script
On your fresh install, create the setup file:
```bash
nano system_setup.sh
chmod +x system_setup.sh
./system_setup.sh
sudo reboot
```

After reboot test audio and video readiness with
```bash
aplay -l
arecord -l
aplay /usr/share/sounds/alsa/Front_Center.wav
```