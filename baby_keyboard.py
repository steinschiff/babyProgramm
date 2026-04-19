#!/usr/bin/env python3
"""
BabyKeyboard - Sicherer Spielmodus fuer Kleinkinder
Eltern-Toggle: Ctrl+Shift+Alt+B  |  Standard-Passwort: 1234
"""

import pygame
import sys
import math
import random
import hashlib
import json
from pathlib import Path

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

# ── Konstanten ────────────────────────────────────────────────────────────────

FPS            = 60
CONFIG_FILE    = Path.home() / ".babykeyboard.json"
DEFAULT_PASS   = "1234"
SHAPE_LIFETIME = 5.0     # Sekunden bis vollstaendig verschwunden
MAX_SHAPES     = 80
SAMPLE_RATE    = 44100

PALETTE = [
    (255,  80,  80),   # rot
    ( 80, 220,  80),   # gruen
    ( 80, 100, 255),   # blau
    (255, 210,  50),   # gelb
    (255, 100, 210),   # pink
    ( 60, 220, 220),   # cyan
    (200,  80, 255),   # lila
    (255, 150,  50),   # orange
    (150, 255,  80),   # hellgruen
    (255,  80, 150),   # magenta
]

# Chromatische Tonleiter - auf Tasten gemappt
_NOTES = [261.6, 293.7, 329.6, 349.2, 392.0, 440.0, 493.9,
          523.3, 587.3, 659.3, 698.5, 783.9, 880.0, 987.8]
_KEY_ORDER = "qwertyuiopasdfghjklzxcvbnm0123456789"
KEY_FREQ: dict[str, float] = {}
for _i, _k in enumerate(_KEY_ORDER):
    _oct  = _i // len(_NOTES)
    KEY_FREQ[_k] = _NOTES[_i % len(_NOTES)] * (1.5 ** _oct)


# ── Sound ─────────────────────────────────────────────────────────────────────

_sound_cache: dict[float, pygame.mixer.Sound] = {}


def make_sound(freq: float) -> "pygame.mixer.Sound | None":
    if not HAS_NUMPY:
        return None
    if freq in _sound_cache:
        return _sound_cache[freq]

    dur    = 0.45
    frames = int(dur * SAMPLE_RATE)
    t      = np.linspace(0, dur, frames, False)

    wave = (  np.sin(2 * np.pi * freq       * t) * 0.65
            + np.sin(4 * np.pi * freq       * t) * 0.20
            + np.sin(6 * np.pi * freq       * t) * 0.10
            + np.sin(2 * np.pi * freq * 1.5 * t) * 0.05)

    atk  = int(0.015 * frames)
    dec  = int(0.08  * frames)
    rel  = int(0.35  * frames)
    sus  = max(0, frames - atk - dec - rel)
    env  = np.concatenate([
        np.linspace(0, 1,    atk),
        np.linspace(1, 0.72, dec),
        np.full(sus,   0.72),
        np.linspace(0.72, 0, rel),
    ])[:frames]

    buf = (wave * env * 0.38 * 32767).astype(np.int16)
    snd = pygame.sndarray.make_sound(np.column_stack([buf, buf]))
    _sound_cache[freq] = snd
    return snd


# ── Form-Klasse ───────────────────────────────────────────────────────────────

class Shape:
    TYPES = ("circle", "rect", "triangle", "star", "diamond")

    def __init__(self, label: str, sw: int, sh: int):
        self.label      = label
        self.sw, self.sh = sw, sh
        self.kind       = random.choice(self.TYPES)
        self.color      = random.choice(PALETTE)
        self.radius     = random.randint(48, 115)

        m = self.radius + 20
        self.x  = float(random.randint(m, sw - m))
        self.y  = float(random.randint(m, sh - m))

        speed   = random.uniform(90, 220)
        angle   = random.uniform(0, 2 * math.pi)
        self.vx = speed * math.cos(angle)
        self.vy = speed * math.sin(angle)

        self.rot       = random.uniform(0, 360)
        self.rot_speed = random.uniform(-80, 80)
        self.age       = 0.0
        self.alive     = True

    @property
    def alpha(self) -> int:
        t = self.age / SHAPE_LIFETIME
        if t < 0.55:
            return 255
        return max(0, int(255 * (1.0 - (t - 0.55) / 0.45)))

    def update(self, dt: float):
        self.age += dt
        if self.age >= SHAPE_LIFETIME:
            self.alive = False
            return

        self.x   += self.vx * dt
        self.y   += self.vy * dt
        self.rot += self.rot_speed * dt

        r = self.radius
        if self.x - r < 0:
            self.x  = float(r);       self.vx =  abs(self.vx)
        elif self.x + r > self.sw:
            self.x  = float(self.sw - r); self.vx = -abs(self.vx)
        if self.y - r < 0:
            self.y  = float(r);       self.vy =  abs(self.vy)
        elif self.y + r > self.sh:
            self.y  = float(self.sh - r); self.vy = -abs(self.vy)

    def _poly_verts(self, cx, cy):
        r   = self.radius
        rot = self.rot

        if self.kind == "triangle":
            return [(cx + r * math.cos(math.radians(rot - 90 + i * 120)),
                     cy + r * math.sin(math.radians(rot - 90 + i * 120)))
                    for i in range(3)]

        if self.kind == "diamond":
            pts = [(0, -r), (r * 0.65, 0), (0, r), (-r * 0.65, 0)]
            cr, sr = math.cos(math.radians(rot)), math.sin(math.radians(rot))
            return [(cx + x * cr - y * sr, cy + x * sr + y * cr) for x, y in pts]

        if self.kind == "star":
            inner, verts = r * 0.42, []
            for i in range(10):
                rad = r if i % 2 == 0 else inner
                a   = math.radians(rot - 90 + i * 36)
                verts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
            return verts

        return []

    def draw(self, surface: pygame.Surface, fonts: dict):
        alpha = self.alpha
        if alpha <= 0:
            return

        cx, cy = int(self.x), int(self.y)
        r      = self.radius
        c      = (*self.color, alpha)
        pad    = r + 8
        tmp    = pygame.Surface((pad * 2, pad * 2), pygame.SRCALPHA)
        offset = pad

        if self.kind == "circle":
            pygame.draw.circle(tmp, c, (offset, offset), r)

        elif self.kind == "rect":
            rect_tmp = pygame.Surface((pad * 2, pad * 2), pygame.SRCALPHA)
            pygame.draw.rect(rect_tmp, c, (offset - r, offset - r, r * 2, r * 2))
            rotated  = pygame.transform.rotate(rect_tmp, self.rot)
            bx = (pad * 2 - rotated.get_width())  // 2
            by = (pad * 2 - rotated.get_height()) // 2
            tmp.blit(rotated, (bx, by))

        else:
            global_verts = self._poly_verts(cx, cy)
            local_verts  = [(vx - (cx - offset), vy - (cy - offset))
                            for vx, vy in global_verts]
            pygame.draw.polygon(tmp, c, local_verts)

        surface.blit(tmp, (cx - offset, cy - offset))

        # Buchstabe/Label zeichnen
        if self.label.strip():
            brightness  = 0.299 * self.color[0] + 0.587 * self.color[1] + 0.114 * self.color[2]
            text_color  = (25, 25, 25) if brightness > 145 else (255, 255, 255)
            font_key    = min(fonts.keys(), key=lambda k: abs(k - int(r * 0.8)))
            font        = fonts[font_key]
            txt         = font.render(self.label, True, text_color)
            txt.set_alpha(alpha)
            surface.blit(txt, txt.get_rect(center=(cx, cy)))


# ── Passwort-Dialog ───────────────────────────────────────────────────────────

def password_dialog(screen: pygame.Surface, clock: pygame.time.Clock,
                    pw_hash: str) -> bool:
    font_title = pygame.font.SysFont("DejaVuSans", 34, bold=True)
    font_hint  = pygame.font.SysFont("DejaVuSans", 22)
    font_input = pygame.font.SysFont("DejaVuSans", 32, bold=True)

    entered = ""
    error   = False
    sw, sh  = screen.get_size()
    bw, bh  = 500, 260
    bx      = (sw - bw) // 2
    by      = (sh - bh) // 2

    pygame.event.set_grab(False)   # temporaer freigeben fuer Dialog

    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_RETURN:
                    if hashlib.sha256(entered.encode()).hexdigest() == pw_hash:
                        return True
                    error, entered = True, ""
                elif ev.key == pygame.K_ESCAPE:
                    return False
                elif ev.key == pygame.K_BACKSPACE:
                    entered, error = entered[:-1], False
                elif ev.unicode and len(entered) < 64:
                    entered, error = entered + ev.unicode, False

        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 175))
        screen.blit(overlay, (0, 0))

        pygame.draw.rect(screen, (35, 35, 55),     (bx, by, bw, bh), border_radius=18)
        pygame.draw.rect(screen, (110, 110, 160),  (bx, by, bw, bh), 2, border_radius=18)

        t1 = font_title.render("Eltern-Passwort eingeben", True, (210, 210, 255))
        screen.blit(t1, t1.get_rect(center=(sw // 2, by + 45)))

        t2 = font_hint.render("ENTER = Bestaetigen   ESC = Abbrechen", True, (140, 140, 180))
        screen.blit(t2, t2.get_rect(center=(sw // 2, by + 85)))

        fr = pygame.Rect(bx + 40, by + 115, bw - 80, 52)
        fc = (150, 100, 100) if error else (100, 100, 150)
        pygame.draw.rect(screen, (50, 50, 75), fr, border_radius=8)
        pygame.draw.rect(screen, fc,           fr, 2, border_radius=8)

        dots = font_input.render("*" * len(entered) or " ", True, (200, 200, 255))
        screen.blit(dots, dots.get_rect(midleft=(fr.x + 14, fr.centery)))

        if error:
            em = font_hint.render("Falsches Passwort!", True, (255, 90, 90))
            screen.blit(em, em.get_rect(center=(sw // 2, by + 200)))

        pygame.display.flip()
        clock.tick(60)


# ── Konfiguration ─────────────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {"password_hash": hashlib.sha256(DEFAULT_PASS.encode()).hexdigest()}


def save_config(cfg: dict):
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    except Exception:
        pass


# ── Haupt-Applikation ─────────────────────────────────────────────────────────

SPECIAL_LABELS = {
    pygame.K_SPACE:  "SPC",
    pygame.K_RETURN: "OK",
    pygame.K_UP:     "^",
    pygame.K_DOWN:   "v",
    pygame.K_LEFT:   "<",
    pygame.K_RIGHT:  ">",
    pygame.K_TAB:    "TAB",
}


class BabyKeyboardApp:

    def __init__(self):
        pygame.init()
        pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=2, buffer=512)
        pygame.display.set_caption("BabyKeyboard")

        self.config    = load_config()
        self.clock     = pygame.time.Clock()
        self.shapes:   list[Shape] = []
        self.baby_mode = False
        self.held_keys: set[int]   = set()
        self.start_requested       = False  # ENTER/SPACE auf Startbildschirm

        info           = pygame.display.Info()
        self.full_w    = info.current_w
        self.full_h    = info.current_h

        self.screen    = pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
        self.fonts     = self._build_fonts()

        # Hintergrund-Sterne
        self.stars = [(random.randint(0, 1280), random.randint(0, 720),
                       random.uniform(0.5, 2.5)) for _ in range(120)]

    # ── Fonts ──────────────────────────────────────────────────────────────────

    def _build_fonts(self) -> dict[int, pygame.font.Font]:
        sizes = [28, 42, 58, 72, 90]
        return {s: pygame.font.SysFont("DejaVuSans", s, bold=True) for s in sizes}

    # ── Modi ───────────────────────────────────────────────────────────────────

    def enter_baby_mode(self):
        self.baby_mode = True
        self.screen    = pygame.display.set_mode(
            (self.full_w, self.full_h),
            pygame.FULLSCREEN | pygame.NOFRAME,
        )
        pygame.event.set_grab(True)
        self.shapes.clear()
        self.held_keys.clear()

    def exit_baby_mode(self):
        self.baby_mode = False
        pygame.event.set_grab(False)
        self.screen    = pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
        self.shapes.clear()
        self.held_keys.clear()

    # ── Hilfsfunktionen ────────────────────────────────────────────────────────

    def _exit_combo_active(self) -> bool:
        hk = self.held_keys
        ctrl  = pygame.K_LCTRL  in hk or pygame.K_RCTRL  in hk
        shift = pygame.K_LSHIFT in hk or pygame.K_RSHIFT in hk
        alt   = pygame.K_LALT   in hk or pygame.K_RALT   in hk
        return ctrl and shift and alt and pygame.K_b in hk

    def _spawn(self, label: str):
        if len(self.shapes) >= MAX_SHAPES:
            self.shapes.pop(0)
        sw, sh = self.screen.get_size()
        self.shapes.append(Shape(label, sw, sh))

    def _play(self, key_char: str):
        freq  = KEY_FREQ.get(key_char.lower(), 440.0)
        sound = make_sound(freq)
        if sound:
            sound.play()

    # ── Events ─────────────────────────────────────────────────────────────────

    def handle_events(self):
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                if not self.baby_mode:
                    self._quit()

            elif ev.type == pygame.VIDEORESIZE and not self.baby_mode:
                self.screen = pygame.display.set_mode(ev.size, pygame.RESIZABLE)

            elif ev.type == pygame.KEYDOWN:
                self.held_keys.add(ev.key)

                # Eltern-Kombi immer pruefen
                if self._exit_combo_active():
                    self.held_keys.clear()
                    if password_dialog(self.screen, self.clock,
                                       self.config["password_hash"]):
                        if self.baby_mode:
                            self.exit_baby_mode()
                        else:
                            self._quit()
                    else:
                        if self.baby_mode:
                            pygame.event.set_grab(True)
                    continue

                if self.baby_mode:
                    char = ev.unicode
                    if char and char.isprintable() and char.strip():
                        self._spawn(char.upper())
                        self._play(char)
                    elif ev.key in SPECIAL_LABELS:
                        label = SPECIAL_LABELS[ev.key]
                        self._spawn(label)
                        self._play(random.choice(list(KEY_FREQ.keys())))
                    # alle anderen Tasten (F-keys, Win, Alt usw.) werden ignoriert

                else:
                    if ev.key == pygame.K_ESCAPE:
                        self._quit()
                    elif ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                        self.start_requested = True

            elif ev.type == pygame.KEYUP:
                self.held_keys.discard(ev.key)

    # ── Update ─────────────────────────────────────────────────────────────────

    def update(self, dt: float):
        self.shapes = [s for s in self.shapes if s.alive]
        for s in self.shapes:
            s.update(dt)

    # ── Zeichnen ───────────────────────────────────────────────────────────────

    def draw_baby_mode(self):
        sw, sh = self.screen.get_size()
        self.screen.fill((10, 10, 25))

        # Sterne
        for sx, sy, sr in self.stars:
            pygame.draw.circle(self.screen, (60, 60, 90), (int(sx % sw), int(sy % sh)),
                                int(sr))

        for shape in self.shapes:
            shape.draw(self.screen, self.fonts)

        # Dezenter Hinweis
        hint = self.fonts[28].render("Ctrl+Shift+Alt+B  =  Eltern-Menue", True, (35, 35, 55))
        self.screen.blit(hint, (10, sh - hint.get_height() - 6))

    def draw_start_screen(self):
        sw, sh = self.screen.get_size()
        self.screen.fill((12, 12, 28))

        for sx, sy, sr in self.stars:
            pygame.draw.circle(self.screen, (55, 55, 85), (int(sx % sw), int(sy % sh)),
                                int(sr))

        title = self.fonts[72].render("BabyKeyboard", True, (160, 160, 255))
        self.screen.blit(title, title.get_rect(center=(sw // 2, sh // 2 - 90)))

        sub = self.fonts[42].render("Baby-Modus starten", True, (120, 220, 120))
        self.screen.blit(sub, sub.get_rect(center=(sw // 2, sh // 2)))

        lines = [
            "ENTER oder LEERTASTE = Baby-Modus starten",
            "Ctrl+Shift+Alt+B  =  Eltern-Menue (Passwort noetig)",
            f"Standard-Passwort: {DEFAULT_PASS}   (aenderbar in ~/.babykeyboard.json)",
            "ESC = Beenden",
        ]
        for i, line in enumerate(lines):
            surf = self.fonts[28].render(line, True, (110, 110, 160))
            self.screen.blit(surf, surf.get_rect(center=(sw // 2, sh // 2 + 75 + i * 36)))

    # ── Hauptschleife ──────────────────────────────────────────────────────────

    def run(self):
        while True:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.05)

            self.handle_events()

            if self.start_requested and not self.baby_mode:
                self.start_requested = False
                self.enter_baby_mode()

            self.update(dt)

            if self.baby_mode:
                self.draw_baby_mode()
            else:
                self.draw_start_screen()

            pygame.display.flip()

    def _quit(self):
        save_config(self.config)
        pygame.quit()
        sys.exit()


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not HAS_NUMPY:
        print("Hinweis: numpy nicht gefunden - keine Toene. "
              "Installiere mit:  pip install numpy")
    BabyKeyboardApp().run()
