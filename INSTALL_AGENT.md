# Native-AI Agent Deployment Guide
**Target OS:** Raspberry Pi OS Trixie (64-bit) (Recommended)
**Required Hardware:** Raspberry Pi 5 (for Gemma 4B performance), Raspiaudio Zero/Audio Drive (configured via previous `SYSTEMSETUP.md`).
**Installation Directory:** `~/native-ai`

## 🛠 Prerequisites
Before running the installation script, ensure you have completed the fundamental hardware and audio configuration using the [system setup](system_setup.sh) that you can read [here](SYSTEM_SETUP.md).

On another system you need to have:

1.  **Audio Configured:** You must have a functional `/etc/asound.conf` routing default audio through your designated audio hardware (`dmix`/`dsnoop` highly recommended). If you have not done this, the agent will fail to capture audio or output speech.
2.  **Reboot Complete:** If you just added your user to the `audio` group manually, a reboot is required for systemd to respect the new group permissions.

## 🚀 Step 1: Create the Agent Deployment Script
Create a new file in your home directory:
```bash
nano install_agent.sh
chmod +x install_agent.sh
./install_agent.sh
```