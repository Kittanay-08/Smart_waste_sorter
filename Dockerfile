FROM python:3.11-slim

WORKDIR /app

# ติดตั้ง dependencies สำหรับ OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hugging Face Spaces และ Cloud ทั่วไป
EXPOSE 7860
ENV PORT=7860

CMD ["python", "main.py"]
