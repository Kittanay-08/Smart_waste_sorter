// app.js - ระบบควบคุมอัจฉริยะ: AR Tracking กรอบติดตามวัตถุแบบเรียลไทม์ 60FPS, เสียงพูดภาษาไทยนุ่มนวล, และ AI ถาม-ตอบ
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const CAT_LABEL = { organic: "อินทรีย์", recyclable: "รีไซเคิล", general: "ทั่วไป", hazardous: "อันตราย" };
const binColor = (name) => (name.includes("เขียว") ? "#3CC850" : name.includes("เหลือง") ? "#FFD700" : name.includes("แดง") ? "#E63232" : "#1E96E6");

// ---------- ระบบเปลี่ยนธีม (Dark / Light Theme Switcher) ----------
const THEME_KEY = "smart_waste_theme";

function applyTheme(theme) {
  const isLight = theme === "light";
  document.documentElement.setAttribute("data-bs-theme", isLight ? "light" : "dark");
  document.documentElement.classList.toggle("light-theme", isLight);
  
  const icon = isLight ? "☀️" : "🌙";
  const label = isLight ? "ธีมสว่าง" : "ธีมมืด";
  
  const iconEl = $("theme-icon");
  const labelEl = $("theme-label");
  if (iconEl) iconEl.textContent = icon;
  if (labelEl) labelEl.textContent = label;

  const iconDrawerEl = $("theme-icon-drawer");
  const labelDrawerEl = $("theme-label-drawer");
  if (iconDrawerEl) iconDrawerEl.textContent = icon;
  if (labelDrawerEl) labelDrawerEl.textContent = label;
  
  localStorage.setItem(THEME_KEY, theme);
}

function initTheme() {
  const saved = localStorage.getItem(THEME_KEY) || "dark";
  applyTheme(saved);
  
  const toggleBtn = $("btn-theme-toggle");
  if (toggleBtn) {
    toggleBtn.onclick = () => {
      const current = document.documentElement.getAttribute("data-bs-theme") || "dark";
      applyTheme(current === "dark" ? "light" : "dark");
    };
  }

  const toggleDrawerBtn = $("btn-theme-toggle-drawer");
  if (toggleDrawerBtn) {
    toggleDrawerBtn.onclick = () => {
      const current = document.documentElement.getAttribute("data-bs-theme") || "dark";
      applyTheme(current === "dark" ? "light" : "dark");
    };
  }
}
initTheme();

let currentLiveItem = ""; // เก็บชื่อขยะที่สแกนพบล่าสุด

// ---------- สลับโหมด (กล้องสด vs อัปโหลด) ----------
document.querySelectorAll("#modeTabs .nav-link").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll("#modeTabs .nav-link").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const live = btn.dataset.mode === "live";
    $("live-panel").classList.toggle("d-none", !live);
    $("upload-panel").classList.toggle("d-none", live);
    if (!live) stopStream();
  };
});

// ---------- ฟังก์ชันสร้างการ์ดข้อมูลที่ AI ประมวลผล ----------
function renderAICardHTML(d) {
  const itemTitle = esc(d.item_name || d.class_name);
  const rawClass = esc(d.class_name || "");
  const binName = esc(d.bin_name || "");
  const binHex = esc(d.bin_color || "#3CC850");
  const confPct = ((d.confidence || 0) * 100).toFixed(0);
  const detail = d.detail ? esc(d.detail) : "";
  const advice = d.advice ? esc(d.advice) : "";

  return `
    <div class="ai-result-card" style="--bin-color: ${binHex}">
      <div class="d-flex justify-content-between align-items-start gap-2 mb-2">
        <div class="ai-item-title">
          <span>🏷️ ${itemTitle}</span>
          ${rawClass ? `<span class="ai-class-badge">${rawClass}</span>` : ""}
        </div>
        <span class="badge rounded-pill bg-success-subtle text-success border border-success-subtle px-2 py-1 flex-shrink-0">
          ความแม่นยำ ${confPct}%
        </span>
      </div>
      <div class="d-flex flex-column gap-1">
        <div class="ai-detail-row d-flex align-items-center gap-2">
          <span class="fw-bold text-white-50">🗑️ ถังขยะ:</span>
          <span class="ai-bin-badge">
            <span class="dot m-0 me-1" style="background:${binHex}"></span>
            ${binName}
          </span>
        </div>
        ${detail ? `
        <div class="ai-detail-row">
          <span class="fw-bold text-white-50">📦 ข้อมูล:</span>
          <span>${detail}</span>
        </div>` : ""}
        ${advice ? `
        <div class="ai-advice-row mt-1">
          <span class="fw-bold">💡 คำแนะนำ:</span> ${advice}
        </div>` : ""}
        <button type="button" class="btn btn-sm btn-outline-warning py-1 px-2 mt-2 w-100 ask-ai-card-btn" data-item="${itemTitle}">
          💬 ถาม AI เพิ่มเติมเกี่ยวกับ "${itemTitle}"
        </button>
      </div>
    </div>
  `;
}

let liveHideTimer = null;
function renderLiveAICards(detections) {
  const box = $("ai-live-box");
  const content = $("ai-live-content");
  const timeLabel = $("ai-live-time");
  if (!box || !content) return;

  if (!detections || detections.length === 0) {
    if (!liveHideTimer) {
      liveHideTimer = setTimeout(() => {
        box.classList.add("d-none");
        content.innerHTML = "";
        liveHideTimer = null;
      }, 3000);
    }
    return;
  }

  if (liveHideTimer) {
    clearTimeout(liveHideTimer);
    liveHideTimer = null;
  }

  box.classList.remove("d-none");
  if (timeLabel) timeLabel.textContent = new Date().toLocaleTimeString();
  content.innerHTML = detections.map(renderAICardHTML).join("");
}

// ---------- ระบบเสียงพูดแนะนำจาก AI (Smooth Thai Speech) ----------
let voiceEnabled = true;
let lastSpokenItem = "";
let lastSpokenTime = 0;

function getBestThaiVoice() {
  if (!window.speechSynthesis) return null;
  const voices = window.speechSynthesis.getVoices();
  const thVoices = voices.filter((v) => v.lang.startsWith("th") || v.lang.includes("TH"));
  if (thVoices.length === 0) return null;
  // เรียงลำดับเสียงที่เป็นธรรมชาติที่สุด (Natural, Online, Premwadee, Niwat, Achara, Google, Kanya)
  const priority = ["Natural", "Online", "Premwadee", "Niwat", "Achara", "Google", "Kanya"];
  for (const p of priority) {
    const found = thVoices.find((v) => v.name.includes(p));
    if (found) return found;
  }
  return thVoices[0];
}

function speakRecommendation(itemName, binName) {
  if (!voiceEnabled || !window.speechSynthesis) return;
  const now = Date.now();
  if (itemName === lastSpokenItem && now - lastSpokenTime < 6000) return;
  if (now - lastSpokenTime < 3500) return;

  lastSpokenItem = itemName;
  lastSpokenTime = now;

  // เอาชื่อหลักที่สั้น กระชับ ชัดเจน (ตัดวงเล็บและตัวเลือกสำรองหลังเครื่องหมาย / ออก เพื่อให้เสียงนุ่มนวลเป็นธรรมชาติ)
  const primaryItem = (itemName || "").split("/")[0].replace(/\(.*?\)/g, "").trim();
  let cleanBin = "ถังสีน้ำเงิน";
  if ((binName || "").includes("เหลือง")) cleanBin = "ถังสีเหลือง";
  else if ((binName || "").includes("เขียว")) cleanBin = "ถังสีเขียว";
  else if ((binName || "").includes("แดง")) cleanBin = "ถังสีแดง";
  else if ((binName || "").includes("น้ำเงิน")) cleanBin = "ถังสีน้ำเงิน";

  // รูปแบบเสียงพูด: "[ชื่อสิ่งของ] ถ้าจะทิ้ง แนะนำถังสี...ครับ" หรือ "ถ้าจะทิ้ง แนะนำถังสี...ครับ"
  const text = primaryItem && !primaryItem.includes("วัตถุ") && !primaryItem.includes("ขยะในภาพ")
    ? `${primaryItem} ถ้าจะทิ้ง แนะนำ${cleanBin}ครับ`
    : `ถ้าจะทิ้ง แนะนำ${cleanBin}ครับ`;

  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = "th-TH";
  utter.rate = 1.0; // จังหวะการพูดปกติ นุ่มนวล เป็นธรรมชาติ
  utter.pitch = 1.0;
  
  const bestVoice = getBestThaiVoice();
  if (bestVoice) utter.voice = bestVoice;

  if (window.speechSynthesis.speaking) {
    window.speechSynthesis.cancel();
  }
  // หน่วงเวลา 40ms ป้องกันเสียงกระตุกหรือเสียงขาดคำแรกบน Windows / Chrome
  setTimeout(() => {
    window.speechSynthesis.speak(utter);
  }, 40);
}

// โหลดรายชื่อเสียงล่วงหน้า
if (window.speechSynthesis) {
  window.speechSynthesis.onvoiceschanged = () => getBestThaiVoice();
}

const toggleVoiceBtn = $("btn-toggle-voice");
if (toggleVoiceBtn) {
  toggleVoiceBtn.onclick = () => {
    voiceEnabled = !voiceEnabled;
    toggleVoiceBtn.textContent = voiceEnabled ? "🔊 เสียงพูด: เปิด" : "🔇 เสียงพูด: ปิด";
    toggleVoiceBtn.classList.toggle("btn-outline-info", voiceEnabled);
    toggleVoiceBtn.classList.toggle("btn-outline-secondary", !voiceEnabled);
    if (!voiceEnabled && window.speechSynthesis) window.speechSynthesis.cancel();
  };
}

// ---------- กล้องระดับ HD พร้อมระบบ AR Interpolation กรอบติดตามวัตถุ ----------
let camStream = null, camRunning = false;
let currentFacingMode = "user"; // "user" = กล้องหน้า/Webcam, "environment" = กล้องหลัง
let isMirrored = true;

const videoEl = $("cam-video-element");
const overlayCanvas = $("cam-overlay-canvas");
const switchCamBtn = $("btn-switch-cam");
const toggleMirrorBtn = $("btn-toggle-mirror");
const resBadge = $("cam-res-badge");
const captureCanvas = document.createElement("canvas");

// กล่องสำหรับทำ Smooth Lerp Animation (ติดตามวัตถุอย่างนุ่มนวล)
let activeBoxes = [];
let animFrameId = null;

function applyMirrorState() {
  if (videoEl) {
    videoEl.style.transform = isMirrored ? "scaleX(-1)" : "none";
  }
  // overlayCanvas ต้องเป็น none เสมอ ตัวอักษรจะไม่ถูกกลับด้าน
  if (overlayCanvas) {
    overlayCanvas.style.transform = "none";
  }
  if (toggleMirrorBtn) {
    toggleMirrorBtn.textContent = isMirrored ? "🪞 กระจก: เปิด" : "🪞 กระจก: ปิด";
  }
}

function syncViewerDimensions() {
  if (!videoEl || !videoEl.videoWidth || !videoEl.videoHeight) return;
  const vidAspect = videoEl.videoWidth / videoEl.videoHeight;
  const viewer = $("viewer-container");
  if (viewer) {
    viewer.style.aspectRatio = `${vidAspect}`;
  }
  const vw = videoEl.clientWidth;
  const vh = videoEl.clientHeight;
  if (overlayCanvas && (overlayCanvas.width !== vw || overlayCanvas.height !== vh)) {
    overlayCanvas.width = vw;
    overlayCanvas.height = vh;
  }
}

// วาดกรอบเดี่ยวแบบมีแอนิเมชันเรืองแสงและขอบมน
function drawSingleBox(ctx, b) {
  ctx.save();
  ctx.globalAlpha = Math.min(1, Math.max(0, b.opacity));

  const x = Math.round(b.x);
  const y = Math.round(b.y);
  const w = Math.round(b.w);
  const h = Math.round(b.h);
  const r = 8;

  // กรอบนีออนเรืองแสง
  ctx.shadowColor = b.color;
  ctx.shadowBlur = 14;
  ctx.lineWidth = 3.5;
  ctx.strokeStyle = b.color;

  ctx.beginPath();
  if (ctx.roundRect) {
    ctx.roundRect(x, y, w, h, r);
  } else {
    ctx.rect(x, y, w, h);
  }
  ctx.stroke();

  // ระบายโปร่งแสงข้างใน
  ctx.fillStyle = b.color + "22";
  ctx.fill();
  ctx.restore();

  // ป้ายชื่อวัตถุบนกรอบ
  ctx.save();
  ctx.globalAlpha = Math.min(1, Math.max(0, b.opacity));
  ctx.font = "bold 13px 'Segoe UI', 'Sarabun', sans-serif";
  const textW = ctx.measureText(b.label).width;
  const tagH = 24;
  const tagY = Math.max(0, y - tagH - 4);

  ctx.fillStyle = b.color;
  ctx.beginPath();
  if (ctx.roundRect) {
    ctx.roundRect(x, tagY, textW + 16, tagH, [6, 6, 2, 2]);
  } else {
    ctx.rect(x, tagY, textW + 16, tagH);
  }
  ctx.fill();

  ctx.fillStyle = "#0a0e1a";
  ctx.fillText(b.label, x + 8, tagY + 16);
  ctx.restore();
}

// ลูปแอนิเมชัน 60 FPS (Lerp Interpolation ให้กรอบเคลื่อนที่ตามวัตถุอย่างลื่นไหล)
function animateOverlay() {
  if (!camRunning) return;
  syncViewerDimensions();

  if (overlayCanvas) {
    const ctx = overlayCanvas.getContext("2d");
    const vw = overlayCanvas.width;
    const vh = overlayCanvas.height;
    ctx.clearRect(0, 0, vw, vh);

    for (let i = 0; i < activeBoxes.length; i++) {
      const b = activeBoxes[i];
      // Lerp พิกัดให้ไหลตามวัตถุ
      b.x += (b.targetX - b.x) * 0.45;
      b.y += (b.targetY - b.y) * 0.45;
      b.w += (b.targetW - b.w) * 0.45;
      b.h += (b.targetH - b.h) * 0.45;
      b.opacity += (b.targetOpacity - b.opacity) * 0.3;

      if (b.opacity > 0.05) {
        drawSingleBox(ctx, b);
      }
    }

    activeBoxes = activeBoxes.filter((b) => b.opacity > 0.05);
  }

  animFrameId = requestAnimationFrame(animateOverlay);
}

// อัปเดตพิกัดเป้าหมายจากผลตรวจจับของ YOLO
function updateBoxTargets(detections, frameW, frameH) {
  if (!videoEl || !overlayCanvas) return;
  const vw = overlayCanvas.width || videoEl.clientWidth;
  const vh = overlayCanvas.height || videoEl.clientHeight;
  const scaleX = vw / frameW;
  const scaleY = vh / frameH;

  if (!detections || detections.length === 0) {
    activeBoxes.forEach((b) => (b.targetOpacity = 0));
    return;
  }

  activeBoxes.forEach((b) => (b.targetOpacity = 0));

  detections.forEach((d) => {
    const [x1, y1, x2, y2] = d.box;
    let targetX, targetW;

    if (isMirrored) {
      targetX = vw - (x2 * scaleX);
      targetW = (x2 - x1) * scaleX;
    } else {
      targetX = x1 * scaleX;
      targetW = (x2 - x1) * scaleX;
    }
    const targetY = y1 * scaleY;
    const targetH = (y2 - y1) * scaleY;
    const label = `${d.item_name || d.class_name} ${(d.confidence * 100).toFixed(0)}%`;
    const color = d.bin_color || "#3CC850";

    const matched = activeBoxes.find((b) => b.class_name === d.class_name);
    if (matched) {
      matched.targetX = targetX;
      matched.targetY = targetY;
      matched.targetW = targetW;
      matched.targetH = targetH;
      matched.label = label;
      matched.color = color;
      matched.targetOpacity = 1;
    } else {
      activeBoxes.push({
        class_name: d.class_name,
        x: targetX,
        y: targetY,
        w: targetW,
        h: targetH,
        targetX,
        targetY,
        targetW,
        targetH,
        label,
        color,
        opacity: 0.15,
        targetOpacity: 1,
      });
    }
  });
}

async function startBrowserCamera() {
  $("live-status").textContent = "กำลังเชื่อมต่อกล้อง Full HD 1080p 60FPS...";
  isMirrored = (currentFacingMode === "user");

  // ขอความละเอียด Full HD 1080p (1920x1080) เพื่อความคมชัดสูงสุด
  const constraints = {
    video: {
      width: { ideal: 1920, min: 1280 },
      height: { ideal: 1080, min: 720 },
      facingMode: currentFacingMode,
      frameRate: { ideal: 60, min: 30 },
    },
    audio: false,
  };

  camStream = await navigator.mediaDevices.getUserMedia(constraints);
  videoEl.srcObject = camStream;
  await videoEl.play();
  camRunning = true;

  videoEl.onloadedmetadata = () => syncViewerDimensions();
  syncViewerDimensions();
  applyMirrorState();

  videoEl.classList.remove("d-none");
  overlayCanvas.classList.remove("d-none");
  $("video").classList.add("d-none");
  $("video-ph").classList.add("d-none");
  if (switchCamBtn) switchCamBtn.classList.remove("d-none");
  if (toggleMirrorBtn) toggleMirrorBtn.classList.remove("d-none");

  if (resBadge) {
    const track = camStream.getVideoTracks()[0];
    const settings = track ? track.getSettings() : {};
    const curW = settings.width || 1920;
    const curH = settings.height || 1080;
    resBadge.textContent = `🟢 Full HD ${curW}x${curH} 60FPS`;
    resBadge.classList.remove("d-none");
  }
  $("live-status").textContent = "🟢 กล้อง Full HD 1080p ลื่นไหล 60FPS";

  // เริ่มลูปแอนิเมชัน AR Bounding Boxes
  if (animFrameId) cancelAnimationFrame(animFrameId);
  animFrameId = requestAnimationFrame(animateOverlay);

  // วนลูปส่งเฟรมไปประมวลผลด้วยความละเอียดสูงระดับ 1080p คุณภาพ JPEG 0.88
  while (camRunning) {
    const w = videoEl.videoWidth, h = videoEl.videoHeight;
    if (!w || !h) { await new Promise((r) => setTimeout(r, 100)); continue; }

    const targetW = 1080;
    const targetH = Math.round(1080 * (h / w));
    captureCanvas.width = targetW;
    captureCanvas.height = targetH;
    const ctx = captureCanvas.getContext("2d");

    ctx.drawImage(videoEl, 0, 0, targetW, targetH);
    const blob = await new Promise((r) => captureCanvas.toBlob(r, "image/jpeg", 0.88));
    const fd = new FormData();
    fd.append("file", blob, "frame.jpg");

    try {
      const r = await fetch("/predict-frame", { method: "POST", body: fd });
      if (r.ok && camRunning) {
        const data = await r.json();
        renderLiveAICards(data.detections);
        updateBoxTargets(data.detections, targetW, targetH);

        if (data.detections && data.detections.length > 0) {
          const top = data.detections[0];
          currentLiveItem = top.item_name || top.class_name;
          updateChatCurrentItem(currentLiveItem);
          speakRecommendation(currentLiveItem, top.bin_name);
        } else {
          updateBoxTargets([], targetW, targetH);
        }
      }
    } catch (_) {
      await new Promise((r) => setTimeout(r, 350));
    }
  }
}

function stopBrowserCamera() {
  camRunning = false;
  if (animFrameId) {
    cancelAnimationFrame(animFrameId);
    animFrameId = null;
  }
  if (camStream) camStream.getTracks().forEach((t) => t.stop());
  camStream = null;
  videoEl.classList.add("d-none");
  overlayCanvas.classList.add("d-none");
  if (switchCamBtn) switchCamBtn.classList.add("d-none");
  if (toggleMirrorBtn) toggleMirrorBtn.classList.add("d-none");
  if (resBadge) resBadge.classList.add("d-none");
  activeBoxes = [];
  if (overlayCanvas) {
    const ctx = overlayCanvas.getContext("2d");
    ctx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
  }
  if (window.speechSynthesis) window.speechSynthesis.cancel();
}

if (switchCamBtn) {
  switchCamBtn.onclick = async () => {
    currentFacingMode = currentFacingMode === "user" ? "environment" : "user";
    stopBrowserCamera();
    try {
      await startBrowserCamera();
    } catch (e) {
      alert("ไม่สามารถสลับกล้องได้: " + e.message);
    }
  };
}

if (toggleMirrorBtn) {
  toggleMirrorBtn.onclick = () => {
    isMirrored = !isMirrored;
    applyMirrorState();
  };
}

// ---------- กล้องเซิร์ฟเวอร์ (Webcam/IP Camera) ----------
let serverStreamPoller = null;
function startServerStreamPolling() {
  stopServerStreamPolling();
  serverStreamPoller = setInterval(async () => {
    try {
      const r = await fetch("/camera/latest");
      if (r.ok) {
        const data = await r.json();
        renderLiveAICards(data.detections);
        if (data.detections && data.detections.length > 0) {
          const top = data.detections[0];
          currentLiveItem = top.item_name || top.class_name;
          updateChatCurrentItem(currentLiveItem);
          speakRecommendation(currentLiveItem, top.bin_name);
        }
      }
    } catch (_) {}
  }, 450);
}

function stopServerStreamPolling() {
  if (serverStreamPoller) {
    clearInterval(serverStreamPoller);
    serverStreamPoller = null;
  }
}

$("btn-start").onclick = async () => {
  const type = $("cam-type").value;
  stopBrowserCamera();
  stopServerStreamPolling();

  if (type === "browser") {
    try {
      await startBrowserCamera();
    } catch (e) {
      $("live-status").textContent = "❌ เปิดกล้องไม่ได้: " + e.message;
    }
    return;
  }

  const source = type === "url" ? $("cam-url").value.trim() : type;
  if (!source) return ($("live-status").textContent = "กรุณากรอก URL");
  $("live-status").textContent = "กำลังเชื่อมต่อกล้อง...";
  try {
    const r = await fetch("/camera/source", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source }),
    });
    if (!r.ok) throw new Error((await r.json()).detail);
    $("video").src = "/video_feed?t=" + Date.now();
    $("video").classList.remove("d-none");
    $("video-ph").classList.add("d-none");
    $("live-status").textContent = "🟢 กำลังสตรีม HD";
    startServerStreamPolling();
  } catch (e) {
    $("live-status").textContent = "❌ " + e.message;
  }
};

async function stopStream() {
  stopBrowserCamera();
  stopServerStreamPolling();
  if (liveHideTimer) {
    clearTimeout(liveHideTimer);
    liveHideTimer = null;
  }
  $("video").removeAttribute("src");
  $("video").classList.add("d-none");
  $("video-ph").classList.remove("d-none");
  $("live-status").textContent = "";
  if ($("ai-live-box")) $("ai-live-box").classList.add("d-none");
  if ($("ai-live-content")) $("ai-live-content").innerHTML = "";
  await fetch("/camera/stop", { method: "POST" }).catch(() => {});
}
$("btn-stop").onclick = stopStream;

// ---------- Mode 2: Upload Image ----------
const dz = $("dropzone");
dz.onclick = () => $("file-input").click();
dz.ondragover = (e) => { e.preventDefault(); dz.classList.add("drag"); };
dz.ondragleave = () => dz.classList.remove("drag");
dz.ondrop = (e) => {
  e.preventDefault();
  dz.classList.remove("drag");
  if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]);
};
$("file-input").onchange = (e) => e.target.files[0] && upload(e.target.files[0]);

async function upload(file) {
  const list = $("result-list");
  if (!/^image\/(jpeg|png)$/.test(file.type)) {
    list.innerHTML = '<div class="alert alert-warning">รองรับเฉพาะ .jpg / .png</div>';
    return;
  }
  list.innerHTML = '<div class="text-secondary">กำลังวิเคราะห์ภาพอย่างละเอียด...</div>';
  const fd = new FormData();
  fd.append("file", file);
  const apiKey = localStorage.getItem("gemini_api_key") || "";
  if (apiKey) fd.append("api_key", apiKey);
  try {
    const r = await fetch("/predict-image", { method: "POST", body: fd });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail);
    $("result-img").src = data.annotated_image;
    $("result-img").classList.remove("d-none");
    $("result-ph").classList.add("d-none");

    if (data.detections && data.detections.length > 0) {
      currentLiveItem = data.detections[0].item_name || data.detections[0].class_name;
      updateChatCurrentItem(currentLiveItem);
      speakRecommendation(currentLiveItem, data.detections[0].bin_name);
    }

    list.innerHTML = data.count === 0
      ? '<div class="alert alert-secondary">ไม่พบวัตถุขยะในภาพ กรุณาถ่ายภาพให้เห็นวัตถุชัดเจนยิ่งขึ้น</div>'
      : `<div class="d-flex align-items-center gap-2 mb-2">
           <span class="live-pulse"></span>
           <span class="fw-bold text-success">🤖 ผลการประมวลผลจาก AI (${data.count} รายการ):</span>
         </div>` +
        `<div class="d-flex flex-column gap-2">` +
        data.detections.map(renderAICardHTML).join("") +
        `</div>`;
    refresh();
  } catch (e) {
    list.innerHTML = `<div class="alert alert-danger">${esc(e.message)}</div>`;
  }
}

// ---------- ระบบ AI ถาม-ตอบ ขยะอัจฉริยะ (AI Chat Assistant) ----------
const chatDrawer = $("ai-chat-drawer");
const chatBackdrop = $("ai-chat-backdrop");
const openChatBtn = $("btn-open-ai-chat");
const closeChatBtn = $("btn-close-ai-chat");
const chatForm = $("ai-chat-form");
const chatInput = $("ai-chat-input");
const chatMessages = $("ai-chat-messages");
const currentBanner = $("ai-chat-current-banner");
const currentNameEl = $("ai-chat-current-name");
const askCurrentBtn = $("btn-ask-current");

function setAiChatOpen(isOpen) {
  if (!chatDrawer || !chatBackdrop) return;
  chatDrawer.classList.toggle("open", isOpen);
  chatBackdrop.classList.toggle("open", isOpen);
  if (isOpen) {
    updateChatCurrentItem(currentLiveItem);
    setTimeout(() => chatInput && chatInput.focus(), 300);
  }
}

if (openChatBtn) openChatBtn.onclick = () => setAiChatOpen(true);
if (closeChatBtn) closeChatBtn.onclick = () => setAiChatOpen(false);
if (chatBackdrop) chatBackdrop.onclick = () => setAiChatOpen(false);

function updateChatCurrentItem(itemName) {
  if (!currentBanner || !currentNameEl) return;
  if (itemName) {
    currentNameEl.textContent = itemName;
    currentBanner.classList.remove("d-none");
  } else {
    currentBanner.classList.add("d-none");
  }
}

if (askCurrentBtn) {
  askCurrentBtn.onclick = () => {
    if (currentLiveItem) {
      sendChatMessage(`ขยะชิ้นนี้คือ "${currentLiveItem}" ต้องแยกทิ้งอย่างไร และมีคำแนะนำอะไรบ้าง`);
    }
  };
}

// คลิกปุ่ม "ถาม AI เพิ่มเติมเกี่ยวกับ..." ในการ์ดผลลัพธ์
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".ask-ai-card-btn");
  if (btn && btn.dataset.item) {
    setAiChatOpen(true);
    sendChatMessage(`ขยะชิ้นนี้คือ "${btn.dataset.item}" ต้องแยกทิ้งอย่างไรและมีขั้นตอนอะไรบ้าง`);
  }
});

// ตั้งค่า Gemini API Key (ตัวเลือกเสริม)
const btnAiSettings = $("btn-ai-settings");
const settingsPanel = $("ai-settings-panel");
const btnCloseSettings = $("btn-close-settings");
const inputGeminiKey = $("input-gemini-key");
const btnSaveGeminiKey = $("btn-save-gemini-key");
const geminiKeyStatus = $("gemini-key-status");

function refreshGeminiKeyUI() {
  const savedKey = localStorage.getItem("gemini_api_key") || "";
  if (inputGeminiKey) inputGeminiKey.value = savedKey;
  if (geminiKeyStatus) {
    if (savedKey) {
      geminiKeyStatus.textContent = "✓ บันทึก Key เรียบร้อย (เปิดใช้งานโมเดล Gemini Flash)";
      geminiKeyStatus.className = "small text-success mt-1";
    } else {
      geminiKeyStatus.textContent = "○ ใช้งานฟรีด้วยระบบ Smart Engine & สารานุกรมความรู้";
      geminiKeyStatus.className = "small text-white-50 mt-1";
    }
  }
}

if (btnAiSettings && settingsPanel) {
  btnAiSettings.onclick = () => {
    settingsPanel.classList.toggle("d-none");
    refreshGeminiKeyUI();
  };
}
if (btnCloseSettings && settingsPanel) {
  btnCloseSettings.onclick = () => settingsPanel.classList.add("d-none");
}
if (btnSaveGeminiKey && inputGeminiKey) {
  btnSaveGeminiKey.onclick = () => {
    const val = inputGeminiKey.value.trim();
    if (val) {
      localStorage.setItem("gemini_api_key", val);
    } else {
      localStorage.removeItem("gemini_api_key");
    }
    refreshGeminiKeyUI();
  };
}
refreshGeminiKeyUI();

// ชิปคำถามยอดนิยม
document.querySelectorAll(".ai-chip-btn").forEach((btn) => {
  btn.onclick = () => sendChatMessage(btn.dataset.q);
});

async function sendChatMessage(msgText) {
  const text = (msgText || (chatInput ? chatInput.value : "")).trim();
  if (!text) return;
  if (chatInput) chatInput.value = "";

  // 1. เพิ่มข้อความฝั่งผู้ใช้
  const userMsgDiv = document.createElement("div");
  userMsgDiv.className = "chat-msg user";
  userMsgDiv.innerHTML = `<div class="chat-bubble">${esc(text)}</div>`;
  chatMessages.appendChild(userMsgDiv);

  // 2. เพิ่มกล่องกำลังโหลด
  const botMsgDiv = document.createElement("div");
  botMsgDiv.className = "chat-msg bot";
  botMsgDiv.innerHTML = `
    <div class="chat-bubble">
      <div class="chat-loading-dots">
        <span></span><span></span><span></span>
      </div>
    </div>`;
  chatMessages.appendChild(botMsgDiv);
  chatMessages.scrollTop = chatMessages.scrollHeight;

  // 3. ส่งไปยังเซิร์ฟเวอร์
  try {
    const apiKey = localStorage.getItem("gemini_api_key") || null;
    const res = await fetch("/ai/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        current_item: currentLiveItem,
        api_key: apiKey,
      }),
    });
    const data = await res.json();
    const formatted = esc(data.reply || "")
      .replace(/\*\*(.*?)\*\*/g, "<b>$1</b>")
      .replace(/\*(.*?)\*/g, "<i>$1</i>")
      .replace(/`([^`]+)`/g, "<code class='bg-black px-1 rounded'>$1</code>")
      .replace(/\n/g, "<br>");

    botMsgDiv.querySelector(".chat-bubble").innerHTML = formatted;
  } catch (e) {
    botMsgDiv.querySelector(".chat-bubble").innerHTML = `⚠️ ขออภัย เกิดข้อผิดพลาดในการเชื่อมต่อ: ${esc(e.message)}`;
  }
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

if (chatForm) {
  chatForm.onsubmit = (e) => {
    e.preventDefault();
    sendChatMessage();
  };
}

// ---------- ประวัติและยอดรวม (History & Summary) ----------
async function refresh() {
  try {
    const [h, s] = await Promise.all([
      fetch("/history?limit=30").then((r) => r.json()),
      fetch("/summary").then((r) => r.json()),
    ]);
    const tbody = $("history-body");
    if (tbody) {
      tbody.innerHTML = h.items.length === 0
        ? '<tr><td colspan="4" class="text-center text-secondary py-3">ยังไม่มีข้อมูลการตรวจจับ</td></tr>'
        : h.items.map((i) =>
            `<tr><td>${esc(i.timestamp.slice(11))}</td><td>${esc(i.class_name)}</td>
             <td>${(i.confidence * 100).toFixed(0)}%</td>
             <td><span class="dot" style="background:${binColor(i.bin_name)}"></span></td></tr>`).join("");
    }
    const summaryBox = $("summary");
    if (summaryBox) {
      summaryBox.innerHTML = ["organic", "recyclable", "general", "hazardous"].map((c) =>
        `<div class="col-6"><div class="glass stat-card"><div class="num">${s[c] || 0}</div><div>${CAT_LABEL[c]}</div></div></div>`).join("");
    }

    const total = (s.organic || 0) + (s.recyclable || 0) + (s.general || 0) + (s.hazardous || 0);
    const badge = $("badge-total-count");
    if (badge) {
      badge.textContent = total;
      badge.classList.toggle("d-none", total === 0);
    }
    const drawerTotal = $("drawer-total-count");
    if (drawerTotal) {
      drawerTotal.textContent = total + " ชิ้น";
    }
    const historyCount = $("history-count");
    if (historyCount) {
      historyCount.textContent = h.items.length + " รายการ";
    }
  } catch (_) {}
}

// ---------- Drawer สถิติ (แถบสามขีดด้านซ้าย) ----------
const drawer = $("stats-drawer");
const backdrop = $("drawer-backdrop");
const toggleBtn = $("btn-toggle-stats");
const closeBtn = $("btn-close-stats");

function setDrawerOpen(isOpen) {
  if (!drawer || !backdrop) return;
  drawer.classList.toggle("open", isOpen);
  backdrop.classList.toggle("open", isOpen);
  if (isOpen) refresh();
}

if (toggleBtn) toggleBtn.onclick = () => setDrawerOpen(true);
if (closeBtn) closeBtn.onclick = () => setDrawerOpen(false);
if (backdrop) backdrop.onclick = () => setDrawerOpen(false);

document.querySelectorAll("#drawerTabs .nav-link").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll("#drawerTabs .nav-link").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const targetTab = btn.dataset.tab;
    const statsPane = $("tab-stats");
    const binsPane = $("tab-bins");
    if (statsPane && binsPane) {
      statsPane.classList.toggle("d-none", targetTab !== "tab-stats");
      binsPane.classList.toggle("d-none", targetTab !== "tab-bins");
    }
  };
});

const manualRefresh = $("btn-manual-refresh");
if (manualRefresh) {
  manualRefresh.onclick = async () => {
    manualRefresh.textContent = "⏳...";
    await refresh();
    setTimeout(() => { manualRefresh.textContent = "🔄 รีเฟรช"; }, 400);
  };
}

const clearHistoryBtn = $("btn-clear-history");
if (clearHistoryBtn) {
  clearHistoryBtn.onclick = async () => {
    if (!confirm("⚠️ ต้องการลบประวัติการตรวจจับทั้งหมดใช่หรือไม่?\n(ข้อมูลสถิติทั้งหมดจะถูกรีเซ็ตเป็น 0)")) {
      return;
    }
    clearHistoryBtn.disabled = true;
    clearHistoryBtn.textContent = "กำลังลบ...";
    try {
      const r = await fetch("/history/clear", { method: "POST" });
      if (r.ok) {
        await refresh();
      } else {
        alert("เกิดข้อผิดพลาดในการลบประวัติ");
      }
    } catch (e) {
      alert("ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ได้: " + e.message);
    } finally {
      clearHistoryBtn.disabled = false;
      clearHistoryBtn.textContent = "🗑️ ลบประวัติ";
    }
  };
}

// ปิดแถบด้วยปุ่ม ESC บนคีย์บอร์ด
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (drawer && drawer.classList.contains("open")) setDrawerOpen(false);
    if (chatDrawer && chatDrawer.classList.contains("open")) setAiChatOpen(false);
  }
});

refresh();
setInterval(refresh, 3000);
