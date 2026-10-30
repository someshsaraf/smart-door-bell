"""Weather for the doorbell's visitors and the dashboard, from Open-Meteo
(free, no API key). Refreshed every 15 minutes; the place is set in
config.json:  "weather": {"place": "Bangalore", "lat": 12.97, "lon": 77.59}"""
import json, threading, time, urllib.request
from PySide6.QtCore import QObject, Signal

# WMO weather codes as Open-Meteo reports them
CODES = {0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Fog",
         51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
         61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
         71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow", 80: "Rain showers", 81: "Rain showers",
         82: "Heavy showers", 85: "Snow showers", 86: "Snow showers", 95: "Thunderstorm", 96: "Thunderstorm",
         99: "Thunderstorm"}
REFRESH_S = 15 * 60
VALID_S = 3 * 3600  # the doorbell stops showing a reading this old


def advice(code, temp, rain_soon):
    """A short line for the visitor (fits the round screen), or ""."""
    if code >= 95: return "Storm: please take shelter"
    if code in (51, 53, 55, 61, 63, 65, 80, 81, 82): return "Raining: please take shelter"
    if rain_soon >= 60: return "Rain expected soon"
    if temp >= 35: return "Hot day: please stay cool"
    return ""


class Weather(QObject):
    updated = Signal(dict)  # {"temp", "text", "note", "place", "until"}

    def __init__(self, cfg):
        super().__init__()
        self.place = cfg.get("place", "Bangalore"); self.lat = cfg.get("lat", 12.97); self.lon = cfg.get("lon", 77.59)
        self.last = None; self.stop_evt = threading.Event()

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.stop_evt.set()

    def _loop(self):
        while not self.stop_evt.is_set():
            wait = REFRESH_S
            try: self.last = self.fetch(); self.updated.emit(self.last)
            except Exception as e:
                print("Weather unavailable:", e, flush=True); wait = 120
            self.stop_evt.wait(wait)

    def fetch(self):
        url = (f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}"
               "&current=temperature_2m,weather_code&hourly=precipitation_probability&forecast_hours=3&timezone=auto")
        with urllib.request.urlopen(url, timeout=15) as r: data = json.load(r)
        cur = data["current"]; code = int(cur["weather_code"]); temp = float(cur["temperature_2m"])
        rain_soon = max(data.get("hourly", {}).get("precipitation_probability") or [0])
        return {"temp": round(temp), "text": CODES.get(code, "—"), "note": advice(code, temp, rain_soon),
                "place": self.place, "until": int(time.time()) + VALID_S}
