const CHUNK_DURATION_MS = 15000;

let meetingId = null;
let stream = null;
let currentRecorder = null;
let loopPromise = null;
let pendingUploads = [];
let stopRequested = true;
let lastMarkdown = "";
let lastTitle = "회의";

let liveSocket = null;
let audioContext = null;
let workletNode = null;
let micSourceNode = null;

const screens = ["start", "recording", "processing", "speakers", "report"];
function showScreen(name) {
  for (const s of screens) {
    document.getElementById(`screen-${s}`).classList.toggle("hidden", s !== name);
  }
}

function recordOneChunk(durationMs) {
  return new Promise((resolve) => {
    const recorder = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
    const localChunks = [];
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) localChunks.push(e.data);
    };
    recorder.addEventListener(
      "stop",
      () => {
        clearTimeout(timer);
        resolve(new Blob(localChunks, { type: "audio/webm" }));
      },
      { once: true }
    );
    currentRecorder = recorder;
    recorder.start();
    const timer = setTimeout(() => {
      if (recorder.state !== "inactive") recorder.stop();
    }, durationMs);
  });
}

async function uploadChunk(blob) {
  if (!blob || blob.size === 0) return;
  const form = new FormData();
  form.append("audio", blob, "chunk.webm");
  await fetch(`/meetings/${meetingId}/chunk`, { method: "POST", body: form });
}

async function recordingLoop() {
  while (!stopRequested) {
    const blob = await recordOneChunk(CHUNK_DURATION_MS);
    // 업로드는 기다리지 않고 바로 다음 녹음을 시작한다 — 대기하면 그 사이 마이크가
    // 비어 있어 발화가 소실된다. 업로드 완료는 finishMeeting에서 한꺼번에 기다린다.
    pendingUploads.push(uploadChunk(blob));
  }
}

function appendCaption(text) {
  const el = document.getElementById("live-captions");
  const p = document.createElement("p");
  p.textContent = text;
  el.appendChild(p);
  el.scrollTop = el.scrollHeight;
}

function setLiveStatus(text, cls) {
  const el = document.getElementById("live-status");
  el.textContent = text;
  el.className = "badge" + (cls ? ` ${cls}` : "");
}

async function startLiveTranscription() {
  const wsProtocol = location.protocol === "https:" ? "wss:" : "ws:";
  liveSocket = new WebSocket(`${wsProtocol}//${location.host}/meetings/${meetingId}/live-ws`);
  liveSocket.binaryType = "arraybuffer";

  liveSocket.onopen = () => setLiveStatus("실시간 자막 연결됨", "connected");
  liveSocket.onerror = () => setLiveStatus("실시간 자막 연결 오류", "error");
  liveSocket.onclose = () => setLiveStatus("실시간 자막 연결 끊김", "error");
  liveSocket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "text" && data.text) {
      appendCaption(data.text);
    } else if (data.type === "status") {
      setLiveStatus(data.text, data.text.includes("끊김") ? "error" : "connected");
    }
  };

  audioContext = new AudioContext({ sampleRate: 16000 });
  await audioContext.audioWorklet.addModule("/pcm-worklet.js");
  micSourceNode = audioContext.createMediaStreamSource(stream);
  workletNode = new AudioWorkletNode(audioContext, "pcm-worklet-processor");
  workletNode.port.onmessage = (event) => {
    if (liveSocket && liveSocket.readyState === WebSocket.OPEN) {
      liveSocket.send(event.data);
    }
  };
  micSourceNode.connect(workletNode);
}

function stopLiveTranscription() {
  if (workletNode) workletNode.port.onmessage = null;
  if (micSourceNode) micSourceNode.disconnect();
  if (workletNode) workletNode.disconnect();
  if (audioContext) audioContext.close();
  if (liveSocket && liveSocket.readyState === WebSocket.OPEN) liveSocket.close();
  audioContext = null;
  workletNode = null;
  micSourceNode = null;
  liveSocket = null;
}

async function startMeeting() {
  lastTitle = document.getElementById("title-input").value.trim() || "제목 없는 회의";
  const res = await fetch("/meetings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: lastTitle }),
  });
  const data = await res.json();
  meetingId = data.meeting_id;

  stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  document.getElementById("live-captions").innerHTML = "";
  stopRequested = false;
  pendingUploads = [];
  showScreen("recording");
  await startLiveTranscription();
  loopPromise = recordingLoop();
}

async function finishMeeting() {
  stopRequested = true;
  if (currentRecorder && currentRecorder.state !== "inactive") {
    currentRecorder.stop();
  }
  stopLiveTranscription();
  await loopPromise; // 마지막 청크의 녹음이 끝나고 업로드가 큐에 들어갈 때까지 대기
  stream.getTracks().forEach((t) => t.stop());
  await Promise.all(pendingUploads); // 아직 처리 중인 업로드(전사)가 모두 끝날 때까지 대기

  showScreen("processing");
  const res = await fetch(`/meetings/${meetingId}/finish`, { method: "POST" });
  const data = await res.json();
  renderSpeakerList(data.speakers);
  showScreen("speakers");
}

function renderSpeakerList(speakers) {
  const container = document.getElementById("speaker-list");
  container.innerHTML = "";
  for (const speaker of speakers) {
    const row = document.createElement("div");
    row.className = "speaker-row";

    const label = document.createElement("span");
    label.className = "speaker-label";
    label.textContent = speaker.label;
    row.appendChild(label);

    if (speaker.sample_path) {
      const audio = document.createElement("audio");
      audio.controls = true;
      audio.src = `/meetings/${meetingId}/speakers/${speaker.label}/sample`;
      row.appendChild(audio);
    }

    const input = document.createElement("input");
    input.type = "text";
    input.placeholder = "이름 입력";
    input.dataset.label = speaker.label;
    row.appendChild(input);

    container.appendChild(row);
  }
}

async function saveSpeakersAndGenerateReport() {
  const inputs = document.querySelectorAll("#speaker-list input");
  const names = {};
  inputs.forEach((input) => {
    if (input.value.trim()) names[input.dataset.label] = input.value.trim();
  });

  if (Object.keys(names).length > 0) {
    await fetch(`/meetings/${meetingId}/speakers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ names }),
    });
  }

  showScreen("processing");
  const res = await fetch(`/meetings/${meetingId}/report`, { method: "POST" });
  const data = await res.json();
  lastMarkdown = data.markdown;
  document.getElementById("report-content").innerHTML = mdToHtml(lastMarkdown);
  showScreen("report");
}

function mdToHtml(md) {
  const escape = (s) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const lines = md.split("\n");
  let html = "";
  let inList = false;
  for (let line of lines) {
    line = escape(line).trim();
    if (line.startsWith("## ")) {
      if (inList) { html += "</ul>"; inList = false; }
      html += `<h3>${line.slice(3)}</h3>`;
    } else if (line.startsWith("- ") || line.startsWith("* ")) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${line.slice(2)}</li>`;
    } else if (line === "") {
      if (inList) { html += "</ul>"; inList = false; }
    } else {
      if (inList) { html += "</ul>"; inList = false; }
      html += `<p>${line.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")}</p>`;
    }
  }
  if (inList) html += "</ul>";
  return html;
}

function downloadReport() {
  const blob = new Blob([lastMarkdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${lastTitle}.md`;
  a.click();
  URL.revokeObjectURL(url);
}

document.getElementById("btn-start").addEventListener("click", startMeeting);
document.getElementById("btn-finish").addEventListener("click", finishMeeting);
document.getElementById("btn-save-speakers").addEventListener("click", saveSpeakersAndGenerateReport);
document.getElementById("btn-download").addEventListener("click", downloadReport);
document.getElementById("btn-new-meeting").addEventListener("click", () => location.reload());
