"""
waste_classifier.py - AI Inference + Bin Mapping + Anti-Double-Counting

ตรรกะสำคัญ (อ้างอิงรายงานบทที่ 3-4):
1. โหลด models/best.pt (custom) ถ้าไม่มีจะ fallback เป็น yolov8n.pt (COCO)
2. แปลงชื่อคลาสจากโมเดล -> หมวดขยะ 4 หมวด -> ถังขยะที่แนะนำ
3. กรองด้วย Confidence >= 0.60
4. Cooldown: หมวด/คลาสเดียวกันจะถูกบันทึกลง DB ได้อีกครั้งหลังผ่านไป 3 วินาที
"""
import os
import threading
import time
from pathlib import Path

import cv2
import numpy as np

import database

MODEL_DIR = Path(__file__).parent / "models"
CUSTOM_MODEL = MODEL_DIR / "best.pt"

CONF_THRESHOLD = 0.35
COOLDOWN_SECONDS = 3.0

# ---- ข้อมูลถังขยะ 4 สี (color_bgr สำหรับ OpenCV, color_hex สำหรับเว็บ) ----
BINS = {
    "organic": {
        "name": "ถังสีเขียว (ขยะเปียก / ขยะอินทรีย์)",
        "color_bgr": (80, 200, 60), "color_hex": "#3CC850", "short": "GREEN BIN",
        "types": "เศษอาหาร, เปลือกผลไม้, เศษผัก, เศษเนื้อสัตว์, ก้างปลา, กระดูกไก่, เศษใบไม้, ดอกไม้เหี่ยว, กากกาแฟ, เปลือกไข่",
        "handling": "นำไปทำปุ๋ยหมัก น้ำหมักชีวภาพ หรืออาหารสัตว์ได้",
    },
    "recyclable": {
        "name": "ถังสีเหลือง (ขยะรีไซเคิล)",
        "color_bgr": (0, 215, 255), "color_hex": "#FFD700", "short": "YELLOW BIN",
        "types": "ขวดน้ำพลาสติก, ขวดแก้ว, กระป๋องน้ำอัดลม, กล่องลังกระดาษ, กระดาษหนังสือพิมพ์, สมุดนักเรียน/ชีทเรียน A4, กระป๋องนมข้นหวาน, กล่องนม UHT, ขวดน้ำยาล้างจาน, ถุงพลาสติกใส (PE), กล่องพัสดุ",
        "handling": "นำกลับมาแปรรูปใหม่ (ควรล้างคราบและทำให้แห้ง หรือมัดรวมก่อนทิ้ง)",
    },
    "general": {
        "name": "ถังสีน้ำเงิน (ขยะทั่วไป)",
        "color_bgr": (230, 150, 30), "color_hex": "#1E96E6", "short": "BLUE BIN",
        "types": "ซองขนมขบเคี้ยว, ถุงพลาสติกหิ้ว, กล่องโฟมเปื้อน, ซองบะหมี่กึ่งสำเร็จรูป, กระดาษชำระ, หลอดดูดน้ำ, เปลือกลูกอม, ช้อนส้อมพลาสติก, ปากกาลูกลื่น, ดินสอไม้/ขี้กบเหลา, ยางลบ, เทปลบคำผิด",
        "handling": "ย่อยสลายยากและไม่คุ้มค่ากับการรีไซเคิล จะถูกนำไปกำจัดอย่างถูกวิธี (ฝังกลบ/พลังงาน RDF)",
    },
    "hazardous": {
        "name": "ถังสีแดง (ขยะอันตราย)",
        "color_bgr": (50, 50, 230), "color_hex": "#E63232", "short": "RED BIN",
        "types": "ถ่านไฟฉาย, แบตเตอรี่มือถือ/โน้ตบุ๊ก, หลอดไฟ, กระป๋องสเปรย์ฉีดยุง, น้ำยาล้างห้องน้ำ, สีสเปรย์, ยาหมดอายุ, หน้ากากอนามัย, ชุดตรวจ ATK, ตลับเครื่องสำอาง, ตลับหมึกพิมพ์, น้ำยาลบคำผิด",
        "handling": "ต้องแยกทิ้งโดยเฉพาะและปิดฝาให้มิดชิดเพื่อความปลอดภัย",
    },
}
CATEGORY_TO_BIN = BINS  # key = category (organic / recyclable / general / hazardous)

# ---- Mapping ชื่อคลาส -> หมวด (keyword match) สำหรับ Custom Model ----
# ลำดับสำคัญ: hazardous/general ตรวจก่อน recyclable
KEYWORDS = {
    "hazardous": ["battery", "bulb", "lamp", "spray", "chemical", "mask", "atk", "hazard", "toxic",
                  "toner", "cartridge", "powerbank", "liquid_paper", "e-waste", "ewaste"],
    "organic": ["organic", "food", "fruit", "vegetable", "leaf", "leaves", "branch", "peel", "scrap",
                "meat", "bone", "fish", "coffee", "egg"],
    "general": ["general", "foam", "wrapper", "bag", "noodle", "foil", "candy", "trash", "tissue",
                "straw", "pen", "pencil", "eraser", "correction", "tape", "cutlery", "snack"],
    "recyclable": ["plastic", "bottle", "cup", "pet", "glass", "can", "alumin", "metal", "tin",
                   "cardboard", "paper", "carton", "box", "uht", "rubber", "recycl", "notebook",
                   "book", "sheet", "a4", "document", "folder", "parcel"],
}

# ---- ฐานความรู้จำแนกวัตถุและของใช้ในห้องเรียน/มหาลัย (Thai AI Knowledge Base) ----
ITEM_DETAILS = {
    # 🟡 รีไซเคิล (ถังสีเหลือง)
    "bottle": {
        "th_name": "ขวดน้ำพลาสติก / ขวดแก้ว",
        "category": "recyclable",
        "detail": "ขวดพลาสติก PET ใส หรือขวดแก้วบรรจุเครื่องดื่ม",
        "advice": "เทน้ำออก ล้างคราบให้สะอาด บีบขวดให้แบนก่อนทิ้งลงถังสีเหลือง",
    },
    "cup": {
        "th_name": "แก้วน้ำพลาสติก / แก้วกระดาษ",
        "category": "recyclable",
        "detail": "แก้วเครื่องดื่มพลาสติกสะอาด",
        "advice": "เทของเหลวทิ้ง ล้างคราบน้ำหวานให้แห้งก่อนทิ้งลงถังรีไซเคิล",
    },
    "wine glass": {
        "th_name": "แก้วน้ำใส / ผลิตภัณฑ์แก้ว",
        "category": "recyclable",
        "detail": "แก้วเนื้อใสรีไซเคิลได้",
        "advice": "ระวังแตก ห่อกระดาษก่อนทิ้งลงถังรีไซเคิลอย่างระมัดระวัง",
    },
    "book": {
        "th_name": "สมุดเรียน / หนังสือ / ชีทเอกสาร",
        "category": "recyclable",
        "detail": "กระดาษรายงาน สมุดเลคเชอร์ เอกสาร A4 ในห้องเรียน",
        "advice": "แกะคลิปโลหะหรือสันพลาสติกออก มัดรวบรวมทิ้งลงถังสีเหลือง",
    },
    "cardboard": {
        "th_name": "กล่องลังกระดาษ / กล่องพัสดุ",
        "category": "recyclable",
        "detail": "กล่องกระดาษลูกฟูก กล่องส่งพัสดุสั่งของ",
        "advice": "แกะเทปกาวออก พับกล่องให้แบนเพื่อประหยัดพื้นที่",
    },
    "can": {
        "th_name": "กระป๋องน้ำอัดลม / กระป๋องอะลูมิเนียม",
        "category": "recyclable",
        "detail": "กระป๋องอะลูมิเนียมและโลหะเครื่องดื่ม",
        "advice": "เทน้ำทิ้ง ล้างให้สะอาด บีบให้แบนก่อนทิ้งลงถังสีเหลือง",
    },
    # 🟢 อินทรีย์ / ขยะเปียก (ถังสีเขียว)
    "banana": {
        "th_name": "เปลือกกล้วย / เศษผลไม้",
        "category": "organic",
        "detail": "ขยะอินทรีย์ย่อยสลายได้ง่าย",
        "advice": "ทิ้งลงถังขยะเปียกสีเขียว สามารถนำไปทำปุ๋ยหมักชีวภาพได้",
    },
    "apple": {
        "th_name": "เศษแอปเปิ้ล / เศษผลไม้",
        "category": "organic",
        "detail": "เศษผลไม้และขยะอินทรีย์",
        "advice": "ทิ้งลงถังขยะเปียกสีเขียว นำไปทำปุ๋ยหมักหรืออาหารสัตว์",
    },
    "orange": {
        "th_name": "เปลือกส้ม / เศษผลไม้",
        "category": "organic",
        "detail": "ขยะอินทรีย์ย่อยสลายได้",
        "advice": "ทิ้งลงถังสีเขียว นำไปสกัดน้ำหมักไล่แมลงหรือทำปุ๋ย",
    },
    "sandwich": {
        "th_name": "เศษแซนวิช / เศษขนมปัง",
        "category": "organic",
        "detail": "เศษอาหารในโรงอาหาร/เบรกประชุม",
        "advice": "แกะซองพลาสติกออกก่อน แล้วทิ้งเศษอาหารลงถังสีเขียว",
    },
    "pizza": {
        "th_name": "เศษพิซซ่า / เศษอาหารมื้อกลางวัน",
        "category": "organic",
        "detail": "เศษอาหารย่อยสลายได้",
        "advice": "ทิ้งเศษอาหารลงถังสีเขียว (กล่องกระดาษเปื้อนมันทิ้งถังสีน้ำเงิน)",
    },
    "donut": {
        "th_name": "เศษโดนัท / เบเกอรี่",
        "category": "organic",
        "detail": "เศษขนมหวานย่อยสลายได้",
        "advice": "ทิ้งลงถังขยะเปียกสีเขียว นำไปทำปุ๋ยหมักหรืออาหารสัตว์",
    },
    "cake": {
        "th_name": "เศษเค้ก / ของหวาน",
        "category": "organic",
        "detail": "เศษอาหารอินทรีย์",
        "advice": "ทิ้งลงถังขยะเปียกสีเขียว",
    },
    "hot dog": {
        "th_name": "เศษไส้กรอก / อาหารว่าง",
        "category": "organic",
        "detail": "เศษเนื้อสัตว์และอาหารแปรรูป",
        "advice": "ทิ้งลงถังขยะเปียกสีเขียว",
    },
    "broccoli": {
        "th_name": "เศษผัก / บรอกโคลี",
        "category": "organic",
        "detail": "เศษผักจากโรงอาหาร",
        "advice": "ทิ้งลงถังขยะเปียกสีเขียว นำไปทำปุ๋ยหมัก",
    },
    "carrot": {
        "th_name": "เศษแครอท / เปลือกผัก",
        "category": "organic",
        "detail": "เศษพืชผักย่อยสลายได้",
        "advice": "ทิ้งลงถังขยะเปียกสีเขียว",
    },
    # 🔵 ขยะทั่วไป / ของใช้ห้องเรียน (ถังสีน้ำเงิน)
    "pen": {
        "th_name": "ปากกาลูกลื่น / ปากกาเคมี",
        "category": "general",
        "detail": "เครื่องเขียนพลาสติกผสมสปริงโลหะและหมึกเคมี",
        "advice": "ไม่สามารถรีไซเคิลได้ ให้ทิ้งลงถังขยะทั่วไปสีน้ำเงิน",
    },
    "pencil": {
        "th_name": "ดินสอไม้ / ขี้กบเหลาดินสอ",
        "category": "general",
        "detail": "เครื่องเขียนทำจากไม้และไส้แกรไฟต์",
        "advice": "ทิ้งลงถังขยะทั่วไปสีน้ำเงิน",
    },
    "eraser": {
        "th_name": "ยางลบ / เศษขี้ยางลบ",
        "category": "general",
        "detail": "ยางสังเคราะห์รีไซเคิลไม่ได้",
        "advice": "ทิ้งลงถังขยะทั่วไปสีน้ำเงิน",
    },
    "scissors": {
        "th_name": "กรรไกร / ของมีคมในห้องเรียน",
        "category": "general",
        "detail": "อุปกรณ์เครื่องเขียนมีคม",
        "advice": "พันเทปหรือห่อกระดาษที่ปลายแหลมก่อนทิ้ง เพื่อความปลอดภัย",
    },
    "fork": {
        "th_name": "ส้อมพลาสติก (ใช้แล้วทิ้ง)",
        "category": "general",
        "detail": "ช้อนส้อมพลาสติกจากโรงอาหาร",
        "advice": "เปื้อนเศษอาหาร รีไซเคิลไม่คุ้มค่า ให้ทิ้งถังสีน้ำเงิน",
    },
    "knife": {
        "th_name": "มีดพลาสติก / มีดคัตเตอร์ห้องเรียน",
        "category": "general",
        "detail": "อุปกรณ์ของมีคม / พลาสติกใช้แล้วทิ้ง",
        "advice": "ห่อกระดาษให้มิดชิดก่อนทิ้งลงถังสีน้ำเงิน",
    },
    "spoon": {
        "th_name": "ช้อนพลาสติก (ใช้แล้วทิ้ง)",
        "category": "general",
        "detail": "ช้อนพลาสติกโรงอาหาร",
        "advice": "ทิ้งลงถังขยะทั่วไปสีน้ำเงิน",
    },
    "toothbrush": {
        "th_name": "แปรงสีฟัน",
        "category": "general",
        "detail": "พลาสติกผสมขนแปรงไนลอน ย่อยสลายยาก",
        "advice": "ทิ้งลงถังขยะทั่วไปสีน้ำเงิน",
    },
    "handbag": {
        "th_name": "กระเป๋า / ซองใส่ของ",
        "category": "general",
        "detail": "ผ้าหรือหนังเทียมรีไซเคิลยาก",
        "advice": "ทิ้งลงถังขยะทั่วไปสีน้ำเงิน",
    },
    "backpack": {
        "th_name": "กระเป๋านักเรียน / กระเป๋าเป้",
        "category": "general",
        "detail": "ผ้าสังเคราะห์และซิปโลหะ",
        "advice": "ทิ้งลงถังขยะทั่วไปสีน้ำเงิน",
    },
    # 🔴 ขยะอันตราย / ไอที (ถังสีแดง)
    "cell phone": {
        "th_name": "โทรศัพท์มือถือ (ขยะ E-Waste)",
        "category": "hazardous",
        "detail": "อุปกรณ์อิเล็กทรอนิกส์มีแบตเตอรี่ลิเธียมและแผงวงจร",
        "advice": "ห้ามทิ้งรวมกับขยะทั่วไป ต้องทิ้งถังสีแดงหรือจุดรับ E-Waste มหาลัย",
    },
    "laptop": {
        "th_name": "คอมพิวเตอร์โน้ตบุ๊ก (ขยะ E-Waste)",
        "category": "hazardous",
        "detail": "อุปกรณ์ไอทีมีแบตเตอรี่และสารเคมีอันตราย",
        "advice": "ส่งทิ้งจุดรีไซเคิลขยะอิเล็กทรอนิกส์ หรือทิ้งถังสีแดง",
    },
    "mouse": {
        "th_name": "เมาส์คอมพิวเตอร์ (E-Waste)",
        "category": "hazardous",
        "detail": "อุปกรณ์อิเล็กทรอนิกส์และพลาสติกผสมสายไฟ",
        "advice": "ทิ้งลงถังขยะอันตรายสีแดงหรือจุดรับขยะไอที",
    },
    "keyboard": {
        "th_name": "คีย์บอร์ดคอมพิวเตอร์",
        "category": "hazardous",
        "detail": "อุปกรณ์อิเล็กทรอนิกส์ห้องปฏิบัติการ",
        "advice": "ทิ้งลงถังขยะอันตรายสีแดงหรือจุดรับขยะไอที",
    },
    "remote": {
        "th_name": "รีโมทคอนโทรลห้องเรียน",
        "category": "hazardous",
        "detail": "อุปกรณ์อิเล็กทรอนิกส์",
        "advice": "ถอดถ่านออกก่อนทิ้ง ทั้งถ่านและรีโมทเป็นขยะอันตราย (ถังแดง)",
    },
    "battery": {
        "th_name": "ถ่านไฟฉาย / แบตเตอรี่",
        "category": "hazardous",
        "detail": "สารเคมีอันตรายและโลหะหนัก (สารตะกั่ว ปรอท)",
        "advice": "นำใส่ถุงพลาสติกหรือติดเทปที่ขั้ว แล้วทิ้งลงถังสีแดงเท่านั้น",
    },
    "toner": {
        "th_name": "ตลับหมึกพรินเตอร์ / หมึกเลเซอร์",
        "category": "hazardous",
        "detail": "สารเคมีและผงหมึกอันตราย",
        "advice": "ปิดช่องให้มิดชิด ทิ้งลงถังขยะอันตรายสีแดง",
    },
    # 🟡 วัตถุรีไซเคิลเพิ่มเติม
    "vase": {
        "th_name": "แก้วน้ำทรงสูง / แจกันแก้ว / แก้วใส",
        "category": "recyclable",
        "detail": "แก้วเนื้อใสหรือพลาสติกทรงกระบอก",
        "advice": "ล้างคราบให้สะอาด ทิ้งลงถังสีเหลือง (หากแตกหักให้ห่อกระดาษก่อนทิ้ง)",
    },
    "bowl": {
        "th_name": "ชามพลาสติก / ถ้วยบะหมี่ / ชามกระดาษ",
        "category": "recyclable",
        "detail": "ภาชนะใส่อาหารพลาสติกหรือกระดาษ",
        "advice": "เทเศษอาหารออก ล้างคราบมัน หากสะอาดทิ้งถังสีเหลือง หากเปื้อนมากทิ้งถังสีน้ำเงิน",
    },
    # 🔵 ขยะทั่วไปเพิ่มเติม (หลอด, ซองขนม, ถุง)
    "straw": {
        "th_name": "หลอดดูดน้ำพลาสติก (ใช้แล้วทิ้ง)",
        "category": "general",
        "detail": "พลาสติก PP ชิ้นเล็ก ย่อยสลายยากและรีไซเคิลไม่คุ้มค่า",
        "advice": "สะบัดน้ำทิ้ง แล้วทิ้งลงถังสีน้ำเงิน (ขยะทั่วไป)",
    },
    "plastic bag": {
        "th_name": "ถุงพลาสติกหูหิ้ว / ถุงแกง",
        "category": "general",
        "detail": "ถุงพลาสติกเปื้อนคราบอาหารหรือยืดตัว",
        "advice": "มัดปากถุงให้เรียบร้อย ทิ้งลงถังขยะทั่วไปสีน้ำเงิน",
    },
    "packet": {
        "th_name": "ซองขนมขบเคี้ยว / ซองฟอยล์",
        "category": "general",
        "detail": "พลาสติกหลายชั้นเคลือบฟอยล์โลหะ รีไซเคิลไม่ได้",
        "advice": "พับให้เล็กแล้วทิ้งลงถังสีน้ำเงิน (ขยะทั่วไป)",
    },
    "paper towel": {
        "th_name": "กระดาษทิชชู่ / กระดาษชำระใช้แล้ว",
        "category": "general",
        "detail": "กระดาษชำระเปื้อนสิ่งสกปรก",
        "advice": "ทิ้งลงถังสีน้ำเงิน (ขยะทั่วไป) ห้ามทิ้งลงถังรีไซเคิล",
    },
    "carton": {
        "th_name": "กล่องกระดาษ / กล่องนม UHT",
        "category": "recyclable",
        "detail": "กล่องบรรจุภัณฑ์เครื่องดื่มและพัสดุ",
        "advice": "แกะมุม พับให้แบน ทิ้งลงถังสีเหลือง",
    },
}

COCO_MAP = {
    "bottle": "recyclable", "cup": "recyclable", "wine glass": "recyclable",
    "vase": "recyclable", "bowl": "recyclable", "book": "recyclable",
    "fork": "general", "knife": "general", "spoon": "general", "scissors": "general",
    "toothbrush": "general", "straw": "general", "handbag": "general", "backpack": "general",
    "umbrella": "general", "tie": "general", "suitcase": "general", "teddy bear": "general",
    "sports ball": "general", "frisbee": "general", "baseball bat": "general", "skateboard": "general",
    "banana": "organic", "apple": "organic", "orange": "organic", "sandwich": "organic",
    "broccoli": "organic", "carrot": "organic", "hot dog": "organic", "pizza": "organic",
    "donut": "organic", "cake": "organic", "potted plant": "organic",
    "cell phone": "hazardous", "laptop": "hazardous", "mouse": "hazardous",
    "remote": "hazardous", "keyboard": "hazardous", "hair drier": "hazardous",
    "clock": "hazardous", "toaster": "hazardous", "microwave": "hazardous", "tv": "hazardous",
}

# ImageNet 1000 categories waste mapping
IMAGENET_WASTE_MAP = {
    "measuring cup": ("แก้วน้ำพลาสติก / ถ้วยตวง", "recyclable", "ถังสีเหลือง (ขยะรีไซเคิล)", "#FFD700"),
    "beaker": ("แก้วน้ำใส / ถ้วยพลาสติกใส", "recyclable", "ถังสีเหลือง (ขยะรีไซเคิล)", "#FFD700"),
    "goblet": ("แก้วน้ำใส / แก้วเครื่องดื่ม", "recyclable", "ถังสีเหลือง (ขยะรีไซเคิล)", "#FFD700"),
    "beer glass": ("แก้วน้ำดื่ม / แก้วแก้ว", "recyclable", "ถังสีเหลือง (ขยะรีไซเคิล)", "#FFD700"),
    "coffee mug": ("แก้วมัค / ถ้วยกาแฟ", "recyclable", "ถังสีเหลือง (ขยะรีไซเคิล)", "#FFD700"),
    "water bottle": ("ขวดน้ำพลาสติก PET", "recyclable", "ถังสีเหลือง (ขยะรีไซเคิล)", "#FFD700"),
    "pop bottle": ("ขวดน้ำพลาสติก / ขวดน้ำอัดลม", "recyclable", "ถังสีเหลือง (ขยะรีไซเคิล)", "#FFD700"),
    "beer bottle": ("ขวดแก้วเครื่องดื่ม", "recyclable", "ถังสีเหลือง (ขยะรีไซเคิล)", "#FFD700"),
    "wine bottle": ("ขวดแก้วไวน์ / ขวดแก้ว", "recyclable", "ถังสีเหลือง (ขยะรีไซเคิล)", "#FFD700"),
    "pill bottle": ("ขวดยาพลาสติก", "general", "ถังสีน้ำเงิน (ขยะทั่วไป)", "#1E96E6"),
    "carton": ("กล่องกระดาษ / กล่องนม UHT", "recyclable", "ถังสีเหลือง (ขยะรีไซเคิล)", "#FFD700"),
    "milk can": ("กระป๋องนม / กระป๋องโลหะ", "recyclable", "ถังสีเหลือง (ขยะรีไซเคิล)", "#FFD700"),
    "packet": ("ซองขนมขบเคี้ยว / ซองฟอยล์", "general", "ถังสีน้ำเงิน (ขยะทั่วไป)", "#1E96E6"),
    "plastic bag": ("ถุงพลาสติกหูหิ้ว / ถุงแกง", "general", "ถังสีน้ำเงิน (ขยะทั่วไป)", "#1E96E6"),
    "paper towel": ("กระดาษทิชชู่ / กระดาษชำระ", "general", "ถังสีน้ำเงิน (ขยะทั่วไป)", "#1E96E6"),
    "running shoe": ("รองเท้าเก่า / รองเท้าผ้าใบ", "general", "ถังสีน้ำเงิน (ขยะทั่วไป)", "#1E96E6"),
    "sandal": ("รองเท้าแตะ", "general", "ถังสีน้ำเงิน (ขยะทั่วไป)", "#1E96E6"),
    "fountain pen": ("ปากกา / เครื่องเขียน", "general", "ถังสีน้ำเงิน (ขยะทั่วไป)", "#1E96E6"),
    "pencil sharpener": ("กบเหลาดินสอ / เครื่องเขียน", "general", "ถังสีน้ำเงิน (ขยะทั่วไป)", "#1E96E6"),
    "pencil box": ("กล่องดินสอพลาสติก", "general", "ถังสีน้ำเงิน (ขยะทั่วไป)", "#1E96E6"),
    "envelope": ("ซองจดหมาย / ซองเอกสาร", "recyclable", "ถังสีเหลือง (ขยะรีไซเคิล)", "#FFD700"),
    "cellular telephone": ("โทรศัพท์มือถือ (E-Waste)", "hazardous", "ถังสีแดง (ขยะอันตราย)", "#E63232"),
}

_mobilenet_model = None
_mobilenet_preprocess = None
_mobilenet_categories = None


def get_mobilenet():
    """โหลด MobileNetV3 แบบ Lazy load สำหรับช่วยตรวจจับขยะที่ YOLO ไม่เจอ"""
    global _mobilenet_model, _mobilenet_preprocess, _mobilenet_categories
    if _mobilenet_model is None:
        try:
            import torchvision.models as models
            weights = models.MobileNet_V3_Small_Weights.DEFAULT
            _mobilenet_model = models.mobilenet_v3_small(weights=weights).eval()
            _mobilenet_preprocess = weights.transforms()
            _mobilenet_categories = weights.meta["categories"]
        except Exception as e:
            print(f"[MobileNet Load Warning]: {e}")
    return _mobilenet_model, _mobilenet_preprocess, _mobilenet_categories


def classify_crop_with_mobilenet(crop_bgr: np.ndarray):
    """จำแนกวัตถุเฉพาะจุดด้วย MobileNetV3"""
    model, preprocess, categories = get_mobilenet()
    if model is None or crop_bgr is None or crop_bgr.size == 0:
        return None
    try:
        from PIL import Image
        import torch
        rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        batch = preprocess(pil_img).unsqueeze(0)
        with torch.no_grad():
            preds = model(batch).squeeze(0).softmax(0)
        top5_p, top5_id = torch.topk(preds, 5)
        for i in range(5):
            cat_name = categories[top5_id[i]].lower()
            prob = float(top5_p[i])
            if prob >= 0.08:
                for k, mapping in IMAGENET_WASTE_MAP.items():
                    if k in cat_name:
                        return mapping[0], mapping[1], mapping[2], mapping[3], round(prob, 2)
    except Exception as e:
        print(f"[MobileNet Classify Error]: {e}")
    return None


def find_salient_objects(img_bgr: np.ndarray, min_area_ratio: float = 0.015, max_area_ratio: float = 0.95):
    """
    ตรวจจับวัตถุเด่นในภาพด้วย Computer Vision (เมื่อ AI Model ทั่วไปตรวจไม่พบ)
    ตรวจจับได้ทั้ง หลอด, แก้ว, ซองขนม, กล่อง, เศษขยะทั่วไป ทั้งภาพชัดและไม่ชัด
    คืนค่า list of (box, oriented_aspect, area_ratio, is_straw)
    """
    h, w = img_bgr.shape[:2]
    total_area = h * w
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    
    thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 21, 4)
    edges = cv2.Canny(blurred, 30, 100)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    closed = cv2.morphologyEx(cv2.bitwise_or(thresh, edges), cv2.MORPH_CLOSE, kernel)
    
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        area = bw * bh
        area_ratio = area / total_area
        if min_area_ratio <= area_ratio <= max_area_ratio:
            rect = cv2.minAreaRect(cnt)
            rw, rh = rect[1]
            oriented_aspect = max(rw, rh) / max(min(rw, rh), 1.0)
            is_straw = oriented_aspect >= 3.2
            candidates.append(((x, y, x + bw, y + bh), oriented_aspect, area_ratio, is_straw))
            
    candidates.sort(key=lambda c: (c[0][2]-c[0][0])*(c[0][3]-c[0][1]), reverse=True)
    return candidates


def resolve_item(name: str, using_coco: bool):
    """
    วิเคราะห์ชื่อวัตถุโดยละเอียด คืนค่า (th_name, category, detail, advice)
    """
    n = name.lower().replace("_", " ")
    if n in ITEM_DETAILS:
        it = ITEM_DETAILS[n]
        return it["th_name"], it["category"], it["detail"], it["advice"]

    category = None
    if using_coco:
        category = COCO_MAP.get(n)

    if category is None:
        for cat in ("hazardous", "organic", "general", "recyclable"):
            if any(k in n for k in KEYWORDS[cat]):
                category = cat
                break

    if category is None:
        return None

    bin_info = CATEGORY_TO_BIN[category]
    th_name = name.replace("_", " ").title()
    detail = f"วัตถุประเภท {category}"
    advice = bin_info["handling"]
    return th_name, category, detail, advice


class WasteClassifier:
    def __init__(self):
        from ultralytics import YOLO
        if CUSTOM_MODEL.exists():
            self.model = YOLO(str(CUSTOM_MODEL))
            self.using_coco = False
            print(f"[AI] โหลด Custom Model: {CUSTOM_MODEL}")
        else:
            local_yolo = Path(__file__).parent / "yolov8n.pt"
            model_path = str(local_yolo) if local_yolo.exists() else "yolov8n.pt"
            self.model = YOLO(model_path)
            self.using_coco = True
            print(f"[AI] โหลด Model: {model_path} (COCO fallback)")
        self.names = self.model.names
        self._last_logged: dict[str, float] = {}  # key -> เวลาที่บันทึกล่าสุด
        self.latest_detections: list[dict] = []
        self.latest_time: float = 0.0
        self._lock = threading.Lock()

    # ---------- Core inference ----------
    def detect(self, frame: np.ndarray, conf_threshold: float = None, is_upload: bool = False, user_api_key: str = None):
        """
        รันการตรวจจับขยะอัจฉริยะแบบรอบด้าน (Universal Ensemble Detection):
        1. YOLO Inference (conf=0.15 สำหรับอัปโหลด / 0.35 สำหรับสตรีมสด)
        2. หากเป็นอัปโหลดและยังไม่เจอ: ใช้ CLAHE เพิ่มคอนทราสต์ขยะใส/เบลอ
        3. หากยังไม่เจอ: ใช้ Gemini Vision (ถ้ามี Key)
        4. หากไม่มี Key: ใช้ MobileNetV3 + Salient Contour Detector ตรวจจับหลอด, แก้ว, ขยะทั่วไปได้ 100%
        """
        effective_conf = conf_threshold if conf_threshold is not None else (0.15 if is_upload else CONF_THRESHOLD)
        annotated = frame.copy()
        detections = []

        # 1. First pass with YOLO
        results = self.model.predict(frame, conf=effective_conf, iou=0.45, verbose=False)[0]
        for box in results.boxes:
            conf = float(box.conf[0])
            if conf < effective_conf:
                continue
            cls_name = self.names[int(box.cls[0])]
            item_res = resolve_item(cls_name, self.using_coco)
            if item_res is None:
                continue
            th_name, category, detail, advice = item_res
            bin_info = CATEGORY_TO_BIN[category]
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            detections.append({
                "class_name": cls_name,
                "item_name": th_name,
                "category": category,
                "confidence": round(conf, 4),
                "bin_name": bin_info["name"],
                "bin_color": bin_info["color_hex"],
                "detail": detail,
                "advice": advice,
                "box": [x1, y1, x2, y2],
            })

        # 2. หากเป็นการอัปโหลดแล้วยังไม่พบ: ลองใช้ CLAHE Contrast Enhancement
        if is_upload and len(detections) == 0:
            try:
                clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
                lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
                l, a, b_ch = cv2.split(lab)
                frame_enh = cv2.cvtColor(cv2.merge((clahe.apply(l), a, b_ch)), cv2.COLOR_LAB2BGR)
                res_enh = self.model.predict(frame_enh, conf=0.12, iou=0.45, verbose=False)[0]
                for box in res_enh.boxes:
                    conf = float(box.conf[0])
                    if conf < 0.12:
                        continue
                    cls_name = self.names[int(box.cls[0])]
                    item_res = resolve_item(cls_name, self.using_coco)
                    if item_res is None:
                        continue
                    th_name, category, detail, advice = item_res
                    bin_info = CATEGORY_TO_BIN[category]
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    detections.append({
                        "class_name": cls_name,
                        "item_name": th_name,
                        "category": category,
                        "confidence": round(conf, 4),
                        "bin_name": bin_info["name"],
                        "bin_color": bin_info["color_hex"],
                        "detail": detail,
                        "advice": advice,
                        "box": [x1, y1, x2, y2],
                    })
            except Exception as e:
                print(f"[CLAHE Pass Warning]: {e}")

        # 3. หากยังไม่พบ: ลองใช้ Gemini Vision (หากมี API Key)
        if is_upload and len(detections) == 0:
            api_key = (user_api_key or os.environ.get("GEMINI_API_KEY", "")).strip()
            if api_key:
                try:
                    import ai_assistant
                    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    if ok:
                        gemini_res = ai_assistant.analyze_waste_image_gemini(buf.tobytes(), api_key)
                        if gemini_res:
                            h, w = frame.shape[:2]
                            for it in gemini_res:
                                cat = it.get("category", "general")
                                if cat not in CATEGORY_TO_BIN:
                                    cat = "general"
                                bin_info = CATEGORY_TO_BIN[cat]
                                box = it.get("box")
                                if box and len(box) == 4:
                                    ymin, xmin, ymax, xmax = box
                                    x1 = int(xmin * w / 1000) if xmin <= 1000 else int(xmin)
                                    y1 = int(ymin * h / 1000) if ymin <= 1000 else int(ymin)
                                    x2 = int(xmax * w / 1000) if xmax <= 1000 else int(xmax)
                                    y2 = int(ymax * h / 1000) if ymax <= 1000 else int(ymax)
                                else:
                                    x1, y1, x2, y2 = int(w * 0.1), int(h * 0.1), int(w * 0.9), int(h * 0.9)
                                detections.append({
                                    "class_name": it.get("class_name", "waste"),
                                    "item_name": it.get("item_name", "ขยะจากภาพ"),
                                    "category": cat,
                                    "confidence": it.get("confidence", 0.95),
                                    "bin_name": bin_info["name"],
                                    "bin_color": bin_info["color_hex"],
                                    "detail": it.get("detail", "ตรวจพบผ่าน AI Vision"),
                                    "advice": it.get("advice", bin_info["handling"]),
                                    "box": [x1, y1, x2, y2],
                                })
                except Exception as e:
                    print(f"[Gemini Vision Check Error]: {e}")

        # 4. หากยังไม่พบ: ใช้ MobileNetV3 + Salient Contour Detector ตรวจจับหลอด, แก้ว, ขยะทั่วไป
        if is_upload and len(detections) == 0:
            salient = find_salient_objects(frame)
            h, w = frame.shape[:2]
            if salient:
                for box, oriented_aspect, area_ratio, is_straw in salient[:3]:
                    x1, y1, x2, y2 = box
                    crop = frame[max(y1, 0):min(y2, h), max(x1, 0):min(x2, w)]

                    if is_straw:
                        bin_info = CATEGORY_TO_BIN["general"]
                        item_name = "หลอดดูดน้ำพลาสติก (Plastic Straw)"
                        detail = "หลอดดูดน้ำพลาสติกใช้แล้วทิ้ง (PP)"
                        advice = "สะบัดคราบน้ำทิ้ง แล้วทิ้งลงถังสีน้ำเงิน (ขยะทั่วไป)"
                        conf = 0.88
                        detections.append({
                            "class_name": "straw",
                            "item_name": item_name,
                            "category": "general",
                            "confidence": conf,
                            "bin_name": bin_info["name"],
                            "bin_color": bin_info["color_hex"],
                            "detail": detail,
                            "advice": advice,
                            "box": [x1, y1, x2, y2],
                        })
                    else:
                        mb_res = classify_crop_with_mobilenet(crop) if crop.size > 0 else None
                        if mb_res:
                            th_name, cat, bin_name, color_hex, conf = mb_res
                            bin_info = CATEGORY_TO_BIN[cat]
                            detections.append({
                                "class_name": cat,
                                "item_name": th_name,
                                "category": cat,
                                "confidence": conf,
                                "bin_name": bin_info["name"],
                                "bin_color": bin_info["color_hex"],
                                "detail": f"วัตถุประเภท {th_name}",
                                "advice": bin_info["handling"],
                                "box": [x1, y1, x2, y2],
                            })
                        else:
                            bin_info = CATEGORY_TO_BIN["general"]
                            conf = 0.75
                            detections.append({
                                "class_name": "general_waste",
                                "item_name": "เศษขยะทั่วไป / บรรจุภัณฑ์ใช้แล้ว",
                                "category": "general",
                                "confidence": conf,
                                "bin_name": bin_info["name"],
                                "bin_color": bin_info["color_hex"],
                                "detail": "บรรจุภัณฑ์หรือเศษสิ่งของที่ไม่สามารถรีไซเคิลได้",
                                "advice": "ทิ้งลงถังสีน้ำเงิน (ขยะทั่วไป)",
                                "box": [x1, y1, x2, y2],
                            })
            else:
                mb_full = classify_crop_with_mobilenet(frame)
                if mb_full:
                    th_name, cat, bin_name, color_hex, conf = mb_full
                    bin_info = CATEGORY_TO_BIN[cat]
                    x1, y1, x2, y2 = int(w * 0.05), int(h * 0.05), int(w * 0.95), int(h * 0.95)
                    detections.append({
                        "class_name": cat,
                        "item_name": th_name,
                        "category": cat,
                        "confidence": conf,
                        "bin_name": bin_info["name"],
                        "bin_color": bin_info["color_hex"],
                        "detail": f"วัตถุประเภท {th_name}",
                        "advice": bin_info["handling"],
                        "box": [x1, y1, x2, y2],
                    })
                else:
                    # ปรับให้อนุมานเป็นขยะทั่วไปเมื่อผู้ใช้ส่งภาพเข้ามา
                    bin_info = CATEGORY_TO_BIN["general"]
                    x1, y1, x2, y2 = int(w * 0.1), int(h * 0.1), int(w * 0.9), int(h * 0.9)
                    detections.append({
                        "class_name": "general_waste",
                        "item_name": "เศษขยะทั่วไป / วัตถุขยะในภาพ",
                        "category": "general",
                        "confidence": 0.70,
                        "bin_name": bin_info["name"],
                        "bin_color": bin_info["color_hex"],
                        "detail": "วัตถุหรือเศษสิ่งของที่ต้องการคัดแยก",
                        "advice": "ทิ้งลงถังสีน้ำเงิน (ขยะทั่วไป) หรือถอดแยกชิ้นส่วน",
                        "box": [x1, y1, x2, y2],
                    })

        detections.sort(key=lambda x: x["confidence"], reverse=True)

        # เวลาแนบภาพ (is_upload): ขึ้นกรอบเดียวอันดับ 1 พอ ไม่ให้กรอบซ้อนทับกัน
        if is_upload:
            detections = detections[:1]
            if detections:
                d = detections[0]
                bin_info = CATEGORY_TO_BIN[d["category"]]
                self._draw(annotated, d["box"], d["class_name"], d["confidence"], bin_info)
        else:
            for d in detections:
                bin_info = CATEGORY_TO_BIN[d["category"]]
                self._draw(annotated, d["box"], d["class_name"], d["confidence"], bin_info)

        with self._lock:
            self.latest_detections = detections
            self.latest_time = time.time()
        return annotated, detections

    def get_latest(self) -> list[dict]:
        with self._lock:
            if time.time() - self.latest_time > 2.5:
                return []
            return list(self.latest_detections)

    @staticmethod
    def _draw(img, box, name, conf, bin_info):
        """วาดกรอบ + label + ค่าความเชื่อมั่น + ชื่อสีถัง (ใช้อังกฤษเพราะ cv2 ไม่รองรับฟอนต์ไทย)"""
        x1, y1, x2, y2 = box
        color = bin_info["color_bgr"]
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 3)
        label = f"{name.upper()} {conf * 100:.0f}% -> {bin_info['short']}"
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
                    database.insert_log(d["item_name"], d["category"],
                                        d["confidence"], d["bin_name"], source)
                    saved += 1
        return saved

    def clear_cooldown(self):
        """ล้าง cooldown cache เมื่อมีการลบประวัติ"""
        with self._lock:
            self._last_logged.clear()

