"""Finds people, animals and vehicles in camera frames, on the Pi's Hailo AI
accelerator (YOLOv8s trained on COCO, from Raspberry Pi's hailo-models package).

A frame takes ~33 ms on the Hailo-8L and next to no CPU. Only the newest frame
is looked at (offer() replaces any waiting one), at most RATE times a second.
Everything else the model knows (plants, furniture, ...) is ignored, and so is
anything below its kind's MIN_SCORE: swaying leaves and insects are not
recognised as any of these kinds, so they never count.

found(list) is emitted for every frame looked at, with what was in it:
{"kind": "person" | "animal" | "vehicle", "label": "Person", "score": 0.92,
 "box": (x1, y1, x2, y2)} with the box in 0..1 of the frame's width and height."""
import threading, time
from pathlib import Path
import numpy as np
import cv2
from PySide6.QtCore import QObject, Signal

HEF = Path("/usr/share/hailo-models/yolov8s_h8l.hef")
RATE = 10  # frames a second, at most
# COCO class number: (kind, label)
KINDS = {0: ("person", "Person"),
         1: ("vehicle", "Bicycle"), 2: ("vehicle", "Car"), 3: ("vehicle", "Motorbike"), 5: ("vehicle", "Bus"), 7: ("vehicle", "Truck"),
         14: ("animal", "Bird"), 15: ("animal", "Cat"), 16: ("animal", "Dog"), 17: ("animal", "Horse"), 18: ("animal", "Sheep"),
         19: ("animal", "Cow"), 20: ("animal", "Elephant"), 21: ("animal", "Bear"), 22: ("animal", "Zebra"), 23: ("animal", "Giraffe")}
MIN_SCORE = {"person": 0.5, "animal": 0.55, "vehicle": 0.5}


class Detector(QObject):
    found = Signal(list)

    def __init__(self):
        super().__init__()
        self.cond = threading.Condition(); self.frame = None; self.ready = False; self.problem = ""
        threading.Thread(target=self._run, daemon=True).start()

    def offer(self, bgr):
        """A frame to look at (BGR, any size); a newer one replaces it if it was not looked at yet."""
        if not self.ready: return
        with self.cond:
            self.frame = bgr; self.cond.notify()

    def _run(self):
        try:
            from hailo_platform import (HEF as Hef, VDevice, ConfigureParams, InputVStreamParams, OutputVStreamParams,
                                        FormatType, HailoStreamInterface, InferVStreams)
            hef = Hef(str(HEF))
            with VDevice() as dev:
                group = dev.configure(hef, ConfigureParams.create_from_hef(hef, interface=HailoStreamInterface.PCIe))[0]
                inputs = InputVStreamParams.make(group, format_type=FormatType.UINT8)
                outputs = OutputVStreamParams.make(group, format_type=FormatType.FLOAT32)
                info = hef.get_input_vstream_infos()[0]
                with InferVStreams(group, inputs, outputs) as pipe, group.activate(group.create_params()):
                    self.ready = True; print("Detector: Hailo ready", flush=True)
                    last = 0.0
                    while True:
                        with self.cond:
                            self.cond.wait_for(lambda: self.frame is not None)
                            frame, self.frame = self.frame, None
                        wait = 1 / RATE - (time.monotonic() - last)
                        if wait > 0: time.sleep(wait)
                        last = time.monotonic()
                        self.found.emit(self._look(pipe, info, frame))
        except Exception as e:  # no Hailo, no model: the camera view simply has no boxes
            self.problem = str(e); self.ready = False
            print("Detector unavailable:", e, flush=True)

    @staticmethod
    def _look(pipe, info, frame):
        H, W = info.shape[0], info.shape[1]
        h, w = frame.shape[:2]; s = min(W / w, H / h); nw, nh = int(w * s), int(h * s)
        top, left = (H - nh) // 2, (W - nw) // 2
        canvas = np.full((H, W, 3), 114, np.uint8)  # letterboxed, as the model was trained
        canvas[top:top + nh, left:left + nw] = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
        out = pipe.infer({info.name: cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)[None]})
        per_class = list(out.values())[0][0]  # 80 arrays of (y1, x1, y2, x2, score), 0..1 of the letterboxed input
        found = []
        for cls, (kind, label) in KINDS.items():
            for y1, x1, y2, x2, score in np.asarray(per_class[cls]).reshape(-1, 5):
                if score < MIN_SCORE[kind]: continue
                box = tuple(float(min(1.0, max(0.0, v))) for v in (
                    (x1 * W - left) / nw, (y1 * H - top) / nh, (x2 * W - left) / nw, (y2 * H - top) / nh))
                found.append({"kind": kind, "label": label, "score": round(float(score), 2), "box": box})
        return found
