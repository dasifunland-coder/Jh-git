# 클립러닝 서버

유튜브 링크만 넣으면 서버가 스크립트를 구해 Claude로 학습 코스를 만들어요.

```
링크 ─▶ ① 유튜브 자막 (사람이 만든 자막 > 자동 자막, 한국어 > 영어 > 기타)
         │  없으면
         ▼
        ② yt-dlp로 오디오만 받기 → ffmpeg로 3분 조각 → OpenAI 음성 인식 (4개씩 동시에)
         │
         ▼
        ③ Claude가 학습 코스 생성 (JSON) ─▶ 앱 화면
```

- 대부분의 영상은 ①에서 끝나서 음성 인식 비용이 들지 않아요.
- Claude·OpenAI API 키는 서버에만 있고, 브라우저로 내려가지 않아요.
- 이 서버가 띄운 화면(`http://localhost:8000`)은 자동으로 **서버 모드**가 돼요. `index.html`을 파일로 바로 열면 이전처럼 브라우저 모드(API 키 직접 입력)로 동작해요.

## 실행

준비물: Python 3.10 이상, ffmpeg (`brew install ffmpeg` / `sudo apt install ffmpeg`)

```bash
cd youtube-learn/server
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # ANTHROPIC_API_KEY, OPENAI_API_KEY 채우기
python app.py               # http://127.0.0.1:8000 접속
```

Docker로 실행하려면 `youtube-learn` 폴더에서:

```bash
docker build -t cliplearn .
docker run -p 8000:8000 --env-file server/.env cliplearn
```

## 설정 (`.env`)

| 이름 | 필수 | 설명 |
|---|---|---|
| `ANTHROPIC_API_KEY` | 예 | 학습 코스를 만드는 Claude API 키 |
| `OPENAI_API_KEY` | 아니요 | 자막 없는 영상의 음성 인식용. 없으면 자막 있는 영상만 분석 |
| `STT_MODEL` | | 기본 `gpt-transcribe`. 아래 참고 |
| `STT_CHUNK_SECONDS` | | 오디오 조각 길이(초), 기본 180 |
| `MAX_STT_MINUTES` | | 음성 인식을 허용할 최대 영상 길이(분), 기본 90. 비용 보호용 |
| `CLAUDE_MODEL` | | 기본 `claude-opus-5-5` |
| `APP_TOKEN` | 공개 배포 시 | 접속 암호. 화면에서 한 번 입력하면 브라우저에 저장돼요 |
| `ALLOWED_ORIGINS` | | 앱 화면을 다른 주소에서 띄울 때만 (쉼표 구분) |
| `YT_PROXY_URL`, `YTDLP_COOKIES` | | 유튜브가 서버 IP를 막을 때 프록시와 쿠키 파일 |

### 음성 인식 모델 고르기

| 모델 | 타임스탬프 | 비고 |
|---|---|---|
| `gpt-transcribe` (기본) | 3분 조각 단위 | OpenAI의 최신 음성 인식 모델 |
| `whisper-1` | 문장 단위 (챕터 이동이 더 정확) | **2027-02-26 종료 예정** (OpenAI SDK 안내 기준) |

기존 Whisper 계열(`whisper-1`, `gpt-4o-transcribe`, `gpt-4o-mini-transcribe`)은 모두 2027-02-26에 종료된다고 OpenAI SDK에 표시되어 있어서 기본값을 `gpt-transcribe`로 정했어요. `gpt-transcribe`에서 타임스탬프 간격을 더 촘촘히 하려면 `STT_CHUNK_SECONDS`를 줄이세요 (요청 수는 늘어나요).

## API

| 경로 | 설명 |
|---|---|
| `GET /api/health` | 서버 모드 여부, 음성 인식 가능 여부, 접속 암호 필요 여부 |
| `POST /api/analyze` | `{url, transcript?, level, minutes}` → NDJSON 스트림: `stage` → `progress` → `result` 또는 `error` |
| `POST /api/ask` | `{title, transcript, level, history, question}` → 튜터 답변 텍스트 스트림 |

## 테스트

외부 API 없이 돌아가요 (유튜브·OpenAI·Claude는 가짜로 바꾸고, ffmpeg 분할만 실제로 실행).

```bash
pip install -r requirements-dev.txt
pytest
```

## 알아둘 점

- **유튜브 차단:** 클라우드 서버(AWS, GCP 등) IP는 유튜브가 자막·오디오 요청을 자주 막아요. 집 PC에서 돌리면 대개 문제없고, 서버에 올릴 때는 `YT_PROXY_URL`(주거용 프록시)이나 `YTDLP_COOKIES`가 필요할 수 있어요.
- **약관:** 유튜브 약관은 영상·오디오 내려받기를 원칙적으로 금지해요. 개인 학습용 범위를 넘어 서비스로 운영하려면 법률 검토가 필요해요. 자막만 쓰는 ①단계는 다운로드가 없어요.
- **비용:** 음성 인식은 자막이 없는 영상에만 쓰이고 `MAX_STT_MINUTES`로 길이를 제한해요. 공개 배포할 땐 `APP_TOKEN`을 꼭 설정하세요.
