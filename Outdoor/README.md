# 🛎️ Outdoor unit — build & flash guide

Firmware for the round-screen doorbell, built with the [TuyaOpen](https://github.com/tuya/TuyaOpen) SDK.

| | |
|---|---|
| **Device** | Tuya T5-E1, 1.75″ 466×466 AMOLED round touch display, QSPI, standard version |
| **SDK board definition** | `WAVESHARE_T5AI_TOUCH_AMOLED_1_75` (platform `T5AI`) |
| **Graphics** | LVGL 9.1, 16-bit colour, FreeRTOS integration, touch through LVGL |
| **Output** | `dist/Outdoor_1.0.1/Outdoor_QIO_1.0.1.bin` |
| **Tested with** | TuyaOpen checked out at commit `2ea79258`, built on Windows 11 |

> The SDK has no board entry named *T5-E1*. This firmware uses the Waveshare T5AI 1.75″ Touch AMOLED
> definition; display (466×466, QSPI), touch, Wi-Fi and storage all work with it on the T5-E1 board.

---

## 1 · Install the TuyaOpen SDK

```powershell
git clone https://github.com/tuya/TuyaOpen.git
cd TuyaOpen
git config core.longpaths true          # Windows: build paths get long
. .\export.ps1                          # Linux/macOS: . ./export.sh
tos.py check                            # verifies tools and submodules
```

`export.ps1` creates a Python environment and installs the SDK's tools; run it in **every new terminal**
before using `tos.py`. On Windows, run it from PowerShell.

## 2 · Put this project into the SDK

The firmware must sit **inside** the TuyaOpen tree. The tested location is
`TuyaOpen/examples/graphics/doorbell`:

```powershell
cd examples\graphics
git clone https://github.com/someshsaraf/smart-door-bell.git doorbell
cd doorbell\Outdoor
```

`Outdoor` is the TuyaOpen *project root* (it has `CMakeLists.txt` and `app_default.config`);
`tos.py` must always be run from there.

## 3 · Board configuration

Everything the device needs is already in [`app_default.config`](app_default.config), so a fresh
checkout builds without any menu work:

| Setting | Why |
|---|---|
| `CONFIG_BOARD_CHOICE_T5AI=y` | T5AI platform (Tuya T5 chip) |
| `CONFIG_BOARD_CHOICE_WAVESHARE_T5AI_TOUCH_AMOLED_1_75=y` | Display, QSPI wiring and touch controller of the 1.75″ round AMOLED |
| `CONFIG_ENABLE_LIBLVGL=y` | LVGL graphics library |
| `CONFIG_ENABLE_LVGL_TP=y` | Touch input through LVGL |
| `CONFIG_LV_FONT_MONTSERRAT_22=y`, `..._48=y` | Sizes used for the clock and icons (not on by default) |
| `CONFIG_DISPLAY_DEFAULT_BRIGHTNESS=80` | Start-up brightness |
| `CONFIG_ENABLE_BATTERY=y` | Board battery support |
| `CONFIG_PROJECT_VERSION="1.0.1"` | Ends up in the firmware file name |

These come from the SDK defaults for this board and must stay as they are:

| Generated value | Meaning |
|---|---|
| `CONFIG_LVGL_VERSION_9=y` (LVGL 8 off) | The code uses LVGL 9 APIs only |
| `CONFIG_ENABLE_LVGL_OS_FREERTOS=y` | LVGL runs on the board's FreeRTOS integration |
| `CONFIG_ENABLE_LVGL_DUAL_DISP_BUFF=y` | Two display buffers for smooth animation |
| `CONFIG_LVGL_COLOR_DEPTH=16` | RGB565 panel |
| `CONFIG_LV_FONT_MONTSERRAT_14/16/24=y` | Other font sizes used by the UI |
| `CONFIG_ENABLE_LVGL_DEMO` **not set** | The LVGL demo is not needed (the board's sample config turns it on) |

The project's [`CMakeLists.txt`](CMakeLists.txt) adds `-DLV_LVGL_H_INCLUDE_SIMPLE` so the sources can
`#include "lvgl.h"`.

**Check** the effective values (no editing needed):

```powershell
tos.py config get CONFIG_BOARD_CHOICE CONFIG_LVGL_VERSION_9 CONFIG_ENABLE_LVGL_TP CONFIG_LV_FONT_MONTSERRAT_48
tos.py config list -p LV_FONT_MONTSERRAT     # all font sizes
```

**Change** a setting with `config set` — it respects dependencies and regenerates everything:

```powershell
tos.py config set CONFIG_DISPLAY_DEFAULT_BRIGHTNESS=60
tos.py config set -u CONFIG_DISPLAY_DEFAULT_BRIGHTNESS     # back to the default
```

> Don't hand-edit `.build/cache/using.config` — it is generated output and is overwritten on the next build.
> `tos.py config menu` also works, but needs an interactive terminal.

## 4 · Build

```powershell
tos.py build
```

The first build downloads the T5AI platform SDK and toolchain (several hundred MB) and takes a while;
later builds only recompile what changed. A successful build ends with:

```text
====================[ BUILD SUCCESS ]===================
 Target    : Outdoor_QIO_1.0.1.bin
 Output    : ...\Outdoor\dist\Outdoor_1.0.1
 Board     : WAVESHARE_T5AI_TOUCH_AMOLED_1_75
```

To start from scratch: `tos.py clean`, then `tos.py build`.

## 5 · Flash and watch the log

Connect the board over USB and find its serial port (Device Manager → *Ports (COM & LPT)* on Windows,
`/dev/ttyACM0` or similar on Linux).

```powershell
tos.py flash -p COM6        # writes Outdoor_QIO_1.0.1.bin
tos.py monitor -p COM6      # device log; Ctrl+C to quit
```

Wi-Fi, broker address and settings live in the board's key–value storage. If the doorbell comes up
without them after flashing, set them again as in step 6. Useful log lines start with
`[NET]` (Wi-Fi, clock, MQTT) and `[DOORBELL]` (UI).

## 6 · First start on the device

1. The home screen shows the bell. **Hold the screen for 5 s** to open settings.
2. **Wi-Fi → Choose network**, pick your network, type the password.
3. **Indoor Unit → Set address**: the Raspberry Pi's IP address (`hostname -I` on the Pi).
   The status turns **Connected** within a few seconds.
4. Tap the bell — the indoor dashboard rings.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Not project root [...]` | Run `tos.py` from the `Outdoor` folder. |
| `can't open file '...\tos.py'` | Run `. .\export.ps1` in the TuyaOpen root first, then use plain `tos.py` — no `..\..\` paths to count. |
| Checkout or build fails with *Filename too long* (Windows) | `git config core.longpaths true` in both repositories. |
| Flash cannot open the port | Close any open serial monitor; check the COM number; try another USB cable (data, not charge-only). |
| Indoor Unit stays **Connecting… / Not reachable** | The Pi's firewall or Wi-Fi isolation blocks port 1883 — see the main [README](../README.md#-good-to-know). |
| Clock shows `--:--` | Waiting for network time; needs internet access. Time zone is IST (`DOORBELL_UTC_OFFSET_S` in `src/doorbell_net.h`). |

## Source overview

| File | Contents |
|---|---|
| [`src/doorbell_ui.c`](src/doorbell_ui.c) | LVGL screens, on-device bell rendering, ring animation, touch handling, settings pages, keyboard |
| [`src/doorbell_net.c`](src/doorbell_net.c) / [`.h`](src/doorbell_net.h) | Wi-Fi scan/connect/save, NTP clock, minimal MQTT client, ring delivery with ack and resend, remote settings |
| [`src/doorbell_sound.c`](src/doorbell_sound.c) / [`.h`](src/doorbell_sound.h) | Ding-dong chime on the board speaker (synthesised at start-up, played on its own thread) |
| [`app_default.config`](app_default.config) | Board and feature configuration |
| [`config/`](config) | TuyaOpen sample configs of other T5AI boards (not used by this build) |
