from transcribe import client, MODEL


def _format_timestamp(seconds: float) -> str:
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def build_transcript_text(segments: list[dict], speaker_names: dict) -> str:
    lines = []
    for seg in segments:
        name = speaker_names.get(seg["speaker_label"], seg["speaker_label"])
        lines.append(f"[{_format_timestamp(seg['start_ts'])}] {name}: {seg['text']}")
    return "\n".join(lines)


def generate_report(meeting_title: str, segments: list[dict], speaker_names: dict) -> str:
    transcript_text = build_transcript_text(segments, speaker_names)
    if not transcript_text:
        return "# 회의록\n\n녹음된 발화 내용이 없습니다."

    prompt = (
        f"다음은 '{meeting_title}' 회의를 녹음해서 받아쓴 대화록이다. 화자 이름과 발화 시각이 "
        "타임스탬프로 표시되어 있다. 이 내용만을 근거로 한국어 회의록을 마크다운으로 작성해줘. "
        "대화록에 없는 내용은 절대 지어내지 마.\n\n"
        "다음 섹션을 이 순서로 포함해:\n"
        "## 참석자\n"
        "## 주요 논의사항 (안건/주제별로 불릿 정리)\n"
        "## 결정사항\n"
        "## 액션 아이템 (담당자와 기한이 대화록에 명시된 경우에만 표기하고, 없으면 '미정'이라고 표시)\n\n"
        "=== 대화록 ===\n"
        f"{transcript_text}"
    )

    response = client.models.generate_content(model=MODEL, contents=prompt)
    return (response.text or "").strip()
