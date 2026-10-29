# 🎬 Recordings & detection

[← Back to the README](../README.md)

The Pi records the door camera onto its SD card in two cases — when the bell rings, and when a person, animal or
vehicle moves in view — and lists every recording under **Events**.

| | 🔔 Bell pressed | 🚶 Motion |
|---|---|---|
| **Starts when** | Someone presses the bell | A person, animal or vehicle **moves** in view |
| **Length** | 3 s before the press, then 1 s up to the ring's length after it (5 s by default) | 5 s before the movement, 55 s after it |
| **Sound** | The doorbell's own microphone, in sync with the picture | The camera's sound |
| **Shown as** | *Bell pressed* (orange) | *Motion · Person, Car* (blue) |
| **Settings** | **Settings → Camera**: recording length, sound on or off | **Settings → Camera**: motion recording on or off |

---

## 🧠 Seeing people, animals and vehicles

The Pi carries a **Hailo-8L** AI accelerator (Raspberry Pi AI Kit). It runs **YOLOv8s** on the camera's picture in
about 33 ms a frame, with almost no load on the Pi's CPU, so the door can be watched all the time.

- **What counts:** people; animals (dog, cat, cow, horse, bird and others); vehicles (car, motorbike, bicycle, bus,
  truck). Everything else the model knows — plants, furniture, parcels — is ignored
- **How sure:** people and vehicles need 50 % confidence, animals 55 %. Swaying leaves and shadows score far lower
  and never count
- **In the Front door view:** a red box with a label (*Person 92 %*) around each one, updated ten times a second

### Movement, not just presence

Each detection is followed from frame to frame. Only something that **travels** — its centre moves by about 5 % of
the picture, or more for big close objects — over at least three frames triggers a recording. So:

| Seen | Recorded? |
|---|---|
| A person walking up the path | ✅ yes |
| A dog crossing the drive | ✅ yes |
| A car driving in | ✅ yes |
| A car or scooter parked in view | ❌ no — present, but not moving |
| Someone standing still at the door (already recorded as they walked in) | ❌ no |
| Leaves, shadows, rain, insects | ❌ no — not recognised as any of the kinds |

While a motion clip records, anything else that moves is added to its list (*Person, Dog*) instead of starting a
new clip; and while the bell rings, the ring's own recording covers it. Each motion clip also appears in the
dashboard's recent events (*Motion: Person*).

When the Front door view is open its camera frames go to the detector; otherwise the camera's small stream is
decoded five frames a second for it.

---

## 🎞️ How clips are made

The camera's own H.264 stream is copied — never re-encoded, so full quality at about 1 % CPU — into short segments
**in RAM** (`/dev/shm`): the last 90 seconds are always there, and the SD card is not worn by constant writing. A
clip is cut from those segments, which is how it can start *before* the press or the movement. Each clip gets a
thumbnail of the moment it was triggered.

### The doorbell's sound, in sync

The doorbell's microphone always keeps its last 8 s of sound. On a press it streams it to the Pi from 3 s before
the press, so the sound starts as early as the picture.

- **In step:** every 20 ms packet carries its sample number, and the Pi places it on its own clock. It then matches
  that sound against the camera's microphone, which is in step with the picture, to remove the camera's delay
- **Fallback:** the camera's sound is kept when no doorbell sound arrives
- **Live:** the Front door view plays the same sound live, delayed to match the picture

---

## 📋 Events

The **Events** tile lists every recording, newest first, with its thumbnail:

- **All / Bell / Motion** shows one kind only; voice commands pick days (*"Show events from yesterday"*)
- Tap one to play it full screen, with its sound on the speaker
- Delete one, several (**Select**) or all, each confirmed by a second tap

The same list is in the web app, with the same filters.

## 💾 Storage

- Recordings are kept for **30 days**
- When the SD card runs short of space (under 2 GB free), the **oldest motion clips are deleted first**; ring
  recordings go only when no motion clips are left
- A one-minute motion clip from a 1080p camera is a few megabytes
