#!/bin/bash

# Exit on error, undefined vars, or pipe failures
set -euo pipefail

# Configuration
SEARX_DIR="$HOME/searxng-docker"
PORT=8081
IMAGE="searxng/searxng:latest"

echo ">>> [1/7] Identity & Permission Check"
if ! groups "$USER" | grep -q "\bdocker\b"; then
    echo ">>> Adding $USER to docker group..."
    sudo usermod -aG docker "$USER"
    echo "!!! NOTICE: Group membership updated. For non-sudo docker access, you must re-log."
    echo ">>> Proceeding with sudo for current deployment session..."
fi

echo ">>> [2/7] Dependency Check"
if ! command -v docker &> /dev/null; then
    echo ">>> Docker not found. Installing..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    rm get-docker.sh
else
    echo ">>> Docker is present."
fi

echo ">>> [3/7] Environment Preparation"
# Idempotent directory creation
if [ -d "$SEARX_DIR" ]; then
    echo ">>> Backing up existing settings.yml if present..."
    [ -f "$SEARX_DIR/settings.yml" ] && cp "$SEARX_DIR/settings.yml" "$SEARX_DIR/settings.yml.bak"
fi
mkdir -p "$SEARX_DIR"
cd "$SEARX_DIR"

echo ">>> [4/7] Security Configuration"
# Only generate a new secret if one doesn't exist to prevent session invalidation on updates
if [ ! -f .env_secret ]; then
    openssl rand -hex 32 > .env_secret
fi
SECRET_KEY=$(cat .env_secret)

echo ">>> [5/7] Generating Settings"
cat <<EOF > settings.yml
use_default_settings: true
server:
  secret_key: "$SECRET_KEY"
  bind_address: "0.0.0.0"
search:
  formats:
    - html
    - json
EOF

echo ">>> [6/7] Deployment"
# Ensure we clean up existing container to avoid name conflicts
sudo docker rm -f searxng 2>/dev/null || true

# Run with explicit resource limits and restart policy
sudo docker run -d \
    --name searxng \
    --restart unless-stopped \
    -p "$PORT:8080" \
    -v "$(pwd)/settings.yml:/etc/searxng/settings.yml:ro" \
    --cap-drop ALL \
    --cap-add CHOWN \
    --cap-add SETGID \
    --cap-add SETUID \
    "$IMAGE"

echo ">>> [7/7] Verification"
MAX_RETRIES=15
for i in $(seq 1 $MAX_RETRIES); do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$PORT/search?q=health&format=json" || echo "000")
    if [ "$STATUS" == "200" ]; then
        echo ">>> SUCCESS: SearXNG online at http://localhost:$PORT"
        exit 0
    fi
    echo ">>> Waiting for service... ($i/$MAX_RETRIES)"
    sleep 2
done

echo ">>> ERROR: Service failed to respond. Check logs:"
sudo docker logs searxng
exit 1