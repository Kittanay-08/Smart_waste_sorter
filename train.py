"""
train.py - ฝึกสอน YOLOv8 บน Custom Dataset และบันทึก Metrics

ใช้งาน:
    python train.py --epochs 100 --imgsz 640 --batch 16
ผลลัพธ์: models/best.pt และ models/metrics.json (mAP50, mAP50-95, Precision, Recall)
"""
import argparse
import json
import shutil
from pathlib import Path

from ultralytics import YOLO

BASE = Path(__file__).parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(BASE / "dataset" / "data.yaml"))
    ap.add_argument("--base", default="yolov8n.pt", help="pretrained weight เริ่มต้น (Transfer Learning)")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=16)
    args = ap.parse_args()

    model = YOLO(args.base)
    # Transfer learning: ใช้ weight COCO แล้ว fine-tune กับ dataset ขยะ
    model.train(data=args.data, epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
                project=str(BASE / "runs"), name="waste", exist_ok=True,
                patience=20, augment=True)

    best = BASE / "runs" / "waste" / "weights" / "best.pt"
    (BASE / "models").mkdir(exist_ok=True)
    shutil.copy(best, BASE / "models" / "best.pt")

    # ประเมินบน validation set -> metrics ใช้ในรายงานบทที่ 4
    best_model = YOLO(str(best))
    m = best_model.val(data=args.data)
    metrics = {
        "precision": float(m.box.mp),
        "recall": float(m.box.mr),
        "mAP50": float(m.box.map50),
        "mAP50-95": float(m.box.map),
        "per_class_mAP50-95": {best_model.names[i]: float(v) for i, v in enumerate(m.box.maps)},
    }
    (BASE / "models" / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
