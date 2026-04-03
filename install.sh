#!/bin/bash
#
# SIGINT Training Ops - Steam Deck Installer
# Run this on any Steam Deck to install the game.
#
# Usage:
#   curl -sL https://raw.githubusercontent.com/naanprofit/sigint-game/main/install.sh | bash
#
# Or clone and run:
#   git clone https://github.com/naanprofit/sigint-game.git
#   cd sigint-game && bash install.sh
#

set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

GAME_DIR="$HOME/sigint-game"
VENV_DIR="$HOME/sigint-game-venv"
REPO_URL="https://github.com/naanprofit/sigint-game.git"

echo -e "${CYAN}"
echo "  ╔══════════════════════════════════════════╗"
echo "  ║     SIGINT Training Ops - Installer      ║"
echo "  ║  Side-scroller training for SIGINT-Deck   ║"
echo "  ╚══════════════════════════════════════════╝"
echo -e "${NC}"

# ── Check we're on a Steam Deck (or at least Linux) ──
if [ "$(uname)" != "Linux" ]; then
    echo -e "${RED}This installer is designed for Linux / Steam Deck.${NC}"
    echo "For other platforms, clone the repo and run with Python 3 + pygame."
    exit 1
fi

echo -e "${GREEN}[1/5]${NC} Checking Python..."
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}Python 3 not found. On Steam Deck, it should be pre-installed.${NC}"
    exit 1
fi
PYVER=$(python3 --version 2>&1)
echo "  Found: $PYVER"

echo ""
echo -e "${GREEN}[2/5]${NC} Downloading game files..."
if [ -d "$GAME_DIR/.git" ]; then
    echo "  Game directory exists, updating..."
    cd "$GAME_DIR"
    git pull origin main 2>/dev/null || {
        echo "  Git pull failed, re-cloning..."
        cd "$HOME"
        rm -rf "$GAME_DIR"
        git clone "$REPO_URL" "$GAME_DIR"
    }
else
    if [ -d "$GAME_DIR" ]; then
        rm -rf "$GAME_DIR"
    fi
    git clone "$REPO_URL" "$GAME_DIR"
fi
echo "  Done."

echo ""
echo -e "${GREEN}[3/5]${NC} Setting up Python virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo "  Created venv at $VENV_DIR"
else
    echo "  Venv already exists at $VENV_DIR"
fi

echo "  Installing dependencies..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip 2>/dev/null || true
"$VENV_DIR/bin/pip" install --quiet pygame numpy 2>&1 | tail -2
echo "  Done."

echo ""
echo -e "${GREEN}[4/5]${NC} Making launcher executable..."
chmod +x "$GAME_DIR/run_game.sh"
echo "  Done."

echo ""
echo -e "${GREEN}[5/5]${NC} Installing desktop shortcut..."
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/sigint-training-ops.desktop" << EOF
[Desktop Entry]
Name=SIGINT Training Ops
Comment=Side-scroller training game for SIGINT-Deck / SIGINT-Pi
Exec=$GAME_DIR/run_game.sh
Icon=applications-games
Terminal=false
Type=Application
Categories=Game;
EOF
echo "  Desktop shortcut installed."

# ── Optional: Add as non-Steam game ──
echo ""
echo -e "${YELLOW}Add to Steam library as a non-Steam game?${NC}"
echo "  This makes it launchable from Game Mode with controller support."
echo ""
read -p "  Add to Steam? [Y/n] " -n 1 -r ADD_STEAM
echo ""

if [[ ! "$ADD_STEAM" =~ ^[Nn]$ ]]; then
    if command -v steamos-add-to-steam &>/dev/null; then
        if pgrep -x steam &>/dev/null; then
            steamos-add-to-steam "$GAME_DIR/run_game.sh" 2>/dev/null && {
                echo -e "  ${GREEN}Added to Steam!${NC}"
                echo "  Look for 'run_game.sh' in your Steam library."
                echo "  You can rename it to 'SIGINT Training Ops' in Steam properties."
            } || {
                echo -e "  ${YELLOW}Could not add automatically.${NC}"
                echo "  To add manually:"
                echo "    1. Open Steam > Library > Add a Game > Add a Non-Steam Game"
                echo "    2. Click Browse, navigate to: $GAME_DIR/run_game.sh"
                echo "    3. Click Add Selected Programs"
            }
        else
            echo -e "  ${YELLOW}Steam is not running.${NC}"
            echo "  Start Steam first, then run:"
            echo "    steamos-add-to-steam $GAME_DIR/run_game.sh"
        fi
    else
        echo "  steamos-add-to-steam not found (not a Steam Deck?)."
        echo "  To add manually in Steam:"
        echo "    1. Library > Add a Game > Add a Non-Steam Game"
        echo "    2. Browse to: $GAME_DIR/run_game.sh"
    fi
else
    echo "  Skipped. You can add it later:"
    echo "    steamos-add-to-steam $GAME_DIR/run_game.sh"
fi

echo ""
echo -e "${CYAN}══════════════════════════════════════════${NC}"
echo -e "${GREEN}Installation complete!${NC}"
echo ""
echo "  To run from terminal:"
echo -e "    ${CYAN}$GAME_DIR/run_game.sh${NC}"
echo ""
echo "  To run from Desktop Mode:"
echo "    Find 'SIGINT Training Ops' in your application menu"
echo ""
echo "  To run from Game Mode:"
echo "    Find 'run_game.sh' in your Steam library"
echo "    (rename it in Properties > Shortcut > Name)"
echo ""
echo "  Controls:"
echo "    D-Pad / Left Stick / Arrow Keys  - Navigate / Move"
echo "    A / Enter / Space                - Select / Jump"
echo "    B / Esc                          - Back / Menu"
echo ""
echo -e "${CYAN}  Learn SIGINT. Detect threats. Have fun.${NC}"
echo -e "${CYAN}══════════════════════════════════════════${NC}"
