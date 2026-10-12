"""
main.py - FastAPI Web Server

Endpoints:
  GET  /               หน้าเว็บ Dashboard
  GET  /video_feed     MJPEG stream (webcam / IP camera)
  POST /camera/source  ตั้งค่าแหล่งกล้อง (ดัชนี เช่น "0" หรือ URL)
  POST /camera/stop    หยุดกล้อง
  POST /predict-image  อัปโหลดภาพนิ่ง -> JSON + Base64 annotated image
  GET  /history        ประวัติการตรวจจับ
  GET  /summary        สรุปจำนวนตามหมวด

รัน:  uvicorn main:app --host 0.0.0.0 --port 8000
"""
import base64
import io
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageOps
from pydantic import BaseModel

import database
from waste_classifier import WasteClassifier

BASE = Path(__file__).parent
classifier: WasteClassifier | None = None


class CameraManager:
    """
    จัดการกล้องตัวเดียวแบบ thread-safe
    - เปิดกล้องตามที่ผู้ใช้เลือก (index หรือ URL)
    - เมื่อ client หลายคนดู stream พร้อมกัน จะใช้กล้องร่วมกันได้
    """
    def __init__(self):
        self.cap: cv2.VideoCapture | None = None
        self.source: str | int | None = None
        self.lock = threading.Lock()
        self.generation = 0  # เปลี่ยนค่าเมื่อเปลี่ยน/หยุดกล้อง เพื่อให้ stream เก่าจบการทำงาน

    def set_source(self, src: str):
        src = src.strip()
        parsed = int(src) if src.isdigit() else src  # "0" -> webcam index, อื่นๆ -> URL
        with self.lock:
            self._release()
            cap = cv2.VideoCapture(parsed, cv2.CAP_DSHOW) if isinstance(parsed, int) and hasattr(cv2, "CAP_DSHOW") and _is_windows() \
                else cv2.VideoCapture(parsed)
            if not cap.isOpened():
                cap.release()
                raise RuntimeError(f"ไม่สามารถเปิดกล้อง: {src}")
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.cap, self.source = cap, parsed
            self.generation += 1

    def read(self):
        with self.lock:
            if self.cap is None:
                return None
            ok, frame = self.cap.read()
            return frame if ok else None

    def stop(self):
        with self.lock:
            self._release()
            self.generation += 1

    def _release(self):
        if self.cap is not None:
            self.cap.release()
        self.cap, self.source = None, None


def _is_windows() -> bool:
    import os
    return os.name == "nt"


camera = CameraManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global classifier
    database.init_db()
    classifier = WasteClassifier()
    yield
    camera.stop()


app = FastAPI(title="Smart Waste Sorter", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE / "templates"))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


# ---------------- Mode 1: Real-time stream ----------------
class SourceBody(BaseModel):
    source: str = "0"


@app.post("/camera/source")
def set_camera(body: SourceBody):
    try:
        camera.set_source(body.source)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "source": str(camera.source)}


@app.post("/camera/stop")
def stop_camera():
    camera.stop()
    return {"status": "stopped"}


def mjpeg_generator():
    """
    วนอ่านเฟรม -> YOLO -> วาดกรอบ -> log (ผ่าน cooldown) -> encode JPEG -> yield
    รูปแบบ multipart/x-mixed-replace ทำให้ <img src="/video_feed"> แสดงวิดีโอได้โดยตรง
    """
    gen = camera.generation
    while gen == camera.generation:
        frame = camera.read()
        if frame is None:
            if camera.cap is None:
                break
            time.sleep(0.05)
            continue
        # Webcam ในเครื่อง (source เป็นตัวเลข) -> พลิกซ้าย/ขวาให้เป็นภาพกระจก เลื่อนมือไปทางไหนภาพไปทางนั้น
        # พลิก "ก่อน" ตรวจจับ เพื่อให้ข้อความบนกรอบไม่กลับด้าน; กล้องมือถือ/IP ไม่พลิก
        if isinstance(camera.source, int):
            frame = cv2.flip(frame, 1)
        annotated, dets = classifier.detect(frame)
        if dets:
            classifier.log_with_cooldown(dets, source="stream")
        ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            continue
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"


@app.get("/video_feed")
def video_feed():
    if camera.cap is None:
        raise HTTPException(status_code=409, detail="ยังไม่ได้เลือกกล้อง (POST /camera/source)")
    return StreamingResponse(mjpeg_generator(),
                             media_type="multipart/x-mixed-replace; boundary=frame")


# ---------------- Mode 2: Image upload ----------------
@app.post("/predict-image")
async def predict_image(file: UploadFile = File(...)):
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(status_code=400, detail="รองรับเฉพาะไฟล์ .jpg / .png")
    data = await file.read()
    try:
        # exif_transpose แก้ภาพจากมือถือที่หมุนผิดทิศ
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="ไฟล์ภาพไม่ถูกต้อง")
    frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

    annotated, dets = classifier.detect(frame)
    # ภาพนิ่งแต่ละครั้งเป็นการอัปโหลดแยกกัน -> บันทึกทุกรายการ ไม่ใช้ cooldown
    for d in dets:
        database.insert_log(d["class_name"], d["category"], d["confidence"], d["bin_name"], "upload")

    ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 90])
    b64 = base64.b64encode(buf.tobytes()).decode()
    return {
        "count": len(dets),
        "detections": dets,
        "annotated_image": f"data:image/jpeg;base64,{b64}",
        "model": "custom best.pt" if not classifier.using_coco else "yolov8n.pt (fallback)",
    }


# ---------------- Mode 1b: Browser camera (ใช้บน Render/คลาวด์) ----------------
@app.post("/predict-frame")
async def predict_frame(file: UploadFile = File(...)):
    """
    เบราว์เซอร์เปิดกล้องผู้ใช้เอง (getUserMedia) แล้วส่งเฟรม JPEG มาทีละภาพ
    ใช้ Cooldown เหมือนโหมดสตรีม เพื่อไม่ให้บันทึกขยะชิ้นเดิมซ้ำทุกเฟรม
    """
    data = await file.read()
    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="เฟรมภาพไม่ถูกต้อง")
    annotated, dets = classifier.detect(frame)
    if dets:
        classifier.log_with_cooldown(dets, source="camera")
    ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 75])
    return {
        "count": len(dets),
        "detections": dets,
        "annotated_image": "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode(),
    }


# ---------------- History ----------------
@app.get("/history")
def history(limit: int = 50):
    return {"items": database.get_history(max(1, min(limit, 500)))}


@app.get("/summary")
def summary():
    return database.get_summary()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/bins")
def bins():
    """ข้อมูลถังขยะ 4 สี (ประเภทขยะและวิธีจัดการ) สำหรับแสดงบนหน้าเว็บ"""
    from waste_classifier import BINS
    return {k: {f: v[f] for f in ("name", "color_hex", "types", "handling")} | {"key": k}
            for k, v in BINS.items()}


if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    print(f"[Server] กำลังเริ่มทำงานบนพอร์ต: {port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, workers=1)
