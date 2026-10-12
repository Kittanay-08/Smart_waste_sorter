// app.js - ควบคุมหน้าบ้าน: สลับโหมด, ควบคุมสตรีม, อัปโหลดภาพ, อัปเดตประวัติ
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const CAT_LABEL = { organic: "อินทรีย์", recyclable: "รีไซเคิล", general: "ทั่วไป", hazardous: "อันตราย" };
const binColor = (name) => (name.includes("เขียว") ? "#3CC850" : name.includes("เหลือง") ? "#FFD700" : name.includes("แดง") ? "#E63232" : "#1E96E6");

// ---------- สลับโหมด ----------
document.querySelectorAll("#modeTabs .nav-link").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll("#modeTabs .nav-link").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const live = btn.dataset.mode === "live";
    $("live-panel").classList.toggle("d-none", !live);
    $("upload-panel").classList.toggle("d-none", live);
    if (!live) stopStream(); // ปิดกล้องเมื่อออกจากโหมดสด เพื่อประหยัดทรัพยากร
  };
});

// ---------- Mode 1: Live ----------
$("cam-type").onchange = () => {
  const isUrl = $("cam-type").value === "url";
  $("cam-url").disabled = !isUrl;
  if (isUrl) $("cam-url").focus();
};

// ---------- กล้องของเบราว์เซอร์ (getUserMedia) ----------
// จับเฟรมจากกล้องผู้ใช้ -> พลิกซ้าย/ขวาเป็นภาพกระจก -> ส่ง /predict-frame -> แสดงภาพที่ตีกรอบแล้ว
// ส่งทีละเฟรม (รอผลก่อนส่งเฟรมถัดไป) ป้องกันเซิร์ฟเวอร์ล้น
let camStream = null, camRunning = false;
const camVideo = document.createElement("video");
camVideo.playsInline = true; camVideo.muted = true;
const camCanvas = document.createElement("canvas");

async function startBrowserCamera() {
  camStream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 }, facingMode: "environment" }, audio: false });
  camVideo.srcObject = camStream;
  await camVideo.play();
  camRunning = true;
  $("video").classList.remove("d-none");
  $("video-ph").classList.add("d-none");
  $("live-status").textContent = "🟢 กำลังวิเคราะห์";
  while (camRunning) {
    const w = camVideo.videoWidth, h = camVideo.videoHeight;
    if (!w) { await new Promise((r) => setTimeout(r, 100)); continue; }
    camCanvas.width = w; camCanvas.height = h;
    const ctx = camCanvas.getContext("2d");
    ctx.translate(w, 0); ctx.scale(-1, 1); // mirror
    ctx.drawImage(camVideo, 0, 0, w, h);
    const blob = await new Promise((r) => camCanvas.toBlob(r, "image/jpeg", 0.7));
    const fd = new FormData();
    fd.append("file", blob, "frame.jpg");
    try {
      const r = await fetch("/predict-frame", { method: "POST", body: fd });
      if (r.ok && camRunning) $("video").src = (await r.json()).annotated_image;
    } catch (_) { await new Promise((r) => setTimeout(r, 500)); }
  }
}

function stopBrowserCamera() {
  camRunning = false;
  if (camStream) camStream.getTracks().forEach((t) => t.stop());
  camStream = null;
}

$("btn-start").onclick = async () => {
  const type = $("cam-type").value;
  stopBrowserCamera();
  if (type === "browser") {
    $("live-status").textContent = "กำลังขอสิทธิ์กล้อง...";
    try { await startBrowserCamera(); }
    catch (e) { $("live-status").textContent = "❌ เปิดกล้องไม่ได้ (ต้องอนุญาตกล้อง และใช้ https): " + e.message; }
    return;
  }
  const source = type === "url" ? $("cam-url").value.trim() : type;
  if (!source) return ($("live-status").textContent = "กรุณากรอก URL");
  $("live-status").textContent = "กำลังเชื่อมต่อ...";
  try {
    const r = await fetch("/camera/source", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source }),
    });
    if (!r.ok) throw new Error((await r.json()).detail);
    $("video").src = "/video_feed?t=" + Date.now(); // t = กัน browser cache
    $("video").classList.remove("d-none");
    $("video-ph").classList.add("d-none");
    $("live-status").textContent = "🟢 กำลังสตรีม";
  } catch (e) {
    $("live-status").textContent = "❌ " + e.message;
  }
};

async function stopStream() {
  stopBrowserCamera();
  $("video").removeAttribute("src");
  $("video").classList.add("d-none");
  $("video-ph").classList.remove("d-none");
  $("live-status").textContent = "";
  await fetch("/camera/stop", { method: "POST" }).catch(() => {});
}
$("btn-stop").onclick = stopStream;

// ---------- Mode 2: Upload ----------
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
  list.innerHTML = '<div class="text-secondary">กำลังวิเคราะห์...</div>';
  const fd = new FormData();
  fd.append("file", file);
  try {
    const r = await fetch("/predict-image", { method: "POST", body: fd });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail);
    $("result-img").src = data.annotated_image;
    $("result-img").classList.remove("d-none");
    $("result-ph").classList.add("d-none");
    list.innerHTML = data.count === 0
      ? '<div class="alert alert-secondary">ไม่พบขยะในภาพ (conf ≥ 60%)</div>'
      : data.detections.map((d) =>
          `<div class="p-2 mb-2 rounded" style="background:${esc(d.bin_color)};color:#111">
             <b>${esc(d.class_name)}</b> (${(d.confidence * 100).toFixed(0)}%) → ${esc(d.bin_name)}
             <div class="small">ประเภท: ${esc(d.types)}<br>การจัดการ: ${esc(d.handling)}</div></div>`).join("");
    refresh();
  } catch (e) {
    list.innerHTML = `<div class="alert alert-danger">${esc(e.message)}</div>`;
  }
}

// ---------- History & Summary ----------
async function refresh() {
  try {
    const [h, s] = await Promise.all([fetch("/history?limit=30").then((r) => r.json()), fetch("/summary").then((r) => r.json())]);
    $("history-body").innerHTML = h.items.map((i) =>
      `<tr><td>${esc(i.timestamp.slice(11))}</td><td>${esc(i.class_name)}</td>
       <td>${(i.confidence * 100).toFixed(0)}</td>
       <td><span class="dot" style="background:${binColor(i.bin_name)}"></span></td></tr>`).join("");
    $("summary").innerHTML = ["organic", "recyclable", "general", "hazardous"].map((c) =>
      `<div class="col-6"><div class="glass stat-card"><div class="num">${s[c] || 0}</div><div>${CAT_LABEL[c]}</div></div></div>`).join("");
  } catch (_) { /* เครือข่ายขัดข้องชั่วคราว ข้ามรอบนี้ */ }
}
refresh();
setInterval(refresh, 3000);
