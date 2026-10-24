"""Generates the bell tones in assets/tones/ (standard library only).

Each note is a struck-bell sound: a few partials with the ratios of a tubular
chime, each decaying on its own, after a 4 ms attack. Every file ends with a
short silence so that looping it while the doorbell rings sounds natural.

    python3 tools/make_tones.py
"""
import array, math, wave
from pathlib import Path

RATE = 44100
OUT = Path(__file__).resolve().parent.parent / "assets" / "tones"

# (ratio to fundamental, relative level, decay time constant in s)
CHIME = [(1.0, 1.0, 1.4), (2.76, 0.45, 0.7), (5.40, 0.22, 0.38), (8.93, 0.10, 0.2)]
CHURCH = [(0.5, 0.55, 2.6), (1.0, 1.0, 2.0), (1.19, 0.5, 1.6), (1.5, 0.35, 1.2), (2.0, 0.4, 1.0), (2.74, 0.2, 0.6)]
MARIMBA = [(1.0, 1.0, 0.45), (3.93, 0.35, 0.12), (9.2, 0.08, 0.05)]

def note_freq(name):
    """'E5' -> Hz (A4 = 440)."""
    steps = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}
    semis = steps[name[0]] + (1 if "#" in name else 0) + 12 * (int(name[-1]) - 4)
    return 440.0 * 2 ** (semis / 12)

def render(notes, timbre, length):
    """notes: [(start s, note name, level)] -> float samples of `length` s."""
    buf = [0.0] * int(RATE * length)
    for start, name, level in notes:
        f0, s0 = note_freq(name), int(start * RATE)
        for ratio, amp, decay in timbre:
            w, n = 2 * math.pi * f0 * ratio / RATE, min(len(buf) - s0, int(decay * 7 * RATE))
            for i in range(n):
                env = math.exp(-i / (decay * RATE)) * min(1.0, i / (0.004 * RATE))
                buf[s0 + i] += level * amp * env * math.sin(w * i)
    return buf

def save(name, samples):
    peak = max(abs(s) for s in samples) or 1.0
    pcm = array.array("h", (int(s / peak * 0.85 * 32767) for s in samples))
    OUT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT / name), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm.tobytes())
    print(f"{name}: {len(samples) / RATE:.1f} s")

TONES = {
    "ding_dong.wav": (render([(0.0, "E5", 1.0), (0.55, "C5", 1.0)], CHIME, 2.6)),
    # two phrases of the Westminster quarters, with a pause between them
    "westminster.wav": (render([(i * 0.5, n, 1.0) for i, n in enumerate(["E5", "C5", "D5", "G4"])] +
                               [(2.3 + i * 0.5, n, 1.0) for i, n in enumerate(["G4", "D5", "E5", "C5"])], CHIME, 5.6)),
    "triple_chime.wav": (render([(0.0, "C6", 0.9), (0.22, "E6", 0.9), (0.44, "G6", 1.0)], CHIME, 2.4)),
    "soft_marimba.wav": (render([(0.0, "G5", 1.0), (0.18, "E5", 0.9), (0.36, "C5", 0.9), (0.72, "G5", 0.7)], MARIMBA, 2.0)),
    "church_bell.wav": (render([(0.0, "C4", 1.0), (1.6, "C4", 0.9)], CHURCH, 4.4)),
}

if __name__ == "__main__":
    for name, samples in TONES.items():
        save(name, samples)
