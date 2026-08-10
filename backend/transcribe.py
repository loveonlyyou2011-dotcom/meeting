import json
import os
from pathlib import Path

from google import genai
from google.genai import types

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError(
        "환경변수 GEMINI_API_KEY가 설정되지 않았습니다. "
        "PowerShell: $env:GEMINI_API_KEY=\"발급받은키\""
    )

client = genai.Client(api_key=GEMINI_API_KEY)

MODEL = "gemini-flash-latest"

_MIME_BY_SUFFIX = {
    ".webm": "audio/webm",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".mp3": "audio/mp3",
    ".m4a": "audio/mp4",
}


def _mime_type(path: Path) -> str:
    return _MIME_BY_SUFFIX.get(path.suffix.lower(), "audio/webm")


def transcribe_chunk_plain(audio_path: Path) -> str:
    """회의 중 실시간 자막용: 화자 구분/타임스탬프 없이 빠르게 텍스트만 받아쓴다."""
    audio_bytes = audio_path.read_bytes()
    if not audio_bytes:
        return ""
    response = client.models.generate_content(
        model=MODEL,
        contents=[
            types.Part.from_bytes(data=audio_bytes, mime_type=_mime_type(audio_path)),
            "이 오디오를 한국어로 정확히 받아써줘. 다른 설명 없이 받아쓴 텍스트만 출력해. "
            "말소리가 없으면 빈 문자열을 출력해.",
        ],
    )
    return (response.text or "").strip()


def transcribe_full_with_timestamps(audio_path: Path) -> list[dict]:
    """회의 종료 후 전체 오디오에 대해 문장 단위 타임스탬프가 포함된 전사를 1회 수행한다."""
    audio_bytes = audio_path.read_bytes()
    prompt = (
        "이 회의 녹음 오디오 전체를 한국어로 받아써줘. "
        "발화를 문장 또는 자연스러운 어절 단위로 나누고, 각 구간의 시작/종료 시각(초, 오디오 처음부터 "
        "경과된 시간)을 함께 출력해. 다음 JSON 배열 형식으로만 응답하고 다른 텍스트는 출력하지 마: "
        '[{"start": 0.0, "end": 3.2, "text": "발화 내용"}, ...]'
    )
    response = client.models.generate_content(
        model=MODEL,
        contents=[
            types.Part.from_bytes(data=audio_bytes, mime_type=_mime_type(audio_path)),
            prompt,
        ],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    text = (response.text or "").strip()
    try:
        segments = json.loads(text)
    except json.JSONDecodeError:
        return []

    result = []
    for seg in segments:
        try:
            result.append(
                {
                    "start": float(seg["start"]),
                    "end": float(seg["end"]),
                    "text": str(seg["text"]).strip(),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return result
