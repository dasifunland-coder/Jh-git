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

## 휴대폰 앱으로 쓰기

클립러닝은 홈 화면에 설치하는 웹앱(PWA)이에요. 설치하면 일반 앱처럼 아이콘으로 열리고, 안드로이드에서는 **유튜브 앱 → 공유 → 클립러닝**으로 영상을 바로 보낼 수 있어요. 공유하면 분석이 자동으로 시작돼요.

휴대폰 설치에는 **https 주소**가 필요해요. 방법은 두 가지예요.

**A. 집 컴퓨터 + Tailscale (추천, 무료)**
집 컴퓨터에서 서버를 켜 두고, 휴대폰에서 어디서든 접속해요. 집 인터넷이라 유튜브 차단도 거의 없어요.
1. 컴퓨터와 휴대폰에 Tailscale 앱을 설치하고 같은 계정으로 로그인
2. 컴퓨터에서 서버 실행 (`python app.py`)
3. 컴퓨터 터미널에서 `tailscale serve --bg 8000` → 나오는 `https://컴퓨터이름.….ts.net` 주소를 휴대폰에서 열기
   (명령은 Tailscale 버전에 따라 다를 수 있어요. 안 되면 Tailscale 문서의 "serve" 항목 참고)

**B. 인터넷 서버에 배포 (Render, Fly.io 등)**
Dockerfile로 올리면 https 주소가 자동으로 생겨요. 다만 유튜브가 클라우드 IP를 자주 막아 `YT_PROXY_URL`이 필요할 수 있고, 누구나 접속할 수 있으니 `APP_TOKEN`을 꼭 설정하세요.

**설치하기**
- 안드로이드(크롬): 주소를 열면 나오는 **설치** 버튼, 또는 메뉴(⋮) → 앱 설치
- 아이폰(사파리): 아래쪽 공유 버튼(□↑) → **홈 화면에 추가**
  아이폰은 유튜브 공유 목록에 웹앱이 뜨지 않아요. 유튜브에서 '링크 복사' 후 클립러닝의 **붙여넣기** 버튼을 누르세요.

## 비용 표시

분석이 끝나면 결과 화면에 `사용 비용 약 $0.27 (약 380원) · 분석 … · 튜터 …`가 나오고, 서버 창에도 `[비용] 학습 코스 생성: 입력 … / 출력 … 토큰 → 약 $…`가 찍혀요.
- 토큰 수는 Claude가 돌려준 실제 값이고, 금액은 공개 가격표(`course.py`의 `PRICES`)로 계산한 예상치예요. 정확한 청구 금액은 Anthropic 콘솔에서 확인하세요.
- 원화는 `.env`의 `USD_KRW` 환율(기본 1400)로 계산해요.
- 음성 인식(OpenAI) 비용은 포함되지 않아요.

## Obsidian에 깨알 정보 저장

학습 코스에는 영상 속 구체적인 숫자·사실·팁을 모은 **깨알 정보**가 들어 있어요. 결과 화면의 **Obsidian에 저장**을 누르면 이것만 모은 노트가 만들어져요 (영상 시점 링크, 태그 포함).

- **컴퓨터 보관함에 바로 저장 (추천):** `.env`에 `OBSIDIAN_VAULT=보관함 폴더 경로`를 넣고 서버를 다시 켜세요. 노트는 보관함 안 `클립러닝` 폴더(`OBSIDIAN_FOLDER`로 변경)에 써지고, 같은 영상을 다시 저장하면 그 노트를 새 내용으로 바꿔요. 휴대폰에서 눌러도 컴퓨터 보관함에 저장되고, Obsidian Sync 등으로 동기화하면 휴대폰에도 나타나요.
- **설정이 없을 때:** Obsidian 앱이 열리면서 새 노트로 만들어져요 (마지막으로 연 보관함).
- **노트 복사:** 마크다운을 복사해서 원하는 곳에 붙여넣을 수 있어요.

보관함 폴더 경로 찾기: Obsidian에서 아무 노트나 오른쪽 클릭 → **시스템 탐색기에서 보기** → 열린 탐색기 주소창의 경로(보관함 맨 위 폴더까지).

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
| `USD_KRW` | | 비용을 원화로 보여 줄 때 쓰는 환율, 기본 1400 (0이면 원화 표시 안 함) |
| `OBSIDIAN_VAULT` | | Obsidian 보관함 폴더 경로. 넣으면 서버가 노트를 바로 써요 |
| `OBSIDIAN_FOLDER` | | 보관함 안에서 노트를 모을 폴더, 기본 `클립러닝` |

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
