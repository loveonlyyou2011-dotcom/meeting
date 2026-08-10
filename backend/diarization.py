import os
import subprocess
from functools import lru_cache
from pathlib import Path

from ffmpeg_util import resolve_ffmpeg

HF_TOKEN = os.environ.get("HF_TOKEN")
if not HF_TOKEN:
    raise RuntimeError(
        "환경변수 HF_TOKEN이 설정되지 않았습니다. "
        "huggingface.co에서 pyannote/speaker-diarization-3.1 라이선스에 동의하고 "
        "발급받은 토큰을 PowerShell에서 $env:HF_TOKEN=\"토큰\" 으로 설정하세요."
    )


@lru_cache(maxsize=1)
def _get_pipeline():
    from pyannote.audio import Pipeline

    return Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1", use_auth_token=HF_TOKEN
    )


def diarize(audio_path: Path) -> list[dict]:
    """전체 회의 오디오 파일에 대해 화자분리를 1회 수행한다."""
    pipeline = _get_pipeline()
    result = pipeline(str(audio_path))

    segments = []
    for turn, _, speaker in result.itertracks(yield_label=True):
        segments.append(
            {"speaker_label": speaker, "start": turn.start, "end": turn.end}
        )
    segments.sort(key=lambda s: s["start"])
    return segments


def extract_speaker_samples(
    audio_path: Path, segments: list[dict], out_dir: Path, max_seconds: float = 5.0
) -> dict:
    """화자별로 가장 긴 발화 구간을 짧게 잘라 재생용 샘플 클립을 만든다 (이름 매핑 UI용)."""
    longest: dict = {}
    for seg in segments:
        duration = seg["end"] - seg["start"]
        current = longest.get(seg["speaker_label"])
        if current is None or duration > current["duration"]:
            longest[seg["speaker_label"]] = {"start": seg["start"], "duration": duration}

    out_dir.mkdir(parents=True, exist_ok=True)
    samples = {}
    for label, info in longest.items():
        clip_len = max(0.5, min(info["duration"], max_seconds))
        out_path = out_dir / f"{label}.wav"
        subprocess.run(
            [
                resolve_ffmpeg(),
                "-y",
                "-ss",
                str(info["start"]),
                "-t",
                str(clip_len),
                "-i",
                str(audio_path),
                str(out_path),
            ],
            check=True,
            capture_output=True,
        )
        samples[label] = out_path
    return samples
