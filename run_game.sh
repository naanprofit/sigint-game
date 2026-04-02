#!/bin/bash
# SIGINT Training Ops Launcher
cd "$(dirname "$0")"

# In Steam Game Mode, gamescope provides an xwayland display.
# Steam sets DISPLAY when launching; if missing, find it.
if [ -z "$DISPLAY" ]; then
    # gamescope xwayland is typically :1 in Game Mode
    for d in :1 :0 :2; do
        if xdpyinfo -display "$d" >/dev/null 2>&1; then
            export DISPLAY="$d"
            break
        fi
    done
fi

# Force SDL to use x11 (gamescope provides xwayland)
export SDL_VIDEODRIVER=x11
# Ensure SDL sees the gamepad
export SDL_GAMECONTROLLERCONFIG=""

exec /home/deck/sigint-game-venv/bin/python sigint_trainer.py "$@"
