# ♻️ Smart Waste Sorter (ระบบตรวจจับและแนะนำการคัดแยกขยะอัจฉริยะ)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Kittanay-08/Smart_waste_sorter)

ระบบตรวจจับขยะและแนะนำการคัดแยกขยะอัจฉริยะแบบเรียลไทม์ (Real-time AI Waste Detection and Smart Sorting Guide System) พัฒนาด้วย **FastAPI** และ **Ultralytics YOLOv8** รองรับทั้งโหมดสตรีมจากกล้องของอุปกรณ์ (Webcam/Mobile Camera) และการอัปโหลดไฟล์ภาพนิ่ง พร้อมระบบป้องกันการนับซ้ำ (Anti-Double Counting) และบันทึกประวัติลงฐานข้อมูล SQLite

---

## 🗑️ มาตรฐานถังขยะ 4 ประเภท (Smart Bin Mapping)
ระบบจำแนกและจับคู่ขยะกับถังขยะตามหลักสุขาภิบาล 4 สี:
1. 🟢 **ถังขยะสีเขียว (ขยะอินทรีย์ / ขยะย่อยสลายได้)**
   - **ประเภทขยะ:** เศษอาหาร, พืชผัก, ผลไม้เน่าเสีย, ใบไม้, กิ่งไม้
   - **การจัดการ:** นำไปทำปุ๋ยหมักหรืออาหารสัตว์ได้
2. 🟡 **ถังขยะสีเหลือง (ขยะรีไซเคิล)**
   - **ประเภทขยะ:** ขวดพลาสติก, แก้ว, กระป๋องอะลูมิเนียม, เศษโลหะ, กล่องกระดาษ, กล่อง UHT, ยาง
   - **การจัดการ:** นำกลับมาแปรรูปใหม่ (ควรล้างคราบและทำให้แห้งก่อนทิ้ง)
3. 🔵 **ถังขยะสีน้ำเงิน หรือสีฟ้า (ขยะทั่วไป)**
   - **ประเภทขยะ:** ซองบะหมี่กึ่งสำเร็จรูป, ถุงพลาสติก, กล่องโฟมเปื้อน, ฟอยล์, เปลือกลูกอม
   - **การจัดการ:** ย่อยสลายยากและไม่คุ้มค่ากับการรีไซเคิล จะถูกนำไปกำจัดอย่างถูกวิธี
4. 🔴 **ถังขยะสีแดง (ขยะอันตราย / ขยะมีพิษ / ขยะติดเชื้อ)**
   - **ประเภทขยะ:** ถ่านไฟฉาย, แบตเตอรี่, หลอดไฟ, กระป๋องสเปรย์, สารเคมี, หน้ากากอนามัย, ชุดตรวจ ATK
   - **การจัดการ:** ต้องแยกทิ้งและปิดฝาให้มิดชิดเพื่อความปลอดภัย

---

## 🚀 ฟังก์ชันการทำงานหลัก (Core Features)
- **Dual-Input Mode:**
  1. *Real-time Stream / In-Browser Camera:* รองรับการเปิดกล้องผ่านเบราว์เซอร์ของมือถือหรือคอมพิวเตอร์พร้อมระบบกลับภาพซ้าย-ขวา (Mirroring) แบบเรียลไทม์ และรองรับ RTSP/MJPEG IP Webcam
  2. *Image Upload:* ลากและวาง (Drag & Drop) ไฟล์ภาพความละเอียดสูงเพื่อตรวจจับแบบละเอียด
- **Anti-Double Counting (Cooldown Stability):**
  - หน่วงเวลา 3 วินาทีสำหรับขยะประเภทเดิม และกรองด้วยค่าความเชื่อมั่น `Confidence >= 0.60`
- **Database Logging:**
  - บันทึก Timestamp, ประเภทขยะ, ค่า Confidence, และถังขยะที่แนะนำลง SQLite อัตโนมัติ

---

## 🐳 วิธีการรันผ่าน Docker (Docker Run)
1. **เปิดด้วย 1-Click บน Windows:**
   - เริ่มทำงาน: ดับเบิลคลิก `DOCKER_START.bat`
   - หยุดทำงาน: ดับเบิลคลิก `DOCKER_STOP.bat`
2. **รันผ่าน Command Line (Docker Compose):**
   ```bash
   # เริ่มระบบและ Build Image
   docker compose up -d --build

   # ดู Log การทำงาน
   docker logs -f smart_waste_sorter

   # หยุดการทำงาน
   docker compose down
   ```
   เปิดใช้งานได้ที่: `http://localhost:8000`

---

## 🛠️ วิธีการรันในเครื่อง (Local Run - ไม่ใช้ Docker)
1. **เปิดด้วย 1-Click:**
   - ดับเบิลคลิกไฟล์ `START.bat`
2. **เปิดผ่าน Terminal (Python 3.10+):**
   ```bash
   pip install -r requirements.txt
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```
   เปิดเบราว์เซอร์ที่: `http://localhost:8000`

---

## ☁️ การนำขึ้น Cloud (Render Deploy)
สามารถกดปุ่ม **Deploy to Render** ด้านบน หรือ:
1. เข้าไปที่ [Render Dashboard](https://dashboard.render.com/)
2. เลือก **New +** -> **Blueprint**
3. เลือก Repository `Smart_waste_sorter`
4. Render จะอ่านการตั้งค่าจาก `render.yaml` และ Deploy ให้ฟรีอัตโนมัติ
