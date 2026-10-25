"""Creates the doorbell <-> broker TLS pre-shared key (both files are git-ignored):

  Outdoor/src/doorbell_secret.h   built into the doorbell firmware
  Indoor/mqtt_psk.txt             copy to ~/Indoor/ on the Pi, then run
                                  sudo bash ~/Indoor/tools/setup_mqtt_tls.sh

    python Outdoor/tools/make_psk.py          # keeps an existing key
    python Outdoor/tools/make_psk.py --new    # replaces it (flash the doorbell and rerun the Pi script)
"""
import re, secrets, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEADER = ROOT / "Outdoor" / "src" / "doorbell_secret.h"
PI_FILE = ROOT / "Indoor" / "mqtt_psk.txt"
IDENTITY = "doorbell"

key = None
if HEADER.exists() and "--new" not in sys.argv:
    m = re.search(r'DOORBELL_PSK_HEX\s+"([0-9a-f]+)"', HEADER.read_text(encoding="utf-8"))
    key = m.group(1) if m else None
if key:
    print(f"Keeping the key in {HEADER.relative_to(ROOT)}")
else:
    key = secrets.token_hex(32)  # 256 bits
    HEADER.write_text(f'''/*
 * Doorbell <-> indoor broker TLS pre-shared key. NOT in git (see .gitignore).
 * Made by Outdoor/tools/make_psk.py together with Indoor/mqtt_psk.txt, which
 * Indoor/tools/setup_mqtt_tls.sh installs on the Pi's broker. A new key needs
 * both: rebuild and flash the doorbell, and run the script again.
 */
#pragma once
#define DOORBELL_PSK_IDENTITY "{IDENTITY}"
#define DOORBELL_PSK_HEX      "{key}"
''', encoding="utf-8")
    print(f"New key written to {HEADER.relative_to(ROOT)}")
PI_FILE.write_text(f"{IDENTITY}:{key}\n", encoding="utf-8")
print(f"Pi copy: {PI_FILE.relative_to(ROOT)}  ->  scp it to ~/Indoor/ on the Pi (then chmod 600)")
