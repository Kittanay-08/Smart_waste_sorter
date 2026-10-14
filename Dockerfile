FROM python:3.11-slim

WORKDIR /app

# ติดตั้ง System dependencies สำหรับ OpenCV และประมวลผลกราฟิก
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# ติดตั้ง Python dependencies (PyTorch CPU build ช่วยลดขนาด Image)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "import torchvision.models as models; models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.DEFAULT)"

# คัดลอกโปรเจกต์ทั้งหมด
COPY . .

# กำหนดพอร์ตใช้งาน
EXPOSE 8000
ENV PORT=8000
ENV PYTHONUNBUFFERED=1
ENV YOLO_CONFIG_DIR=/tmp/Ultralytics

CMD ["python", "main.py"]
