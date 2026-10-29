import json, os, signal, sys, threading, time
from pathlib import Path
# RTSP over TCP is far more reliable than UDP on Wi-Fi; the 5 s timeout keeps a
# dead camera from blocking the capture thread. Must be set before cv2 loads.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|timeout;5000000")
# SDL (pygame) otherwise swallows SIGTERM, so `kill` / systemd could not stop the app.
os.environ.setdefault("SDL_NO_SIGNAL_HANDLERS", "1")
# Bell audio in ~40 ms chunks: SDL otherwise asks PipeWire for ~3 ms ones, which drives the whole
# chain (Bluetooth speaker included) at that pace and drops out audibly under any load.
os.environ.setdefault("PIPEWIRE_LATENCY", "2048/48000")
os.environ.setdefault("PULSE_LATENCY_MSEC", "60")
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QThread
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QFrame, QStackedWidget,
                               QSizePolicy)
try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None
try:
    import pygame
except ImportError:
    pygame = None
try:
    import cv2
except ImportError:
    cv2 = None

import datetime as dt
import looks
from string import Template
from bluetooth import Bluetooth
from festivals import current as current_festival, greeting as festival_greeting
from news import News, ago
from home_qml import QuickHome
from ring_ui import RingPage
from web import Web
from webapp import WebApp
import recorder as recorder_mod
from markets import Markets
from settings_ui import SettingsPage, this_ip
from intercom import Intercom, PORT as TALK_PORT
from notify import Notifier
import camera_cfg
from recorder import Recorder, CLIP_S, PRE_S
from door_audio import DoorAudio, LivePlayer, PORT as LISTEN_PORT
from detect import Detector
from watch import Watcher
from events_ui import EventsPage
from assistant import Assistant

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "config.json").read_text())
TONES = ROOT / "assets" / "tones"
# Choices made on the settings screen (tone, speaker). config.json stays hand-edited setup.
SETTINGS_FILE = ROOT / "settings.json"
try: SETTINGS = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
except (OSError, ValueError): SETTINGS = {}
def save_settings():
    tmp = SETTINGS_FILE.with_suffix(".tmp"); tmp.write_text(json.dumps(SETTINGS, indent=2), encoding="utf-8"); tmp.replace(SETTINGS_FILE)
def topic(key, default): return CFG["mqtt"].get(key, default)
T_OUT_STATE = topic("topic_outdoor_state", "home/doorbell/outdoor/state")
T_OUT_ONLINE = topic("topic_outdoor_online", "home/doorbell/outdoor/online")
T_OUT_CONFIG = topic("topic_outdoor_config", "home/doorbell/outdoor/config")
T_OUT_SCAN = topic("topic_outdoor_scan", "home/doorbell/outdoor/wifi_scan")
T_FESTIVAL = topic("topic_festival", "home/doorbell/festival")  # retained, read by the doorbell
T_TALK = topic("topic_talk", "home/doorbell/talk")  # intercom call start / end, to the doorbell
# Festival running now with festival tones on (key, e.g. "diwali"), else None; set by Window.check_festival.
FESTIVAL = {"key": None}
BOTTOM_H = 120  # the voice button and its bubble stay above the foot of the pages (market band, ticker)
FESTIVAL_TONES = {"diwali": "shehnai_swagat.wav", "christmas": "jingle_bells.wav", "new_year": "auld_lang_syne.wav"}
class Signals(QObject):
    message = Signal(str, str)
    status = Signal(bool, str)

class MQTT:
    def __init__(self, signals):
        self.s = signals; self.client = None; self.connected = False
    def start(self):
        if mqtt is None:
            self.s.status.emit(False, "paho-mqtt missing"); return
        c = CFG["mqtt"]
        try:
            try: self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=c["client_id"])
            except (AttributeError, TypeError): self.client = mqtt.Client(client_id=c["client_id"])
            if c.get("username"): self.client.username_pw_set(c["username"], c.get("password", ""))
            self.client.on_connect = self.on_connect; self.client.on_disconnect = self.on_disconnect; self.client.on_message = self.on_message
            self.client.connect_async(c["host"], int(c["port"]), 30); self.client.loop_start()
        except Exception as e: self.s.status.emit(False, str(e))
    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        try: ok = int(reason_code) == 0
        except Exception: ok = str(reason_code).lower() in ("success", "0")
        self.connected = ok
        if ok:
            for t in (CFG["mqtt"]["topic_start"], CFG["mqtt"]["topic_stop"], T_OUT_STATE, T_OUT_ONLINE, T_OUT_SCAN):
                client.subscribe(t, qos=1)
            self.s.status.emit(True, "MQTT connected")
        else: self.s.status.emit(False, f"MQTT connection failed: {reason_code}")
    def on_disconnect(self, *args): self.connected = False; self.s.status.emit(False, "MQTT disconnected")
    def on_message(self, client, userdata, msg): self.s.message.emit(msg.topic, msg.payload.decode("utf-8", "replace"))
    def publish(self, topic, payload, retain=False):
        if not (self.client and self.connected): return False
        self.client.publish(topic, json.dumps(payload), qos=1, retain=retain); return True
    def close(self):
        if self.client:
            self.client.loop_stop(); self.client.disconnect()

class Audio:
    """Plays the chosen bell tone. The mixer is reopened for every sound so it
    always uses the current output, e.g. a speaker connected after start-up."""
    def tone(self):
        name = FESTIVAL_TONES.get(FESTIVAL["key"]) or SETTINGS.get("tone", "ding_dong.wav")  # festival tone wins
        path = TONES / name
        if not path.exists(): path = TONES / SETTINGS.get("tone", "ding_dong.wav")
        return path if path.exists() else ROOT / CFG["bell_audio"]
    def play(self, path=None, loop=True):
        if pygame is None: print("Audio unavailable: pygame missing", flush=True); return
        try:
            if pygame.mixer.get_init(): pygame.mixer.quit()
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=4096)  # a large buffer: no dropouts
            pygame.mixer.music.load(str(path or self.tone())); pygame.mixer.music.play(-1 if loop else 0)
        except Exception as e: print("Audio unavailable:", e, flush=True)
    def stop(self):
        if pygame and pygame.mixer.get_init(): pygame.mixer.music.stop(); pygame.mixer.quit()
    def release_if_idle(self):
        """Closes the audio stream once a sound has finished: an open one keeps the speaker link busy."""
        if pygame and pygame.mixer.get_init() and not pygame.mixer.music.get_busy(): pygame.mixer.quit()

class Camera(QThread):
    """Reads the VIGI RTSP stream while a ring is active and hands frames to the UI.
    Only the newest frame is delivered; if the UI is busy, frames are dropped
    rather than queued, so the picture never lags behind live. Every frame is
    also offered to the detector (it keeps only the newest)."""
    frame = Signal(QImage)
    state = Signal(str)
    def __init__(self, url, detector=None):
        super().__init__(); self.url = url; self.detector = detector; self.idle = threading.Event(); self.idle.set()
    def run(self):
        while not self.isInterruptionRequested():
            self.state.emit("Connecting to camera…")
            cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                cap.release(); self.state.emit("Camera unavailable · retrying")
                for _ in range(20):
                    if self.isInterruptionRequested(): return
                    self.msleep(100)
                continue
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.state.emit("")
            while not self.isInterruptionRequested():
                ok, img = cap.read()
                if not ok: self.state.emit("Camera stream lost · reconnecting"); break
                if self.detector: self.detector.offer(img)
                if not self.idle.is_set(): continue
                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB); h, w, _ = rgb.shape
                self.idle.clear(); self.frame.emit(QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy())
            cap.release()
    def stop(self):
        self.requestInterruption(); self.wait(6000)

def label(text, obj=None):
    w = QLabel(text)
    if obj: w.setObjectName(obj)
    return w

class Window(QWidget):
    def __init__(self):
        super().__init__(); self.setWindowTitle("Indoor Doorbell Dashboard"); self.setMinimumSize(800,450)
        self.active=False; self.until=0; self.event_id=None; self.camera=None
        self.audio=Audio(); self.bt=Bluetooth(); self.door_ip=None
        self.intercom=Intercom()
        self.stack=QStackedWidget(); self.home=QuickHome(SETTINGS.get("home_view","news"), SETTINGS.get("look", looks.DEFAULT),
                                                         ROOT/CFG.get("scenic",{}).get("folder","assets/scenic"),
                                                         lambda: camera_cfg.url(which="sub") or camera_cfg.url()); self.ring=RingPage(lambda: SETTINGS.get("intercom", False))
        self.home.view_changed.connect(lambda v: (SETTINGS.__setitem__("home_view", v), save_settings()))
        self.news=News(SETTINGS, ROOT/"news_cache.json")
        self.news.updated.connect(self.home.set_news); self.news.breaking.connect(self.home.set_breaking)
        self.markets=Markets(); self.markets.updated.connect(self.home.set_market)
        self.markets.status.connect(self.home.set_market_note); self.markets.start()
        self.news.failed.connect(lambda why: self.home.set_news_note(f"News unavailable ({why}). Retrying every minute."))
        self.news.start()
        self.notifier=Notifier(SETTINGS, CFG.get("notify",{}).get("server"), CFG.get("notify",{}).get("token"))
        self.settings=SettingsPage(self.bt, TONES, SETTINGS, save_settings, self.preview, self.send_outdoor, self.news.refresh,
                                   CFG.get("festivals"), self.notifier)
        self.settings.speaker.test_cb=lambda: self.preview(self.audio.tone())
        self.settings.webaccess.changed.connect(self.apply_web_access); QTimer.singleShot(0, self.apply_web_access)
        # the doorbell's microphone: recorded with the camera's picture, heard while the camera view is open
        # people, animals and vehicles (on the Hailo): boxes in the Front door view, and motion recording
        self.detector=Detector(); self.detector.found.connect(lambda found: self.stack.currentWidget() is self.ring and self.ring.set_boxes(found))
        self.watcher=Watcher(self.detector, lambda: camera_cfg.url(which="sub") or camera_cfg.url(), lambda: self.camera is not None)
        self.watcher.moved.connect(self.on_motion); self.motion_until=0.0; self.motion_seen=[]
        self.door_audio=DoorAudio(); self.door_live=LivePlayer(self.door_audio); self.listen_until=0.0; self.listen_sent=0.0
        self.recorder=Recorder(lambda: camera_cfg.url() or CFG.get("camera",{}).get("rtsp_url",""),
                               lambda: SETTINGS.get("record_audio", True), self.door_audio)
        # the dashboard in a browser (Settings > Web access); actions come back here like taps
        self.web=Web(recorder_mod.DIR, lambda: camera_cfg.url(which="sub") or camera_cfg.url(), self.door_audio)
        self.door_online=None
        self.events_page=EventsPage(self.recorder)
        self.recorder.saved.connect(lambda _e: self.show_visits()); self.show_visits()
        self.settings.camera.on_saved=self.recorder.buffer.restart  # new camera details: rebuffer from it
        self.settings.camera.on_audio=self.recorder.buffer.restart  # sound in recordings switched on or off
        self.settings.look.on_look=self.apply_look
        self.events_page.back.connect(lambda: self.stack.setCurrentWidget(self.home))
        self.home.open_events.connect(lambda: (self.events_page.set_filter(None), self.stack.setCurrentWidget(self.events_page)))
        for page in (self.home, self.ring, self.settings, self.events_page): self.stack.addWidget(page)
        self.home.open_settings.connect(lambda: self.stack.setCurrentWidget(self.settings))
        self.settings.back.connect(lambda: (self.audio.stop(), self.stack.setCurrentWidget(self.home)))
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0); layout.addWidget(self.stack)
        # Voice: a round button floating over every page, and a bubble saying what was heard and done.
        self.muted_until=0.0
        self.assistant=Assistant()
        self.mic=QPushButton("◉",self); self.mic.setObjectName("mic"); self.mic.setFixedSize(84,84); self.mic.clicked.connect(self.assistant.listen)
        # not over the settings menu, nor the home screen (it has its own voice orb)
        self.stack.currentChanged.connect(lambda _i: self.mic.setVisible(self.stack.currentWidget() not in (self.settings, self.home)))
        self.mic.hide(); self.home.listen.connect(self.assistant.listen)
        self.bubble=QLabel("",self); self.bubble.setObjectName("bubble"); self.bubble.setAlignment(Qt.AlignCenter); self.bubble.hide()
        self.bubble_timer=QTimer(self); self.bubble_timer.setSingleShot(True); self.bubble_timer.timeout.connect(self.bubble.hide)
        self.assistant.state.connect(self.on_voice_state); self.assistant.heard.connect(lambda t: self.say(f"“{t}”" if t else "…", 0))
        self.assistant.command.connect(self.on_voice_command)
        self.assistant.unknown.connect(lambda t: self.say(f"“{t}” · sorry, I can't do that yet" if t else "Sorry, I didn't catch that"))
        self.ring.stop.connect(lambda: self.stop_ring("TOUCH"))
        self.ring.talk.connect(self.toggle_call)
        self.intercom.state.connect(lambda note: self.ring.set_call(True, note))
        self.intercom.ended.connect(self.call_ended)
        self.home.open_door.connect(self.open_door)
        if SETTINGS.get("speaker"): self.bt.request("reconnect", SETTINGS["speaker"]["mac"])
        self.sig=Signals(); self.sig.message.connect(self.handle); self.sig.status.connect(self.home.set_status)
        self.mqtt=MQTT(self.sig); self.mqtt.start()
        self.tick=QTimer(self); self.tick.timeout.connect(self.countdown); self.tick.start(200)
        self.audio_idle=QTimer(self); self.audio_idle.timeout.connect(self.audio.release_if_idle); self.audio_idle.start(5000)
        self.listen_timer=QTimer(self); self.listen_timer.timeout.connect(self.listen_tick); self.listen_timer.start(2000)
        # Is the doorbell there? Its broker connection has a last will: "offline" ~45 s after it vanishes.
        self.mqtt_ok=False; self.offline_since=time.time(); self.offline_alerted=False  # nothing heard yet counts as gone
        self.sig.status.connect(lambda ok, _m: setattr(self, "mqtt_ok", ok))
        self.door_watch=QTimer(self); self.door_watch.timeout.connect(self.check_door); self.door_watch.start(30000)
        self.demo=QTimer(self)
        if CFG.get("demo_mode",False): self.demo.timeout.connect(self.demo_ring); self.demo.start(18000)
        # Festival themes: checked every minute; the result goes to the doorbell as a retained message.
        self.fest_sent=None; self.fest_preview=None  # last payload published; (key, monotonic end) of a trial
        self.sig.status.connect(lambda ok, _m: ok and (setattr(self, "fest_sent", None), QTimer.singleShot(500, self.check_festival)))
        self.settings.festival_changed.connect(self.check_festival); self.settings.festival_preview.connect(self.preview_festival)
        self.fest_timer=QTimer(self); self.fest_timer.timeout.connect(self.check_festival); self.fest_timer.start(60000)
        self.fest_timer.timeout.connect(self.show_visits)  # "today" starts again at midnight
        self.check_festival()
        self.webapp=WebApp(self, SETTINGS, save_settings, TONES)  # the dashboard in browsers; last: it uses everything above
    def cfg_camera_url(self): return CFG.get("camera",{}).get("rtsp_url","")
    def on_motion(self, labels):
        """A person, animal or vehicle moved in view (watch.py): recorded from 5 s before to 55 s after."""
        now=time.time()
        if now<self.motion_until:  # already recording: note what else came by
            self.motion_seen.extend(l for l in labels if l not in self.motion_seen); return
        if not SETTINGS.get("motion_record", True) or self.active: return  # a ring records itself
        self.motion_seen=list(labels); self.motion_until=now+recorder_mod.MOTION_S
        # the doorbell's sound too, from its history: the clip's 5 s before, and room to line it up
        pre_ms=int((recorder_mod.MOTION_PRE_S+recorder_mod.MARGIN_S+0.5)*1000)
        if self.mqtt.publish(T_TALK, {"command": "listen", "host": this_ip(), "port": LISTEN_PORT, "seconds": 15, "pre_ms": pre_ms}):
            self.listen_sent=now
        self.want_listen(recorder_mod.MOTION_S+5)  # kept going while the clip records
        self.recorder.record("motion", recorder_mod.MOTION_S, recorder_mod.MOTION_PRE_S, self.motion_seen)
        self.home.add_event("Motion: "+", ".join(labels))
    def show_visits(self):
        """Rings today and the last visitor's picture, for the home screen."""
        rings=[e for e in self.recorder.entries if e.get("kind")=="ring"]
        midnight=dt.datetime.combine(dt.date.today(), dt.time()).timestamp()
        last=max(rings, key=lambda e: e["time"]) if rings else None
        thumb=recorder_mod.DIR/last["thumb"] if last and last.get("thumb") else None
        self.home.set_visits(sum(1 for e in rings if e["time"]>=midnight), last["time"] if last else 0, thumb)
    def cfg_festivals(self): return CFG.get("festivals")
    def preview_festival(self, key):
        """Show a festival for one minute (Settings > Festivals > Try)."""
        self.fest_preview=(key, time.monotonic()+60) if key else None
        self.check_festival()
        if key: QTimer.singleShot(61000, self.check_festival)
    def check_festival(self):
        today=dt.date.today(); key=until=None
        if self.fest_preview and time.monotonic()<self.fest_preview[1]:
            key=self.fest_preview[0]; until=int(time.time()+self.fest_preview[1]-time.monotonic())
        else:
            self.fest_preview=None
            if SETTINGS.get("festival_themes", True):
                key, last=current_festival(today, CFG.get("festivals"))
                if key:  # runs until midnight after the last day
                    until=int(dt.datetime.combine(last+dt.timedelta(days=1), dt.time()).timestamp())
        tones=bool(key) and SETTINGS.get("festival_tones", True)
        FESTIVAL["key"]=key if tones else None
        text=festival_greeting(key, today) if key else ""
        if self.home.festival_key!=key or self.home.greeting!=text: self.home.set_festival(key, text)
        if key!=getattr(self, "fest_look", None):  # wallpaper and page colours follow the festival
            self.fest_look=key; style(QApplication.instance(), key, SETTINGS.get("look"))
        payload={"festival":key or "none","until":until or 0,"greeting":text,"tones":tones}
        if payload!=self.fest_sent and self.mqtt.publish(T_FESTIVAL, payload, retain=True): self.fest_sent=payload
    def demo_ring(self):
        if not self.active: self.start_ring(CFG.get("default_timer_seconds",30),"DEMO")
    def preview(self, path):
        if not self.active: self.audio.play(path, loop=False)  # never over a real ring
    def send_outdoor(self, change):
        return self.mqtt.publish(T_OUT_CONFIG, change)
    def handle(self,topic,payload):
        c=CFG["mqtt"]
        if topic in (T_OUT_STATE, T_OUT_SCAN, T_OUT_ONLINE):
            o=self.settings.outdoor
            if topic==T_OUT_ONLINE:
                online=payload.strip()=="online"
                o.on_online(online); self.door_online=online; self.home.set_door(online); self.door_status_changed(online); self.web_publish(); return
            try: data=json.loads(payload)
            except ValueError: return
            if topic==T_OUT_STATE and data.get("ip"): self.door_ip=data["ip"]  # where call audio goes
            (o.on_state if topic==T_OUT_STATE else o.on_scan)(data); return
        if topic==c["topic_stop"]: self.stop_ring("MQTT"); return
        if topic!=c["topic_start"]: return
        try:
            data=json.loads(payload) if payload.strip().startswith("{") else {"timer":int(payload.strip())}
            cmd=str(data.get("command",data.get("action","start"))).lower()
            if cmd in ("stop","cancel"): self.stop_ring("MQTT"); return
            seconds=max(1,min(3600,int(data.get("timer",data.get("timer_seconds",CFG.get("default_timer_seconds",30))))))
            # Ack first, also for duplicates: the outdoor unit resends the start every
            # 2 s until it sees an ack carrying its event_id.
            self.mqtt.publish(c["topic_ack"],{"event_id":data.get("event_id"),"status":"duplicate" if self.active else "received"})
            if self.active: return  # already ringing: discard until the timer has run out
            self.start_ring(seconds,"MQTT",data.get("event_id"))
        except Exception as e: self.home.add_event("Invalid MQTT command: "+str(e))
    # ---------- voice ----------
    def resizeEvent(self, e):
        super().resizeEvent(e); self.place_mic(); self.place_bubble()
    def place_mic(self):
        self.mic.move(24, self.height()-self.mic.height()-BOTTOM_H-16); self.mic.raise_()  # above the market band and ticker
    def apply_look(self):
        """Settings > Look: the pages' colours (a festival's own while it lasts) and the home page's layout."""
        style(QApplication.instance(), getattr(self, "fest_look", None), SETTINGS.get("look"))
        self.home.set_look(SETTINGS.get("look", looks.DEFAULT)); self.place_mic()
    def place_bubble(self):
        self.bubble.adjustSize(); w=min(self.width()-240, max(420, self.bubble.width()+60))
        self.bubble.setFixedSize(w, 72); self.bubble.move((self.width()-w)//2, self.height()-72-BOTTOM_H-24); self.bubble.raise_()
    def say(self, text, hide_after=4000):
        """Shows the bubble; hide_after 0 keeps it up (more is coming)."""
        self.bubble.setText(text); self.bubble.show(); self.place_bubble(); self.bubble_timer.stop()
        if hide_after: self.bubble_timer.start(hide_after)
    def on_voice_state(self, state):
        self.home.set_mic(state)
        self.mic.setProperty("listening", state=="listening"); self.mic.style().unpolish(self.mic); self.mic.style().polish(self.mic)
        if state=="listening": self.say("Listening…", 0)
        elif state=="thinking": self.say("…", 0)
        elif state: self.say(state)
    def on_voice_command(self, action, args, reply):
        self.say(reply)
        if action=="stop":
            if self.active: self.stop_ring("TOUCH")
            else: self.audio.stop()
        elif action=="mute":
            self.muted_until=time.monotonic()+args*60; self.audio.stop()
            self.home.add_event(f"Bell muted until {time.strftime('%I:%M %p', time.localtime(time.time()+args*60)).lstrip('0')}")
        elif action=="unmute":
            self.muted_until=0.0; self.home.add_event("Bell on again")
        if action in ("mute", "unmute"): self.web_publish()
        elif action=="events":
            self.events_page.set_filter(args); self.stack.setCurrentWidget(self.events_page)
        elif action=="play_last":
            e=self.events_page.latest_with_video()
            if not e: self.say("There is no recording yet"); return
            self.events_page.set_filter(None); self.stack.setCurrentWidget(self.events_page); self.events_page.open(e)
        elif action=="door":
            if not self.active: self.open_door()
        elif action=="home":
            for player in self.findChildren(QFrame, "player"): player.close_player()
            if not self.active: self.stop_camera(); self.stack.setCurrentWidget(self.home)
        elif action=="settings":
            self.stack.setCurrentWidget(self.settings)
    # ---------- web access ----------
    def apply_web_access(self):
        import web as webmod
        if SETTINGS.get("web_access", False) and webmod.has_password(): self.web.start(); self.webapp.publish_all()
        else: self.web.stop()
    def web_publish(self):
        """Browsers see the change (called on every change, each second while ringing)."""
        if self.web.server: self.webapp.state()
    def open_door(self):
        """Front door tile: live camera and the intercom, no ring."""
        if self.active: return
        self.ring.set_mode(False); self.ring.set_call(False); self.stack.setCurrentWidget(self.ring); self.start_camera(); self.start_sound()
    # ---------- is the doorbell there? ----------
    def door_status_changed(self, online):
        now=time.time()
        if online:
            if self.offline_alerted:
                gone=fmt_span(now-self.offline_since)
                self.alert_phones("Doorbell back online", f"The doorbell is working again; it was offline for {gone}.", "white_check_mark", "default")
                self.home.add_event(f"Doorbell back online (offline {gone})")
            self.offline_since=None; self.offline_alerted=False
        elif self.offline_since is None:
            self.offline_since=now; self.offline_alerted=False; self.home.add_event("Doorbell went offline")
    def check_door(self):
        """Alerts the phones once the doorbell has been gone for the time chosen in Settings > Phone."""
        wait=SETTINGS.get("offline_alert_min", 15)
        if not wait or self.offline_since is None or self.offline_alerted or not self.mqtt_ok: return
        if time.time()-self.offline_since < wait*60: return
        self.offline_alerted=True
        since=time.strftime("%I:%M %p", time.localtime(self.offline_since)).lstrip("0")
        heard="has not been heard from" if self.door_online is None else "has been offline"
        self.alert_phones("Doorbell offline", f"The doorbell {heard} since {since}: rings will not reach you. "
                          "Check its power and Wi-Fi.", "warning", "high")
    def alert_phones(self, title, text, tags, priority):
        """ntfy (Settings > Phone) and the browsers registered for ring alerts."""
        self.notifier.send(title, text, tags=tags, priority=priority)
        import push
        push.send({"type": "health", "tag": "doorbell-health", "title": title, "body": text, "time": time.time()},
                  self.webapp.sub_claim(), ttl=6*3600, urgency="high" if priority=="high" else "normal")
        print(f"Phones alerted: {title}", flush=True)
    # ---------- the doorbell's microphone ----------
    def want_listen(self, seconds):
        """The doorbell's microphone is needed for `seconds` more (it is asked again until then)."""
        self.listen_until=max(self.listen_until, time.time()+seconds); self.listen_tick()
    def listen_tick(self):
        now=time.time()
        if self.stack.currentWidget() is self.ring or self.door_live.active: self.listen_until=max(self.listen_until, now+6)
        if self.web.live_audio.listeners: self.listen_until=max(self.listen_until, now+6)
        if now<self.listen_until:
            if now-self.listen_sent>8 and self.mqtt.publish(T_TALK, {"command": "listen", "host": this_ip(), "port": LISTEN_PORT, "seconds": 15}):
                self.listen_sent=now
        elif self.listen_sent:
            self.mqtt.publish(T_TALK, {"command": "listen_end"}); self.listen_sent=0.0
        if self.door_live.active:
            self.ring.set_sound("" if self.door_audio.receiving() or now-self.sound_started<4
                                else "No sound from the doorbell yet (its firmware may need updating)")
    def start_sound(self):
        """The door's sound plays with its picture, mixed with the chime while ringing."""
        if self.intercom.active or self.door_live.active: return  # a call has its own sound
        self.door_live.start(); self.sound_started=time.time(); self.want_listen(10)
    def stop_sound(self):
        self.door_live.stop(); self.ring.set_sound("")
    def toggle_call(self):
        if self.intercom.active: self.end_call(); return
        if not SETTINGS.get("intercom", False): return
        if not self.door_ip: self.ring.set_call(False, "Doorbell address not known yet (it is sent when the doorbell connects)"); return
        self.stop_sound(); self.audio.stop()  # the bell tone gives way to the call, and the speaker is switched to hands-free
        if pygame and pygame.mixer.get_init(): pygame.mixer.quit()
        if not self.mqtt.publish(T_TALK, {"command": "start", "host": this_ip(), "port": TALK_PORT}):
            self.ring.set_call(False, "Not connected to the doorbell (MQTT)"); return
        self.home.add_event("Talked to the door")
        self.intercom.start(self.door_ip, (SETTINGS.get("speaker") or {}).get("name")); self.ring.set_call(True, "Connecting…")
    def end_call(self):
        self.mqtt.publish(T_TALK, {"command": "end"}); self.intercom.stop()
    def call_ended(self):
        note=self.ring.call_note.text()
        self.ring.set_call(False, note if note.startswith("Call failed") else "Call ended")
        if self.active: self.until=max(self.until, time.monotonic()+10)  # a moment to see the door before the page closes
        if self.stack.currentWidget() is self.ring: self.start_sound()  # back to hearing the door
    def start_camera(self):
        if self.camera: return
        url=camera_cfg.url() or CFG.get("camera",{}).get("rtsp_url","")  # Settings > Camera, else config.json
        if not url: self.ring.clear_video("Camera not set up · Settings › Camera"); return
        if cv2 is None: self.ring.clear_video("OpenCV missing · sudo apt install python3-opencv"); return
        self.ring.clear_video("Connecting to camera…")
        self.camera=Camera(url, self.detector); self.camera.frame.connect(self.on_frame); self.camera.state.connect(self.ring.set_note); self.camera.start()
    def on_frame(self, img):
        self.ring.show_frame(img); self.webapp.frame(img)
        if self.camera: self.camera.idle.set()
    def stop_camera(self):
        self.stop_sound()
        if self.camera:
            cam=self.camera; self.camera=None
            cam.frame.disconnect(); cam.state.disconnect(); cam.stop()
        self.ring.clear_video("")
    def start_ring(self,seconds,source="MQTT",event_id=None):
        seconds=max(1,min(3600,int(seconds))); self.until=time.monotonic()+seconds; self.event_id=event_id; self.ring_total=seconds
        self.ring.set_mode(True); self.ring.set_call(self.intercom.active)
        self.ring.set_count(seconds, seconds)
        self.ring.set_subtitle("Bell muted" if time.monotonic() < self.muted_until else "The bell is ringing inside")
        self.stack.setCurrentWidget(self.ring); self.start_camera(); self.start_sound()
        if self.intercom.active: pass  # no bell tone over a call
        elif time.monotonic() < self.muted_until: self.home.add_event("Bell muted: no chime")
        else: self.audio.play()
        self.active=True; self.home.add_event(f"Doorbell started ({seconds}s)")
        if source=="MQTT":  # a real press: record it (Events page)
            clip=max(1, min(SETTINGS.get("record_seconds", CLIP_S), seconds))  # never longer than the ring
            self.recorder.record("ring", clip)  # with 3 s from before the press
            self.want_listen(clip+PRE_S+5)  # the doorbell streams from the press; keep it going
        if source=="MQTT":  # a real press (not the demo): tell the phones
            self.notifier.send("Doorbell", "Someone is at the front door · "+time.strftime("%I:%M %p").lstrip("0"))
        self.mqtt.publish(CFG["mqtt"]["topic_status"],{"state":"ringing","remaining_seconds":seconds,"event_id":event_id})
        self.web_publish(); self.webapp.ring_started(source)
        self.demo.stop()
    def countdown(self):
        if not self.active:return
        if self.intercom.active: self.until=max(self.until, time.monotonic()+1)  # the page stays while talking
        remaining=max(0,int(self.until-time.monotonic()+0.999))
        if remaining!=getattr(self,"_last_left",None): self._last_left=remaining; self.ring.set_count(remaining); self.web_publish()
        if remaining<=0:self.stop_ring("TIMER")
    def stop_ring(self,source="TOUCH"):
        if self.intercom.active and source in ("TOUCH", "MQTT"): self.end_call()
        if not self.active:  # the live door view closes
            self.stop_camera(); self.stack.setCurrentWidget(self.home); return
        self.active=False; self.audio.stop(); self.stop_camera(); self.stack.setCurrentWidget(self.home)
        self.home.add_event("Doorbell ended ("+source.lower()+")")
        # STOP pressed here: tell the outdoor unit so it returns to its main screen.
        # (On TIMER both sides time out by themselves; on MQTT the stop came from outside.)
        if source=="TOUCH":
            self.mqtt.publish(CFG["mqtt"]["topic_stop"],{"command":"stop","source":"indoor","event_id":self.event_id})
        self.mqtt.publish(CFG["mqtt"]["topic_status"],{"state":"idle","reason":source.lower(),"event_id":self.event_id})
        self.web_publish(); self.webapp.ring_ended(source)
        self.event_id=None
        if CFG.get("demo_mode",False): self.demo.start(18000)
    @staticmethod
    def fmt(s): return f"{s//60:02d}:{s%60:02d}"
    def closeEvent(self,event):
        self.door_live.stop(); self.web.stop(); self.markets.stop(); self.recorder.stop(); self.watcher.stop(); self.intercom.stop(); self.audio.stop(); self.stop_camera(); self.mqtt.close(); self.bt.request("quit"); self.news.stop(); event.accept()

def fmt_span(seconds):
    """3 h 20 min, 12 min, 1 day 4 h"""
    m=int(seconds//60); d, m=divmod(m, 1440); h, m=divmod(m, 60)
    return " ".join(t for t in (f"{d} day{'s' if d>1 else ''}" if d else "", f"{h} h" if h else "", f"{m} min" if (m or not (d or h)) and not d else "") if t)

# Colours of every page come from the look (looks.py); a festival swaps in its own set (see Window.check_festival).
FEST_TEXT = dict(text="#edf3fb", text2="#b3c0d1")
PALETTES = {
    "diwali": dict(**FEST_TEXT, bg="#1a0709", panel="#2a0e10", button="#3a1416", border="#6a2a22", line="#52201c", accent="#e8952a",
                   on_accent="#2a1200", muted="#d9a86b", list="#210a0c", count="#ffc24a", tag="#ffc24a"),
    "christmas": dict(**FEST_TEXT, bg="#071a10", panel="#0f2a1b", button="#15402a", border="#2b6a46", line="#1e5236", accent="#c8302f",
                      on_accent="#ffffff", muted="#a9c9b4", list="#0b2116", count="#ff8a80", tag="#ff8a80"),
    "new_year": dict(**FEST_TEXT, bg="#070b24", panel="#101a40", button="#18245a", border="#2f3f85", line="#223070", accent="#d4a537",
                     on_accent="#1a1400", muted="#a3aed6", list="#0c1434", count="#ffd54a", tag="#ffd54a"),
}
PALETTE = dict(looks.get(looks.DEFAULT)["colors"])
STYLE = Template("""
    QWidget { background:$bg; color:$text; font-family:'$sans'; font-size:15px; }
    #ring { background:$bg; }
    QLabel#section {color:$muted;font-size:12px;font-weight:700;letter-spacing:1px;}
    QLabel#secondary {color:$text2;font-size:14px;}
    QLabel#sectionTitle {font-family:'$display';font-size:$title_px;font-weight:$title_weight;}
    QFrame#video {background:#000;border:1px solid $line;border-radius:18px;}
    QLabel#videoView {background:#000;border-radius:18px;}
    QLabel#camNote {background:transparent;color:$muted;font-size:14px;padding:6px;}
    QFrame#side {background:transparent;}
    QFrame#side QLabel {background:transparent;}
    QLabel#bell {font-size:72px;}
    QLabel#ringTitle {font-size:28px;font-weight:700;color:#f8fafc;}
    QLabel#count {font-size:56px;font-weight:700;color:$count;}
    QPushButton#ringStop {background:#e5484d;color:white;border:0;border-radius:52px;font-size:34px;font-weight:800;letter-spacing:3px;}
    QPushButton#ringStop:pressed {background:#c43c40;}
    QPushButton#ringTalk {background:rgba(47,163,107,230);color:white;border:0;border-radius:52px;font-size:28px;font-weight:700;}
    QPushButton#ringTalk:pressed {background:#258556;}
    QPushButton#ringTalk[calling="true"] {background:#e8952a;}
    QPushButton#stop {background:#e85d5d;color:white;border:0;border-radius:24px;font-size:34px;font-weight:800;letter-spacing:4px;}
    QPushButton#stop:pressed {background:#c94343;}
    QPushButton#talk {background:#2fa36b;color:white;border:0;border-radius:24px;font-size:26px;font-weight:700;}
    QPushButton#talk:pressed {background:#258556;}
    QPushButton#talk[calling="true"] {background:#e8952a;}
    QPushButton {background:$button;color:$text;border:1px solid $border;border-radius:14px;font-size:17px;padding:0 18px;}
    QPushButton:pressed {background:$line;}
    QPushButton:checked {background:$accent;border-color:$accent;color:$on_accent;}
    QPushButton#subtab {background:transparent;border:0;border-bottom:3px solid transparent;border-radius:0;font-size:19px;color:$muted;}
    QPushButton#subtab:checked {color:$text;border-bottom:3px solid $accent;background:transparent;}
    QPushButton#nav {text-align:left;padding-left:24px;font-size:19px;}
    QLabel#pageTitle {font-family:'$display';font-size:$page_px;font-weight:$title_weight;}
    QPushButton#eventCard {background:$panel;border:1px solid $line;border-radius:18px;padding:0;}
    QPushButton#eventCard:pressed {background:$button;}
    QPushButton#mic {background:rgba(10,16,26,170);color:#ffffff;border:2px solid rgba(255,255,255,90);border-radius:42px;font-size:40px;padding:0;}
    QPushButton#mic:pressed {background:$accent;}
    QPushButton#mic[listening="true"] {background:#e5484d;border-color:#ffffff;}
    QLabel#bubble {background:rgba(10,16,26,215);color:#ffffff;border:1px solid rgba(255,255,255,70);border-radius:36px;font-size:24px;padding:0 28px;}
    QPushButton#eventCard:checked {background:$button;border:3px solid $accent;}
    QPushButton#lookCard {background:$panel;border:2px solid $line;border-radius:18px;padding:0;}
    QPushButton#lookCard:checked {background:$button;border:3px solid $accent;}
    QPushButton#lookCard QLabel {background:transparent;}
    QLabel#lookName {font-size:20px;font-weight:700;}
    QLabel#lookAbout {font-size:14px;color:$text2;}
    QLabel#eventPic {background:#000;border-radius:12px;color:$muted;}
    QLabel#eventKind {font-size:17px;font-weight:700;background:transparent;color:#ff9f0a;}
    QLabel#eventKind[kind="motion"] {color:#64d2ff;}
    QLabel#eventTime {font-size:14px;color:$muted;background:transparent;}
    QFrame#player {background:$bg;}
    QLabel#webUrl {font-size:24px;font-weight:700;color:$count;}
    QLabel#camValue {font-size:22px;font-weight:600;}
    QLabel#camPreview {background:#000;border:1px solid $line;border-radius:14px;color:$muted;}
    QLabel#topicName {font-size:34px;font-weight:700;color:$count;padding:4px 0;}
    QFrame#panel {background:$panel;border:1px solid $line;border-radius:18px;}
    QFrame#panel QLabel, QFrame#panel QSlider {background:transparent;}
    QFrame#panel QScrollArea, QFrame#panel QScrollArea > QWidget > QWidget {background:transparent;}
    QFrame#panel QStackedWidget, QFrame#panel QStackedWidget > QWidget {background:transparent;}
    QListWidget#list {background:$list;border:1px solid $line;border-radius:12px;font-size:18px;}
    QListWidget#list::item {min-height:58px;padding-left:12px;}
    QListWidget#list::item:selected {background:$accent;color:$on_accent;border-radius:10px;}
    QSlider::groove:horizontal {height:10px;background:$line;border-radius:5px;}
    QSlider::handle:horizontal {background:$accent;width:36px;margin:-14px 0;border-radius:18px;}
    QDialog#keyboard {background:$bg;}
    QLineEdit#kbEdit {background:$panel;border:2px solid $accent;border-radius:12px;font-size:24px;padding:0 14px;}
    QPushButton#kbKey {font-size:22px;}
    QPushButton#kbOk {font-size:20px;background:$accent;border-color:$accent;}
    """)

def style(app, festival=None, look=None):
    """Every page's colours (the festival's while one is on, else the look's) and the look's fonts (Settings > Look)."""
    PALETTE.clear(); PALETTE.update(PALETTES.get(festival) or looks.get(look)["colors"])
    app.setStyleSheet(STYLE.substitute(PALETTE, **looks.get(look)["type"]))
def main():
    app=QApplication(sys.argv); style(app, None, SETTINGS.get("look")); w=Window()
    # Quit cleanly on SIGTERM; the timer gives Python a chance to run the handler.
    signal.signal(signal.SIGTERM, lambda *a: app.quit())
    keepalive=QTimer(); keepalive.timeout.connect(lambda: None); keepalive.start(500)
    if os.environ.get("DOORBELL_FULLSCREEN","1")=="1": w.showFullScreen()
    else:w.show()
    sys.exit(app.exec())
if __name__=="__main__":main()
