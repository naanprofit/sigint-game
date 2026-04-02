#!/bin/bash
# SIGINT Training Ops Launcher
cd "$(dirname "$0")"
exec /home/deck/sigint-game-venv/bin/python sigint_trainer.py "$@"
