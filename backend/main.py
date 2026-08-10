import subprocess
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # transcribe.py/diarization.py가 import 시점에 환경변수를 읽으므로 가장 먼저 실행

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import align
import diarization
import storage
import summarize
import transcribe

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="회의록 자동 생성")
storage.init_db()


def _meeting_dir(meeting_id: str) -> Path:
    return DATA_DIR / meeting_id


def _require_meeting(meeting_id: str) -> dict:
    meeting = storage.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="회의를 찾을 수 없습니다.")
    return meeting


class CreateMeetingBody(BaseModel):
    title: str = "제목 없는 회의"


class SpeakerNamesBody(BaseModel):
    names: dict[str, str]


@app.post("/meetings")
def create_meeting(body: CreateMeetingBody):
    meeting_id = storage.create_meeting(body.title)
    (_meeting_dir(meeting_id) / "chunks").mkdir(parents=True, exist_ok=True)
    return {"meeting_id": meeting_id}


@app.post("/meetings/{meeting_id}/chunk")
def upload_chunk(meeting_id: str, audio: UploadFile = File(...)):
    _require_meeting(meeting_id)
    chunks_dir = _meeting_dir(meeting_id) / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    idx = len(storage.list_chunks(meeting_id))
    ext = Path(audio.filename or "chunk.webm").suffix or ".webm"
    dst = chunks_dir / f"chunk_{idx:03d}{ext}"
    dst.write_bytes(audio.file.read())
    storage.add_chunk(meeting_id, idx, str(dst))

    text = transcribe.transcribe_chunk_plain(dst)
    if text:
        storage.add_live_caption(meeting_id, idx, text)
    return {"chunk_index": idx, "text": text}


@app.get("/meetings/{meeting_id}/live")
def get_live_captions(meeting_id: str, after: int = 0):
    _require_meeting(meeting_id)
    rows = storage.get_live_captions_after(meeting_id, after)
    last_id = rows[-1]["id"] if rows else after
    return {"captions": rows, "cursor": last_id}


def _build_full_audio(meeting_id: str) -> Path:
    chunks = storage.list_chunks(meeting_id)
    if not chunks:
        raise HTTPException(status_code=400, detail="녹음된 오디오 청크가 없습니다.")

    meeting_dir = _meeting_dir(meeting_id)
    wav_dir = meeting_dir / "chunks_wav"
    wav_dir.mkdir(parents=True, exist_ok=True)

    wav_paths = []
    for c in chunks:
        src = Path(c["file_path"])
        dst = wav_dir / (src.stem + ".wav")
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(src), "-ar", "16000", "-ac", "1", str(dst)],
            check=True,
            capture_output=True,
        )
        wav_paths.append(dst)

    filelist = meeting_dir / "filelist.txt"
    filelist.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in wav_paths), encoding="utf-8"
    )
    full_path = meeting_dir / "full.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(filelist), "-c", "copy", str(full_path)],
        check=True,
        capture_output=True,
    )
    return full_path


@app.post("/meetings/{meeting_id}/finish")
def finish_meeting(meeting_id: str):
    _require_meeting(meeting_id)
    storage.update_meeting_status(meeting_id, "processing")

    full_path = _build_full_audio(meeting_id)
    diarization_segments = diarization.diarize(full_path)
    transcript_segments = transcribe.transcribe_full_with_timestamps(full_path)
    aligned = align.align(transcript_segments, diarization_segments)
    storage.save_segments(meeting_id, aligned)

    meeting_dir = _meeting_dir(meeting_id)
    samples = diarization.extract_speaker_samples(
        full_path, diarization_segments, meeting_dir / "samples"
    )
    labels = {s["speaker_label"] for s in aligned} | set(samples.keys())
    for label in labels:
        storage.upsert_speaker(meeting_id, label, str(samples.get(label)) if label in samples else None)

    storage.update_meeting_status(meeting_id, "diarized")
    return {"segments": aligned, "speakers": storage.get_speakers(meeting_id)}


@app.get("/meetings/{meeting_id}/speakers")
def list_speakers(meeting_id: str):
    _require_meeting(meeting_id)
    return {"speakers": storage.get_speakers(meeting_id)}


@app.get("/meetings/{meeting_id}/speakers/{label}/sample")
def get_speaker_sample(meeting_id: str, label: str):
    _require_meeting(meeting_id)
    for speaker in storage.get_speakers(meeting_id):
        if speaker["label"] == label and speaker["sample_path"]:
            path = Path(speaker["sample_path"])
            if path.exists():
                return FileResponse(path, media_type="audio/wav")
    raise HTTPException(status_code=404, detail="샘플 오디오를 찾을 수 없습니다.")


@app.post("/meetings/{meeting_id}/speakers")
def set_speaker_names(meeting_id: str, body: SpeakerNamesBody):
    _require_meeting(meeting_id)
    for label, name in body.names.items():
        storage.set_speaker_name(meeting_id, label, name)
    return {"speakers": storage.get_speakers(meeting_id)}


@app.post("/meetings/{meeting_id}/report")
def create_report(meeting_id: str):
    meeting = _require_meeting(meeting_id)
    segments = storage.get_segments(meeting_id)
    speakers = storage.get_speakers(meeting_id)
    speaker_names = {s["label"]: (s["display_name"] or s["label"]) for s in speakers}

    markdown = summarize.generate_report(meeting["title"], segments, speaker_names)
    storage.save_report(meeting_id, markdown)
    storage.update_meeting_status(meeting_id, "reported")
    return {"markdown": markdown}


@app.get("/meetings/{meeting_id}/report")
def get_report(meeting_id: str):
    _require_meeting(meeting_id)
    report = storage.get_report(meeting_id)
    if not report:
        raise HTTPException(status_code=404, detail="아직 회의록이 생성되지 않았습니다.")
    return JSONResponse(report)


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
