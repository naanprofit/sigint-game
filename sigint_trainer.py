#!/usr/bin/env python3
"""
SIGINT-Deck Training Ops -- Side-Scroller Training Game
Teaches SIGINT-Pi / SIGINT-Deck concepts through gameplay.
Runs fullscreen on Steam Deck with controller support.
"""

import pygame
import sys
import math
import random
import json
import os
import time
import struct
import array as _array

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

# ── Constants ──────────────────────────────────────────────────────────────────

SCREEN_W, SCREEN_H = 1280, 800
FPS = 60
GRAVITY = 0.6
JUMP_FORCE = -12
PLAYER_SPEED = 5
SCROLL_SPEED = 3

# Colors
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GREEN = (0, 255, 100)
RED = (255, 60, 60)
BLUE = (60, 140, 255)
YELLOW = (255, 220, 50)
ORANGE = (255, 160, 40)
PURPLE = (180, 80, 255)
CYAN = (0, 220, 220)
DARK_BG = (12, 14, 20)
PANEL_BG = (20, 24, 35)
HUD_BG = (10, 12, 18, 200)
GRID_COLOR = (25, 30, 45)
ACCENT_GREEN = (0, 255, 136)
ACCENT_BLUE = (60, 180, 255)
ACCENT_RED = (255, 80, 80)
ACCENT_YELLOW = (255, 200, 60)

SAVE_FILE = os.path.expanduser("~/.sigint_game_save.json")
SAMPLE_RATE = 44100

# ── Procedural Audio Engine ────────────────────────────────────────────────────
# All sounds match the real SIGINT-Pi/Deck alerting system:
#   Backend: src/alerts/sound.rs  (SoundEffect enum, play_system_beep frequencies)
#   Browser: static/index.html    (playAlertTone WebAudio tones)
#
# Priority → Frequency mapping (from sound.rs play_system_beep):
#   Critical/Attack (90-100) → 880 Hz, 300ms
#   Tracker/Geofence (70-89) → 660 Hz, 200ms
#   Medium/NewDevice (50-69) → 440 Hz, 100ms
#   Low/System       (<50)   → 330 Hz, 100ms
#
# Browser playAlertTone (from index.html):
#   drone:   square wave 660→880→660 Hz
#   tracker: triangle wave 440→550→440 Hz
#   default: sine 523 Hz

class AudioEngine:
    """Procedural audio matching SIGINT-Pi/Deck alert system. No files needed."""

    def __init__(self):
        try:
            pygame.mixer.pre_init(SAMPLE_RATE, -16, 2, 512)
            pygame.mixer.init()
            self.enabled = True
        except Exception:
            self.enabled = False
            return

        self.sfx = {}
        self.music_playing = False
        self.bar_pos = 0
        self._generate_sfx()
        self._generate_music_loops()

    # ── Waveform primitives ────────────────────────────────────────────

    def _make_sound(self, samples_float, volume=1.0):
        """Convert float [-1,1] mono array to stereo pygame Sound."""
        if HAS_NUMPY:
            s = np.clip(samples_float, -1, 1)
            s = (s * volume * 32767).astype(np.int16)
            return pygame.sndarray.make_sound(np.column_stack((s, s)))
        # fallback: already a Sound
        return samples_float

    def _sine(self, freq, duration, volume=0.3):
        n = int(SAMPLE_RATE * duration)
        if HAS_NUMPY:
            t = np.linspace(0, duration, n, endpoint=False)
            return self._make_sound(np.sin(2 * np.pi * freq * t), volume)
        buf = _array.array("h")
        for i in range(n):
            v = int(math.sin(2 * math.pi * freq * i / SAMPLE_RATE) * volume * 32767)
            buf.append(v); buf.append(v)
        return pygame.mixer.Sound(buffer=buf)

    def _square(self, freq, duration, volume=0.2):
        n = int(SAMPLE_RATE * duration)
        if HAS_NUMPY:
            t = np.linspace(0, duration, n, endpoint=False)
            return self._make_sound(np.sign(np.sin(2 * np.pi * freq * t)), volume)
        return self._sine(freq, duration, volume)

    def _triangle(self, freq, duration, volume=0.25):
        n = int(SAMPLE_RATE * duration)
        if HAS_NUMPY:
            t = np.linspace(0, duration, n, endpoint=False)
            phase = (t * freq) % 1.0
            wave = 2 * np.abs(2 * phase - 1) - 1
            return self._make_sound(wave, volume)
        return self._sine(freq, duration, volume)

    def _saw(self, freq, duration, volume=0.2):
        n = int(SAMPLE_RATE * duration)
        if HAS_NUMPY:
            t = np.linspace(0, duration, n, endpoint=False)
            wave = ((t * freq) % 1.0) * 2 - 1
            env = np.linspace(1, 0, n) ** 0.5
            return self._make_sound(wave * env, volume)
        return self._sine(freq, duration, volume)

    def _noise(self, duration, volume=0.15):
        n = int(SAMPLE_RATE * duration)
        if HAS_NUMPY:
            raw = np.random.uniform(-1, 1, n)
            env = np.linspace(1, 0, n) ** 2
            return self._make_sound(raw * env, volume)
        buf = _array.array("h")
        for i in range(n):
            v = int(random.uniform(-1, 1) * volume * 32767 * (1 - i / n) ** 2)
            buf.append(v); buf.append(v)
        return pygame.mixer.Sound(buffer=buf)

    def _sweep_tone(self, f_start, f_end, duration, waveform="sine", volume=0.3):
        """Frequency sweep (used for drone alerts, kicks)."""
        n = int(SAMPLE_RATE * duration)
        if HAS_NUMPY:
            t = np.linspace(0, duration, n, endpoint=False)
            freq = np.linspace(f_start, f_end, n)
            phase = np.cumsum(freq / SAMPLE_RATE) * 2 * np.pi
            if waveform == "square":
                wave = np.sign(np.sin(phase))
            else:
                wave = np.sin(phase)
            env = np.exp(-t * (3 / duration))
            return self._make_sound(wave * env, volume)
        return self._sine((f_start + f_end) / 2, duration, volume)

    def _multi_tone(self, segments, waveform="sine", volume=0.3):
        """Build a sound from [(freq, duration), ...] segments.
        Matches the browser playAlertTone pattern."""
        if not HAS_NUMPY:
            f = segments[0][0] if segments else 440
            d = sum(s[1] for s in segments)
            return self._sine(f, d, volume)
        parts = []
        for freq, dur in segments:
            n = int(SAMPLE_RATE * dur)
            t = np.linspace(0, dur, n, endpoint=False)
            if waveform == "square":
                w = np.sign(np.sin(2 * np.pi * freq * t))
            elif waveform == "triangle":
                phase = (t * freq) % 1.0
                w = 2 * np.abs(2 * phase - 1) - 1
            else:
                w = np.sin(2 * np.pi * freq * t)
            parts.append(w)
        wave = np.concatenate(parts)
        total_n = len(wave)
        # Exponential decay envelope matching browser gain.exponentialRampToValueAtTime
        env = np.exp(-np.linspace(0, 4, total_n))
        return self._make_sound(wave * env, volume)

    # ── SIGINT-matched SFX ─────────────────────────────────────────────

    def _generate_sfx(self):
        if not self.enabled:
            return

        # -- NewDevice (prio 50): 440 Hz sine, 100ms
        #    → Game: pickup collect
        self.sfx["pickup"] = self._sine(440, 0.1, 0.35)

        # -- TrackerDetected (prio 90): 880 Hz, 300ms backend
        #    Browser: triangle 440→550→440 Hz
        #    → Game: enemy nearby warning
        self.sfx["tracker"] = self._multi_tone(
            [(440, 0.15), (550, 0.15), (440, 0.15)], "triangle", 0.3
        )

        # -- AttackDetected (prio 100): 880 Hz, 300ms
        #    → Game: taking damage
        self.sfx["hit"] = self._sine(880, 0.3, 0.35)

        # -- DroneDetected: square 660→880→660 (browser playAlertTone)
        #    → Game: drone level enemies
        self.sfx["drone_alert"] = self._multi_tone(
            [(660, 0.2), (880, 0.2), (660, 0.2)], "square", 0.3
        )

        # -- CriticalAlert (prio 100): 880 Hz, 300ms rapid pulse
        #    → Game: level fail
        self.sfx["critical"] = self._build_critical()

        # -- HighAlert (prio 80): 660 Hz, 200ms
        #    → Game: HP low warning
        self.sfx["high_alert"] = self._sine(660, 0.2, 0.3)

        # -- MediumAlert (prio 60): 440 Hz, 100ms
        #    → Game: tutorial page advance
        self.sfx["medium_alert"] = self._sine(440, 0.1, 0.2)

        # -- LowAlert (prio 40): 330 Hz, 100ms
        #    → Game: menu navigation
        self.sfx["low_alert"] = self._sine(330, 0.1, 0.15)

        # -- GeofenceEnter (prio 70): 660 Hz, 200ms
        #    → Game: level start / entering zone
        self.sfx["geofence_enter"] = self._sine(660, 0.2, 0.25)

        # -- GeofenceExit (prio 70): 660 Hz descending
        #    → Game: level complete
        self.sfx["geofence_exit"] = self._build_level_complete()

        # -- SystemReady (prio 30): 330 Hz, 100ms
        #    → Game: boot/ready chime
        self.sfx["system_ready"] = self._build_ready_chime()

        # -- SystemError (prio 30): 330 Hz low
        #    → Game: error state
        self.sfx["system_error"] = self._sine(330, 0.3, 0.3)

        # -- Achievement unlock (ascending arp from alert frequencies)
        self.sfx["achievement"] = self._build_achievement()

        # -- Jump (short chirp, not a real SIGINT sound)
        self.sfx["jump"] = self._sweep_tone(330, 660, 0.08, "sine", 0.15)

        # -- Sentinel mode radar ping
        self.sfx["radar_ping"] = self._sweep_tone(1200, 2400, 0.15, "sine", 0.1)

        # Aliases for easy use
        self.sfx["menu_move"] = self.sfx["low_alert"]
        self.sfx["menu_confirm"] = self.sfx["geofence_enter"]
        self.sfx["page"] = self.sfx["medium_alert"]
        self.sfx["fail"] = self.sfx["critical"]
        self.sfx["level_complete"] = self.sfx["geofence_exit"]

    def _build_critical(self):
        """CriticalAlert: triple 880 Hz pulse (matching backend 880Hz/300ms)."""
        if not HAS_NUMPY:
            return self._sine(880, 0.5, 0.35)
        parts = []
        for _ in range(3):
            n_on = int(SAMPLE_RATE * 0.1)
            n_off = int(SAMPLE_RATE * 0.05)
            t = np.linspace(0, 0.1, n_on, endpoint=False)
            parts.append(np.sin(2 * np.pi * 880 * t))
            parts.append(np.zeros(n_off))
        wave = np.concatenate(parts)
        return self._make_sound(wave, 0.35)

    def _build_level_complete(self):
        """GeofenceExit → level complete: ascending chord 330→440→660→880."""
        if not HAS_NUMPY:
            return self._sine(660, 0.6, 0.25)
        freqs = [330, 440, 660, 880]
        total_n = int(SAMPLE_RATE * 0.8)
        wave = np.zeros(total_n)
        for i, f in enumerate(freqs):
            start = int(i * SAMPLE_RATE * 0.15)
            dur = int(SAMPLE_RATE * 0.4)
            end = min(start + dur, total_n)
            t = np.arange(end - start) / SAMPLE_RATE
            wave[start:end] += np.sin(2 * np.pi * f * t) * np.exp(-t * 3) * 0.2
        return self._make_sound(np.clip(wave, -1, 1), 0.3)

    def _build_ready_chime(self):
        """SystemReady: two-tone 330→440 chime."""
        if not HAS_NUMPY:
            return self._sine(330, 0.2, 0.2)
        n1 = int(SAMPLE_RATE * 0.15)
        n2 = int(SAMPLE_RATE * 0.2)
        t1 = np.arange(n1) / SAMPLE_RATE
        t2 = np.arange(n2) / SAMPLE_RATE
        w1 = np.sin(2 * np.pi * 330 * t1) * np.exp(-t1 * 8)
        w2 = np.sin(2 * np.pi * 440 * t2) * np.exp(-t2 * 6)
        return self._make_sound(np.concatenate([w1, w2]), 0.25)

    def _build_achievement(self):
        """Achievement: ascending through the SIGINT priority frequencies."""
        if not HAS_NUMPY:
            return self._sine(880, 0.6, 0.25)
        # Walk up the alert priority ladder: 330 → 440 → 660 → 880 → 1320
        freqs = [330, 440, 660, 880, 1320]
        total_n = int(SAMPLE_RATE * 1.0)
        wave = np.zeros(total_n)
        for i, f in enumerate(freqs):
            start = int(i * SAMPLE_RATE * 0.12)
            dur = int(SAMPLE_RATE * 0.5)
            end = min(start + dur, total_n)
            t = np.arange(end - start) / SAMPLE_RATE
            wave[start:end] += np.sin(2 * np.pi * f * t) * np.exp(-t * 2) * 0.15
        return self._make_sound(np.clip(wave, -1, 1), 0.3)

    # ── Techno music loops (procedural) ────────────────────────────────

    def _generate_music_loops(self):
        if not self.enabled:
            return
        # Kick drum: pitch-swept sine (150→40 Hz)
        self.kick_sound = self._sweep_tone(150, 40, 0.25, "sine", 0.45)
        # Hi-hat: short noise burst
        self.hihat_sound = self._noise(0.04, 0.06)
        # Snare: noise + 200 Hz tone burst
        self.snare_sound = self._build_snare()
        # Acid bassline in A minor
        bass_freqs = [55, 55, 65.4, 73.4, 55, 82.4, 73.4, 65.4]
        self.bass_notes = [self._saw(f, 0.18, 0.2) for f in bass_freqs]
        # Arp: minor pentatonic using FM synthesis
        arp_freqs = [220, 261, 330, 392, 440, 523, 660, 784]
        self.arp_notes = []
        for f in arp_freqs:
            if HAS_NUMPY:
                n = int(SAMPLE_RATE * 0.1)
                t = np.linspace(0, 0.1, n, endpoint=False)
                mod = np.sin(2 * np.pi * (f * 0.5) * t) * 2.0
                wave = np.sin(2 * np.pi * f * t + mod) * np.exp(-t * 15)
                self.arp_notes.append(self._make_sound(wave, 0.08))
            else:
                self.arp_notes.append(self._sine(f, 0.1, 0.08))
        # Pad drone
        self.pad_sound = self._sine(110, 2.0, 0.06)

    def _build_snare(self):
        if not HAS_NUMPY:
            return self._noise(0.1, 0.18)
        n = int(SAMPLE_RATE * 0.12)
        t = np.linspace(0, 0.12, n, endpoint=False)
        tone = np.sin(2 * np.pi * 200 * t) * np.exp(-t * 40)
        noise = np.random.uniform(-1, 1, n) * np.exp(-t * 20)
        return self._make_sound(tone * 0.5 + noise * 0.5, 0.18)

    # ── Playback ───────────────────────────────────────────────────────

    def play(self, name):
        if not self.enabled:
            return
        snd = self.sfx.get(name)
        if snd:
            snd.play()

    def tick_music(self, frame):
        """Call every frame to drive the 138 BPM sequencer."""
        if not self.enabled or not self.music_playing:
            return
        step_frames = max(1, int(60 * 60 / (138 * 4)))
        if frame % step_frames != 0:
            return

        step = self.bar_pos % 16
        bar = (self.bar_pos // 16) % 4

        if step % 4 == 0:
            self.kick_sound.play()
        if step % 2 == 0:
            self.hihat_sound.play()
        if step in (4, 12):
            self.snare_sound.play()
        if step % 4 == 0:
            bass_idx = (step // 4 + bar * 4) % len(self.bass_notes)
            self.bass_notes[bass_idx].play()
        if bar in (1, 3) and step % 2 == 0:
            arp_idx = (step // 2 + bar) % len(self.arp_notes)
            self.arp_notes[arp_idx].play()
        if step == 0 and bar % 2 == 0:
            self.pad_sound.play()
        self.bar_pos += 1

    def start_music(self):
        self.music_playing = True
        self.bar_pos = 0

    def stop_music(self):
        self.music_playing = False


# ── Achievement Definitions ────────────────────────────────────────────────────

ACHIEVEMENTS = {
    "wifi_hunter": {
        "name": "WiFi Hunter",
        "desc": "Complete the WiFi scanning level",
        "icon": "W",
        "steam_id": "ach_wifi_hunter",
    },
    "ble_tracker": {
        "name": "BLE Tracker",
        "desc": "Complete the BLE monitoring level",
        "icon": "B",
        "steam_id": "ach_ble_tracker",
    },
    "sdr_operator": {
        "name": "SDR Operator",
        "desc": "Complete the SDR spectrum analysis level",
        "icon": "S",
        "steam_id": "ach_sdr_operator",
    },
    "drone_spotter": {
        "name": "Drone Spotter",
        "desc": "Complete the drone detection level",
        "icon": "D",
        "steam_id": "ach_drone_spotter",
    },
    "sentinel_mode": {
        "name": "Sentinel Activated",
        "desc": "Complete the sentinel mode level",
        "icon": "!",
        "steam_id": "ach_sentinel_mode",
    },
    "siem_analyst": {
        "name": "SIEM Analyst",
        "desc": "Complete the SIEM log analysis level",
        "icon": "L",
        "steam_id": "ach_siem_analyst",
    },
    "array_builder": {
        "name": "Array Builder",
        "desc": "Complete the antenna array level",
        "icon": "A",
        "steam_id": "ach_array_builder",
    },
    "kraken_master": {
        "name": "Kraken Master",
        "desc": "Complete the KrakenSDR DF level",
        "icon": "K",
        "steam_id": "ach_kraken_master",
    },
    "flipper_hacker": {
        "name": "Flipper Hacker",
        "desc": "Complete the Flipper Zero level",
        "icon": "F",
        "steam_id": "ach_flipper_hacker",
    },
    "full_operator": {
        "name": "Full Operator",
        "desc": "Complete all levels",
        "icon": "*",
        "steam_id": "ach_full_operator",
    },
}

# ── Level Definitions ──────────────────────────────────────────────────────────

LEVELS = [
    {
        "id": "wifi",
        "name": "WiFi Reconnaissance",
        "color": ACCENT_GREEN,
        "achievement": "wifi_hunter",
        "tutorial": [
            "SIGINT-Deck scans WiFi networks to detect threats.",
            "Access Points broadcast SSIDs -- your scanner captures them.",
            "Collect the signal icons to scan each AP.",
            "Avoid the DEAUTH packets -- they kick clients offline!",
            "Monitor mode lets your adapter see ALL traffic.",
        ],
        "enemy_type": "deauth",
        "pickup_type": "signal",
        "bg_element": "waves",
        "length": 8000,
    },
    {
        "id": "ble",
        "name": "BLE Tracking",
        "color": BLUE,
        "achievement": "ble_tracker",
        "tutorial": [
            "Bluetooth Low Energy devices broadcast advertisements.",
            "BLE beacons, trackers, and IoT devices are everywhere.",
            "Collect the BLE advertisements to fingerprint devices.",
            "Watch out for spoofed beacons -- they have wrong MACs!",
            "RSSI (signal strength) helps estimate device distance.",
        ],
        "enemy_type": "spoof",
        "pickup_type": "beacon",
        "bg_element": "dots",
        "length": 8000,
    },
    {
        "id": "sdr",
        "name": "SDR Spectrum Ops",
        "color": CYAN,
        "achievement": "sdr_operator",
        "tutorial": [
            "Software Defined Radio captures raw RF signals.",
            "RTL-SDR covers 24-1766 MHz. HackRF covers 1 MHz-6 GHz.",
            "The spectrum waterfall shows signal strength over time.",
            "Collect spectrum samples to build your baseline.",
            "Anomalies above baseline = potential threats!",
        ],
        "enemy_type": "interference",
        "pickup_type": "spectrum",
        "bg_element": "waterfall",
        "length": 9000,
    },
    {
        "id": "drone",
        "name": "Drone Detection",
        "color": ORANGE,
        "achievement": "drone_spotter",
        "tutorial": [
            "Drones emit RF on 2.4/5.8 GHz (control) and 900 MHz (telem).",
            "DJI drones broadcast DroneID with GPS and serial number.",
            "Motor ESCs create EMI that SDR can detect as anomalies.",
            "Fiber-optic drones have NO RF link -- EMI only detection.",
            "Baseline subtraction improves EMI range to ~100-250m.",
        ],
        "enemy_type": "drone",
        "pickup_type": "droneid",
        "bg_element": "sky",
        "length": 10000,
    },
    {
        "id": "sentinel",
        "name": "Sentinel Mode",
        "color": RED,
        "achievement": "sentinel_mode",
        "tutorial": [
            "Sentinel Mode = continuous autonomous threat monitoring.",
            "It starts all SDR monitors and scans every 30 seconds.",
            "The watchlist database tracks known bad actors.",
            "MAC addresses and RF signatures are cross-referenced.",
            "Alerts fire via TTS, webhook, email, and Telegram.",
        ],
        "enemy_type": "threat",
        "pickup_type": "alert",
        "bg_element": "radar",
        "length": 9000,
    },
    {
        "id": "siem",
        "name": "SIEM Analysis",
        "color": PURPLE,
        "achievement": "siem_analyst",
        "tutorial": [
            "The SIEM stores all events in SQLite with FTS5 search.",
            "4GB rolling log budget with automatic pruning.",
            "Time filters: Last Hour, 24h, 7d, 30d presets.",
            "Watch mode refreshes every 5 seconds for live monitoring.",
            "Export events to JSON for external analysis tools.",
        ],
        "enemy_type": "overflow",
        "pickup_type": "log",
        "bg_element": "matrix",
        "length": 8000,
    },
    {
        "id": "array",
        "name": "Antenna Array Setup",
        "color": YELLOW,
        "achievement": "array_builder",
        "tutorial": [
            "4 sectors (N/S/E/W) with RTL-SDR + HackRF each.",
            "LPDA antennas are wideband AND directional (80MHz-2GHz).",
            "Sub-GHz yagis watch 900/915 MHz telemetry bands.",
            "Dual-band panels cover 2.4/5 GHz WiFi/FPV links.",
            "Mount 2 antennas per sector: same azimuth, 1-3ft apart.",
        ],
        "enemy_type": "multipath",
        "pickup_type": "antenna",
        "bg_element": "compass",
        "length": 10000,
    },
    {
        "id": "kraken",
        "name": "KrakenSDR Direction Finding",
        "color": ACCENT_BLUE,
        "achievement": "kraken_master",
        "tutorial": [
            "KrakenSDR: 5-channel coherent RTL-SDR on one oscillator.",
            "Phase difference across antennas gives precise bearing.",
            "Sectors say 'east is hottest.' Kraken says 'bearing 073'.",
            "Krakentenna matched set ensures calibrated DF results.",
            "Combine sector detection + Kraken DF for full situational awareness.",
        ],
        "enemy_type": "jammer",
        "pickup_type": "bearing",
        "bg_element": "df_sweep",
        "length": 10000,
    },
    {
        "id": "flipper",
        "name": "Flipper Zero Integration",
        "color": ACCENT_GREEN,
        "achievement": "flipper_hacker",
        "tutorial": [
            "Flipper Zero connects via USB serial for RF replay.",
            "Sub-GHz: capture and replay garage, TPMS, weather signals.",
            "RFID/NFC: read tags, emulate cards, analyze protocols.",
            "IR: capture and replay remote control signals.",
            "BadUSB: automated keystroke injection for testing.",
        ],
        "enemy_type": "firewall",
        "pickup_type": "subghz",
        "bg_element": "flipper_bg",
        "length": 9000,
    },
]


# ── Save/Load ──────────────────────────────────────────────────────────────────

def load_save():
    try:
        with open(SAVE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"unlocked": [], "high_scores": {}, "completed_levels": []}


def save_game(data):
    try:
        with open(SAVE_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


# ── Particle System ────────────────────────────────────────────────────────────

class Particle:
    def __init__(self, x, y, color, dx=0, dy=0, life=30, size=3):
        self.x, self.y = x, y
        self.color = color
        self.dx, self.dy = dx, dy
        self.life = life
        self.max_life = life
        self.size = size

    def update(self):
        self.x += self.dx
        self.y += self.dy
        self.dy += 0.05
        self.life -= 1

    def draw(self, surf):
        alpha = max(0, int(255 * (self.life / self.max_life)))
        r, g, b = self.color
        s = max(1, int(self.size * (self.life / self.max_life)))
        pygame.draw.circle(surf, (min(255, r), min(255, g), min(255, b)), (int(self.x), int(self.y)), s)


# ── Game Objects ───────────────────────────────────────────────────────────────

class Player:
    def __init__(self):
        self.x, self.y = 120, SCREEN_H - 200
        self.w, self.h = 32, 48
        self.vy = 0
        self.on_ground = False
        self.hp = 100
        self.score = 0
        self.facing_right = True
        self.anim_frame = 0
        self.anim_timer = 0
        self.flash_timer = 0
        self.pickups_collected = 0
        self.pickups_needed = 0

    def update(self, platforms):
        self.vy += GRAVITY
        self.y += self.vy
        self.on_ground = False
        for px, py, pw, ph in platforms:
            if (self.x + self.w > px and self.x < px + pw and
                self.y + self.h > py and self.y < py + ph and self.vy >= 0):
                self.y = py - self.h
                self.vy = 0
                self.on_ground = True
        if self.y > SCREEN_H:
            self.hp -= 25
            self.y = SCREEN_H - 200
            self.vy = 0
        self.anim_timer += 1
        if self.anim_timer > 8:
            self.anim_frame = (self.anim_frame + 1) % 4
            self.anim_timer = 0
        if self.flash_timer > 0:
            self.flash_timer -= 1

    def draw(self, surf):
        if self.flash_timer > 0 and self.flash_timer % 4 < 2:
            return
        # Body
        body_color = ACCENT_GREEN
        pygame.draw.rect(surf, body_color, (self.x + 4, self.y + 12, 24, 28))
        # Head
        pygame.draw.rect(surf, WHITE, (self.x + 6, self.y, 20, 14))
        # Visor (antenna operator)
        pygame.draw.rect(surf, CYAN, (self.x + 8, self.y + 4, 16, 6))
        # Antenna on head
        ax = self.x + 16
        ay = self.y - 8
        pygame.draw.line(surf, ACCENT_GREEN, (ax, self.y), (ax, ay), 2)
        pygame.draw.circle(surf, ACCENT_GREEN, (int(ax), int(ay)), 3)
        # Legs (animated)
        leg_offset = [0, 3, 0, -3][self.anim_frame]
        pygame.draw.rect(surf, (40, 50, 70), (self.x + 6, self.y + 40, 8, 8 + leg_offset))
        pygame.draw.rect(surf, (40, 50, 70), (self.x + 18, self.y + 40, 8, 8 - leg_offset))

    def rect(self):
        return pygame.Rect(self.x, self.y, self.w, self.h)


class Pickup:
    def __init__(self, x, y, ptype, color):
        self.x, self.y = x, y
        self.ptype = ptype
        self.color = color
        self.collected = False
        self.bob_offset = random.uniform(0, math.pi * 2)
        self.size = 14

    def update(self, frame):
        self.bob_y = self.y + math.sin(frame * 0.05 + self.bob_offset) * 6

    def draw(self, surf, scroll_x):
        sx = self.x - scroll_x
        if sx < -40 or sx > SCREEN_W + 40:
            return
        sy = self.bob_y
        # Glow
        glow_surf = pygame.Surface((40, 40), pygame.SRCALPHA)
        pygame.draw.circle(glow_surf, (*self.color, 40), (20, 20), 20)
        surf.blit(glow_surf, (sx - 20 + self.size // 2, sy - 20 + self.size // 2))
        # Icon
        pygame.draw.polygon(surf, self.color, [
            (sx + self.size // 2, sy - 4),
            (sx + self.size + 4, sy + self.size // 2),
            (sx + self.size // 2, sy + self.size + 4),
            (sx - 4, sy + self.size // 2),
        ])
        pygame.draw.polygon(surf, WHITE, [
            (sx + self.size // 2, sy - 4),
            (sx + self.size + 4, sy + self.size // 2),
            (sx + self.size // 2, sy + self.size + 4),
            (sx - 4, sy + self.size // 2),
        ], 2)

    def rect(self, scroll_x):
        return pygame.Rect(self.x - scroll_x - 4, self.bob_y - 4,
                           self.size + 8, self.size + 8)


class Enemy:
    def __init__(self, x, y, etype, color):
        self.x, self.y = x, y
        self.etype = etype
        self.color = color
        self.alive = True
        self.w, self.h = 28, 28
        self.move_timer = 0
        self.base_y = y

    def update(self, frame):
        self.move_timer += 1
        if self.etype in ("deauth", "spoof", "jammer"):
            self.y = self.base_y + math.sin(self.move_timer * 0.04) * 30
        elif self.etype == "drone":
            self.y = self.base_y + math.sin(self.move_timer * 0.03) * 50
            self.x -= 1
        elif self.etype in ("interference", "multipath"):
            self.x += math.sin(self.move_timer * 0.05) * 2
        elif self.etype == "threat":
            self.y = self.base_y + math.sin(self.move_timer * 0.06) * 20
            self.x -= 0.5

    def draw(self, surf, scroll_x):
        sx = self.x - scroll_x
        if sx < -50 or sx > SCREEN_W + 50:
            return
        sy = self.y
        # Enemy body -- red-tinted hostile marker
        pygame.draw.rect(surf, self.color, (sx, sy, self.w, self.h))
        pygame.draw.rect(surf, RED, (sx, sy, self.w, self.h), 2)
        # X mark
        pygame.draw.line(surf, RED, (sx + 4, sy + 4), (sx + self.w - 4, sy + self.h - 4), 2)
        pygame.draw.line(surf, RED, (sx + self.w - 4, sy + 4), (sx + 4, sy + self.h - 4), 2)

    def rect(self, scroll_x):
        return pygame.Rect(self.x - scroll_x, self.y, self.w, self.h)


# ── Level Generator ────────────────────────────────────────────────────────────

def generate_level(level_def):
    platforms = []
    pickups = []
    enemies = []
    length = level_def["length"]

    # Ground
    platforms.append((0, SCREEN_H - 60, length + SCREEN_W, 80))

    # Generate platforms
    x = 300
    while x < length:
        gap = random.randint(180, 400)
        pw = random.randint(100, 250)
        py = SCREEN_H - random.randint(120, 350)
        platforms.append((x, py, pw, 16))

        # Pickup on platform
        if random.random() < 0.6:
            pickups.append(Pickup(
                x + pw // 2, py - 30,
                level_def["pickup_type"], level_def["color"]
            ))

        # Enemy near platform
        if random.random() < 0.4:
            ex = x + random.randint(-80, pw + 80)
            ey = py - random.randint(40, 100)
            enemies.append(Enemy(ex, ey, level_def["enemy_type"], level_def["color"]))

        x += gap + pw

    # Ground-level pickups
    for gx in range(400, length, random.randint(250, 500)):
        if random.random() < 0.5:
            pickups.append(Pickup(
                gx, SCREEN_H - 100,
                level_def["pickup_type"], level_def["color"]
            ))

    # Ground-level enemies
    for gx in range(600, length, random.randint(300, 600)):
        if random.random() < 0.5:
            enemies.append(Enemy(
                gx, SCREEN_H - 90,
                level_def["enemy_type"], level_def["color"]
            ))

    return platforms, pickups, enemies


# ── Background Renderers ───────────────────────────────────────────────────────

def draw_bg_waves(surf, scroll_x, frame, color):
    for i in range(3):
        pts = []
        for x in range(0, SCREEN_W + 20, 8):
            y = SCREEN_H - 200 + i * 60 + math.sin((x + scroll_x * (0.3 + i * 0.1) + frame * (1 + i)) * 0.02) * 25
            pts.append((x, y))
        pts.append((SCREEN_W, SCREEN_H))
        pts.append((0, SCREEN_H))
        alpha = 15 + i * 8
        c = (color[0] // 4, color[1] // 4, color[2] // 4)
        pygame.draw.polygon(surf, c, pts)


def draw_bg_grid(surf, scroll_x, frame):
    for x in range(0, SCREEN_W, 50):
        ox = (x - int(scroll_x * 0.2)) % SCREEN_W
        pygame.draw.line(surf, GRID_COLOR, (ox, 0), (ox, SCREEN_H))
    for y in range(0, SCREEN_H, 50):
        pygame.draw.line(surf, GRID_COLOR, (0, y), (SCREEN_W, y))


def draw_bg_radar(surf, scroll_x, frame):
    cx, cy = SCREEN_W // 2, SCREEN_H // 2 - 40
    for r in range(50, 350, 60):
        pygame.draw.circle(surf, (20, 30, 20), (cx, cy), r, 1)
    angle = (frame * 2) % 360
    ex = cx + int(300 * math.cos(math.radians(angle)))
    ey = cy + int(300 * math.sin(math.radians(angle)))
    pygame.draw.line(surf, (0, 80, 0), (cx, cy), (ex, ey), 2)


def draw_bg_waterfall(surf, scroll_x, frame):
    for y in range(0, SCREEN_H - 60, 4):
        for x in range(0, SCREEN_W, 4):
            noise = random.randint(0, 30)
            freq_peak = abs(math.sin((x + scroll_x * 0.1) * 0.01 + y * 0.005)) * 40
            v = min(255, int(noise + freq_peak))
            if v > 20:
                surf.set_at((x, y), (0, v // 4, v // 2))


def draw_bg_matrix(surf, scroll_x, frame):
    if frame % 3 == 0:
        for _ in range(15):
            x = random.randint(0, SCREEN_W)
            y = random.randint(0, SCREEN_H - 100)
            c = random.choice("0123456789ABCDEF")
            color = (0, random.randint(60, 180), 0)
            # We'll just draw small rects since font rendering per-char here is expensive
            pygame.draw.rect(surf, color, (x, y, 6, 8))


def draw_background(surf, bg_type, scroll_x, frame, color):
    surf.fill(DARK_BG)
    draw_bg_grid(surf, scroll_x, frame)
    if bg_type == "waves":
        draw_bg_waves(surf, scroll_x, frame, color)
    elif bg_type == "radar":
        draw_bg_radar(surf, scroll_x, frame)
    elif bg_type == "waterfall":
        draw_bg_waterfall(surf, scroll_x, frame)
    elif bg_type in ("matrix", "dots"):
        draw_bg_matrix(surf, scroll_x, frame)
    elif bg_type in ("compass", "df_sweep"):
        draw_bg_radar(surf, scroll_x, frame)
    elif bg_type == "sky":
        # Gradient sky
        for y in range(0, SCREEN_H - 60, 4):
            r = int(12 + y * 0.02)
            g = int(14 + y * 0.04)
            b = int(30 + y * 0.08)
            pygame.draw.line(surf, (r, g, b), (0, y), (SCREEN_W, y))


# ── HUD ───────────────────────────────────────────────────────────────────────

def draw_hud(surf, font, small_font, player, level_def, scroll_x, level_length):
    # HP bar
    bar_w = 200
    bar_h = 16
    bx, by = 20, 20
    pygame.draw.rect(surf, (40, 40, 50), (bx, by, bar_w, bar_h))
    hp_w = int(bar_w * max(0, player.hp) / 100)
    hp_color = GREEN if player.hp > 50 else YELLOW if player.hp > 25 else RED
    pygame.draw.rect(surf, hp_color, (bx, by, hp_w, bar_h))
    pygame.draw.rect(surf, WHITE, (bx, by, bar_w, bar_h), 1)
    hp_text = small_font.render(f"HP: {max(0, player.hp)}", True, WHITE)
    surf.blit(hp_text, (bx + bar_w + 10, by - 2))

    # Score
    score_text = font.render(f"SCORE: {player.score}", True, ACCENT_GREEN)
    surf.blit(score_text, (SCREEN_W - 250, 15))

    # Pickups
    pickup_text = small_font.render(
        f"INTEL: {player.pickups_collected}/{player.pickups_needed}", True, level_def["color"]
    )
    surf.blit(pickup_text, (SCREEN_W // 2 - 60, 15))

    # Progress bar
    prog = min(1.0, scroll_x / max(1, level_length - SCREEN_W))
    prog_w = 300
    prog_bx = SCREEN_W // 2 - prog_w // 2
    prog_by = 45
    pygame.draw.rect(surf, (40, 40, 50), (prog_bx, prog_by, prog_w, 8))
    pygame.draw.rect(surf, level_def["color"], (prog_bx, prog_by, int(prog_w * prog), 8))
    pygame.draw.rect(surf, WHITE, (prog_bx, prog_by, prog_w, 8), 1)

    # Level name
    name_text = small_font.render(level_def["name"], True, level_def["color"])
    surf.blit(name_text, (20, 45))


# ── Achievement Popup ──────────────────────────────────────────────────────────

class AchievementPopup:
    def __init__(self, ach_data):
        self.name = ach_data["name"]
        self.desc = ach_data["desc"]
        self.icon = ach_data["icon"]
        self.timer = 180  # 3 seconds at 60fps
        self.y = -80

    def update(self):
        self.timer -= 1
        target_y = 70 if self.timer > 30 else -80
        self.y += (target_y - self.y) * 0.12

    def draw(self, surf, font, small_font):
        w = 380
        h = 70
        x = SCREEN_W // 2 - w // 2
        y = int(self.y)
        # Panel
        pygame.draw.rect(surf, (30, 35, 50), (x, y, w, h), border_radius=8)
        pygame.draw.rect(surf, ACCENT_GREEN, (x, y, w, h), 2, border_radius=8)
        # Steam-style achievement banner
        steam_text = small_font.render("ACHIEVEMENT UNLOCKED", True, ACCENT_GREEN)
        surf.blit(steam_text, (x + 60, y + 8))
        name_text = font.render(self.name, True, WHITE)
        surf.blit(name_text, (x + 60, y + 28))
        desc_text = small_font.render(self.desc, True, (180, 180, 190))
        surf.blit(desc_text, (x + 60, y + 50))
        # Icon
        pygame.draw.rect(surf, ACCENT_GREEN, (x + 10, y + 12, 40, 40), border_radius=6)
        icon_text = font.render(self.icon, True, BLACK)
        surf.blit(icon_text, (x + 20, y + 18))

    def done(self):
        return self.timer <= 0


# ── Main Game Class ────────────────────────────────────────────────────────────

class Game:
    def __init__(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "x11")
        pygame.init()
        pygame.joystick.init()

        # Gamescope (Steam Game Mode) handles compositing -- use NOFRAME so
        # gamescope can scale/position the window itself.  Fall back through
        # progressively simpler modes if something goes wrong.
        self.screen = None
        for flags in (pygame.NOFRAME, pygame.FULLSCREEN, 0):
            try:
                self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), flags)
                break
            except Exception:
                continue
        if self.screen is None:
            print("FATAL: could not create display", file=sys.stderr)
            sys.exit(1)

        pygame.display.set_caption("SIGINT Training Ops")
        self.audio = AudioEngine()
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 28)
        self.big_font = pygame.font.Font(None, 48)
        self.title_font = pygame.font.Font(None, 72)
        self.small_font = pygame.font.Font(None, 20)

        self.joystick = None
        if pygame.joystick.get_count() > 0:
            self.joystick = pygame.joystick.Joystick(0)
            self.joystick.init()

        self.save_data = load_save()
        self.state = "menu"
        self.selected_level = 0
        self.frame = 0
        self.particles = []
        self.popups = []

        # Level state
        self.player = None
        self.platforms = []
        self.pickups = []
        self.enemies = []
        self.scroll_x = 0
        self.tutorial_page = 0
        self.tutorial_done = False
        self.level_complete = False
        self.level_failed = False

        # Menu animation
        self.menu_scroll = 0
        self.credits_scroll_y = float(SCREEN_H)
        self._credits_surface = pygame.Surface((SCREEN_W, SCREEN_H))
        self._credits_total_h = SCREEN_H

        # Boot chime
        self.audio.play("system_ready")

    def run(self):
        while True:
            self.frame += 1
            dt = self.clock.tick(FPS)

            events = pygame.event.get()
            for ev in events:
                if ev.type == pygame.QUIT:
                    self.quit()
                if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                    if self.state == "menu":
                        self.quit()
                    else:
                        self.state = "menu"

            if self.state == "menu":
                self.update_menu(events)
                self.draw_menu()
            elif self.state == "tutorial":
                self.update_tutorial(events)
                self.draw_tutorial()
            elif self.state == "playing":
                self.update_playing(events)
                self.draw_playing()
            elif self.state == "level_complete":
                self.update_level_complete(events)
                self.draw_level_complete()
            elif self.state == "achievements":
                self.update_achievements(events)
                self.draw_achievements()
            elif self.state == "credits":
                self.update_credits(events)
                self.draw_credits()

            # Music sequencer
            self.audio.tick_music(self.frame)

            # Popups
            for p in self.popups:
                p.update()
                p.draw(self.screen, self.font, self.small_font)
            self.popups = [p for p in self.popups if not p.done()]

            pygame.display.flip()

    def quit(self):
        save_game(self.save_data)
        pygame.quit()
        sys.exit()

    # ── Input helpers ──────────────────────────────────────────────────────

    def get_joy_axis(self, axis):
        if self.joystick:
            val = self.joystick.get_axis(axis)
            if abs(val) < 0.15:
                return 0
            return val
        return 0

    def joy_button(self, btn):
        if self.joystick and btn < self.joystick.get_numbuttons():
            return self.joystick.get_button(btn)
        return False

    def action_pressed(self, events):
        for ev in events:
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                return True
            if ev.type == pygame.JOYBUTTONDOWN and ev.button in (0, 7):  # A or Start
                return True
        return False

    def back_pressed(self, events):
        for ev in events:
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return True
            if ev.type == pygame.JOYBUTTONDOWN and ev.button in (1, 6):  # B or Back
                return True
        return False

    def up_pressed(self, events):
        for ev in events:
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_UP, pygame.K_w):
                return True
            if ev.type == pygame.JOYHATMOTION and ev.value[1] > 0:
                return True
        if self.get_joy_axis(1) < -0.5:
            return True
        return False

    def down_pressed(self, events):
        for ev in events:
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_DOWN, pygame.K_s):
                return True
            if ev.type == pygame.JOYHATMOTION and ev.value[1] < 0:
                return True
        if self.get_joy_axis(1) > 0.5:
            return True
        return False

    # ── Menu ───────────────────────────────────────────────────────────────

    def update_menu(self, events):
        self.menu_scroll += 0.5

        # levels + achievements + credits = len(LEVELS) + 2 items
        menu_count = len(LEVELS) + 2
        if self.up_pressed(events):
            self.selected_level = (self.selected_level - 1) % menu_count
            self.audio.play("menu_move")
        if self.down_pressed(events):
            self.selected_level = (self.selected_level + 1) % menu_count
            self.audio.play("menu_move")

        if self.action_pressed(events):
            self.audio.play("menu_confirm")
            if self.selected_level == len(LEVELS):
                self.state = "achievements"
            elif self.selected_level == len(LEVELS) + 1:
                self.credits_scroll_y = float(SCREEN_H)
                self._build_credits_surface()
                self.audio.start_music()
                self.state = "credits"
            else:
                self.start_level(self.selected_level)

    def draw_menu(self):
        self.screen.fill(DARK_BG)
        draw_bg_grid(self.screen, self.menu_scroll, self.frame)

        # Title
        title = self.title_font.render("SIGINT TRAINING OPS", True, ACCENT_GREEN)
        self.screen.blit(title, (SCREEN_W // 2 - title.get_width() // 2, 40))

        subtitle = self.small_font.render("Learn SIGINT-Deck / SIGINT-Pi through gameplay", True, (120, 130, 150))
        self.screen.blit(subtitle, (SCREEN_W // 2 - subtitle.get_width() // 2, 95))

        # Level list
        start_y = 140
        visible_start = max(0, self.selected_level - 5)

        for i, level in enumerate(LEVELS):
            if i < visible_start or i > visible_start + 10:
                continue
            y = start_y + (i - visible_start) * 55
            selected = i == self.selected_level
            completed = level["id"] in self.save_data.get("completed_levels", [])

            # Selection highlight
            if selected:
                pygame.draw.rect(self.screen, (30, 40, 55), (80, y - 4, SCREEN_W - 160, 48), border_radius=6)
                pygame.draw.rect(self.screen, level["color"], (80, y - 4, SCREEN_W - 160, 48), 2, border_radius=6)

            # Level number
            num_color = level["color"] if selected else (80, 90, 100)
            num = self.font.render(f"{i + 1:02d}", True, num_color)
            self.screen.blit(num, (100, y + 6))

            # Level name
            name_color = WHITE if selected else (140, 150, 160)
            name = self.font.render(level["name"], True, name_color)
            self.screen.blit(name, (150, y + 6))

            # Completion check
            if completed:
                check = self.font.render("[OK]", True, ACCENT_GREEN)
                self.screen.blit(check, (SCREEN_W - 180, y + 6))

            # High score
            hs = self.save_data.get("high_scores", {}).get(level["id"], 0)
            if hs > 0:
                hs_text = self.small_font.render(f"Best: {hs}", True, (100, 110, 120))
                self.screen.blit(hs_text, (SCREEN_W - 280, y + 10))

        # Achievements button
        ach_y = start_y + (min(len(LEVELS), 10)) * 55
        sel_ach = self.selected_level == len(LEVELS)
        if sel_ach:
            pygame.draw.rect(self.screen, (30, 40, 55), (80, ach_y - 4, SCREEN_W - 160, 48), border_radius=6)
            pygame.draw.rect(self.screen, YELLOW, (80, ach_y - 4, SCREEN_W - 160, 48), 2, border_radius=6)
        ach_text = self.font.render("VIEW ACHIEVEMENTS", True, YELLOW if sel_ach else (140, 140, 100))
        unlocked_count = len(self.save_data.get("unlocked", []))
        ach_count = self.small_font.render(f"{unlocked_count}/{len(ACHIEVEMENTS)}", True, (100, 110, 120))
        self.screen.blit(ach_text, (150, ach_y + 6))
        self.screen.blit(ach_count, (SCREEN_W - 180, ach_y + 10))

        # Credits button
        cred_y = ach_y + 55
        sel_cred = self.selected_level == len(LEVELS) + 1
        if sel_cred:
            pygame.draw.rect(self.screen, (30, 40, 55), (80, cred_y - 4, SCREEN_W - 160, 48), border_radius=6)
            pygame.draw.rect(self.screen, CYAN, (80, cred_y - 4, SCREEN_W - 160, 48), 2, border_radius=6)
        cred_text = self.font.render("CREDITS & SPECIAL THANKS", True, CYAN if sel_cred else (100, 140, 140))
        self.screen.blit(cred_text, (150, cred_y + 6))

        # Controls hint
        hint = self.small_font.render(
            "D-Pad/Arrow: Select  |  A/Enter: Start  |  B/Esc: Back", True, (80, 90, 110)
        )
        self.screen.blit(hint, (SCREEN_W // 2 - hint.get_width() // 2, SCREEN_H - 40))

    # ── Level Start ────────────────────────────────────────────────────────

    def start_level(self, idx):
        self.current_level = LEVELS[idx]
        self.player = Player()
        self.platforms, self.pickups, self.enemies = generate_level(self.current_level)
        self.player.pickups_needed = len(self.pickups)
        self.scroll_x = 0
        self.tutorial_page = 0
        self.tutorial_done = False
        self.level_complete = False
        self.level_failed = False
        self.particles = []
        self.state = "tutorial"

    # ── Tutorial ───────────────────────────────────────────────────────────

    def update_tutorial(self, events):
        if self.action_pressed(events):
            self.tutorial_page += 1
            self.audio.play("page")
            if self.tutorial_page >= len(self.current_level["tutorial"]):
                self.tutorial_done = True
                self.audio.play("geofence_enter")
                self.audio.start_music()
                self.state = "playing"

        if self.back_pressed(events):
            self.state = "menu"

    def draw_tutorial(self):
        self.screen.fill(DARK_BG)
        draw_bg_grid(self.screen, 0, self.frame)

        level = self.current_level

        # Title
        title = self.big_font.render(level["name"], True, level["color"])
        self.screen.blit(title, (SCREEN_W // 2 - title.get_width() // 2, 80))

        # Mission briefing panel
        panel_x, panel_y = 100, 160
        panel_w, panel_h = SCREEN_W - 200, 400
        pygame.draw.rect(self.screen, PANEL_BG, (panel_x, panel_y, panel_w, panel_h), border_radius=10)
        pygame.draw.rect(self.screen, level["color"], (panel_x, panel_y, panel_w, panel_h), 2, border_radius=10)

        header = self.font.render("MISSION BRIEFING", True, level["color"])
        self.screen.blit(header, (panel_x + 20, panel_y + 15))

        # Tutorial lines
        for i, line in enumerate(level["tutorial"]):
            alpha = 255 if i <= self.tutorial_page else 80
            c = WHITE if i <= self.tutorial_page else (60, 70, 80)
            marker = ">" if i == self.tutorial_page else " "
            text = self.font.render(f"  {marker} {line}", True, c)
            self.screen.blit(text, (panel_x + 20, panel_y + 60 + i * 40))

        # Page indicator
        page = self.small_font.render(
            f"[{self.tutorial_page + 1}/{len(level['tutorial'])}]  Press A/Enter to continue",
            True, (120, 130, 150)
        )
        self.screen.blit(page, (SCREEN_W // 2 - page.get_width() // 2, SCREEN_H - 80))

    # ── Playing ────────────────────────────────────────────────────────────

    def draw_playing(self):
        level = self.current_level
        draw_background(self.screen, level["bg_element"], self.scroll_x, self.frame, level["color"])

        # Platforms
        for px, py, pw, ph in self.platforms:
            sx = px - self.scroll_x
            if sx + pw < -10 or sx > SCREEN_W + 10:
                continue
            if ph > 20:
                # Ground
                pygame.draw.rect(self.screen, (30, 40, 50), (sx, py, pw, ph))
                pygame.draw.line(self.screen, level["color"], (sx, py), (sx + pw, py), 2)
            else:
                # Platform
                pygame.draw.rect(self.screen, (35, 45, 60), (sx, py, pw, ph))
                pygame.draw.rect(self.screen, level["color"], (sx, py, pw, ph), 1)

        # Pickups
        for p in self.pickups:
            if not p.collected:
                p.draw(self.screen, self.scroll_x)

        # Enemies
        for e in self.enemies:
            if e.alive:
                e.draw(self.screen, self.scroll_x)

        # Player (draw in screen coords)
        old_x = self.player.x
        self.player.x -= self.scroll_x
        self.player.draw(self.screen)
        self.player.x = old_x

        # Particles
        for p in self.particles:
            p.draw(self.screen)

        # HUD
        draw_hud(self.screen, self.font, self.small_font, self.player,
                 level, self.scroll_x, self.current_level["length"])

        # Level complete overlay
        if self.level_complete:
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 150))
            self.screen.blit(overlay, (0, 0))
            text = self.big_font.render("MISSION COMPLETE", True, ACCENT_GREEN)
            self.screen.blit(text, (SCREEN_W // 2 - text.get_width() // 2, SCREEN_H // 2 - 60))
            score = self.font.render(f"Score: {self.player.score}", True, WHITE)
            self.screen.blit(score, (SCREEN_W // 2 - score.get_width() // 2, SCREEN_H // 2))
            hint = self.small_font.render("Press A/Enter to continue", True, (150, 160, 170))
            self.screen.blit(hint, (SCREEN_W // 2 - hint.get_width() // 2, SCREEN_H // 2 + 50))

        if self.level_failed:
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 150))
            self.screen.blit(overlay, (0, 0))
            text = self.big_font.render("MISSION FAILED", True, RED)
            self.screen.blit(text, (SCREEN_W // 2 - text.get_width() // 2, SCREEN_H // 2 - 40))
            hint = self.small_font.render("Press A/Enter to retry  |  B/Esc to menu", True, (150, 160, 170))
            self.screen.blit(hint, (SCREEN_W // 2 - hint.get_width() // 2, SCREEN_H // 2 + 20))

    # ── Level Complete ─────────────────────────────────────────────────────

    def on_level_complete(self):
        level = self.current_level
        lid = level["id"]

        # Track completion
        completed = self.save_data.get("completed_levels", [])
        if lid not in completed:
            completed.append(lid)
            self.save_data["completed_levels"] = completed

        # High score
        hs = self.save_data.get("high_scores", {})
        old = hs.get(lid, 0)
        if self.player.score > old:
            hs[lid] = self.player.score
            self.save_data["high_scores"] = hs

        # Achievement
        ach_id = level["achievement"]
        unlocked = self.save_data.get("unlocked", [])
        if ach_id not in unlocked:
            unlocked.append(ach_id)
            self.save_data["unlocked"] = unlocked
            self.popups.append(AchievementPopup(ACHIEVEMENTS[ach_id]))
            self.audio.play("achievement")

        # Check full operator
        all_done = all(l["id"] in completed for l in LEVELS)
        if all_done and "full_operator" not in unlocked:
            unlocked.append("full_operator")
            self.save_data["unlocked"] = unlocked
            self.popups.append(AchievementPopup(ACHIEVEMENTS["full_operator"]))
            self.audio.play("achievement")

        save_game(self.save_data)

    def update_level_complete(self, events):
        if self.action_pressed(events):
            self.state = "menu"

    def draw_level_complete(self):
        self.draw_playing()

    def update_playing(self, events):
        if self.back_pressed(events):
            self.audio.stop_music()
            self.state = "menu"
            return

        if self.level_complete:
            if self.action_pressed(events):
                self.state = "menu"
            return

        if self.level_failed:
            if self.action_pressed(events):
                self.start_level(self.selected_level)
            if self.back_pressed(events):
                self.state = "menu"
            return

        keys = pygame.key.get_pressed()
        joy_x = self.get_joy_axis(0)

        dx = 0
        if keys[pygame.K_LEFT] or keys[pygame.K_a] or joy_x < -0.3:
            dx = -PLAYER_SPEED
            self.player.facing_right = False
        if keys[pygame.K_RIGHT] or keys[pygame.K_d] or joy_x > 0.3:
            dx = PLAYER_SPEED
            self.player.facing_right = True

        self.player.x += dx

        jump = False
        for ev in events:
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_SPACE, pygame.K_UP, pygame.K_w):
                jump = True
            if ev.type == pygame.JOYBUTTONDOWN and ev.button == 0:
                jump = True
        if jump and self.player.on_ground:
            self.player.vy = JUMP_FORCE
            self.audio.play("jump")

        self.player.update(self.platforms)

        target_scroll = self.player.x - SCREEN_W // 3
        self.scroll_x += (target_scroll - self.scroll_x) * 0.1
        self.scroll_x = max(0, min(self.scroll_x, self.current_level["length"] - SCREEN_W + 200))

        for p in self.pickups:
            if p.collected:
                continue
            p.update(self.frame)
            pr = p.rect(self.scroll_x)
            psr = pygame.Rect(
                self.player.x - self.scroll_x, self.player.y, self.player.w, self.player.h
            )
            if psr.colliderect(pr):
                p.collected = True
                self.player.score += 100
                self.player.pickups_collected += 1
                self.audio.play("pickup")
                for _ in range(12):
                    self.particles.append(Particle(
                        p.x - self.scroll_x, p.bob_y, self.current_level["color"],
                        random.uniform(-3, 3), random.uniform(-4, 1), 25, 4
                    ))

        for e in self.enemies:
            if not e.alive:
                continue
            e.update(self.frame)
            er = e.rect(self.scroll_x)
            psr = pygame.Rect(
                self.player.x - self.scroll_x, self.player.y, self.player.w, self.player.h
            )
            if psr.colliderect(er):
                if self.player.flash_timer == 0:
                    self.player.hp -= 15
                    self.player.flash_timer = 30
                    # Play the matching SIGINT alert for this enemy type
                    if e.etype == "drone":
                        self.audio.play("drone_alert")
                    elif e.etype in ("spoof", "threat"):
                        self.audio.play("tracker")
                    else:
                        self.audio.play("hit")
                    if self.player.hp <= 25 and self.player.hp > 0:
                        self.audio.play("high_alert")
                    for _ in range(8):
                        self.particles.append(Particle(
                            self.player.x - self.scroll_x + 16,
                            self.player.y + 24, RED,
                            random.uniform(-3, 3), random.uniform(-3, 1), 20, 3
                        ))

        for p in self.particles:
            p.update()
        self.particles = [p for p in self.particles if p.life > 0]

        if self.player.x > self.current_level["length"]:
            self.level_complete = True
            self.audio.stop_music()
            self.audio.play("level_complete")
            self.on_level_complete()

        if self.player.hp <= 0:
            self.level_failed = True
            self.audio.stop_music()
            self.audio.play("critical")

    # ── Achievements Screen ────────────────────────────────────────────────

    def update_achievements(self, events):
        if self.back_pressed(events) or self.action_pressed(events):
            self.state = "menu"

    def draw_achievements(self):
        self.screen.fill(DARK_BG)
        draw_bg_grid(self.screen, self.frame * 0.3, self.frame)

        title = self.big_font.render("ACHIEVEMENTS", True, YELLOW)
        self.screen.blit(title, (SCREEN_W // 2 - title.get_width() // 2, 30))

        unlocked = self.save_data.get("unlocked", [])
        count = self.small_font.render(f"{len(unlocked)}/{len(ACHIEVEMENTS)} Unlocked", True, (140, 150, 160))
        self.screen.blit(count, (SCREEN_W // 2 - count.get_width() // 2, 75))

        col = 0
        row = 0
        items_per_row = 2
        card_w = 540
        card_h = 60
        start_x = SCREEN_W // 2 - (items_per_row * card_w + 20) // 2
        start_y = 110

        for ach_id, ach in ACHIEVEMENTS.items():
            is_unlocked = ach_id in unlocked
            x = start_x + col * (card_w + 20)
            y = start_y + row * (card_h + 12)

            bg = (30, 40, 55) if is_unlocked else (18, 20, 28)
            border = ACCENT_GREEN if is_unlocked else (40, 45, 55)

            pygame.draw.rect(self.screen, bg, (x, y, card_w, card_h), border_radius=8)
            pygame.draw.rect(self.screen, border, (x, y, card_w, card_h), 2, border_radius=8)

            # Icon
            icon_bg = ACCENT_GREEN if is_unlocked else (40, 45, 55)
            pygame.draw.rect(self.screen, icon_bg, (x + 8, y + 10, 40, 40), border_radius=6)
            icon_color = BLACK if is_unlocked else (60, 65, 75)
            icon_text = self.font.render(ach["icon"], True, icon_color)
            self.screen.blit(icon_text, (x + 18, y + 16))

            # Text
            name_color = WHITE if is_unlocked else (70, 75, 85)
            name_text = self.font.render(ach["name"], True, name_color)
            self.screen.blit(name_text, (x + 58, y + 8))

            desc_color = (160, 170, 180) if is_unlocked else (50, 55, 65)
            desc_text = self.small_font.render(ach["desc"], True, desc_color)
            self.screen.blit(desc_text, (x + 58, y + 34))

            # Steam ID reference
            if is_unlocked:
                steam = self.small_font.render(f"Steam: {ach['steam_id']}", True, (80, 100, 80))
                self.screen.blit(steam, (x + card_w - 150, y + 36))

            col += 1
            if col >= items_per_row:
                col = 0
                row += 1

        hint = self.small_font.render("Press B/Esc to return", True, (80, 90, 110))
        self.screen.blit(hint, (SCREEN_W // 2 - hint.get_width() // 2, SCREEN_H - 40))

    # ── Credits Screen ─────────────────────────────────────────────────────

    CREDITS_DATA = [
        ("title", "SIGINT TRAINING OPS"),
        ("blank", ""),
        ("heading", "CREATED BY"),
        ("text", "naanprofit"),
        ("link", "github.com/naanprofit/sigint-pi"),
        ("link", "github.com/naanprofit/sigint-deck"),
        ("blank", ""),
        ("divider", ""),
        ("blank", ""),
        ("heading", "BUILT WITH"),
        ("blank", ""),
        ("subheading", "RTL-SDR Project"),
        ("text", "Antti Palosaari, Eric Fry, Osmocom team"),
        ("text", "The RTL2832U DVB-T dongle that started it all."),
        ("link", "osmocom.org/projects/rtl-sdr"),
        ("link", "rtl-sdr.com"),
        ("blank", ""),
        ("subheading", "HackRF / Great Scott Gadgets"),
        ("text", "Michael Ossmann"),
        ("text", "Open-source SDR platform. 1 MHz - 6 GHz."),
        ("link", "greatscottgadgets.com/hackrf"),
        ("link", "github.com/greatscottgadgets/hackrf"),
        ("blank", ""),
        ("subheading", "KrakenSDR"),
        ("text", "KrakenRF Inc."),
        ("text", "5-channel coherent RTL-SDR for direction finding."),
        ("link", "krakenrf.com"),
        ("link", "github.com/krakenrf/krakensdr_doa"),
        ("blank", ""),
        ("subheading", "Flipper Zero"),
        ("text", "Flipper Devices Inc."),
        ("text", "Multi-tool for pentesters and hardware hackers."),
        ("link", "flipperzero.one"),
        ("link", "github.com/flipperdevices"),
        ("blank", ""),
        ("subheading", "GNU Radio"),
        ("text", "The Free Software Foundation and contributors"),
        ("text", "Free and open-source signal processing toolkit."),
        ("link", "gnuradio.org"),
        ("link", "github.com/gnuradio/gnuradio"),
        ("blank", ""),
        ("subheading", "rtl_433"),
        ("text", "Benjamin Larsson and contributors"),
        ("text", "Generic data receiver for ISM band devices."),
        ("link", "github.com/merbanan/rtl_433"),
        ("blank", ""),
        ("subheading", "Gqrx SDR"),
        ("text", "Alexandru Csete (OZ9AEC)"),
        ("text", "Open-source SDR receiver powered by GNU Radio."),
        ("link", "gqrx.dk"),
        ("link", "github.com/gqrx-sdr/gqrx"),
        ("blank", ""),
        ("subheading", "SDR# (SDRSharp)"),
        ("text", "Youssef Touil / Airspy"),
        ("text", "Popular SDR receiver software for Windows."),
        ("link", "airspy.com/download"),
        ("blank", ""),
        ("subheading", "Airspy"),
        ("text", "Youssef Touil"),
        ("text", "High-performance SDR receivers."),
        ("link", "airspy.com"),
        ("link", "github.com/airspy"),
        ("blank", ""),
        ("subheading", "SoapySDR"),
        ("text", "Josh Blum (Pothosware)"),
        ("text", "Vendor-neutral SDR abstraction library."),
        ("link", "github.com/pothosware/SoapySDR"),
        ("blank", ""),
        ("subheading", "RayHunter"),
        ("text", "Electronic Frontier Foundation"),
        ("text", "IMSI catcher / cell-site simulator detector."),
        ("link", "github.com/EFF-Org/rayhunter"),
        ("blank", ""),
        ("subheading", "Wireshark"),
        ("text", "Gerald Combs and the Wireshark community"),
        ("text", "The world's foremost network protocol analyzer."),
        ("link", "wireshark.org"),
        ("link", "github.com/wireshark/wireshark"),
        ("blank", ""),
        ("subheading", "Kismet"),
        ("text", "Mike Kershaw (dragorn)"),
        ("text", "Wireless network and device detector/sniffer."),
        ("link", "kismetwireless.net"),
        ("link", "github.com/kismetwireless/kismet"),
        ("blank", ""),
        ("subheading", "Aircrack-ng"),
        ("text", "Thomas d'Otreppe (aircrack-ng team)"),
        ("text", "WiFi security auditing tools suite."),
        ("link", "aircrack-ng.org"),
        ("link", "github.com/aircrack-ng/aircrack-ng"),
        ("blank", ""),
        ("subheading", "Piper TTS"),
        ("text", "Michael Hansen (rhasspy)"),
        ("text", "Fast local neural text-to-speech engine."),
        ("link", "github.com/rhasspy/piper"),
        ("blank", ""),
        ("subheading", "Rust Language"),
        ("text", "The Rust Foundation and contributors"),
        ("text", "Memory-safe systems programming. No GC. No fear."),
        ("link", "rust-lang.org"),
        ("link", "github.com/rust-lang/rust"),
        ("blank", ""),
        ("subheading", "Actix Web"),
        ("text", "Nikolay Kim and contributors"),
        ("text", "Powerful Rust web framework for the backend."),
        ("link", "actix.rs"),
        ("link", "github.com/actix/actix-web"),
        ("blank", ""),
        ("subheading", "SQLite"),
        ("text", "D. Richard Hipp"),
        ("text", "The most deployed database engine in the world."),
        ("link", "sqlite.org"),
        ("blank", ""),
        ("subheading", "Pygame"),
        ("text", "Pete Shinners, Lenard Lindstrom, and community"),
        ("text", "Making this very game possible."),
        ("link", "pygame.org"),
        ("link", "github.com/pygame/pygame"),
        ("blank", ""),
        ("subheading", "Valve / Steam Deck"),
        ("text", "Valve Corporation"),
        ("text", "Handheld Linux gaming PC. Our field platform."),
        ("link", "store.steampowered.com/steamdeck"),
        ("blank", ""),
        ("subheading", "Raspberry Pi Foundation"),
        ("text", "Eben Upton and the RPi team"),
        ("text", "Affordable ARM SBCs powering our sensor nodes."),
        ("link", "raspberrypi.com"),
        ("blank", ""),
        ("subheading", "Factory AI"),
        ("text", "AI-powered software engineering platform."),
        ("text", "Droid built every line of this game."),
        ("link", "factory.ai"),
        ("link", "docs.factory.ai"),
        ("blank", ""),
        ("divider", ""),
        ("blank", ""),
        ("heading", "SPECIAL THANKS"),
        ("blank", ""),
        ("subheading", "Electronic Frontier Foundation (EFF)"),
        ("text", "Defending digital privacy, free speech,"),
        ("text", "and innovation since 1990."),
        ("text", "Their work on RayHunter, surveillance oversight,"),
        ("text", "and digital rights makes projects like this possible."),
        ("text", "If you believe in privacy, support them."),
        ("link", "eff.org"),
        ("link", "eff.org/donate"),
        ("blank", ""),
        ("subheading", "Anonymous"),
        ("text", "We are Anonymous. We are Legion."),
        ("text", "We do not forgive. We do not forget."),
        ("text", "Expect us."),
        ("text", ""),
        ("text", "For decades of holding power accountable,"),
        ("text", "exposing corruption, and defending the voiceless."),
        ("text", "The idea that information wants to be free"),
        ("text", "is woven into the DNA of this project."),
        ("blank", ""),
        ("subheading", "The Open-Source Community"),
        ("text", "Every contributor who writes code, files bugs,"),
        ("text", "reviews PRs, writes docs, or answers questions."),
        ("text", "None of this exists without you."),
        ("blank", ""),
        ("subheading", "The SDR Community"),
        ("text", "Ham radio operators, RF engineers, hobbyists,"),
        ("text", "researchers, and tinkerers worldwide who share"),
        ("text", "knowledge freely and keep the airwaves open."),
        ("blank", ""),
        ("subheading", "The Hacker Community"),
        ("text", "DEF CON, Chaos Computer Club, 2600,"),
        ("text", "Hack The Planet, and every local hackerspace."),
        ("text", "Curiosity is not a crime."),
        ("blank", ""),
        ("divider", ""),
        ("blank", ""),
        ("heading", "LEGAL"),
        ("text", "This software is receive-only / passive monitoring."),
        ("text", "Licensed under GPL-3.0."),
        ("text", "Transmitting without authorization is illegal."),
        ("text", "Know your local laws. Be responsible."),
        ("blank", ""),
        ("divider", ""),
        ("blank", ""),
        ("text", "\"Knowledge is free.\""),
        ("text", "\"Privacy is a right, not a privilege.\""),
        ("text", "\"The best way to predict the future is to build it.\""),
        ("blank", ""),
        ("blank", ""),
        ("heading", "THANK YOU FOR PLAYING"),
        ("blank", ""),
        ("blank", ""),
        ("blank", ""),
    ]

    def _build_credits_surface(self):
        """Pre-render entire credits to one surface for smooth scrolling."""
        cx = SCREEN_W // 2
        # First pass: measure total height
        y = 0
        for entry_type, _ in self.CREDITS_DATA:
            if entry_type == "title": y += 64
            elif entry_type == "heading": y += 48
            elif entry_type == "subheading": y += 30
            elif entry_type == "text": y += 26
            elif entry_type == "link": y += 22
            elif entry_type == "divider": y += 20
            elif entry_type == "blank": y += 18
        total_h = y + SCREEN_H  # extra padding so it scrolls fully off

        surf = pygame.Surface((SCREEN_W, total_h))
        surf.fill(DARK_BG)

        # Second pass: render
        y = 0
        for entry_type, text in self.CREDITS_DATA:
            if entry_type == "title":
                r = self.title_font.render(text, True, ACCENT_GREEN)
                surf.blit(r, (cx - r.get_width() // 2, y))
                y += 64
            elif entry_type == "heading":
                r = self.big_font.render(text, True, WHITE)
                surf.blit(r, (cx - r.get_width() // 2, y))
                y += 48
            elif entry_type == "subheading":
                r = self.font.render(text, True, ACCENT_BLUE)
                surf.blit(r, (cx - r.get_width() // 2, y))
                y += 30
            elif entry_type == "text":
                r = self.font.render(text, True, (190, 195, 210))
                surf.blit(r, (cx - r.get_width() // 2, y))
                y += 26
            elif entry_type == "link":
                r = self.small_font.render(text, True, (80, 160, 200))
                surf.blit(r, (cx - r.get_width() // 2, y))
                y += 22
            elif entry_type == "divider":
                pygame.draw.line(surf, (40, 50, 65),
                                 (cx - 200, y + 8), (cx + 200, y + 8), 1)
                y += 20
            elif entry_type == "blank":
                y += 18

        self._credits_surface = surf
        self._credits_total_h = total_h

    def update_credits(self, events):
        if self.back_pressed(events) or self.action_pressed(events):
            self.audio.stop_music()
            self.state = "menu"
            return

        # Smooth sub-pixel scrolling via float accumulator
        self.credits_scroll_y -= 0.8

        keys = pygame.key.get_pressed()
        joy_y = self.get_joy_axis(1)
        if keys[pygame.K_UP] or keys[pygame.K_w] or joy_y < -0.3:
            self.credits_scroll_y -= 3.0
        if keys[pygame.K_DOWN] or keys[pygame.K_s] or joy_y > 0.3:
            self.credits_scroll_y += 3.0

        # Wrap when scrolled past everything
        if self.credits_scroll_y < -self._credits_total_h:
            self.credits_scroll_y = float(SCREEN_H)

    def draw_credits(self):
        self.screen.fill(DARK_BG)

        # Subtle animated background grid (slow)
        draw_bg_grid(self.screen, self.frame * 0.15, self.frame)

        # Blit pre-rendered credits surface at integer offset for clean pixels
        iy = int(self.credits_scroll_y)
        self.screen.blit(self._credits_surface, (0, iy))

        # Top/bottom fade gradients for polish
        for i in range(60):
            alpha = 255 - int(255 * (i / 60))
            fade = pygame.Surface((SCREEN_W, 1), pygame.SRCALPHA)
            fade.fill((12, 14, 20, alpha))
            self.screen.blit(fade, (0, i))
            self.screen.blit(fade, (0, SCREEN_H - 41 - i))

        # Fixed hint bar at bottom
        hint_bg = pygame.Surface((SCREEN_W, 40), pygame.SRCALPHA)
        hint_bg.fill((12, 14, 20, 230))
        self.screen.blit(hint_bg, (0, SCREEN_H - 40))
        hint = self.small_font.render(
            "D-Pad/Arrows: Scroll  |  B/Esc/Enter: Back to Menu", True, (80, 90, 110)
        )
        self.screen.blit(hint, (SCREEN_W // 2 - hint.get_width() // 2, SCREEN_H - 30))


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    game = Game()
    game.run()
