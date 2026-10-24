"""Generates the bell tones in assets/tones/ and their catalogue tones.json
(standard library only).

Three families, all original compositions synthesised here:
  chimes    struck-bell partials (tubular chime, church bell, marimba)
  bollywood Indian instruments in raga scales: shehnai, sitar, santoor,
            tabla, dhol, tumbi, tanpura drone
  funny     cartoon sounds: spring boing, slide whistle, rubber duck,
            kazoo, cuckoo clock

Every file ends with a short silence so that looping it for the whole ring
sounds natural. Deterministic: the same script always writes the same files.

    python3 tools/make_tones.py
"""
import array, json, math, random, wave
from pathlib import Path

RATE = 44100
OUT = Path(__file__).resolve().parent.parent / "assets" / "tones"
TAU = 2 * math.pi

# ---------- notes ----------

def note_freq(name):
    """'E5', 'F#4' -> Hz (A4 = 440)."""
    steps = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}
    semis = steps[name[0]] + (1 if "#" in name else 0) + 12 * (int(name[-1]) - 4)
    return 440.0 * 2 ** (semis / 12)

# ---------- struck bells (the original chimes; unchanged) ----------

# (ratio to fundamental, relative level, decay time constant in s)
CHIME = [(1.0, 1.0, 1.4), (2.76, 0.45, 0.7), (5.40, 0.22, 0.38), (8.93, 0.10, 0.2)]
CHURCH = [(0.5, 0.55, 2.6), (1.0, 1.0, 2.0), (1.19, 0.5, 1.6), (1.5, 0.35, 1.2), (2.0, 0.4, 1.0), (2.74, 0.2, 0.6)]
MARIMBA = [(1.0, 1.0, 0.45), (3.93, 0.35, 0.12), (9.2, 0.08, 0.05)]

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

# ---------- building blocks for the new tones ----------

class Track:
    """A mono buffer that instruments are mixed into."""
    def __init__(self, seconds):
        self.buf = [0.0] * int(RATE * seconds)
    def add(self, start, samples, level=1.0):
        s0 = int(start * RATE)
        for i, v in enumerate(samples[: max(0, len(self.buf) - s0)]):
            self.buf[s0 + i] += v * level

def env_adsr(n, attack, release, i):
    a, r = int(attack * RATE) or 1, int(release * RATE) or 1
    return min(1.0, i / a, (n - i) / r)

def wavetable(harmonics, size=2048):
    """One cycle from {harmonic number: amplitude}."""
    return [sum(a * math.sin(TAU * k * i / size) for k, a in harmonics.items()) for i in range(size)]

def oscillate(table, freq_at, seconds, amp_at):
    """Wavetable oscillator; freq_at/amp_at are functions of time t (s)."""
    n, size, phase, out = int(seconds * RATE), len(table), 0.0, []
    for i in range(n):
        t = i / RATE
        out.append(table[int(phase) % size] * amp_at(t, i, n))
        phase += freq_at(t) * size / RATE
    return out

def formant(harmonic_count, f0, peaks, width=350.0):
    """Sawtooth-like harmonics shaped by vocal-tract style resonances (nasal reeds, kazoo, duck)."""
    h = {}
    for k in range(1, harmonic_count + 1):
        boost = sum(g * math.exp(-((k * f0 - p) / width) ** 2) for p, g in peaks)
        h[k] = (1.0 / k) * (0.25 + boost)
    return h

def pluck(freq, seconds, bright=0.5, rng=None, jawari=0.0, decay=0.996):
    """Karplus-Strong plucked string; `jawari` adds the sitar's buzzing bridge."""
    rng = rng or random.Random(int(freq))
    period = max(2, int(RATE / freq))
    line = [rng.uniform(-1, 1) for _ in range(period)]
    for i in range(1, period):  # soften the excitation for darker strings
        line[i] = bright * line[i] + (1 - bright) * line[i - 1]
    out, idx = [], 0
    for _ in range(int(seconds * RATE)):
        a, b = line[idx], line[(idx + 1) % period]
        v = decay * 0.5 * (a + b)
        line[idx] = v; idx = (idx + 1) % period
        out.append(v + jawari * (abs(v) - 0.3 * v * v))
    return out

def drum(f_start, f_end, seconds, decay, partials=((1, 1.0),), noise=0.0, rng=None):
    """Membrane: pitch glides f_start -> f_end, plus an optional noise slap."""
    rng = rng or random.Random(int(f_start * 7))
    out, phase = [], [0.0] * len(partials)
    for i in range(int(seconds * RATE)):
        t = i / RATE
        f = f_end + (f_start - f_end) * math.exp(-t * 25)
        v = 0.0
        for j, (ratio, a) in enumerate(partials):
            phase[j] += TAU * f * ratio / RATE
            v += a * math.sin(phase[j])
        v += noise * rng.uniform(-1, 1) * math.exp(-t * 60)
        out.append(v * math.exp(-t / decay) * min(1.0, i / 40))
    return out

# instruments -------------------------------------------------------------

def shehnai(freq, seconds, glide_from=None):
    """Double-reed with nasal resonance, vibrato and an Indian meend (glide) into the note."""
    table = wavetable(formant(14, freq, [(1100, 1.4), (2600, 0.7)]))
    f0 = glide_from or freq
    def f_at(t):
        g = freq + (f0 - freq) * math.exp(-t * 9)
        return g * (1 + 0.012 * math.sin(TAU * 5.5 * t) * min(1, t * 3))
    return oscillate(table, f_at, seconds, lambda t, i, n: env_adsr(n, 0.05, 0.12, i) * 0.6)

def tanpura(freq, seconds):
    table = wavetable({1: 1, 2: 0.6, 3: 0.5, 4: 0.35, 5: 0.25, 6: 0.15})
    return oscillate(table, lambda t: freq, seconds, lambda t, i, n: env_adsr(n, 0.8, 0.8, i) * 0.12)

def sitar(freq, seconds=1.6):
    return pluck(freq, seconds, bright=0.9, jawari=0.35, decay=0.9975)

def santoor(freq, seconds=1.4):
    a = pluck(freq, seconds, bright=0.95, decay=0.9968, rng=random.Random(int(freq) + 1))
    b = pluck(freq * 1.004, seconds, bright=0.95, decay=0.9968, rng=random.Random(int(freq) + 2))  # paired strings
    return [x + y for x, y in zip(a, b)]

def tumbi(freq, seconds=0.5):
    return pluck(freq, seconds, bright=1.0, jawari=0.15, decay=0.993)

def tabla(stroke):
    if stroke == "na":   # ringing treble stroke
        return drum(780, 760, 0.6, 0.18, ((1, 1), (2, 0.5), (3, 0.3), (4.1, 0.2)), noise=0.3)
    if stroke == "tin":
        return drum(820, 800, 0.35, 0.09, ((1, 1), (2, 0.4), (3, 0.2)), noise=0.2)
    if stroke == "ge":   # bass stroke with the bayan's pitch bend
        return drum(160, 85, 0.7, 0.22, ((1, 1), (2, 0.25)), noise=0.05)
    if stroke == "dha":  # na + ge together
        return [a + b for a, b in zip(tabla("na"), tabla("ge") + [0.0] * RATE)]
    raise ValueError(stroke)

def dhol(side):
    if side == "dagga":  # deep bass side
        return drum(120, 55, 0.6, 0.2, ((1, 1), (1.5, 0.3)), noise=0.15)
    return drum(420, 400, 0.18, 0.05, ((1, 0.6), (2.3, 0.3)), noise=0.9)  # tilli: bright slap

def boing(freq, seconds=0.7):
    def f_at(t): return freq * (1 + 0.45 * math.sin(TAU * 11 * t) * math.exp(-4 * t)) * (1 - 0.25 * t)
    table = wavetable({1: 1, 2: 0.3, 3: 0.1})
    return oscillate(table, f_at, seconds, lambda t, i, n: math.exp(-3.5 * t) * min(1, i / 200) * 0.8)

def slide_whistle(f_from, f_to, seconds):
    rng = random.Random(7)
    table = wavetable({1: 1, 2: 0.08})
    def f_at(t):
        x = t / seconds; return f_from * (f_to / f_from) ** x * (1 + 0.01 * math.sin(TAU * 6 * t))
    tone = oscillate(table, f_at, seconds, lambda t, i, n: env_adsr(n, 0.03, 0.05, i) * 0.6)
    return [v + 0.03 * rng.uniform(-1, 1) for v in tone]  # a little breath

def pop():
    return drum(900, 300, 0.12, 0.03, ((1, 1),), noise=0.4)

def quack(freq=320, seconds=0.2):
    table = wavetable(formant(20, freq, [(1000, 2.0), (2400, 1.0)], width=300))
    return oscillate(table, lambda t: freq * (1 - 0.6 * t), seconds,
                     lambda t, i, n: env_adsr(n, 0.01, 0.06, i) * 0.7)

def kazoo(freq, seconds, glide_from=None):
    rng = random.Random(int(freq))
    table = wavetable(formant(24, freq, [(700, 1.2), (1800, 1.0), (3000, 0.5)]))
    f0 = glide_from or freq * 0.94  # kazoos scoop up into every note
    def f_at(t): return (freq + (f0 - freq) * math.exp(-t * 18)) * (1 + 0.02 * math.sin(TAU * 7 * t))
    tone = oscillate(table, f_at, seconds, lambda t, i, n: env_adsr(n, 0.02, 0.06, i) * 0.6)
    return [v * (1 + 0.25 * rng.uniform(-1, 1)) for v in tone]  # the buzz

def cuckoo(freq, seconds=0.32):
    table = wavetable({1: 1, 2: 0.12, 3: 0.05})
    return oscillate(table, lambda t: freq, seconds, lambda t, i, n: env_adsr(n, 0.02, 0.12, i) * 0.7)

# ---------- the tones ----------

def shehnai_swagat():
    """Welcome phrase in Raag Yaman over a tanpura drone, with meend glides."""
    t = Track(6.2)
    t.add(0, tanpura(note_freq("C3"), 5.6)); t.add(0, tanpura(note_freq("G3"), 5.6))
    phrase = [(0.0, "B4", 0.45, None), (0.45, "D5", 0.45, None), (0.9, "E5", 0.5, "D5"), (1.4, "F#5", 0.5, "E5"),
              (1.9, "G5", 1.0, "F#5"), (2.95, "E5", 0.45, "G5"), (3.4, "D5", 0.45, None), (3.85, "C5", 1.6, "D5")]
    for start, n, dur, src in phrase:
        t.add(start, shehnai(note_freq(n), dur + 0.08, note_freq(src) if src else None))
    for s, k in [(0, "dha"), (0.9, "na"), (1.9, "dha"), (2.95, "na"), (3.85, "dha")]:
        t.add(s, tabla(k), 0.35)
    return t.buf

def sitar_dhun():
    """Sitar phrase in Raag Bhairav with a tabla theka."""
    t = Track(5.0)
    beat = 0.25
    melody = ["C5", "B4", "G#4", "G4", "F4", "E4", "C#4", "C4", "G4", "G#4", "G4", "C5", "C5"]
    for i, n in enumerate(melody):
        t.add(i * beat if i < 12 else 12 * beat + 0.25, sitar(note_freq(n), 1.6 if i >= 11 else 0.9))
    theka = ["dha", "ge", "na", "tin", "dha", "ge", "na", "tin", "dha", "ge", "na", "dha"]
    for i, k in enumerate(theka):
        t.add(i * beat, tabla(k), 0.45)
    return t.buf

def dhol_dhamaka():
    """Bhangra chaal on dhol with a tumbi riff."""
    t = Track(4.6)
    beat = 60 / 140
    for bar in range(2):
        b0 = bar * 4 * beat
        for pos in (0, 1.5, 2, 3.5):
            t.add(b0 + pos * beat, dhol("dagga"))
        for pos in (0.5, 1, 2.5, 3, 3.25):
            t.add(b0 + pos * beat, dhol("tilli"), 0.6)
    riff = ["G5", "G5", "A#5", "G5", "F5", "G5", "D5", "G5"]
    for i, n in enumerate(riff):
        t.add(i * beat * 0.5 + 4 * beat, tumbi(note_freq(n)), 0.7)
    return t.buf

def santoor_subah():
    """Rippling santoor arpeggios in Raag Yaman ('morning')."""
    t = Track(4.6)
    notes = ["C5", "E5", "G5", "B5", "A5", "G5", "F#5", "E5", "D5", "F#5", "A5", "G5", "E5", "D5", "C5", "G4"]
    for i, n in enumerate(notes):
        t.add(i * 0.15, santoor(note_freq(n), 1.4 if i == len(notes) - 1 else 0.9))
        if i % 4 == 0:
            t.add(i * 0.15 + 0.075, santoor(note_freq(n), 0.5), 0.5)  # the quick double strike
    return t.buf

def boing_boing():
    t = Track(3.0)
    for i, f in enumerate((220, 180, 150)):
        t.add(i * 0.6, boing(f))
    t.add(2.0, pop(), 0.8)
    return t.buf

def slide_whistle_tone():
    t = Track(3.0)
    t.add(0.0, slide_whistle(500, 1800, 0.6))
    t.add(0.7, slide_whistle(1800, 700, 0.35))
    t.add(1.15, slide_whistle(700, 2200, 0.5))
    t.add(1.7, pop(), 0.9)
    return t.buf

def rubber_duck():
    t = Track(2.6)
    for s, f in ((0, 330), (0.32, 330), (0.8, 360), (0.98, 360), (1.16, 300)):
        t.add(s, quack(f))
    return t.buf

def kazoo_tada():
    """A silly original fanfare: ta-ta-ta TAAA, with a wobbly finish."""
    t = Track(3.2)
    for s, n, d in ((0, "G4", 0.18), (0.22, "G4", 0.18), (0.44, "G4", 0.18), (0.7, "C5", 0.9), (1.7, "E5", 0.2), (1.95, "C5", 0.6)):
        t.add(s, kazoo(note_freq(n), d))
    return t.buf

def cuckoo_clock():
    t = Track(3.2)
    for i in range(4):
        t.add(i * 0.6, cuckoo(note_freq("D6"))); t.add(i * 0.6 + 0.24, cuckoo(note_freq("A#5")))
    return t.buf

# file name: (display name, category, generator)
TONES = {
    "ding_dong.wav": ("Ding Dong", "Chimes", lambda: render([(0.0, "E5", 1.0), (0.55, "C5", 1.0)], CHIME, 2.6)),
    # two phrases of the Westminster quarters, with a pause between them
    "westminster.wav": ("Westminster", "Chimes", lambda: render(
        [(i * 0.5, n, 1.0) for i, n in enumerate(["E5", "C5", "D5", "G4"])] +
        [(2.3 + i * 0.5, n, 1.0) for i, n in enumerate(["G4", "D5", "E5", "C5"])], CHIME, 5.6)),
    "triple_chime.wav": ("Triple Chime", "Chimes", lambda: render([(0.0, "C6", 0.9), (0.22, "E6", 0.9), (0.44, "G6", 1.0)], CHIME, 2.4)),
    "soft_marimba.wav": ("Soft Marimba", "Chimes", lambda: render(
        [(0.0, "G5", 1.0), (0.18, "E5", 0.9), (0.36, "C5", 0.9), (0.72, "G5", 0.7)], MARIMBA, 2.0)),
    "church_bell.wav": ("Church Bell", "Chimes", lambda: render([(0.0, "C4", 1.0), (1.6, "C4", 0.9)], CHURCH, 4.4)),
    "shehnai_swagat.wav": ("Shehnai Swagat", "Bollywood style", shehnai_swagat),
    "sitar_dhun.wav": ("Sitar Dhun", "Bollywood style", sitar_dhun),
    "dhol_dhamaka.wav": ("Dhol Dhamaka", "Bollywood style", dhol_dhamaka),
    "santoor_subah.wav": ("Santoor Subah", "Bollywood style", santoor_subah),
    "boing_boing.wav": ("Boing Boing", "Funny", boing_boing),
    "slide_whistle.wav": ("Slide Whistle", "Funny", slide_whistle_tone),
    "rubber_duck.wav": ("Rubber Duck", "Funny", rubber_duck),
    "kazoo_tada.wav": ("Kazoo Ta-Da", "Funny", kazoo_tada),
    "cuckoo_clock.wav": ("Cuckoo Clock", "Funny", cuckoo_clock),
}

def save(name, samples):
    peak = max(abs(s) for s in samples) or 1.0
    fade = int(0.02 * RATE)  # no click at the loop point
    pcm = array.array("h", (int(s / peak * 0.85 * 32767 * min(1.0, (len(samples) - i) / fade)) for i, s in enumerate(samples)))
    OUT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT / name), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm.tobytes())
    print(f"{name}: {len(samples) / RATE:.1f} s")

if __name__ == "__main__":
    only = set(__import__("sys").argv[1:])  # optional: names to regenerate
    for name, (label, category, make) in TONES.items():
        if not only or name in only:
            save(name, make())
    catalogue = {name: {"name": label, "category": category} for name, (label, category, _) in TONES.items()}
    (OUT / "tones.json").write_text(json.dumps(catalogue, indent=2) + "\n", encoding="utf-8")
    print("tones.json:", len(catalogue), "tones")
