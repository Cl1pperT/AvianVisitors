#!/usr/bin/env bash
# Explicitly install the weather timer. This script never disables or edits the
# existing bird-frame timer; it refuses to continue while that timer owns the panel.
set -euo pipefail
cd "$(dirname "$0")"
WEATHER="$(pwd)"
ROOT="$(cd .. && pwd)"
PYTHON="$ROOT/frame/.venv/bin/python"
CONFIG="$HOME/.weatherframe/config.toml"

if systemctl is-active --quiet birdframe.timer || systemctl is-enabled --quiet birdframe.timer 2>/dev/null; then
  echo "birdframe.timer is active or enabled; refusing to create two panel writers." >&2
  echo "To switch deliberately, first run: sudo systemctl disable --now birdframe.timer" >&2
  exit 1
fi
if [ ! -x "$PYTHON" ]; then
  echo "$PYTHON is missing; install the AvianVisitors frame environment first." >&2
  exit 1
fi
if [ ! -f "$CONFIG" ]; then
  echo "$CONFIG is missing. Copy config.example.toml there and set location first." >&2
  exit 1
fi

ROOT_SED="$(printf '%s' "$ROOT" | sed 's/[&|]/\\&/g')"
HOME_SED="$(printf '%s' "$HOME" | sed 's/[&|]/\\&/g')"
USER_SED="$(printf '%s' "$USER" | sed 's/[&|]/\\&/g')"
sed "s|@ROOT@|$ROOT_SED|g; s|@HOME@|$HOME_SED|g; s|@USER@|$USER_SED|g" \
  "$WEATHER/systemd/weatherframe.service" |
  sudo tee /etc/systemd/system/weatherframe.service >/dev/null
sudo cp "$WEATHER/systemd/weatherframe.timer" /etc/systemd/system/weatherframe.timer
sudo systemctl daemon-reload
sudo systemctl enable --now weatherframe.timer
echo "weatherframe.timer enabled for 06:05 local time."

