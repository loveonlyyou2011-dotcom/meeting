def _best_matching_speaker(segment: dict, diarization_segments: list[dict]) -> str:
    best_label = None
    best_overlap = 0.0
    for d in diarization_segments:
        overlap = min(segment["end"], d["end"]) - max(segment["start"], d["start"])
        if overlap > best_overlap:
            best_overlap = overlap
            best_label = d["speaker_label"]

    if best_label is not None:
        return best_label

    # 겹치는 구간이 없으면(짧은 침묵 경계 등) 가장 가까운 화자 구간으로 대체
    if not diarization_segments:
        return "SPEAKER_00"

    mid = (segment["start"] + segment["end"]) / 2
    nearest = min(
        diarization_segments,
        key=lambda d: min(abs(mid - d["start"]), abs(mid - d["end"])),
    )
    return nearest["speaker_label"]


def _merge_consecutive(segments: list[dict], gap_threshold: float = 1.0) -> list[dict]:
    merged: list[dict] = []
    for seg in segments:
        if (
            merged
            and merged[-1]["speaker_label"] == seg["speaker_label"]
            and seg["start"] - merged[-1]["end"] <= gap_threshold
        ):
            merged[-1]["end"] = seg["end"]
            merged[-1]["text"] = (merged[-1]["text"] + " " + seg["text"]).strip()
        else:
            merged.append(dict(seg))
    return merged


def align(transcript_segments: list[dict], diarization_segments: list[dict]) -> list[dict]:
    """타임스탬프가 포함된 전사 구간에 화자분리 결과를 시간 겹침 기준으로 붙인다."""
    aligned = [
        {
            "speaker_label": _best_matching_speaker(t, diarization_segments),
            "start": t["start"],
            "end": t["end"],
            "text": t["text"],
        }
        for t in transcript_segments
        if t["text"]
    ]
    return _merge_consecutive(aligned)
