# 회의록 자동 생성 프로그램 — 작업 요약 (2026-08-10)

## 만든 것

노트북 브라우저에서 회의를 녹음하면서 **실시간 자막**을 보여주고, 회의 종료 후
**화자별로 구분된 회의록**(참석자/논의사항/결정사항/액션아이템)을 자동 생성하는
웹앱. 전부 무료(Gemini API 무료 티어 + 오픈소스 pyannote.audio)로 동작하도록 설계.

## 아키텍처 핵심 결정

- **화자분리와 전사/요약의 역할 분리**: Gemini는 청크 단위로 화자 라벨을 일관되게
  유지하지 못하기 때문에, 화자분리(누가 언제 말했는가)는 `pyannote.audio`가 **회의
  종료 후 전체 오디오에 대해 1회만** 수행하고, 전사·요약은 Gemini가 담당한다.
- **실시간 자막은 Gemini Live API(WebSocket)**: 처음엔 15초 청크를 REST로 개별
  전사하는 방식(폴링, 15~25초 지연)으로 만들었다가, 지연을 줄이기 위해 Live API
  스트리밍으로 전환했다. 화자분리용 원본 오디오 확보(15초 webm 청크 업로드)는
  그대로 유지하고, 실시간 자막 표시만 Live API가 전담한다.
- **API 키는 항상 서버(백엔드)에만 보관**. 브라우저는 우리 FastAPI 서버와만 통신하고,
  Gemini와는 백엔드가 대신 연결한다.

## 프로젝트 구조

```
meeting-minutes/
  backend/
    main.py            # FastAPI 라우트, WebSocket 라우트
    storage.py          # SQLite (meetings, live_captions, segments, speakers, reports)
    transcribe.py        # Gemini REST 전사 (전체 타임스탬프 전사용)
    live_transcribe.py    # Gemini Live API 세션 관리 (실시간 자막)
    diarization.py       # pyannote.audio 화자분리 래퍼
    align.py             # 화자분리 ∩ 전사 시간축 정렬
    summarize.py          # Gemini 회의록 요약
    ffmpeg_util.py         # ffmpeg 경로 자동 탐색 (winget 설치 직후 PATH 미반영 대응)
    requirements.txt
  frontend/
    index.html / app.js / style.css / manifest.json
    pcm-worklet.js         # 마이크 오디오를 16kHz PCM16으로 변환 (AudioWorklet)
  data/                    # SQLite DB + 녹음 파일 (.gitignore 처리, 로컬에만 존재)
  .env / .env.example        # GEMINI_API_KEY, HF_TOKEN (.env는 gitignore 처리)
  README.md
```

## 이번 세션에서 겪은 주요 이슈와 해결

1. **의존성 버전 지옥** — 최신 `pyannote.audio`(4.x)가 추가 게이트 모델(HF 라이선스
   동의 필요)에 의존해 `pyannote.audio<4.0`으로 고정. 이어서 `torchaudio`/`torch`
   최신 버전이 pyannote가 쓰는 옛 API(`AudioMetaData`)를 제거해 `torch==2.2.2`,
   `torchaudio==2.2.2`로 고정. 그 여파로 `huggingface_hub<1.0`, `numpy<2`,
   `scipy<1.13`까지 순차적으로 고정해야 전체가 맞물려 동작했다. → **`requirements.txt`에
   전부 반영되어 있어 다음 설치부터는 이 과정을 반복하지 않는다.**
2. **ffmpeg PATH 미반영** — winget으로 설치 직후 같은 세션에서 PATH가 갱신되지 않는
   문제를 `ffmpeg_util.py`가 winget 설치 경로를 자동 탐색하는 방식으로 우회.
3. **HF 게이트 모델** — `pyannote/speaker-diarization-3.1`뿐 아니라 내부적으로 쓰는
   `pyannote/segmentation-3.0`도 별도 라이선스 동의가 필요했음(README에 안내 추가).
4. **`.env` 실수로 GitHub에 커밋된 사건** — GitHub 웹 UI에서 직접 `.env` 파일을
   올려 API 키가 공개 저장소에 노출됨. Hugging Face가 자동 탐지해 토큰을 강제
   만료시켰음. **두 키 모두 폐기 후 재발급**하고, `.env`를 git 추적에서 제거했다.
   (교훈: `.gitignore`는 로컬 git 명령에서만 작동하고, GitHub 웹 UI로 직접 파일을
   올리는 경우엔 적용되지 않는다.)
5. **녹음 중 발화 소실 버그** — 초기 구현은 "업로드+Gemini 전사 완료까지 기다린 뒤
   다음 녹음 시작" 구조라, 그 대기 시간 동안 마이크가 비어 발화가 소실됐다. 녹음
   재개를 업로드 완료와 분리해 끊김을 없앴다(`frontend/app.js`).
6. **Gemini Live API 모델 제약** — `response_modalities=["TEXT"]`는 지원하지 않고
   `["AUDIO"]`만 지원하는 모델이라 오류가 났음. 응답 오디오는 쓰지 않고
   `input_transcription`(사용자 발화 전사)만 사용하도록 수정.

## 회의록 저장 위치

- 서버가 실행되는 동안 `meeting-minutes/data/meetings.db`(SQLite)에 계속 누적 저장.
- 프론트엔드의 "다운로드 (.md)" 버튼으로 개별 회의록을 파일로 저장 가능 (보통 다운로드
  폴더에 저장됨).
- `data/`는 `.gitignore`에 있어 GitHub에는 올라가지 않는다.

## 무료 사용량 한도 (참고)

- Gemini Live API: 요청 횟수 한도 없음, **동시 세션 3개** 제한만 있음 (개인 순차
  사용에는 사실상 무제한).
- Gemini REST(회의 종료 시 전체 전사 + 요약, 총 2회/회의): 무료 티어 하루 1,500회
  한도 안에서 넉넉히 사용 가능.

## 다음 논의 중이던 것

- 로컬 PC를 켜지 않아도 접속 가능한 배포처 검토 중 — Oracle Cloud Always Free(2 OCPU/
  12GB RAM, ARM)가 유력 후보. 저가 VPS(월 $5~7)는 ARM 호환성 이슈 없이 더 간단한
  대안. 계정 생성/서버 발급은 사용자가 직접 해야 함.
