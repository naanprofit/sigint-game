# SIGINT Training Ops

Side-scroller training game that teaches [SIGINT-Pi](https://github.com/naanprofit/sigint-pi) / [SIGINT-Deck](https://github.com/naanprofit/sigint-deck) concepts through gameplay.

Built with Pygame. Runs fullscreen on Steam Deck with controller support. No external assets -- all graphics and audio are procedurally generated.

## Install (Steam Deck)

```bash
curl -sL https://raw.githubusercontent.com/naanprofit/sigint-game/main/install.sh | bash
```

The installer clones the repo, creates a Python venv, installs pygame + numpy, sets up a desktop shortcut, and optionally adds the game to your Steam library as a non-Steam game for Game Mode.

## Manual Install (any Linux / macOS)

```bash
git clone https://github.com/naanprofit/sigint-game.git
cd sigint-game
python3 -m venv venv
venv/bin/pip install pygame numpy
venv/bin/python sigint_trainer.py
```

## Levels

| # | Level | Teaches |
|---|-------|---------|
| 1 | WiFi Reconnaissance | WiFi scanning, monitor mode, SSID capture, deauth detection |
| 2 | BLE Tracking | BLE advertisements, device fingerprinting, RSSI, spoofed beacons |
| 3 | SDR Spectrum Ops | RTL-SDR/HackRF basics, spectrum waterfall, baseline anomaly detection |
| 4 | Drone Detection | DroneID, 2.4/5.8 GHz control links, EMI from motors, fiber-optic drones |
| 5 | Sentinel Mode | Autonomous monitoring, watchlist scanning, alert pipelines |
| 6 | SIEM Analysis | FTS5 search, log budgets, time filters, Watch mode, event export |
| 7 | Antenna Array Setup | 4-sector LPDA/yagi/panel layout, mounting, feedlines, baseline subtraction |
| 8 | KrakenSDR Direction Finding | Coherent DF, phase-based bearing, sector vs Kraken comparison |
| 9 | Flipper Zero Integration | Sub-GHz replay, RFID/NFC, IR capture, BadUSB |

## Audio

All sound effects match the real SIGINT-Pi/Deck alert system (`src/alerts/sound.rs` and browser `playAlertTone`):

| Game Event | SIGINT Alert | Sound |
|------------|-------------|-------|
| Pickup collect | NewDevice (prio 50) | 440 Hz sine, 100ms |
| Tracker enemy | TrackerDetected (prio 90) | 440>550>440 Hz triangle |
| Drone enemy | DroneDetected | 660>880>660 Hz square |
| Taking damage | AttackDetected (prio 100) | 880 Hz, 300ms |
| HP low warning | HighAlert (prio 80) | 660 Hz, 200ms |
| Level start | GeofenceEnter (prio 70) | 660 Hz, 200ms |
| Level complete | GeofenceExit (prio 70) | Ascending 330>440>660>880 Hz |
| Level fail | CriticalAlert (prio 100) | 880 Hz triple pulse |
| Menu navigate | LowAlert (prio 40) | 330 Hz, 100ms |
| Boot chime | SystemReady (prio 30) | 330>440 Hz |
| Achievement | Priority ladder | Ascending 330>440>660>880>1320 Hz |

Background music: procedural 138 BPM techno (kick, hi-hat, snare, acid bassline, FM arp, pad drone).

## Achievements

10 Steam-style achievements, one per level plus "Full Operator" for completing all. Progress saved to `~/.sigint_game_save.json`.

## Controls

| Input | Action |
|-------|--------|
| D-Pad / Left Stick / Arrow Keys | Navigate menus, move player |
| A / Enter / Space | Select, jump |
| B / Esc | Back, menu |
| D-Pad Up/Down in credits | Scroll faster |

## Easter Egg

In the SIGINT-Pi/Deck web UI, go to Settings, scroll to the About section, and click the `. . .` five times.

## License

GPL-3.0-or-later
