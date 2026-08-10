# 회의록 자동 생성 프로그램 (MVP)

노트북 브라우저로 회의를 녹음하면서 근실시간 자막을 보여주고, 회의 종료 후
화자를 구분한 정확한 회의록(참석자/논의사항/결정사항/액션아이템)을 자동 생성합니다.

## 아키텍처

- 화자 인식(누가 언제 말했는가)은 `pyannote.audio`로 **회의 종료 후 전체 녹음 파일에 대해 1회만** 수행합니다.
  청크 단위로 나눠 돌리면 화자 라벨이 청크마다 리셋되기 때문입니다.
- 전사(무슨 말을 했는가)와 회의록 요약은 Gemini API(`google-genai`)가 담당합니다.
- 회의 중에는 화자 라벨 없는 근실시간 자막만 보여주고, 종료 시점에 diarization과
  transcript를 시간축으로 정렬해 화자별 발화록을 만듭니다.

## 비용 — 완전 무료로 돌릴 수 있습니다

- **Gemini API(Google AI Studio)**: 신용카드 없이 무료 티어로 사용 가능합니다. 이 프로젝트가 쓰는
  Flash 모델은 무료 티어에서 하루 1,500회 요청 / 분당 15회 요청 한도를 제공하므로, 개인 회의
  용도로는 충분합니다. 다만 **무료 티어는 입력한 데이터가 구글의 서비스 개선에 사용될 수 있다는
  점**은 알아두세요(유료 티어는 이 조항이 없습니다) — 민감한 회의 내용이라면 유료 전환을 고려하세요.
- **pyannote.audio + ffmpeg**: 둘 다 오픈소스이며 로컬에서 실행되어 별도 비용이 없습니다.
  Hugging Face 계정과 토큰도 무료로 발급됩니다.

## 사전 준비물 (필수)

1. `.env.example`을 `.env`로 복사하고 값을 채워넣으세요.
   ```powershell
   cd meeting-minutes
   copy .env.example .env
   ```
   - **GEMINI_API_KEY**: [Google AI Studio](https://aistudio.google.com/apikey)에서 발급 (무료).
   - **HF_TOKEN**: https://huggingface.co/pyannote/speaker-diarization-3.1 에서 로그인 후
     라이선스 동의(Agree and access repository) → https://huggingface.co/settings/tokens 에서
     Read 권한 토큰 발급 (무료). 계정 로그인/약관 동의가 필요해 직접 진행하셔야 합니다.

   `.env`는 `.gitignore`에 포함되어 있어 깃허브에 올려도 커밋되지 않습니다.

2. **ffmpeg** — PATH에 설치되어 있어야 합니다 (청크 오디오 병합/변환용).
   ```powershell
   winget install Gyan.FFmpeg
   ```

## 설치 및 실행

```powershell
cd meeting-minutes/backend
pip install -r requirements.txt
uvicorn main:app --reload
```

브라우저에서 `http://localhost:8000` 접속 → 마이크 권한 허용 → "회의 시작".

## GitHub에 올리기

`data/`(녹음 파일 · SQLite DB)와 `.env`(API 키)는 `.gitignore`로 이미 제외되어 있어 실수로
커밋될 걱정은 없습니다. 이 프로젝트 폴더(`meeting-minutes/`)만 독립 저장소로 만드는 것을
권장합니다(상위 `파이썬` 폴더에는 다른 프로젝트의 토큰/키 파일이 섞여 있습니다).

```powershell
cd meeting-minutes
git init
git add .
git commit -m "Initial commit: meeting minutes MVP"
```

이후 GitHub에서 빈 저장소를 만들고 `git remote add origin <repo-url>` → `git push -u origin main`
으로 올리면 됩니다. 다른 사람이 클론해서 테스트할 때는 `.env.example`을 `.env`로 복사하고
자기 키를 채워넣기만 하면 됩니다.

## 알려진 제약

- pyannote 모델은 최초 실행 시 다운로드되며(수백MB), CPU 환경에서는 처리 속도가
  느릴 수 있습니다(1시간 회의 → 화자분리에 수 분 소요 가능). 회의 종료 후 1회만
  실행되므로 실시간 자막에는 영향이 없습니다.
- 화자 분리 정확도는 마이크 배치, 참석자 간 거리, 주변 잡음에 따라 달라집니다.
- 이번 MVP는 노트북(localhost) 기준으로 검증되었습니다. 폰에서 접속하려면 HTTPS
  또는 동일 네트워크 내 접근 구성이 추가로 필요합니다(후속 과제).
- Gemini 오디오 처리 비용: 회의 중 청크 라이브 전사 + 종료 시 전체 전사로 총
  2회 오디오를 처리하므로 API 사용량에 유의하세요.
