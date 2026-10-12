"""
waste_classifier.py - AI Inference + Bin Mapping + Anti-Double-Counting

ตรรกะสำคัญ (อ้างอิงรายงานบทที่ 3-4):
1. โหลด models/best.pt (custom) ถ้าไม่มีจะ fallback เป็น yolov8n.pt (COCO)
2. แปลงชื่อคลาสจากโมเดล -> หมวดขยะ 4 หมวด -> ถังขยะที่แนะนำ
3. กรองด้วย Confidence >= 0.60
4. Cooldown: หมวด/คลาสเดียวกันจะถูกบันทึกลง DB ได้อีกครั้งหลังผ่านไป 3 วินาที
"""
import threading
import time
from pathlib import Path

import cv2
import numpy as np

import database

MODEL_DIR = Path(__file__).parent / "models"
CUSTOM_MODEL = MODEL_DIR / "best.pt"

CONF_THRESHOLD = 0.60
COOLDOWN_SECONDS = 3.0

# ---- ข้อมูลถังขยะ 4 สี (color_bgr สำหรับ OpenCV, color_hex สำหรับเว็บ) ----
BINS = {
    "organic": {
        "name": "ถังขยะสีเขียว (ขยะอินทรีย์ / ขยะย่อยสลายได้)",
        "color_bgr": (80, 200, 60), "color_hex": "#3CC850", "short": "GREEN BIN",
        "types": "เศษอาหาร, พืชผัก, ผลไม้เน่าเสีย, ใบไม้, กิ่งไม้",
        "handling": "นำไปทำปุ๋ยหมักหรืออาหารสัตว์ได้",
    },
    "recyclable": {
        "name": "ถังขยะสีเหลือง (ขยะรีไซเคิล)",
        "color_bgr": (0, 215, 255), "color_hex": "#FFD700", "short": "YELLOW BIN",
        "types": "ขวดพลาสติก, แก้ว, กระป๋องอะลูมิเนียม, เศษโลหะ, กล่องกระดาษ, กล่อง UHT, ยาง",
        "handling": "นำกลับมาแปรรูปใหม่ (ควรล้างคราบและทำให้แห้งก่อนทิ้ง)",
    },
    "general": {
        "name": "ถังขยะสีน้ำเงิน/สีฟ้า (ขยะทั่วไป)",
        "color_bgr": (230, 150, 30), "color_hex": "#1E96E6", "short": "BLUE BIN",
        "types": "ซองบะหมี่กึ่งสำเร็จรูป, ถุงพลาสติก, กล่องโฟมเปื้อน, ฟอยล์, เปลือกลูกอม",
        "handling": "ย่อยสลายยากและไม่คุ้มค่ากับการรีไซเคิล จะถูกนำไปกำจัดอย่างถูกวิธี",
    },
    "hazardous": {
        "name": "ถังขยะสีแดง (ขยะอันตราย / ขยะมีพิษ / ขยะติดเชื้อ)",
        "color_bgr": (50, 50, 230), "color_hex": "#E63232", "short": "RED BIN",
        "types": "ถ่านไฟฉาย, แบตเตอรี่, หลอดไฟ, กระป๋องสเปรย์, สารเคมี, หน้ากากอนามัย, ชุดตรวจ ATK",
        "handling": "ต้องแยกทิ้งและปิดฝาให้มิดชิดเพื่อความปลอดภัย",
    },
}
CATEGORY_TO_BIN = BINS  # key = category (organic / recyclable / general / hazardous)

# ---- Mapping ชื่อคลาส -> หมวด (keyword match) สำหรับ Custom Model ----
# ลำดับสำคัญ: hazardous/general ตรวจก่อน recyclable เพื่อไม่ให้ "plastic bag", "foam box"
# ถูกจับเป็นรีไซเคิลเพราะมีคำว่า plastic/box
KEYWORDS = {
    "hazardous": ["battery", "bulb", "lamp", "spray", "chemical", "mask", "atk", "hazard", "toxic"],
    "organic": ["organic", "food", "fruit", "vegetable", "leaf", "leaves", "branch", "peel", "scrap"],
    "general": ["general", "foam", "wrapper", "bag", "noodle", "foil", "candy", "trash"],
    "recyclable": ["plastic", "bottle", "cup", "pet", "glass", "can", "alumin", "metal", "tin",
                   "cardboard", "paper", "carton", "box", "uht", "rubber", "recycl"],
}

# ---- Mapping สำหรับ COCO (yolov8n.pt fallback) ----
COCO_MAP = {
    "bottle": "recyclable", "cup": "recyclable", "wine glass": "recyclable",
    "fork": "recyclable", "knife": "recyclable", "spoon": "recyclable", "scissors": "recyclable",
    "book": "recyclable",
    "banana": "organic", "apple": "organic", "orange": "organic", "sandwich": "organic",
    "broccoli": "organic", "carrot": "organic", "hot dog": "organic", "pizza": "organic",
    "donut": "organic", "cake": "organic",
    "handbag": "general", "toothbrush": "general",
}


def map_class(name: str, using_coco: bool):
    """คืนค่า category หรือ None ถ้าไม่เกี่ยวกับขยะ"""
    n = name.lower().replace("_", " ")
    if using_coco:
        return COCO_MAP.get(n)
    for cat in ("hazardous", "organic", "general", "recyclable"):
        if any(k in n for k in KEYWORDS[cat]):
            return cat
    return None


class WasteClassifier:
    def __init__(self):
        from ultralytics import YOLO
        if CUSTOM_MODEL.exists():
            self.model = YOLO(str(CUSTOM_MODEL))
            self.using_coco = False
            print(f"[AI] โหลด Custom Model: {CUSTOM_MODEL}")
        else:
            self.model = YOLO("yolov8n.pt")  # ดาวน์โหลดอัตโนมัติ
            self.using_coco = True
            print("[AI] ไม่พบ best.pt -> ใช้ yolov8n.pt (COCO fallback)")
        self.names = self.model.names
        self._last_logged: dict[str, float] = {}  # key -> เวลาที่บันทึกล่าสุด
        self._lock = threading.Lock()

    # ---------- Core inference ----------
    def detect(self, frame: np.ndarray):
        """
        รัน YOLO แล้วคืน (annotated_frame, detections)
        detections = list of dict (class_name, category, confidence, bin, box)
        """
        results = self.model.predict(frame, conf=CONF_THRESHOLD, verbose=False)[0]
        annotated = frame.copy()
        detections = []
        for box in results.boxes:
            conf = float(box.conf[0])
            if conf < CONF_THRESHOLD:
                continue
            cls_name = self.names[int(box.cls[0])]
            category = map_class(cls_name, self.using_coco)
            if category is None:
                continue
            bin_info = CATEGORY_TO_BIN[category]
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            self._draw(annotated, (x1, y1, x2, y2), cls_name, conf, bin_info)
            detections.append({
                "class_name": cls_name,
                "category": category,
                "confidence": round(conf, 4),
                "bin_name": bin_info["name"],
                "bin_color": bin_info["color_hex"],
                "types": bin_info["types"],
                "handling": bin_info["handling"],
                "box": [x1, y1, x2, y2],
            })
        return annotated, detections

    @staticmethod
    def _draw(img, box, name, conf, bin_info):
        """วาดกรอบ + label + ค่าความเชื่อมั่น + ชื่อสีถัง (ใช้อังกฤษเพราะ cv2 ไม่รองรับฟอนต์ไทย)"""
        x1, y1, x2, y2 = box
        color = bin_info["color_bgr"]
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 3)
        label = f"{name} {conf * 100:.0f}% -> {bin_info['short']}"
        (tw, th), base = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        top = max(y1 - th - base - 6, 0)
        cv2.rectangle(img, (x1, top), (x1 + tw + 8, top + th + base + 6), color, -1)
        cv2.putText(img, label, (x1 + 4, top + th + 2), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (0, 0, 0), 2, cv2.LINE_AA)

    # ---------- Anti double counting ----------
    def log_with_cooldown(self, detections: list[dict], source: str = "stream") -> int:
        """
        บันทึกเฉพาะรายการที่พ้น cooldown แล้ว
        key = class_name : วัตถุชนิดเดิมที่ค้างอยู่หน้ากล้องจะไม่ถูกบันทึกซ้ำทุกเฟรม
        คืนจำนวนรายการที่บันทึกจริง
        """
        now = time.time()
        saved = 0
        with self._lock:
            for d in detections:
                key = d["class_name"]
                if now - self._last_logged.get(key, 0.0) >= COOLDOWN_SECONDS:
                    self._last_logged[key] = now
                    database.insert_log(d["class_name"], d["category"],
                                        d["confidence"], d["bin_name"], source)
                    saved += 1
        return saved
